"""The judging layer: which transport is built, and the decide stage on top.

Qwen via Ollama is the only model transport since M14 (the Claude CLI and API
transports and the in-session review handoff are gone); the Ollama wire format
itself is covered in test_ollama.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import json

from jobscraper import backends as B


def test_backend_choice_follows_config():
    assert B.build({"enable_llm": False, "backend": "ollama"}).name == "off"
    assert B.build({"enable_llm": True, "backend": "off"}).name == "off"
    assert B.build({"enable_llm": True, "backend": "ollama"}).name == "ollama"
    assert B.build({"enable_llm": True}).name == "ollama", "Qwen is the default"
    for gone in ("cli", "api", "nonsense"):
        bad = B.build({"enable_llm": True, "backend": gone})
        assert bad.name == "off" and gone in bad.unavailable_reason


def test_no_claude_transport_is_left():
    """M14: Haiku is out of the application, judge and resume parser alike."""
    src = (Path(__file__).resolve().parents[1] / "src" / "jobscraper")
    for f in src.rglob("*.py"):
        text = f.read_text(encoding="utf-8").lower()
        for marker in ("claude -p", "import anthropic", "claude-haiku"):
            assert marker not in text, f"{f.name} still mentions {marker!r}"


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

    def complete(self, system, user, max_tokens=4096):
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
                     model="qwen3:14b", lookup=lambda j, h: cache.get((j, h)),
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



def test_fit_contract_code_decides_not_the_model():
    """The model reports facts (fit, is_singapore, yoe_min); code decides.
    Measured 2026-09-24: Qwen3-14B rejected 3-year roles "on experience" however
    the prompt was worded - with `fit`, experience is not the model's call."""
    got = DC.parse_decisions(json.dumps({"decisions": [
        {"id": "a", "fit": True, "is_singapore": True, "yoe_min": 3, "reason": "backend"},
        {"id": "b", "fit": False, "is_singapore": True, "yoe_min": 0, "reason": "sales"},
        {"id": "c", "fit": "true", "is_singapore": True, "yoe_min": 1, "reason": "x"},
        {"id": "d", "decision": "accept", "is_singapore": True, "yoe_min": 0,
         "reason": "legacy shape"},
        {"id": "e", "fit": "maybe", "is_singapore": True, "reason": "unparseable"}]}))
    assert got["a"]["decision"] == "accept"     # 3 years is within the cap
    assert got["b"]["decision"] == "reject"
    assert got["c"]["decision"] == "accept"
    assert got["d"]["decision"] == "accept"     # the old contract still parses
    assert "e" not in got                       # neither fit nor decision: retried
    final, _, downgraded = DC.guard(got["a"]["decision"], True, 3, "", 3)
    assert final == "accept" and not downgraded
    assert DC.guard("accept", True, 4, "", 3)[0] == "reject"   # the cap is code's


def test_prompt_asks_for_facts_not_a_verdict():
    s = DC.system_prompt(3, ["product management", "finance"])
    assert '"fit": true | false' in s and '"decision"' not in s
    assert "applied by code" in s
    # The user's interests reach the model, with the lax instruction.
    assert "product management; finance" in s and "When unsure, answer true" in s
    assert "software engineering" in DC.system_prompt(3)   # defaults when unset
    u = DC._user_prompt("x", [DC.Posting("j1", "T", "LOCATION: SG")])
    assert '"fit": true | false' in u and '"j1"' in u
