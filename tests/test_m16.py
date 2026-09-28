"""M16: the user's own list of companies (upload, Qwen + discovery search, the
plan's cap counting only what was found), the job description in the Inbox,
and the owner's uncapped plan.

The model and the network are always stubs here.
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jobscraper import company_search as CS  # noqa: E402
from jobscraper import watchlist as W  # noqa: E402
from jobscraper.backends import Backend, BackendError, Completion  # noqa: E402
from jobscraper.config import Config, Plan  # noqa: E402
from jobscraper.models import RawJob, parse_company_lines  # noqa: E402
from jobscraper.scrape.discovery import Resolution  # noqa: E402
from jobscraper.scrape.net import FetchError  # noqa: E402
from jobscraper.store import Store  # noqa: E402
from test_web_control import QUICK, _stub, _wait, _world  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ---------------------------------------------------------------- parsing

def test_list_lines_become_names_in_order():
    text = ("1. Grab\n- OKX\n• 2C2P\n7-Eleven\n99 Group\n(3) Visa\n4 - Stripe\n"
            "grab\n   \n  Sea   Ltd ,\n")
    assert parse_company_lines(text) == ["Grab", "OKX", "2C2P", "7-Eleven", "99 Group",
                                         "Visa", "Stripe", "Sea Ltd"]
    assert parse_company_lines("") == []
    assert parse_company_lines("x" * 121) == [], "a paragraph is not a company name"


def test_store_keeps_results_for_names_it_has_searched():
    st = Store(Path(tempfile.mkdtemp()) / "t.db")
    st.replace_company_list(["Grab", "OKX", "Ghost"])
    st.update_company_list_entry(1, status="found", company_key="grab", postings=12)
    st.update_company_list_entry(3, status="failed", detail="no careers site found")
    change = st.replace_company_list(["okx", "Visa", "GRAB"])       # reordered, edited
    assert change == {"kept": 1, "new": 2, "dropped": 1}
    rows = st.company_list()
    assert [(r["position"], r["name"], r["status"]) for r in rows] == \
        [(1, "okx", "pending"), (2, "Visa", "pending"), (3, "GRAB", "found")]
    assert rows[2]["postings"] == 12, "a found company keeps what was found"
    st.close()


# ---------------------------------------------------------------- upload API

def _docx(lines):
    import docx
    d = docx.Document()
    for line in lines:
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_web_upload_a_text_list_keeps_its_order():
    with _world() as (c, cfg, _):
        r = c.put("/api/companies/list", content="1. Grab\n2. OKX\n\n3. Visa\n".encode("utf-8"),
                  headers={"Content-Type": "text/plain"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert [(i["position"], i["name"], i["status"]) for i in body["items"]] == \
            [(1, "Grab", "pending"), (2, "OKX", "pending"), (3, "Visa", "pending")]
        assert body["upload"]["read"] == 3 and body["upload"]["new"] == 3
        assert body["counts"]["pending"] == 3 and body["searched"] == 0
        assert body["max_companies"] is None and body["plan"] == "local"
        assert c.get("/api/companies/list").json()["items"] == body["items"]


def test_web_upload_a_docx_list():
    with _world() as (c, cfg, _):
        r = c.put("/api/companies/list", content=_docx(["Standard Chartered", "", "Thunes"]),
                  headers={"Content-Type": DOCX})
        assert r.status_code == 200, r.text
        assert [i["name"] for i in r.json()["items"]] == ["Standard Chartered", "Thunes"]


def test_web_upload_refuses_what_is_not_a_list():
    with _world() as (c, cfg, _):
        form = c.put("/api/companies/list", content=b"a=b",
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert form.status_code == 415
        fake = c.put("/api/companies/list", content=b"%PDF-1.7 ...", headers={"Content-Type": DOCX})
        assert fake.status_code == 415
        binary = c.put("/api/companies/list", content=b"PK\x03\x04zip",
                       headers={"Content-Type": "text/plain"})
        assert binary.status_code == 415
        empty = c.put("/api/companies/list", content=b"\n  \n", headers={"Content-Type": "text/plain"})
        assert empty.status_code == 422
        big = c.put("/api/companies/list", content=b"Grab\n" * 300_000,
                    headers={"Content-Type": "text/plain"})
        assert big.status_code == 413
        assert c.get("/api/companies/list").json()["items"] == []


def test_web_clearing_the_list():
    with _world() as (c, cfg, _):
        c.put("/api/companies/list", content=b"Grab\n", headers={"Content-Type": "text/plain"})
        assert c.delete("/api/companies/list").json()["items"] == []


def test_web_a_found_company_dropped_from_the_list_stops_being_watched_at_once():
    with _world() as (c, cfg, _):
        c.put("/api/companies/list", content=b"Brexish\nOther Co\n", headers={"Content-Type": "text/plain"})
        st = Store(cfg.db_path)
        st.update_company_list_entry(1, status="found", company_key="brexish", provider="greenhouse",
                                     slug="brexish", careers_url="https://job-boards.greenhouse.io/brexish")
        st.sync_watchlist(W.all_entries(cfg.watchlist_path, st))
        assert "brexish" in {x.key for x in st.companies(enabled_only=True)}
        st.close()

        c.put("/api/companies/list", content=b"Other Co\n", headers={"Content-Type": "text/plain"})
        st = Store(cfg.db_path)
        assert "brexish" not in {x.key for x in st.companies(enabled_only=True)}
        st.close()


def test_web_company_search_is_a_background_job():
    with _world(job_command=_stub(QUICK)) as (c, cfg, _):
        r = c.post("/api/jobs/companies")
        assert r.status_code == 202 and r.json()["kind"] == "companies"
        assert "kind companies" in _wait(c)["log"]
    from jobscraper.web.jobs import cli_command
    assert cli_command(None)("companies", {})[-2:] == ["companies", "search"]


# ---------------------------------------------------------------- the search

class _Qwen(Backend):
    name = "stub"
    model_id = "qwen-stub"

    def __init__(self, answer=None, fail=False):
        self.answer, self.fail, self.asked = answer or {}, fail, []

    @property
    def available(self):
        return True

    def complete(self, system, user, max_tokens=4096):
        names = user.split("<companies>\n")[1].split("\n</companies>")[0].split("\n")
        self.asked.append(names)
        if self.fail:
            raise BackendError("down")
        return Completion("```json\n" + json.dumps({"companies": [
            {"name": n, "website": None, "careers_url": self.answer.get(n)} for n in names]}) + "\n```")


def _search_world(names, plan=None):
    """A temp config (watchlist.yaml holding OKX), a store listing `names`."""
    tmp = Path(tempfile.mkdtemp())
    wl = tmp / "watchlist.yaml"
    wl.write_text("version: 1\ncompanies:\n  - key: okx\n    name: OKX\n"
                  "    careers_url: https://okx.com/careers\n"
                  "    provider: greenhouse\n    slug: okx\n", encoding="utf-8")

    class _Cfg(Config):
        @property
        def plan(self):
            return plan or super().plan

    cfg = _Cfg({"paths": {"watchlist": str(wl), "db": str(tmp / "t.db")},
                "run": {"cycle_days": 7}})
    st = Store(tmp / "t.db")
    st.sync_watchlist(W.load(wl))
    st.replace_company_list(names)
    return cfg, st


BOARDS = {"known": ("greenhouse", "knownco"), "blocked": ("lever", "blockedco")}


def _resolve(client, company):
    hit = BOARDS.get(company.key.split("-")[0])
    if hit:
        return Resolution(hit[0], hit[1], None, "probe")
    if company.careers_url:                 # Qwen's lead: a plain careers page
        return Resolution("generic_html", None, company.careers_url, "fallback")
    return Resolution(None, None, None, "unresolved")


def _fetch(client, company):
    if company.slug == "blockedco":
        raise FetchError("blocked", "HTTP 403")
    if company.provider == "generic_html":
        return [RawJob("", "Engineer", company.careers_url + "/1")]
    return [RawJob("1", "Engineer", "u1"), RawJob("2", "Analyst", "u2"), RawJob("3", "Intern", "u3")]


def _run(cfg, st, backend=None):
    return CS.search(cfg, st, backend=backend or _Qwen({"Lead Co": "https://leadco.example/careers"}),
                     client=object(), resolve=_resolve, fetch=_fetch, say=lambda *_: None)


def test_search_goes_in_order_and_says_what_happened_to_each():
    cfg, st = _search_world(["okx", "Known Co", "Ghost Co", "Blocked Co", "Lead Co"])
    counts = _run(cfg, st)
    rows = {r["name"]: r for r in st.company_list()}
    assert rows["okx"]["status"] == "watched" and "already watched as OKX" in rows["okx"]["detail"]
    assert rows["Known Co"]["status"] == "found" and rows["Known Co"]["postings"] == 3
    assert rows["Known Co"]["careers_url"] == "https://job-boards.greenhouse.io/knownco"
    assert rows["Ghost Co"]["status"] == "failed" and "no careers site found" in rows["Ghost Co"]["detail"]
    assert rows["Blocked Co"]["status"] == "failed" and "blocked" in rows["Blocked Co"]["detail"]
    assert rows["Lead Co"]["status"] == "found" and rows["Lead Co"]["provider"] == "generic_html"
    assert counts == {"watched": 1, "found": 2, "failed": 2}
    assert all(r["searched_at"] for r in rows.values())
    st.close()


def test_search_asks_qwen_only_about_companies_it_does_not_know():
    q = _Qwen()
    cfg, st = _search_world(["OKX", "Known Co", "Ghost Co"])
    _run(cfg, st, backend=q)
    assert q.asked == [["Known Co", "Ghost Co"]], "OKX is already watched"
    st.close()


def test_search_survives_the_model_being_down():
    cfg, st = _search_world(["Known Co", "Lead Co"])
    _run(cfg, st, backend=_Qwen(fail=True))
    rows = {r["name"]: r["status"] for r in st.company_list()}
    # Known Co is still found by name; Lead Co needed Qwen's lead.
    assert rows == {"Known Co": "found", "Lead Co": "failed"}
    st.close()


def test_the_plan_caps_companies_found_and_failures_do_not_count():
    capped = Plan("test", (7,), 5, 5, 2)
    cfg, st = _search_world(["Ghost Co", "Known Co", "Blocked Co", "okx", "Lead Co", "Known Co 2"],
                            plan=capped)
    _run(cfg, st)
    rows = [(r["name"], r["status"]) for r in st.company_list()]
    assert rows == [("Ghost Co", "failed"), ("Known Co", "found"), ("Blocked Co", "failed"),
                    ("okx", "watched"), ("Lead Co", "over_limit"), ("Known Co 2", "over_limit")]
    assert "adds up to 2 companies" in st.company_list()[4]["detail"]
    st.close()


def test_found_companies_are_watched_and_leave_when_the_list_drops_them():
    cfg, st = _search_world(["Known Co", "okx"])
    _run(cfg, st)
    enabled = {c.key: c for c in st.companies(enabled_only=True)}
    assert set(enabled) == {"okx", "known-co"}, "found and synced at once; OKX not twice"
    assert enabled["known-co"].provider == "greenhouse"
    st.replace_company_list(["okx"])
    st.sync_watchlist(W.all_entries(cfg.watchlist_path, st))
    assert {c.key for c in st.companies(enabled_only=True)} == {"okx"}
    st.close()


def test_qwen_leads_must_be_real_urls():
    q = _Qwen({"A": "not a url", "B": "https://b.example/careers"})
    assert CS.lookup_sites(q, ["A", "B"]) == {"a": None, "b": "https://b.example/careers"}
    assert CS.lookup_sites(_Qwen(fail=True), ["A"]) == {}


# ---------------------------------------------------------------- Inbox: rank and description

def test_shortlist_jobs_carry_the_users_company_rank():
    from test_web import _world as web_world
    with web_world() as (client, open_store):
        st = open_store()
        st.replace_company_list(["Grab", "OKX"])
        st.update_company_list_entry(1, status="found", company_key="grab")
        st.update_company_list_entry(2, status="watched", company_key="okx")
        st.close()
        jobs = {j["company"]: j for j in client.get("/api/shortlist?run=all").json()}
    assert jobs["Grab"]["company_rank"] == 1 and jobs["OKX"]["company_rank"] == 2
    assert jobs["Stripe"]["company_rank"] is None


def test_web_posting_serves_the_full_description():
    with _world() as (c, cfg, _):
        st = Store(cfg.db_path)
        cid = st.companies()[0].id
        raw = RawJob("7", "Backend Engineer", "https://x.example/7", "Singapore")
        jid = raw.job_id(cid, "greenhouse")
        st.upsert_job(jid, cid, raw, 1, True)
        st.conn.commit()
        st.set_description(jid, "About Us\nWe build � payments.\n\nResponsibilities\n- Build APIs\n")
        st.close()
        r = c.get(f"/api/postings/{jid}")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["description"] == "About Us\nWe build – payments.\n\nResponsibilities\n- Build APIs"
        assert body["title"] == "Backend Engineer" and body["company"] == "Company 0"
        assert c.get("/api/postings/nope").status_code == 404
        assert c.get("/api/postings/bad id!").status_code == 422
