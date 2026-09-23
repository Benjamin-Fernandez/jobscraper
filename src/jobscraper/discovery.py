"""ATS resolution: careers URL -> (provider, slug, feed_url).

Run once per company and cached forever in `companies`. Re-resolution is only
triggered by repeated fetch failures (see runner.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from .adapters import parse_workday
from .models import Company
from .net import FetchError, HttpClient

# Host markers that identify a provider straight from the careers URL.
FINGERPRINTS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/([\w.-]+)", re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([\w.-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.-]+)", re.I)),
    ("smartrecruiters", re.compile(r"jobs\.smartrecruiters\.com/([\w.-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/([\w.-]+)", re.I)),
    ("recruitee", re.compile(r"([\w-]+)\.recruitee\.com", re.I)),
]

PROBES: dict[str, str] = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json&limit=1",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "smartrecruiters":
        "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=1",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{slug}",
    "recruitee": "https://{slug}.recruitee.com/api/offers/",
}

# Probe order matters: cheapest and most-common first.
PROBE_ORDER = ["greenhouse", "lever", "ashby", "smartrecruiters",
               "workable", "recruitee"]

STOPWORDS = {"inc", "ltd", "llc", "plc", "group", "corp", "corporation",
             "holdings", "technologies", "technology", "the", "co", "limited",
             "sg", "singapore", "global", "international"}


@dataclass
class Resolution:
    provider: Optional[str]
    slug: Optional[str]
    feed_url: Optional[str]
    method: str
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.provider is not None


SUBDOMAIN_NOISE = {"www", "careers", "career", "jobs", "job", "apply", "boards",
                   "recruiting", "talent", "hire", "hiring", "work", "join", "en"}
TLD_NOISE = {"com", "co", "uk", "net", "org", "io", "ai", "sg", "us", "eu",
             "inc", "dev", "app", "xyz", "asia", "jp", "hk", "cn", "au"}

# Job aggregators and social sites. A careers_url pointing at one of these says
# nothing about the company's own ATS, and the domain label is actively harmful
# as a slug: linkedin.com/company/mathrix/jobs once resolved Mathrix to
# LinkedIn's own Greenhouse board and scraped 53 of LinkedIn's postings.
AGGREGATOR_HOSTS = {
    "linkedin", "indeed", "glassdoor", "monster", "ziprecruiter", "dice",
    "jobstreet", "jobsdb", "mycareersfuture", "efinancialcareers", "wellfound",
    "angel", "otta", "levels", "builtin", "seek", "naukri", "zhipin", "lagou",
    "facebook", "twitter", "instagram", "youtube", "github", "notion",
    "docs", "forms", "bit", "tinyurl",
}

# Titles that mean the board is a demo account somebody never cleaned up.
SAMPLE_TITLE = re.compile(
    r"\b(sample|demo|dummy|test\s*job|example|your\s+(?:first\s+)?job|"
    r"lorem|placeholder|template)\b", re.I)


def is_aggregator(careers_url: str) -> bool:
    host = urlparse(careers_url or "").netloc.lower()
    labels = {x for x in host.split(".") if x}
    return bool(labels & AGGREGATOR_HOSTS)


def domain_slug(careers_url: str) -> Optional[str]:
    """Derive a slug from the careers domain.

    Usually a better signal than the display name: 'HRT' is unguessable, but
    www.hudsonrivertrading.com/careers gives 'hudsonrivertrading'.

    Returns None for aggregators - their domain names belong to them, not to
    the company we are looking for.
    """
    host = urlparse(careers_url or "").netloc.lower()
    if not host or "myworkdayjobs.com" in host:
        return None
    if is_aggregator(careers_url):
        return None
    labels = [x for x in host.split(".") if x]
    labels = [x for x in labels if x not in SUBDOMAIN_NOISE and x not in TLD_NOISE]
    return labels[0] if labels else None


def name_tokens(name: str) -> set[str]:
    """Comparable word-stems of a company name, stopwords removed."""
    cleaned = re.sub(r"[^\w\s]", " ", (name or "").lower())
    return {w for w in cleaned.split() if w and w not in STOPWORDS and len(w) > 2}


def _squashed(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def corroborates(company_name: str, board_name: Optional[str],
                 slug: str) -> bool:
    """Does this board plausibly belong to this company?

    A probe only proves the slug exists on that ATS - anyone can register
    `google.recruitee.com`. So the board has to agree it is us: either it
    reports a name overlapping ours, or - when the ATS exposes no name - the
    slug itself has to look like our name.
    """
    ours = name_tokens(company_name)
    squash_ours = _squashed(re.split(r"[/(]", company_name or "")[0])

    if board_name:
        theirs = name_tokens(board_name)
        if ours & theirs:
            return True
        sq = _squashed(board_name)
        return bool(sq and squash_ours and
                    (sq in squash_ours or squash_ours in sq))

    sq_slug = _squashed(slug)
    if not sq_slug or not squash_ours:
        return False
    return sq_slug in squash_ours or squash_ours in sq_slug


def slug_candidates(name: str, careers_url: str = "") -> list[str]:
    """Plausible ATS slugs, most likely first."""
    primary = re.split(r"[/(]", name)[0].strip()
    cleaned = re.sub(r"[^\w\s-]", " ", primary.lower())
    words = [w for w in cleaned.split() if w and w not in STOPWORDS]
    if not words:
        words = cleaned.split()
    out: list[str] = []
    dom = domain_slug(careers_url)
    if dom:
        out.append(dom)
    joined = "".join(words)
    hyphen = "-".join(words)
    for c in (joined, hyphen, words[0] if words else "", joined.replace(".", "")):
        if c and c not in out and len(c) >= 2:
            out.append(c)
    # "Alibaba / AliCloud" -> also try the second alternative.
    if "/" in name:
        alt = re.sub(r"[^\w]", "", name.split("/")[1].strip().lower())
        if alt and alt not in out:
            out.append(alt)
    return out[:5]


def _plausible(provider: str, payload: object) -> bool:
    """Does the probe response look like a job board with actual jobs on it?

    A slug that exists but returns zero postings is almost always the wrong
    slug (HRT -> ashby/hrt, Optiver -> greenhouse/optiver). Accepting it would
    silently monitor an empty board forever, so require at least one posting
    and let the ladder fall through to the HTML sniff instead.
    """
    if provider == "lever":
        return isinstance(payload, list) and len(payload) > 0
    if not isinstance(payload, dict):
        return False
    if provider in ("greenhouse", "ashby", "workable"):
        return bool(payload.get("jobs"))
    if provider == "smartrecruiters":
        return bool(payload.get("content")) or int(payload.get("totalFound") or 0) > 0
    if provider == "recruitee":
        return bool(payload.get("offers"))
    return False


def fingerprint(url: str) -> Optional[Resolution]:
    wd = parse_workday(url)
    if wd:
        host, tenant, site = wd
        return Resolution("workday", tenant, f"https://{host}/{site}", "fingerprint")
    for provider, pat in FINGERPRINTS:
        m = pat.search(url or "")
        if m:
            return Resolution(provider, m.group(1), None, "fingerprint")
    return None


def _titles(provider: str, payload: object) -> list[str]:
    """Posting titles out of a probe response, for the sample-board check."""
    try:
        if provider == "lever":
            return [str(j.get("text") or "") for j in payload][:20]
        if provider in ("greenhouse", "ashby", "workable"):
            return [str(j.get("title") or "") for j in payload["jobs"]][:20]
        if provider == "smartrecruiters":
            return [str(j.get("name") or "") for j in payload["content"]][:20]
        if provider == "recruitee":
            return [str(j.get("title") or "") for j in payload["offers"]][:20]
    except Exception:
        pass
    return []


def _board_name(client: HttpClient, provider: str, slug: str,
                payload: object) -> Optional[str]:
    """The name the board reports for itself, if the ATS exposes one."""
    try:
        if provider == "recruitee":
            return payload["offers"][0].get("company_name")
        if provider == "smartrecruiters":
            return payload["content"][0]["company"]["name"]
        if provider == "workable" and isinstance(payload, dict):
            return payload.get("name") or payload.get("description")
        if provider == "greenhouse":
            # The jobs feed carries no company name; the board endpoint does.
            meta = client.get_json(
                f"https://boards-api.greenhouse.io/v1/boards/{slug}",
                check_robots=False)
            if isinstance(meta, dict):
                return meta.get("name")
    except Exception:
        pass
    return None


def _all_samples(titles: list[str]) -> bool:
    """True when every posting on the board looks like demo filler."""
    real = [t for t in titles if t.strip()]
    return bool(real) and all(SAMPLE_TITLE.search(t) for t in real)


def probe(client: HttpClient, name: str,
          careers_url: str = "") -> Optional[Resolution]:
    """Guess the slug, then make the board prove it belongs to this company."""
    for slug in slug_candidates(name, careers_url):
        for provider in PROBE_ORDER:
            url = PROBES[provider].format(slug=slug)
            try:
                data = client.get_json(url, check_robots=False)
            except Exception:
                continue
            if not _plausible(provider, data):
                continue
            if _all_samples(_titles(provider, data)):
                continue                    # an abandoned demo account
            if not corroborates(name, _board_name(client, provider, slug, data),
                                slug):
                continue                    # somebody else's board
            return Resolution(provider, slug, None, "probe")
    return None


SNIFF_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(
        r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([\w.-]+)",
        re.I)),
    ("lever", re.compile(r"jobs\.lever\.co/([\w.-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.-]+)", re.I)),
    ("smartrecruiters", re.compile(
        r"smartrecruiters\.com/(?:v1/companies/)?([\w.-]+)", re.I)),
    ("workable", re.compile(
        r"apply\.workable\.com/(?:api/v1/widget/accounts/)?([\w.-]+)", re.I)),
    ("recruitee", re.compile(r"([\w-]+)\.recruitee\.com", re.I)),
]

SNIFF_JUNK = {"embed", "api", "v1", "www", "job_board", "jobs", "static"}


def sniff_html(client: HttpClient, url: str) -> Optional[Resolution]:
    """Fetch the careers page and look for an embedded provider."""
    try:
        resp = client.get(url)
    except Exception:
        return None

    final = str(resp.url)
    wd = parse_workday(final)
    if wd:
        host, tenant, site = wd
        return Resolution("workday", tenant, f"https://{host}/{site}",
                          "sniff_redirect")

    body = resp.text[:600_000]
    if "myworkdayjobs.com" in body:
        m = re.search(
            r"https?://[\w-]+\.wd\d+\.myworkdayjobs\.com/[^\s\"'<>\\]+", body, re.I)
        if m:
            wd = parse_workday(m.group(0))
            if wd:
                host, tenant, site = wd
                return Resolution("workday", tenant,
                                  f"https://{host}/{site}", "sniff_html")

    for provider, pat in SNIFF_PATTERNS:
        m = pat.search(body)
        if m:
            slug = m.group(1)
            if slug.lower() in SNIFF_JUNK:
                continue
            return Resolution(provider, slug, None, "sniff_html")
    return None


def resolve(client: HttpClient, company: Company) -> Resolution:
    """Run the ladder. Returns an unresolved Resolution rather than raising."""
    url = company.careers_url or ""

    # An aggregator page is not this company's careers site. Never fingerprint,
    # sniff or scrape it - whatever ATS it embeds belongs to the aggregator.
    # Try the name alone, then hand it to needs_review for a real URL.
    if is_aggregator(url):
        hit = probe(client, company.name, "")
        if hit:
            return hit
        return Resolution(None, None, None, "unresolved",
                          "careers_url points at a job aggregator, not the "
                          "company's own site - paste a real careers URL")

    hit = fingerprint(url)
    if hit:
        return hit

    hit = probe(client, company.name, url)
    if hit:
        return hit

    hit = sniff_html(client, url)
    if hit:
        return hit

    if url:
        return Resolution("generic_html", None, url, "fallback",
                          "no ATS detected; scraping careers page directly")
    return Resolution(None, None, None, "unresolved", "no careers URL")
