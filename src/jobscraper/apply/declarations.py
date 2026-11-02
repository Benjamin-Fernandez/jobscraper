"""Tier 4: declarations and attestations (apply_design §7.5, PRD F-33, D-55).

Questions like "Are you a politically exposed person?", "Do you hold shares
in this company?" or "Have you previously worked for us?" are statements the
owner signs. They are answered only from the profile's standing declarations
(D-55: "No" unless the owner says otherwise) and from facts in the data
(prior employment from `experience[]`, a previous application from the
store) - never by the model, and never by guessing: a question that looks like
an attestation but cannot be pinned to one class fails closed.

D-87 (Q-48): the owner's standing answer to a declaration-type question is "No /
none / not applicable", never blank and never the model's guess. So restrictive
agreements of every kind (NDA, non-solicitation, stock grants), government or
military employment (National Service excluded) and disability (any country)
are classes here too, and a label that matches several classes which all
carry the same standing answer gets that answer (the agreement rule).
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from .contracts import (
    CHOICE_TYPES, Answer, AnswerStatus, AnswerTier, DeclarationLabel, FieldType, FormField,
    ResolveContext,
)
from .plan import norm_label

# Tokens dropped before comparing company names (only while others remain).
_COMPANY_NOISE = frozenset({"pte", "ltd", "limited", "inc", "llc", "corp", "corporation",
                            "co", "plc", "group", "holdings", "the", "singapore", "sg", "bank"})


def _company_tokens(name: str) -> list[str]:
    toks = norm_label(name or "").split()
    kept = [t for t in toks if t not in _COMPANY_NOISE]
    return kept or toks


def employer_norm(name: str) -> str:
    """The §7.5 company normalisation as one string ("Shopee Pte Ltd" ->
    "shopee"): the key of an `extra` entry's `by_employer` override and of a
    question sighting's employer (questions_design §6.2)."""
    return " ".join(_company_tokens(name))


def company_match(a: str, b: str) -> bool:
    """§7.5: both names normalised (§7.1) with legal-form and filler tokens
    dropped (only while other tokens remain); a match if equal or one token
    list is a prefix of the other. "DBS Bank Ltd" ~ "DBS"; "Grab" ~ "Grab
    Financial Group" (on a declaration a truthful Yes beats a wrong No)."""
    ta, tb = _company_tokens(a), _company_tokens(b)
    if not ta or not tb:
        return False
    n = min(len(ta), len(tb))
    return ta[:n] == tb[:n]


def _matches_employer(name: str, employer: str, aliases: Iterable[str]) -> bool:
    return any(company_match(name, e) for e in (employer, *aliases) if e)


def prior_employment(profile: dict, employer: str, aliases: Iterable[str] = ()) -> bool:
    """True if any `experience[].employer` company-matches the employer or one
    of its aliases (internships count, D-55)."""
    aliases = tuple(aliases)
    return any(isinstance(e, dict) and _matches_employer(str(e.get("employer") or ""),
                                                         employer, aliases)
               for e in (profile or {}).get("experience") or [])


def current_employment(profile: dict, employer: str, aliases: Iterable[str] = ()) -> bool:
    """D-69: true only if a matching `experience[]` entry has no end date."""
    aliases = tuple(aliases)
    return any(isinstance(e, dict) and e.get("end") in (None, "")
               and _matches_employer(str(e.get("employer") or ""), employer, aliases)
               for e in (profile or {}).get("experience") or [])


# --------------------------------------------------------------------------
# Classifier (§7.5)
# --------------------------------------------------------------------------

class _Ambiguous:
    """The classifier's "this is an attestation, but which one is unclear"."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "AMBIGUOUS"


AMBIGUOUS = _Ambiguous()     # module-level sentinel, not a DeclarationLabel (D-69)

L = DeclarationLabel
PHRASES: dict[DeclarationLabel, tuple[str, ...]] = {
    L.PEP: ("politically exposed", "pep", "prominent public function", "public office",
            "senior government official", "senior political"),
    L.CONFLICT_AUDIT_INDEPENDENCE: ("audit client", "independence", "conflict of interest",
                                    "conflicts of interest"),
    L.SHAREHOLDING: ("shares in", "shareholding", "shareholder", "financial interest",
                     "equity interest", "own securities", "stock in"),
    L.RELATIVES: ("relative", "relatives", "related to", "family member", "family members",
                  "friends or family", "know anyone who works", "close personal relationship"),
    L.CRIMINAL_RECORD: ("convicted", "criminal", "offence", "offense", "pending charges",
                        "court proceedings"),
    L.BANKRUPTCY: ("bankrupt", "bankruptcy", "insolvency", "insolvent", "judgment debt"),
    L.REGULATORY: ("regulatory", "disciplinary", "mas", "licence revoked", "license revoked",
                   "suspended", "censured", "investigated by"),
    # D-87: any agreement that limits the work you can do. "subject to any
    # restrictions" is left out on purpose: work-rights questions use it.
    L.NON_COMPETE: ("non compete", "non competes", "noncompete", "non competition",
                    "non solicitation", "non solicit", "nonsolicitation", "non disclosure",
                    "nondisclosure", "nda", "ndas", "confidentiality agreement",
                    "confidentiality agreements", "confidentiality obligation",
                    "confidentiality obligations", "restrictive covenant",
                    "restrictive covenants", "restrictive agreement", "restrictive agreements",
                    "restraint of trade", "garden leave", "bound by any agreement",
                    "agreement that restricts", "agreements that restrict",
                    "agreement that would restrict", "agreement restricting",
                    "agreements restricting", "agreement that prevents",
                    "agreement that would prevent", "agreement that prohibits",
                    "agreement that would prohibit", "stock option agreement",
                    "stock option agreements", "stock option or restricted stock",
                    "restricted stock grant", "restricted stock agreement",
                    "restricted stock unit agreement", "stock grant agreement",
                    "equity grant agreement"),
    # D-87: ever worked for the government. Applied through the government/NS
    # rule in classify_all (NS-inclusive and government-linked wording is not
    # decided here).
    L.GOVERNMENT_EMPLOYMENT: (
        "civil service", "civil servant", "civil servants", "public service", "public servant",
        "public sector", "public officer", "government service", "government employee",
        "government employees", "government employment", "government agency",
        "government agencies", "government ministry", "government department",
        "government body", "government bodies", "statutory board", "statutory boards",
        "government official", "public official", "worked for the government",
        "worked for government", "worked for a government", "worked for any government",
        "worked in the government", "worked in government", "work for the government",
        "working for the government", "employed by the government", "employed by government",
        "employed by a government", "employed by any government",
        "employed in the government", "employed in government", "have you worked in government",
        "have you worked in the government", "have you worked in the public sector",
        "have you worked in the public service", "have you worked in the civil service"),
    L.HEALTH: ("medical condition", "health condition", "mental health", "medical history",
               "illness"),
    # D-87: matched on the LABEL only (an EEO preamble in a description mentions
    # disability on every form).
    L.DISABILITY: ("disability", "disabilities", "disabled", "person with disability",
                   "persons with disabilities", "people with disabilities", "pwd", "pwds",
                   "handicap", "handicapped"),
    L.PRIOR_EMPLOYMENT: ("previously worked", "previously employed", "previously been employed",
                         "worked for us", "worked for", "employed by", "former employee",
                         "ex employee", "have you worked", "currently or previously employed"),
    L.CURRENT_EMPLOYEE: ("currently an employee", "current employee", "currently employed",
                         "currently work for", "currently working for", "currently work at",
                         "currently working at", "employee at", "employee of"),
    L.PREVIOUSLY_APPLIED: ("previously applied", "applied before", "have you applied",
                           "applied to this", "applied for a position"),
}
_PHRASE_TOKENS = {lab: tuple(tuple(norm_label(p).split()) for p in ps)
                  for lab, ps in PHRASES.items()}

ATTESTATION_MARKERS = frozenset({"declare", "declaration", "attest", "politically", "convicted",
                                 "bankrupt", "conflict", "disciplinary", "charged"})
# Tokens that make "current or prior employee" mean prior (D-69 precedence).
_PRIOR_HINTS = frozenset({"previously", "ever", "before", "former", "ex"})
# A single checkbox whose label has one of these is a "tick = I am clear" box.
_NEGATIONS = (("not",), ("never",), ("no",), ("none", "of"), ("neither",))
# D-87 / LF L7: a Yes/No question with one of these cannot be mapped to a bool
# safely ("Are you free of any non-compete?" - the answer is the opposite of the
# fact). The checkbox rule above ticks by the statement instead.
_QUESTION_NEGATIONS = (("not",), ("never",), ("no",), ("none",), ("neither",),
                       ("free", "of"), ("without",))
# A trailing answer hint ("... convicted? (Yes/No)") is not a negation (LF review F6).
_ANSWER_HINTS = (("yes", "no"), ("yes", "or", "no"), ("y", "n"), ("no", "yes"),
                 ("no", "or", "yes"))

# The employer-independent classes (D-87 agreement rule): each is a plain
# `declarations.<label>` fact, so several of them on one question can be
# compared. A set that holds an employer-specific class, `health` or
# `disability` is never agreed (D-70's prefill overwrite and LF L6's skip key off
# a single employer-specific class).
STANDING_DECLARATIONS = frozenset({
    L.PEP, L.CONFLICT_AUDIT_INDEPENDENCE, L.CRIMINAL_RECORD, L.BANKRUPTCY, L.REGULATORY,
    L.NON_COMPETE, L.GOVERNMENT_EMPLOYMENT,
})

# --- the government / National Service rule (apply_design §7.5, D-87) --------
# A "government employment" question that includes the military or National
# Service is not the owner's "No" (NS is real service), so it is only answered
# when NS is explicitly excluded; a question about NS itself belongs to
# `ns_status` (tier 2), not here.
_MILITARY = ("military", "armed forces", "armed services", "defence force", "defence forces",
             "defense force", "army", "navy", "air force", "national service", "ns", "nsf",
             "nsman", "saf", "conscription", "uniformed service", "uniformed services")
_UNSURE = ("government linked", "glc", "glcs", "government owned", "state owned",
           "state enterprise")
_EXCLUDING = ("excluding", "exclude", "excludes", "except", "other than", "apart from",
              "aside from", "besides", "save for", "not including", "not counting",
              "does not include", "do not include")
_NS_TERMS = ("national service", "full time national service", "ns", "nsf",
             "mandatory military service", "compulsory military service",
             "mandatory national service", "military service", "mandatory service",
             "compulsory service", "conscription")
_NS_EXCLUDED_AFTER = ("not included", "excluded", "not counted", "does not count")
_EXCL_WINDOW = 4     # an NS term must START within this many tokens after an exclusion run
_AFTER_WINDOW = 3    # an "excluded" marker must START within this many tokens after an NS term
# A disability label that also covers one of these is several questions at once.
_DISABILITY_COMPANIONS = frozenset({
    "veteran", "veterans", "gender", "genders", "race", "races", "ethnic", "ethnicity",
    "ethnicities", "religion", "marital"})


def _toks(phrases: Iterable[str]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(norm_label(p).split()) for p in phrases)


_MILITARY_TOKENS, _UNSURE_TOKENS = _toks(_MILITARY), _toks(_UNSURE)
_EXCLUDING_TOKENS, _NS_TOKENS = _toks(_EXCLUDING), _toks(_NS_TERMS)
_NS_AFTER_TOKENS = _toks(_NS_EXCLUDED_AFTER)


def _has_run(hay: list[str], needle: tuple[str, ...]) -> bool:
    n = len(needle)
    return any(tuple(hay[i:i + n]) == needle for i in range(len(hay) - n + 1))


def _spans(hay: list[str], needles: Iterable[tuple[str, ...]]) -> list[tuple[int, int]]:
    """(start, end) of every occurrence of any phrase in `needles`."""
    out = []
    for needle in needles:
        n = len(needle)
        out.extend((i, i + n) for i in range(len(hay) - n + 1) if tuple(hay[i:i + n]) == needle)
    return out


def _ns_exclusion_spans(toks: list[str]) -> list[tuple[int, int]]:
    """The token spans of every NS exclusion ("excluding mandatory military
    service", "not including national service", "national service is not
    included"): from the exclusion run through the NS term, or from the NS term
    through the marker. Empty when the question does not exclude NS."""
    ns = _spans(toks, _NS_TOKENS)
    out: list[tuple[int, int]] = []
    for start, end in _spans(toks, _EXCLUDING_TOKENS):
        near = [s for s in ns if end <= s[0] < end + _EXCL_WINDOW]
        if near:
            first = min(s[0] for s in near)
            out.append((start, max(s[1] for s in near if s[0] == first)))
    for s_start, s_end in ns:
        marks = [m for m in _spans(toks, _NS_AFTER_TOKENS) if s_end <= m[0] < s_end + _AFTER_WINDOW]
        if marks:
            out.append((s_start, max(m[1] for m in marks)))
    return out


def _strip_ns_exclusions(toks: list[str]) -> list[str]:
    """`toks` without its NS-exclusion runs: "not including national service" is
    not a negation of the question."""
    dropped = {i for a, b in _ns_exclusion_spans(toks) for i in range(a, b)}
    return [t for i, t in enumerate(toks) if i not in dropped]


def classify_all(label_norm: str, description_norm: str = ""
                 ) -> tuple[frozenset[DeclarationLabel], bool]:
    """(classes, unsure): every declaration class a question matches (§7.5,
    D-87), and whether it is a government-employment question that cannot be
    pinned down (it includes the military, or says government-linked).

    1. A class matches when one of its phrases occurs as a contiguous token run
       in label + description (`disability`: in the label only).
    2. Longest match: a class's hit is dropped when every span it matched lies
       inside a longer span matched by another class ("worked for the
       government" beats prior employment's "worked for"; "senior government
       official" is a PEP question, not a government-employment one).
    3. "Current" and "prior" employee together resolve by D-69 precedence.
    4. The government/NS rule on `government_employment` (see _MILITARY).
    5. A disability label that is also about veterans, gender, race, religion
       or marital status is unsure."""
    label_toks = label_norm.split()
    text = f"{label_norm} {description_norm}".split()
    found: dict[DeclarationLabel, list[tuple[int, int]]] = {}
    for lab, phrases in _PHRASE_TOKENS.items():
        spans = _spans(label_toks if lab is L.DISABILITY else text, phrases)
        if spans:
            found[lab] = spans
    dropped = {
        lab for lab, spans in found.items()
        if all(any(other is not lab and b2 - a2 > b1 - a1 and a2 <= a1 and b1 <= b2
                   for other, others in found.items() for a2, b2 in others)
               for a1, b1 in spans)}
    hits = set(found) - dropped
    if {L.CURRENT_EMPLOYEE, L.PRIOR_EMPLOYMENT} <= hits:
        hits -= {L.CURRENT_EMPLOYEE, L.PRIOR_EMPLOYMENT}
        hits.add(L.PRIOR_EMPLOYMENT if _PRIOR_HINTS & set(text) else L.CURRENT_EMPLOYEE)

    unsure = False
    gov = L.GOVERNMENT_EMPLOYMENT in hits
    govlike = bool(_spans(text, _UNSURE_TOKENS))
    mil = bool(_spans(text, _MILITARY_TOKENS))
    excl = bool(_ns_exclusion_spans(text))
    if gov and (govlike or (mil and not excl)):
        hits.discard(L.GOVERNMENT_EMPLOYMENT)
        unsure = True
    elif not gov and mil and excl and not govlike:
        hits.add(L.GOVERNMENT_EMPLOYMENT)
    if L.DISABILITY in hits and _DISABILITY_COMPANIONS & set(label_toks):
        unsure = True
    return frozenset(hits), unsure


def classify(label_norm: str, description_norm: str = ""):
    """The declaration class of a question (§7.5), AMBIGUOUS, or None.

    Built on `classify_all`. (The tier-2 rule that a one-word phrase needs a
    label of 4 tokens or fewer is not applied here: attestations are long
    sentences, and a miss must fail closed, not fall through to the model.)
    Unsure -> AMBIGUOUS; exactly one class -> it; several -> AMBIGUOUS (the
    agreement rule in `answer` may still settle it); none -> AMBIGUOUS when
    the label carries an attestation marker, else None."""
    hits, unsure = classify_all(label_norm, description_norm)
    if unsure:
        return AMBIGUOUS
    if len(hits) == 1:
        return next(iter(hits))
    if len(hits) > 1:
        return AMBIGUOUS
    if ATTESTATION_MARKERS & set(label_norm.split()):
        return AMBIGUOUS
    return None


def is_negated(label_norm: str) -> bool:
    """A "tick = I am clear" checkbox: the label says not / never / no /
    none of / neither (NS-exclusion runs such as "not including National
    Service" do not count, D-87)."""
    toks = _strip_ns_exclusions(label_norm.split())
    return any(_has_run(toks, n) for n in _NEGATIONS)


def negated_question(label_norm: str) -> bool:
    """LF L7 / D-87: a Yes/No (non-checkbox) question whose label says not /
    never / no / none / neither / free of / without cannot be mapped to a bool
    safely. A trailing "(Yes/No)" hint and NS-exclusion runs are not negations."""
    toks = label_norm.split()
    for hint in _ANSWER_HINTS:
        if len(toks) > len(hint) and tuple(toks[-len(hint):]) == hint:
            toks = toks[:-len(hint)]
            break
    toks = _strip_ns_exclusions(toks)
    return any(_has_run(toks, n) for n in _QUESTION_NEGATIONS)


# --------------------------------------------------------------------------
# Rules (§7.5): the truth of each declaration for this employer
# --------------------------------------------------------------------------

_PLAIN_BOOLS = frozenset({L.PEP, L.CONFLICT_AUDIT_INDEPENDENCE, L.CRIMINAL_RECORD,
                          L.BANKRUPTCY, L.REGULATORY, L.NON_COMPETE, L.GOVERNMENT_EMPLOYMENT})

# Option wording for the one disability answer (D-87): the EEO disability phrases
# plus the plain "no" / "yes" wordings other forms use.
DISABILITY_VALUE_MAP: dict[str, tuple[str, ...]] = {
    "yes": ("yes i have a disability", "i have a disability", "i am a person with disability",
            "person with disability"),
    "no": ("no i do not have a disability", "i do not have a disability",
           "no i don't have a disability", "i don't have a disability",
           "no disability", "i do not have any disability", "not a person with disability",
           "i am not a person with disability"),
}


def _disability(profile: dict) -> Optional[bool]:
    """`us_self_id.disability_status` as a bool: no -> False, yes -> True,
    decline / absent / anything else -> None (never guessed)."""
    v = ((profile or {}).get("us_self_id") or {}).get("disability_status")
    if isinstance(v, bool):
        return v
    word = str(v or "").strip().lower()
    return {"no": False, "yes": True}.get(word)


def truth(label: DeclarationLabel, profile: dict, employer: str,
          aliases: Iterable[str] = (), previously_applied: bool = False) -> Optional[bool]:
    """True/False for a declaration class; None for `health` (never a bool) and
    for a `disability` the owner declines. D-55: the standing declarations
    default to No."""
    decl = (profile or {}).get("declarations") or {}
    aliases = tuple(aliases)
    if label in _PLAIN_BOOLS:
        return bool(decl.get(label.value, False))
    if label is L.DISABILITY:
        return _disability(profile)
    if label is L.SHAREHOLDING:
        return bool(decl.get("shareholding_in_company")) or any(
            _matches_employer(str(h), employer, aliases) for h in decl.get("holdings") or [])
    if label is L.RELATIVES:
        return bool(decl.get("relatives_at_company")) or any(
            _matches_employer(str(r), employer, aliases)
            for r in decl.get("relatives_employers") or [])
    if label is L.PRIOR_EMPLOYMENT:
        return prior_employment(profile, employer, aliases)
    if label is L.CURRENT_EMPLOYEE:
        return current_employment(profile, employer, aliases)
    if label is L.PREVIOUSLY_APPLIED:
        return bool(previously_applied)
    return None


# --------------------------------------------------------------------------
# Tier 4: the value onto the field
# --------------------------------------------------------------------------

def _ended(f: FormField, label: str, note: str) -> Answer:
    """No answer, and no further tier: required -> unknown, optional -> blank."""
    return Answer(field_key=f.key, value=None, tier=AnswerTier.NONE, source="",
                  confidence=0.0,
                  status=AnswerStatus.UNKNOWN if f.required else AnswerStatus.BLANK_OPTIONAL,
                  rule_id=label, sensitive=True, note=note)


def answer(label, f: FormField, ctx: ResolveContext) -> Answer:
    """The tier-4 Answer for a classified field (§7.5). Always final: an
    attestation never goes on to the model.

    AMBIGUOUS -> the agreement rule (D-87), else unknown (required) /
    blank_optional. `health` -> blank when optional, the decline option when
    required and offered, else unknown. `disability` -> the profile's one
    disability answer (decline -> the decline option). Every other class is a
    bool mapped by §7.3.2; a single checkbox is ticked when the statement on it
    is true ("I am not a PEP" is true when the pep declaration is false), and a
    required box that must stay unticked is unknown: a false statement is never
    ticked to get past validation. A negated Yes/No question ("free of any
    non-compete?") ends unknown too (L7): the bool would be the wrong way round."""
    if label is AMBIGUOUS:
        agreed = _agreed(f, ctx)
        if agreed is None:
            return _ended(f, "", "attestation not recognised: " + norm_label(f.label)[:120])
        classes, value = agreed
        name = "+".join(sorted(c.value for c in classes))
        return _bool_answer(f, name, value, note=f"agreed: {name}")
    if label is L.HEALTH:
        return _health_answer(f)
    value = truth(label, ctx.profile, ctx.employer_name, ctx.employer_aliases,
                  ctx.previously_applied)
    if label is L.DISABILITY:
        return _disability_answer(f, value)
    return _bool_answer(f, label.value, value)


def _agreed(f: FormField, ctx: ResolveContext):
    """(classes, value) when a multi-class question's classes are all standing
    declarations with one and the same truth value (D-87 agreement rule), else
    None. A single checkbox never qualifies (ADR-0003: a tick is a signed
    statement and token rules can't tell each class's polarity), nor does an
    unsure question, nor a set holding an employer-specific class, `health` or
    `disability`."""
    if f.type is FieldType.CHECKBOX:
        return None
    classes, unsure = classify_all(norm_label(f.label), norm_label(f.description))
    if unsure or len(classes) < 2 or not classes <= STANDING_DECLARATIONS:
        return None
    values = {truth(c, ctx.profile, ctx.employer_name, ctx.employer_aliases,
                    ctx.previously_applied) for c in classes}
    return (classes, values.pop()) if len(values) == 1 and None not in values else None


def _answer(f: FormField, name: str, fit, note: str = "") -> Answer:
    v, labels = fit
    return Answer(field_key=f.key, value=v, tier=AnswerTier.DECLARATION,
                  source=f"declaration:{name}", confidence=0.95, status=AnswerStatus.FILLED,
                  option_labels=tuple(labels), rule_id=name, sensitive=True, note=note)


def _bool_answer(f: FormField, name: str, value: Optional[bool], note: str = "") -> Answer:
    """A declaration bool onto a field (§7.3.2); `name` is the class (or the
    agreed classes joined by "+")."""
    from .resolve import fit_bool                    # resolve imports this module

    label_norm = norm_label(f.label)
    if f.type is FieldType.CHECKBOX:
        tick = (not value) if is_negated(label_norm) else bool(value)
        if not tick and f.required:
            return _ended(f, name, "required box states something untrue")
        fit = ("true" if tick else "false", ())
    elif negated_question(label_norm):
        return _ended(f, name, "negated declaration question")
    else:
        fit = fit_bool(f, value)
    if fit is None:
        return _ended(f, name, "no offered option fits the declaration")
    return _answer(f, name, fit, note)


def _health_answer(f: FormField) -> Answer:
    from .resolve import fit_decline

    if not f.required:
        return _ended(f, L.HEALTH.value, "health question left blank")
    fit = fit_decline(f)
    if fit is None:
        return _ended(f, L.HEALTH.value, "health question with no decline option")
    return _answer(f, L.HEALTH.value, fit)


def _disability_answer(f: FormField, value: Optional[bool]) -> Answer:
    """The one disability answer (D-87) onto a field. A bool goes onto a
    bool-shaped field or a text box like any declaration (§7.3.2), onto a
    single checkbox by the negation rule, and onto any other choice by its
    wording (DISABILITY_VALUE_MAP). Declined (None): the decline option when
    one is offered, else required -> unknown, optional -> blank."""
    from .resolve import bool_shaped, fit_decline, fit_enum

    name = L.DISABILITY.value
    if value is None:
        fit = fit_decline(f)
        if fit is None:
            return _ended(f, name, "disability: declined, no decline option")
        return _answer(f, name, fit)
    if f.type in CHOICE_TYPES and not bool_shaped(f):
        fit = fit_enum(f, "yes" if value else "no", DISABILITY_VALUE_MAP)
        if fit is None:
            return _ended(f, name, "no offered option fits the declaration")
        return _answer(f, name, fit)
    return _bool_answer(f, name, value)
