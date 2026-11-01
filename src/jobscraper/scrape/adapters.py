"""Fetch adapters, one per applicant-tracking system.

Adapters return postings WITHOUT descriptions where the provider needs a second
request per job. The pipeline calls `hydrate()` only for postings that survive the
title filter, so detail requests are never spent on roles we already rejected.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any, Iterable, Optional
from urllib.parse import urljoin, urlparse

from ..models import SCHEMA, RawJob, WatchedCompany
from .net import FetchError, HttpClient

MAX_JOBS = 600


class JobList(list):
    """A fetch's postings, plus whether the board was queried per-location.

    `Adapter.fetch` runs concurrently across companies in the pipeline's
    thread pool (see pipeline.run), and the shared `REGISTRY` adapters are
    singletons - so the faceted flag cannot live on `self`. Subclassing
    `list` instead of adding an instance attribute on the adapter keeps every
    existing caller that treats a fetch as `list[RawJob]` unchanged, while
    letting a faceting adapter attach the one bit of state that belongs to a
    single call (D-33/P0-D4)."""

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.faceted = False


def is_capped(jobs: list) -> bool:
    """True when a fetch returned MAX_JOBS postings or more - the provider's
    own cap, not a real count, so postings past it (e.g. more Singapore
    roles) may have been missed (P0-D4)."""
    return len(jobs) >= MAX_JOBS


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

class _Stripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("p", "br", "li", "div", "tr", "h1", "h2", "h3", "h4"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    if "<" not in raw:
        return re.sub(r"[ \t]+", " ", html.unescape(raw)).strip()
    p = _Stripper()
    try:
        p.feed(raw)
    except Exception:
        return re.sub(r"<[^>]+>", " ", raw)
    text = "".join(p.parts)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _as_total(value: Any) -> int:
    """A board's reported total (Workday's `total`, SmartRecruiters'
    `totalFound`), coerced defensively (P0 review HIGH): the value comes from
    the provider's own JSON and is never validated upstream, so a string, a
    missing key (already handled by `.get(...) or 0` before this runs), a
    dict, or a bool (technically an `int` in Python, but never a meaningful
    total) must not raise when compared against MAX_JOBS - it reads as 0,
    which takes the existing small-board path (first page kept, paginated as
    before) instead of the fetch being misreported as a schema failure."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value) if value > 0 else 0


# --------------------------------------------------------------------------
# adapters
# --------------------------------------------------------------------------

class Adapter:
    provider = "base"

    def fetch(self, client: HttpClient, company: WatchedCompany,
             locations: Iterable[str] = ()) -> list[RawJob]:
        """`locations` (P0-D1): allowed locations for adapters that can query
        a large board per-location (Workday, SmartRecruiters). Optional and
        ignored by providers that cannot facet, so every existing call site
        keeps working unchanged."""
        raise NotImplementedError

    def hydrate(self, client: HttpClient, company: WatchedCompany, job: RawJob) -> None:
        """Fill job.description in place. Default: nothing more to fetch."""
        return None


class Greenhouse(Adapter):
    provider = "greenhouse"

    def fetch(self, client, company, locations=()):
        slug = company.slug
        url = (company.feed_url
               or f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
        data = client.get_json(url)
        out = []
        for j in (data.get("jobs") or [])[:MAX_JOBS]:
            loc = (j.get("location") or {}).get("name", "")
            depts = ", ".join(d.get("name", "") for d in (j.get("departments") or []))
            out.append(RawJob(
                external_id=_s(j.get("id")),
                title=_s(j.get("title")),
                url=_s(j.get("absolute_url")),
                location=_s(loc),
                department=depts,
                posted_at=_s(j.get("updated_at"))[:10],
                description=html_to_text(html.unescape(_s(j.get("content")))),
            ))
        return out


class Lever(Adapter):
    provider = "lever"

    def fetch(self, client, company, locations=()):
        url = (company.feed_url
               or f"https://api.lever.co/v0/postings/{company.slug}?mode=json")
        data = client.get_json(url)
        if not isinstance(data, list):
            raise FetchError(SCHEMA, "lever payload was not a list")
        out = []
        for j in data[:MAX_JOBS]:
            cats = j.get("categories") or {}
            desc = _s(j.get("descriptionPlain")) or html_to_text(_s(j.get("description")))
            for blk in (j.get("lists") or []):
                desc += "\n\n" + _s(blk.get("text")) + "\n" + html_to_text(
                    _s(blk.get("content")))
            desc += "\n" + _s(j.get("additionalPlain"))
            out.append(RawJob(
                external_id=_s(j.get("id")),
                title=_s(j.get("text")),
                url=_s(j.get("hostedUrl")),
                location=_s(cats.get("location")),
                department=_s(cats.get("team")),
                employment_type=_s(cats.get("commitment")),
                posted_at="",
                description=desc.strip(),
            ))
        return out


class Ashby(Adapter):
    provider = "ashby"

    def fetch(self, client, company, locations=()):
        url = (company.feed_url
               or f"https://api.ashbyhq.com/posting-api/job-board/{company.slug}")
        data = client.get_json(url)
        out = []
        for j in (data.get("jobs") or [])[:MAX_JOBS]:
            desc = _s(j.get("descriptionPlain")) or html_to_text(
                _s(j.get("descriptionHtml")))
            out.append(RawJob(
                external_id=_s(j.get("id")),
                title=_s(j.get("title")),
                url=_s(j.get("jobUrl")) or _s(j.get("applyUrl")),
                location=_s(j.get("location")),
                department=_s(j.get("department")) or _s(j.get("team")),
                employment_type=_s(j.get("employmentType")),
                posted_at=_s(j.get("publishedAt"))[:10],
                description=desc,
            ))
        return out


# ISO-3166 alpha-2 codes for the locations the Posting API's `country` filter
# accepts (P0-D3). Small on purpose - a location with no entry here just falls
# back to the unfaceted, capped fetch; add codes as more locations are needed.
SR_COUNTRY_CODES = {
    "singapore": "sg",
}


def _sr_country_code(locations: Iterable[str]) -> Optional[str]:
    for loc in locations:
        code = SR_COUNTRY_CODES.get(_s(loc).lower())
        if code:
            return code
    return None


class SmartRecruiters(Adapter):
    provider = "smartrecruiters"

    def fetch(self, client, company, locations=()):
        slug = company.slug
        base = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"

        # Unfaceted first page: cheap way to read totalFound. Reused below
        # when the board turns out to be small, so a small board costs no
        # extra request (P0-D3).
        first = client.get_json(f"{base}?limit=100&offset=0")
        total = _as_total(first.get("totalFound"))
        country_qs = ""
        faceted = False
        if total > MAX_JOBS and locations:
            code = _sr_country_code(locations)
            if code:
                country_qs, faceted = f"&country={code}", True

        out: list[RawJob] = []
        offset = 0
        # Once faceted, the first page's un-filtered content is discarded -
        # every page including offset 0 is re-fetched with the country filter.
        data: Optional[dict] = None if faceted else first
        while offset < MAX_JOBS:
            if data is None:
                data = client.get_json(f"{base}?limit=100&offset={offset}{country_qs}")
            batch = data.get("content") or []
            data = None
            if not batch:
                break
            for j in batch:
                loc = j.get("location") or {}
                where = ", ".join(x for x in [_s(loc.get("city")),
                                              _s(loc.get("region")),
                                              _s(loc.get("country"))] if x)
                out.append(RawJob(
                    external_id=_s(j.get("id")),
                    title=_s(j.get("name")),
                    url=f"https://jobs.smartrecruiters.com/{slug}/{_s(j.get('id'))}",
                    location=where,
                    department=_s((j.get("department") or {}).get("label")),
                    employment_type=_s((j.get("typeOfEmployment") or {}).get("label")),
                    posted_at=_s(j.get("releasedDate"))[:10],
                ))
            offset += len(batch)
            if len(batch) < 100:
                break
        result = JobList(out)
        result.faceted = faceted
        return result

    def hydrate(self, client, company, job):
        url = (f"https://api.smartrecruiters.com/v1/companies/"
               f"{company.slug}/postings/{job.external_id}")
        try:
            data = client.get_json(url)
        except FetchError:
            return
        bits = []
        ad = (data.get("jobAd") or {}).get("sections") or {}
        for key in ("companyDescription", "jobDescription", "qualifications",
                    "additionalInformation"):
            sec = ad.get(key) or {}
            bits.append(html_to_text(_s(sec.get("text"))))
        job.description = "\n\n".join(b for b in bits if b)


class Workable(Adapter):
    provider = "workable"

    def fetch(self, client, company, locations=()):
        url = (company.feed_url or
               f"https://apply.workable.com/api/v1/widget/accounts/"
               f"{company.slug}?details=true")
        data = client.get_json(url)
        out = []
        for j in (data.get("jobs") or [])[:MAX_JOBS]:
            where = ", ".join(x for x in [_s(j.get("city")), _s(j.get("country"))] if x)
            out.append(RawJob(
                external_id=_s(j.get("shortcode")) or _s(j.get("id")),
                title=_s(j.get("title")),
                url=_s(j.get("url")) or _s(j.get("application_url")),
                location=where,
                department=_s(j.get("department")),
                employment_type=_s(j.get("employment_type")),
                posted_at=_s(j.get("created_at"))[:10],
                description=html_to_text(_s(j.get("description"))),
            ))
        return out


class Recruitee(Adapter):
    provider = "recruitee"

    def fetch(self, client, company, locations=()):
        url = company.feed_url or f"https://{company.slug}.recruitee.com/api/offers/"
        data = client.get_json(url)
        out = []
        for j in (data.get("offers") or [])[:MAX_JOBS]:
            out.append(RawJob(
                external_id=_s(j.get("id")),
                title=_s(j.get("title")),
                url=_s(j.get("careers_url")) or _s(j.get("careers_apply_url")),
                location=_s(j.get("location")) or _s(j.get("city")),
                department=_s(j.get("department")),
                employment_type=_s(j.get("employment_type_code")),
                posted_at=_s(j.get("published_at"))[:10],
                description=html_to_text(
                    _s(j.get("description")) + " " + _s(j.get("requirements"))),
            ))
        return out


WD_RE = re.compile(
    r"https?://(?P<host>(?P<tenant>[\w-]+)\.(?P<wd>wd\d+)\.myworkdayjobs\.com)"
    r"(?P<path>/[^?#]*)?", re.I)


def parse_workday(url: str) -> Optional[tuple[str, str, str]]:
    """-> (host, tenant, site) or None."""
    m = WD_RE.match(url or "")
    if not m:
        return None
    host, tenant = m.group("host"), m.group("tenant")
    parts = [p for p in (m.group("path") or "").split("/") if p]
    # Drop locale segments such as en-US / en_US.
    parts = [p for p in parts if not re.fullmatch(r"[a-zA-Z]{2}[-_][a-zA-Z]{2}", p)]
    site = parts[0] if parts else "External"
    return host, tenant, site


# A facet parameter is "location-like" when its name mentions a location or a
# country - Workday tenants name theirs differently (locationCountry,
# locations, primaryLocations, country, ...), so this matches by substring
# rather than an enumerated list (P0-D2).
WD_LOCATION_PARAM_RE = re.compile(r"location|country", re.I)


def _wd_find_location_facet(
        facets: list, allowed: set[str]) -> Optional[tuple[str, list[str]]]:
    """Search Workday's (possibly nested) facet tree for values whose
    descriptor matches an allowed location, case-insensitively, on whole
    words - "Singapore" matches "Singapore" and "Singapore, Singapore" but
    "India" does not match "Indianapolis, Indiana" (P0 review MEDIUM: a plain
    substring test would false-positive there).

    Workday nests facets: a facet has `facetParameter` and `values`; a value
    has `descriptor`, `id`, `count` and may itself carry its own
    `facetParameter` + `values` one or more levels down. Only facet groups
    whose parameter looks location-like are searched at all, at every depth -
    a location facet nested under a parent whose own facetParameter does not
    look location-like (WD_LOCATION_PARAM_RE) is a blind spot this will not
    find; that is safe by construction, since finding nothing just falls back
    to the unfaceted, capped fetch rather than mis-faceting. Returns the
    first matching `(facetParameter, [ids])` - the coarsest level that has a
    match is enough to narrow the query - or None.
    """
    for group in facets or []:
        param = _s(group.get("facetParameter"))
        if not WD_LOCATION_PARAM_RE.search(param):
            continue
        values = group.get("values") or []
        ids = [_s(v.get("id")) for v in values
              if any(re.search(r"\b" + re.escape(a) + r"\b",
                               _s(v.get("descriptor")), re.I)
                     for a in allowed)]
        ids = [i for i in ids if i]
        if ids:
            return param, ids
        # No match at this level: descend into any value that nests its own
        # facet group (e.g. a region value nesting locationCountry values).
        nested = [{"facetParameter": v.get("facetParameter"), "values": v.get("values")}
                 for v in values if v.get("facetParameter") and v.get("values")]
        found = _wd_find_location_facet(nested, allowed)
        if found:
            return found
    return None


class Workday(Adapter):
    provider = "workday"

    def fetch(self, client, company, locations=()):
        parsed = parse_workday(company.feed_url or company.careers_url)
        if not parsed:
            raise FetchError(SCHEMA, f"not a workday url: {company.careers_url}")
        host, tenant, site = parsed
        endpoint = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"

        def request(applied_facets: dict, offset: int) -> dict:
            body = {"appliedFacets": applied_facets, "limit": 20, "offset": offset,
                    "searchText": ""}
            return client.post_json(
                endpoint, json=body,
                headers={"Content-Type": "application/json",
                         "Accept": "application/json"})

        def map_page(posts: list) -> list[RawJob]:
            mapped = []
            for j in posts:
                ext = _s(j.get("externalPath"))
                bullets = j.get("bulletFields") or []
                mapped.append(RawJob(
                    external_id=_s(bullets[0]) if bullets else ext,
                    title=_s(j.get("title")),
                    url=f"https://{host}/en-US/{site}{ext}",
                    location=_s(j.get("locationsText")),
                    posted_at=_s(j.get("postedOn")),
                ))
            return mapped

        # Unfaceted first page: cheap way to read `total` and the board's own
        # facet ids (per-tenant, so they must be discovered, not guessed). A
        # small board (total <= MAX_JOBS) reuses this page and costs no extra
        # request (P0-D2).
        first = request({}, 0)
        total = _as_total(first.get("total"))
        applied_facets: dict = {}
        faceted = False
        if total > MAX_JOBS and locations:
            found = _wd_find_location_facet(
                first.get("facets") or [], {_s(l).lower() for l in locations})
            if found:
                param, ids = found
                applied_facets, faceted = {param: ids}, True

        out: list[RawJob] = []
        offset = 0
        # Once faceted, the unfaceted first page is discarded entirely - every
        # page, including offset 0, is re-queried with appliedFacets set.
        data: Optional[dict] = None if faceted else first
        while offset < MAX_JOBS:
            if data is None:
                data = request(applied_facets, offset)
            posts = data.get("jobPostings") or []
            data = None
            if not posts:
                break
            out.extend(map_page(posts))
            offset += len(posts)
            if len(posts) < 20:
                break
        result = JobList(out)
        result.faceted = faceted
        return result

    def hydrate(self, client, company, job):
        parsed = parse_workday(company.feed_url or company.careers_url)
        if not parsed:
            return
        host, tenant, site = parsed
        path = urlparse(job.url).path
        marker = f"/{site}"
        idx = path.find(marker)
        ext = path[idx + len(marker):] if idx >= 0 else ""
        if not ext:
            return
        try:
            data = client.get_json(f"https://{host}/wday/cxs/{tenant}/{site}{ext}")
        except FetchError:
            return
        info = data.get("jobPostingInfo") or {}
        job.description = html_to_text(_s(info.get("jobDescription")))
        job.location = job.location or _s(info.get("location"))
        job.posted_at = job.posted_at or _s(info.get("startDate"))


class GenericHtml(Adapter):
    """Last resort: scrape anchors that look like job links.

    Low precision by design. Postings arrive with no location, which the filter
    treats as ambiguous rather than rejecting outright.
    """
    provider = "generic_html"
    JOBISH = re.compile(
        r"(job|career|opening|position|requisition|vacanc|apply|role)", re.I)
    NOISE = re.compile(
        r"(privacy|cookie|terms|login|signin|sign-in|search|filter|rss|mailto:|"
        r"linkedin\.com|facebook\.com|twitter\.com|instagram\.com)", re.I)

    def fetch(self, client, company, locations=()):
        url = company.feed_url or company.careers_url
        resp = client.get(url)
        page = resp.text
        base = str(resp.url)

        anchors = re.findall(
            r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
            page, re.I | re.S)
        seen: set[str] = set()
        out: list[RawJob] = []
        for href, inner in anchors:
            if self.NOISE.search(href):
                continue
            if not self.JOBISH.search(href):
                continue
            text = html_to_text(inner)
            text = re.sub(r"\s+", " ", text).strip()
            if not (6 <= len(text) <= 140):
                continue
            full = urljoin(base, href)
            if full in seen:
                continue
            seen.add(full)
            out.append(RawJob(external_id="", title=text, url=full,
                              location="", description=""))
            if len(out) >= 200:
                break
        if not out:
            raise FetchError(
                SCHEMA,
                f"no job-like links found on {base} (needs a manual feed_url)")
        return out


REGISTRY: dict[str, Adapter] = {
    a.provider: a for a in (
        Greenhouse(), Lever(), Ashby(), SmartRecruiters(), Workable(),
        Recruitee(), Workday(), GenericHtml(),
    )
}


def get_adapter(provider: Optional[str]) -> Optional[Adapter]:
    return REGISTRY.get(provider or "")
