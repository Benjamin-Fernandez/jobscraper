"""M17: Not interested is kept; stored descriptions expire after 7 days; title
recommendations are always new; every watched company's scan status as a CSV;
a posting already tracked under another id is not new again.

The model and the network are always stubs here.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jobscraper.backends import Backend, Completion  # noqa: E402
from jobscraper.models import RawJob  # noqa: E402
from jobscraper.profile import titles as T  # noqa: E402
from jobscraper.store import Store, shift, utcnow  # noqa: E402
from jobscraper.web import data as D  # noqa: E402
import test_pipeline as P  # noqa: E402

NOW = "2026-10-10T12:00:00"


def _store():
    return Store(Path(tempfile.mkdtemp()) / "t.db")


def _job(st, cid, n, desc="About the role\nBuild things."):
    raw = RawJob(f"x{n}", f"Engineer {n}", f"https://x.example/{n}", "Singapore", description=desc)
    jid = raw.job_id(cid, "greenhouse")
    st.upsert_job(jid, cid, raw, 1, True)
    st.commit()
    return jid


# ---------------------------------------------------------------- descriptions expire

def test_old_descriptions_are_deleted_but_not_those_the_inbox_shows():
    st = _store()
    cid = st.insert_company("x", "X", "https://x.example")
    old, accepted, applied, fresh = (_job(st, cid, n) for n in range(4))
    st.conn.execute("UPDATE jobs SET jd_fetched_at = ?, vital_text = 'V' WHERE job_id != ?",
                    (shift(NOW, days=-8), fresh))
    st.conn.execute("UPDATE jobs SET jd_fetched_at = ? WHERE job_id = ?", (shift(NOW, days=-2), fresh))
    st.save_decision(accepted, 1, "h", "accept", True, 0, "fits", "m")
    st.set_application_status(applied, "applied")
    st.commit()

    assert st.purge_descriptions(7, now=NOW) == 1
    jd = {j: st.get_job(j)["jd_text"] for j in (old, accepted, applied, fresh)}
    assert jd[old] is None, "a week-old description nobody needs is gone"
    assert all(jd[j] for j in (accepted, applied, fresh)), "the Inbox's, the tracked and new ones stay"
    assert st.get_job(old)["vital_text"] == "V", "what the judge read is kept"
    assert st.purge_descriptions(7, now=NOW) == 0
    assert st.compact() is True
    st.close()


def test_an_older_database_gets_the_fetch_date_backfilled():
    tmp = Path(tempfile.mkdtemp()) / "t.db"
    st = Store(tmp)
    cid = st.insert_company("x", "X", "https://x.example")
    run = st.start_run()
    jid = _job(st, cid, 1)
    st.conn.execute("UPDATE jobs SET first_seen_run = ?", (run,))
    started = st.conn.execute("SELECT started_at FROM runs WHERE run_no = ?", (run,)).fetchone()[0]
    st.conn.execute("ALTER TABLE jobs DROP COLUMN jd_fetched_at")       # as before M17
    st.commit()
    st.close()
    st = Store(tmp)
    assert st.get_job(jid)["jd_fetched_at"] == started
    st.close()


def test_new_and_hydrated_descriptions_are_dated():
    st = _store()
    cid = st.insert_company("x", "X", "https://x.example")
    jid = _job(st, cid, 1)
    assert st.get_job(jid)["jd_fetched_at"]
    bare = _job(st, cid, 2, desc="")
    assert st.get_job(bare)["jd_fetched_at"] is None
    st.set_description(bare, "Fetched later")
    assert st.get_job(bare)["jd_fetched_at"]
    st.close()


class _RejectAll(P._AcceptSingapore):
    def complete(self, system, user, max_tokens=4096):
        return Completion(super().complete(system, user, max_tokens).text
                          .replace('"accept"', '"reject"'))


def _with_description(client, company):
    return P.FetchOutcome(company.id, True, provider=company.provider, jobs=[
        RawJob(f"{company.key}-{k}", "Backend Engineer", f"https://{company.key}.example.com/jobs/{k}",
               "Singapore", description="We build payment systems in Python and Kafka. " * 5)
        for k in range(2)])


def test_a_deleted_description_does_not_send_the_role_back_to_the_model():
    cfg, st = P._world(1)
    judge = _RejectAll()
    P._run(cfg, st, fetcher=_with_description, backend=judge)
    assert judge.calls == 1
    st.conn.execute("UPDATE jobs SET jd_fetched_at = ?", (shift(utcnow(), days=-8),))
    st.commit()
    assert st.purge_descriptions(7) == 2
    rep = P._run(cfg, st, fetcher=_with_description, backend=judge, now=shift(P.T0, days=8))
    assert rep.status == "ok"
    assert judge.calls == 1, "the kept extract matches the cached decision"
    st.close()


# ---------------------------------------------------------------- Not interested is kept

def test_web_not_interested_is_stored_and_can_be_undone():
    from test_web import _world as web_world
    with web_world() as (c, open_store):
        r = c.put("/api/dismissals/a1b2c3")
        assert r.status_code == 200 and r.json()["dismissed_at"]
        again = c.put("/api/dismissals/a1b2c3").json()["dismissed_at"]
        assert again == r.json()["dismissed_at"], "the first time is kept"
        jobs = {j["id"]: j for j in c.get("/api/shortlist?run=all").json()}
        assert jobs["a1b2c3"]["dismissed_at"] == again and jobs["d4e5f6"]["dismissed_at"] is None

        assert c.delete("/api/dismissals/a1b2c3").json()["removed"] is True
        assert c.delete("/api/dismissals/a1b2c3").json()["removed"] is False
        jobs = {j["id"]: j for j in c.get("/api/shortlist?run=all").json()}
        assert jobs["a1b2c3"]["dismissed_at"] is None
        assert c.put("/api/dismissals/bad id!").status_code == 422


# ---------------------------------------------------------------- one posting, two ids

def test_posting_keys_ignore_what_does_not_change_the_posting():
    k = D.posting_key
    assert k("https://Example.org/grab/jobs/3003/") == k("http://example.org/grab/jobs/3003#apply")
    assert k("https://x.io/a?utm_source=li&gh_jid=5") == k("https://x.io/a?gh_jid=5")
    assert k("https://x.io/a?gh_jid=5") != k("https://x.io/a?gh_jid=6")
    assert k(None) == k("") == ""


def test_web_a_posting_applied_for_under_another_id_is_not_new():
    from test_web import _world as web_world
    with web_world() as (c, open_store):
        st = open_store()
        # The same Grab posting, tracked under the id of a second watched company.
        st.set_application_status("otherco-3003", "applied", company="Grab Financial Group",
                                  role="Software Engineer I",
                                  url="https://example.org/grab/jobs/3003/?utm_source=x")
        # Same company, same title as OKX's posting, but another URL: not sure, stays new.
        st.set_application_status("okx-other", "applied", company="OKX",
                                  role="DevOps / Site Reliability Engineer",
                                  url="https://job-boards.greenhouse.io/okx/jobs/1111")
        st.close()
        jobs = {j["id"]: j for j in c.get("/api/shortlist?run=all").json()}
    assert jobs["j1k2l3"]["tracked_as"] == {"job_id": "otherco-3003", "status": "applied"}
    assert jobs["a1b2c3"]["tracked_as"] is None
    assert jobs["d4e5f6"]["tracked_as"] is None


# ---------------------------------------------------------------- titles: always new

class _Answers(Backend):
    name = "stub"
    model_id = "qwen-stub"

    def __init__(self, *answers):
        self.answers, self.seen = list(answers), []

    @property
    def available(self):
        return True

    def complete(self, system, user, max_tokens=4096):
        self.seen.append(user)
        titles = self.answers.pop(0) if self.answers else []
        return Completion(json.dumps({"field_of_study": "BEng", "experience": [],
                                      "suggestions": [{"title": t, "why": "w"} for t in titles]}))


PREVIOUS = {"suggestions": [{"title": "data engineer", "why": "a"}, {"title": "qa engineer", "why": "b"}],
            "seen": ["cloud engineer"]}


def test_recommend_asks_for_five_new_titles_and_tops_up_a_short_answer():
    q = _Answers(["Data Engineer", "Product Manager", "Business Analyst", "Software Engineer"],
                 ["Trade Support Analyst", "Technology Analyst", "Product Manager"])
    out = T.recommend(q, "resume", {}, ["software engineer"], PREVIOUS, limit=5)
    assert [s["title"] for s in out["suggestions"]] == [
        "product manager", "business analyst", "trade support analyst", "technology analyst"]
    first, second = q.seen
    told = first.split("<already_suggested>")[1]
    assert "data engineer" in told and "cloud engineer" in told and "qa engineer" in told
    assert "product manager" in second.split("<already_suggested>")[1], "the top-up excludes the first answer"
    assert out["repeated"] is False
    assert {"cloud engineer", "data engineer", "product manager", "technology analyst"} <= set(out["seen"])


def test_recommend_repeats_earlier_titles_only_when_nothing_new_is_left():
    q = _Answers(["Data Engineer", "Software Engineer"], [])
    out = T.recommend(q, "resume", {}, ["software engineer", "qa engineer"], PREVIOUS, limit=5)
    assert out["repeated"] is True
    assert [s["title"] for s in out["suggestions"]] == ["data engineer"], "earlier, still unchosen"
    nothing = T.recommend(_Answers([], []), "resume", {}, ["data engineer", "qa engineer"], PREVIOUS)
    assert nothing["suggestions"] == [] and nothing["repeated"] is False


def test_web_titles_say_when_the_recommendations_are_repeats():
    from test_web_control import _world
    from test_m15 import _profile
    with _world() as (c, cfg, _):
        _profile(cfg)
        st = Store(cfg.db_path)
        st.set_setting(T.SUGGESTIONS_KEY, json.dumps({
            "generated_at": NOW, "model": "m", "suggestions": [{"title": "data engineer", "why": ""}],
            "repeated": True}))
        st.close()
        s = c.get("/api/titles").json()["suggestions"]
    assert s["repeated"] is True and [i["title"] for i in s["items"]] == ["data engineer"]


# ---------------------------------------------------------------- an update shows at once

def test_the_page_is_always_revalidated_and_the_bundle_cached():
    """An old copy of index.html kept the M16 app on screen after M17 was
    installed: the page must be revalidated, the hashed bundle may be kept."""
    import re
    from test_web_control import _world
    with _world() as (c, cfg, _):
        page = c.get("/")
        assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"
        asset = re.search(r'/?(assets/[^"]+\.js)', page.text).group(1)
        js = c.get("/" + asset)
        assert js.status_code == 200
        assert js.headers["cache-control"] == "public, max-age=31536000, immutable"
        again = c.get("/", headers={"If-None-Match": page.headers["etag"]})
        assert again.status_code == 304, "revalidating an unchanged page is cheap"


# ---------------------------------------------------------------- companies CSV

def test_web_every_watched_company_with_whether_it_can_be_scanned():
    from test_web_control import _world
    with _world(enabled=4, disabled=1) as (c, cfg, _):
        st = Store(cfg.db_path)
        ids = {co.key: co.id for co in st.companies()}
        st.record_coverage(1, ids["co0"], "ok", 12, 3, 0, None, None, None)
        st.record_success(ids["co0"])
        st.record_coverage(1, ids["co1"], "failed", 0, 0, 0, 403, "blocked", "HTTP 403")
        st.record_failure(ids["co1"], "blocked", "=HYPERLINK(evil) 403")
        st.record_coverage(1, ids["co2"], "failed", 0, 0, 0, 404, "gone", "HTTP 404")
        st.record_failure(ids["co2"], "gone", "HTTP 404 for https://co2.example")
        st.close()

        body = c.get("/api/companies/health").json()
        assert body["total"] == 4 and body["counts"] == {"ok": 1, "failed": 2, "not_scanned": 1}
        assert [(i["company"], i["state"]) for i in body["items"]] == [
            ("Company 0", "ok"), ("Company 1", "failed"), ("Company 2", "failed"),
            ("Company 3", "not_scanned")]
        assert body["items"][0]["open_roles"] == 12
        assert body["items"][1]["reason"] == "the site blocks automated access"

        r = c.get("/api/companies/export.csv")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
        assert 'attachment; filename="jobscraper-companies-' in r.headers["content-disposition"]
        text = r.content.decode("utf-8")
        assert text.startswith("﻿Company,Can be scanned,Why not,Open roles at last scan")
        lines = text.lstrip("﻿").splitlines()
        assert lines[1].startswith("Company 0,yes,,12,")
        assert lines[2].startswith("Company 1,no - failed,the site blocks automated access,")
        assert "'=HYPERLINK(evil) 403" in lines[2], "never a formula in Excel"
        assert lines[4].startswith("Company 3,not scanned yet,")
        assert len(lines) == 5, "disabled companies are not listed"
