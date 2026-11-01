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
                                   classify_status, detect_block)


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


def test_non_faceting_adapters_accept_and_ignore_the_locations_keyword():
    """Adapter.fetch(client, company, locations=()) is a base-class kwarg
    (P0-D1); providers that cannot facet just ignore it - same result with or
    without it."""
    payload = {"jobs": [{"id": 1, "title": "T"}]}
    client_a = FakeClient(get={"https://boards-api.greenhouse.io/v1/boards/acme/": payload})
    client_b = FakeClient(get={"https://boards-api.greenhouse.io/v1/boards/acme/": payload})
    without = A.Greenhouse().fetch(client_a, co("greenhouse"))
    withloc = A.Greenhouse().fetch(client_b, co("greenhouse"), locations=["Singapore"])
    assert [j.external_id for j in without] == [j.external_id for j in withloc]

    lever_payload = [{"id": "L1", "text": "SRE", "hostedUrl": "https://lever/L1"}]
    jobs = A.Lever().fetch(FakeClient(get={"https://api.lever.co/": lever_payload}),
                           co("lever"), locations=["Singapore"])
    assert len(jobs) == 1

    rc = {"offers": [{"id": 7, "title": "Backend Engineer"}]}
    jobs = A.Recruitee().fetch(FakeClient(get={"https://acme.recruitee.com/": rc}),
                               co("recruitee"), locations=[])
    assert len(jobs) == 1


def test_is_capped_reports_the_max_jobs_boundary():
    assert A.is_capped([1] * A.MAX_JOBS) is True
    assert A.is_capped([1] * (A.MAX_JOBS - 1)) is False
    assert A.is_capped([]) is False


def test_as_total_coerces_defensively():
    """P0 review HIGH: a board's reported total is untrusted input. Anything
    that is not a non-negative int/float - a string, None, a dict, a bool
    (technically an int in Python) or a negative number - reads as 0, the
    existing small-board path, rather than raising."""
    assert A._as_total(1200) == 1200
    assert A._as_total(1200.0) == 1200
    assert A._as_total("1200") == 0
    assert A._as_total(None) == 0
    assert A._as_total({}) == 0
    assert A._as_total(True) == 0
    assert A._as_total(-5) == 0


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


def test_smartrecruiters_small_board_ignores_locations():
    """total <= MAX_JOBS: no country request, even when locations are given."""
    base = "https://api.smartrecruiters.com/v1/companies/acme/postings"
    payload = {"totalFound": 3,
               "content": [{"id": f"s{i}", "name": "Engineer"} for i in range(3)]}
    client = FakeClient(get={base: payload})
    jobs = A.SmartRecruiters().fetch(client, co("smartrecruiters"),
                                     locations=["Singapore"])
    assert len(jobs) == 3 and jobs.faceted is False
    assert len(client.calls) == 1
    assert all("country=" not in c[1] for c in client.calls)


def test_smartrecruiters_facets_by_country_for_a_large_board():
    """total > MAX_JOBS and Singapore maps to a known ISO code: re-query with
    &country=sg and use those results (P0-D3)."""
    sg_page = {"content": [{"id": "sg1", "name": "Engineer",
                            "location": {"city": "Singapore", "country": "sg"}}]}
    unfiltered_first = {"totalFound": 2000,
                        "content": [{"id": f"s{i}", "name": "Engineer"}
                                    for i in range(100)]}

    class Country(FakeClient):
        def get_json(self, url):
            self.calls.append(("GET", url, None))
            return sg_page if "country=sg" in url else unfiltered_first

    client = Country()
    jobs = A.SmartRecruiters().fetch(client, co("smartrecruiters"),
                                     locations=["Singapore"])
    assert jobs.faceted is True
    assert len(jobs) == 1 and jobs[0].external_id == "sg1"
    assert any("country=sg" in c[1] for c in client.calls)


def test_smartrecruiters_survives_a_non_numeric_totalfound():
    """A `totalFound` that is not a real number (string, None, or missing)
    must not crash the fetch or read as a schema failure - it takes the
    existing small-board path and still returns the postings (P0 review)."""
    base = "https://api.smartrecruiters.com/v1/companies/acme/postings"
    for bad_total in ("not-a-number", None, "__missing__"):
        payload = {"content": [{"id": "s0", "name": "Engineer"}]}
        if bad_total != "__missing__":
            payload["totalFound"] = bad_total
        client = FakeClient(get={base: payload})
        jobs = A.SmartRecruiters().fetch(client, co("smartrecruiters"),
                                         locations=["Singapore"])
        assert len(jobs) == 1 and jobs[0].external_id == "s0"
        assert jobs.faceted is False
        assert all("country=" not in c[1] for c in client.calls)


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


def test_workday_small_board_costs_one_request_even_with_a_matching_facet():
    """total <= MAX_JOBS: never facet, so a small board costs one request."""
    url = "https://acme.wd3.myworkdayjobs.com/en-US/Careers"
    payload = {"total": 5,
               "jobPostings": [{"title": f"T{i}", "externalPath": f"/job/{i}"}
                               for i in range(5)],
               "facets": [{"facetParameter": "locationCountry",
                           "values": [{"descriptor": "Singapore", "id": "sg"}]}]}
    client = FakeClient(post=[payload])
    jobs = A.Workday().fetch(client, co("workday", careers_url=url),
                             locations=["Singapore"])
    assert len(client.calls) == 1 and len(jobs) == 5
    assert jobs.faceted is False and not A.is_capped(jobs)
    assert client.calls[0][2]["appliedFacets"] == {}


def test_workday_large_board_facets_by_a_nested_location_value():
    """total > MAX_JOBS: Workday nests facets, so a value that itself carries
    facetParameter + values (here locationCountry, nested one level under the
    top-level "locations" facet) must be searched too. A second request
    carries appliedFacets keyed by the facetParameter of the matching level,
    and its results - not the first page's - are returned (P0-D2)."""
    url = "https://acme.wd3.myworkdayjobs.com/en-US/Careers"
    facets = [
        {"facetParameter": "timeType",
         "values": [{"descriptor": "Full time", "id": "t1", "count": 900}]},
        {"facetParameter": "locations",
         "values": [
             {"descriptor": "Asia Pacific", "id": "region-apac", "count": 500,
              "facetParameter": "locationCountry",
              "values": [{"descriptor": "Singapore", "id": "loc-sg", "count": 45},
                        {"descriptor": "Malaysia", "id": "loc-my", "count": 30}]},
             {"descriptor": "Americas", "id": "region-amer", "count": 700},
         ]},
    ]
    first_page = {"total": 1200, "facets": facets,
                 "jobPostings": [{"title": f"T{i}", "externalPath": f"/job/{i}"}
                                 for i in range(20)]}
    faceted_page = {"jobPostings": [{"title": "SG Engineer",
                                     "externalPath": "/job/sg1",
                                     "bulletFields": ["SG1"]}]}
    client = FakeClient(post=[first_page, faceted_page])
    jobs = A.Workday().fetch(client, co("workday", careers_url=url),
                             locations=["Singapore"])
    assert len(client.calls) == 2
    assert client.calls[1][2]["appliedFacets"] == {"locationCountry": ["loc-sg"]}
    assert client.calls[1][2]["offset"] == 0
    assert len(jobs) == 1 and jobs[0].external_id == "SG1"
    assert jobs.faceted is True and not A.is_capped(jobs)


def test_workday_large_board_with_no_matching_facet_falls_back_capped():
    """total > MAX_JOBS but no facet value matches an allowed location: keep
    the unfaceted, capped results rather than failing the fetch."""
    url = "https://acme.wd3.myworkdayjobs.com/en-US/Careers"
    facets = [{"facetParameter": "locationCountry",
              "values": [{"descriptor": "United States", "id": "us"},
                        {"descriptor": "Germany", "id": "de"}]}]

    class Big(FakeClient):
        def post_json(self, u, json=None, headers=None):
            self.calls.append(("POST", u, json))
            offset = json["offset"]
            page = [{"title": f"T{offset + i}", "externalPath": f"/job/{offset + i}"}
                   for i in range(20)]
            data = {"jobPostings": page}
            if offset == 0:
                data.update(total=5000, facets=facets)
            return data

    client = Big()
    jobs = A.Workday().fetch(client, co("workday", careers_url=url),
                             locations=["Singapore"])
    assert jobs.faceted is False and A.is_capped(jobs)
    assert len(jobs) == A.MAX_JOBS


def test_workday_facet_matching_uses_word_boundaries_not_substrings():
    """"India" must not match "Indianapolis, Indiana" - a naive substring
    match would pull in the wrong facet id(s) (P0 review MEDIUM)."""
    url = "https://acme.wd3.myworkdayjobs.com/en-US/Careers"
    facets = [{"facetParameter": "locationCountry",
              "values": [{"descriptor": "Indianapolis, Indiana", "id": "us-in"},
                        {"descriptor": "India", "id": "in"}]}]
    first_page = {"total": 1200, "facets": facets,
                 "jobPostings": [{"title": f"T{i}", "externalPath": f"/job/{i}"}
                                 for i in range(20)]}
    faceted_page = {"jobPostings": [{"title": "IN Engineer",
                                     "externalPath": "/job/in1",
                                     "bulletFields": ["IN1"]}]}
    client = FakeClient(post=[first_page, faceted_page])
    jobs = A.Workday().fetch(client, co("workday", careers_url=url),
                             locations=["India"])
    assert client.calls[1][2]["appliedFacets"] == {"locationCountry": ["in"]}
    assert jobs.faceted is True and len(jobs) == 1


def test_workday_survives_a_non_numeric_total():
    """A `total` that is not a real number (string, None, or missing) must
    not crash the fetch or read as a schema failure - it takes the existing
    small-board path and still returns the postings (P0 review)."""
    url = "https://acme.wd3.myworkdayjobs.com/en-US/Careers"
    page = {"jobPostings": [{"title": "SE 0", "externalPath": "/job/0",
                             "bulletFields": ["R0"]}]}
    for bad_total in ("not-a-number", None, "__missing__"):
        body = dict(page)
        if bad_total != "__missing__":
            body = {**page, "total": bad_total}
        client = FakeClient(post=[body])
        jobs = A.Workday().fetch(client, co("workday", careers_url=url),
                                 locations=["Singapore"])
        assert len(jobs) == 1 and jobs[0].external_id == "R0"
        assert jobs.faceted is False
        assert client.calls[0][2]["appliedFacets"] == {}
    assert all(j["appliedFacets"] == {} for _, _, j in client.calls)


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


# ---------------------------------------------------------------- block signatures (P0-D5)

def test_detect_block_cloudflare_by_header_and_body():
    assert detect_block(403, {"cf-ray": "abc123"}, "") == "cloudflare"
    assert detect_block(200, {"cf-mitigated": "challenge"}, "") == "cloudflare"
    assert detect_block(503, {"server": "cloudflare"}, "") == "cloudflare"
    assert detect_block(200, {}, "Just a moment...") == "cloudflare"
    assert detect_block(403, {}, "Attention Required! | Cloudflare") == "cloudflare"
    assert detect_block(403, {}, "cf-chl-bypass token") == "cloudflare"
    # server: cloudflare with an ordinary 200 is not enough on its own
    assert detect_block(200, {"server": "cloudflare"}, "welcome") == ""


def test_detect_block_header_only_signals_are_gated_on_block_relevant_statuses():
    """cf-ray rides along on nearly every Cloudflare-proxied response, blocked
    or not - so a header-only claim (cf-ray, server: cloudflare, server:
    AkamaiGHost) must not fire on a plain 404/410, a real app 401 with no
    corroborating body text, or an unrelated 500. It still fires on a status
    that is itself block-shaped (403, 429, 503). Body markers are unaffected -
    they can decide on any status, including the 200-challenge-page case
    net.py handles separately."""
    assert detect_block(404, {"cf-ray": "abc"}, "") == ""
    assert detect_block(410, {"cf-ray": "abc"}, "") == ""
    assert detect_block(401, {"cf-ray": "abc"}, "") == "forbidden", \
        "a header alone must not promote a real 401 to a block signature"
    assert detect_block(500, {"cf-ray": "abc"}, "") == ""
    assert detect_block(403, {"cf-ray": "abc"}, "") == "cloudflare"
    assert detect_block(503, {}, "Just a moment...") == "cloudflare"
    assert detect_block(404, {"server": "AkamaiGHost"}, "") == ""
    # a body marker still decides regardless of the header gate
    assert detect_block(401, {"cf-ray": "abc"}, "Just a moment...") == "cloudflare"


def test_detect_block_akamai_needs_the_header_or_both_body_markers():
    assert detect_block(403, {"server": "AkamaiGHost"}, "") == "akamai"
    assert detect_block(403, {}, "Access Denied\nReference #18.abc123") == "akamai"
    assert detect_block(403, {}, "Access Denied - see errors.edgesuite.net") == "akamai"
    # "Access Denied" with no confirming marker is just a plain 403
    assert detect_block(403, {}, "Access Denied") == "forbidden"


def test_detect_block_captcha_regardless_of_status():
    assert detect_block(200, {}, "Please complete the reCAPTCHA below") == "captcha"
    assert detect_block(403, {}, "hCaptcha challenge") == "captcha"


def test_detect_block_rate_limited_and_forbidden_and_plain_404():
    assert detect_block(429, {}, "") == "rate_limited"
    assert detect_block(403, {}, "") == "forbidden"
    assert detect_block(401, {}, "") == "forbidden"
    assert detect_block(404, {}, "not found") == "", "a plain 404 has no block signature"
    assert detect_block(500, {}, "internal error") == ""
