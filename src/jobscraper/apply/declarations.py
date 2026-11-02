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

import re
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
# --- the question frame (D-90; review Q-48 F1-F5, F7) ------------------------
# A declaration class answers only when the question is a STATUS question about the
# applicant ("Are you bound by ...?", "Have you ever been convicted ...?"), its
# polarity is known, and the field can carry a Yes/No. The owner's standing "No"
# is only the right answer to that frame; a willingness, consent or
# acknowledgement question mentioning the same noun needs the owner (ADR-0003).
#
# One negation list, here (D-90 (3), F3, F10): a Yes/No question holding one of
# these is not mapped to a bool (it ends unknown, never inverted).
NEGATIONS = (
    ("not",), ("never",), ("no",), ("none",), ("neither",), ("nor",), ("without",),
    ("nothing",), ("nobody",), ("cannot",), ("unable",), ("lack",), ("devoid",),
    ("absent",), ("exempt",), ("unrestricted",), ("unencumbered",), ("unrestrained",),
    ("free", "of"), ("free", "from"), ("clear", "of"), ("clear", "from"),
    ("absence", "of"),
    ("don't",), ("doesn't",), ("didn't",), ("haven't",), ("hasn't",), ("hadn't",),
    ("isn't",), ("aren't",), ("wasn't",), ("weren't",), ("can't",), ("won't",),
    ("wouldn't",), ("couldn't",), ("shouldn't",), ("cant",), ("dont",),
)
# A trailing answer hint ("... convicted? (Yes/No)") is not a negation (LF review F6).
ANSWER_HINTS = (("yes", "no"), ("yes", "or", "no"), ("y", "n"), ("no", "yes"),
                ("no", "or", "yes"))
# Willingness / consent / acknowledgement frames: never a declaration status.
_WILLINGNESS = frozenset({
    "willing", "willingness", "agree", "agrees", "consent", "consents", "accept", "accepts",
    "acknowledge", "acknowledges", "acknowledgement", "acknowledgment", "comply", "abide",
    "understand", "understood", "read", "prepared", "sign", "signing", "object", "objection",
    "objections", "wish", "want", "prefer", "familiar", "comfortable", "interested", "keen",
    "knowledge", "experience"})
# Deliberately NOT here: "know" (the relatives class: "know anyone who works") and
# "aware" ("Are you aware of any conflict of interest?" is a status question) - D-90a.
_WILLINGNESS_RUNS = (("able", "to", "sign"), ("will", "you", "sign"), ("would", "you", "sign"),
                     ("can", "you", "sign"), ("able", "to", "agree"), ("open", "to"),
                     ("happy", "to"))
# A question starts with one of these (§5.4 + did). A TEXT / TYPEAHEAD field is
# answered only when the label does (never a TEXTAREA): "Why do you want to join
# the public service?" is not a Yes/No question.
QUESTION_STARTERS = frozenset({"are", "is", "do", "does", "did", "have", "has", "had", "was",
                               "were", "will", "would", "can", "could"})
# The positive STATUS frame a Yes/No bool needs: the label starts with a status
# verb, or holds a status run (D-90 (2)).
_STATUS_STARTERS = frozenset({"are", "is", "do", "does", "did", "have", "has", "had", "was",
                              "were"})
_STATUS_RUNS = (("bound", "by"), ("subject", "to"), ("party", "to"), ("signed",), ("convicted",),
                ("charged",), ("hold",), ("holds",), ("held",), ("status",))
# A single checkbox is ticked only by a recognised attestation of the right
# polarity: "I am not bound by ..." / "I do not have ..." for a false profile
# value, "I am ..." / "I have ..." for a true one - never by a stray "no".
_ATTEST_LEADS = (("i", "confirm", "that"), ("i", "confirm"), ("i", "declare", "that"),
                 ("i", "declare"), ("i", "certify", "that"), ("i", "certify"),
                 ("i", "hereby", "confirm", "that"), ("i", "hereby", "declare", "that"),
                 ("i", "hereby", "confirm"), ("i", "hereby", "declare"),
                 ("i", "can", "confirm", "that"), ("i", "can", "confirm"), ("i", "attest"),
                 ("i", "attest", "that"))
_NEGATIVE_ATTESTATIONS = (
    ("i", "am", "not"), ("i", "am", "neither"), ("i", "am", "free", "of"),
    ("i", "am", "free", "from"), ("i", "do", "not", "have"), ("i", "don't", "have"),
    ("i", "have", "not"), ("i", "haven't"), ("i", "have", "never"), ("i", "have", "no"),
    ("i", "was", "not"), ("i", "wasn't"), ("i", "had", "no"), ("i", "hold", "no"),
    ("i'm", "not"), ("i", "do", "not", "hold"), ("i", "don't", "hold"),
    ("i", "am", "under", "no"), ("there", "is", "no"), ("there", "are", "no"))
# D-91: a "freedom" form answers the INVERTED value when it is the only negation and
# directly governs the matched class phrase ("Are you free from any restrictive
# covenants?" -> Yes when the owner is bound by none). Any other negation: unknown.
_FREEDOM_RUNS = (("free", "from"), ("free", "of"), ("clear", "of"), ("clear", "from"),
                 ("unrestricted", "by"), ("unencumbered", "by"), ("not", "bound", "by"),
                 ("not", "subject", "to"), ("not", "party", "to"))
_FREEDOM_FILLER = frozenset({"any", "a", "an", "the", "all", "such", "other", "existing",
                             "current", "prior", "previous", "of", "or", "and", "either"})
# D-91 nda_willingness: the only object a willingness frame may have and still be answered,
# and the consent verbs that make it a consent question (never object / read / understand).
_NDA_OBJECTS = (("nda",), ("ndas",), ("non", "disclosure"), ("nondisclosure",),
                ("confidentiality", "agreement"), ("confidentiality", "agreements"),
                ("confidentiality", "obligation"), ("confidentiality", "obligations"))
_NDA_CONSENT = frozenset({"willing", "willingness", "agree", "agrees", "consent", "consents",
                          "accept", "accepts", "comply", "abide", "prepared", "comfortable",
                          "sign", "signing"})
_NDA_CONSENT_RUNS = (("able", "to", "sign"), ("will", "you", "sign"), ("would", "you", "sign"),
                     ("can", "you", "sign"), ("happy", "to"), ("open", "to"))
# Disability, status frames only (D-90 (5)).
_DISABILITY_FRAMES = (("do", "you", "have"), ("have", "you", "ever", "had"),
                      ("are", "you", "a", "person", "with"), ("do", "you", "consider", "yourself"),
                      ("do", "you", "identify", "as"), ("disability", "status"),
                      ("have", "a", "disability"), ("are", "you", "disabled"))
# (a bare "I do not ..." is not one: "I do not wish to disclose ..." is no statement
# about the profile value, D-90a)
_POSITIVE_ATTESTATIONS = (("i", "am"), ("i", "have"), ("i", "hold"), ("i", "was"), ("i", "had"))
# A disability question about accommodation, adjustment or job performance is not
# "do you have a disability" (D-90 (5)): not answered from the owner's status.
_DISABILITY_OFF_FRAME = frozenset({
    "accommodation", "accommodations", "accommodate", "adjustment", "adjustments", "adjust",
    "prevent", "prevents", "limit", "limits", "affect", "affects", "perform", "performing",
    "comfortable", "require", "requires", "need", "needs", "assistance", "support",
    "arrangement", "arrangements", "wish", "disclose"})
# This employer (D-90 (4), Q-46c): a prior / current employment class applies only
# to a label that names it. Lower-case "us", never the country "US".
THIS_EMPLOYER_RUNS = (("us",), ("our",), ("we",), ("here",), ("this", "company"),
                      ("this", "employer"), ("this", "organisation"),
                      ("this", "organization"), ("this", "firm"), ("this", "bank"),
                      ("this", "group"), ("the", "company"), ("the", "employer"))

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


def strip_ns_exclusions(toks: list[str]) -> list[str]:
    """`toks` without its NS-exclusion runs: "not including national service" is
    not a negation of the question. The one implementation (review F10): the
    classifier, `negated_question` and lock L3/L7 all use it."""
    dropped = {i for a, b in _ns_exclusion_spans(toks) for i in range(a, b)}
    return [t for i, t in enumerate(toks) if i not in dropped]


def names_employer(toks: list[str], employer_names: Iterable[str] = (), raw: str = "") -> bool:
    """D-90 (4), Q-46c, D-89: the text names THIS employer: us / our / we / here /
    this or the company (see THIS_EMPLOYER_RUNS), or a run of tokens that
    `company_match`es the employer or one of its aliases (`employer_names`).
    `raw` is the unnormalised text: an upper-case "US" there is the country, not
    "us". The one implementation (facts.names_this_employer uses it too)."""
    for run in THIS_EMPLOYER_RUNS:
        if _has_run(toks, run):
            if run == ("us",) and raw and not re.search(r"\b[Uu]s\b", raw):
                continue
            return True
    for name in employer_names:
        width = len(_company_tokens(name or ""))
        for i in range(len(toks) if width else 0):
            for j in range(i + 1, min(len(toks), i + width + 2) + 1):
                if company_match(" ".join(toks[i:j]), name):
                    return True
    return False


def names_this_employer(label_raw: str, employer_names: Iterable[str] = ()) -> bool:
    """D-90 (4): `names_employer` for raw label text (the shared Q-46c / tier-4 test).
    An upper-case "US" is the country."""
    return names_employer(norm_label(label_raw or "").split(), employer_names, label_raw or "")


def employer_names_of(ctx: Optional[ResolveContext]) -> tuple[str, ...]:
    """The employer and its aliases, the `employer_names` of every caller."""
    if ctx is None:
        return ()
    return tuple(n for n in (ctx.employer_name, *(ctx.employer_aliases or ())) if n)


def _willing(label_toks: list[str]) -> bool:
    return bool(_WILLINGNESS & set(label_toks)) or any(_has_run(label_toks, r)
                                                       for r in _WILLINGNESS_RUNS)


def classify_all(label_norm: str, description_norm: str = "",
                 employer_names: Iterable[str] = (), *, raw_label: str = ""
                 ) -> tuple[frozenset[DeclarationLabel], bool]:
    """(classes, unsure): every declaration class a question matches (§7.5,
    D-87), and whether it is a question that cannot be pinned down (a
    government question that includes the military or says government-linked;
    a willingness question; an employer-class question that does not name this
    employer; a disability question about accommodation).

    1. A class matches when one of its phrases occurs as a contiguous token run
       in label + description (`disability`: in the label only).
    2. Longest match: a class's hit is dropped when every span it matched lies
       inside a longer span matched by another class ("worked for the
       government" beats prior employment's "worked for"; "senior government
       official" is a PEP question, not a government-employment one). D-89:
       prior / current employment also lose to a government span they share a
       token with.
    3. D-90 (4): prior / current employment apply only to a label that names
       THIS employer (`names_employer`; `employer_names` = the employer and its
       aliases; `raw_label` lets an upper-case "US" be the country). Without
       that reference the class does not match and the question is unsure
       (callers that pass no names never get an employer class: fail closed).
    4. "Current" and "prior" employee together resolve by D-69 precedence.
    5. The government/NS rule on `government_employment` (see _MILITARY).
    6. D-90 (2): a willingness / consent / acknowledgement label is unsure for
       every class.
    7. A disability label that is also about veterans, gender, race, religion
       or marital status, or about accommodation / adjustment / performing the
       job (D-90 (5)), is unsure and not the disability class."""
    label_toks = label_norm.split()
    text = f"{label_norm} {description_norm}".split()
    found: dict[DeclarationLabel, list[tuple[int, int]]] = {}
    for lab, phrases in _PHRASE_TOKENS.items():
        spans = _spans(label_toks if lab is L.DISABILITY else text, phrases)
        if spans:
            found[lab] = spans
    employer_ref = names_employer(label_toks, tuple(employer_names), raw_label)
    gov_spans = found.get(L.GOVERNMENT_EMPLOYMENT, [])

    def covered(lab: DeclarationLabel, a1: int, b1: int) -> bool:
        # R1: inside a longer span of another class. D-89: for the two employer
        # classes, also sharing a token with a government span ("Have you worked
        # for the government?": prior's "have you worked" sticks out of "worked
        # for the government").
        if any(other is not lab and b2 - a2 > b1 - a1 and a2 <= a1 and b1 <= b2
               for other, others in found.items() for a2, b2 in others):
            return True
        return lab in (L.PRIOR_EMPLOYMENT, L.CURRENT_EMPLOYEE) and not employer_ref \
            and any(a1 < b2 and a2 < b1 for a2, b2 in gov_spans)

    dropped = {lab for lab, spans in found.items()
               if all(covered(lab, a1, b1) for a1, b1 in spans)}
    hits = set(found) - dropped
    unsure = False
    if not employer_ref and hits & {L.PRIOR_EMPLOYMENT, L.CURRENT_EMPLOYEE}:
        hits -= {L.PRIOR_EMPLOYMENT, L.CURRENT_EMPLOYEE}
        unsure = True
    if {L.CURRENT_EMPLOYEE, L.PRIOR_EMPLOYMENT} <= hits:
        hits -= {L.CURRENT_EMPLOYEE, L.PRIOR_EMPLOYMENT}
        hits.add(L.PRIOR_EMPLOYMENT if _PRIOR_HINTS & set(text) else L.CURRENT_EMPLOYEE)

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
    if L.DISABILITY in hits and (
            _DISABILITY_OFF_FRAME & set(label_toks) or _has_run(label_toks, ("working", "with"))
            or not (len(label_toks) <= 3
                    or any(_has_run(label_toks, r) for r in _DISABILITY_FRAMES))):
        hits.discard(L.DISABILITY)
        unsure = True
    if hits and _willing(label_toks):
        if L.NON_COMPETE in hits and _nda_consent(label_toks, found.get(L.NON_COMPETE, [])):
            hits.discard(L.NON_COMPETE)          # D-91: the one exempt object
            hits.add(L.NDA_WILLINGNESS)
        else:
            unsure = True
    return frozenset(hits), unsure


def _nda_consent(label_toks: list[str], non_compete_spans: list[tuple[int, int]]) -> bool:
    """D-91: a consent / willingness question whose ONLY restrictive-agreement object
    is an NDA / confidentiality agreement or obligation. Not: another object (non
    compete, non solicit, stock terms), an objection / read / understand / acknowledge
    frame, or any negation."""
    nda = _spans(label_toks, _NDA_OBJECTS)
    if not nda or any(not any(a >= s and b <= e for s, e in nda)
                      for a, b in non_compete_spans if a < len(label_toks)):
        return False
    words = set(label_toks)
    if (_WILLINGNESS & words) - _NDA_CONSENT:
        return False
    if not ((_NDA_CONSENT - {"sign", "signing"}) & words
            or any(_has_run(label_toks, r) for r in _NDA_CONSENT_RUNS)):
        return False
    return not negated_question(" ".join(label_toks))


def classify(label_norm: str, description_norm: str = "", employer_names: Iterable[str] = (),
             *, raw_label: str = ""):
    """The declaration class of a question (§7.5), AMBIGUOUS, or None.
    `employer_names` (the employer and its aliases) and `raw_label` feed the
    D-90 (4) employer condition; see `classify_all`. Callers with a field use
    `classify_field`.

    Built on `classify_all`. (The tier-2 rule that a one-word phrase needs a
    label of 4 tokens or fewer is not applied here: attestations are long
    sentences, and a miss must fail closed, not fall through to the model.)
    Unsure -> AMBIGUOUS; exactly one class -> it; several -> AMBIGUOUS (the
    agreement rule in `answer` may still settle it); none -> AMBIGUOUS when
    the label carries an attestation marker, else None."""
    hits, unsure = classify_all(label_norm, description_norm, employer_names,
                                raw_label=raw_label)
    if unsure:
        return AMBIGUOUS
    if len(hits) == 1:
        return next(iter(hits))
    if len(hits) > 1:
        return AMBIGUOUS
    if ATTESTATION_MARKERS & set(label_norm.split()):
        return AMBIGUOUS
    return None


def classify_field(f: FormField, ctx: Optional[ResolveContext] = None):
    """`classify` for a form field: the one entry point every tier uses (tier 4,
    lock L3, the D-70 / L6 / capture checks), so the employer condition and the
    "US is the country" test see the field's real label and employer (D-90)."""
    return classify(norm_label(f.label), norm_label(f.description), employer_names_of(ctx),
                    raw_label=f.label or "")


def negated_question(label_norm: str) -> bool:
    """LF L7 / D-90 (3): a Yes/No (non-checkbox) question whose label holds a
    negation (NEGATIONS: not, never, no, none, neither, free of / from, clear of /
    from, unrestricted, unencumbered, absence of, cannot, unable ...) cannot be
    mapped to a bool safely: it ends unknown, never inverted. A trailing
    "(Yes/No)" hint and NS-exclusion runs are not negations."""
    toks = label_norm.split()
    for hint in ANSWER_HINTS:
        if len(toks) > len(hint) and tuple(toks[-len(hint):]) == hint:
            toks = toks[:-len(hint)]
            break
    toks = strip_ns_exclusions(toks)
    return any(_has_run(toks, n) for n in NEGATIONS)


def is_negated(label_norm: str) -> bool:
    """The label holds a negation (NEGATIONS), NS-exclusion runs aside. For a
    single checkbox the polarity itself comes from `attestation_polarity`."""
    toks = strip_ns_exclusions(label_norm.split())
    return any(_has_run(toks, n) for n in NEGATIONS)


def attestation_polarity(label_norm: str) -> Optional[bool]:
    """Polarity of a single checkbox's statement (D-90 (3)): False = a recognised
    NEGATIVE attestation ("I am not bound by ...", "I do not have ..."), True = a
    recognised positive one ("I am a ...", "I have ..." with no negation in it),
    None = anything else. A stray "no" ("I have read it and have no questions")
    is not a negative attestation."""
    toks = strip_ns_exclusions(label_norm.split())
    for lead in sorted(_ATTEST_LEADS, key=len, reverse=True):
        if tuple(toks[:len(lead)]) == lead:
            toks = toks[len(lead):]
            break
    for run in _NEGATIVE_ATTESTATIONS:
        if tuple(toks[:len(run)]) == run:
            return False
    if any(tuple(toks[:len(run)]) == run for run in _POSITIVE_ATTESTATIONS) \
            and not any(_has_run(toks, n) for n in NEGATIONS):
        return True
    return None


def _status_frame(label_toks: list[str]) -> bool:
    """The label asks the applicant's STATUS (D-90 (2)): it starts with have / has /
    are / is / do / did / ..., or holds bound by / subject to / party to / signed /
    convicted / hold ..."""
    toks = label_toks[1:] if label_toks[:1] in (["please"], ["kindly"]) else label_toks
    return bool(toks) and (toks[0] in _STATUS_STARTERS
                           or any(_has_run(toks, r) for r in _STATUS_RUNS))


def _starts_as_question(label_toks: list[str]) -> bool:
    toks = label_toks[1:] if label_toks[:1] in (["please"], ["kindly"]) else label_toks
    return bool(toks) and toks[0] in QUESTION_STARTERS


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
    if label is L.NDA_WILLINGNESS:
        # D-91: a willingness ANSWER, not a "no ties" fact: unset stays None (unknown).
        v = decl.get("willing_to_sign_nda")
        return v if isinstance(v, bool) else None
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
    gate = _field_gate(f)                    # D-90 gate 1: the field can carry a Yes/No
    if gate:
        return _ended(f, label.value, gate)
    if label is L.HEALTH:
        return _health_answer(f)
    value = truth(label, ctx.profile, ctx.employer_name, ctx.employer_aliases,
                  ctx.previously_applied)
    if label is L.DISABILITY:
        return _disability_answer(f, value)
    return _bool_answer(f, label.value, value, cls=label)


def _field_gate(f: FormField) -> str:
    """D-90 gate 1 (review F2): a declaration goes only onto a dropdown / radio, a
    single checkbox, or a TEXT / TYPEAHEAD box whose label opens like a question;
    never a TEXTAREA, a multi-select or any other type. "" = fine, else the note."""
    if f.type in (FieldType.DROPDOWN, FieldType.RADIO, FieldType.CHECKBOX):
        return ""
    if f.type in (FieldType.TEXT, FieldType.TYPEAHEAD) \
            and _starts_as_question(norm_label(f.label).split()):
        return ""
    return "not a yes/no question"


def _agreed(f: FormField, ctx: ResolveContext):
    """(classes, value) when a multi-class question's classes are all standing
    declarations with one and the same truth value (D-87 agreement rule), else
    None. A single checkbox never qualifies (ADR-0003: a tick is a signed
    statement and token rules can't tell each class's polarity), nor does an
    unsure question, nor a set holding an employer-specific class, `health` or
    `disability`."""
    if f.type is FieldType.CHECKBOX:
        return None
    classes, unsure = classify_all(norm_label(f.label), norm_label(f.description),
                                   employer_names_of(ctx), raw_label=f.label or "")
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


def _second_clause(gap: list[str]) -> bool:
    """The tokens between a freedom run and a class phrase open another clause (D-91)."""
    return bool(QUESTION_STARTERS & set(gap)) or _has_run(gap, ("i", "am")) \
        or _has_run(gap, ("i", "have"))


def _freedom_inverts(label_norm: str, cls: Optional[DeclarationLabel]) -> bool:
    """D-91: the label's only negation is a freedom form ("free from", "unrestricted
    by", "not bound by", ...) that directly governs the matched class phrase, so the
    field takes the INVERTED truth value. Every other negation, a second one, or a
    phrase the run does not govern: False (unknown, as D-90)."""
    if cls is None or cls not in _PHRASE_TOKENS:
        return False
    toks = label_norm.split()
    for hint in ANSWER_HINTS:
        if len(toks) > len(hint) and tuple(toks[-len(hint):]) == hint:
            toks = toks[:-len(hint)]
            break
    toks = strip_ns_exclusions(toks)
    spans = _spans(toks, _PHRASE_TOKENS[cls])
    for i, j in _spans(toks, _FREEDOM_RUNS):
        rest = toks[:i] + toks[j:]
        if any(_has_run(rest, n) for n in NEGATIONS) or not spans:
            continue
        # every matched phrase follows the run (or is the tail of it, "not bound by any
        # agreement") with no second clause between them (a question starter, "i am")
        governed = all(
            (s >= j and not _second_clause(toks[j:s])) or (i <= s < j < e)
            for s, e in spans)
        if governed:
            return True
    return False


def _bool_answer(f: FormField, name: str, value: Optional[bool], note: str = "",
                 cls: Optional[DeclarationLabel] = None) -> Answer:
    """A declaration bool onto a field (§7.3.2); `name` is the class (or the
    agreed classes joined by "+"; then `cls` is None). D-90: field type (gate 1),
    status frame (2), known polarity (3) - otherwise unknown / blank."""
    from .resolve import fit_bool                    # resolve imports this module

    gate = _field_gate(f)
    if gate:
        return _ended(f, name, gate)
    if value is None:
        return _ended(f, name, "no answer in the profile")
    label_norm = norm_label(f.label)
    toks = label_norm.split()
    if f.type is FieldType.CHECKBOX:
        if cls is L.NDA_WILLINGNESS:                 # D-91: "I agree to sign the NDA"
            polarity = None if is_negated(label_norm) else True
        else:
            polarity = attestation_polarity(label_norm)
            if polarity is None and _freedom_inverts(label_norm, cls):
                polarity = False
        if polarity is None:
            return _ended(f, name, "checkbox statement not recognised")
        tick = (not value) if polarity is False else bool(value)
        if not tick and f.required:
            return _ended(f, name, "required box left unticked")
        fit = ("true" if tick else "false", ())
    else:
        if negated_question(label_norm):
            if not _freedom_inverts(label_norm, cls):
                return _ended(f, name, "negated declaration question")
            value = not value
        if cls is not L.NDA_WILLINGNESS and not _status_frame(toks):
            return _ended(f, name, "not a status question")
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
            return _ended(f, name, "disability: no answer offered")     # never "declined" (F8)
        return _answer(f, name, fit)
    if f.type in CHOICE_TYPES and not bool_shaped(f):
        fit = fit_enum(f, "yes" if value else "no", DISABILITY_VALUE_MAP)
        if fit is None:
            return _ended(f, name, "no offered option fits the declaration")
        return _answer(f, name, fit)
    return _bool_answer(f, name, value, cls=L.DISABILITY)
