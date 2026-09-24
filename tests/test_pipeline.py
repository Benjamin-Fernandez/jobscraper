"""The run sequence end to end, with the network replaced by a stub (M3-T4).

What these pin down is ordering and bookkeeping, the parts a live run cannot
prove cheaply: a dry run never consumes the queue, a crash before the stamp is a
no-op, a failed fetch is stamped but never closes jobs, and a batch-wide outage
charges nobody.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jobscraper import pipeline
from jobscraper.backends import Backend, Completion, OffBackend
from jobscraper.config import load_config
from jobscraper.models import FetchOutcome, RawJob
from jobscraper.scrape.discovery import Resolution
from jobscraper.store import Store, shift

T0 = "2026-09-24T09:00:00"


def _world(n=12):
    """A config pointing at a temp watchlist of n companies and a temp DB."""
    tmp = Path(tempfile.mkdtemp())
    wl = tmp / "watchlist.yaml"
    wl.write_text("version: 1\ncompanies:\n" + "".join(
        f"  - name: Co{i:02d}\n    careers_url: https://co{i:02d}.example.com/careers\n"
        f"    provider: greenhouse\n    slug: co{i:02d}\n" for i in range(1, n + 1)),
        encoding="utf-8")
    cfg = load_config()
    # Hermetic: every path a run writes points into the temp dir, never data/.
    cfg.raw["paths"]["watchlist"] = str(wl)
    cfg.raw["paths"]["shortlist"] = str(tmp / "shortlist.json")
    cfg.raw["paths"]["profile"] = str(tmp / "profile.derived.yaml")
    cfg.raw["paths"]["db"] = str(tmp / "t.db")
    cfg.raw["run"]["max_workers"] = 2
    return cfg, Store(tmp / "t.db")


PROFILE = {"profile_version": 1, "summary": "new grad backend engineer",
           "skills": ["python", "kafka", "kubernetes"],
           "target_titles": ["backend engineer", "software engineer"],
           "title_aliases": {}, "years_experience": 0}


def _jobs(company, n=2):
    return [RawJob(external_id=f"{company.key}-{k}", title="Backend Engineer",
                   url=f"https://{company.key}.example.com/jobs/{k}",
                   location="Singapore") for k in range(n)]


def ok_fetcher(client, company):
    return FetchOutcome(company.id, True, jobs=_jobs(company), provider=company.provider)


def fail_fetcher(client, company):
    return FetchOutcome(company.id, False, error_class="blocked", error="403",
                        http_status=403)


def failing_only(key):
    def fetch(client, company):
        return (fail_fetcher if company.key == key else ok_fetcher)(client, company)
    return fetch


class _Client:
    def close(self):
        pass


def _run(cfg, st, fetcher=ok_fetcher, **kw):
    kw.setdefault("now", T0)
    # Never the real transport: a test must not spend the user's model quota.
    kw.setdefault("backend", OffBackend("tests"))
    kw.setdefault("profile", PROFILE)
    return pipeline.run(cfg, st, fetcher=fetcher, client=_Client(),
                        resolver=lambda c, co: Resolution(None, None, None, "stub"), verbose=False, **kw)


def _count(st, table):
    return st.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_pipeline_dry_run_selects_ten_and_consumes_nothing():
    cfg, st = _world(12)
    a = _run(cfg, st, dry_run=True)
    b = _run(cfg, st, dry_run=True)
    assert a.status == b.status == "dry_run"
    assert len(a.due) == 10 and a.due == b.due          # same 10: queue untouched
    assert a.postings == 20
    for table in ("jobs", "runs", "coverage"):
        assert _count(st, table) == 0
    assert all(c.last_scraped_at is None for c in st.companies())


def test_pipeline_real_run_persists_then_stamps():
    cfg, st = _world(12)
    rep = _run(cfg, st)
    assert rep.status == "ok" and rep.run_no == 1
    assert _count(st, "jobs") == 20 and _count(st, "coverage") == 10
    stamped = [c for c in st.companies() if c.last_scraped_at == T0]
    assert len(stamped) == 10
    run = st.list_runs()[0]
    assert run["status"] == "ok" and run["stats"]["postings_new"] == 20
    # The next run takes the two never-scraped companies, not the same ten.
    nxt = _run(cfg, st, now=shift(T0, seconds=60))
    assert nxt.due == ["Co11", "Co12"]


def test_pipeline_nothing_due_exits_with_next_due_date():
    """M3-T3's runner half: with everyone fresh, report when, scrape nothing."""
    cfg, st = _world(10)
    _run(cfg, st)
    rep = _run(cfg, st, now=shift(T0, days=1))
    assert rep.status == "nothing_due" and rep.run_no == 0
    assert rep.next_due_at == shift(T0, days=14)
    assert _count(st, "runs") == 1


def test_pipeline_failed_fetch_is_stamped_counted_and_closes_nothing():
    cfg, st = _world(10)
    _run(cfg, st)                                          # everyone has 2 open jobs
    rep = _run(cfg, st, fetcher=failing_only("co01"), now=shift(T0, days=15))
    assert rep.status == "ok" and rep.failed == 1
    c = st.company_by_key("co01")
    assert c.consecutive_failures == 1
    assert c.last_scraped_at == shift(T0, days=15)        # stamped on attempt
    open_jobs = st.conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE company_id = ? AND closed_at IS NULL",
        (c.id,)).fetchone()[0]
    assert open_jobs == 2                                  # a failure closes nothing


def test_pipeline_outage_charges_nobody_and_stamps_nobody():
    cfg, st = _world(10)
    rep = _run(cfg, st, fetcher=fail_fetcher)
    assert rep.status == "aborted_unhealthy"
    assert all(c.consecutive_failures == 0 for c in st.companies())
    assert all(c.last_scraped_at is None for c in st.companies())
    assert st.list_runs()[0]["status"] == "aborted_unhealthy"
    # Re-running retries the very same batch.
    assert _run(cfg, st, now=shift(T0, seconds=60)).due == rep.due


def test_pipeline_quarantines_after_threshold_and_leaves_the_due_queue():
    cfg, st = _world(10)
    for k in range(3):                                     # quarantine_threshold = 3
        _run(cfg, st, fetcher=failing_only("co01"), now=shift(T0, days=15 * k))
    c = st.company_by_key("co01")
    assert c.quarantined_at is not None and c.probation_due_run is not None
    rep = _run(cfg, st, now=shift(T0, days=45))
    assert "Co01" not in rep.due                           # back only via probation


def test_pipeline_crash_before_stamp_is_a_no_op_and_is_reaped():
    cfg, st = _world(10)

    def exploding(*a, **k):
        raise RuntimeError("boom")
    real = st.relink_orphan_applications
    st.relink_orphan_applications = exploding               # crash after persist
    try:
        _run(cfg, st)
        raise AssertionError("the stub crash did not fire")
    except RuntimeError:
        pass
    st.relink_orphan_applications = real
    assert all(c.last_scraped_at is None for c in st.companies())
    assert st.list_runs()[0]["status"] == "running"
    rep = _run(cfg, st, now=shift(T0, seconds=7200))       # past per_run_timeout
    assert {r["run_no"]: r["status"] for r in st.list_runs()}[1] == "failed"
    assert rep.status == "ok" and len(rep.due) == 10       # the batch comes round


def test_pipeline_relinks_a_migrated_application():
    cfg, st = _world(1)
    st.set_application_status("v1-id", "applied", company="Co01", role="Backend",
                              url="https://co01.example.com/jobs/0")
    rep = _run(cfg, st)
    assert rep.relinked == 1
    assert st.application("v1-id") is None
    assert [a["status"] for a in st.applications()] == ["applied"]



# ---------------- stages [3]-[6] wired (M4/M5) ----------------

class _AcceptSingapore(Backend):
    """Accepts Singapore postings, rejects the rest; counts its calls."""
    name = "stub"

    def __init__(self):
        self.calls = 0

    @property
    def available(self):
        return True

    def complete(self, model, system, user, max_tokens=4096):
        import json
        self.calls += 1
        out, cur = [], None
        for line in user.splitlines():
            if line.startswith("<posting id="):
                cur = line.split('"')[1]
            elif line.startswith("LOCATION:") and cur:
                sg = "singapore" in line.lower()
                out.append({"id": cur, "decision": "accept" if sg else "reject",
                            "is_singapore": sg, "yoe_min": 0, "reason": "stub"})
                cur = None
        return Completion(json.dumps({"decisions": out}), 100, 10)


def mixed_fetcher(client, company):
    jobs = [RawJob(external_id=f"{company.key}-sg", title="Backend Engineer",
                   url=f"https://{company.key}.example.com/jobs/sg",
                   location="Singapore",
                   description="Build Python services on Kafka and Kubernetes."),
            RawJob(external_id=f"{company.key}-us", title="Backend Engineer",
                   url=f"https://{company.key}.example.com/jobs/us",
                   location="Austin, TX, United States",
                   description="Python and Kafka."),
            RawJob(external_id=f"{company.key}-sr", title="Senior Backend Engineer",
                   url=f"https://{company.key}.example.com/jobs/sr",
                   location="Singapore", description="Python.")]
    return FetchOutcome(company.id, True, jobs=jobs, provider=company.provider)


def test_pipeline_funnel_shortlists_only_what_survives_rules_and_model():
    cfg, st = _world(2)
    model = _AcceptSingapore()
    rep = _run(cfg, st, fetcher=mixed_fetcher, backend=model)
    s = rep.stats
    assert s["prefilter_evaluated"] == 6 and s["prefilter_passed"] == 2
    assert s["prefilter_rejected_by_rule"] == {"location_explicit": 2, "title_deny": 2}
    assert s["judged"] == 2 and model.calls == 1
    import json
    doc = json.loads(Path(cfg.shortlist_path).read_text(encoding="utf-8"))
    assert [j["url"].rsplit("/", 1)[1] for j in doc["jobs"]] == ["sg", "sg"]
    assert "status" not in json.dumps(doc)             # D-5


def test_pipeline_decisions_are_not_paid_for_twice():
    cfg, st = _world(1)
    model = _AcceptSingapore()
    _run(cfg, st, fetcher=mixed_fetcher, backend=model)
    _run(cfg, st, fetcher=mixed_fetcher, backend=model, now=shift(T0, days=15))
    assert model.calls == 1


def test_pipeline_without_a_model_leaves_survivors_waiting():
    cfg, st = _world(1)
    rep = _run(cfg, st, fetcher=mixed_fetcher)          # OffBackend
    assert rep.stats["awaiting_model"] == 1 and "judged" not in rep.stats
    later = _run(cfg, st, fetcher=mixed_fetcher, backend=_AcceptSingapore(),
                 now=shift(T0, days=15))
    assert later.stats["judged"] == 1                   # picked up next run
