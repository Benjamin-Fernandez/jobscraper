"""Q-74 design section 4: the llm_fill hooks (pins a-d), and the D-109 split.

(a) flag on + local backend: a private value is in the llm_fill prompt (`facts_text(show_private=)`);
(b) no dump, log, cache row or audit note holds an S value; `pick_option` keeps its full redaction;
(c) a text value holding a protected term that the resume, JD and facts do not hold gives unknown
    (guards `_model_field`), and a quote holding one is rejected (`_grounded`);
(d) flipping the flag changes `inputs_hash` (the fill-cache key).
Every case also runs with the flag off, where behaviour must be unchanged.

Synthetic values (`zzz...`); scripted fake backends; no network, no Ollama. The browser case is skipped
cleanly when headless Edge is missing, like the other pagefill oracles.
"""
from __future__ import annotations

import dataclasses
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_fill_t2 as T  # noqa: E402
import test_q74_model_sees_sensitive as base  # noqa: E402
from llm_fill_support import FIX, FakeFillBackend  # noqa: E402
from questions_support import StubBackend  # noqa: E402

from jobscraper import applicant  # noqa: E402
from jobscraper.apply import facts as F, guards as G, llm_fill as L, locks  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    AnswerStatus, FieldType as FT, FillSource, ModelDecision,
)

class KwStub(StubBackend):
    """StubBackend that also takes the `timeout` keyword llm_fill passes."""

    def complete(self, system, user, max_tokens=4096, *, timeout=None, **kw):
        return super().complete(system, user, max_tokens, **kw)


PROTECTED = (base.RACE, base.FAITH, base.RESIDENCY, base.GENDER, base.DOB)


def _ctx(on: bool, **kw):
    return dataclasses.replace(T.rctx(base.s_profile(), **kw), model_sees_sensitive=on)


def _facts(ctx):
    return F.fact_catalogue(ctx.profile, ctx, today=T.TODAY)


def _prompt(ctx, label="Describe a project you are proud of"):
    """The llm_fill user prompt as pagefill builds it: nothing is redacted when the flag is on
    (`run.sv_prompt` is []), the full S list when it is off."""
    pf = T.pf("k", label, FT.TEXTAREA, required=True)
    sv = [] if ctx.model_sees_sensitive else F.s_values(ctx.profile, ctx.account_email)
    return L.user_prompt(L.Chunk("one:k", None, (pf,)), _facts(ctx), ctx, step_title="Step", s_values=sv, cfg={})


def _decide(ctx, value, evidence, source=FillSource.RESUME):
    fields = [T.pf("k", "Describe a project you are proud of", FT.TEXTAREA, required=True)]
    rules = T.rules()
    lk = locks.lock_page(fields, ctx, rules, today=T.TODAY, uploaded={})
    d = [ModelDecision(field_key="k", source=source, value=value, evidence=evidence)]
    out = G.decide(fields, lk, d, _facts(ctx), ctx, matches={}, second=lambda pf: None, today=T.TODAY, rules=rules)
    return out.answers["k"], out


# ------------------------------------------------------------------ (a) the prompt

def test_hook_a_flag_on_the_llm_fill_prompt_shows_private_values():
    up = _prompt(_ctx(True))
    for m in (base.DOB, base.GENDER, base.RACE, base.FAITH, base.RESIDENCY):
        assert m in up, m
    assert f"| private: {base.DOB}" in up, "facts_text prints `private: <value>`"


def test_hook_a_flag_off_the_prompt_is_unchanged_and_shows_none():
    ctx = _ctx(False)
    up = _prompt(ctx)
    base.assert_no_s(up, "llm_fill prompt with the flag off")
    assert "| private, set" in up
    assert F.facts_text(_facts(ctx)) == F.facts_text(_facts(ctx), show_private=False)


def test_hook_a_the_catalogue_value_is_filled_only_with_the_flag_and_the_ref_stays_private():
    on = {f.ref: f for f in _facts(_ctx(True))}
    off = {f.ref: f for f in _facts(_ctx(False))}
    assert on["profile:identity.date_of_birth"].value == base.DOB and on["profile:identity.date_of_birth"].private
    assert off["profile:identity.date_of_birth"].value == "" and off["profile:identity.date_of_birth"].private
    assert on.keys() == off.keys()


def _sensitive_extra_profile(value="zzzextra"):
    """A profile with one VALID sensitive text `extra` entry (labels + kind, so tier 3 and FACTS take it)."""
    p = base.s_profile()
    p["extra"] = {"pet": {"labels": ["Favourite plant"], "kind": "text", "title": "Plant",
                          "value": value, "sensitive": True}}
    return p


def test_hook_a_d201_a_sensitive_extra_answer_is_in_facts_with_the_flag_on_and_nowhere_with_it_off():
    """D-201 (b), the flipped pin: the old entry (`label`, no `kind`) was invalid and dropped, so it passed
    empty. This one is accepted by `facts._extra_usable` (asserted), so the pin cannot pass vacuously."""
    p = _sensitive_extra_profile()
    on = dataclasses.replace(T.rctx(p), model_sees_sensitive=True)
    off = dataclasses.replace(T.rctx(p), model_sees_sensitive=False)
    assert not applicant.extra_entry_errors("pet", p["extra"]["pet"]), "precondition: a valid entry"
    assert F._extra_usable("pet", p["extra"]["pet"], on, F.other_employers(on)) is not None, "precondition"
    fact = {f.ref: f for f in _facts(on)}["extra:pet"]
    assert fact.private and fact.value == "zzzextra", "private stays True, the value is shown"
    assert "extra:pet | Plant | private: zzzextra" in F.facts_text(_facts(on), show_private=True)
    assert "private: zzzextra" in _prompt(on)
    ref_off = {f.ref: f for f in _facts(off)}["extra:pet"]
    assert ref_off.private and ref_off.value == "" and ref_off.is_set, "flag off: the fact is there, no value"
    assert "zzzextra" not in _prompt(off), "flag off: the value is nowhere in the prompt"


def test_hook_a_show_private_without_a_value_keeps_the_set_marker():
    f = F.Fact if hasattr(F, "Fact") else None
    on = F.facts_text(_facts(_ctx(True)), show_private=True)
    assert "profile:identity.pronouns | Pronouns | private, empty" in on, "an unset private fact has nothing to show"


# ------------------------------------------------------------------ (b) no S value in a dump, log, cache row or note

def test_hook_b_pick_option_keeps_the_full_redaction_whatever_the_flag():
    ctx = _ctx(True)
    sv = F.s_values(ctx.profile, ctx.account_email)
    pf = T.pf("k", "Which group applies?", FT.DROPDOWN, options=[f"Alpha {base.PHONE}", "Beta"])
    be = KwStub([{"choice": "Beta"}])
    L.pick_option(be, pf, "Group Q", [f"Alpha {base.PHONE}", "Beta"], s_values=sv, cfg={})
    assert be.calls, "the pick ran"
    base.assert_no_s(be.calls[0]["user"], "the pick prompt", (base.PHONE,))


def test_hook_b_rejected_answers_carry_no_s_value_in_note_or_value():
    ctx = _ctx(True)
    a, out = _decide(ctx, f"I am a {base.RESIDENCY} who loves APIs", "Built REST APIs")
    assert a.status is AnswerStatus.UNGROUNDED and a.value is None
    base.assert_no_s(a.note + " " + str(a.value) + " " + str(out.unknown_required), "the guard result", PROTECTED)
    resume = ctx.resume_text + f"\nReligion: {base.FAITH}\n"
    a2, _ = _decide(_ctx(True, resume_text=resume), "I volunteer weekly", f"Religion: {base.FAITH}")
    base.assert_no_s(a2.note + str(a2.value), "the quote-guard result", PROTECTED)


def test_hook_b_a_flag_on_page_fill_sends_private_values_to_the_model_and_stores_none():
    """fill_page end to end on a recorded page (skipped when headless Edge is missing): the model
    prompt holds the private value, the cache rows, the log lines and the audit notes do not."""
    import test_apply_pagefill as TP
    from jobscraper.apply.pagefill import fill_page
    dob = base.DOB

    def run(on):
        with TP._open("wd_b/02-my_information/page.html") as pg:
            if pg is None:
                return None
            fb = FakeFillBackend.from_file(FIX / "wd_b/02-my_information/reply.json")
            with tempfile.TemporaryDirectory() as tmp:
                ctx, rctx = TP._world(Path(tmp))
                rctx.profile["identity"]["date_of_birth"] = dob
                rctx = dataclasses.replace(rctx, model_sees_sensitive=on)
                hashes = []

                class Svc(TP.FakeServices):
                    def cache_get(self, job_id, sigs, prompt_version, model, inputs_hash):
                        hashes.append(inputs_hash)
                        return {}
                sv = Svc(fb, pg)
                pg.evaluate(TP.INPUTS)
                out = fill_page(pg, TP.FakeNav("my_information"), ctx, rctx, sv)
                return fb, sv, out, hashes

    off, on = run(False), run(True)
    if off is None or on is None:
        return
    fb_off, sv_off, _o, h_off = off
    fb_on, sv_on, out_on, h_on = on
    assert dob not in "\n".join(c.user for c in fb_off.calls), "flag off: unchanged, no private value"
    assert dob in "\n".join(c.user for c in fb_on.calls), "flag on: the local model reads it"
    assert h_off and h_on and h_off != h_on, "hook 9: the flag is part of the cache key"
    for sv, out in ((sv_off, None), (sv_on, out_on)):
        assert dob not in "\n".join(sv.lines), "the log"
        assert dob not in repr(sv.puts), "the cache rows"
    for a in out_on.answers.values() if hasattr(out_on, "answers") else ():
        assert dob not in str(a.note), "the audit note"


# ------------------------------------------------------------------ (c) guards

def test_hook_c_value_with_a_protected_term_not_in_resume_jd_or_facts_gives_unknown():
    a, out = _decide(_ctx(True), f"I am a {base.RESIDENCY} who loves APIs", "Built REST APIs")
    assert a.status is AnswerStatus.UNGROUNDED and a.value is None and "k" in out.unknown_required
    assert "private value" in a.note


def test_hook_c_the_same_value_fills_with_the_flag_off():
    a, out = _decide(_ctx(False), f"I am a {base.RESIDENCY} who loves APIs", "Built REST APIs")
    assert a.status is AnswerStatus.FILLED and "k" not in out.unknown_required, "behaviour unchanged"


def test_hook_c_a_clean_value_fills_with_the_flag_on():
    a, out = _decide(_ctx(True), "I love building APIs", "Built REST APIs")
    assert a.status is AnswerStatus.FILLED and a.value == "I love building APIs" and not out.unknown_required


def test_hook_c_a_protected_term_the_resume_also_holds_does_not_block_the_value():
    ctx = _ctx(True, resume_text=T.rctx().resume_text + f"\nVolunteer, {base.FAITH} community centre\n")
    a, _ = _decide(ctx, f"I volunteer at the {base.FAITH} community centre", "Built REST APIs")
    assert a.status is AnswerStatus.FILLED, (a.status, a.note)


def test_hook_c_a_quote_holding_a_protected_term_is_rejected():
    ctx = _ctx(True, resume_text=T.rctx().resume_text + f"\nReligion: {base.FAITH}\n")
    a, out = _decide(ctx, "I volunteer weekly", f"Religion: {base.FAITH}")
    assert a.status is not AnswerStatus.FILLED and a.value is None and "k" in out.unknown_required, (a.status, a.note)
    assert "G3" in a.note and "private" in a.note


def test_hook_c_the_same_quote_is_accepted_with_the_flag_off():
    ctx = _ctx(False, resume_text=T.rctx().resume_text + f"\nReligion: {base.FAITH}\n")
    a, _ = _decide(ctx, "I volunteer weekly", f"Religion: {base.FAITH}")
    assert a.status is AnswerStatus.FILLED, (a.status, a.note)


def test_hook_c_a_quote_the_posting_also_holds_is_not_blocked():
    jd = T.rctx().jd_text + f"\nWe welcome the {base.FAITH} community.\n"
    ctx = _ctx(True, jd_text=jd, resume_text=T.rctx().resume_text + f"\nReligion: {base.FAITH}\n")
    a, _ = _decide(ctx, "I volunteer weekly", f"Religion: {base.FAITH}")
    assert a.status is AnswerStatus.FILLED, (a.status, a.note)


def test_hook_d201_account_email_is_shown_with_the_flag_on_and_the_cache_key_moves_off_the_d105_marker():
    """D-201 (b)/(f3): `standing:account_email` prints `private: <value>` with the flag on, none with it off;
    the flag-on `inputs_hash` differs from the flag-off one and from the D-105 marker's hash."""
    on, off = _ctx(True), _ctx(False)
    assert on.account_email
    line = f"standing:account_email | Email address of this application | private: {on.account_email}"
    assert line in F.facts_text(_facts(on), show_private=True)
    assert on.account_email in _prompt(on) and on.account_email not in _prompt(off)
    assert {f.ref: f for f in _facts(on)}["standing:account_email"].private is True
    h_on, h_off = F.inputs_hash("resume", "jd", sees_private=True), F.inputs_hash("resume", "jd", sees_private=False)
    d105 = F._sha16("resume" + "\n\x1e\n" + "jd" + "\n\x1e\x1dprivate-visible")      # the D-105 recipe, old marker
    assert h_on != h_off and h_on != d105, "a flag-on fill cached under D-105 re-runs once"


# ------------------------------------------------------------------ (d) the cache key

def test_hook_d_flipping_the_flag_changes_inputs_hash_and_off_is_the_old_hash():
    old = F.inputs_hash("resume", "jd")
    assert F.inputs_hash("resume", "jd", sees_private=False) == old, "flag off: the old key, byte for byte"
    assert F.inputs_hash("resume", "jd", sees_private=True) != old
    assert F.inputs_hash("resume", "jd", sees_private=True) == F.inputs_hash("resume", "jd", sees_private=True)
    assert F.inputs_hash("resume2", "jd", sees_private=True) != F.inputs_hash("resume", "jd", sees_private=True)


# ------------------------------------------------------------------ D-201 pins: F1 redaction, F2 tier-5 salary, G7

DISTINCT = ("Zyxquill", "Vandermoot", "Quillo", "xe/xem", "Plumbago-7731")     # string leaves newly readable
SALARY = "987654"                                                                 # a number: not redacted by design
WHY = "Describe a project you are proud of"


def _d201_profile() -> dict:
    """Dummy applicant with every newly readable leaf set to a distinctive value (nothing real)."""
    from apply_flow_support import sample_profile
    p = sample_profile()
    p["identity"].update(legal_first_name="Zyxquill", legal_last_name="Vandermoot", preferred_name="Quillo",
                         pronouns="xe/xem", name_order="surname_first")
    p["pay"]["current_salary"] = {"amount": int(SALARY), "currency": "SGD", "period": "annual"}
    p["pay"]["months_per_year"] = 14
    p["consents"] = dict(privacy_consent=True, data_retention_consent=True, talent_pool_opt_in=True,
                         certify_true=True)
    p["extra"] = {"plant": {"labels": ["Favourite plant"], "kind": "text", "title": "Plant",
                            "value": "Plumbago-7731", "sensitive": True}}
    return p


def test_d201_f1_no_newly_readable_value_reaches_the_job_log_or_the_audit_rows():
    """F1 (review): flag effective, one llm_fill page through the N6a harness (`fill_page` is a script that
    runs the real `llm_fill.ask` + `guards.decide`; local fake backend). The model reads every value, so the
    prompt holds them (the precondition); the job log and the audit rows (note, source, hashes ...) hold none.
    `debug_dump` is a config key only: nothing in src/ writes a dump, so there is no dump to assert on.
    A deliberate log line naming the string values stands in for any leak: `_Log` must scrub it."""
    import test_apply_flow_n6a as N
    import test_q79_body_llm_sees_sensitive as Q79
    from jobscraper import apply_flow
    reply = {"kind": "page", "repeat": True, "reply": {f"|{WHY}": {
        "source": "resume", "ref": "", "value": "I built Zyxquill Vandermoot's Plumbago-7731 tool",
        "evidence": "Zyxquill Vandermoot Quillo xe/xem Plumbago-7731 " + SALARY}}}
    inner = FakeFillBackend(replies=[reply])
    seen = {}

    def fake(page, nav_, ctx, rctx, services):
        step = nav_.step_id(page, ctx)
        if step == "review":
            return N.outcome(step, [])
        seen["flag"] = rctx.model_sees_sensitive
        pfs = [T.pf("k", WHY, FT.TEXTAREA, required=True)]
        facts = F.fact_catalogue(rctx.profile, rctx, today=T.TODAY)
        stats = L.CallLog()
        decisions = L.ask(services.backend, L.Chunk("one:k", None, tuple(pfs)), facts, rctx, step_title="Step",
                          s_values=[], cfg=services.cfg, stats=stats)
        rules = T.rules()
        lk = locks.lock_page(pfs, rctx, rules, today=T.TODAY, uploaded={})
        out = G.decide(pfs, lk, decisions, facts, rctx, matches={}, second=lambda pf: None, today=T.TODAY,
                       rules=rules, model=services.model, prompt_hashes=stats.prompt_hashes)
        services.log("stand-in leak: " + " ".join(DISTINCT))
        return N.outcome(step, pfs, answers=out.answers)

    w, jid = N.world(profile=_d201_profile())
    saved, apply_flow.fill_page = apply_flow.fill_page, fake
    try:
        r, _f, say, _m = N.run(w, jid, N.FakeNav(("one", "review")), Q79.LocalFill(inner=inner),
                               apply_over={"model_sees_sensitive": True})
        rows = w.store.answers(r.attempt_id)
    finally:
        apply_flow.fill_page = saved
        w.close()
    assert seen.get("flag") is True and inner.calls, "precondition: the flag is effective and the model ran"
    prompt = Q79.user_text(inner)
    for m in DISTINCT + (SALARY,):
        assert m in prompt, f"precondition: the model reads {m!r}"
    assert rows, "the audit rows exist"
    haystack = {"log": say.text, "result": str(r.reason_detail or "")}
    for i, x in enumerate(rows):
        for k, v in x.items():
            if k not in ("value_json", "corrected_json"):       # the filled value itself may name the applicant
                haystack[f"audit row {i} column {k}"] = str(v)
    leaks = [f"{what} holds {m[:3]!r}..." for what, text in haystack.items() for m in DISTINCT + (SALARY,)
             if m in text]                       # never print a whole value
    assert not leaks, leaks
    assert "[redacted]" in say.text, "the stand-in leak line was scrubbed, not dropped"


def test_d201_f2_tier5_salary_text_is_never_filled_from_the_current_salary():
    """F2 (review): flag on, the model can now read `pay.current_salary`. "Expected salary" is the program's
    (tier 2, `pay.expected_salary`); a free-text compensation question that reaches tier 5 ends ungrounded
    even when the model returns exactly the current amount. Distinct amounts for expected and current."""
    from questions_support import field
    p = base.s_profile()
    p["pay"]["expected_salary"] = {"amount": 41234, "currency": "SGD", "period": "monthly", "negotiable": True}
    p["pay"]["current_salary"] = {"amount": 38765, "currency": "SGD", "period": "monthly"}
    reply = [{"text": "38765"}] * 2
    a, be, _ = base.resolve_one(field("a", "What is your expected salary?", FT.TEXT), on=True, replies=reply, p=p)
    assert a.status is AnswerStatus.FILLED and a.source == "profile:pay.expected_salary"
    assert "41234" in str(a.value) and "38765" not in str(a.value) and not be.calls
    f5 = field("b", "Tell us about your compensation", FT.TEXTAREA)
    a, be, _ = base.resolve_one(f5, on=True, replies=reply, p=p)
    assert be.calls and "38765" in be.calls[0]["user"], "precondition: tier 5 reaches the model, which now reads it"
    assert a.tier.name == "LLM" and a.status is AnswerStatus.UNGROUNDED and a.value is None, (a.status, a.note)
    a, be, _ = base.resolve_one(f5, on=False, replies=reply, p=p)
    assert be.calls and "38765" not in be.calls[0]["user"], "flag off: the model never reads it"


def test_d201_g7_a_private_extra_fact_cited_for_an_s_labelled_field_ends_unknown():
    """G7 with the flag on: the model now sees the sensitive `extra` value, but citing it for a pronouns question is
    still refused (`fact.private and ns == "profile"` is the only private route), so nothing is filled."""
    p = base.s_profile()
    p["extra"] = {"pet": {"labels": ["Favourite plant", "Garden hobby"], "kind": "text", "title": "Pronouns",
                          "value": "Plumbago-7731", "sensitive": True}}
    ctx = dataclasses.replace(T.rctx(p), model_sees_sensitive=True)
    fields = [T.pf("k", "Which pronouns do you use?", FT.TEXT, required=True)]
    rules = T.rules()
    lk = locks.lock_page(fields, ctx, rules, today=T.TODAY, uploaded={})
    d = [ModelDecision(field_key="k", source=FillSource.EXTRA, ref="extra:pet", value="Plumbago-7731")]
    out = G.decide(fields, lk, d, _facts(ctx), ctx, matches={}, second=lambda pf: None, today=T.TODAY, rules=rules)
    a = out.answers["k"]
    assert {f.ref: f for f in _facts(ctx)}["extra:pet"].value == "Plumbago-7731", "precondition: the value is shown"
    assert a.status is AnswerStatus.UNKNOWN and a.note.startswith("G7") and a.value is None, (a.status, a.note)
