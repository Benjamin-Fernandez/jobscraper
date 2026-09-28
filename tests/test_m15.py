"""M15: the cycle the user chooses, run ranges, and job titles (+ Qwen's
recommendations) - all bounded by the plan in force, so a future tier changes
numbers, not code.

Web tests reuse test_web_control's world: the real app over a temp config,
database and data dir. The model is always a stub.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import yaml  # noqa: E402

from jobscraper.backends import Backend, BackendError, Completion  # noqa: E402
from jobscraper.config import PLANS, Config  # noqa: E402
from jobscraper.profile import titles as T  # noqa: E402
from jobscraper.profile.resume_ingest import ProfileError  # noqa: E402
from jobscraper.store import Store  # noqa: E402
from jobscraper.web import data as D  # noqa: E402
from test_web_control import ENABLED, QUICK, _stored, _stub, _wait, _world  # noqa: E402


# ---------------------------------------------------------------- plans

def test_plans_carry_every_tier_limit_and_local_is_the_most_generous():
    assert Config({}).plan.name == "local"
    assert Config({"plan": "FREE"}).plan == PLANS["free"]
    assert Config({"plan": "enterprise"}).plan.name == "local", "unknown -> local"
    free, plus, pro, local = (PLANS[k] for k in ("free", "plus", "pro", "local"))
    assert free.cycle_day_options == (7, 14, 30)
    assert set(free.cycle_day_options) < set(plus.cycle_day_options) < set(pro.cycle_day_options)
    assert free.max_target_titles < plus.max_target_titles < pro.max_target_titles == 20
    assert free.max_companies < plus.max_companies < pro.max_companies
    # The owner's install: every cycle, and no cap on titles or companies (M16).
    assert local.cycle_day_options == pro.cycle_day_options
    assert (local.max_target_titles, local.max_companies) == (None, None)
    assert local.max_title_suggestions == 20


def test_effective_cycle_is_the_stored_choice_only_when_the_plan_offers_it():
    cfg = Config({"run": {"cycle_days": 7}})
    assert cfg.effective_cycle_days(None) == 7
    assert cfg.effective_cycle_days("1") == 1
    assert cfg.effective_cycle_days("30") == 30
    for off_plan in ("2", "0", "-7", "weekly", ""):
        assert cfg.effective_cycle_days(off_plan) == 7, off_plan
    free = Config({"run": {"cycle_days": 7}, "plan": "free"})
    assert free.effective_cycle_days("1") == 7, "a daily cycle is not a free-plan option"


# ---------------------------------------------------------------- settings: cycle

def test_web_settings_report_the_cycle_and_the_plan_options():
    with _world() as (c, cfg, _):
        body = c.get("/api/settings").json()
    assert body == {"batch_size": 10, "batch_size_default": 10,
                    "enabled_companies": ENABLED, "cycle_days": 14,
                    "cycle_days_default": 14, "cycle_day_options": [1, 3, 7, 14, 30],
                    "plan": "local", "runs_per_day_needed": 0.2}   # 30 / 10 / 14


def test_web_settings_round_trip_a_cycle_and_the_cadence_follows():
    with _world() as (c, cfg, _):
        r = c.put("/api/settings", json={"cycle_days": 3})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["cycle_days"] == 3 and body["cycle_days_default"] == 14
        assert body["runs_per_day_needed"] == 1.0            # 30 / 10 / 3
        assert body["batch_size"] == 10, "the other setting is left alone"
        assert _stored(cfg, "cycle_days") == "3"            # what `run` reads
        both = c.put("/api/settings", json={"cycle_days": 7, "batch_size": 15}).json()
        assert (both["cycle_days"], both["batch_size"]) == (7, 15)


def test_web_settings_refuse_a_cycle_the_plan_does_not_offer():
    with _world() as (c, cfg, _):
        for bad in (2, 0, -1, 365, "7", 7.0, True):
            r = c.put("/api/settings", json={"cycle_days": bad})
            assert r.status_code == 422, (bad, r.status_code)
        r = c.put("/api/settings", json={"cycle_days": 2})
        assert "[1, 3, 7, 14, 30]" in r.json()["detail"]
        # One bad field refuses the whole request: nothing is half-written.
        assert c.put("/api/settings", json={"cycle_days": 2, "batch_size": 12}).status_code == 422
        assert _stored(cfg, "cycle_days") is None and _stored(cfg, "batch_size") is None


def test_web_settings_follow_a_smaller_plan():
    with _world() as (c, cfg, _):
        cfg.raw["plan"] = "free"
        assert c.get("/api/settings").json()["cycle_day_options"] == [7, 14, 30]
        assert c.put("/api/settings", json={"cycle_days": 1}).status_code == 422
        assert c.put("/api/settings", json={"cycle_days": 30}).status_code == 200


# ---------------------------------------------------------------- titles API

def _profile(cfg: Config, titles=("software engineer", "backend engineer")):
    cfg.profile_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.profile_path.write_text(yaml.safe_dump({
        "profile_version": 2, "source_file": "resume.pdf", "summary": "grad",
        "skills": ["python"], "target_titles": list(titles)}), encoding="utf-8")


def test_web_titles_default_to_the_resume_with_the_plan_limits():
    with _world() as (c, cfg, _):
        _profile(cfg)
        body = c.get("/api/titles").json()
    assert body == {"titles": ["software engineer", "backend engineer"], "source": "resume",
                    "resume_titles": ["software engineer", "backend engineer"],
                    "max_titles": None, "max_suggestions": 20, "plan": "local",
                    "suggestions": None}


def test_web_titles_put_cleans_stores_and_delete_resets():
    with _world() as (c, cfg, _):
        _profile(cfg)
        r = c.put("/api/titles", json={"titles": ["  Data   Analyst ", "data analyst",
                                                  "Trade Support Engineer", ""]})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["titles"] == ["Data Analyst", "Trade Support Engineer"]
        assert body["source"] == "custom"
        assert json.loads(_stored(cfg, "target_titles")) == body["titles"]
        reset = c.delete("/api/titles").json()
        assert reset["source"] == "resume" and reset["titles"] == ["software engineer", "backend engineer"]


def test_web_titles_refuse_empty_too_long_and_over_the_plan():
    with _world() as (c, cfg, _):
        _profile(cfg)
        assert c.put("/api/titles", json={"titles": []}).status_code == 422
        assert c.put("/api/titles", json={"titles": ["  ", "-"]}).status_code == 422
        assert c.put("/api/titles", json={"titles": ["x" * 81]}).status_code == 422
        many = [f"title {i}" for i in range(60)]
        assert c.put("/api/titles", json={"titles": many}).status_code == 200, \
            "the owner's plan has no cap on titles"
        cfg.raw["plan"] = "pro"
        r = c.put("/api/titles", json={"titles": many[:21]})
        assert r.status_code == 422 and "allows 20" in r.json()["detail"]
        assert c.put("/api/titles", json={"titles": many[:20]}).status_code == 200
        cfg.raw["plan"] = "free"
        r = c.put("/api/titles", json={"titles": many[:6]})
        assert r.status_code == 422 and "free plan allows 5" in r.json()["detail"]


def test_web_titles_serve_recommendations_minus_what_is_already_chosen():
    with _world() as (c, cfg, _):
        _profile(cfg)
        st = Store(cfg.db_path)
        st.set_setting("title_suggestions", json.dumps({
            "generated_at": "2026-09-28T04:00:00", "model": "qwen3:14b",
            "field_of_study": "BEng Computer Engineering",
            "experience": ["Software engineering intern at Grab (internship)"],
            "suggestions": [{"title": "data engineer", "why": "pipelines"},
                            {"title": "Backend Engineer", "why": "already chosen"},
                            {"title": "technology analyst", "why": "banks"}]}))
        st.close()
        s = c.get("/api/titles").json()["suggestions"]
        assert s["field_of_study"] == "BEng Computer Engineering"
        assert s["experience"] == ["Software engineering intern at Grab (internship)"]
        assert [i["title"] for i in s["items"]] == ["data engineer", "technology analyst"]
        # Choose data engineer and drop backend engineer: the list follows.
        c.put("/api/titles", json={"titles": ["software engineer", "data engineer"]})
        s = c.get("/api/titles").json()["suggestions"]
        assert [i["title"] for i in s["items"]] == ["Backend Engineer", "technology analyst"]


def test_web_titles_recommendation_is_a_background_job():
    with _world(job_command=_stub(QUICK)) as (c, cfg, _):
        r = c.post("/api/jobs/titles")
        assert r.status_code == 202 and r.json()["kind"] == "titles"
        job = _wait(c)
        assert job["state"] == "succeeded" and "kind titles" in job["log"]


def test_web_titles_job_runs_the_cli_titles_suggest():
    from jobscraper.web.jobs import cli_command
    argv = cli_command(None)("titles", {})
    assert argv[-3:] == ["jobscraper", "titles", "suggest"]


# ---------------------------------------------------------------- run ranges

SHORTLIST = {"runs": [{"run_no": 14, "finished_at": "2026-09-28T03:00:00", "accepted": 3},
                      {"run_no": 12, "finished_at": "2026-09-23T14:30:00", "accepted": 2},
                      {"run_no": 9, "finished_at": "2026-09-01T09:00:00", "accepted": 1},
                      {"run_no": 5, "finished_at": "2026-08-01T09:00:00", "accepted": 0}],
             "jobs": [{"id": "a", "run_no": 14}, {"id": "b", "run_no": 12},
                      {"id": "c", "run_no": 9}, {"id": "d", "run_no": 12}]}
NOW = dt.datetime(2026, 9, 28, 12, 0, 0)


def test_run_ranges_week_month_and_chosen_runs():
    assert D.resolve_run(SHORTLIST, "week", now=NOW) == frozenset({14, 12})
    assert D.resolve_run(SHORTLIST, "month", now=NOW) == frozenset({14, 12, 9})
    assert D.resolve_run(SHORTLIST, "12,9") == frozenset({12, 9})
    assert D.resolve_run(SHORTLIST, "12") == 12
    assert D.resolve_run(SHORTLIST, "latest") == 14

    def ids(sel):
        return sorted(j["id"] for j in D.jobs_for(SHORTLIST, sel))
    assert ids(D.resolve_run(SHORTLIST, "week", now=NOW)) == ["a", "b", "d"]
    assert ids(D.resolve_run(SHORTLIST, "12,9")) == ["b", "c", "d"]
    assert ids(D.resolve_run(SHORTLIST, "all")) == ["a", "b", "c", "d"]
    assert ids(D.resolve_run(SHORTLIST, "week", now=dt.datetime(2027, 1, 1))) == []


def test_web_shortlist_accepts_the_new_selectors_and_nothing_else():
    with _world() as (c, cfg, _):
        cfg.shortlist_path.write_text(json.dumps(SHORTLIST), encoding="utf-8")
        assert sorted(j["id"] for j in c.get("/api/shortlist?run=12,9").json()) == ["b", "c", "d"]
        for ok in ("all", "week", "month", "latest", "12"):
            assert c.get(f"/api/shortlist?run={ok}").status_code == 200, ok
        for bad in ("12,", ",12", "year", "12;9", "all,12"):
            assert c.get(f"/api/shortlist?run={bad}").status_code == 422, bad


# ---------------------------------------------------------------- titles module

def test_user_titles_parse_apply_and_key():
    assert T.parse_user_titles(None) is None
    assert T.parse_user_titles("not json") is None
    assert T.parse_user_titles("[]") is None
    assert T.parse_user_titles('["A  b", "a b", "c"]') == ["A b", "c"]
    profile = {"target_titles": ["software engineer"], "skills": ["x"]}
    assert T.apply(profile, None) is profile
    assert T.apply(profile, ["data analyst"]) == {"target_titles": ["data analyst"], "skills": ["x"]}
    assert T.prefilter_key("h", None) == "h", "no user titles: nothing is re-checked"
    k = T.prefilter_key("h", ["Data Analyst", "b"])
    assert k != "h" and k == T.prefilter_key("h", ["b", "data analyst"])
    assert k != T.prefilter_key("h", ["b"])


class _Qwen(Backend):
    name = "stub"
    model_id = "qwen-stub"

    def __init__(self, text):
        self.text, self.seen = text, []

    @property
    def available(self):
        return True

    def complete(self, system, user, max_tokens=4096):
        self.seen.append((system, user))
        if isinstance(self.text, Exception):
            raise self.text
        return Completion(self.text)


def test_suggest_caps_excludes_chosen_and_reports_what_it_read():
    answer = json.dumps({
        "field_of_study": "BEng  Computer Engineering",
        "experience": ["Software intern at Grab (internship)", ""],
        "suggestions": [{"title": "Software Engineer", "why": "already chosen"},
                        {"title": "Data Engineer", "why": "pipelines"},
                        {"title": "data engineer", "why": "duplicate"},
                        {"title": "Technology Analyst", "why": "banks"},
                        {"title": "Platform Engineer", "why": "infra"}]})
    q = _Qwen("```json\n" + answer + "\n```")
    out = T.suggest(q, "RESUME TEXT", {"skills": ["python", "go"]},
                    ["software engineer"], limit=2, interests=["fintech", "trade operations"],
                    now="2026-09-28T04:00:00")
    assert [s["title"] for s in out["suggestions"]] == ["data engineer", "technology analyst"]
    assert out["field_of_study"] == "BEng Computer Engineering"
    assert out["experience"] == ["Software intern at Grab (internship)"]
    assert out["model"] == "qwen-stub" and out["based_on"] == ["software engineer"]
    system, user = q.seen[0]
    assert "at most 2" in system and "RESUME TEXT" in user
    assert "software engineer" in user.split("<chosen_titles>")[1], "it sees what is chosen"
    assert "<open_to>fintech; trade operations</open_to>" in user, "and the areas you are open to"


def test_suggest_fails_loudly_rather_than_storing_nothing():
    for bad in (_Qwen("I think you should be a chef."), _Qwen(BackendError("down"))):
        try:
            T.suggest(bad, "r", {}, [], 5)
            raise AssertionError("a useless answer must raise")
        except ProfileError:
            pass
