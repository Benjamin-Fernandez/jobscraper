"""Small-model backstops (AWS-1 env overrides, AWS-2 / AWS-D3).

A 1.7B model on a CPU miscopies long ids, drifts off the format and is slow, so
code carries what the prompt cannot: short ids, a JSON schema, an output cap,
splitting a failed batch, a retry limit, a location check on the evidence, and a
deadline per run. The transport side is pinned with httpx's MockTransport (no
Ollama needed); the decide side with a stub backend.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx  # noqa: E402

from jobscraper import backends as B  # noqa: E402
from jobscraper import decide as DC  # noqa: E402
from jobscraper.backends import Backend, BackendError, Completion  # noqa: E402

URL = "http://ollama.test:11434"
HEX = "0123456789abcdef0123456789abcdef"


# ---------------------------------------------------------------- transport

def _server(show=None, show_status=200, seen=None, shown=None,
            chat_extra=None):
    """A fake Ollama. `show` is the /api/show answer's `capabilities`."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [
                {"name": m} for m in ("qwen3:1.7b", "qwen3:14b",
                                      "qwen3:4b-instruct-2507-q4_K_M")]})
        if request.url.path == "/api/show":
            if shown is not None:
                shown.append(json.loads(request.content))
            if show_status != 200:
                return httpx.Response(show_status, json={"error": "nope"})
            body = {} if show is None else {"capabilities": show}
            return httpx.Response(200, json=body)
        if request.url.path == "/api/chat":
            if seen is not None:
                seen.append(json.loads(request.content))
            data = {"message": {"role": "assistant", "content": '{"decisions": []}'},
                    "prompt_eval_count": 800, "eval_count": 60,
                    "prompt_eval_duration": 4_000_000_000, "eval_duration": 6_500_000_000}
            data.update(chat_extra or {})
            return httpx.Response(200, json=data)
        return httpx.Response(404)
    return handler


def _backend(handler, model="qwen3:1.7b"):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return B.OllamaBackend(url=URL, model=model, num_ctx=8192, client=client)


def test_schema_goes_into_format_and_no_schema_still_means_json():
    seen: list = []
    b = _backend(_server(show=["completion", "thinking"], seen=seen))
    schema = {"type": "object", "properties": {"decisions": {"type": "array"}}}
    b.complete("S", "U", max_tokens=160, schema=schema)
    b.complete("S", "U")
    assert seen[0]["format"] == schema and seen[0]["options"]["num_predict"] == 160
    assert seen[1]["format"] == "json" and seen[1]["options"]["num_predict"] == 4096


def test_think_false_is_sent_when_the_model_lists_thinking():
    seen: list = []
    b = _backend(_server(show=["completion", "tools", "thinking"], seen=seen),
                 model="qwen3:14b")
    b.complete("S", "U")
    assert seen[0]["think"] is False


def test_think_is_left_out_when_the_model_has_no_thinking_capability():
    """qwen3:4b-instruct-2507 has none, and Ollama answers 400 to think:false."""
    seen: list = []
    b = _backend(_server(show=["completion", "tools"], seen=seen),
                 model="qwen3:4b-instruct-2507-q4_K_M")
    b.complete("S", "U")
    assert "think" not in seen[0]


def test_think_false_stays_when_show_cannot_tell_us():
    """An older Ollama (no capabilities) or a failed /api/show keeps today's request."""
    for kw in ({"show": None}, {"show_status": 500}):
        seen: list = []
        b = _backend(_server(seen=seen, **kw))
        b.complete("S", "U")
        assert seen[0]["think"] is False, kw


def test_the_capability_is_asked_once_per_backend_and_for_its_model():
    seen, shown = [], []
    b = _backend(_server(show=["thinking"], seen=seen, shown=shown))
    for _ in range(3):
        b.complete("S", "U")
    assert len(seen) == 3 and len(shown) == 1
    assert shown[0]["model"] == "qwen3:1.7b"


def test_durations_are_recorded_next_to_the_token_counts():
    b = _backend(_server(show=["thinking"]))
    comp = b.complete("S", "U")
    assert (comp.input_tokens, comp.output_tokens) == (800, 60)
    assert (comp.prompt_eval_ns, comp.eval_ns) == (4_000_000_000, 6_500_000_000)
    bare = _backend(_server(show=["thinking"],
                            chat_extra={"prompt_eval_duration": None})).complete("S", "U")
    assert bare.prompt_eval_ns == 0


# (cloud env-override tests, AWS-1, not ported: personal has no env overrides, R-12)


# ---------------------------------------------------------------- decide

SG = "LOCATION: Singapore | Based in Singapore\nEXPERIENCE: UNSTATED"


def _p(n, vital=SG):
    return DC.Posting(f"{HEX[:-4]}{n:04x}", f"Engineer {n}", vital)


class _Model(Backend):
    """Answers by the short id in each <posting id="pN"> tag.

    `behave(call_no, ids)` returns one of: a list of ids to answer, the string
    "garbage", or "down" (a transport error).
    """
    name = "stub"

    def __init__(self, behave=None):
        self.behave = behave or (lambda n, ids: ids)
        self.calls: list[dict] = []

    @property
    def available(self):
        return True

    def complete(self, system, user, max_tokens=4096, schema=None, timeout=None):
        ids = [ln.split('"')[1] for ln in user.splitlines()
               if ln.startswith("<posting id=")]
        self.calls.append({"ids": ids, "user": user, "max_tokens": max_tokens,
                           "schema": schema, "timeout": timeout})
        act = self.behave(len(self.calls), ids)
        if act == "down":
            raise BackendError("transport down")
        if act == "length":
            return Completion('{"decisions": [{"id": "p1", "fi', 10, 99, 0, 0, "length")
        if act == "garbage":
            return Completion("Sure! Here is my screening report.", 10, 5,
                              2_000_000_000, 3_000_000_000)
        return Completion(json.dumps({"decisions": [
            {"id": i, "fit": True, "is_singapore": True, "yoe_min": 0, "reason": "ok"}
            for i in act]}), 100, 20, 1_000_000_000, 2_000_000_000)


class _Memory:
    """The store's side of decide: decisions and per-posting failure counts."""

    def __init__(self):
        self.rows, self.fails = {}, {}

    def kwargs(self):
        return dict(
            lookup=lambda j, h: self.rows.get((j, h)),
            save=lambda d: self.rows.__setitem__((d.job_id, d.vital_hash), {
                "decision": d.decision, "is_singapore": d.is_singapore,
                "yoe_min": d.yoe_min, "reason": d.reason, "model": d.model}),
            failed_before=lambda j, h: self.fails.get((j, h), 0),
            record_failure=self._record)

    def _record(self, j, h):
        self.fails[(j, h)] = self.fails.get((j, h), 0) + 1
        return self.fails[(j, h)]


def _deaf_model(title):
    """A model that answers everything except calls that contain `title`."""
    def behave(n, ids):
        return "garbage" if title in model.calls[-1]["user"] else ids
    model = _Model(behave)
    return model


def _decide(backend, postings, mem=None, **kw):
    mem = mem or _Memory()
    return DC.decide(postings, summary="new grad", backend=backend, model="m",
                     batch_size=kw.pop("batch_size", 20), **mem.kwargs(), **kw)


def test_the_model_sees_short_ids_and_the_schema_limits_it_to_them():
    model = _Model()
    posts = [_p(i) for i in range(1, 4)]
    out, st = _decide(model, posts)
    call = model.calls[0]
    assert call["ids"] == ["p1", "p2", "p3"]
    assert HEX[:-4] not in call["user"]                   # no 32-hex id reaches the model
    enum = call["schema"]["properties"]["decisions"]["items"]["properties"]["id"]["enum"]
    assert enum == ["p1", "p2", "p3"]
    assert call["schema"]["properties"]["decisions"]["maxItems"] == 3
    # ...and the answers are mapped back to the real ids.
    assert sorted(d.job_id for d in out) == sorted(p.job_id for p in posts)
    assert st.judged == 3


def test_an_id_outside_the_batch_is_ignored_not_mapped():
    model = _Model(lambda n, ids: ids + ["p9", HEX])
    out, st = _decide(model, [_p(1), _p(2)])
    assert st.judged == 2 and len(out) == 2


def test_output_cap_leaves_room_for_the_longest_allowed_answer():
    model = _Model()
    _decide(model, [_p(i) for i in range(1, 8)], batch_size=5)
    assert [c["max_tokens"] for c in model.calls] == [130 * 5 + 64, 130 * 2 + 64]
    item = model.calls[0]["schema"]["properties"]["decisions"]["items"]
    assert item["properties"]["reason"]["maxLength"] == 120


def test_a_cut_off_answer_is_not_blamed_on_the_postings():
    model = _Model(lambda n, ids: "length")
    mem = _Memory()
    out, st = _decide(model, [_p(1), _p(2)], mem)
    assert out == [] and st.truncated == 1 and st.undecided == 2
    assert mem.fails == {} and st.splits == 0 and st.parse_failures == 0
    assert len(model.calls) == 1


def test_three_unreadable_calls_in_a_row_stop_the_run_as_an_outage():
    model = _Model(lambda n, ids: "garbage")
    mem = _Memory()
    out, st = _decide(model, [_p(i) for i in range(1, 9)], mem)
    assert [len(c["ids"]) for c in model.calls] == [8, 4, 2]       # then it stops
    assert st.outage and out == [] and st.undecided == 8
    assert mem.fails == {}                                          # nobody parked


def test_a_dead_model_blames_no_posting_even_alone():
    model = _Model(lambda n, ids: "garbage")
    mem = _Memory()
    for _ in range(4):
        _, st = _decide(model, [_p(1)], mem)
        assert st.parse_failures == 1 and st.newly_parked == 0
    assert mem.fails == {}


def test_a_working_model_resets_the_outage_count():
    # Two bad calls, a good one, two more bad ones: never three in a row.
    script = iter(["garbage", "garbage", "ok", "garbage", "garbage", "ok", "ok", "ok"])
    model = _Model(lambda n, ids: ids if next(script) == "ok" else "garbage")
    out, st = _decide(model, [_p(i) for i in range(1, 5)], batch_size=1)
    assert not st.outage


def test_durations_add_up_in_the_stats():
    model = _Model()
    _, st = _decide(model, [_p(1), _p(2)], batch_size=1)
    assert st.model_calls == 2
    assert (st.prompt_eval_s, st.eval_s) == (2.0, 4.0)


def test_a_garbled_answer_splits_the_batch_in_half_and_retries_down_to_one():
    # The model cannot manage more than two postings at once.
    model = _Model(lambda n, ids: ids if len(ids) <= 2 else "garbage")
    mem = _Memory()
    posts = [_p(i) for i in range(1, 9)]
    out, st = _decide(model, posts, mem)
    assert st.judged == 8 and st.undecided == 0
    sizes = [len(c["ids"]) for c in model.calls]
    assert sizes == [8, 4, 2, 2, 4, 2, 2]                 # halves, depth first, in order
    assert st.splits == 3 and mem.fails == {}              # recovered: nobody is blamed


def test_a_partial_answer_retries_only_the_missing_ones():
    model = _Model(lambda n, ids: ids[:2] if n == 1 else ids)
    out, st = _decide(model, [_p(i) for i in range(1, 5)])
    assert st.judged == 4
    assert [c["ids"] for c in model.calls] == [["p1", "p2", "p3", "p4"], ["p1", "p2"]]


def test_a_posting_that_fails_alone_is_counted_when_the_model_works_for_others():
    bad, good = _p(3), _p(4)
    model = _deaf_model("Engineer 3")
    mem = _Memory()
    out, st = _decide(model, [bad, good], mem)
    assert [d.job_id for d in out] == [good.job_id]
    assert st.undecided == 1 and st.parse_failures == 1
    assert mem.fails == {(bad.job_id, DC.vital_hash(bad.vital_text)): 1}


def test_a_lone_failing_posting_is_blamed_when_earlier_answers_are_cached():
    bad, good = _p(3), _p(4)
    mem = _Memory()
    _decide(_Model(), [good], mem)                        # run 1 caches the good one
    out, st = _decide(_deaf_model("Engineer 3"), [bad, good], mem)
    assert st.cached == 1 and mem.fails == {(bad.job_id, DC.vital_hash(bad.vital_text)): 1}


def test_three_failures_across_runs_park_the_posting_and_it_is_not_retried():
    bad, good = _p(3), _p(4)
    mem = _Memory()
    model = _deaf_model("Engineer 3")
    for run in (1, 2, 3):
        _, st = _decide(model, [bad, good], mem)
        assert st.undecidable == 0 and st.newly_parked == (1 if run == 3 else 0)
    calls = len(model.calls)
    out, st = _decide(model, [bad, good], mem)            # the fourth run
    assert len(model.calls) == calls                      # no call: it is parked, good cached
    assert st.undecidable == 1 and st.undecided == 0 and st.cached == 1


def test_a_changed_extract_or_a_recovered_model_gets_a_parked_posting_another_go():
    bad, good = _p(3), _p(4)
    mem = _Memory()
    for _ in range(3):
        _decide(_deaf_model("Engineer 3"), [bad, good], mem)
    changed = DC.Posting(bad.job_id, bad.title, SG + " Python")
    out, st = _decide(_Model(), [changed], mem)
    assert st.judged == 1 and st.undecidable == 0


def test_transport_errors_do_not_count_against_a_posting():
    mem = _Memory()
    model = _Model(lambda n, ids: "down")
    out, st = _decide(model, [_p(1), _p(2)], mem)
    assert st.undecided == 2 and mem.fails == {} and st.parse_failures == 0
    assert len(model.calls) == 1 and st.errors


def test_one_failing_posting_does_not_stop_the_rest_of_a_batch():
    bad = _p(2)

    def behave(n, ids):
        # p2 of the full batch is the poison; any call containing it garbles.
        return "garbage" if "Engineer 2" in model.calls[-1]["user"] else ids
    model = _Model(behave)
    mem = _Memory()
    out, st = _decide(model, [_p(1), bad, _p(3), _p(4)], mem)
    assert sorted(d.job_id for d in out) == sorted(p.job_id for p in (_p(1), _p(3), _p(4)))
    assert mem.fails == {(bad.job_id, DC.vital_hash(bad.vital_text)): 1}


# ---- the deadline

class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_deadline_stops_new_batches_and_leaves_the_rest_undecided():
    clock = _Clock()

    def behave(n, ids):
        clock.t += 100                                    # every call takes 100 s
        return ids
    model = _Model(behave)
    mem = _Memory()
    posts = [_p(i) for i in range(1, 7)]
    out, st = _decide(model, posts, mem, batch_size=2, deadline=250.0, clock=clock)
    assert len(model.calls) == 3 and st.judged == 6       # 0, 100, 200 < 250: three calls
    # A call may not outlive the deadline: its timeout is what is left of it.
    assert [c["timeout"] for c in model.calls] == [250.0, 150.0, 50.0]
    clock.t = 0.0
    model2 = _Model(behave)
    out, st = _decide(model2, [_p(i) for i in range(11, 17)], batch_size=2,
                      deadline=150.0, clock=clock)
    assert len(model2.calls) == 2 and st.judged == 4
    assert st.deadline_hit and st.skipped_by_deadline == 2 and st.undecided == 2
    assert mem.fails == {}                                # waiting is not failing


def test_no_deadline_means_no_limit():
    model = _Model()
    _, st = _decide(model, [_p(i) for i in range(1, 6)], batch_size=1,
                    deadline=None, clock=lambda: 1e9)
    assert st.judged == 5 and not st.deadline_hit


# ---- the guard on location evidence

ALLOW = ("singapore", "sg")


def test_guard_accepts_only_when_the_location_line_names_an_allowed_place():
    ok = DC.guard("accept", True, 1, "r", 3, vital_text=SG, allowed=ALLOW)
    assert ok[0] == "accept"
    for vital in ("LOCATION: Remote | UNSTATED\nEXPERIENCE: UNSTATED",
                  "LOCATION: UNSTATED | UNSTATED\nEXPERIENCE: UNSTATED",
                  "LOCATION: APAC | We hire across APAC\nEXPERIENCE: UNSTATED",
                  "LOCATION: Kuala Lumpur | UNSTATED\nEXPERIENCE: Singapore clients"):
        got = DC.guard("accept", True, 1, "r", 3, vital_text=vital, allowed=ALLOW)
        assert got[0] == "reject" and got[2] is True, vital
        assert got[1] == DC.REJECT_LOCATION_EVIDENCE


def test_guard_reads_the_body_part_of_the_location_line_too():
    vital = "LOCATION: Multiple | Join our Singapore office\nEXPERIENCE: UNSTATED"
    assert DC.guard("accept", True, 1, "r", 3, vital_text=vital, allowed=ALLOW)[0] == "accept"


def test_guard_matches_whole_words_only_and_ignores_case():
    mk = lambda loc: f"LOCATION: {loc} | UNSTATED\nEXPERIENCE: UNSTATED"
    assert DC.guard("accept", True, 1, "", 3, vital_text=mk("SG"), allowed=ALLOW)[0] == "accept"
    assert DC.guard("accept", True, 1, "", 3, vital_text=mk("SINGAPORE"),
                    allowed=ALLOW)[0] == "accept"
    for no in ("Sgt. Pepper Rd", "Singaporean Airlines HQ in Doha", "Messaging"):
        assert DC.guard("accept", True, 1, "", 3, vital_text=mk(no),
                        allowed=ALLOW)[0] == "reject", no


def test_guard_keeps_the_existing_rules_and_is_off_without_a_list():
    assert DC.guard("accept", None, 1, "", 3, vital_text=SG, allowed=ALLOW)[1] == DC.REJECT_LOCATION
    assert DC.guard("accept", True, 9, "", 3, vital_text=SG, allowed=ALLOW)[0] == "reject"
    assert DC.guard("reject", True, 0, "", 3, vital_text=SG, allowed=ALLOW)[0] == "reject"
    # Nothing to check against (rule absent, or an old caller): as before.
    assert DC.guard("accept", True, 1, "", 3)[0] == "accept"
    assert DC.guard("accept", True, 1, "", 3, vital_text="LOCATION: Paris", allowed=())[0] == "accept"


def test_decide_downgrades_an_accept_the_extract_does_not_support():
    """The model says Singapore for a posting whose location line does not."""
    model = _Model()
    vague = _p(1, "LOCATION: Remote | UNSTATED\nEXPERIENCE: UNSTATED")
    named = _p(2)
    out, st = _decide(model, [vague, named], allowed_locations=ALLOW)
    got = {d.job_id: d.decision for d in out}
    assert got == {vague.job_id: "reject", named.job_id: "accept"}
    assert st.rejected_by_postcondition == 1 and st.accepted == 1


def test_no_deadline_sends_no_timeout():
    model = _Model()
    _decide(model, [_p(1)])
    assert model.calls[0]["timeout"] is None


def test_the_backend_caps_a_call_at_the_time_left():
    seen = []
    inner = _server(show=["thinking"])

    def handler(request):
        if request.url.path == "/api/chat":
            seen.append(request.extensions["timeout"])
        return inner(request)
    b = _backend(handler)
    b.timeout = 600.0
    b.complete("S", "U", timeout=42.0)
    b.complete("S", "U")
    assert seen[0]["read"] == 42.0 and seen[1]["read"] == 600.0


def test_a_truncated_ollama_answer_reports_done_reason():
    comp = _backend(_server(show=["thinking"],
                            chat_extra={"done_reason": "length"})).complete("S", "U")
    assert comp.done_reason == "length"


# ---- location evidence in the cases that matter

def test_location_evidence_cases():
    mk = lambda field, body="UNSTATED": f"LOCATION: {field} | {body}\nEXPERIENCE: UNSTATED"
    cases = {"Singapore (Hybrid)": True, "SG": True, "Remote - Singapore": True,
             "Central Region (City Area)": True, "Remote (US)": False}
    for field, expect in cases.items():
        assert DC.location_names(mk(field), ALLOW) is expect, field
    # "Central Region" only counts as the FIELD; a body mention is not evidence.
    assert not DC.location_names(mk("Multiple", "Central Region of Poland"), ALLOW)


def test_an_evidence_reject_is_stored_but_retried_once_the_list_can_accept_it():
    vague = _p(1, "LOCATION: Tokyo | UNSTATED\nEXPERIENCE: UNSTATED")
    mem = _Memory()
    model = _Model()
    out, st = _decide(model, [vague], mem, allowed_locations=ALLOW)
    assert out[0].decision == "reject" and out[0].reason == DC.REJECT_LOCATION_EVIDENCE
    out, st = _decide(model, [vague], mem, allowed_locations=ALLOW)
    assert st.cached == 1 and len(model.calls) == 1        # same evidence: still cached
    out, st = _decide(model, [vague], mem, allowed_locations=ALLOW + ("tokyo",))
    assert st.judged == 1 and out[0].decision == "accept"   # the list grew: judged again
