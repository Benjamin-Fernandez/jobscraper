"""F-50 rules file loader, header and content gates, and the phrase classifier.

Design: docs/architecture/mail_status_design.md (MS) section 6.1 (the rules file
and its validation), 6.2 (gates), 6.3 (classifier and quote), 6.4 (domain
decisions, carried by the phrases themselves) and decision D-92 (an assessment
vendor never decides `interview`). Requirements F-50h, F-50i, F-50k, F-50t.

Pure: the only I/O is reading the YAML file in `load_rules`. The flow hands in a
parsed `MailHeader` and `MailBody` (URLs already replaced by "[link]"); nothing
here touches IMAP, the store or a model. Every sync is a new process that calls
`load_rules` again, so an edit to config/mail_rules.yaml applies at the next
check. A `RulesError` names the file and the entry and never holds mail text,
so the flow can log it as it is (sync code `rules_invalid`).
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional

import yaml

from .contracts import QUOTE_MAX, Category, MailBody, MailHeader, Reason, Tier, Verdict

VERSION = 1
KINDS = frozenset({"ats", "assessment", "scheduler"})
WHERE = frozenset({"any", "subject", "body"})
GATE_KEYS = ("auto_reply", "account", "job_alert", "outreach")
# Category keys the file may hold: no_change and unknown are decided by code (MS 6.1).
RULE_CATEGORIES = tuple(c for c in Category if c not in (Category.NO_CHANGE, Category.UNKNOWN))
ELLIPSIS = "…"

_TOP_KEYS = frozenset({"version", "platforms", "job_boards", "company_suffixes",
                       "common_word_names", "bulk", "gates", "categories", "dominates"})
_PLATFORM_KEYS = frozenset({"id", "kind", "domains", "tenant_from_local_part",
                            "tenant_from_subdomain", "tenant_sites"})
_PHRASE_KEYS = frozenset({"id", "re", "in", "calendar"})
_CATEGORY_KEYS = frozenset({"phrases", "weak"})
_BULK_KEYS = frozenset({"list_id", "precedence"})
_ID = re.compile(r"[a-z0-9_.]+")
_RULE_VALUES = {c.value: c for c in RULE_CATEGORIES}
# The content gate's order (MS 6.2) and the reason each gate stores.
_CONTENT_GATES = (("auto_reply", Reason.AUTO_REPLY), ("account", Reason.ACCOUNT_MAIL),
                  ("job_alert", Reason.JOB_ALERT), ("outreach", Reason.OUTREACH))


class RulesError(ValueError):
    """The rules file is unreadable or breaks MS 6.1. `entry_id` is the phrase or
    platform id (or the top-level key) at fault; the message names the file too."""

    def __init__(self, entry_id: str, message: str, *, path: str = ""):
        self.entry_id = entry_id
        self.message = message
        self.path = path
        super().__init__(f"{path + ': ' if path else ''}{entry_id}: {message}")


@dataclass(frozen=True)
class Phrase:
    """One phrase entry, its `re` compiled with IGNORECASE and wrapped as
    `(?<!\\w)(?:re)(?!\\w)`, so a phrase never matches inside a longer word."""
    id: str
    pattern: re.Pattern
    where: str = "any"         # any | subject | body
    calendar: bool = False     # hits only with a METHOD:REQUEST calendar part


@dataclass(frozen=True)
class Platform:
    id: str
    kind: str                                  # ats | assessment | scheduler
    domains: tuple[str, ...]
    tenant_from_local_part: bool = False       # <tenant>@myworkday.com
    tenant_from_subdomain: bool = False        # <tenant>.tal.net
    tenant_sites: tuple[str, ...] = ()         # career-site suffixes (E1)


@dataclass(frozen=True)
class CategoryRules:
    category: Category
    phrases: tuple[Phrase, ...]
    weak: tuple[Phrase, ...]    # plain words: they only mark status_words


@dataclass(frozen=True)
class Rules:
    platforms: tuple[Platform, ...]
    job_boards: tuple[str, ...]
    company_suffixes: tuple[str, ...]          # casefolded
    common_word_names: frozenset[str]          # casefolded
    bulk_list_id: bool
    bulk_precedence: frozenset[str]
    gates: Mapping[str, tuple[Phrase, ...]]    # every GATE_KEYS key, maybe empty
    categories: tuple[CategoryRules, ...]      # file order: decides "the first hit"
    dominates: Mapping[Category, frozenset[Category]]
    source: str = ""

    def platform(self, platform_id: str) -> Optional[Platform]:
        return next((p for p in self.platforms if p.id == platform_id), None)


# ---------------------------------------------------------------------------
# 6.1 Loading and validation
# ---------------------------------------------------------------------------

def load_rules(path: str | Path) -> Rules:
    """Read and validate the rules file. Raises `RulesError` naming the file and
    the entry; never returns a partly valid `Rules`."""
    p = Path(path)
    try:
        raw = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise RulesError("file", f"can't be read ({type(exc).__name__})", path=p.name) from None
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" at line {mark.line + 1}" if mark is not None else ""
        raise RulesError("file", f"not valid YAML{where}", path=p.name) from None
    try:
        return build_rules(data, source=p.name)
    except RulesError as exc:
        raise RulesError(exc.entry_id, exc.message, path=p.name) from None


def build_rules(data: Any, *, source: str = "") -> Rules:
    """Validate an already-parsed rules document (MS 6.1) and compile it."""
    if not isinstance(data, dict):
        raise RulesError("file", "must be a mapping")
    _known(data, _TOP_KEYS, "file")
    version = data.get("version")
    if isinstance(version, bool) or version != VERSION:
        raise RulesError("version", f"must be {VERSION}")
    ids: set[str] = set()

    platforms = tuple(_platform(raw, i, ids) for i, raw in enumerate(_list(data, "platforms")))
    job_boards = tuple(_domain(d, "job_boards") for d in _list(data, "job_boards"))
    suffixes = tuple(_word(w, "company_suffixes") for w in _list(data, "company_suffixes"))
    common = frozenset(_word(w, "common_word_names") for w in _list(data, "common_word_names"))

    bulk = data.get("bulk") or {}
    if not isinstance(bulk, dict):
        raise RulesError("bulk", "must be a mapping")
    _known(bulk, _BULK_KEYS, "bulk")
    list_id = bulk.get("list_id", True)
    if not isinstance(list_id, bool):
        raise RulesError("bulk", "list_id must be true or false")
    precedence = frozenset(_word(w, "bulk") for w in _list(bulk, "precedence", "bulk"))

    raw_gates = data.get("gates") or {}
    if not isinstance(raw_gates, dict):
        raise RulesError("gates", "must be a mapping")
    _known(raw_gates, frozenset(GATE_KEYS), "gates")
    gates = {key: tuple(_phrase(raw, f"gates.{key}[{i}]", ids)
                        for i, raw in enumerate(_list(raw_gates, key, "gates")))
             for key in GATE_KEYS}

    raw_cats = data.get("categories") or {}
    if not isinstance(raw_cats, dict):
        raise RulesError("categories", "must be a mapping")
    categories = []
    for key, body in raw_cats.items():
        cat = _category(key, "categories")
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise RulesError(str(key), "a category must be a mapping of phrases and weak")
        _known(body, _CATEGORY_KEYS, str(key))
        phrases = tuple(_phrase(raw, f"{key}.phrases[{i}]", ids)
                        for i, raw in enumerate(_list(body, "phrases", str(key))))
        weak = tuple(_weak(w, f"{key}.weak[{i}]") for i, w in enumerate(_list(body, "weak", str(key))))
        categories.append(CategoryRules(cat, phrases, weak))

    raw_dom = data.get("dominates") or {}
    if not isinstance(raw_dom, dict):
        raise RulesError("dominates", "must be a mapping")
    dominates = {}
    for key, beaten in raw_dom.items():
        if not isinstance(beaten, list):
            raise RulesError("dominates", f"{key}: must be a list of categories")
        dominates[_category(key, "dominates")] = frozenset(_category(b, "dominates") for b in beaten)

    return Rules(platforms=platforms, job_boards=job_boards, company_suffixes=suffixes,
                 common_word_names=common, bulk_list_id=list_id, bulk_precedence=precedence,
                 gates=MappingProxyType(gates), categories=tuple(categories),
                 dominates=MappingProxyType(dominates), source=source)


def _known(mapping: dict, allowed: frozenset, entry: str) -> None:
    unknown = sorted(str(k) for k in mapping if k not in allowed)
    if unknown:
        raise RulesError(entry, f"unknown key {unknown[0]!r}")


def _list(mapping: dict, key: str, entry: str = "") -> list:
    value = mapping.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise RulesError(entry or key, f"{key} must be a list")
    return value


def _new_id(value: Any, entry: str, ids: set[str]) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise RulesError(entry, "id must match [a-z0-9_.]+")
    if value in ids:
        raise RulesError(value, "id is used twice")
    ids.add(value)
    return value


def _domain(value: Any, entry: str) -> str:
    if (not isinstance(value, str) or not value or value != value.lower()
            or "@" in value or any(c.isspace() for c in value)):
        raise RulesError(entry, f"{value!r} is not a lower-case domain without '@'")
    return value


def _word(value: Any, entry: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RulesError(entry, f"{value!r} must be a non-empty string")
    return value.strip().casefold()


def _category(value: Any, entry: str) -> Category:
    cat = _RULE_VALUES.get(value) if isinstance(value, str) else None
    if cat is None:
        raise RulesError(entry, f"{value!r} is not a rule category ({', '.join(_RULE_VALUES)})")
    return cat


def _platform(raw: Any, index: int, ids: set[str]) -> Platform:
    entry = f"platforms[{index}]"
    if not isinstance(raw, dict):
        raise RulesError(entry, "a platform must be a mapping")
    if isinstance(raw.get("id"), str):
        entry = raw["id"]
    _known(raw, _PLATFORM_KEYS, entry)
    pid = _new_id(raw.get("id"), entry, ids)
    kind = raw.get("kind")
    if kind not in KINDS:
        raise RulesError(pid, f"kind must be one of {', '.join(sorted(KINDS))}")
    domains = raw.get("domains")
    if not isinstance(domains, list) or not domains:
        raise RulesError(pid, "domains must be a non-empty list")
    flags = {}
    for key in ("tenant_from_local_part", "tenant_from_subdomain"):
        flags[key] = raw.get(key, False)
        if not isinstance(flags[key], bool):
            raise RulesError(pid, f"{key} must be true or false")
    if all(flags.values()):
        raise RulesError(pid, "tenant_from_local_part and tenant_from_subdomain can't both be true")
    sites = raw.get("tenant_sites") or []
    if not isinstance(sites, list):
        raise RulesError(pid, "tenant_sites must be a list")
    return Platform(id=pid, kind=kind, domains=tuple(_domain(d, pid) for d in domains),
                    tenant_sites=tuple(_domain(s, pid) for s in sites), **flags)


def _phrase(raw: Any, entry: str, ids: set[str]) -> Phrase:
    if not isinstance(raw, dict):
        raise RulesError(entry, "a phrase must be a mapping with id and re")
    if isinstance(raw.get("id"), str):
        entry = raw["id"]
    _known(raw, _PHRASE_KEYS, entry)
    pid = _new_id(raw.get("id"), entry, ids)
    rx = raw.get("re")
    if not isinstance(rx, str) or not rx:
        raise RulesError(pid, "re must be a non-empty string")
    where = raw.get("in", "any")
    if where not in WHERE:
        raise RulesError(pid, "in must be any, subject or body")
    calendar = raw.get("calendar", False)
    if not isinstance(calendar, bool):
        raise RulesError(pid, "calendar must be true or false")
    return Phrase(pid, _compile(rx, pid), where, calendar)


def _weak(raw: Any, entry: str) -> Phrase:
    if not isinstance(raw, str) or not raw.strip():
        raise RulesError(entry, "a weak entry must be a non-empty word")
    return Phrase(entry, _compile(re.escape(raw.strip()), entry))


def _compile(rx: str, entry: str) -> re.Pattern:
    try:
        return re.compile(rf"(?<!\w)(?:{rx})(?!\w)", re.IGNORECASE)
    except re.error as exc:
        raise RulesError(entry, f"re does not compile ({exc.msg})") from None


# ---------------------------------------------------------------------------
# Senders
# ---------------------------------------------------------------------------

def domain_matches(domain: str, base: str) -> bool:
    """Suffix match on labels: "us.greenhouse-mail.io" matches "greenhouse-mail.io"."""
    return bool(domain) and (domain == base or domain.endswith("." + base))


def sender_platform(h: MailHeader, rules: Rules) -> Optional[Platform]:
    """The platform the From address belongs to (From only: the tenant signal and
    D-92 read the sender, and Reply-To is the employer's address on most ATS mail)."""
    for domain in (h.from_domain, h.from_reg):
        for p in rules.platforms:
            if any(domain_matches(domain, d) for d in p.domains):
                return p
    return None


def platform_of(h: MailHeader, rules: Rules) -> str:
    """The rules platform id of the sender, or ""."""
    p = sender_platform(h, rules)
    return p.id if p else ""


def is_shared_domain(domain: str, rules: Rules) -> bool:
    """D-104 (a), review F1: a domain that is, or sits under, a platform domain, a
    `tenant_sites` suffix or a job board carries mail for many employers, so it is
    never one employer's domain ("tal.net" from acmebank.tal.net would otherwise
    match every other Oleeo tenant's mail). On those hosts the employer comes only
    from the tenant signal (E1)."""
    d = (domain or "").strip().lower().rstrip(".")
    if not d:
        return True
    bases = [*rules.job_boards, *(x for p in rules.platforms for x in (*p.domains, *p.tenant_sites))]
    return any(domain_matches(d, b) for b in bases)


def employer_regs_only(domains, rules: Rules) -> frozenset[str]:
    """The given registrable domains minus the shared ones (`is_shared_domain`)."""
    return frozenset(d.strip().lower() for d in domains
                     if d and not is_shared_domain(d, rules))


def _sender_domains(h: MailHeader) -> tuple[str, ...]:
    return tuple(d for d in (h.from_domain, h.from_reg, *h.reply_to_regs) if d)


# ---------------------------------------------------------------------------
# 6.2 Gates
# ---------------------------------------------------------------------------

def header_gate(h: MailHeader, rules: Rules, *, own: frozenset[str], window_start: str,
                threads: frozenset[str], employer_regs: frozenset[str]) -> Optional[Reason]:
    """MS 6.2 header gate, in order; the first hit decides. No body is read yet.
    `own` holds the owner's addresses, `threads` the gm_thrid values already
    matched to an application, `employer_regs` the registrable employer domains
    of every tracked application."""
    if window_start and h.received_at < window_start:
        return Reason.TOO_OLD
    owned = {a.lower() for a in own}
    if _own_label(h.labels) or (h.from_addr and h.from_addr.lower() in owned):
        return Reason.OWN_MAIL
    # RFC 3834: "auto-replied" is skipped; "auto-generated" is not (ATS notices use it).
    if (h.auto_submitted.lower().startswith("auto-replied") or h.autoreply_header
            or any(_first(p.pattern, h.subject) for p in rules.gates["auto_reply"]
                   if p.where == "subject")):
        return Reason.AUTO_REPLY
    senders = _sender_domains(h)
    if any(domain_matches(d, b) for d in senders for b in rules.job_boards):
        return Reason.JOB_BOARD
    in_thread = bool(h.gm_thrid) and h.gm_thrid in threads
    platform_mail = any(domain_matches(d, b) for d in senders
                        for p in rules.platforms for b in p.domains)
    # D-104 (a): a platform, careers-site or job-board domain is never an employer's.
    regs = employer_regs_only(employer_regs, rules)
    employer_mail = any(r in regs for r in (h.from_reg, *h.reply_to_regs) if r)
    if not (platform_mail or employer_mail or in_thread):
        return Reason.NOT_JOB_MAIL
    if not in_thread and ((rules.bulk_list_id and h.list_id)
                          or h.precedence in rules.bulk_precedence):
        return Reason.BULK
    return None


def _own_label(labels: tuple[str, ...]) -> bool:
    """Gmail's system labels \\Sent and \\Draft; a user label named "Sent" (no
    backslash) is not the owner's own mail."""
    for raw in labels:
        token = raw.strip().strip('"').replace("\\\\", "\\")
        if token.startswith("\\") and token[1:].lower() in ("sent", "draft"):
            return True
    return False


def content_gate(h: MailHeader, body: Optional[MailBody], rules: Rules, *,
                 in_matched_thread: bool) -> Optional[Reason]:
    """MS 6.2 content gate on the subject and body text: auto_reply, account,
    job_alert, then outreach (outreach only outside a matched thread)."""
    subject, text, calendar = _parts(h, body)
    for key, reason in _CONTENT_GATES:
        if key == "outreach" and in_matched_thread:
            continue
        if any(_search(p, subject, text, calendar) for p in rules.gates[key]):
            return reason
    return None


# ---------------------------------------------------------------------------
# 6.3 Classifier
# ---------------------------------------------------------------------------

def classify(h: MailHeader, body: Optional[MailBody], rules: Rules) -> Verdict:
    """MS 6.3. The first hit of a category is its first phrase (file order) that
    matches; within a phrase the body text is searched before the subject, so the
    quote is a sentence from the email when there is one (the subject is stored
    on the evidence row anyway)."""
    subject, text, calendar = _parts(h, body)
    first: dict[Category, tuple[Phrase, str, int, int]] = {}
    for cr in rules.categories:
        for p in cr.phrases:
            hit = _search(p, subject, text, calendar)
            if hit:
                first[cr.category] = (p, *hit)
                break
    hits = set(first)
    if len(hits) > 1:
        hits.discard(Category.PORTAL_UPDATE)
    if hits:
        winners = [w for w in hits if hits - {w} <= rules.dominates.get(w, frozenset())]
        if len(winners) == 1:
            w = winners[0]
            p, source, start, end = first[w]
            quote = quote_around(text if source == "text" else subject, start, end)
            category = w
            # D-92: an assessment vendor's "interview" is a one-way recorded one.
            if w is Category.INTERVIEW:
                vendor = sender_platform(h, rules)
                if vendor is not None and vendor.kind == "assessment":
                    category = Category.ASSESSMENT
            return Verdict(category, Tier.RULE, quote=quote, rule_id=p.id, status_words=True)
        names = "+".join(c.value for c in Category if c in hits)
        return Verdict(Category.UNKNOWN, Tier.RULE, rule_id=f"conflict:{names}", status_words=True)
    status_words = (calendar
                    or any(_search(w, subject, text, False)
                           for cr in rules.categories for w in cr.weak)
                    or mostly_non_latin(f"{subject} {text}"))
    return Verdict(Category.UNKNOWN, Tier.RULE, status_words=status_words)


def needs_model(v: Verdict) -> bool:
    """MS 5.4 step 6 / 6.5: a rule-tier UNKNOWN with status words (a conflict
    included) goes to the model; everything else is decided."""
    return v.tier is Tier.RULE and v.category is Category.UNKNOWN and v.status_words


def mostly_non_latin(s: str) -> bool:
    """At least 20% of the letters are not Latin (MS 6.3: non-English mail goes
    to the model, which reads it better than English phrases can)."""
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    other = sum(1 for c in letters
                if c >= "ɐ" and not unicodedata.name(c, "").startswith("LATIN"))
    return other * 5 >= len(letters)


def _parts(h: MailHeader, body: Optional[MailBody]) -> tuple[str, str, bool]:
    if body is None:
        return h.subject or "", "", False
    return h.subject or "", body.text or "", bool(body.calendar_request)


def _search(p: Phrase, subject: str, text: str, calendar: bool) -> Optional[tuple[str, int, int]]:
    """(source, start, end) of the phrase's first hit: text first, then subject."""
    if p.calendar and not calendar:
        return None
    if p.where in ("any", "body"):
        m = _first(p.pattern, text)
        if m:
            return ("text", *m)
    if p.where in ("any", "subject"):
        m = _first(p.pattern, subject)
        if m:
            return ("subject", *m)
    return None


def _first(pattern: re.Pattern, s: str) -> Optional[tuple[int, int]]:
    if not s:
        return None
    for m in pattern.finditer(s):
        if m.end() > m.start():
            return m.start(), m.end()
    return None


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------

_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+|\n")
_WS = re.compile(r"\s+")


def quote_around(text: str, start: int, end: int) -> str:
    """MS 6.3: the sentence holding text[start:end] (sentences split on
    `(?<=[.!?])\\s+` and newlines), whitespace collapsed. Longer than QUOTE_MAX:
    a window around the hit, cut at word boundaries and marked with "…" on each
    cut side; the result never exceeds QUOTE_MAX."""
    s, e = 0, len(text)
    for m in _SENTENCE_BREAK.finditer(text):
        if m.end() <= start:
            s = m.end()
        elif m.start() >= end:
            e = m.start()
            break
    sentence = _WS.sub(" ", text[s:e]).strip()
    if len(sentence) <= QUOTE_MAX:
        return sentence
    hs = min(len(_WS.sub(" ", text[s:start]).lstrip()), len(sentence))
    he = min(hs + len(_WS.sub(" ", text[start:end])), len(sentence))
    return _window(sentence, hs, he)


def _window(sentence: str, hs: int, he: int, limit: int = QUOTE_MAX) -> str:
    n = len(sentence)
    budget = limit - 2 - (he - hs)            # context room, two ellipses kept free
    if budget <= 0:                            # the hit alone is too long: keep its start
        a, b = hs, hs + limit - 2
        space = sentence.rfind(" ", a + 1, b)
        if space > a:
            b = space
    else:
        left = min(budget // 2, hs)
        right = min(budget - left, n - he)
        left = min(budget - right, hs)
        a, b = hs - left, he + right
        if a > 0 and sentence[a - 1] != " ":
            space = sentence.find(" ", a, hs)
            a = space + 1 if space >= 0 else hs
        if b < n and sentence[b] != " ":
            space = sentence.rfind(" ", he, b)
            b = space if space >= 0 else he
    piece = sentence[a:b].strip()
    return (ELLIPSIS if a > 0 else "") + piece + (ELLIPSIS if b < n else "")
