"""The small-model backstops, wired through a whole run (AWS-2).

A judging deadline must end the run normally - shortlist written, companies
stamped - and a posting the model cannot answer for must stop costing calls.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from jobscraper.backends import Backend, Completion  # noqa: E402
from jobscraper.models import FetchOutcome, RawJob  # noqa: E402
from jobscraper.store import Store, shift  # noqa: E402
import test_pipeline as P  # noqa: E402


# ---------------------------------------------------------------- the store

def test_store_counts_decision_failures_per_extract_and_model():
    st = Store(Path(tempfile.mkdtemp()) / "t.db")
    assert st.decision_failures("j", 1, "h", "m") == 0
    assert st.add_decision_failure("j", 1, "h", "m") == 1
    assert st.add_decision_failure("j", 1, "h", "m") == 2
    assert st.decision_failures("j", 1, "h", "m") == 2
    assert st.decision_failures("j", 1, "h2", "m") == 0           # changed extract
    assert st.decision_failures("j", 1, "h", "other-model") == 0   # changed model
    assert st.decision_failures("j", 2, "h", "m") == 0             # new profile
    st.close()


# ---------------------------------------------------------------- a run

class _Judge(Backend):
    """Accepts every posting as Singapore; can be slow or deaf to one title."""
    name = "stub"
    model_id = "stub-model"

    def __init__(self, delay=0.0, deaf_to=None):
        self.delay, self.deaf_to, self.calls = delay, deaf_to, 0

    @property
    def available(self):
        return True

    def complete(self, system, user, max_tokens=4096, schema=None, timeout=None):
        self.calls += 1
        time.sleep(self.delay)
        if self.deaf_to and self.deaf_to in user:
            return Completion("I cannot help with that.", 5, 5)
        ids = [ln.split('"')[1] for ln in user.splitlines()
               if ln.startswith("<posting id=")]
        return Completion(json.dumps({"decisions": [
            {"id": i, "fit": True, "is_singapore": True, "yoe_min": 0, "reason": "ok"}
            for i in ids]}), 100, 10)


def _sg_fetcher(client, company):
    return FetchOutcome(company.id, True, provider=company.provider, jobs=[
        RawJob(f"{company.key}-sg", "Backend Engineer",
               f"https://{company.key}.example.com/jobs/sg", "Singapore",
               description="Build Python services on Kafka and Kubernetes.")])


def test_a_deadline_ended_run_still_writes_the_shortlist_and_stamps_its_companies():
    cfg, st = P._world(3)
    cfg.raw["budget"]["decide_batch"] = 1
    cfg.raw["budget"]["decide_deadline_s"] = 0.03       # personal: config key, not env
    judge = _Judge(delay=0.06)
    rep = P._run(cfg, st, fetcher=_sg_fetcher, backend=judge)
    assert rep.status == "ok"
    assert judge.calls == 1                                   # the 2nd and 3rd were not started
    assert rep.stats["judged"] == 1 and rep.stats["decide_deadline_hit"] is True
    assert rep.stats["skipped_by_deadline"] == 2 and rep.stats["undecided"] == 2
    doc = json.loads(Path(cfg.shortlist_path).read_text(encoding="utf-8"))
    assert len(doc["jobs"]) == 1                              # written, with what was judged
    stamped = st.conn.execute(
        "SELECT COUNT(*) FROM companies WHERE last_scraped_at IS NOT NULL").fetchone()[0]
    assert stamped == 3                                       # mark_attempted ran
    run = st.conn.execute("SELECT status FROM runs").fetchone()[0]
    assert run == "ok"
    # The next run (nothing due) judges the rest and extends the shortlist.
    later = P._run(cfg, st, fetcher=_sg_fetcher, backend=_Judge(), now=shift(P.T0, days=1))
    assert later.stats["judged"] == 2
    doc = json.loads(Path(cfg.shortlist_path).read_text(encoding="utf-8"))
    assert len(doc["jobs"]) == 3
    st.close()


def test_without_a_deadline_the_run_judges_everything():
    cfg, st = P._world(3)
    cfg.raw["budget"]["decide_batch"] = 1
    cfg.raw["budget"].pop("decide_deadline_s", None)
    rep = P._run(cfg, st, fetcher=_sg_fetcher, backend=_Judge())
    assert rep.stats["judged"] == 3 and rep.stats["decide_deadline_hit"] is False
    st.close()


def test_a_posting_the_model_cannot_answer_for_is_parked_after_three_runs():
    cfg, st = P._world(1)
    judge = _Judge(deaf_to="Platform Engineer")                # never answers for this one

    def two(client, company):
        return FetchOutcome(company.id, True, provider=company.provider, jobs=[
            RawJob(f"{company.key}-{t}", f"{t} Engineer",
                   f"https://{company.key}.example.com/jobs/{t}", "Singapore",
                   description="Build Python services on Kafka and Kubernetes.")
            for t in ("Backend", "Platform")])
    P._run(cfg, st, fetcher=two, backend=judge)                # failure 1 (+ the run)
    for day in (1, 2):                                         # nothing due: funnel only
        rep = P._run(cfg, st, fetcher=two, backend=judge, now=shift(P.T0, days=day))
        assert rep.stats["undecided"] == 1
    assert rep.stats["undecidable"] == 1                        # parked on the third
    calls = judge.calls
    rep = P._run(cfg, st, fetcher=two, backend=judge, now=shift(P.T0, days=3))
    assert judge.calls == calls                                # not sent any more
    assert rep.stats["undecidable"] == 1 and rep.stats["undecided"] == 0
    assert rep.stats["model_calls"] == 0
    st.close()


def test_a_dead_model_parks_nothing_across_runs():
    cfg, st = P._world(1)
    judge = _Judge(deaf_to="Backend Engineer")                 # nothing is ever readable
    for day in range(5):
        rep = P._run(cfg, st, fetcher=_sg_fetcher, backend=judge,
                     now=shift(P.T0, days=day))
        assert rep.stats["undecided"] == 1 and rep.stats["undecidable"] == 0
    assert st.conn.execute("SELECT COUNT(*) FROM decision_failures").fetchone()[0] == 0
    st.close()


def test_the_batch_is_stamped_as_of_the_start_of_the_run():
    """A long run must not push a company past the 12-hour grace of a weekly cycle."""
    cfg, st = P._world(1)

    def slow(client, company):
        time.sleep(1.2)
        return _sg_fetcher(client, company)
    rep = P._run(cfg, st, fetcher=slow)
    started = st.conn.execute("SELECT started_at FROM runs WHERE run_no = ?",
                              (rep.run_no,)).fetchone()[0]
    stamped = st.conn.execute("SELECT last_scraped_at FROM companies").fetchone()[0]
    assert stamped == started
    st.close()


def test_the_guard_checks_the_location_line_against_the_rules_allow_tokens():
    """The model says Singapore for a posting that never names it."""
    cfg, st = P._world(1)

    def fetch(client, company):
        return FetchOutcome(company.id, True, provider=company.provider, jobs=[
            RawJob("a", "Backend Engineer", "https://x.example.com/a", "APAC",
                   description="Build Python services on Kafka."),
            RawJob("b", "Backend Engineer", "https://x.example.com/b", "APAC",
                   description="Based in Singapore. Build Python services on Kafka.")])
    rep = P._run(cfg, st, fetcher=fetch, backend=_Judge())
    assert rep.stats["prefilter_passed"] == 2                  # APAC is vague: left to the model
    assert rep.stats["rejected_by_postcondition"] == 1
    doc = json.loads(Path(cfg.shortlist_path).read_text(encoding="utf-8"))
    assert [j["url"].rsplit("/", 1)[1] for j in doc["jobs"]] == ["b"]
    st.close()
