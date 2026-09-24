"""The judging layer: model transport, and the in-session review handoff.

The backend tests cover `backends.py`, which PRD section 9 marks REUSE - it is
the cheap-model transport v2 is built on (D-6), so these must keep passing
through the whole rebuild.

The review tests cover `review.py` (KEEP). M9-T1 repoints it at the new schema;
until then these prove the content-hash caching discipline that v2's `decisions`
table inherits.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import json
import tempfile

from jobscraper import backends as B
from jobscraper import review as R
from jobscraper.config import load_config, load_profile
from jobscraper.llm import _key
from jobscraper.models import Candidate, RawJob, ScoreBreakdown
from jobscraper.store import Store

def _store(n=25):
    db = Path(tempfile.mkdtemp()) / "t.db"
    st = Store(db)
    st.sync_companies([{"ordinal": i, "name": f"C{i}", "tier": "T3",
                        "category": "Fintech", "careers_url": "https://x/careers",
                        "role_type_hint": "SWE"} for i in range(1, n + 1)])
    return st

def _scored_job(st, cid, jid, title, score, desc="Backend role in Singapore."):
    raw = RawJob(external_id=jid, title=title, url=f"https://x/{jid}",
                 location="Singapore", description=desc)
    st.upsert_job(jid, cid, raw, 1, True)
    st.commit()
    cand = Candidate(job_id=jid, company=st.get_company(cid), raw=raw)
    cand.score = ScoreBreakdown(total=score)
    st.save_score(cand, 1)
    return raw

def _review_setup(tmp):
    """A store plus a Config/Profile pointing at a throwaway output dir."""
    st = _store(3)
    cfg = load_config()
    cfg.raw["paths"]["output_dir"] = str(tmp)
    return st, cfg, load_profile()

def test_model_ids_map_onto_cli_aliases():
    assert B.cli_model_alias("claude-sonnet-5") == "sonnet"
    assert B.cli_model_alias("claude-haiku-4-5-20251001") == "haiku"
    assert B.cli_model_alias("claude-opus-5") == "opus"
    # Anything unrecognised is handed to the CLI untouched.
    assert B.cli_model_alias("some-future-model") == "some-future-model"

def test_backend_choice_follows_config():
    assert B.build({"enable_llm": False, "backend": "cli"}).name == "off"
    assert B.build({"enable_llm": True, "backend": "off"}).name == "off"
    assert B.build({"enable_llm": True, "backend": "cli"}).name == "cli"
    bad = B.build({"enable_llm": True, "backend": "nonsense"})
    assert bad.name == "off" and "nonsense" in bad.unavailable_reason

def test_backend_says_so_when_the_cli_is_not_installed():
    # An empty `binary` means auto-detect, so hide `claude` from PATH lookup to
    # reach the not-installed path on a machine that does have it.
    real_which = B.shutil.which
    B.shutil.which = lambda _name: None
    try:
        b = B.ClaudeCliBackend(binary="")
        assert not b.available and "not on PATH" in b.unavailable_reason
        try:
            b.complete("claude-haiku-4-5", "sys", "user")
            raise AssertionError("a missing CLI must refuse, not pretend")
        except B.BackendError:
            pass
    finally:
        B.shutil.which = real_which

def test_a_broken_cli_path_fails_loudly_rather_than_hanging():
    b = B.ClaudeCliBackend(binary=str(Path(tempfile.mkdtemp()) / "no-such-claude"))
    assert b.available, "a configured path is taken at face value until used"
    try:
        b.complete("claude-haiku-4-5", "sys", "user")
        raise AssertionError("a bad binary path must raise")
    except B.BackendError as exc:
        assert "could not start" in str(exc)

def test_cli_envelope_survives_a_banner_line():
    assert B._envelope('{"result": "hi"}')["result"] == "hi"
    noisy = 'Some notice line\n{"result": "hi", "is_error": false}'
    assert B._envelope(noisy)["result"] == "hi"
    for junk in ("", "not json at all"):
        try:
            B._envelope(junk)
            raise AssertionError(f"{junk!r} should not parse")
        except B.BackendError:
            pass

def test_review_queue_holds_only_unjudged_in_band_postings():
    tmp = Path(tempfile.mkdtemp())
    st, cfg, prof = _review_setup(tmp)
    lo, hi = prof.thresholds["llm_band"]
    _scored_job(st, 1, "inband", "Graduate Software Engineer", (lo + hi) / 2)
    _scored_job(st, 1, "toolow", "Cleaner", float(lo) - 5)
    _scored_job(st, 1, "toohigh", "Perfect Match", float(hi) + 5)

    path, n = R.export_queue(cfg, prof, st)
    assert n == 1, f"expected only the in-band posting, got {n}"
    queued = json.loads(path.read_text(encoding="utf-8"))
    assert [j["id"] for j in queued["jobs"]] == ["inband"]
    # The queue has to carry everything a reviewer needs to decide.
    job = queued["jobs"][0]
    for field in ("id", "company", "title", "location", "score", "description"):
        assert field in job, f"queue entry is missing {field}"
    assert queued["candidate_profile"], "reviewer needs the candidate profile"

def test_applied_verdicts_are_cached_and_never_re_queued():
    tmp = Path(tempfile.mkdtemp())
    st, cfg, prof = _review_setup(tmp)
    lo, hi = prof.thresholds["llm_band"]
    mid = (float(lo) + float(hi)) / 2
    _scored_job(st, 1, "keepme", "Graduate Backend Engineer", mid)
    _scored_job(st, 2, "dropme", "Senior Staff Engineer", mid)

    _path, n = R.export_queue(cfg, prof, st)
    assert n == 2

    (tmp / R.VERDICTS_NAME).write_text(json.dumps({"results": [
        {"id": "keepme", "verdict": "strong", "confidence": 0.9,
         "reason": "grad role", "concerns": []},
        {"id": "dropme", "verdict": "reject", "confidence": 0.9,
         "reason": "too senior", "concerns": []},
    ]}), encoding="utf-8")

    stats = R.apply_verdicts(cfg, prof, st)
    assert stats["applied"] == 2, stats
    assert stats["tally"] == {"strong": 1, "reject": 1}, stats["tally"]
    # Only the strong one is exportable; the rejected one must not reach the tracker.
    assert stats["exported"] == 1, stats

    _path, n = R.export_queue(cfg, prof, st)
    assert n == 0, "a judged posting must not come round again"

def test_apply_ignores_unknown_ids_and_junk_verdicts():
    tmp = Path(tempfile.mkdtemp())
    st, cfg, prof = _review_setup(tmp)
    lo, hi = prof.thresholds["llm_band"]
    _scored_job(st, 1, "real", "Graduate Backend Engineer",
                (float(lo) + float(hi)) / 2)

    (tmp / R.VERDICTS_NAME).write_text(json.dumps({"results": [
        {"id": "real", "verdict": "STRONG", "confidence": 5, "reason": "x"},
        {"id": "ghost", "verdict": "strong", "confidence": 0.5, "reason": "x"},
        {"id": "real", "verdict": "maybe-ish", "confidence": 0.5, "reason": "x"},
    ]}), encoding="utf-8")

    stats = R.apply_verdicts(cfg, prof, st)
    assert stats["applied"] == 1, stats
    assert stats["unknown_id"] == 1 and stats["bad_verdict"] == 1, stats
    # Upper-cased verdict normalised, out-of-range confidence clamped.
    jd_hash = RawJob(external_id="real", title="Graduate Backend Engineer",
                     url="https://x/real", location="Singapore",
                     description="Backend role in Singapore.").jd_hash()
    row = st.get_cached(_key("real", jd_hash, 1, "c2"))
    assert row and row["verdict"] == "strong" and row["confidence"] == 1.0, row

def test_missing_verdicts_file_is_a_clear_error():
    tmp = Path(tempfile.mkdtemp())
    st, cfg, prof = _review_setup(tmp)
    try:
        R.apply_verdicts(cfg, prof, st)
        raise AssertionError("a missing verdicts file must not pass silently")
    except SystemExit as exc:
        assert "review --export" in str(exc)


# --------------------------------------------------------------------------
# M4-T2 - vital extract (PRD section 8.3[4])
#
# The decide step pays per character, so the extract has a hard budget. What
# must never be lost in the squeeze are the two facts the post-conditions guard:
# where the job is, and how many years it asks for.
# --------------------------------------------------------------------------

from jobscraper.decide import vital_extract

FIXTURES = Path(__file__).resolve().parent / "fixtures"
VITAL_LABELS = ("LOCATION: ", "EXPERIENCE: ", "REQUIREMENTS: ", "ROLE: ")


def _jd(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _lines(extract):
    lines = extract.split("\n")
    assert len(lines) == 4, extract
    for line, label in zip(lines, VITAL_LABELS):
        assert line.startswith(label), (label, line)
    return lines


def test_vital_extract_squeezes_a_real_12k_jd_and_keeps_location_and_years():
    jd = _jd("jd_edge_infrastructure_warsaw.json")
    assert len(jd["jd_text"]) >= 12000, "the fixture must be a real ~12k JD"

    out = vital_extract(jd["title"], jd["location"], jd["jd_text"])

    assert len(out) <= 800, len(out)
    loc, exp, req, role = _lines(out)
    assert "Warsaw, Poland" in loc, loc               # the field, verbatim
    assert "Warsaw location" in loc, loc              # and the body's place line
    assert "5+ years experience" in exp, exp          # the deciding number survives
    assert "UNSTATED" not in req and "UNSTATED" not in role, out
    # Headings are found by meaning, not position: Palantir says "What We Require".
    assert "Active clearance" in out, out


def test_vital_extract_on_a_singapore_jd_with_shouted_headings():
    jd = _jd("jd_account_executive_singapore.json")
    assert len(jd["jd_text"]) >= 12000

    out = vital_extract(jd["title"], jd["location"], jd["jd_text"])

    assert len(out) <= 800, len(out)
    loc, exp, req, _role = _lines(out)
    assert "SG - Singapore" in loc and "Singapore" in loc.split("|", 1)[1], loc
    assert "5 years of sales experience" in exp, exp
    assert "UNSTATED" not in req, req


def test_vital_extract_marks_missing_sections_unstated():
    out = vital_extract("Backend Engineer", "", "We build payment rails. Join us.")
    loc, exp, req, role = _lines(out)
    assert loc == "LOCATION: UNSTATED | UNSTATED", loc
    assert exp == "EXPERIENCE: UNSTATED", exp
    assert req == "REQUIREMENTS: UNSTATED", req
    assert role == "ROLE: UNSTATED", role


def test_vital_extract_honours_the_limit_on_flattened_text():
    # Some adapters hand back one enormous line with no headings on their own
    # lines. The budget must still hold, and the years must still be found.
    body = ("Great culture and snacks. " * 300
            + "Requirements: 2-5 years of experience with Python and Kubernetes. "
            + "Degree in computer science. " + "Benefits galore. " * 300)
    for limit in (800, 300):
        out = vital_extract("Platform Engineer", "Singapore", body, limit=limit)
        assert len(out) <= limit, (limit, len(out))
    out = vital_extract("Platform Engineer", "Singapore", body)
    assert "2-5 years of experience" in out, out
    assert "REQUIREMENTS: UNSTATED" not in out, out
