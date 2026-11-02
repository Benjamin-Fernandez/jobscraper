"""Questions from applications: capture, grouping and naming (questions_design §4-§5, F-13, D-74).

When an attempt stops on a required field that no resolver tier could answer,
the owner should see that question once, answer it once, and never be asked
again. This module decides, without touching a store or a log:

  - which unanswered fields are worth asking the owner about, and why
    (`capture`, §4.2): a profile gap, an option that does not fit, an
    attestation the classifier could not settle, a D-75 work-rights conflict,
    an answer the model could not ground, or simply no rule;
  - which earlier question a new one is the same as (`signature`, §5.1) and
    which key its answer is saved under in `data/applicant.yaml` `extra:`
    (`assign_key`, §5.2): a profile path, an existing key, the local model's
    suggestion, or a deterministic slug.

The model only names and groups (§5.3). It never answers, never sees a
profile value or an answer, never sees a sensitive question, and every reply
is re-checked here; anything off falls back to the slug. apply_flow (WP-Q1b)
does the store writes and the logging; the backend is handed in, as the
resolver's is.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

from .. import applicant
from ..backends import BackendError, OffBackend
from . import declarations, resolve
from .contracts import (
    EMPLOYER_SPECIFIC_DECLARATIONS, EXTRA_KEY_PATTERN, Answer, AnswerStatus, Canonical,
    CapturedQuestion, FieldType, FormField, QuestionKind, QuestionReason, ResolveContext,
)
from .plan import STOP_WORDS as _PLAN_STOP_WORDS, norm_label, qualified_label

LABEL_MAX = 300
DESCRIPTION_MAX = 300
OPTIONS_MAX = 50
NOTE_MAX = 300
TITLE_MAX = 60

EXTRA_KEY_RE = re.compile(EXTRA_KEY_PATTERN)

# Tier-1 canonicals whose value lives at a profile path (§4.2). Others have none.
CANONICAL_PATHS: dict[Canonical, str] = {
    Canonical.FIRST_NAME: "identity.legal_first_name",
    Canonical.LAST_NAME: "identity.legal_last_name",
    Canonical.PREFERRED_NAME: "identity.preferred_name",
    Canonical.ADDRESS_LINE1: "contact.address_line1",
    Canonical.ADDRESS_LINE2: "contact.address_line2",
    Canonical.CITY: "contact.city",
    Canonical.POSTAL_CODE: "contact.postal_code",
    Canonical.PHONE: "contact.phone_number",
    Canonical.PHONE_COUNTRY_CODE: "contact.phone_country_code",
    Canonical.COUNTRY: "contact.country",
    Canonical.LOCATION: "contact.city",
    Canonical.LINKEDIN: "links.linkedin",
    Canonical.GITHUB: "links.github",
    Canonical.PORTFOLIO: "links.portfolio",
    Canonical.HOW_HEARD: "sourcing.how_heard_default",
    Canonical.EEO_GENDER: "us_self_id.eeo_gender",
    Canonical.EEO_RACE: "us_self_id.eeo_race_ethnicity",
    Canonical.EEO_VETERAN: "us_self_id.veteran_status",
    Canonical.EEO_DISABILITY: "us_self_id.disability_status",
}

UNANSWERED = frozenset({AnswerStatus.UNKNOWN, AnswerStatus.UNGROUNDED})
NOT_CAPTURED_TYPES = frozenset({FieldType.FILE, FieldType.HIDDEN})


# --------------------------------------------------------------------------
# Kind (§4.2)
# --------------------------------------------------------------------------

def kind_for(f: FormField) -> QuestionKind:
    """The widget the owner answers with: a single checkbox or a Yes/No choice
    -> yes_no; dropdown/radio -> choice; multi-select -> multi; date; number;
    anything typed -> text."""
    if f.type is FieldType.CHECKBOX or resolve.bool_shaped(f):
        return QuestionKind.YES_NO
    if f.type in (FieldType.DROPDOWN, FieldType.RADIO):
        return QuestionKind.CHOICE
    if f.type is FieldType.MULTI_CHOICE:
        return QuestionKind.MULTI
    if f.type is FieldType.DATE:
        return QuestionKind.DATE
    if f.type is FieldType.NUMBER:
        return QuestionKind.NUMBER
    return QuestionKind.TEXT


# --------------------------------------------------------------------------
# Capture (§4.2)
# --------------------------------------------------------------------------

def _form_targets() -> frozenset[str]:
    """Profile paths the form edits: every FORM item, and each entries
    sub-field of the first entry ("education[0].grade")."""
    out: set[str] = set()
    for g in applicant.FORM:
        for it in g.items:
            out.add(it.path)
            out.update(f"{it.path}[0].{s.path}" for s in it.sub)
    return frozenset(out)


def form_label(path: str) -> str:
    """The Profile form's label for a path ("contact.city" -> "City"), "" if none."""
    for g in applicant.FORM:
        for it in g.items:
            if it.path == path:
                return it.label
            for s in it.sub:
                if path == f"{it.path}[0].{s.path}":
                    return f"{it.label}: {s.label}"
    return ""


def _empty(v: Any) -> bool:
    """No usable value. A salary whose amount is 0 is the template's "not
    filled yet" (applicant.missing_for_apply)."""
    if isinstance(v, dict) and "amount" in v:
        return not v.get("amount")
    return v is None or v == [] or v == {} or (isinstance(v, str) and not v.strip())


def _has_value(profile: dict, path: str) -> bool:
    if path in resolve.COUNTRY_BOOL_KEYS:       # D-75: always answerable (work_rights)
        return True
    return not _empty(resolve.profile_value(profile, path))


def _profile_key(rule_id: str, rule_keys: Mapping[str, Any]) -> str:
    """The profile path a tier-2 rule_id names: a questions.yaml key, a
    virtual "<key>#<id>" read as its parent; "" for anything else (a
    declaration label, llm:v1, computed.*)."""
    key = (rule_id or "").split("#", 1)[0]
    if not key or (rule_id not in rule_keys and key not in rule_keys):
        return ""
    return "" if key.startswith("computed.") else key


def _reason(f: FormField, a: Answer, ctx: ResolveContext, rule_keys: Mapping[str, Any],
            declaration: Any) -> tuple[QuestionReason, str]:
    """(reason, target_path) per the §4.2 table. A D-75 conflict is checked
    first: its rule_id names a work-rights map, which always has a value."""
    if a.note.startswith(resolve.WORK_RIGHTS_CONFLICT):
        return QuestionReason.CONFLICT, ""
    profile = ctx.profile or {}
    if f.canonical in CANONICAL_PATHS:
        path = CANONICAL_PATHS[f.canonical]
        if _has_value(profile, path):
            return QuestionReason.NO_OPTION_FITS, ""
        return QuestionReason.PROFILE_GAP, path
    key = _profile_key(a.rule_id, rule_keys)
    if key:
        if _has_value(profile, key):
            return QuestionReason.NO_OPTION_FITS, ""
        if key in _form_targets():
            return QuestionReason.PROFILE_GAP, key
    if declaration is not None and a.status is AnswerStatus.UNKNOWN:
        return QuestionReason.ATTESTATION_UNCLEAR, ""
    if a.status is AnswerStatus.UNGROUNDED:
        return QuestionReason.UNGROUNDED, ""
    return QuestionReason.NO_RULE, ""


def capture(fields: Sequence[FormField], answers: Mapping[str, Answer], ctx: ResolveContext,
            rules: resolve.QuestionRules) -> list[CapturedQuestion]:
    """Every required field left `unknown`/`ungrounded` that the owner can
    answer, in field order (§4.2). Not captured: optional fields, files,
    hidden inputs, and declarations about this employer (tier 4 owns those;
    an unknown there is a real stop)."""
    rule_keys = {r.key: r for r in rules.rules}
    employer = declarations.employer_norm(ctx.employer_name or "")
    out: list[CapturedQuestion] = []
    for f in fields:
        a = answers.get(f.key)
        if a is None or not f.required or a.status not in UNANSWERED \
                or f.type in NOT_CAPTURED_TYPES:
            continue
        label_norm = norm_label(f.label)
        decl = declarations.classify(label_norm, norm_label(f.description))
        if decl in EMPLOYER_SPECIFIC_DECLARATIONS:
            continue
        reason, target = _reason(f, a, ctx, rule_keys, decl)
        rule = rule_keys.get(a.rule_id) or rule_keys.get((a.rule_id or "").split("#", 1)[0])
        sensitive = bool(a.sensitive or (rule is not None and rule.sensitive)
                         or reason is QuestionReason.ATTESTATION_UNCLEAR
                         or f.canonical in resolve.SENSITIVE_CANONICALS
                         or (target and applicant.is_sensitive(target)))
        options = tuple(o.label for o in f.options[:OPTIONS_MAX])
        out.append(CapturedQuestion(
            label=f.label[:LABEL_MAX], label_norm=label_norm, kind=kind_for(f),
            reason=reason, field_key=f.key, field_type=f.type, required=True,
            sensitive=sensitive, description=(f.description or "")[:DESCRIPTION_MAX],
            options=options, option_norms=tuple(norm_label(o) for o in options),
            target_path=target, step=f.step, ats=ctx.ats, employer_norm=employer,
            note=(a.note or "")[:NOTE_MAX]))
    return out


# --------------------------------------------------------------------------
# Capture from the page (D-78; llm_fill_design §11, §12.1; WP-M5)
# --------------------------------------------------------------------------

# Notes pagefill gives fields left unknown by a transport failure (BackendError, a
# timeout, a reply still cut or malformed): the attempt ends model_unavailable and
# nothing is captured (§11), so these are skipped even if they reach capture_page.
TRANSPORT_NOTES = ("transport", "model: unavailable", "model_unavailable")
_TAG = re.compile(r"^(G\d+|L\d+|E\d+)")
_INDEX = re.compile(r"\[\d+\]")

# D-86 interim (review F9): until a compose WP exists (Q-45), a required cover letter or
# "why join" text the program can't fill stops the attempt and is captured per job with
# reason `compose_needed`, so the owner sees why. contracts v5 has no such QuestionReason
# yet (requested from the architect); until it lands the row says `no_rule` and the
# note starts "compose_needed".
try:
    COMPOSE_NEEDED = QuestionReason("compose_needed")
except ValueError:
    COMPOSE_NEEDED = QuestionReason.NO_RULE
COMPOSE_NOTE = "compose_needed"
_COVER = re.compile(r"\bcover\s*letter\b|\bmotivation(al)?\s+letter\b", re.I)
_MOTIVE = re.compile(r"\bwhy\b.{0,60}\b(join|work|apply|applying|interested|want|choose|chose)\b"
                     r"|\bmotivat(e|es|ed|ion)\b|\bwhat\s+(interests|attracts|excites)\s+you\b",
                     re.I | re.S)


def compose_needed(f: FormField, group: str = "") -> bool:
    """A text only a compose step could write: a cover-letter upload, or a free-text
    cover letter / motivation question outside repeated entries."""
    text = f"{f.label} {f.description}"
    if f.type is FieldType.FILE:
        return bool(_COVER.search(text))
    return f.type is FieldType.TEXTAREA and not group and bool(
        _COVER.search(text) or _MOTIVE.search(f.label))


def _compose_label(f: FormField, ctx: ResolveContext) -> str:
    """Per job: the employer and a hash of the posting, so one job's answer is never
    matched on another (a cover letter names its employer)."""
    job = hashlib.sha256((ctx.jd_text or "").encode("utf-8")).hexdigest()[:8]
    return (f"{norm_label(f.label)} | compose @"
            f"{declarations.employer_norm(ctx.employer_name or '') or 'employer'}#{job}")


def _gap_target(path: str) -> str:
    """A G2 profile_gap's rule_id as a target path: a path the Profile form edits
    (list entries by any index: "experience[1].location"), else ""."""
    if not path or ":" in path:
        return ""
    return path if _INDEX.sub("[0]", path) in _form_targets() else ""


def _rule_gap(f: FormField, ctx: ResolveContext, rules: Any) -> str:
    """The empty profile path the unique tier-2 row for this label names, else "". The
    model never sees an empty non-private fact (§5.1), so it says "unknown" where the
    old tier 2 saw a profile gap; the owner's answer still belongs in the profile."""
    if rules is None or not getattr(rules, "rules", None):
        return ""
    best, _score = rules.select(norm_label(f.label), f)
    if len(best) != 1:
        return ""
    r = best[0]
    key = r.parent if getattr(r, "is_virtual", False) else r.key
    if not key or key.startswith("computed.") or key not in _form_targets():
        return ""
    return "" if _has_value(ctx.profile or {}, key) else key


def page_reason(f: FormField, a: Answer, ctx: ResolveContext, rule_keys: Mapping[str, Any],
                declaration: Any, rules: Any = None) -> tuple[QuestionReason, str]:
    """(reason, target_path) from the guard or lock that left the field unknown (§11):
    G2 profile_gap / no_option_fits (G2d, G2e); L3, L7 attestation_unclear; L4 conflict;
    G3, G6, G11 ungrounded; any other guard no_rule. A model "unknown" (or a G2a/G2b
    reject) whose label the unique tier-2 row maps to an empty profile path is a
    profile_gap with that target. A lock answer from the resolver's own rules (L5
    no-fit, L3 ambiguous, the D-75 conflict note) keeps `_reason`."""
    note = a.note or ""
    m = _TAG.match(note)
    tag = m.group(1) if m else ""
    if note.startswith(resolve.WORK_RIGHTS_CONFLICT) or tag == "L4":
        return QuestionReason.CONFLICT, ""
    if tag == "G2":
        if "profile_gap" in note:
            target = _gap_target(a.rule_id)
            return (QuestionReason.PROFILE_GAP, target) if target else (QuestionReason.NO_RULE, "")
        if note.startswith(("G2d", "G2e")):
            return QuestionReason.NO_OPTION_FITS, ""
    if tag in ("", "G2") and (note.startswith(("model:", "G2a", "G2b")) or not note):
        gap = _rule_gap(f, ctx, rules)
        if gap:
            return QuestionReason.PROFILE_GAP, gap
        return QuestionReason.NO_RULE, ""
    if tag == "G2":
        return QuestionReason.NO_RULE, ""
    if tag in ("L3", "L7"):
        return QuestionReason.ATTESTATION_UNCLEAR, ""
    if tag in ("G3", "G6", "G11"):
        return QuestionReason.UNGROUNDED, ""
    if tag.startswith(("G", "E")):
        return QuestionReason.NO_RULE, ""
    return _reason(f, a, ctx, rule_keys, declaration)


def capture_page(fields: Sequence[Any], answers: Mapping[str, Answer], ctx: ResolveContext,
                 rules: resolve.QuestionRules) -> list[CapturedQuestion]:
    """`capture` for the D-78 page (one capture point: the page stop, §11). `fields` are
    `PageField`s; `label_norm` is the qualified label (§12.1: a generic label carries its
    help text or context, else its place on the step), so "Please specify" after two
    different questions are two questions, and the saved answer matches only where it
    was asked. A required cover letter / "why join" text is captured per job with reason
    `compose_needed` (D-86 interim), a cover-letter upload included. Not captured:
    optional fields, other files, hidden inputs, employer-specific declarations, and
    fields left unknown by a transport failure."""
    rule_keys = {r.key: r for r in getattr(rules, "rules", ()) or ()}
    employer = declarations.employer_norm(ctx.employer_name or "")
    forms = [pf.field for pf in fields]
    ords = resolve.generic_ordinals(forms)
    out: list[CapturedQuestion] = []
    for pf in fields:
        f = pf.field
        a = answers.get(f.key)
        if a is None or not f.required or a.status not in UNANSWERED \
                or (a.note or "").lower().startswith(TRANSPORT_NOTES):
            continue
        if compose_needed(f, pf.group):
            out.append(CapturedQuestion(
                label=f.label[:LABEL_MAX], label_norm=_compose_label(f, ctx),
                kind=QuestionKind.TEXT, reason=COMPOSE_NEEDED, field_key=f.key,
                field_type=f.type, required=True, sensitive=False,
                description=(f.description or "")[:DESCRIPTION_MAX], step=f.step,
                ats=ctx.ats, employer_norm=employer,
                note=f"{COMPOSE_NOTE}: {a.note or ''}"[:NOTE_MAX]))
            continue
        if f.type in NOT_CAPTURED_TYPES:
            continue
        decl = declarations.classify(norm_label(f.label), norm_label(f.description))
        if decl in EMPLOYER_SPECIFIC_DECLARATIONS:
            continue
        label_norm = qualified_label(f.label, f.description, pf.context, step=f.step,
                                     ordinal=ords.get(f.key, 0))
        reason, target = page_reason(f, a, ctx, rule_keys, decl, rules)
        rule = rule_keys.get(a.rule_id) or rule_keys.get((a.rule_id or "").split("#", 1)[0])
        sensitive = bool(a.sensitive or (rule is not None and rule.sensitive)
                         or reason is QuestionReason.ATTESTATION_UNCLEAR
                         or f.canonical in resolve.SENSITIVE_CANONICALS
                         or (target and applicant.is_sensitive(target))
                         or (a.note or "").startswith("G7"))
        options = tuple(o.label for o in f.options[:OPTIONS_MAX]) \
            if f.type is not FieldType.DATE else ()
        out.append(CapturedQuestion(
            label=f.label[:LABEL_MAX], label_norm=label_norm, kind=kind_for(f),
            reason=reason, field_key=f.key, field_type=f.type, required=True,
            sensitive=sensitive, description=(f.description or "")[:DESCRIPTION_MAX],
            options=options, option_norms=tuple(norm_label(o) for o in options),
            target_path=target, step=f.step, ats=ctx.ats, employer_norm=employer,
            note=(a.note or "")[:NOTE_MAX]))
    return out


# --------------------------------------------------------------------------
# Equivalent questions (§5.1)
# --------------------------------------------------------------------------

def signature(q: Union[CapturedQuestion, QuestionKind, str], label_norm: Optional[str] = None,
              option_norms: Iterable[str] = ()) -> str:
    """sha256(kind \\n label_norm \\n sorted option norms)[:16]: the same
    question asked with its options in another order is the same row.
    Call with a CapturedQuestion, or with (kind, label_norm, option_norms)."""
    if isinstance(q, CapturedQuestion):
        kind, label_norm, option_norms = q.kind, q.label_norm, q.option_norms
    else:
        kind = q
    k = kind.value if isinstance(kind, QuestionKind) else str(kind)
    text = k + "\n" + (label_norm or "") + "\n" + "\n".join(sorted(option_norms))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# Keys (§5.2)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ExistingKey:
    """A key already in use: an `extra` entry, or a group in the `questions` table."""
    key: str
    title: str
    kind: str
    sensitive: bool = False
    labels: frozenset[str] = frozenset()     # normalised labels that mean it
    description: str = ""
    in_extra: bool = False


@dataclass(frozen=True)
class KeyChoice:
    """Where a new question's answer goes, and what the owner reads."""
    key: str
    title: str
    description: str = ""
    named_by: str = "rule"                   # rule | model | profile


ExistingLike = Union[ExistingKey, Sequence[Any], Mapping[str, Any]]


def as_existing(x: ExistingLike) -> ExistingKey:
    """An ExistingKey from itself, a (key, title, kind, sensitive) tuple
    (store.question_keys()), or a questions-row dict."""
    if isinstance(x, ExistingKey):
        return x
    if isinstance(x, Mapping):
        labels = x.get("labels") or ([x["label_norm"]] if x.get("label_norm") else [])
        return ExistingKey(str(x["key"]), str(x.get("title") or x["key"]), str(x.get("kind") or ""),
                           bool(x.get("sensitive")), frozenset(norm_label(s) for s in labels),
                           str(x.get("description") or ""))
    key, title, kind, sensitive = (list(x) + [None, None, None])[:4]
    return ExistingKey(str(key), str(title or key), str(kind or ""), bool(sensitive))


def existing_keys(extra: Optional[Mapping[str, Any]] = None,
                  rows: Sequence[Mapping[str, Any]] = ()) -> list[ExistingKey]:
    """The keys in use, newest first: `extra` entries (the file appends, so
    reversed), then `questions` rows (store.question_rows(), newest first).
    One ExistingKey per key, its labels merged."""
    found: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    def add(key: str, title: str, kind: str, sensitive: bool, labels: Iterable[str],
            description: str, in_extra: bool) -> None:
        if key not in found:
            order.append(key)
            found[key] = {"title": title, "kind": kind, "sensitive": sensitive,
                          "labels": set(), "description": description, "in_extra": in_extra}
        e = found[key]
        e["sensitive"] = e["sensitive"] or sensitive
        e["labels"].update(norm_label(x) for x in labels if isinstance(x, str))

    for key, entry in reversed(list((extra or {}).items())):
        if isinstance(key, str) and isinstance(entry, dict):
            add(key, str(entry.get("title") or key), str(entry.get("kind") or ""),
                entry.get("sensitive") is True, entry.get("labels") or [],
                str(entry.get("description") or ""), True)
    for r in rows:
        add(str(r["key"]), str(r.get("title") or r["key"]), str(r.get("kind") or ""),
            bool(r.get("sensitive")), [r.get("label_norm") or ""],
            str(r.get("description") or ""), False)
    return [ExistingKey(k, found[k]["title"], found[k]["kind"], found[k]["sensitive"],
                        frozenset(x for x in found[k]["labels"] if x),
                        found[k]["description"], found[k]["in_extra"]) for k in order]


# questions_design §5.2 stop words; one table, kept in plan.py (plan.is_generic reads it too).
STOP_WORDS = _PLAN_STOP_WORDS


def _kind_value(kind: Any) -> str:
    return kind.value if isinstance(kind, QuestionKind) else str(kind or "")


def slug_key(label_norm: str, existing: Iterable[Union[ExistingKey, str]] = (),
             kind: Any = "") -> str:
    """The deterministic key (§5.2 rule 5): the label's first 4 tokens that
    are not stop words, joined with "_", [a-z0-9_] only, at most 40
    characters, a letter first ("q_" otherwise), "question" when nothing is
    left. A key already used for another label or kind gets _2, _3, ..."""
    toks = [re.sub(r"[^a-z0-9_]", "", t) for t in label_norm.split() if t not in STOP_WORDS]
    base = "_".join([t for t in toks if t][:4])
    base = re.sub(r"_+", "_", base).strip("_")[:40].rstrip("_") or "question"
    if not base[0].isalpha() or len(base) < 2:
        base = ("q_" + base)[:40].rstrip("_")
    k = _kind_value(kind)
    taken: dict[str, Optional[ExistingKey]] = {}
    for e in existing:
        if isinstance(e, ExistingKey):
            taken[e.key] = e
        else:
            taken[str(e)] = None

    def free(name: str) -> bool:
        e = taken.get(name, False)
        if e is False:
            return True
        return e is not None and e.kind == k and label_norm in e.labels

    if free(base):
        return base
    n = 2
    while True:
        suffix = f"_{n}"
        name = base[:40 - len(suffix)].rstrip("_") + suffix
        if free(name):
            return name
        n += 1


def short_title(label: str) -> str:
    """The verbatim label as a title: at most 60 characters, cut at a word."""
    t = " ".join((label or "").split())
    if len(t) <= TITLE_MAX:
        return t
    cut = t[:TITLE_MAX + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut or t[:TITLE_MAX]


# --------------------------------------------------------------------------
# Naming by the local model (§5.3): names and groups, never answers
# --------------------------------------------------------------------------

NAMING_SYSTEM = """You name a question from a job application form so it can be saved as a field in the applicant's profile.
You never answer the question. Reply with JSON only.
key: a short snake_case name for what is asked (for example visa_status, notice_period, gpa).
title: a short label a person would read (at most 6 words).
description: one sentence saying what the field holds (at most 25 words).
same_as: the key of an EXISTING FIELD that asks for the same fact, or "" if none does."""

NAMING_SCHEMA = {"type": "object", "properties": {
    "key": {"type": "string", "pattern": "^[a-z][a-z0-9_]{1,39}$"},
    "title": {"type": "string", "maxLength": 60},
    "description": {"type": "string", "maxLength": 160},
    "same_as": {"type": "string", "maxLength": 40}},
    "required": ["key", "title", "description", "same_as"]}

NAMING_OPTIONS_MAX = 20
NAMING_EXISTING_MAX = 50
NAMING_MAX_TOKENS = 200
NAMING_SEED = 7


def naming_candidates(existing: Sequence[ExistingLike]) -> list[ExistingKey]:
    """What the prompt may list: non-sensitive `extra` keys (never a profile
    path, never a sensitive one), newest first, at most 50."""
    keys = [as_existing(x) for x in existing]
    return [e for e in keys
            if not e.sensitive and EXTRA_KEY_RE.match(e.key)][:NAMING_EXISTING_MAX]


def naming_user_prompt(q: CapturedQuestion, existing: Sequence[ExistingLike] = ()) -> str:
    """The question's own text and the keys already in use. Nothing from the
    profile, no answer and no employer name (§5.3). `existing` = ExistingKeys,
    (key, title, kind, sensitive) tuples or questions-row dicts."""
    lines = [f"QUESTION: {q.label}", f"HELP: {q.description}", f"TYPE: {_kind_value(q.kind)}",
             "OPTIONS:"]
    lines += [f"- {o}" for o in q.options[:NAMING_OPTIONS_MAX]]
    lines += ["", "EXISTING FIELDS:"]
    lines += [f"- {e.key}: {e.title} ({e.kind})" for e in naming_candidates(existing)]
    return "\n".join(lines)


def parse_naming(reply: Any, existing: Sequence[ExistingLike],
                 q: CapturedQuestion) -> Optional[KeyChoice]:
    """The model's reply (JSON text or a dict), re-checked (§5.3): None (use
    the slug) for a reply that is not the JSON asked for, a key outside the
    pattern, or a key that another kind (or a sensitive question) already
    holds. `same_as` joins a listed key of the same kind; any other `same_as`
    is ignored. An empty title becomes the question's label."""
    if isinstance(reply, str):
        try:
            reply = json.loads(reply)
        except (TypeError, ValueError):
            return None
    if not isinstance(reply, dict):
        return None
    kind = _kind_value(q.kind)
    keys = [as_existing(x) for x in existing]
    by_key = {e.key: e for e in keys}
    listed = {e.key: e for e in naming_candidates(keys)}
    title = reply.get("title")
    title = (title.strip()[:TITLE_MAX] if isinstance(title, str) and title.strip()
             else short_title(q.label))
    desc = reply.get("description")
    desc = " ".join(desc.split())[:160] if isinstance(desc, str) else ""
    same = reply.get("same_as")
    if isinstance(same, str) and same in listed and listed[same].kind == kind:
        e = listed[same]
        return KeyChoice(e.key, e.title, e.description, "model")
    key = reply.get("key")
    if not isinstance(key, str) or not EXTRA_KEY_RE.match(key):
        return None
    held = by_key.get(key)
    if held is not None:
        if held.kind != kind or held.sensitive:
            return None
        return KeyChoice(held.key, held.title, held.description, "model")
    return KeyChoice(key, title, desc, "model")


def can_name(backend: Any) -> bool:
    """A model may be asked: a backend that is not OffBackend and is up."""
    if backend is None or isinstance(backend, OffBackend):
        return False
    try:
        return bool(getattr(backend, "available", False))
    except Exception:                     # a probe that fails is "not available"
        return False


def _accepts_timeout(backend: Any) -> bool:
    try:
        params = inspect.signature(backend.complete).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == "timeout" or p.kind is p.VAR_KEYWORD for p in params)


def ask_model(backend: Any, q: CapturedQuestion, existing: Sequence[ExistingLike] = (),
              timeout: Optional[float] = None) -> Optional[str]:
    """One naming call (§5.3), for apply_flow: `complete(NAMING_SYSTEM, user,
    max_tokens=200, format=NAMING_SCHEMA, temperature=0, seed=7)`, capped at
    `timeout` seconds when the backend takes one. Returns the reply text, or
    None when the model is down or the call fails (the caller logs
    "question naming unavailable" and uses the slug). Never called for a
    sensitive question."""
    if q.sensitive or not can_name(backend):
        return None
    kw: dict[str, Any] = {"max_tokens": NAMING_MAX_TOKENS, "format": NAMING_SCHEMA,
                          "temperature": 0, "seed": NAMING_SEED}
    if timeout and _accepts_timeout(backend):
        kw["timeout"] = float(timeout)
    try:
        return backend.complete(NAMING_SYSTEM, naming_user_prompt(q, existing), **kw).text
    except (BackendError, TimeoutError, OSError):
        return None


def assign_key(q: CapturedQuestion, extra: Optional[Mapping[str, Any]] = None,
               rows: Sequence[Mapping[str, Any]] = (), suggestion: Any = None) -> KeyChoice:
    """The key for a question whose `sig` is new (§5.2), first rule that holds:
    1 a profile gap -> its profile path ("profile"); 2 an `extra` entry that
    lists this label; 3 a stored `questions` row with this label and kind;
    4 the model's `suggestion` (its reply, or parse_naming's result), never for
    a sensitive question ("model"); 5 the slug ("rule"). `rows` are questions
    rows ({key, label_norm, kind, title, sensitive}, e.g. store.question_rows()).
    Pure: the naming call itself is `ask_model`, made by apply_flow."""
    if q.target_path:
        return KeyChoice(q.target_path, form_label(q.target_path) or short_title(q.label),
                         "", "profile")
    kind = _kind_value(q.kind)
    existing = existing_keys(extra, rows)
    for e in existing:
        if e.in_extra and q.label_norm in e.labels:
            return KeyChoice(e.key, e.title, e.description, "rule")
    for r in rows:
        if (r.get("label_norm") == q.label_norm and str(r.get("kind")) == kind
                and not r.get("target_path")):
            return KeyChoice(str(r["key"]), str(r.get("title") or r["key"]),
                             str(r.get("description") or ""), "rule")
    if suggestion is not None and not q.sensitive:
        choice = (suggestion if isinstance(suggestion, KeyChoice)
                  else parse_naming(suggestion, existing, q))
        if choice is not None:
            return KeyChoice(choice.key, choice.title, choice.description, "model")
    return KeyChoice(slug_key(q.label_norm, existing, kind), short_title(q.label), "", "rule")


def question_row(q: CapturedQuestion, choice: KeyChoice) -> dict[str, Any]:
    """The dict store.upsert_question takes (questions_design §7): employer
    text and the key, never an answer."""
    return {"sig": signature(q), "key": choice.key, "target_path": q.target_path,
            "title": choice.title, "description": choice.description,
            "kind": _kind_value(q.kind), "label": q.label, "label_norm": q.label_norm,
            "options": [{"label": o, "norm": n} for o, n in zip(q.options, q.option_norms)],
            "sensitive": q.sensitive, "reason": q.reason.value, "named_by": choice.named_by}
