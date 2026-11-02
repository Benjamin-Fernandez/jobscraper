"""Tier 4: declarations and attestations (apply_design §7.5, PRD F-33, D-55).

Questions like "Are you a politically exposed person?", "Do you hold shares
in this company?" or "Have you previously worked for us?" are statements the
owner signs. They are answered only from the profile's standing declarations
(D-55: "No" unless the owner says otherwise) and from facts in the data
(prior employment from `experience[]`, a previous application from the
store) - never by the model, and never by guessing: a question that looks like
an attestation but cannot be pinned to one class fails closed.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from .contracts import (
    Answer, AnswerStatus, AnswerTier, DeclarationLabel, FieldType, FormField, ResolveContext,
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
    L.NON_COMPETE: ("non compete", "restrictive covenant", "non solicitation",
                    "bound by any agreement", "restraint of trade"),
    L.HEALTH: ("medical condition", "health condition", "mental health", "medical history",
               "illness"),
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


def _has_run(hay: list[str], needle: tuple[str, ...]) -> bool:
    n = len(needle)
    return any(tuple(hay[i:i + n]) == needle for i in range(len(hay) - n + 1))


def classify(label_norm: str, description_norm: str = ""):
    """The declaration class of a question (§7.5), AMBIGUOUS, or None.

    A class matches when one of its phrases occurs as a contiguous token run
    in label + description. (The tier-2 rule that a one-word phrase needs a
    label of 4 tokens or fewer is not applied here: attestations are long
    sentences, and a miss must fail closed, not fall through to the model.)
    Exactly one class -> it; several -> AMBIGUOUS, except that "current" and
    "prior" employee together resolve by D-69 precedence; none -> AMBIGUOUS
    when the label carries an attestation marker, else None."""
    text = f"{label_norm} {description_norm}".split()
    hits = {lab for lab, phrases in _PHRASE_TOKENS.items()
            if any(_has_run(text, p) for p in phrases)}
    if {L.CURRENT_EMPLOYEE, L.PRIOR_EMPLOYMENT} <= hits:
        hits -= {L.CURRENT_EMPLOYEE, L.PRIOR_EMPLOYMENT}
        hits.add(L.PRIOR_EMPLOYMENT if _PRIOR_HINTS & set(text) else L.CURRENT_EMPLOYEE)
    if len(hits) == 1:
        return next(iter(hits))
    if len(hits) > 1:
        return AMBIGUOUS
    if ATTESTATION_MARKERS & set(label_norm.split()):
        return AMBIGUOUS
    return None


def is_negated(label_norm: str) -> bool:
    """A "tick = I am clear" checkbox: the label says not / never / no /
    none of / neither."""
    toks = label_norm.split()
    return any(_has_run(toks, n) for n in _NEGATIONS)


# --------------------------------------------------------------------------
# Rules (§7.5): the truth of each declaration for this employer
# --------------------------------------------------------------------------

_PLAIN_BOOLS = frozenset({L.PEP, L.CONFLICT_AUDIT_INDEPENDENCE, L.CRIMINAL_RECORD,
                          L.BANKRUPTCY, L.REGULATORY, L.NON_COMPETE})


def truth(label: DeclarationLabel, profile: dict, employer: str,
          aliases: Iterable[str] = (), previously_applied: bool = False) -> Optional[bool]:
    """True/False for a declaration class; None for `health` (never a bool).
    D-55: the standing declarations default to No."""
    decl = (profile or {}).get("declarations") or {}
    aliases = tuple(aliases)
    if label in _PLAIN_BOOLS:
        return bool(decl.get(label.value, False))
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

    AMBIGUOUS -> unknown (required) / blank_optional. `health` -> blank when
    optional, the decline option when required and offered, else unknown.
    Every other class is a bool mapped by §7.3.2; a single checkbox is ticked
    when the statement on it is true ("I am not a PEP" is true when the pep
    declaration is false), and a required box that must stay unticked is
    unknown: a false statement is never ticked to get past validation."""
    from .resolve import fit_bool, fit_decline       # resolve imports this module

    if label is AMBIGUOUS:
        return _ended(f, "", "attestation not recognised: " + norm_label(f.label)[:120])
    src = f"declaration:{label.value}"
    if label is L.HEALTH:
        if not f.required:
            return _ended(f, label.value, "health question left blank")
        fit = fit_decline(f)
        if fit is None:
            return _ended(f, label.value, "health question with no decline option")
    else:
        value = truth(label, ctx.profile, ctx.employer_name, ctx.employer_aliases,
                      ctx.previously_applied)
        if f.type is FieldType.CHECKBOX:
            tick = (not value) if is_negated(norm_label(f.label)) else bool(value)
            if not tick and f.required:
                return _ended(f, label.value, "required box states something untrue")
            fit = ("true" if tick else "false", ())
        else:
            fit = fit_bool(f, value)
        if fit is None:
            return _ended(f, label.value, "no offered option fits the declaration")
    v, labels = fit
    return Answer(field_key=f.key, value=v, tier=AnswerTier.DECLARATION, source=src,
                  confidence=0.95, status=AnswerStatus.FILLED, option_labels=tuple(labels),
                  rule_id=label.value, sensitive=True)
