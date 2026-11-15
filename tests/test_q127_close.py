"""Q-127 Release 1 closing pins (D-215). Two gaps the earlier Q-127 files leave:

H3 END TO END (design review H3): a model-answered declaration, work-rights question and consent box
under the `always` policy are STAMPED with a protected `field_class` by the real filler
(`always.fill_page_always`), stored by the real `apply_flow.audit_row` + `Store.add_answers`, and the
real "remember" route then REFUSES each one (422 `follows_your_details`, nothing written), while an
ordinary model answer is accepted. `test_q127_web` pins the route over hand-written class strings and
`test_always_a1_final_r5::test_ruling5_*` pins the stamp; this file chains stamp -> store -> route, so a
break in any link (a class not stamped, not stored, or not read back) turns it red.

COVER LETTER, compose OFF (Settings -> Apply "Write cover letters": Off + Stop when unsure the
application stops, Off + Always answer a required one is still written): the flow with a required
cover-letter field and `compose.enabled: false`. strict -> the attempt ends `unanswerable_required`
and the tailor is never called; always -> it is composed (the tailor gets policy "always", enabled
False, required True) and the page fills. (`test_apply_flow_compose` pins the strict half with the
policy unset; the always half had no pin.)

Fakes only: a scripted model, a fake browser, a temp DB and a temp COPY of the sample applicant file;
no network, no process, nothing from data/. Made-up names only ("Example Co", "Example Employer").
Verify: python tests/run_tests.py -k q127_close
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import always_flow_support as S  # noqa: E402
from always_a1_support import FakeAsk, is_stop, lie, page as always_page, pick_by, _pf  # noqa: E402
from always_flow_support import Net, backend, make, nav_class, run_batch  # noqa: E402
from test_q127_web import R, _answers, _by_label, _etag, _file, _remember, _world  # noqa: E402

from jobscraper import apply_flow  # noqa: E402
from jobscraper.apply import contracts as C  # noqa: E402
from jobscraper.apply.contracts import AttemptState as ST, ReasonCode as RC  # noqa: E402
from jobscraper.config import ComposeConfig  # noqa: E402

PROTECTED_LABELS = {
    "decl": ("Have you ever been convicted of a criminal offence?", "declaration"),
    "wr": ("Are you legally authorised to work in Singapore?", "work_right"),
    "box": ("I agree to the privacy policy", "consent_privacy"),
}
ORDINARY_LABEL = "Do you enjoy working in a team environment?"


def _stamped_rows():
    """Run one `always` page (fake model, sample profile) and turn each Answer into the audit row the flow
    would store, as a Q-127 web-test row. Returns (rows, {key: stored class})."""
    fields = [_pf("decl", PROTECTED_LABELS["decl"][0], "RADIO", options=("Yes", "No")),
              _pf("wr", PROTECTED_LABELS["wr"][0], "RADIO", options=("Yes", "No")),
              _pf("box", PROTECTED_LABELS["box"][0], "CHECKBOX", required=False),
              _pf("ord", ORDINARY_LABEL, "RADIO", options=("Yes", "No"))]
    ask = FakeAsk(lambda v: {"decl": lie("No"), "wr": lie("Yes"), "box": lie("true"),
                             "ord": lie("Yes", "ordinary")}.get(v["id"]), pick=pick_by("", ""))
    got = always_page(fields, ask)
    assert not is_stop(got), got
    rows, classes = [], {}
    for pf in fields:
        k = pf.field.key
        row = apply_flow.audit_row("s1", pf.field, got[k])
        classes[k] = row["field_class"]
        ftype = row["field_type"] if k != "ord" else "dropdown"
        rows.append(R(k, pf.field.label, ftype=ftype, options=("Yes", "No") if k != "box" else (),
                      source="assumption", status=row["status"],   # a model-answered row: the CLASS alone must protect it assumed=bool(row["assumed"]),
                      field_class=row["field_class"] or "", value=row["value_json"],
                      qkind="yes_no" if k == "ord" else "text", capture=(f"model_key_{k}", "model")))
    return rows, classes


def test_q127_close_the_filler_stamps_a_protected_class_on_what_it_stores():
    _rows, classes = _stamped_rows()
    for key, (_label, head) in PROTECTED_LABELS.items():
        assert classes[key].split(":")[0] == head, (key, classes[key])
        assert C.follows_your_details("assumption", classes[key]), (key, classes[key])
    assert classes["ord"] == "ordinary", classes
    assert not C.follows_your_details("assumption", classes["ord"])


def test_q127_close_h3_end_to_end_each_stamped_protected_answer_is_refused_by_the_remember_route():
    rows, _classes = _stamped_rows()
    with _world(rows) as (client, cfg, ids):
        got = _by_label(_answers(client, ids))
        for key, (label, _head) in PROTECTED_LABELS.items():
            f = got[label]
            assert f["can_remember"] is False and f["refusal"] == "follows_your_details", (key, f)
        before_file = _file(cfg)
        etag = _etag(client)
        for key in PROTECTED_LABELS:
            resp = _remember(client, ids, key, etag=etag, value="Yes", only_employer=True)
            assert resp.status_code == 422 and "follows_your_details" in resp.text, (key, resp.status_code, resp.text)
        assert _file(cfg) == before_file, "a refused remember writes nothing to the applicant file"


def test_q127_close_h3_end_to_end_an_ordinary_model_answer_is_accepted():
    rows, _classes = _stamped_rows()
    with _world(rows) as (client, cfg, ids):
        f = _by_label(_answers(client, ids))[ORDINARY_LABEL]
        assert f["can_remember"] is True and not f["refusal"], f
        resp = _remember(client, ids, "ord", value=True, only_employer=True)
        assert resp.status_code == 200, (resp.status_code, resp.text)
        assert _file(cfg) != b"", "the correction was saved"


# ---- the cover letter with compose OFF, per fill policy -------------------------------------------------

COMPOSED = "I am drawn to Example Co because I enjoy building small tested tools."


def _cover_run(policy):
    """One required `Cover letter` field, compose off, the tailor faked. Returns (result, tailor calls)."""
    U = S._u()
    w, _cid, jobs = make(1)
    try:
        calls = []

        def script(nav, services, ctx, rctx):
            f = U.pf("cover", "Cover letter", required=True)
            if ctx.composed:
                text = next(iter(ctx.composed.values()))
                a = U.ans("cover", text)
                return U.outcome("one", [f], {"cover": a})
            return U.outcome("one", [f], {"cover": U.ans("cover", None, status=S.AnswerStatus.UNKNOWN,
                                                          note="compose needed")},
                             compose_needed=("cover",))

        def fake_compose(*a, **kw):
            calls.append(kw)
            return SimpleNamespace(ok=True, error="", text=COMPOSED, model="fake-model:1b", prompt_hash="h" * 16)
        real = apply_flow.tailor_flow.compose
        apply_flow.tailor_flow.compose = fake_compose
        try:
            res, _f, say = run_batch(w, jobs, nav_class()(), backend(Net()), script, fill_policy=policy,
                                     compose=ComposeConfig(enabled=False))
        finally:
            apply_flow.tailor_flow.compose = real
        return res[0], calls, say
    finally:
        w.close()


def test_q127_close_compose_off_strict_stops_unanswerable_required_and_never_calls_the_tailor():
    r, calls, _say = _cover_run("strict")
    assert r.state is ST.FAILED and r.reason is RC.UNANSWERABLE_REQUIRED, (r.state, r.reason, r.reason_detail)
    assert r.reason_detail == "Cover letter", r.reason_detail
    assert calls == [], "composing is off under strict: the tailor is not asked"


def test_q127_close_compose_off_always_composes_a_required_cover_letter():
    r, calls, _say = _cover_run("always")
    assert r.state is ST.READY_TO_SUBMIT, (r.state, r.reason, r.reason_detail)
    assert len(calls) == 1, calls
    assert calls[0].get("policy") == "always" and calls[0].get("enabled") is False and calls[0].get("required") is True, calls[0]
