"""The judging layer: model transport, and the in-session review handoff.

The backend tests cover `backends.py`, which PRD section 9 marks REUSE - it is
the cheap-model transport v2 is built on (D-6), so these must keep passing
through the whole rebuild.

The review tests cover `review.py`, the in-session transport for the same
decide step (ported to the v2 schema at M9-T1): its answers must go through the
same guard, into the same cache, as the automatic path.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import json
import tempfile

from jobscraper import backends as B
from jobscraper import review as R
from jobscraper.config import load_config
from jobscraper.models import RawJob
from jobscraper.store import Store


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

REVIEW_PROFILE = {"profile_version": 1, "summary": "new grad backend engineer",
                  "skills": ["python"], "target_titles": ["backend engineer"],
                  "title_aliases": {}, "years_experience": 0}


def _review_world():
    """A temp DB with two prefilter survivors and one reject, plus a config
    whose data paths point into the temp dir."""
    from jobscraper import filter as F
    tmp = Path(tempfile.mkdtemp())
    cfg = load_config()
    cfg.raw["paths"]["shortlist"] = str(tmp / "shortlist.json")
    st = Store(tmp / "t.db")
    rules = F.load_rules(cfg.rules_path)
    cid = st.insert_company("co", "Co", "https://co.example.com")
    ids = {}
    for ext, passed in (("a", True), ("b", True), ("c", False)):
        raw = RawJob(ext, f"Backend Engineer {ext}", f"https://co.example.com/{ext}",
                     "Singapore", description="Python services.")
        jid = raw.job_id(cid, "greenhouse")
        st.upsert_job(jid, cid, raw, 1, True)
        st.commit()
        st.save_prefilter(jid, 1, rules.hash, passed, None if passed else "title_deny")
        ids[ext] = jid
    return tmp, cfg, st, rules, ids


def _verdicts(tmp, items):
    (tmp / R.VERDICTS_NAME).write_text(json.dumps({"decisions": items}),
                                       encoding="utf-8")


def test_review_queue_holds_only_undecided_survivors():
    tmp, cfg, st, rules, ids = _review_world()
    path, n = R.export_queue(cfg, st, REVIEW_PROFILE, rules)
    q = json.loads(path.read_text(encoding="utf-8"))
    assert n == 2 and sorted(q["ids"]) == sorted([ids["a"], ids["b"]])
    # The session is asked exactly what `claude -p` is asked.
    assert "DO NOT judge experience" in q["system_prompt"]
    assert ids["a"] in q["user_prompt"] and "Reply with ONLY" in q["user_prompt"]


def test_review_answers_pass_the_same_guard_and_are_never_requeued():
    tmp, cfg, st, rules, ids = _review_world()
    _verdicts(tmp, [
        {"id": ids["a"], "decision": "accept", "is_singapore": True, "yoe_min": 0,
         "reason": "fits"},
        # The model says accept, but 5 years is over the cap: the guard wins.
        {"id": ids["b"], "decision": "accept", "is_singapore": True, "yoe_min": 5,
         "reason": "fits"},
    ])
    stats = R.apply_verdicts(cfg, st, REVIEW_PROFILE, rules)
    assert stats["applied"] == 2 and stats["accepted"] == 1
    assert stats["rejected_by_postcondition"] == 1 and stats["shortlisted"] == 1
    _path, n = R.export_queue(cfg, st, REVIEW_PROFILE, rules)
    assert n == 0, "a decided posting must not come round again"


def test_review_ignores_unknown_ids_and_never_overwrites():
    tmp, cfg, st, rules, ids = _review_world()
    _verdicts(tmp, [{"id": ids["a"], "decision": "reject", "is_singapore": False,
                     "yoe_min": 0, "reason": "first"}])
    R.apply_verdicts(cfg, st, REVIEW_PROFILE, rules)
    _verdicts(tmp, [
        {"id": ids["a"], "decision": "accept", "is_singapore": True, "yoe_min": 0,
         "reason": "second opinion"},                      # already decided
        {"id": "ghost", "decision": "accept", "is_singapore": True, "yoe_min": 0,
         "reason": "x"},                                   # unknown
        {"id": ids["c"], "decision": "accept", "is_singapore": True, "yoe_min": 0,
         "reason": "x"},                                   # prefilter reject
    ])
    stats = R.apply_verdicts(cfg, st, REVIEW_PROFILE, rules)
    assert stats["applied"] == 0 and stats["not_pending"] == 3
    rows = st.conn.execute("SELECT decision, reason FROM decisions").fetchall()
    assert [tuple(r) for r in rows] == [("reject", "first")]


def test_missing_verdicts_file_is_a_clear_error():
    _tmp, cfg, st, rules, _ids = _review_world()
    try:
        R.apply_verdicts(cfg, st, REVIEW_PROFILE, rules)
        raise AssertionError("a missing verdicts file must not pass silently")
    except FileNotFoundError as exc:
        assert "review_queue.json" in str(exc)


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


# ---------------- M4-T3: decision call + accept guard ----------------

import json as _json

from jobscraper import decide as DC
from jobscraper.backends import Backend, BackendError, Completion


class _StubBackend(Backend):
    """Answers every posting in a call with the same canned object."""
    name = "stub"

    def __init__(self, answer=None, raw_text=None, fail=False):
        self.answer, self.raw_text, self.fail = answer, raw_text, fail
        self.calls = 0

    @property
    def available(self):
        return True

    def complete(self, model, system, user, max_tokens=4096):
        self.calls += 1
        if self.fail:
            raise BackendError("transport down")
        if self.raw_text is not None:
            return Completion(self.raw_text, 10, 5)
        ids = [line.split('"')[1] for line in user.splitlines()
               if line.startswith("<posting id=")]
        return Completion(_json.dumps({"decisions": [
            dict(self.answer, id=i) for i in ids]}), 100 * len(ids), 20 * len(ids))


def _decide(backend, postings=None, cache=None, **kw):
    cache = {} if cache is None else cache
    postings = postings or [DC.Posting("j1", "Backend Engineer",
                                       "LOCATION: Singapore\nEXPERIENCE: UNSTATED")]
    return DC.decide(postings, summary="new grad backend engineer", backend=backend,
                     model="claude-haiku-4-5", lookup=lambda j, h: cache.get((j, h)),
                     save=lambda d: cache.__setitem__((d.job_id, d.vital_hash), {
                         "decision": d.decision, "is_singapore": d.is_singapore,
                         "yoe_min": d.yoe_min, "reason": d.reason, "model": d.model}),
                     **kw)


def test_decide_accept_with_unconfirmed_location_is_stored_as_reject():
    """D-7: `is_singapore: null` is not Singapore."""
    cache = {}
    out, st = _decide(_StubBackend({"decision": "accept", "is_singapore": None,
                                    "yoe_min": 0, "reason": "fits"}), cache=cache)
    assert out[0].decision == "reject" and out[0].reason == DC.REJECT_LOCATION
    assert next(iter(cache.values()))["decision"] == "reject"
    assert st.rejected_by_postcondition == 1 and st.accepted == 0


def test_decide_accept_outside_singapore_is_stored_as_reject():
    out, _ = _decide(_StubBackend({"decision": "accept", "is_singapore": False,
                                   "yoe_min": 0, "reason": "fits"}))
    assert out[0].decision == "reject" and out[0].reason == DC.REJECT_LOCATION


def test_decide_accept_over_the_years_ceiling_is_stored_as_reject():
    """D-12: yoe_min 4 > 3."""
    out, _ = _decide(_StubBackend({"decision": "accept", "is_singapore": True,
                                   "yoe_min": 4, "reason": "fits"}))
    assert out[0].decision == "reject" and out[0].reason == "requires more than 3 years"


def test_decide_a_clean_accept_survives_the_guard():
    out, st = _decide(_StubBackend({"decision": "accept", "is_singapore": True,
                                    "yoe_min": 0, "reason": "SG backend, new grad"}))
    assert out[0].decision == "accept" and st.accepted == 1
    assert st.input_tokens == 100 and st.model_calls == 1


def test_decide_truthy_strings_do_not_count_as_singapore():
    out, _ = _decide(_StubBackend({"decision": "accept", "is_singapore": "yes",
                                   "yoe_min": 0, "reason": "x"}))
    assert out[0].decision == "reject"


def test_decide_is_cached_and_never_paid_twice():
    b = _StubBackend({"decision": "reject", "is_singapore": False, "yoe_min": 0,
                      "reason": "US only"})
    cache = {}
    _decide(b, cache=cache)
    out, st = _decide(b, cache=cache)
    assert b.calls == 1 and st.cached == 1 and out[0].cached


def test_decide_a_changed_extract_is_decided_again():
    b = _StubBackend({"decision": "reject", "is_singapore": False, "yoe_min": 0,
                      "reason": "x"})
    cache = {}
    _decide(b, cache=cache)
    _decide(b, cache=cache, postings=[DC.Posting("j1", "Backend Engineer",
                                                 "LOCATION: Singapore, SG")])
    assert b.calls == 2


def test_decide_batches_by_decide_batch():
    b = _StubBackend({"decision": "reject", "is_singapore": False, "yoe_min": 0,
                      "reason": "x"})
    ps = [DC.Posting(f"j{i}", "Backend Engineer", f"LOCATION: X{i}") for i in range(45)]
    _, st = _decide(b, postings=ps, batch_size=20)
    assert b.calls == 3 and st.judged == 45


def test_decide_malformed_answers_leave_postings_undecided():
    cache = {}
    out, st = _decide(_StubBackend(raw_text="Sure! Here is my analysis..."), cache=cache)
    assert out == [] and st.undecided == 1 and cache == {}


def test_decide_transport_failures_stand_down_and_store_nothing():
    b = _StubBackend(fail=True)
    ps = [DC.Posting(f"j{i}", "T", f"LOCATION: X{i}") for i in range(100)]
    out, st = _decide(b, postings=ps, batch_size=20, max_consecutive_failures=3)
    assert b.calls == 3 and st.undecided == 100 and out == []


def test_decide_parses_a_fenced_answer():
    text = ('```json\n{"decisions": [{"id": "j1", "decision": "ACCEPT", '
            '"is_singapore": true, "yoe_min": "2", "reason": "ok"}]}\n```')
    got = DC.parse_decisions(text)
    assert got["j1"] == {"decision": "accept", "is_singapore": True, "yoe_min": 2,
                         "reason": "ok"}



def test_cli_system_prompt_goes_by_file_not_argv():
    """claude.CMD cuts an argument at its first newline (measured 2026-09-24):
    a multi-line system prompt must travel as a file, whole."""
    import subprocess
    from jobscraper import backends as B

    seen = {}

    def fake_run(argv, **kw):
        assert "--system-prompt" not in argv
        path = argv[argv.index("--system-prompt-file") + 1]
        seen["text"] = Path(path).read_text(encoding="utf-8")
        seen["path"] = path
        return subprocess.CompletedProcess(argv, 0, stdout='{"result": "ok"}', stderr="")

    b = B.ClaudeCliBackend(binary="claude-fake")
    real = subprocess.run
    B.subprocess.run = fake_run
    try:
        b.complete("claude-haiku-4-5", "line one\nline two", "hi")
    finally:
        B.subprocess.run = real
    assert seen["text"] == "line one\nline two"
    assert not Path(seen["path"]).exists()          # the temp file is cleaned up
