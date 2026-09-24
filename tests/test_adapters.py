"""The ATS adapters and failure classification (scrape/, PRD section 9: REUSE).

The adapters are the most valuable code in the repo and, until now, had no
direct test: a change to one payload mapping would silently drop a provider's
postings - fewer jobs, no error. These drive every adapter with a fake client
serving payloads in each API's real shape, so a mapping regression fails here.

The classification tests pin the failure policy's input: a 403 is `blocked`, a
404 `gone`, a 429/5xx `transient` (retried), and only those drive quarantine.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402

from jobscraper.models import (BLOCKED, GONE, SCHEMA, TRANSIENT, UNKNOWN,  # noqa: E402
                               RawJob, WatchedCompany)
from jobscraper.scrape import adapters as A  # noqa: E402
from jobscraper.scrape.net import (FetchError, classify_exception,  # noqa: E402
                                   classify_status)


class FakeClient:
    """Serves canned payloads by URL; records every request."""

    def __init__(self, get=None, post=None, pages=None):
        self._get = get or {}
        self._post = post or []          # successive POST responses
        self._pages = pages or {}        # url -> (text, final_url) for .get()
        self.calls: list[tuple[str, str, object]] = []

    def get_json(self, url):
        self.calls.append(("GET", url, None))
        for key, payload in self._get.items():
            if url.startswith(key):
                if isinstance(payload, Exception):
                    raise payload
                return payload
        raise FetchError(GONE, f"no fixture for {url}", 404)

    def post_json(self, url, json=None, headers=None):
        self.calls.append(("POST", url, json))
        return self._post.pop(0) if self._post else {"jobPostings": []}

    def get(self, url):
        self.calls.append(("GET", url, None))
        text, final = self._pages[url]
        return SimpleNamespace(text=text, url=final)


def co(provider, slug="acme", feed_url=None,
       careers_url="https://acme.example/careers"):
    return WatchedCompany(id=1, key="acme", name="Acme", careers_url=careers_url,
                          provider=provider, slug=slug, feed_url=feed_url)


# ---------------------------------------------------------------- registry

def test_every_watchlist_provider_has_an_adapter():
    """A provider named in watchlist.yaml with no adapter fails only at run time."""
    from jobscraper.watchlist import load
    used = {e.provider for e in load() if e.provider}
    assert used <= set(A.REGISTRY), sorted(used - set(A.REGISTRY))
    assert A.get_adapter(None) is None and A.get_adapter("nope") is None


# ---------------------------------------------------------------- helpers

def test_html_to_text_drops_scripts_and_keeps_structure():
    raw = ("<div><h2>Role</h2><p>Build &amp; run <b>Kafka</b></p>"
           "<script>track()</script><ul><li>Go</li><li>SQL</li></ul></div>")
    text = A.html_to_text(raw)
    assert "track" not in text and "Build & run Kafka" in text
    assert text.splitlines()[0] == "Role" and "Go" in text and "SQL" in text
    assert A.html_to_text("") == "" and A.html_to_text("plain &amp; simple") == \
        "plain & simple"


# ---------------------------------------------------------------- JSON ATS

def test_greenhouse_maps_fields_and_unescapes_content():
    payload = {"jobs": [{
        "id": 42, "title": "Backend Engineer", "absolute_url": "https://gh/42",
        "location": {"name": "Singapore"}, "departments": [{"name": "Eng"}],
        "updated_at": "2026-09-20T10:00:00Z",
        "content": "&lt;p&gt;Build services in &lt;b&gt;Go&lt;/b&gt;&lt;/p&gt;"}]}
    client = FakeClient(get={"https://boards-api.greenhouse.io/v1/boards/acme/": payload})
    [j] = A.Greenhouse().fetch(client, co("greenhouse"))
    assert (j.external_id, j.title, j.url, j.location, j.department, j.posted_at) == \
        ("42", "Backend Engineer", "https://gh/42", "Singapore", "Eng", "2026-09-20")
    assert j.description == "Build services in Go"


def test_greenhouse_honours_feed_url_and_caps_postings():
    feed = "https://custom.example/feed"
    payload = {"jobs": [{"id": i, "title": f"T{i}"} for i in range(A.MAX_JOBS + 50)]}
    client = FakeClient(get={feed: payload})
    jobs = A.Greenhouse().fetch(client, co("greenhouse", feed_url=feed))
    assert client.calls[0][1] == feed and len(jobs) == A.MAX_JOBS


def test_lever_appends_lists_and_rejects_a_non_list_payload():
    payload = [{"id": "L1", "text": "SRE", "hostedUrl": "https://lever/L1",
                "categories": {"location": "Singapore", "team": "Infra",
                               "commitment": "Full-time"},
                "descriptionPlain": "Keep things up.",
                "lists": [{"text": "Requirements", "content": "<li>2+ years</li>"}],
                "additionalPlain": "Hybrid."}]
    [j] = A.Lever().fetch(FakeClient(get={"https://api.lever.co/": payload}),
                          co("lever"))
    assert (j.location, j.department, j.employment_type) == \
        ("Singapore", "Infra", "Full-time")
    assert "Requirements" in j.description and "2+ years" in j.description
    try:
        A.Lever().fetch(FakeClient(get={"https://api.lever.co/": {"x": 1}}),
                        co("lever"))
        raise AssertionError("a dict payload must be a schema error")
    except FetchError as exc:
        assert exc.kind == SCHEMA


def test_ashby_falls_back_to_apply_url_and_html():
    payload = {"jobs": [{"id": "A1", "title": "Platform Engineer",
                         "applyUrl": "https://ashby/apply/A1", "location": "Singapore",
                         "team": "Platform", "descriptionHtml": "<p>Kubernetes</p>",
                         "publishedAt": "2026-09-01T00:00:00Z"}]}
    [j] = A.Ashby().fetch(FakeClient(get={"https://api.ashbyhq.com/": payload}),
                          co("ashby"))
    assert j.url == "https://ashby/apply/A1" and j.department == "Platform"
    assert j.description == "Kubernetes" and j.posted_at == "2026-09-01"


def test_smartrecruiters_paginates_until_a_short_page():
    base = "https://api.smartrecruiters.com/v1/companies/acme/postings"
    page1 = {"content": [{"id": f"s{i}", "name": "Engineer",
                          "location": {"city": "Singapore", "country": "sg"}}
                         for i in range(100)]}
    page2 = {"content": [{"id": "last", "name": "Engineer"}]}

    class Paged(FakeClient):
        def get_json(self, url):
            self.calls.append(("GET", url, None))
            return page1 if url.endswith("offset=0") else page2

    client = Paged()
    jobs = A.SmartRecruiters().fetch(client, co("smartrecruiters"))
    assert len(jobs) == 101 and len(client.calls) == 2
    assert client.calls[1][1] == f"{base}?limit=100&offset=100"
    assert jobs[0].location == "Singapore, sg"
    assert jobs[0].url == "https://jobs.smartrecruiters.com/acme/s0"


def test_smartrecruiters_hydrate_joins_sections_and_survives_errors():
    detail = {"jobAd": {"sections": {
        "jobDescription": {"text": "<p>Build APIs</p>"},
        "qualifications": {"text": "<p>Python</p>"}}}}
    job = RawJob("s1", "Engineer", "https://x")
    A.SmartRecruiters().hydrate(
        FakeClient(get={"https://api.smartrecruiters.com/": detail}),
        co("smartrecruiters"), job)
    assert job.description == "Build APIs\n\nPython"
    job2 = RawJob("s2", "Engineer", "https://x")
    A.SmartRecruiters().hydrate(
        FakeClient(get={"https://api.smartrecruiters.com/": FetchError(GONE, "x", 404)}),
        co("smartrecruiters"), job2)
    assert job2.description == ""                     # a failed detail is not fatal


def test_workable_and_recruitee_map_their_fields():
    wk = {"jobs": [{"shortcode": "W1", "title": "DevOps Engineer",
                    "url": "https://wk/W1", "city": "Singapore", "country": "SG",
                    "description": "<p>Terraform</p>", "created_at": "2026-09-02"}]}
    [w] = A.Workable().fetch(FakeClient(get={"https://apply.workable.com/": wk}),
                             co("workable"))
    assert (w.external_id, w.location, w.description) == \
        ("W1", "Singapore, SG", "Terraform")
    rc = {"offers": [{"id": 7, "title": "Backend Engineer", "careers_url": "https://rc/7",
                      "city": "Singapore", "description": "<p>Go</p>",
                      "requirements": "<p>Kafka</p>", "published_at": "2026-09-03 10:00"}]}
    [r] = A.Recruitee().fetch(FakeClient(get={"https://acme.recruitee.com/": rc}),
                              co("recruitee"))
    assert (r.location, r.posted_at) == ("Singapore", "2026-09-03")
    assert "Go" in r.description and "Kafka" in r.description


# ---------------------------------------------------------------- Workday

def test_parse_workday_url_forms():
    assert A.parse_workday("https://acme.wd3.myworkdayjobs.com/en-US/Careers") == \
        ("acme.wd3.myworkdayjobs.com", "acme", "Careers")
    assert A.parse_workday("https://acme.wd5.myworkdayjobs.com/") == \
        ("acme.wd5.myworkdayjobs.com", "acme", "External")
    assert A.parse_workday("https://acme.example/careers") is None
    assert A.parse_workday("") is None


def test_workday_paginates_by_post_and_builds_urls():
    url = "https://acme.wd3.myworkdayjobs.com/en-US/Careers"
    full = {"jobPostings": [{"title": f"SE {i}", "externalPath": f"/job/SG/SE_{i}",
                             "bulletFields": [f"R{i}"], "locationsText": "Singapore"}
                            for i in range(20)]}
    tail = {"jobPostings": [{"title": "SE last", "externalPath": "/job/SG/SE_last"}]}
    client = FakeClient(post=[full, tail])
    jobs = A.Workday().fetch(client, co("workday", careers_url=url))
    assert len(jobs) == 21 and [c[0] for c in client.calls] == ["POST", "POST"]
    assert client.calls[0][1] == \
        "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/Careers/jobs"
    assert client.calls[1][2]["offset"] == 20
    assert jobs[0].external_id == "R0" and jobs[-1].external_id == "/job/SG/SE_last"
    assert jobs[0].url == "https://acme.wd3.myworkdayjobs.com/en-US/Careers/job/SG/SE_0"


def test_workday_rejects_a_non_workday_url_and_hydrates_by_path():
    try:
        A.Workday().fetch(FakeClient(), co("workday"))
        raise AssertionError("a non-workday URL must be a schema error")
    except FetchError as exc:
        assert exc.kind == SCHEMA
    url = "https://acme.wd3.myworkdayjobs.com/en-US/Careers"
    detail = {"jobPostingInfo": {"jobDescription": "<p>Build it</p>",
                                 "location": "Singapore", "startDate": "2026-09-09"}}
    client = FakeClient(get={
        "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/Careers/job/SG/SE_1": detail})
    job = RawJob("R1", "SE", url + "/job/SG/SE_1")
    A.Workday().hydrate(client, co("workday", careers_url=url), job)
    assert (job.description, job.location, job.posted_at) == \
        ("Build it", "Singapore", "2026-09-09")


# ---------------------------------------------------------------- generic HTML

def test_generic_html_keeps_job_links_and_drops_noise():
    page = """
      <a href="/jobs/123">Backend Engineer, Payments</a>
      <a href="/jobs/123">Backend Engineer, Payments</a>
      <a href="/careers/apply/9">Site Reliability Engineer</a>
      <a href="/privacy">Privacy policy for job seekers</a>
      <a href="https://linkedin.com/jobs/1">Follow our jobs</a>
      <a href="/jobs/1">Go</a>
      <a href="/about">About our engineering team</a>"""
    client = FakeClient(pages={"https://acme.example/careers":
                               (page, "https://acme.example/careers")})
    jobs = A.GenericHtml().fetch(client, co("generic_html"))
    assert [(j.title, j.url) for j in jobs] == [
        ("Backend Engineer, Payments", "https://acme.example/jobs/123"),
        ("Site Reliability Engineer", "https://acme.example/careers/apply/9")]
    assert all(j.location == "" for j in jobs)        # left for the model (D-2)


def test_generic_html_with_no_job_links_is_a_schema_error():
    client = FakeClient(pages={"https://acme.example/careers":
                               ("<a href='/about'>About us</a>",
                                "https://acme.example/careers")})
    try:
        A.GenericHtml().fetch(client, co("generic_html"))
        raise AssertionError("an empty board must not look like zero openings")
    except FetchError as exc:
        assert exc.kind == SCHEMA and "manual feed_url" in exc.message


# ---------------------------------------------------------------- classification

def test_http_status_classification_drives_the_failure_policy():
    expected = {401: BLOCKED, 403: BLOCKED, 451: BLOCKED, 404: GONE, 410: GONE,
                429: TRANSIENT, 500: TRANSIENT, 503: TRANSIENT, 400: SCHEMA,
                422: SCHEMA, 302: UNKNOWN}
    for status, kind in expected.items():
        assert classify_status(status) == kind, status


def test_exception_classification():
    req = httpx.Request("GET", "https://x")
    assert classify_exception(httpx.ConnectError("dns", request=req)) == TRANSIENT
    assert classify_exception(httpx.ReadTimeout("slow", request=req)) == TRANSIENT
    assert classify_exception(httpx.TooManyRedirects("loop", request=req)) == SCHEMA
    assert classify_exception(ValueError("?")) == UNKNOWN
