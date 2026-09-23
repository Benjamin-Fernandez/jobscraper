"""Fetch adapters, one per applicant-tracking system.

Adapters return postings WITHOUT descriptions where the provider needs a second
request per job. The pipeline calls `hydrate()` only for postings that survive the
title filter, so detail requests are never spent on roles we already rejected.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

from .models import SCHEMA, Company, RawJob
from .net import FetchError, HttpClient

MAX_JOBS = 600


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


# --------------------------------------------------------------------------
# adapters
# --------------------------------------------------------------------------

class Adapter:
    provider = "base"

    def fetch(self, client: HttpClient, company: Company) -> list[RawJob]:
        raise NotImplementedError

    def hydrate(self, client: HttpClient, company: Company, job: RawJob) -> None:
        """Fill job.description in place. Default: nothing more to fetch."""
        return None


class Greenhouse(Adapter):
    provider = "greenhouse"

    def fetch(self, client, company):
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

    def fetch(self, client, company):
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

    def fetch(self, client, company):
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


class SmartRecruiters(Adapter):
    provider = "smartrecruiters"

    def fetch(self, client, company):
        slug = company.slug
        base = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
        out: list[RawJob] = []
        offset = 0
        while offset < MAX_JOBS:
            data = client.get_json(f"{base}?limit=100&offset={offset}")
            batch = data.get("content") or []
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
        return out

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

    def fetch(self, client, company):
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

    def fetch(self, client, company):
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


class Workday(Adapter):
    provider = "workday"

    def fetch(self, client, company):
        parsed = parse_workday(company.feed_url or company.careers_url)
        if not parsed:
            raise FetchError(SCHEMA, f"not a workday url: {company.careers_url}")
        host, tenant, site = parsed
        endpoint = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        out: list[RawJob] = []
        offset = 0
        while offset < MAX_JOBS:
            body = {"appliedFacets": {}, "limit": 20, "offset": offset,
                    "searchText": ""}
            data = client.post_json(
                endpoint, json=body,
                headers={"Content-Type": "application/json",
                         "Accept": "application/json"})
            posts = data.get("jobPostings") or []
            if not posts:
                break
            for j in posts:
                ext = _s(j.get("externalPath"))
                bullets = j.get("bulletFields") or []
                out.append(RawJob(
                    external_id=_s(bullets[0]) if bullets else ext,
                    title=_s(j.get("title")),
                    url=f"https://{host}/en-US/{site}{ext}",
                    location=_s(j.get("locationsText")),
                    posted_at=_s(j.get("postedOn")),
                ))
            offset += len(posts)
            if len(posts) < 20:
                break
        return out

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

    def fetch(self, client, company):
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
