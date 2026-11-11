"""Composed texts: a cover letter or a "why join" answer from the master resume.

Design: docs/architecture/llm_fill_design.md section 19.4 (the call and its checks C1-C7)
and 19.5 (audit, privacy); truthfulness rules reused from tailor_design.md 7.4 and 8.1
(`validate.numbers`, `validate.facts`, `validate.UPGRADE_WORDS`). PRD F-22, F-32, NF-02.

A cover letter can't be copied from anywhere, so the model writes the words and code
decides everything else: the prompt is built here in a fixed order, the whole user prompt
goes through the injected `redact` (the apply stage's S-value scrubber; stages don't import
each other), and the reply is accepted only if all seven deterministic checks pass. A
failure gets exactly one retry with a `FIX:` line; the second failure is the end
(`ok=False`, the caller turns the field into a question).

Privacy: no text (prompt, resume, reply) is ever logged or put into an issue detail or an
error. `PRIVATE_VALUE` details are a category, never the value, and the FIX line never
echoes them either.

Boundary: this module builds prompts and checks replies. The model call is the injected
`backend.complete` (backends.py is the only code that talks to a model).
"""
from __future__ import annotations

import hashlib
import inspect
import json
import logging
import re
from typing import Any, Callable, Iterable, Optional, Sequence

from .contracts import (COMPOSE_VERSION, ComposeRequest, ComposeResult, IssueCode,
                        MasterResume, ValidationIssue)
from .mapping import resume_text
from .terms import Dictionary, tokens
from .validate import UPGRADE_WORDS, facts, numbers

log = logging.getLogger(__name__)

TEMPERATURE = 0.3
SEED = 7
TOP_K = 20
JD_CHARS = 3000                 # the posting text sent to the model (design 19.4)
MIN_WORDS = {"letter": 80, "answer": 20}
LONG_DIGITS = 7                 # a digit run this long is a phone or id number, never a claim

_LETTER = "a short cover letter"
_ANSWER = "a short answer to the question"
COMPOSE_SYSTEM = (
    "Write {what} for this applicant and job.\n"
    "Use only facts in RESUME: every skill, tool, employer, school, project, number and date you mention\n"
    "must appear there. Name the employer and the role exactly as JOB gives them. Choose the RESUME facts\n"
    "that fit JOB best. Don't claim anything RESUME doesn't say: no new skills, no stronger verbs (don't\n"
    "say led, owned or managed unless RESUME does), no numbers it doesn't have. No contact details, no\n"
    "address, no name, no placeholders like [Name]. No salutation, greeting or sign-off: start with the\n"
    "first sentence of the body. Plain text in the first person, at most {n} words."
)
# The closing line of the user prompt (design 19.4 leaves its wording open): it only names the
# reply shape the schema already enforces.
FINAL_LINE = 'Reply as JSON: {"text": "<the text>"}.'

_SUFFIXES = frozenset({"pte", "ltd", "limited", "inc", "llc", "corp", "corporation", "co", "plc",
                       "group", "holdings", "the", "singapore", "sg", "bank"})   # as apply/declarations
_ALNUM = re.compile(r"[a-z0-9]+")
_WORD = re.compile(r"[A-Za-z]+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+|\b[a-z0-9-]+\.(?:com|net|org|io|dev|sg|co|ai|app)\b(?:/[^\s<>\"')\]]*)?",
                  re.IGNORECASE)
_DIGIT_RUN = re.compile(r"\+?\d(?:[\s\-().]?\d)+")
_PLACEHOLDER = re.compile(r"\[[^\]\n]*\]|<[^>\n]*>|lorem|your name|company name", re.IGNORECASE)
_PARA_BREAK = re.compile(r"\s*\n\s*")



# D-183 (llm_fill_design 19.4): words a letter or answer may open a sentence with without
# being a claim. A capitalised sentence-start word outside this list, the master, the JD and
# the names JOB gives is a fact candidate ("Stripe taught me ..." -> FACT_ADDED stripe).
COMMON_WORDS = frozenset("""
a about above across after afterwards again against all almost also although always am among an
and another any anyone anything are around as at away back be became because become been before
began being believe below beside besides between beyond both bring but by came can cannot could
current day despite did do does doing done down during each early either else enough especially
even ever every everything far few finally first following for from further gave get getting give
given go going gone good got great had has have having he her here hers herself him himself his
how however i if in indeed initially instead into is it its itself just keen kept know large last
later learned learning least led less let like likely little long made make making many may me
meanwhile might more moreover most much must my myself need never new next no none nor not now of
off often on once one only onto or other others our ours ourselves out over own particularly past
per perhaps plus prior quickly rather really recently regularly since small so some someone
something sometimes soon still strong such take taking than that the their theirs them themselves
then there therefore these they this those though through throughout thus time to together took
toward towards under until up upon us used using very was we well were what whatever when whenever
where whether which while who whom whose why will with within without would yes yet you your yours
yourself

alongside applying approaching aware beginning building built collaborating completing
contributing creating curious delivering designing developing driven eager enjoy enjoyed excited
exploring focused found gaining gained getting growing happy helping hoping hope improving
interested joining keen looking love managing motivated passionate practical proud pursuing
reading real reflecting seeing seeking shipping solving starting strengthening studying
supporting taught teaching testing thank thanks together translating trying turning understanding
wanting working writing
""".split())


def schema(max_chars: int) -> dict:
    return {"type": "object", "required": ["text"],
            "properties": {"text": {"type": "string", "maxLength": int(max_chars)}}}


def system_prompt(req: ComposeRequest) -> str:
    return COMPOSE_SYSTEM.format(what=_LETTER if req.kind == "letter" else _ANSWER, n=req.max_words)


def user_prompt(req: ComposeRequest, master_text: str) -> str:
    """JOB -> QUESTION -> RESUME -> final line, before redaction (design 19.4)."""
    question = "Cover letter" if req.kind == "letter" else req.question.strip()
    job = [f"Employer: {req.employer}"]
    if req.job_title:
        job.append(f"Title: {req.job_title}")
    if req.jd_text.strip():
        job.append(req.jd_text.strip()[:JD_CHARS])
    return "\n".join(["JOB:", *job, "", "QUESTION:", question, "", "RESUME:", master_text, "",
                      FINAL_LINE])


# --------------------------------------------------------------------------
# The checks (design 19.5): deterministic, all on the returned text
# --------------------------------------------------------------------------

def _tokset(names: Iterable[str]) -> set[str]:
    return {t.lower() for n in names for _s, _e, t in tokens(n)}


def _norm_company(name: str) -> list[str]:
    toks = _ALNUM.findall((name or "").lower())
    return [t for t in toks if t not in _SUFFIXES] or toks


def _has_run(hay: Sequence[str], needle: Sequence[str]) -> bool:
    n = len(needle)
    return n > 0 and any(list(hay[i:i + n]) == list(needle) for i in range(len(hay) - n + 1))


_OPENER = re.compile(r"(?:^|[.!?]\s+)([A-Za-z0-9][A-Za-z0-9+#]*(?:\.[A-Za-z0-9+#]+)*)")


def _opening_words(flat: str, req: ComposeRequest, master_text: str, allowed: set[str]) -> set[str]:
    """D-183: capitalised sentence/paragraph/line-start words (2+ letters, no digit) that are
    neither common words nor present, in any case, in the master, the JD or the names JOB
    gives. `validate.facts` exempts every sentence start; a composed text may not."""
    known = {w.lower() for w in _WORD.findall(
        " ".join([master_text, req.jd_text, req.employer, req.job_title, *req.employer_aliases]))}
    out: set[str] = set()
    for m in _OPENER.finditer(flat):
        tok = m.group(1)
        low = tok.lower()
        letters = sum(c.isalpha() for c in tok)
        if (tok[0].isupper() and letters >= 2 and not any(c.isdigit() for c in tok)
                and low not in COMMON_WORDS and low not in known and low not in allowed):
            out.add(low)
    return out


def _issue(code: IssueCode, detail: str = "") -> ValidationIssue:
    return ValidationIssue(code, None, detail)


def allowed_facts(req: ComposeRequest, master_text: str, dictionary: Dictionary,
                  attested: Iterable[str] = ()) -> set[str]:
    """The claim corpus for C3: the master's facts, the attested canonicals and the names
    the letter must use (employer, aliases, job title; every word of them)."""
    names = [req.employer, *req.employer_aliases, req.job_title]
    out = set(facts(master_text, dictionary))
    for term in attested:
        term = str(term).strip()
        if term:
            out |= {h.canonical.lower() for h in dictionary.hits(term)} | {term.lower()}
    for name in names:
        if name:
            out |= facts(name, dictionary)
    return out | _tokset(n for n in names if n)


def check(text: str, req: ComposeRequest, master_text: str, dictionary: Dictionary,
          attested: Iterable[str] = ()) -> list[ValidationIssue]:
    """C1-C7 on `text`; `[]` = clean. C1 failing returns at once (nothing else is
    worth judging in an empty or mis-sized text). Details are counts, offending tokens
    from the text, or a category; never an S value."""
    words = len(text.split())
    if not text.strip():
        return [_issue(IssueCode.EMPTY)]
    lo = min(MIN_WORDS.get(req.kind, MIN_WORDS["answer"]), req.max_words)        # C1
    if not lo <= words <= req.max_words:
        return [_issue(IssueCode.LENGTH, f"{words} words, allowed {lo}-{req.max_words}")]
    if len(text) > req.max_chars:
        return [_issue(IssueCode.LENGTH, f"{len(text)} chars, allowed {req.max_chars}")]
    issues: list[ValidationIssue] = []
    names = [n for n in (req.employer, *req.employer_aliases, req.job_title) if n]
    # C5 first: the private spans are blanked before the other checks, so no other issue
    # detail (a number, a fact token) can carry a piece of an S value into the FIX line.
    private, text = _private(text, req, master_text, names)

    ok_numbers = set(numbers(master_text, dictionary))                            # C2
    for n in names:
        ok_numbers |= set(numbers(n, dictionary))
    for tok in sorted(set(numbers(text, dictionary)) - ok_numbers):
        issues.append(_issue(IssueCode.NUMBER_ADDED, tok))

    # A paragraph or line start reads as a sentence start (validate.facts only knows ". ").
    flat = _PARA_BREAK.sub(". ", text)
    allowed = allowed_facts(req, master_text, dictionary, attested)
    claimed = set(facts(flat, dictionary)) | _opening_words(flat, req, master_text, allowed)
    for tok in sorted(claimed - allowed):
        issues.append(_issue(IssueCode.FACT_ADDED, tok))                          # C3

    have = {w.lower() for w in _WORD.findall(master_text)} | _tokset(names)       # C4
    seen: set[str] = set()
    for w in (w.lower() for w in _WORD.findall(text)):
        if w in UPGRADE_WORDS and w not in have and w not in seen:
            seen.add(w)
            issues.append(_issue(IssueCode.VERB_UPGRADE, w))

    issues += private                                                              # C5

    toks = _ALNUM.findall(text.lower())                                            # C6
    for other in req.other_employers:
        if _has_run(toks, _norm_company(other)):
            issues.append(_issue(IssueCode.OTHER_EMPLOYER, other))

    for m in _PLACEHOLDER.finditer(text):                                          # C7
        issues.append(_issue(IssueCode.PLACEHOLDER, m.group()[:40]))
    return issues


def _private(text: str, req: ComposeRequest, master_text: str,
             names: Sequence[str]) -> tuple[list[ValidationIssue], str]:
    """C5: (issues, `text` with every private span blanked). Details are categories
    ("value", "email", "digits", "url"), never the value."""
    out: list[ValidationIssue] = []
    spans: list[tuple[int, int]] = []
    for v in sorted({str(x).strip() for x in req.s_values if str(x).strip()}):
        if len(v) < 3:
            continue
        pat = r"(?<![A-Za-z0-9])" + r"\s+".join(re.escape(p) for p in v.split()) + r"(?![A-Za-z0-9])"
        hits = [m.span() for m in re.finditer(pat, text, re.IGNORECASE)]
        if hits:
            out.append(_issue(IssueCode.PRIVATE_VALUE, "value"))
            spans += hits
    hits = [m.span() for m in _EMAIL.finditer(text)]
    if hits:
        out.append(_issue(IssueCode.PRIVATE_VALUE, "email"))
        spans += hits
    hits = [m.span() for m in _DIGIT_RUN.finditer(text)
            if len(re.sub(r"\D", "", m.group())) >= LONG_DIGITS]
    if hits:
        out.append(_issue(IssueCode.PRIVATE_VALUE, "digits"))
        spans += hits
    known = (master_text + "\n" + "\n".join(names)).lower()
    no_mail = _EMAIL.sub(lambda m: " " * len(m.group()), text)       # "a@b.org" is not also a URL
    hits = [m.span() for m in _URL.finditer(no_mail) if m.group().lower().rstrip(".,;:!?") not in known]
    if hits:
        out.append(_issue(IssueCode.PRIVATE_VALUE, "url"))
        spans += hits
    chars = list(text)
    for a, b in spans:
        chars[a:b] = " " * (b - a)
    return out, "".join(chars)


def fix_line(issues: Sequence[ValidationIssue]) -> str:
    """`FIX: <codes and offending tokens>` for the retry. PRIVATE_VALUE adds its code only."""
    parts = []
    for i in issues[:10]:
        detail = "" if i.code is IssueCode.PRIVATE_VALUE else i.detail
        parts.append(f"{i.code.value} {detail}".strip())
    return "FIX: " + "; ".join(parts)


# --------------------------------------------------------------------------
# The call
# --------------------------------------------------------------------------

def _call(backend: Any, system: str, user: str, req: ComposeRequest,
          timeout: Optional[float] = None) -> str:
    """One completion under the schema; returns the reply's `text` ("" when unreadable).
    Per-call options go only to a backend that accepts them (the master-parse pattern)."""
    params = inspect.signature(backend.complete).parameters
    kw: dict[str, Any] = {}
    kw["format" if "format" in params else "schema"] = schema(req.max_chars)
    for name, value in (("temperature", TEMPERATURE), ("seed", SEED), ("top_k", TOP_K)):
        if name in params:
            kw[name] = value
    if timeout is not None and "timeout" in params:      # D-184: the attempt's time left, in seconds
        kw["timeout"] = float(timeout)
    comp = backend.complete(system, user, 2 * req.max_words + 100, **kw)
    try:
        data = json.loads(comp.text)
        text = data.get("text") if isinstance(data, dict) else None
    except (ValueError, TypeError, AttributeError):
        return ""
    return text.strip() if isinstance(text, str) else ""


def compose(req: ComposeRequest, master: MasterResume, dictionary: Dictionary, *, backend: Any,
            redact: Callable[[str, Sequence[str]], str],
            attested: Iterable[str] = (), timeout: Optional[float] = None) -> ComposeResult:
    """Write, check, retry once. `redact(text, req.s_values)` is applied to the whole user
    prompt (FIX line included) so no S value reaches the model. `timeout` (seconds, D-184)
    caps each model call; a timeout is a transport error. Never logs a text."""
    master_text = resume_text(master)
    system = system_prompt(req)
    base = user_prompt(req, master_text)
    model = getattr(backend, "model_id", "") or getattr(backend, "name", "") or ""
    issues: list[ValidationIssue] = []
    h = ""
    for attempt in (1, 2):
        user = base if attempt == 1 else base + "\n" + fix_line(issues)
        user = redact(user, req.s_values)
        h = hashlib.sha256((system + user).encode("utf-8")).hexdigest()[:16]
        try:
            text = _call(backend, system, user, req, timeout)
        except Exception as exc:    # any transport failure; the type name carries no personal text
            log.warning("compose: model call failed (%s)", type(exc).__name__)
            return ComposeResult(False, "", tuple(issues), model, h, attempt,
                                 f"transport: {type(exc).__name__}")
        issues = check(text, req, master_text, dictionary, attested)
        if not issues:
            log.info("compose: ok after %d attempt(s), %d words", attempt, len(text.split()))
            return ComposeResult(True, text, (), model, h, attempt, "")
        log.info("compose: attempt %d failed %s", attempt, sorted({i.code.value for i in issues}))
    return ComposeResult(False, "", tuple(issues), model, h, 2, "")
