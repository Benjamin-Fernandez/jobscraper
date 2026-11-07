"""Guards: the model's decisions -> Answers, entry actions and the stop list (llm_fill_design §7).

The model chooses where each answer comes from; nothing it says is used before these
checks pass. `decide` is pure (the one model call it may need, the G5 second opinion,
arrives as the `second` callable), applied per field in order G1-G12; the first
rejection ends the field unknown with a note that names the guard and never a value:

  G1  shape          a choice value must be an offered option
  G2  fact refs      (a) in the chunk's scope, (b) relevant to the question, (c) set,
                     (d) on a choice: a tier-2/`extra` label match, or the model's option
                     equals the program's; (e) no program fit -> unknown (D-86: never
                     the model's option or evidence alone)
  G3  grounding      resume/job/keep: the quote is in the corpus; copy rule (every word of
                     a typed value is in the quote) or compose rule (`resolve.grounded`)
  G4  choice/source  a model-chosen option shares a word with its quote (Yes/No exempt)
  G5  second opinion every model-chosen Yes/No and required choice/number: two agreeing
                     runs (ADR-0003 §3), incl. a Yes/No accepted through G2(d) (D-84 R2)
  G6  entry scope    an entry field's quote lies in that entry's block
  G7  sensitive      only a lock or a private profile fact answers it
  G8  prefill trust  MyGreenhouse values are kept unquoted only where safe; the rest need G3
  G9  leftovers      a site value nobody backed is cleared, reset, unticked or flagged
  G10 required       every required unknown stops the page
  G11 entry titles   a job title must not carry the employer unless the resume's does
  G12 other employers no kept, cited or composed text names another employer (D-84 R1)

Entries (§10): junk entries are deleted (E3), missing ones added (E5), ungroundable
optional ones deleted (E6); decided here, applied by pagefill only after the page is
known to be fillable (E7, review M9).

Fact values are written by the program (`facts.fact_value`, i.e. `resolve.fit_*`); the
model's own text is used only for resume/job values that pass G3. Notes never carry a
value, so the audit and the job log stay free of personal data (NF-02).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field as dc_field, replace
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence, Union

from .. import applicant
from . import declarations, facts as F, resolve
from .contracts import (
    CHOICE_TYPES, EMPLOYER_SPECIFIC_DECLARATIONS, TRUSTED_ORIGINS, Answer, AnswerStatus,
    AnswerTier, EntrySection, Fact, FieldType, FillSource, ModelDecision, PageField,
    ResolveContext, ValueOrigin,
)
from .plan import STOP_WORDS, contains_run, is_generic, norm_label, tokens

RULE_ID = "fill:v2"            # = llm_fill.FILL_PROMPT_VERSION, on every model-backed row
CONF_FACT = 0.9
CONF_MODEL_CHECKED = 0.9                        # resume/job value with two agreeing runs
CONF_MODEL = 0.8
CONF_KEEP_TRUSTED = 0.95
CONF_KEEP_GROUNDED = 0.85
CONF_UNVERIFIED = 0.5
MIN_EVIDENCE = 3

# Module constants (TR-10), all matched on whole words / token runs.
LEVEL_SYNONYMS: tuple[tuple[str, ...], ...] = (
    ("native", "fluent", "bilingual", "mother tongue", "expert", "advanced", "full professional"),
    ("professional", "working", "intermediate", "proficient", "good"),
    ("basic", "beginner", "elementary", "limited", "conversational", "novice"),
)
SENSITIVE_LABEL: tuple[str, ...] = (
    "date of birth", "birth date", "birthdate", "dob", "gender", "sex", "race", "ethnic",
    "ethnicity", "religion", "religious", "nric", "national id", "identity card",
    "identity number", "passport", "disability", "disabled", "veteran", "marital", "pronoun",
    "pronouns", "citizen", "citizenship", "permanent resident", "pr", "resident status",
    "residency status", "residence status", "nationality", "national service", "ns", "ord",
    "military", "armed forces",                      # D-88: NS-inclusive questions
)
CONTACT_WORDS: tuple[str, ...] = (
    "address", "street", "unit", "postal", "zip", "postcode", "phone", "mobile", "email",
    "nric", "passport", "id number",
)
FACT_TITLE_SYNONYMS = F.FACT_TITLE_SYNONYMS
TITLE_FIELD_WORDS = ("title", "position", "role")
SITE_ORIGINS = frozenset({ValueOrigin.SITE_DEFAULT, ValueOrigin.RESUME_IMPORT,
                          ValueOrigin.MYGREENHOUSE, ValueOrigin.WORKDAY_LAST_APPLICATION})
TEXT_LIKE = frozenset({FieldType.TEXT, FieldType.TEXTAREA, FieldType.EMAIL, FieldType.PHONE,
                       FieldType.URL, FieldType.NUMBER})
UNANSWERED = frozenset({AnswerStatus.UNKNOWN, AnswerStatus.UNGROUNDED})
COVER_RE = re.compile(r"cover\s*letter", re.I)
_URL = re.compile(r"(https?://\S+|www\.\S+|\b[\w-]+\.(?:com|io|org|net|dev|me|sg)\b\S*)", re.I)
_MONTH_NUM = {m: i for i, m in enumerate(resolve.MONTHS, start=1)}
_MONTH_NUM.update({m[:3]: i for m, i in list(_MONTH_NUM.items())})
_MONTH_NUM["sept"] = 9
_APOS = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "•": " "})


@dataclass
class Decision:
    """What one page gets (§7, §10): an Answer per field, the required unknowns that stop
    it (G10), and the actions pagefill applies in step 9 (E7: only once the page is known
    to be fillable). Shape agreed with lane R (WP-R3 reads it).

    `resets` lists the keys whose site value G9 removes; that field's `Answer.note` is
    exactly one of G9_NOTES ("G9: clear" | "G9: reset" | "G9: untick"), see `reset_action`.
    When the widget can't reset a choice, pagefill turns the row into PREFILLED 0.5
    "unverified site value" (in an entry group E6 deletes the entry instead)."""
    answers: dict[str, Answer] = dc_field(default_factory=dict)
    unknown_required: tuple[str, ...] = ()            # field keys, page order (G10)
    deletes: tuple[str, ...] = ()                     # entry group ids "<section>#<index>" (E3, E6)
    adds: tuple[tuple[str, str], ...] = ()            # (site section, source entry id) (E5)
    resets: tuple[str, ...] = ()                      # field keys G9 clears / resets / unticks


G9_NOTES = {"clear": "G9: clear", "reset": "G9: reset", "untick": "G9: untick"}
UNVERIFIED_NOTE = "unverified site value"


def reset_action(answer: Answer) -> str:
    """"clear" | "reset" | "untick" for a row listed in `Decision.resets`, else ""."""
    for action, note in G9_NOTES.items():
        if answer.note == note:
            return action
    return ""


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------

def cnorm(text: str) -> str:
    """Corpus normalisation for quotes: NFKC, curly quotes/dashes/bullets folded,
    lowercase, whitespace collapsed, "," dropped inside digit groups."""
    t = unicodedata.normalize("NFKC", str(text or "")).translate(_APOS)
    return resolve.corpus_norm(t)


def _num(tok: str) -> str:
    return tok.lstrip("0") or "0" if tok.isdigit() else tok


def ctoks(text: str, *, months: bool = False) -> set[str]:
    """Content tokens: lowercase alphanumeric runs minus the §5.2 stop words; numbers
    without leading zeros. `months=True` also adds a month name's number (a quote
    "May 2024" backs the value "2024-05")."""
    out: set[str] = set()
    for t in re.findall(r"[a-z0-9]+", cnorm(text)):
        if t in STOP_WORDS:
            continue
        out.add(_num(t))
        if months and t in _MONTH_NUM:
            out.add(str(_MONTH_NUM[t]))
    return out


def _phrases(words: Iterable[str], text_toks: Sequence[str]) -> bool:
    return any(contains_run(text_toks, w.split()) for w in words)


def sensitive_label(pf: PageField) -> bool:
    """G7: the question is about an S topic (whole words: "Sussex" is not "sex"). A
    generic label ("Please specify") belongs to its context question (§12.1), so its
    context and group heading count too: a follow-up to "Race" is an S field (review F3).
    `llm_fill._withhold` uses this, so such a field's `current` is withheld as well."""
    text = pf.field.label + " " + pf.field.description
    if is_generic(norm_label(pf.field.label)):
        text += " " + (pf.context or "") + " " + (pf.group_title or "")
    return _phrases(SENSITIVE_LABEL, tokens(text))


def contact_label(pf: PageField) -> bool:
    return _phrases(CONTACT_WORDS, tokens(pf.field.label))


def _shown(pf: PageField) -> Any:
    return pf.shown


def _has_shown(pf: PageField) -> bool:
    v = pf.shown
    if pf.field.type is FieldType.CHECKBOX:
        return str(v).strip().lower() == "true"
    if isinstance(v, list):
        return any(str(x).strip() for x in v)
    return bool(str(v or "").strip())


def _text_of(v: Any) -> str:
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    return "" if v is None else str(v)


def _date_key(v: str) -> tuple[int, ...]:
    nums = [int(x) for x in re.findall(r"\d+", v or "")]
    if not nums:
        return ()
    yi = next((i for i, n in enumerate(nums) if n >= 1000), None)
    if yi is None:
        return tuple(nums)
    rest = nums[:yi] + nums[yi + 1:]
    if yi != 0:
        rest = list(reversed(rest))
    return (nums[yi], *rest)


def same_value(a: Any, b: Any, pf: PageField) -> bool:
    """Normalised equality (AD §7.1); dates by their numbers; multi as sets."""
    if isinstance(a, list) or isinstance(b, list):
        sa = {norm_label(x) for x in (a if isinstance(a, list) else [a]) if str(x).strip()}
        sb = {norm_label(x) for x in (b if isinstance(b, list) else [b]) if str(x).strip()}
        return sa == sb
    sa, sb = _text_of(a).strip(), _text_of(b).strip()
    if pf.field.type is FieldType.DATE:
        return _date_key(sa) == _date_key(sb) and bool(sa)
    if pf.field.type is FieldType.NUMBER or (re.fullmatch(r"[\d,.\s]+", sa or "x")
                                            and re.fullmatch(r"[\d,.\s]+", sb or "x")):
        return re.sub(r"[,\s]", "", sa).rstrip("0").rstrip(".") == \
            re.sub(r"[,\s]", "", sb).rstrip("0").rstrip(".")
    return norm_label(sa) == norm_label(sb)


def option_for(pf: PageField, value: Any) -> Optional[Union[str, list[str]]]:
    """G1: the offered option(s) the value names (exact, normalised, or the leaf of a
    "Category > Leaf" path), else None. A searchable list (options_complete False) takes
    the words as typed: the widget's strict read-back is the check there (LL3)."""
    f = pf.field
    if f.type is FieldType.CHECKBOX:
        v = str(value).strip().lower()
        return v if v in ("true", "false") else None
    opts = [o.label for o in f.options]

    def one(v: Any) -> Optional[str]:
        s = str(v or "").strip()
        if not s:
            return None
        for o in opts:
            if o == s:
                return o
        n = norm_label(s)
        hits = [o for o in opts if norm_label(o) == n]
        if len(hits) == 1:
            return hits[0]
        leaf = [o for o in opts if " > " in o and norm_label(o.split(" > ")[-1]) == n]
        return leaf[0] if len(leaf) == 1 else None

    if f.type is FieldType.MULTI_CHOICE:
        items = value if isinstance(value, list) else [x for x in str(value or "").split(";")]
        got = [one(x) for x in items if str(x).strip()]
        if not got or None in got:
            return None if opts or pf.options_complete else [str(x).strip() for x in items]
        return list(dict.fromkeys(got))
    if not opts and not pf.options_complete:
        s = str(value or "").strip()
        return s or None
    hit = one(value)
    if hit is None and not pf.options_complete:
        s = str(value or "").strip()
        return s or None
    return hit


def yes_no(pf: PageField) -> bool:
    return pf.field.type is FieldType.CHECKBOX or resolve.bool_shaped(pf.field)


def is_choice(pf: PageField) -> bool:
    return pf.field.type in CHOICE_TYPES or pf.field.type is FieldType.CHECKBOX \
        or (pf.field.type is FieldType.TYPEAHEAD and bool(pf.field.options))


def _level_expand(toks: set[str]) -> set[str]:
    out = set(toks)
    joined = " ".join(sorted(toks))
    for group in LEVEL_SYNONYMS:
        if any(w in toks or w in joined for w in group):
            out |= {w for g in group for w in g.split()}
    return out


def g4_ok(option: Any, quote: str) -> bool:
    """G4: a model-chosen option shares a content word with its quote (or the fact's
    text), with LEVEL_SYNONYMS ("Fluent" is backed by "native")."""
    opt = set()
    for o in (option if isinstance(option, list) else [option]):
        opt |= ctoks(str(o).split(" > ")[-1])
    return bool(_level_expand(opt) & _level_expand(ctoks(quote)))


def lines_in_block(value: str, block: str) -> bool:
    """E4 recheck: every non-empty line of `value` occurs (normalised) in `block`, so a
    copied description holds nothing the entry doesn't say (bullets and spacing aside)."""
    corpus = cnorm(block)
    lines = [cnorm(x).strip(" -*") for x in str(value or "").splitlines()]
    lines = [x for x in lines if x]
    return bool(lines and corpus) and all(x in corpus for x in lines)


def copy_ok(value: Any, evidence: str) -> bool:
    """G3 copy rule: every content token of the value occurs in the quote (numbers and
    dates as tokens, month names as numbers); a URL must occur verbatim."""
    text = _text_of(value)
    ev = cnorm(evidence)
    for u in _URL.findall(text):
        if cnorm(u).rstrip("/") not in ev:
            return False
        text = text.replace(u, " ")
    need = ctoks(text)
    return bool(need or _URL.findall(_text_of(value))) and need <= ctoks(evidence, months=True)


# --------------------------------------------------------------------------
# Scope, recheck selection
# --------------------------------------------------------------------------

def allowed_refs(pf: PageField, facts: Sequence[Fact], matches: Mapping[str, Optional[str]],
                 rctx: Optional[ResolveContext] = None) -> list[str]:
    """G2(a): the refs a field may cite (also the schema's `ref` enum, §6.3). In an entry
    group: that entry's facts plus `standing:today` (an unmatched group: none). Elsewhere:
    facts of no entry, plus the profile's links (single facts that Workday also shows as
    website entries). A generic-label field cites only `extra` answers scoped to this
    employer (§12.1, G12)."""
    if pf.group:
        entry = matches.get(pf.group)
        if not entry:
            return []
        return [f.ref for f in facts if F.listed(f) and (f.entry == entry or f.ref == "standing:today")]
    generic = is_generic(norm_label(pf.field.label))
    out = []
    for f in facts:
        if not F.listed(f) or (f.entry and not f.entry.startswith("links.")):
            continue
        if generic and f.ref.startswith("extra:") and not (
                rctx is not None and F.extra_scoped(f.ref.split(":", 1)[1], rctx)):
            continue
        out.append(f.ref)
    return out


def _group_names(fields: Sequence[PageField]) -> dict[str, str]:
    """Group id -> the employer/school the site shows for it (G11)."""
    out: dict[str, str] = {}
    for pf in fields:
        if pf.group and pf.group not in out:
            kind = F.SECTION_KINDS.get(pf.group.split("#", 1)[0], "")
            name, _t = F._site_parts(kind, [x for x in fields if x.group == pf.group])
            out[pf.group] = name
    return out


def _entry_name(entry: str, rctx: ResolveContext) -> str:
    m = re.match(r"^(experience|education)\[(\d+)\]$", entry or "")
    if not m:
        return ""
    lst = (rctx.profile or {}).get(m.group(1)) or []
    i = int(m.group(2))
    if i < len(lst) and isinstance(lst[i], dict):
        return str(lst[i].get("employer" if m.group(1) == "experience" else "institution") or "")
    return ""


def g11_fails(pf: PageField, value: Any, entry: str, rctx: ResolveContext,
              blocks: Mapping[str, str], site_name: str = "") -> bool:
    """G11 (M12): an entry's title field carries the employer's name while the entry's
    title line in the block does not ("Intern, Example Logistics")."""
    if pf.field.type is not FieldType.TEXT or not _phrases(TITLE_FIELD_WORDS,
                                                          tokens(pf.field.label)):
        return False
    emp = declarations.employer_norm(_entry_name(entry, rctx) or site_name).split()
    if not emp or not contains_run(tokens(_text_of(value)), emp):
        return False
    block = (blocks.get(entry) or "").strip()
    title_line = block.splitlines()[0] if block else ""
    return not contains_run(tokens(title_line), emp)


def recheck_targets(fields: Sequence[PageField], decisions: Any,
                    matches: Mapping[str, Optional[str]], rctx: ResolveContext, *,
                    blocks: Mapping[str, str]) -> list[str]:
    """Field keys that need the `recheck` copy call (§6.4, E4) before `decide`: every
    TEXTAREA of a matched entry whose answer is not a fact (D-84 R3: imported or not,
    program-added entries too), and every entry TEXT title that fails G11."""
    ds = _by_key(decisions)
    names = _group_names(fields)
    out = []
    for pf in fields:
        entry = matches.get(pf.group) if pf.group else None
        if not entry or not blocks.get(entry):
            continue
        d = ds.get(pf.field.key)
        src = d.source if d else FillSource.UNKNOWN
        if src in (FillSource.PROFILE, FillSource.EXTRA, FillSource.STANDING):
            continue
        if pf.field.type is FieldType.TEXTAREA:
            out.append(pf.field.key)
            continue
        if d is not None and src in (FillSource.RESUME, FillSource.KEEP, FillSource.JOB):
            v = pf.shown if src is FillSource.KEEP else d.value
            if g11_fails(pf, v, entry, rctx, blocks, names.get(pf.group, "")):
                out.append(pf.field.key)
    return out


def _by_key(decisions: Any) -> dict[str, ModelDecision]:
    if isinstance(decisions, Mapping):
        return dict(decisions)
    out: dict[str, ModelDecision] = {}
    for d in decisions or ():
        out[d.field_key] = d              # a later call (pick, recheck, corrective) wins
    return out


# --------------------------------------------------------------------------
# decide
# --------------------------------------------------------------------------

class _Ctx:
    def __init__(self, fields, locks, facts, rctx, matches, second, today, rules, sections,
                 model, hashes, cfg, blocks):
        self.fields, self.locks, self.facts, self.rctx = fields, locks, facts, rctx
        self.matches, self.second, self.today, self.rules = matches, second, today, rules
        self.sections, self.model, self.hashes = sections, model, hashes or {}
        self.cfg = cfg or {}
        self.blocks = blocks if blocks is not None else F.entry_blocks(rctx)
        self.by_ref = F.by_ref(facts)
        self.others = F.other_employers(rctx)
        self.others_composed = F.other_employers(rctx, composed=True)
        # Switch off: the model saw the redacted resume, so a quote can't carry an S value;
        # the corpus is the plain text (a "[private]" quote never matches it). Switch on
        # (D-105) the model reads the plain resume, so a quote could carry one: G3 then
        # rejects a quote holding a protected value that the posting and the non-private
        # facts do not also hold (`quote_private`; Q-74 §4 hook 7).
        self.resume_corpus = cnorm(rctx.resume_text or "")
        self.job_corpus = cnorm("\n".join([rctx.employer_name or "",
                                           getattr(rctx, "job_title", "") or "",
                                           rctx.jd_text or ""]))
        self.facts_corpus = cnorm(F.facts_text([f for f in facts if not f.private]))
        self.sees = bool(getattr(rctx, "model_sees_sensitive", False))
        self.protected = applicant.protected_terms(rctx.profile) if self.sees else []
        self.names = _group_names(fields)
        self.own = F.own_details(rctx)


def _answer_unknown(pf: PageField, note: str, *, ungrounded: bool = False, rule_id: str = "",
                    evidence: str = "", sensitive: bool = False) -> Answer:
    if pf.field.required:
        st = AnswerStatus.UNGROUNDED if ungrounded else AnswerStatus.UNKNOWN
    else:
        st = AnswerStatus.BLANK_OPTIONAL
    return Answer(field_key=pf.field.key, value=None, tier=AnswerTier.NONE, source="",
                  confidence=0.0, status=st, rule_id=rule_id, note=note[:300],
                  evidence=evidence[:240], sensitive=sensitive)


def _source_of(ref: str) -> str:
    ns, _, name = ref.partition(":")
    return f"memory:extra.{name}" if ns == "extra" else ref


def _second_agrees(c: _Ctx, pf: PageField, value: Any) -> Optional[bool]:
    """G5: None = the second opinion is switched off (fail closed: unknown)."""
    if c.cfg.get("second_opinion", True) is False or c.second is None:
        return None
    d2 = c.second(pf)
    if d2 is None or d2.source is FillSource.UNKNOWN:
        return False
    v2 = _decision_value(c, pf, d2)
    if v2 is not None and skill_list(pf) and d2.source in (FillSource.RESUME, FillSource.JOB):
        v2 = ground_items(c.rctx, v2 if isinstance(v2, list) else [v2], d2.evidence)
    return v2 is not None and same_value(v2, value, pf)


def _decision_value(c: _Ctx, pf: PageField, d: ModelDecision) -> Any:
    """The value a (second-opinion) decision leads to: a fact's program value, else the
    model's option. When the run also states an option that differs from the fact's
    value, it does not agree with anything (None): a second run citing the same fact
    while choosing "No" is a disagreement, not a "Yes" (D-84 R2)."""
    if d.source in (FillSource.PROFILE, FillSource.EXTRA, FillSource.STANDING):
        fit = F.fact_value(d.ref, pf, c.rctx, c.rules, today=c.today)
        if fit is not None:
            own = option_for(pf, d.value) if is_choice(pf) else d.value
            if _text_of(d.value).strip() and (own in (None, "", [])
                                             or not same_value(own, fit[0], pf)):
                return None
            return fit[0]
        if not is_choice(pf):
            return None
    if d.source is FillSource.KEEP:
        return pf.shown
    if is_choice(pf):
        return option_for(pf, d.value)
    return d.value


def _model_row(c: _Ctx, pf: PageField, value: Any, source: str, *, conf: float,
               evidence: str = "", tier: AnswerTier = AnswerTier.LLM,
               status: AnswerStatus = AnswerStatus.FILLED, sensitive: bool = False,
               note: str = "") -> Answer:
    labels: tuple[str, ...] = ()
    if pf.field.type in CHOICE_TYPES and value not in (None, ""):
        labels = tuple(value) if isinstance(value, list) else (str(value),)
    return Answer(field_key=pf.field.key, value=value, tier=tier, source=source,
                  confidence=conf, status=status, option_labels=labels, rule_id=RULE_ID,
                  model=c.model if tier is AnswerTier.LLM else "",
                  prompt_hash=c.hashes.get(pf.field.key, "") if tier is AnswerTier.LLM else "",
                  sensitive=sensitive, note=note, evidence=(evidence or "")[:240])


def _label_match_extra(ref: str, pf: PageField, rctx: ResolveContext) -> bool:
    ns, _, name = ref.partition(":")
    if ns != "extra":
        return False
    entry = ((rctx.profile or {}).get("extra") or {}).get(name)
    labels = entry.get("labels") if isinstance(entry, dict) else None
    n = norm_label(pf.field.label)
    return isinstance(labels, list) and any(
        isinstance(x, str) and (norm_label(x) == n or x.split(" | ", 1)[0].strip() == n)
        for x in labels)


def _restates_fact(pf: PageField, mv: Any, fact: Fact) -> bool:
    """G2(d) restated fact (Q-48, LF §8 G2d): on a choice field that is not Yes/No, a model
    value that is not an offered option but equals (normalised) the cited non-private
    fact's own value means "map this fact"; the caller writes the program's fit (D-86 F7).
    Private facts never qualify (G7 and the locks cover them)."""
    if fact.private or not fact.value or not is_choice(pf) or yes_no(pf) \
            or not _text_of(mv).strip():
        return False
    offered = option_for(pf, mv) is not None and pf.options_complete
    return not offered and same_value(mv, fact.value, pf)


def _fact_field(c: _Ctx, pf: PageField, d: ModelDecision) -> Answer:
    """G2 (+G7, G5) for a decision that cites a fact."""
    ref = d.ref or ""
    fact = c.by_ref.get(ref)
    if fact is None or not ref.startswith(d.source.value + ":") \
            or ref not in allowed_refs(pf, c.facts, c.matches, c.rctx):
        return _answer_unknown(pf, "G2a: ref out of scope")
    if not F.relevant(ref, pf, c.rules, facts=c.facts, rctx=c.rctx):
        return _answer_unknown(pf, "G2b: fact not relevant to the question")
    ns, _, name = ref.partition(":")
    if sensitive_label(pf) and not (fact.private and ns == "profile"):
        return _answer_unknown(pf, "G7: sensitive question", sensitive=True)
    if not fact.is_set:
        return _answer_unknown(pf, "G2c: profile_gap", rule_id=name if ns == "profile" else "",
                               sensitive=fact.private)
    fit = F.fact_value(ref, pf, c.rctx, c.rules, today=c.today)
    choice = is_choice(pf)
    mv = d.value
    if fit is not None and choice and pf.options_complete and pf.field.options \
            and option_for(pf, fit[0]) in (None, "", []):
        fit = None                       # G2(e): the program's value is no offered option
    if fit is not None:
        pv, _labels = fit
        if choice and (fact.kind in ("bool", "enum", "yes_no", "choice", "multi")):
            label_match = (ns == "profile" and F.rule_match(name, pf, c.rules) is not None) \
                or _label_match_extra(ref, pf, c.rctx)
            if not label_match:
                if fact.private:
                    return _answer_unknown(pf, "G2d: private fact without a matching rule",
                                           sensitive=True)
                if (not _text_of(mv).strip() or not same_value(option_for(pf, mv) or mv, pv, pf)) \
                        and not _restates_fact(pf, mv, fact):
                    return _answer_unknown(pf, "G2d: model and fact disagree")
                if yes_no(pf):                                  # D-84 R2
                    agree = _second_agrees(c, pf, pv)
                    if agree is None:
                        return _answer_unknown(pf, "G5: second opinion off")
                    if not agree:
                        return _answer_unknown(pf, "G5: second opinion disagrees")
        elif _text_of(mv).strip() and not same_value(option_for(pf, mv) or mv, pv, pf) \
                and not _restates_fact(pf, mv, fact):
            # an option named by its leaf ("Category > Leaf") is the same option
            return _answer_unknown(pf, "G2d: model value differs from the fact",
                                   sensitive=fact.private)
        return _model_row(c, pf, pv, _source_of(ref), conf=CONF_FACT, sensitive=fact.private)
    # (e) no program fit: unknown. D-86 (review F7): a fact-cited option is used only when
    # the program's own fact_value / fit_* maps the fact onto it (hierarchical lists by
    # their leaves, facts._leaf_fit), never on the model's option or evidence alone.
    return _answer_unknown(pf, "G2e: no_option_fits", rule_id=name if ns == "profile" else "",
                           sensitive=fact.private)


def _corpus(c: _Ctx, pf: PageField, src: FillSource) -> Optional[str]:
    """The text a quote must come from: the entry's block + its facts in an entry
    group (None when there is no block: reject, M5); else the resume, the job, or for
    a keep any of resume, job and the visible facts."""
    if pf.group:
        entry = c.matches.get(pf.group)
        block = c.blocks.get(entry or "", "")
        if not entry or not block:
            return None
        return cnorm(block + "\n" + F.entry_fact_text(c.facts, entry))
    if src is FillSource.RESUME:
        return c.resume_corpus
    if src is FillSource.JOB:
        return c.job_corpus
    return "\n".join((c.resume_corpus, c.job_corpus, c.facts_corpus))


def _grounded(c: _Ctx, pf: PageField, value: Any, d: ModelDecision) -> Optional[str]:
    """G3 (+G6, G12 compose): None when grounded, else the rejecting guard's note."""
    corpus = _corpus(c, pf, d.source)
    if corpus is None:
        return "G6: no entry block"
    if d.via == "recheck" and pf.group:       # E4: the copy task's own check, line by line
        block = c.blocks.get(c.matches.get(pf.group) or "", "")
        return None if lines_in_block(_text_of(value), block) else "G6: lines outside the entry"
    ev = cnorm(d.evidence)
    if len(ev) < MIN_EVIDENCE:
        return "G3: no quote"
    if c.sees and applicant.terms_hit(c.protected, [], d.evidence,
                                      corpus=c.job_corpus + " " + c.facts_corpus):
        return "G3: quote holds a private value"
    if ev not in corpus:
        return "G6: quote outside the entry" if pf.group else "G3: quote not in the source"
    if is_choice(pf):
        return None
    compose = pf.field.type is FieldType.TEXTAREA and not pf.group and d.source is not FillSource.KEEP
    if compose:
        limit = pf.field.max_length or (resolve.COVER_LETTER_LIMIT if COVER_RE.search(pf.field.label)
                                        else resolve.TEXT_LIMITS[FieldType.TEXTAREA])
        bad = resolve.grounded("text", {"text": _text_of(value)}, c.rctx, limit=int(limit),
                               corpus=resolve.corpus_text(c.rctx))
        if bad:
            return "G3: composed text not grounded"
        if F.names_other_employer(_text_of(value), c.others_composed):
            return "G12: names another employer"
        return None
    if not copy_ok(value, d.evidence):
        return "G3: value not in the quote"
    return None


R4_NOTE = "R4: applicant's own detail"


def _own_detail_for_other(c: _Ctx, pf: PageField, value: Any) -> bool:
    """D-84 R4 on the resume/job/keep routes (review F2): a field about another person
    (emergency contact, referee, next of kin, ...) never takes the applicant's own name,
    city or contact detail, whatever the source says."""
    return F.about_other_person(pf) and F.names_own_detail(_text_of(value), c.rctx, c.own)


SKILL_WORDS = ("skill", "skills")


def skill_list(pf: PageField) -> bool:
    """Q-46(b): a multi-select of skills (or any search-driven multi-select), whose items
    are grounded one by one (`ground_items`), not by the quote as a whole."""
    return pf.field.type is FieldType.MULTI_CHOICE and (
        not pf.options_complete or bool(set(tokens(pf.field.label)) & set(SKILL_WORDS)))


# Review F6: a 1-2 letter or common-word skill is no skill when it is just a word in prose
# ("R&D", "Series C", "go-to-market", "excel in teamwork"). Such a name is grounded only by
# the profile / attested skills or by a skills-list context in the quote.
AMBIGUOUS_SKILL_WORDS = frozenset({"go", "r", "c", "word", "excel", "swift", "spark", "rust",
                                   "scala", "office", "ruby", "flask", "dash", "pandas"})


def _in_skill_list(evidence: str, name: str) -> bool:
    """`name` is one element of a comma / slash / semicolon / bullet separated list of at
    least two elements in `evidence` (a resume skills line), not a word in a sentence."""
    parts = [norm_label(p) for p in re.split(r"[,;/|\u2022\n]+", evidence or "")]
    parts = [p for p in parts if p]
    return len(parts) >= 2 and name in parts


def ground_items(rctx: ResolveContext, items: Sequence[Any], evidence: str) -> list[Any]:
    """Q-46(b): the listed items that stand on their own, in order. An item is kept when
    it (or a member of its alias group) is a profile skill or attested skill, or occurs
    as whole words in the quote; an item whose words contain a kept item's words ("HTML
    Design" after "HTML") is a duplicate and dropped."""
    p = rctx.profile or {}
    known = {norm_label(t) for t in list(p.get("skills") or []) + list(p.get("attested_skills") or [])
             if isinstance(t, str) and t.strip()}
    ev = tokens(evidence or "")
    kept: list[Any] = []
    kept_toks: list[set[str]] = []
    for item in items:
        name = norm_label(str(item).split(" > ")[-1])
        if not name:
            continue
        names = next(({norm_label(t) for t in g} for g in rctx.alias_groups
                      if any(norm_label(t) == name for t in g)), {name})
        if bool(names & known):
            ok = True
        elif len(name) <= 2 or name in AMBIGUOUS_SKILL_WORDS:
            ok = any(n and _in_skill_list(evidence, n) for n in names)
        else:
            ok = any(n and contains_run(ev, n.split()) for n in names)
        toks = set(name.split())
        if ok and not any(k <= toks for k in kept_toks):
            kept.append(item)
            kept_toks.append(toks)
    return kept


def _model_field(c: _Ctx, pf: PageField, d: ModelDecision) -> Answer:
    """resume / job: the model's own value, used only after G1, G3/G6, G4, G5, G7, G11."""
    value = d.value
    if not _text_of(value).strip():
        return _answer_unknown(pf, "G1: empty value")
    if "[private]" in _text_of(value):
        return _answer_unknown(pf, "G3: value carries a withheld value", ungrounded=True)
    if c.sees and applicant.terms_hit(
            c.protected, [value] if not isinstance(value, (list, tuple)) else list(value),
            corpus=" ".join((c.resume_corpus, c.job_corpus, c.facts_corpus))):
        # D-105 / ADR-0008 Option C (F1 on the llm_fill side): the model may read a protected
        # value but not write it, unless the resume, posting or facts also hold it.
        return _answer_unknown(pf, "G3: value carries a private value", ungrounded=True)
    if _own_detail_for_other(c, pf, value):
        return _answer_unknown(pf, R4_NOTE)
    if sensitive_label(pf):
        return _answer_unknown(pf, "G7: sensitive question", sensitive=True)
    if is_choice(pf):
        opt = option_for(pf, value)
        if opt in (None, "", []):
            return _answer_unknown(pf, "G1: not an offered option")
        value = opt
        if skill_list(pf):                           # Q-46(b): drop, don't reject the field
            value = ground_items(c.rctx, value if isinstance(value, list) else [value],
                                 d.evidence)
            if not value:
                return _answer_unknown(pf, "G3: no listed item grounded", ungrounded=True,
                                       evidence=d.evidence)
    why = _grounded(c, pf, value, d)
    if why:
        return _answer_unknown(pf, why, ungrounded=True, evidence=d.evidence)
    if is_choice(pf) and not yes_no(pf) and not g4_ok(value, d.evidence):
        return _answer_unknown(pf, "G4: option not backed by the quote", evidence=d.evidence)
    entry = c.matches.get(pf.group) if pf.group else None
    if entry and g11_fails(pf, value, entry, c.rctx, c.blocks, c.names.get(pf.group, "")):
        return _answer_unknown(pf, "G11: title carries the employer", ungrounded=True,
                               evidence=d.evidence)
    checked = False
    if yes_no(pf) or (pf.field.required and (is_choice(pf) or pf.field.type is FieldType.NUMBER)):
        agree = _second_agrees(c, pf, value)
        if agree is None:
            return _answer_unknown(pf, "G5: second opinion off")
        if not agree:
            return _answer_unknown(pf, "G5: second opinion disagrees")
        checked = True
    return _model_row(c, pf, value, d.source.value,
                      conf=CONF_MODEL_CHECKED if checked else CONF_MODEL, evidence=d.evidence)


def _always_ours(pf: PageField) -> bool:
    f = pf.field
    return f.type in (FieldType.FILE, FieldType.EMAIL, FieldType.CHECKBOX) \
        or (len(tokens(f.label)) <= 4 and "email" in tokens(f.label))


def _keep_field(c: _Ctx, pf: PageField, d: ModelDecision) -> Answer:
    """keep: the site's value stays only when trusted (G8) or quoted (G3/G6), and never
    for a sensitive question unless it equals the cited private fact's value (G7)."""
    if not _has_shown(pf):
        return _answer_unknown(pf, "G1: keep with nothing shown")
    if pf.origin not in SITE_ORIGINS:
        return _answer_unknown(pf, "G8: keep of a value the model did not see")
    if _own_detail_for_other(c, pf, pf.shown):
        return _answer_unknown(pf, R4_NOTE)
    src = pf.origin.value
    if sensitive_label(pf):
        ref = d.ref or ""
        fact = c.by_ref.get(ref)
        ok = (fact is not None and fact.private and ref.startswith("profile:")
              and ref in allowed_refs(pf, c.facts, c.matches, c.rctx)
              and F.relevant(ref, pf, c.rules, facts=c.facts, rctx=c.rctx))
        fit = F.fact_value(ref, pf, c.rctx, c.rules, today=c.today) if ok else None
        if fit is None or not same_value(fit[0], pf.shown, pf):
            return _answer_unknown(pf, "G7: sensitive question", sensitive=True)
        return _model_row(c, pf, pf.shown, src, conf=CONF_KEEP_GROUNDED, tier=AnswerTier.NONE,
                          status=AnswerStatus.PREFILLED, sensitive=True)
    decl = declarations.classify_field(pf.field, c.rctx)
    trusted = (pf.origin in TRUSTED_ORIGINS and pf.field.type is not FieldType.TEXTAREA
               and not COVER_RE.search(pf.field.label) and not _always_ours(pf)
               and decl not in EMPLOYER_SPECIFIC_DECLARATIONS
               and not F.names_other_employer(_text_of(pf.shown), c.others))
    if trusted:
        return _model_row(c, pf, pf.shown, src, conf=CONF_KEEP_TRUSTED, tier=AnswerTier.NONE,
                          status=AnswerStatus.PREFILLED, evidence=d.evidence)
    if pf.origin is ValueOrigin.MYGREENHOUSE and F.names_other_employer(_text_of(pf.shown),
                                                                       c.others):
        return _answer_unknown(pf, "G12: kept text names another employer")
    why = _grounded(c, pf, pf.shown, d)
    if why:
        return _answer_unknown(pf, why, ungrounded=True, evidence=d.evidence)
    if is_choice(pf) and not yes_no(pf) and not g4_ok(pf.shown, d.evidence):
        return _answer_unknown(pf, "G4: option not backed by the quote", evidence=d.evidence)
    entry = c.matches.get(pf.group) if pf.group else None
    if entry and g11_fails(pf, pf.shown, entry, c.rctx, c.blocks, c.names.get(pf.group, "")):
        return _answer_unknown(pf, "G11: title carries the employer", ungrounded=True,
                               evidence=d.evidence)
    if yes_no(pf):
        agree = _second_agrees(c, pf, pf.shown)
        if agree is None:
            return _answer_unknown(pf, "G5: second opinion off")
        if not agree:
            return _answer_unknown(pf, "G5: second opinion disagrees")
    return _model_row(c, pf, pf.shown, src, conf=CONF_KEEP_GROUNDED, tier=AnswerTier.NONE,
                      status=AnswerStatus.PREFILLED, evidence=d.evidence)


def _field(c: _Ctx, pf: PageField, d: Optional[ModelDecision]) -> Answer:
    if pf.group and not c.matches.get(pf.group):
        return _answer_unknown(pf, "E3: unmatched entry")
    if pf.field.type is FieldType.FILE:
        return _answer_unknown(pf, "L1b: no file for this upload")
    if d is None:
        return _answer_unknown(pf, "model: no reply")
    if d.source is FillSource.UNKNOWN:
        return _answer_unknown(pf, "model: unknown" + (" (recheck)" if d.via == "recheck" else ""))
    if d.source in (FillSource.PROFILE, FillSource.EXTRA, FillSource.STANDING):
        return _fact_field(c, pf, d)
    if d.source in (FillSource.RESUME, FillSource.JOB):
        return _model_field(c, pf, d)
    return _keep_field(c, pf, d)


def _leftovers(c: _Ctx, pf: PageField, a: Answer, resets: list[str]) -> Answer:
    """G9 (H3): a site value nobody backed does not stay by default. Files are L1's."""
    if pf.origin not in SITE_ORIGINS or not _has_shown(pf) or pf.field.type is FieldType.FILE:
        return a
    if a.status is AnswerStatus.FILLED or a.status is AnswerStatus.SKIPPED:
        return a
    if a.status is AnswerStatus.PREFILLED and a.confidence >= CONF_KEEP_GROUNDED:
        return a
    key = pf.field.key
    if pf.field.required:
        if a.status not in UNANSWERED:
            a = _answer_unknown(pf, "G9: untrusted site value")
        elif "G9" not in a.note:
            a.note = (a.note + "; G9: untrusted site value").strip("; ")[:300]
        return a
    if pf.field.type is FieldType.CHECKBOX:
        note = G9_NOTES["untick"]
    elif pf.field.type in TEXT_LIKE:
        note = G9_NOTES["clear"]
    elif pf.widget == "radio" or pf.field.type is FieldType.RADIO:
        # A picked radio can't be un-picked: kept, flagged (in an entry group E6 deletes it).
        return Answer(field_key=key, value=pf.shown, tier=AnswerTier.NONE, source=pf.origin.value,
                      confidence=CONF_UNVERIFIED, status=AnswerStatus.PREFILLED,
                      note=UNVERIFIED_NOTE, rule_id=RULE_ID, sensitive=a.sensitive)
    else:
        note = G9_NOTES["reset"]
    resets.append(key)
    return Answer(field_key=key, value=None, tier=AnswerTier.NONE, source=pf.origin.value,
                  confidence=0.0, status=AnswerStatus.BLANK_OPTIONAL, note=note,
                  rule_id=RULE_ID, sensitive=a.sensitive)


def _stamp(a: Answer, pf: PageField) -> Answer:
    a.shown = pf.shown
    a.origin = pf.origin.value
    a.entry = pf.group
    return a


def decide(fields: Sequence[PageField], locks: Mapping[str, Answer], decisions: Any,
           facts: Sequence[Fact], rctx: ResolveContext, *,
           matches: Mapping[str, Optional[str]],
           second: Optional[Callable[[PageField], ModelDecision]], today: str,
           rules: Any = None, sections: Sequence[EntrySection] = (), model: str = "",
           prompt_hashes: Optional[Mapping[str, str]] = None,
           cfg: Optional[Mapping[str, Any]] = None,
           blocks: Optional[Mapping[str, str]] = None) -> Decision:
    """Every field -> one Answer, plus the stop list and the entry/G9 actions (§7, §10).
    Pure apart from `second` (the G5 call). Extra keywords (rules, sections, model,
    prompt_hashes, cfg, blocks) are optional so the pinned call works; pagefill passes
    them: rules for G2 tier-2 matches, sections for delete/add controls, the model name
    and per-field prompt hashes for the audit, the `apply.llm_fill` block for
    `second_opinion`."""
    c = _Ctx(list(fields), dict(locks), list(facts), rctx, dict(matches), second, today, rules,
             list(sections), model, prompt_hashes, cfg, blocks)
    ds = _by_key(decisions)
    answers: dict[str, Answer] = {}
    resets: list[str] = []
    for pf in c.fields:
        key = pf.field.key
        lock = c.locks.get(key)
        # A lock is final: the model's decision for that key (if any) is never read.
        a = replace(lock) if lock is not None else _field(c, pf, ds.get(key))
        a = _stamp(a, pf)
        a = _stamp(_leftovers(c, pf, a, resets), pf)
        answers[key] = a
    deletes, adds = _entries(c, answers, resets)
    gone = set(deletes)
    unknown = tuple(pf.field.key for pf in c.fields
                    if pf.field.required and answers[pf.field.key].status in UNANSWERED
                    and pf.group not in gone)
    return Decision(answers=answers, unknown_required=unknown, deletes=tuple(deletes),
                    adds=tuple(adds), resets=tuple(k for k in resets if k in answers
                                                   and reset_action(answers[k])))


def _entry_group(c: _Ctx, gid: str):
    for sec in c.sections:
        for g in sec.entries:
            if F.group_id(sec.section, g.index) == gid:
                return sec, g
    return None, None


def _entries(c: _Ctx, answers: dict[str, Answer],
             resets: list[str]) -> tuple[list[str], list[tuple[str, str]]]:
    """E3 junk deleted, E6 ungroundable optional entries deleted, E5 missing added."""
    groups = list(dict.fromkeys(pf.group for pf in c.fields if pf.group))
    deletes: list[str] = []
    dropped_sources: set[str] = set()

    def drop(gid: str, note: str) -> None:
        deletes.append(gid)
        for pf in c.fields:
            if pf.group == gid:
                a = answers[pf.field.key]
                answers[pf.field.key] = _stamp(Answer(
                    field_key=pf.field.key, value=None, tier=AnswerTier.NONE, source="",
                    confidence=0.0, status=AnswerStatus.SKIPPED, note=note,
                    sensitive=a.sensitive), pf)
                if pf.field.key in resets:
                    resets.remove(pf.field.key)

    for gid in groups:
        sec, g = _entry_group(c, gid)
        deletable = bool(g is not None and g.delete_locator)
        entry = c.matches.get(gid)
        gf = [pf for pf in c.fields if pf.group == gid]
        if not entry:
            if deletable:
                drop(gid, "E3: junk entry deleted")
            else:
                for pf in gf:
                    a = answers[pf.field.key]
                    if pf.field.required and a.status not in UNANSWERED:
                        answers[pf.field.key] = _stamp(_answer_unknown(
                            pf, "E3: unmatched entry, no delete control"), pf)
            continue
        bad = any(pf.field.required and answers[pf.field.key].status in UNANSWERED for pf in gf) \
            or any(answers[pf.field.key].note == UNVERIFIED_NOTE for pf in gf)
        if not bad or not deletable:
            continue
        others = [x for x in (sec.entries if sec else ())
                  if F.group_id(sec.section, x.index) != gid
                  and F.group_id(sec.section, x.index) not in deletes]
        if (sec is not None and not sec.required) or others:
            drop(gid, "E6: ungroundable entry deleted")
            dropped_sources.add(entry)
    adds: list[tuple[str, str]] = []
    matched = {v for v in c.matches.values() if v}
    for sec in c.sections:
        if not sec.add_locator:
            continue
        kind = F.SECTION_KINDS.get(sec.section)
        if kind not in ("experience", "education", "language", "link"):
            continue
        for eid, _n, _t, _b in F.source_entries(kind, c.rctx):
            if kind in ("language", "link") and not (eid.startswith("languages[")
                                                     or eid.startswith("links.")):
                continue                                  # E5: only from the profile
            if eid not in matched and eid not in dropped_sources:
                adds.append((sec.section, eid))
    return deletes, adds
