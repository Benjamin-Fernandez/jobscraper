"""F-50 matcher: which tracked application an email is about (MS section 7).

Design: docs/architecture/mail_status_design.md (MS) section 7, with amendment E1
(Oleeo-style tenants from the sender's subdomain, `compact()` names and
`tenants_from_hosts`). Requirement F-50j.

Pure: the flow hands in the parsed header, the body text and every tracked
application as an `AppCandidate` (store.mail_match_context, terminal ones
included, so a late email about a closed application doesn't attach to a
sibling). Nothing here reads the store, IMAP or a model.

Normalisation is applied the same way to both sides of every comparison: a
company or role name and the text it is looked for in go through `norm`, so
"Société Générale" in a subject matches "Societe Generale" on the application.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Iterable, Optional, Sequence
from urllib.parse import urlsplit

from .contracts import AppCandidate, MailBody, MailHeader, MatchKind, MatchResult, Signal
from .rules import Rules, platform_of, sender_platform

_PUNCT = re.compile(r"[^\w\s]|_")
_WS = re.compile(r"\s+")
_BRACKET_TAIL = re.compile(r"\s*[(\[{][^()\[\]{}]*[)\]}]\s*$")
ROLE_SHARE = 0.8        # MS 7: >= 80% of a role's tokens (at least 2) in one line
SHORT_NAME = 5          # a one-token variant under 5 characters counts in the body only as written

_STRONG = frozenset({Signal.EMPLOYER_DOMAIN, Signal.TENANT, Signal.NAME_IN_SENDER,
                     Signal.NAME_IN_SUBJECT})
_WEAK = frozenset({Signal.NAME_IN_BODY})


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def _fold(s: str) -> str:
    """NFKD with the accents dropped; capitalisation kept."""
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(s: str) -> str:
    """Accents stripped, casefolded, "&" -> "and", punctuation -> space, collapsed."""
    s = _fold(s or "").casefold().replace("&", " and ")
    return _WS.sub(" ", _PUNCT.sub(" ", s)).strip()


def norm_company(name: str, suffixes: Iterable[str] = ()) -> str:
    """MS 7: `norm`, then trailing `company_suffixes` tokens removed repeatedly
    ("Example Holdings Pte Ltd" -> "example"). The last token always stays, so a
    name made only of suffix words never becomes "" (which would match anything)."""
    suf = {norm(x) for x in suffixes}
    toks = norm(name).split()
    while len(toks) > 1 and toks[-1] in suf:
        toks.pop()
    return " ".join(toks)


def compact(s: str, suffixes: Iterable[str] = ()) -> str:
    """`norm_company(s)` with every space removed. Hyphens and underscores are
    punctuation to `norm`, so a tenant like "example-bank" compacts the same way:
    "Example Bank" -> "examplebank"."""
    return norm_company(s, suffixes).replace(" ", "")


def norm_role(title: str) -> str:
    """MS 7: bracketed suffixes such as "(m/f/d)" removed, then `norm` (the same
    folding as the text the role is looked for in)."""
    t = title or ""
    while True:
        cut = _BRACKET_TAIL.sub("", t)
        if cut == t:
            break
        t = cut
    return norm(t)


def variants(app: AppCandidate, rules: Rules) -> tuple[str, ...]:
    """The normalised names of an application's employer: its company names, its
    board slugs (hyphens as spaces), its tenants and the first label of each
    employer domain. De-duplicated, in that order, never ""."""
    suf = rules.company_suffixes
    raw = [*app.company_names, *(s.replace("-", " ") for s in app.board_slugs),
           *app.tenants, *(d.split(".")[0] for d in app.employer_domains)]
    out: list[str] = []
    for r in raw:
        v = norm_company(r, suf)
        if v and v not in out:
            out.append(v)
    return tuple(out)


def tenants_from_hosts(hosts: Iterable[Optional[str]], rules: Rules) -> tuple[str, ...]:
    """E1: the lower-case first label of each host that is a strict subdomain of a
    platform's `tenant_sites` suffix ("examplecorp.wd3.myworkdayjobs.com" ->
    "examplecorp"). Hosts are the attempt tenant_host plus the hosts of the job,
    application and careers URLs; a full URL is accepted too."""
    sites = [s for p in rules.platforms for s in p.tenant_sites]
    out: list[str] = []
    for raw in hosts:
        host = _host(raw)
        if not host:
            continue
        if any(host.endswith("." + s) for s in sites):
            label = host.split(".")[0]
            if label and label not in out:
                out.append(label)
    return tuple(out)


def _host(raw: Optional[str]) -> str:
    s = str(raw or "").strip().lower()
    if "://" in s:
        try:
            s = urlsplit(s).hostname or ""
        except ValueError:
            return ""
    return s.split("/")[0].split(":")[0].rstrip(".")


# ---------------------------------------------------------------------------
# Signals
# ---------------------------------------------------------------------------

def _has(hay: str, needle: str) -> bool:
    """`needle` occurs in `hay` as whole words (both already normalised)."""
    return bool(needle) and f" {needle} " in f" {hay} "


class _Mail:
    """The header and body, normalised once per `match` call."""

    def __init__(self, h: MailHeader, body: Optional[MailBody], rules: Rules):
        self.h = h
        self.rules = rules
        self.subject_raw = h.subject or ""
        self.text_raw = body.text if body is not None and body.text else ""
        self.sender = norm(h.from_name)
        self.subject = norm(self.subject_raw)
        self.text = norm(self.text_raw)
        self.text_folded = _fold(self.text_raw)        # for names that count only as written
        self.lines = [set(norm(line).split())
                      for line in (self.subject_raw, *self.text_raw.splitlines()) if line.strip()]
        self.regs = {r for r in (h.from_reg, *h.reply_to_regs) if r}
        self.tenant = _sender_tenant(h, rules)


def _sender_tenant(h: MailHeader, rules: Rules) -> str:
    """MS 7 `tenant`: the employer named by the sender, in compact form, when the
    From platform says where (its local part, or its strict subdomain)."""
    p = sender_platform(h, rules)
    if p is None:
        return ""
    if p.tenant_from_local_part:
        return compact(h.from_local, rules.company_suffixes)
    if p.tenant_from_subdomain:
        dom = (h.from_domain or "").lower()
        for d in p.domains:
            if dom.endswith("." + d):
                return compact(dom.split(".")[0], rules.company_suffixes)
    return ""


def _restricted(v: str, rules: Rules) -> bool:
    """A variant that body text alone may only match as written (MS 7, R5)."""
    return (" " not in v and len(v) < SHORT_NAME) or v in rules.common_word_names


def _written_forms(app: AppCandidate, rules: Rules) -> dict[str, set[str]]:
    """normalised variant -> its company names as written (accents dropped,
    capitalisation kept, suffixes removed). Slugs, tenants and domain labels are
    identifiers, not written names, so they have no written form: "sea" from a
    board slug must not match the ordinary word "sea" in a body."""
    suf = {norm(x) for x in rules.company_suffixes}
    out: dict[str, set[str]] = {}
    for name in app.company_names:
        toks = _PUNCT.sub(" ", _fold(name).replace("&", " and ")).split()
        while len(toks) > 1 and norm(toks[-1]) in suf:
            toks.pop()
        if toks:
            out.setdefault(norm(" ".join(toks)), set()).add(" ".join(toks))
    return out


def _written_in(text: str, form: str) -> bool:
    words = form.split()
    if not words or not text:
        return False
    pattern = r"(?<!\w)" + r"\s+".join(re.escape(w) for w in words) + r"(?!\w)"
    return re.search(pattern, text) is not None


def _role_hit(role: str, mail: _Mail) -> bool:
    r = norm_role(role)
    if not r:
        return False
    if _has(mail.subject, r) or _has(mail.text, r):
        return True
    toks = set(r.split())
    if len(toks) < 2:
        return False
    need = max(2, math.ceil(ROLE_SHARE * len(toks)))
    return any(len(toks & line) >= need for line in mail.lines)


def _req_hit(req_ids: Sequence[str], mail: _Mail) -> bool:
    for rid in req_ids:
        rid = (rid or "").strip()
        if not rid:
            continue
        pattern = re.compile(r"(?<!\w)" + re.escape(rid) + r"(?!\w)", re.IGNORECASE)
        if pattern.search(mail.subject_raw) or pattern.search(mail.text_raw):
            return True
    return False


def signals(app: AppCandidate, mail: _Mail) -> tuple[Signal, ...]:
    """Every MS 7 signal that holds for `app`, in `Signal` order."""
    h, rules = mail.h, mail.rules
    found: set[Signal] = set()
    if h.gm_thrid and h.gm_thrid in app.threads:
        found.add(Signal.THREAD)
    if mail.regs & set(app.employer_domains):
        found.add(Signal.EMPLOYER_DOMAIN)
    vs = variants(app, rules)
    if mail.tenant:
        names = {compact(t, rules.company_suffixes) for t in app.tenants}
        names |= {v.replace(" ", "") for v in vs}
        if mail.tenant in names:
            found.add(Signal.TENANT)
    if any(_has(mail.sender, v) for v in vs):
        found.add(Signal.NAME_IN_SENDER)
    if any(_has(mail.subject, v) for v in vs):
        found.add(Signal.NAME_IN_SUBJECT)
    written = None
    for v in vs:
        if _restricted(v, rules):
            written = _written_forms(app, rules) if written is None else written
            if any(_written_in(mail.text_folded, f) for f in written.get(v, ())):
                found.add(Signal.NAME_IN_BODY)
                break
        elif _has(mail.text, v):
            found.add(Signal.NAME_IN_BODY)
            break
    if _role_hit(app.role, mail):
        found.add(Signal.ROLE)
    if _req_hit(app.req_ids, mail):
        found.add(Signal.REQ_ID)
    return tuple(s for s in Signal if s in found)


def _tier(sigs: tuple[Signal, ...]) -> int:
    """Employer signal strength: 2 strong, 1 weak (body only), 0 none."""
    s = set(sigs)
    return 2 if s & _STRONG else 1 if s & _WEAK else 0


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------

def match(h: MailHeader, body: Optional[MailBody], apps: Sequence[AppCandidate],
          rules: Rules) -> MatchResult:
    """MS 7 decision steps 1-6. `signals` is the chosen application's signals, or
    for AMBIGUOUS the union over the candidates, in `Signal` order."""
    mail = _Mail(h, body, rules)
    platform = platform_of(h, rules)
    sig = {a.job_id: signals(a, mail) for a in apps}

    def one(app: AppCandidate, kind: MatchKind) -> MatchResult:
        return MatchResult(kind, app.job_id, (), sig[app.job_id], platform)

    def several(pool: Sequence[AppCandidate]) -> MatchResult:
        union = {s for a in pool for s in sig[a.job_id]}
        return MatchResult(MatchKind.AMBIGUOUS, None, tuple(a.job_id for a in pool),
                           tuple(s for s in Signal if s in union), platform)

    # 1. The thread decides alone; a shared thread narrows the candidates.
    pool = [a for a in apps if Signal.THREAD in sig[a.job_id]]
    if len(pool) == 1:
        return one(pool[0], MatchKind.STRONG)
    if not pool:
        pool = list(apps)
    # 2. Applications with an employer signal.
    emp = [a for a in pool if _tier(sig[a.job_id])]
    if not emp:
        return MatchResult(MatchKind.NONE, platform=platform)
    # 3. Across several companies, the strongest employer tier; a tie stays ambiguous.
    if _company_count(emp, rules) > 1:
        best = max(_tier(sig[a.job_id]) for a in emp)
        emp = [a for a in emp if _tier(sig[a.job_id]) == best]
        if _company_count(emp, rules) > 1:
            return several(emp)
    # 4. Role or requisition id separates applications at one employer.
    roles = [a for a in emp if {Signal.ROLE, Signal.REQ_ID} & set(sig[a.job_id])]
    if len(roles) == 1:
        return one(roles[0], MatchKind.STRONG)
    if len(roles) > 1:
        return several(roles)
    # 5-6. No role signal.
    if len(emp) == 1:
        strong = _tier(sig[emp[0].job_id]) == 2
        return one(emp[0], MatchKind.STRONG if strong else MatchKind.WEAK)
    return several(emp)


def _company_count(apps: Sequence[AppCandidate], rules: Rules) -> int:
    """How many companies `apps` span, by normalised name: two applications are at
    one company when any of their normalised company names agree. One with no
    company name is a company of its own."""
    groups: list[set[str]] = []
    for a in apps:
        names = {norm_company(n, rules.company_suffixes) for n in a.company_names} - {""}
        names = names or {"\x00" + a.job_id}
        joined = [g for g in groups if g & names]
        for g in joined:
            groups.remove(g)
            names |= g
        groups.append(names)
    return len(groups)
