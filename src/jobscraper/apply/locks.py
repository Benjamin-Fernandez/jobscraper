"""Locks: the deterministic pre-pass before the model (llm_fill_design §4; D-78, D-82).

Some answers must never depend on a model: the file we upload, the email whose mailbox
is watched, work rights (D-75), sensitive facts (AD §5.3), consents, the owner's own
explicit answers and the declarations (F-33). `lock_page` settles those fields first.
A FILLED lock is final: the field is left out of the model's output schema and appears
in the prompt only as context. An UNKNOWN lock is final too: the field is captured as a
question (or stops the attempt), and it never goes to the model (ADR-0003 fail closed).

Order per field (review M1, F-32): L1 resume file, L2 email, L4/L5 work rights and
sensitive rows, L6 the owner's `extra` answers, L3/L7 declarations. An UNKNOWN from
L4/L5 consults L6 before it stands; L3/L7 run after L6 had nothing, so an
`attestation_unclear` the owner answers in Profile resolves on the retry through L6.

Pure: no browser, no model, no store, no log. The resolver's tiers 2-4 do the mapping
(`resolve`, `declarations`), so a lock and the old path answer a field the same way.
"""
from __future__ import annotations

import os
import re
from typing import Any, Mapping, Optional, Sequence

from .. import applicant
from . import declarations, facts, resolve
from .contracts import (
    Answer, AnswerStatus, AnswerTier, Canonical, FieldType, PageField, ResolveContext,
)
from .plan import contains_run, norm_label, qualified_label, tokens

# L1 (H6): what makes a FILE input the resume slot, and what never does.
RESUME_RE = re.compile(r"r[eé]sum[eé]|\bcv\b|curriculum", re.I)
RESUME_PAGE_RE = re.compile(r"r[eé]sum[eé]|\bcv\b|drop (off )?your|autofill", re.I)
NOT_RESUME_RE = re.compile(r"cover\s*letter|transcript|portfolio|certificate|writing sample|"
                           r"photo|passport|identity|\bid\b", re.I)
COVER_RE = re.compile(r"cover\s*letter", re.I)
TRANSCRIPT_RE = re.compile(r"transcript", re.I)
# L2: a label that asks for an email (a one-token phrase: labels of 4 tokens or fewer).
EMAIL_PHRASE = ("email",)
# L5: consents that are locks although their tier-2 rows are not sensitive (AD §7.3).
LOCKED_CONSENTS = frozenset({"consents.privacy_consent", "consents.certify_true"})
# L4: the D-75 work-rights maps.
WORK_RIGHTS_PREFIXES = ("singapore_status.authorised_to_work", "singapore_status.requires_sponsorship")
# L5 EEO questions with no tier-2 row: label words -> the tier-1 value rule (AD §7.2 EEO_*).
EEO_WORDS: tuple[tuple[tuple[str, ...], Canonical, str], ...] = (
    (("veteran",), Canonical.EEO_VETERAN, "us_self_id.veteran_status"),
    (("disability",), Canonical.EEO_DISABILITY, "us_self_id.disability_status"),
    (("disabled",), Canonical.EEO_DISABILITY, "us_self_id.disability_status"),
    (("hispanic",), Canonical.EEO_HISPANIC, "us_self_id.eeo_race_ethnicity"),
    (("latino",), Canonical.EEO_HISPANIC, "us_self_id.eeo_race_ethnicity"),
)
# L7: a negated declaration on a Yes/No choice cannot be mapped safely.
NEGATIONS = (("not",), ("never",), ("no",), ("none",), ("neither",), ("free", "of"), ("without",))


def _shown_name(pf: PageField) -> str:
    v = pf.shown
    if isinstance(v, list):
        v = v[0] if v else ""
    return os.path.basename(str(v or "").strip())


def _stamp(a: Answer, pf: PageField) -> Answer:
    """Every row carries what the field showed and where it came from (§7)."""
    a.shown = pf.shown
    a.origin = pf.origin.value
    a.entry = pf.group
    return a


def _filled(pf: PageField, value: Any, tier: AnswerTier, source: str, *, rule_id: str = "",
            note: str = "", sensitive: bool = False, labels: Sequence[str] = ()) -> Answer:
    return _stamp(Answer(field_key=pf.field.key, value=value, tier=tier, source=source,
                         confidence=resolve.CONF_FIELD_MAP if tier is AnswerTier.FIELD_MAP
                         else resolve.CONF_PROFILE, status=AnswerStatus.FILLED,
                         option_labels=tuple(labels), rule_id=rule_id, sensitive=sensitive,
                         note=note), pf)


def _unknown(pf: PageField, note: str, *, rule_id: str = "", sensitive: bool = False) -> Answer:
    """No answer and never the model: required -> UNKNOWN, optional -> BLANK_OPTIONAL."""
    st = AnswerStatus.UNKNOWN if pf.field.required else AnswerStatus.BLANK_OPTIONAL
    return _stamp(Answer(field_key=pf.field.key, value=None, tier=AnswerTier.NONE, source="",
                         confidence=0.0, status=st, rule_id=rule_id, sensitive=sensitive,
                         note=note), pf)


def is_unknown(a: Answer) -> bool:
    return a.status in (AnswerStatus.UNKNOWN, AnswerStatus.UNGROUNDED,
                        AnswerStatus.BLANK_OPTIONAL)


# ---------------------------------------------------------------- L1, L1b

def _file_lock(pf: PageField, rctx: ResolveContext, uploaded: Mapping[str, str], *,
               single_file: bool, page_text: str) -> Answer:
    """L1 (H6, TR-8) and L1b: every FILE field is settled here; none reaches the model."""
    f = pf.field
    own = " ".join((f.label, f.section, f.description, pf.group_title))
    other_doc = bool(NOT_RESUME_RE.search(own))
    is_resume = not other_doc and (bool(RESUME_RE.search(own)) or (
        single_file and bool(RESUME_PAGE_RE.search(own + " " + (page_text or "")))))
    if is_resume:
        if not rctx.resume_path:
            return _unknown(pf, "L1: no resume file")
        shown = _shown_name(pf)
        if shown and shown in uploaded:
            note = "L1: kept, uploaded in this attempt"
        elif shown:
            note = "L1: replace the attachment (not uploaded in this attempt)"
        else:
            note = ""
        return _filled(pf, rctx.resume_path, AnswerTier.FIELD_MAP, "field_map:resume",
                       rule_id="resume", note=note)
    if TRANSCRIPT_RE.search(own):
        path = resolve.profile_value(rctx.profile or {}, "documents.transcript")
        if isinstance(path, str) and path.strip():
            return _filled(pf, path.strip(), AnswerTier.FIELD_MAP, "field_map:transcript",
                           rule_id="transcript")
        return _unknown(pf, "L1b: no transcript file", rule_id="documents.transcript")
    if COVER_RE.search(own):
        if f.required:
            # L1b: a required cover letter is composed by one model call and uploaded;
            # that call is not part of the lock pre-pass (see comms: lane M question).
            return _unknown(pf, "L1b: cover letter not composed")
        return _unknown(pf, "cover letter is optional")
    return _unknown(pf, "L1b: no file for this upload")


# ---------------------------------------------------------------- L2

def _email_lock(pf: PageField, rctx: ResolveContext) -> Optional[Answer]:
    """L2: an EMAIL field, or a label asking for an email, gets the account identity
    (D-70, AD §10.5). Not on a question about another person (D-84 R4)."""
    f = pf.field
    toks = tokens(f.label)
    asks = f.type is FieldType.EMAIL or any(
        len(toks) <= 4 and contains_run(toks, list(p.split())) for p in EMAIL_PHRASE)
    if not asks or facts.about_other_person(pf):
        return None
    email = rctx.account_email or resolve.profile_value(rctx.profile or {}, "contact.email")
    fit = resolve.fit_text(f, email)
    if fit is None:
        return _unknown(pf, "L2: no email fits", rule_id="contact.email", sensitive=True)
    return _filled(pf, fit[0], AnswerTier.FIELD_MAP, "field_map:email", rule_id="email",
                   sensitive=True, labels=fit[1])


# ---------------------------------------------------------------- L4, L5

def _work_rights_bool(f, label_norm: str, rctx: ResolveContext,
                      r: resolve.Rule) -> Optional[Answer]:
    """L4 on a per-country bool row (`...authorised_to_work.SG`): the D-75 map value."""
    parts = r.key.split(".")
    which, code = parts[1], parts[2] if len(parts) > 2 else applicant.WORK_RIGHTS_DEFAULT
    value, src = applicant.work_right(rctx.profile or {}, which, code)
    fit = resolve.fit_bool(f, value)
    if fit is None:
        return None
    return Answer(field_key=f.key, value=fit[0], tier=AnswerTier.PROFILE_RULE,
                  source=f"profile:singapore_status.{which}.{src}", confidence=resolve.CONF_PROFILE,
                  status=AnswerStatus.FILLED, option_labels=tuple(fit[1]), rule_id=r.key)


def _rule_lock(pf: PageField, label_norm: str, rctx: ResolveContext,
               rules: Any) -> Optional[Answer]:
    """L4 (D-75 work rights) and L5 (sensitive tier-2 rows, the two locked consents,
    EEO). Returns a FILLED Answer, an UNKNOWN one (it consults L6 next), or None
    when no lock row matches (non-sensitive rows don't answer on their own, §4)."""
    f = pf.field
    best, _score = rules.select(label_norm, f) if rules is not None else ([], 0)
    if len(best) > 1:
        if any(r.sensitive for r in best):
            return _unknown(pf, "ambiguous: " + ", ".join(r.key for r in best), sensitive=True)
        return None
    if best:
        r = best[0]
        key = r.parent or r.key
        if r.kind == "country_bool":
            t2 = resolve._tier2_country_bool(f, label_norm, rctx, r)
            if t2.answer:
                return _stamp(t2.answer, pf)
            note = t2.stop.note if t2.stop else t2.note
            return _unknown(pf, note, rule_id=r.key)
        if key.startswith(WORK_RIGHTS_PREFIXES):
            a = _work_rights_bool(f, label_norm, rctx, r)
            return _stamp(a, pf) if a else _unknown(pf, f"profile rule {r.key}: no value fits",
                                                    rule_id=r.key)
        if r.sensitive or key in LOCKED_CONSENTS:
            t2 = resolve._tier2_one(f, label_norm, rctx, r)
            if t2.answer:
                return _stamp(t2.answer, pf)
            note = t2.stop.note if t2.stop else t2.note
            return _unknown(pf, note or f"profile rule {r.key}: no value fits", rule_id=r.key,
                            sensitive=r.sensitive)
        return None
    toks = label_norm.split()
    for words, canonical, path in EEO_WORDS:
        if contains_run(toks, list(words)):
            fit = resolve.field_map_fit(canonical, f, rctx)
            if fit is None:
                return _unknown(pf, f"field map {canonical.value}: no value fits",
                                rule_id=path, sensitive=True)
            return _filled(pf, fit[0], AnswerTier.PROFILE_RULE, f"profile:{path}",
                           rule_id=canonical.value, sensitive=True, labels=fit[1])
    return None


# ---------------------------------------------------------------- L3, L7

# A trailing answer hint ("... offence? (Yes/No)") is not a negation (review F6).
ANSWER_HINTS = (("yes", "no"), ("yes", "or", "no"), ("y", "n"), ("no", "yes"),
                ("no", "or", "yes"))


# D-87 (AD §7.5 rule 4): an NS-exclusion run ("excluding mandatory military service",
# "national service is not counted") is not a negation of the question.
NS_EXCLUSION_LEADS = (("excluding",), ("exclude",), ("excludes",), ("except",),
                      ("other", "than"), ("apart", "from"), ("aside", "from"), ("besides",),
                      ("save", "for"), ("not", "including"), ("not", "counting"),
                      ("does", "not", "include"), ("do", "not", "include"))
NS_EXCLUSION_TAILS = (("not", "included"), ("excluded",), ("not", "counted"),
                      ("does", "not", "count"))
NS_TERMS = (("full", "time", "national", "service"), ("mandatory", "military", "service"),
            ("compulsory", "military", "service"), ("mandatory", "national", "service"),
            ("national", "service"), ("military", "service"), ("mandatory", "service"),
            ("compulsory", "service"), ("conscription",), ("nsf",), ("ns",))


def _run_at(toks: list[str], i: int, runs: Sequence[tuple[str, ...]]) -> int:
    """The length of the first run in `runs` starting at toks[i], else 0."""
    for r in runs:
        if tuple(toks[i:i + len(r)]) == r:
            return len(r)
    return 0


def strip_ns_exclusion(toks: list[str]) -> list[str]:
    """D-87: `toks` without its NS-exclusion runs (a lead with an NS term starting in the
    next 4 tokens, or an NS term followed within 3 tokens by a "not included" tail)."""
    out: list[str] = []
    i = 0
    while i < len(toks):
        lead = _run_at(toks, i, NS_EXCLUSION_LEADS)
        if lead:
            for j in range(i + lead, min(i + lead + 4, len(toks))):
                n = _run_at(toks, j, NS_TERMS)
                if n:
                    i = j + n
                    break
            else:
                out.append(toks[i])
                i += 1
            continue
        n = _run_at(toks, i, NS_TERMS)
        if n:
            for j in range(i + n, min(i + n + 3, len(toks))):
                t = _run_at(toks, j, NS_EXCLUSION_TAILS)
                if t:
                    i = j + t
                    break
            else:
                out.extend(toks[i:i + n])
                i += n
            continue
        out.append(toks[i])
        i += 1
    return out


def _negated(label_norm: str) -> bool:
    toks = strip_ns_exclusion(label_norm.split())
    for hint in ANSWER_HINTS:
        if len(toks) > len(hint) and tuple(toks[-len(hint):]) == hint:
            toks = toks[:-len(hint)]
            break
    return any(contains_run(toks, list(n)) for n in NEGATIONS)


def _declaration_lock(pf: PageField, label_norm: str, rctx: ResolveContext) -> Optional[Answer]:
    """L3: the tier-4 declaration answer (AD §7.5). Every classified field, AMBIGUOUS
    included, goes to `declarations.answer()`, which owns the D-87 agreement rule (L3
    does not end AMBIGUOUS itself). L7: a Yes/No choice whose label is negated ("I have
    never been...", "free of", "without"; NS-exclusion runs removed first, D-87) cannot
    be mapped safely -> unknown (attestation_unclear). A single checkbox keeps L3's own
    negation rule (tick when the statement on it is true)."""
    f = pf.field
    label = declarations.classify(label_norm, norm_label(f.description))
    if label is None:
        return None
    if label is not declarations.AMBIGUOUS and f.type is not FieldType.CHECKBOX \
            and resolve.bool_shaped(f) and _negated(label_norm):
        return _unknown(pf, "L7: negated declaration", rule_id=label.value, sensitive=True)
    return _stamp(declarations.answer(label, f, rctx), pf)


# ---------------------------------------------------------------- the pre-pass

def lock_field(pf: PageField, rctx: ResolveContext, rules: Any, *, today: str = "",
               uploaded: Optional[Mapping[str, str]] = None, single_file: bool = False,
               page_text: str = "", qualified: str = "") -> Optional[Answer]:
    """One field through L1, L2, L4/L5, L6, L3/L7. None = not locked (the model's)."""
    f = pf.field
    if f.type is FieldType.HIDDEN:
        return _stamp(Answer(field_key=f.key, value=None, tier=AnswerTier.NONE, source="",
                             confidence=0.0, status=AnswerStatus.SKIPPED, note="hidden"), pf)
    if f.type is FieldType.FILE:
        return _file_lock(pf, rctx, uploaded or {}, single_file=single_file,
                          page_text=page_text)
    a = _email_lock(pf, rctx)
    if a is not None:
        return a
    label_norm = norm_label(f.label)
    held = _rule_lock(pf, label_norm, rctx, rules)
    if held is not None and held.status is AnswerStatus.FILLED:
        return held
    owner, _note = resolve.extra_answer(f, qualified or label_norm, rctx)
    if owner is not None:
        return _stamp(owner, pf)
    if held is not None:
        return held
    return _declaration_lock(pf, label_norm, rctx)


def generic_ordinals(fields: Sequence[PageField]) -> dict[str, int]:
    """Reader key -> place among the step's generic-label fields (§12.1)."""
    return resolve.generic_ordinals([pf.field for pf in fields])


def qualified_labels(fields: Sequence[PageField]) -> dict[str, str]:
    """Reader key -> the qualified label (§12.1) every lane matches and captures with."""
    ords = generic_ordinals(fields)
    return {pf.field.key: qualified_label(pf.field.label, pf.field.description, pf.context,
                                          step=pf.field.step, ordinal=ords.get(pf.field.key, 0))
            for pf in fields}


def lock_page(fields: list[PageField], rctx: ResolveContext, rules: Any, *, today: str,
              uploaded: dict[str, str], page_text: str = "") -> dict[str, Answer]:
    """Every locked field's final Answer, keyed by reader key (§4). Fields not in the
    result are open: the model is asked about them. `page_text` (the step's visible
    text) feeds L1's one-FILE clause only; it is optional so the pinned call works."""
    files = [pf for pf in fields if pf.field.type is FieldType.FILE]
    quals = qualified_labels(fields)
    out: dict[str, Answer] = {}
    for pf in fields:
        a = lock_field(pf, rctx, rules, today=today, uploaded=uploaded or {},
                       single_file=len(files) == 1, page_text=page_text,
                       qualified=quals.get(pf.field.key, ""))
        if a is not None:
            out[pf.field.key] = a
    return out
