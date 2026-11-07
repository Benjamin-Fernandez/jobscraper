"""The real flow + the real Greenhouse adapter + headless Edge, on local fixture pages (WP-B9
Verify `-k apply_e2e`; Q-31). A local http.server stands in for the job board and its API
(JOBSCRAPER_GH_BOARD_BASE / JOBSCRAPER_GH_API_BASE), so nothing leaves 127.0.0.1.

Scenarios: dry run -> ready_to_submit (audit rows + screenshots, nothing submitted); auto ->
submitted exactly once (the page's own submit counter); the three after-submit outcomes
(navigate, security code, server error); a visible challenge -> failed(captcha) before any input;
closed / bot pages; a 404 schema; MyGreenhouse signed in (prefill kept, email and resume ours) and
signed out (dialog closed, nothing typed, full fill).

The old per-adapter path is pinned with `fill="rules"` (edge_acfg; it stays until WP-C1); the LLM
loop (`fill="llm"`, the default) has its own e2e at the end, with a scripted model.

Skips cleanly (one note on stdout) if Edge or Playwright is unavailable. A temp Edge profile, temp
DB, temp evidence dir, synthetic applicant. The model is off: the one question no tier answers is
seeded in the answer memory (tier 3), like a saved answer from the owner.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_flow_support import (  # noqa: E402
    EMAIL, FixtureServer, GH, NoModel, RESUME_BYTES, Say, add_job, edge_acfg, edge_available,
    edge_session_class, local_http, make_world, stored_value,
)

from jobscraper import apply_flow  # noqa: E402
from jobscraper.apply.contracts import AttemptState as S, ReasonCode as R  # noqa: E402

POSTING = "6237419004"
HOWHEARD = "where did you see or hear about this job"
RESUME_SHA = hashlib.sha256(RESUME_BYTES).hexdigest()


class Run:
    """One apply run on the local board: results, the Edge sessions' page snapshots, the log."""

    def __init__(self, w, fx, results, sessions, say):
        self.w, self.fx, self.results, self.sessions, self.say = w, fx, results, sessions, say

    @property
    def r(self):
        return self.results[0]

    @property
    def snap(self) -> dict:
        snaps = [s for sess in self.sessions for s in sess.snapshots]
        assert snaps, "no page was snapshotted"
        return snaps[0]

    def row(self):
        return self.w.store.attempt(self.r.attempt_id)

    def answers(self):
        return self.w.answers_by_key(self.r.attempt_id)

    def evidence(self) -> Path:
        return self.w.tmp / "evidence" / str(self.r.attempt_id)


def run_local(*, page="form.html", query="", dry_run=True, schema_status=200, extra_postings=(),
              backend=None, profile=None, **over):
    """Apply to the Dataiku posting served as `page` (+`?query`). `extra_postings` =
    [(posting_id, page, query)] are applied after it, in the same run."""
    w = make_world(profile=profile)
    w.store.answer_memory_put(HOWHEARD, "dropdown", json.dumps("LinkedIn"))
    cid, jid = add_job(w.store, external_id=POSTING)
    jids = [jid]
    with FixtureServer() as fx:
        fx.set_posting(POSTING, page, query)
        fx.schema_status = schema_status
        for pid, pg, q in extra_postings:
            fx.set_posting(pid, pg, q)
            jids.append(add_job(w.store, external_id=pid, company_id=cid)[1])
        edge_dir = str(w.tmp / "edge-profile")
        cls = edge_session_class()
        sessions = []

        def factory(acfg):
            s = cls(acfg, profile_dir=edge_dir).start()
            sessions.append(s)
            return s
        say = Say()
        acfg = edge_acfg(w.cfg.apply, edge_dir, **over)
        results = apply_flow.run(w.cfg, w.store, jids, dry_run=dry_run, backend=backend or NoModel(),
                                 http=local_http(), browser_factory=factory, apply_cfg=acfg,
                                 say=say, evidence_dir=w.tmp / "evidence")
        assert fx.only_local(), fx.requests
    return Run(w, fx, results, sessions, say)


def _png(path: Path) -> bool:
    return path.is_file() and path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


# ================================================================== dry run

def test_a_dry_run_fills_the_whole_form_and_stops_at_review():
    if not edge_available():
        return
    run = run_local(dry_run=True)
    r = run.r
    assert r.state is S.READY_TO_SUBMIT, (r.state, r.reason, r.reason_detail, run.say.text)
    row = run.row()
    assert (row["state"], row["ats"], row["plan_source"], row["mode"]) == \
        ("ready_to_submit", "greenhouse", "schema", "dry_run")
    assert row["submit_clicked_at"] is None and row["end_url"].endswith(f"/dataiku/jobs/{POSTING}")
    s = run.snap
    assert s["submitCount"] == "0" and s["submitted"] is None, "a dry run never presses Submit"
    assert s["values"]["first_name"] == "Alex" and s["values"]["last_name"] == "Testcase"
    assert s["values"]["email"] == EMAIL and s["values"]["phone"] == "91234567"
    assert s["files"]["resume"] == "resume.pdf"
    assert s["selects"]["question_20424893004"] == "No", "employee at Dataiku: declaration says No"
    assert s["selects"]["question_20424897004"] == "LinkedIn", "tier 3 (answer memory)"
    assert s["selects"]["candidate-location"] == "Singapore, Singapore", "the suggestion that starts with our city"
    assert s["checks"]["gdpr_processing_consent_given_1"] is True
    assert s["checks"]["gdpr_retention_consent_given_1"] is True
    rows = run.answers()
    assert len(rows) >= 20, sorted(rows)
    for key in ("first_name", "last_name", "email", "phone", "resume", "candidate-location",
                "question_20424893004", "question_20424897004", "gdpr_processing_consent_given"):
        assert rows[key]["status"] == "filled", (key, rows[key]["status"])
    assert rows["question_20424897004"]["tier"] == 3 and rows["question_20424893004"]["tier"] == 4
    assert stored_value(rows["resume"]) == {"file": "resume.pdf", "sha256": RESUME_SHA}
    assert not [a for a in rows.values() if a["status"] in ("unknown", "ungrounded", "fill_failed")]
    folder = run.evidence()
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["01-open.png", "02-application.png", "03-review.png"], names
    assert all(_png(folder / n) for n in names)
    assert not (folder / "failed.html").exists()
    assert "ready_to_submit" in run.say.text and EMAIL not in run.say.text


def test_a_dry_run_of_two_postings_shares_one_browser_and_reports_each():
    if not edge_available():
        return
    run = run_local(dry_run=True, extra_postings=[("6237419005", "form_challenge.html", "")])
    a, b = run.results
    assert a.state is S.READY_TO_SUBMIT
    assert b.state is S.FAILED and b.reason is R.CAPTCHA
    assert len(run.sessions) == 1, "one Edge per run, one tab per attempt"
    folder = run.w.tmp / "evidence" / str(b.attempt_id)
    assert (folder / "failed.html").is_file() and any(p.name.endswith("failed.png")
                                                       for p in folder.iterdir())


# ================================================================== auto: the three after-submit outcomes

def test_auto_submits_exactly_once_and_marks_the_application_applied():
    if not edge_available():
        return
    run = run_local(dry_run=False)
    r = run.r
    assert r.state is S.SUBMITTED and r.confirmation == "text", (r.state, r.reason_detail, run.say.text)
    s = run.snap
    assert s["submitCount"] == "1", "the duplicate-submission oracle at page level (NF-06)"
    sent = s["submitted"]
    assert sent["first_name"] == "Alex" and sent["email"] == EMAIL and sent["resume"] == "resume.pdf"
    row = run.row()
    assert row["state"] == "submitted" and row["confirmation"] == "text" and row["submit_clicked_at"]
    jid = r.job_id
    app = run.w.store.application(jid)
    assert app["status"] == "applied" and app["company"] == "Dataiku"
    assert run.w.store.apply_duplicate(jid), "a second apply is now refused"
    names = [p.name for p in run.evidence().iterdir()]
    assert any(n.endswith("-review.png") for n in names) and any(n.endswith("-confirmed.png") for n in names), names


def test_auto_with_a_navigation_to_the_thank_you_page_is_confirmed_by_its_text():
    if not edge_available():
        return
    run = run_local(dry_run=False, query="after=navigate")
    assert run.r.state is S.SUBMITTED and run.r.confirmation == "text", \
        (run.r.state, run.r.reason_detail)
    assert "confirm.html" in run.snap["url"] and run.snap["title"] == "Thank you for applying"


def test_a_security_code_prompt_ends_submitted_unconfirmed_and_is_never_clicked_twice():
    if not edge_available():
        return
    run = run_local(dry_run=False, query="after=code")
    r = run.r
    assert r.state is S.SUBMITTED_UNCONFIRMED, (r.state, r.reason_detail)
    assert "security code needed; mailbox not set up" in r.reason_detail
    assert run.snap["submitCount"] == "0", "the first click only asked for the code; no second click"
    row = run.row()
    assert row["submit_clicked_at"] and row["reason_code"] is None
    assert run.w.store.application(r.job_id) is None


def test_a_server_side_error_after_the_click_is_unconfirmed_not_failed():
    if not edge_available():
        return
    run = run_local(dry_run=False, query="after=errors")
    r = run.r
    assert r.state is S.SUBMITTED_UNCONFIRMED and "errors after submit" in r.reason_detail, \
        (r.state, r.reason_detail)
    assert run.snap["submitCount"] == "0"
    assert run.row()["submit_clicked_at"], "the click was recorded before it happened"


# ================================================================== stop signs

def test_a_visible_challenge_fails_captcha_before_any_input_and_never_submits():
    if not edge_available():
        return
    run = run_local(page="form_challenge.html", dry_run=False)
    r = run.r
    assert r.state is S.FAILED and r.reason is R.CAPTCHA, (r.state, r.reason, r.reason_detail)
    s = run.snap
    assert s["values"]["first_name"] == "" and s["values"]["email"] == "" and s["inputs"] == [], \
        "nothing is typed past a challenge"
    assert s["submitCount"] == "0"
    row = run.row()
    assert row["submit_clicked_at"] is None and row["reason_code"] == "captcha"
    folder = run.evidence()
    assert (folder / "failed.html").is_file() and any(_png(p) for p in folder.iterdir())
    assert "bypass" not in run.say.text.lower()


def test_a_closed_posting_and_a_bot_wall_are_stops_with_their_own_reasons():
    if not edge_available():
        return
    run = run_local(page="closed.html")
    assert run.r.state is S.FAILED and run.r.reason is R.POSTING_CLOSED, (run.r.reason, run.r.reason_detail)
    run = run_local(page="bot_check.html")
    assert run.r.state is S.FAILED and run.r.reason is R.BOT_CHALLENGE, (run.r.reason, run.r.reason_detail)
    assert run.snap["values"] == {} or not any(run.snap["values"].values())


def test_a_404_schema_is_posting_closed_before_edge_even_starts():
    if not edge_available():
        return
    run = run_local(schema_status=404)
    assert run.r.state is S.FAILED and run.r.reason is R.POSTING_CLOSED
    assert run.sessions == [], "the plan comes from the API: no browser for a closed posting"


# ================================================================== MyGreenhouse (D-70)

def test_mygreenhouse_signed_in_keeps_its_values_but_the_email_and_resume_stay_ours():
    if not edge_available():
        return
    run = run_local(page="form_mygreenhouse_signed_in.html", dry_run=True)
    r = run.r
    assert r.state is S.READY_TO_SUBMIT, (r.state, r.reason_detail, run.say.text)
    assert "prefill: mygreenhouse" in run.say.text
    s = run.snap
    assert s["values"]["email"] == EMAIL, "the autofilled email is replaced: the mailbox we watch"
    assert s["values"]["phone"] == "81234567", "a kept site value is not typed over"
    assert s["values"]["question_20424899004"] == "https://www.linkedin.com/in/alex-saved"
    assert s["files"]["resume"] == "resume.pdf", "our resume, never MyGreenhouse's"
    assert not s["dialogOpen"]
    rows = run.answers()
    assert rows["phone"]["status"] == "prefilled" and rows["phone"]["source"] == "mygreenhouse"
    assert rows["phone"]["tier"] == 0 and "differs from profile" in rows["phone"]["note"]
    assert rows["question_20424899004"]["status"] == "prefilled"
    assert rows["first_name"]["status"] == "prefilled" and rows["first_name"]["note"] == ""
    assert rows["email"]["status"] == "filled" and "replaced site value" in rows["email"]["note"]
    assert rows["resume"]["status"] == "filled"
    assert stored_value(rows["resume"])["sha256"] == RESUME_SHA
    assert (run.evidence() / "02-mygreenhouse.png").is_file()


def test_mygreenhouse_signed_out_closes_the_dialog_types_nothing_and_fills_everything():
    if not edge_available():
        return
    run = run_local(page="form_mygreenhouse_signed_out.html", dry_run=True)
    r = run.r
    assert r.state is S.READY_TO_SUBMIT, (r.state, r.reason_detail, run.say.text)
    assert "mygreenhouse: not signed in" in run.say.text and "prefill: mygreenhouse" not in run.say.text
    s = run.snap
    assert not s["dialogOpen"], "the sign-in dialog is closed"
    assert "mygh_email" not in s["inputs"], "no email is ever typed into MyGreenhouse's sign-in"
    assert s["values"]["first_name"] == "Alex" and s["values"]["phone"] == "91234567", \
        "not signed in: the full fill"
    rows = run.answers()
    assert not [a for a in rows.values() if a["status"] == "prefilled"]
    assert rows["first_name"]["status"] == "filled"


def test_with_mygreenhouse_switched_off_the_autofill_button_is_never_pressed():
    if not edge_available():
        return
    run = run_local(page="form_mygreenhouse_signed_in.html", dry_run=True, mygreenhouse=False)
    assert run.r.state is S.READY_TO_SUBMIT, (run.r.reason_detail, run.say.text)
    assert run.snap["values"]["phone"] == "91234567" and "prefill:" not in run.say.text


# ================================================================== fill: llm (WP-N6a)

def _scripted_gh_model():
    """A scripted model for form.html under the LLM loop: every reply cites a fact (the program
    writes the value from the fact), two owner answers sit in `extra:` (saved from the Questions
    inbox in real use). Keys are `group|question`; the section heading is not a group."""
    from llm_fill_support import FakeFillBackend

    def d(source, ref="", value=""):
        return {"source": source, "ref": ref, "value": value, "evidence": ""}
    page = {
        "|First Name": d("profile", "profile:identity.legal_first_name", "Alex"),
        "|Last Name": d("profile", "profile:identity.legal_last_name", "Testcase"),
        "|Phone": d("profile", "profile:contact.phone_number"),
        "|Location (City)": d("profile", "profile:contact.city", "Singapore"),
        "|What are your salary expectations?": d("profile", "profile:pay.expected_salary"),
        "|Are you located in or willing to relocate to this job posting's city?":
            d("extra", "extra:located_or_relocate", "Yes"),
        "|Where did you see or hear about this job?": d("standing", "standing:how_heard"),
        "|I consent to Dataiku keeping my data for 720 days for future roles.":
            d("extra", "extra:retention_consent", "true"),
    }
    return FakeFillBackend(replies=[
        {"kind": "page", "repeat": True, "reply": page},
        {"kind": "pick", "repeat": True, "match": "Location (City)", "raw": {"choice": "Singapore, Singapore"}},
        {"kind": "pick", "repeat": True, "match": "Where did you see", "raw": {"choice": "Dataiku Career Site"}},
        {"kind": "second", "repeat": True, "reply": page},
        {"kind": "corrective", "repeat": True, "reply": page},
    ], strict=False)


def _gh_profile_with_owner_answers():
    from apply_flow_support import sample_profile
    p = sample_profile()
    p["extra"] = {
        "located_or_relocate": {"title": "Located or relocating", "description": "", "kind": "text",
                                "sensitive": False, "value": "Yes",
                                "labels": ["are you located in or willing to relocate to this job posting's city"]},
        "retention_consent": {"title": "Data retention consent", "description": "", "kind": "yes_no",
                              "sensitive": False, "value": True,
                              "labels": ["i consent to dataiku keeping my data for 720 days for future roles"]},
    }
    return p


def test_fill_llm_dry_run_fills_the_greenhouse_form_with_a_scripted_model_and_stops_at_review():
    """The default path (`apply.fill: llm`): the real flow, the real Greenhouse navigator, the real
    page reader and `fill_page` in headless Edge, a scripted model (no Ollama). Dry run -> review:
    every required field filled from its fact, the resume attached, nothing submitted, no S value
    in any prompt (NF-02). Pins DEFECTS D1 (a react-select/combobox choice is a TYPEAHEAD, which
    the deterministic option fits do not accept: Gender stops "no offered option fits") and D2 (the
    hidden resume file input is not read as a field, so no resume is attached)."""
    if not edge_available():
        return
    from llm_fill_support import sample_secrets
    fb = _scripted_gh_model()
    run = run_local(dry_run=True, fill="llm", backend=fb, profile=_gh_profile_with_owner_answers())
    r = run.r
    assert r.state is S.READY_TO_SUBMIT, (r.state, r.reason, r.reason_detail, run.say.text[-1500:].encode("ascii", "replace").decode())
    row = run.row()
    assert (row["state"], row["ats"], row["plan_source"], row["mode"]) ==         ("ready_to_submit", "greenhouse", "page", "dry_run")
    assert row["submit_clicked_at"] is None
    s = run.snap
    assert s["submitCount"] == "0" and s["submitted"] is None, "a dry run never presses Submit"
    assert s["values"]["first_name"] == "Alex" and s["values"]["last_name"] == "Testcase"
    assert s["values"]["email"] == EMAIL and s["values"]["phone"] == "91234567"
    assert s["values"]["question_20424895004"] == "5000", "salary expectation from the profile fact"
    assert s["values"]["question_20424896004"] == "Yes", "the owner's saved answer (extra)"
    assert s["selects"]["candidate-location"] == "Singapore, Singapore"
    assert s["selects"]["question_20424893004"] == "No", "employee at Dataiku: declaration says No"
    assert s["selects"]["question_20424894004"] == "No", "no sponsorship needed"
    assert s["selects"]["question_20424897004"] == "Dataiku Career Site", "the standing how-heard fact"
    assert s["selects"]["4000563004"] == "I don't wish to answer", "D1: gender 'decline' fits the offered option"
    assert s["checks"]["gdpr_processing_consent_given_1"] is True
    assert s["checks"]["gdpr_retention_consent_given_1"] is True
    assert s["files"]["resume"] == "resume.pdf", "D2: the hidden resume input is attached"
    rows = run.answers()
    assert not [a for a in rows.values() if a["status"] in ("unknown", "ungrounded", "fill_failed")]
    # audit key = `<step>:<automation id or html id or slug(label)>` (llm_fill_design §3.1 "Key"): the
    # LLM loop's single Greenhouse page is the step "form"
    for key in ("form:first_name", "form:last_name", "form:email", "form:phone", "form:resume"):
        assert rows[key]["status"] == "filled", (key, sorted(rows))
    assert {c.kind for c in fb.calls} <= {"page", "pick", "second", "corrective"}
    fb.assert_no_secrets(sample_secrets())
    assert run.fx.only_local(), run.fx.requests
    assert EMAIL not in run.say.text

