"""Q-74 pins (KA-2, D-105, ADR-0008, D-107): the model may READ private (S) profile values, never
DECIDE or repeat them.

Spec: docs/architecture/q74_model_sees_sensitive.md section 6 (T1-T8), plus the fix-round pins
F1a-F1d, F2a, F2b, F3 (review docs/reviews/Q-74.md, engineer handoff in comms/outbox/
software-engineer.md). One supersession: section 6 T5 ("grounds when the value is only in the S
facts") is replaced by the F1 rule: with the switch on the grounding corpus holds the CONTACT
details only; a protected S value (race, religion, date of birth, gender, residency, ...) never
grounds a tier-5 answer, and a tier-5 answer that uses one is UNGROUNDED + sensitive.

Every value here is synthetic (the `zzz...` strings are marker values; nothing is a real person).
The model is a scripted fake: no Ollama call, no network, no data/ file, no port.
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_flow_support import Say, fake_world, make_world, registered, page_signals, FakeAdapter, FakeBrowserFactory  # noqa: E402
from questions_support import (  # noqa: E402
    REAL_RULES, StubBackend, ctx_for, field, profile, yes_no,
)

from jobscraper import apply_flow, applicant, backends, cli  # noqa: E402
from jobscraper.apply import questions as Q  # noqa: E402
from jobscraper.apply import resolve as R  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    AnswerStatus, AnswerTier, Canonical, FieldType,
)
from jobscraper.backends import OffBackend, OllamaBackend  # noqa: E402
from jobscraper.config import ApplyConfig, Config  # noqa: E402

# Marker S values. Short enough to read, unique enough that a substring check cannot false-hit.
DOB = "2001-03-12"
RACE, FAITH, RESIDENCY, GENDER = "zzzrace", "zzzfaith", "zzzcitizen", "zzzgender"
PHONE = "91234567"                                    # contact: allowed into the corpus under D-105
S_MARKERS = (RACE, FAITH, RESIDENCY, GENDER, DOB, "2001")
LOCAL = "http://127.0.0.1:11434"


def s_profile() -> dict:
    p = profile()
    p["identity"]["date_of_birth"] = DOB
    p["identity"]["gender"] = GENDER
    p["singapore_status"].update(race=RACE, religion=FAITH, residency_status=RESIDENCY)
    p["contact"]["phone_number"] = PHONE
    return p


def ctx_on(on: bool = True, p: Optional[dict] = None):
    return dataclasses.replace(ctx_for(p or s_profile()), model_sees_sensitive=on)


def resolve_one(f, *, on: bool, replies, p: Optional[dict] = None):
    """The real resolver over config/questions.yaml with a scripted model. (answer, backend, ctx)."""
    be = StubBackend(replies)
    ctx = ctx_on(on, p)
    out = R.resolve_all([f], ctx, backend=be, rules=R.load_rules(REAL_RULES), memory=lambda *_a: None)
    return out[f.key], be, ctx


def assert_no_s(text: str, what: str, markers=S_MARKERS) -> None:
    low = (text or "").lower()
    bad = [m for m in markers if m.lower() in low]
    assert not bad, f"{what} carries S value(s) {bad}: {text!r}"


class LocalFake(OllamaBackend):
    """An OllamaBackend that never touches the network: scripted replies, always available."""

    def __init__(self, url: str = LOCAL, model: str = "qwen3:14b", replies=()):
        super().__init__(url=url, model=model)
        self.replies = list(replies)
        self.calls: list[dict] = []

    @property
    def available(self) -> bool:
        return True

    def describe(self) -> str:
        return "fake local ollama"

    def complete(self, system, user, max_tokens=4096, *, format=None, temperature=None,
                 seed=None, top_k=None, **_kw):
        self.calls.append({"user": user})
        if not self.replies:
            raise backends.BackendError("fake: no reply scripted")
        r = self.replies.pop(0)
        return backends.Completion(text=r if isinstance(r, str) else json.dumps(r))


@contextlib.contextmanager
def env(**kv):
    """Set (or, with None, remove) environment variables for one block."""
    saved = {k: os.environ.get(k) for k in kv}
    try:
        for k, v in kv.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


CLEAN = dict(JOBSCRAPER_OLLAMA_URL=None, JOBSCRAPER_BACKEND=None)

# ================================================================== T1 / F3: is_local


def test_t1_is_local_true_for_this_computer():
    for url in ("http://127.0.0.1:11434", "http://localhost:11434", "http://LOCALHOST:11434",
                "http://[::1]:11434", "https://localhost"):
        assert backends.is_local(OllamaBackend(url=url)) is True, url


def test_t1_is_local_false_for_any_other_host_and_fails_closed():
    for url in ("http://ollama:11434", "http://192.168.1.5:11434", "http://0.0.0.0:11434",
                "http://localhost.evil.com:11434", "http://127.0.0.2:11434", "http://127.1:11434",
                "http://[::ffff:127.0.0.1]:11434", "http://localhost.:11434", "localhost:11434",
                "http://[::1", "", "http://"):
        assert backends.is_local(OllamaBackend(url=url)) is False, url


def test_t1_off_backend_and_foreign_backend_are_not_local():
    assert backends.is_local(OffBackend("disabled")) is False
    assert backends.is_local(StubBackend()) is False


def test_t1_env_override_wins_in_build():
    with env(JOBSCRAPER_BACKEND=None, JOBSCRAPER_OLLAMA_URL="http://ollama:11434"):
        assert backends.is_local(backends.build({})) is False
        assert backends.is_local(backends.build({"ollama_url": LOCAL})) is False
    with env(JOBSCRAPER_BACKEND=None, JOBSCRAPER_OLLAMA_URL=LOCAL):
        assert backends.is_local(backends.build({"ollama_url": "http://ollama:11434"})) is True
    with env(**CLEAN):
        assert backends.is_local(backends.build({})) is True          # the default URL is this computer
        assert backends.is_local(backends.build({"ollama_url": "http://ollama:11434"})) is False
        assert backends.is_local(backends.build({"backend": "off"})) is False
        assert backends.is_local(backends.build({"enable_llm": False})) is False


def test_f3_ollama_cloud_tags_are_not_local_d107():
    for model in ("x:cloud", "x-cloud", "X:Cloud", "gpt-oss:120b-cloud", " qwen3:14b-CLOUD "):
        be = OllamaBackend(url=LOCAL, model=model)
        assert backends.is_local(be) is False, model
    for model in ("qwen3:14b", "cloudy:7b", "cloud:latest", "mycloud7:q4"):
        assert backends.is_local(OllamaBackend(url=LOCAL, model=model)) is True, model


def test_f3_is_local_config_matches_build_without_a_backend():
    with env(**CLEAN):
        assert backends.is_local_config({}) is True
        assert backends.is_local_config({"ollama_model": "qwen3:14b"}) is True
        assert backends.is_local_config({"ollama_model": "x:cloud"}) is False
        assert backends.is_local_config({"ollama_model": "x-cloud"}) is False
        assert backends.is_local_config({"ollama_url": "http://ollama:11434"}) is False
        assert backends.is_local_config({"enable_llm": False}) is False
        assert backends.is_local_config({"backend": "off"}) is False
        assert backends.is_local_config(None) is True                 # defaults, like build({})
    with env(JOBSCRAPER_BACKEND=None, JOBSCRAPER_OLLAMA_URL="http://ollama:11434"):
        assert backends.is_local_config({}) is False
    with env(JOBSCRAPER_BACKEND=None, JOBSCRAPER_OLLAMA_URL=LOCAL):
        assert backends.is_local_config({"ollama_url": "http://ollama:11434"}) is True
    with env(JOBSCRAPER_BACKEND="off", JOBSCRAPER_OLLAMA_URL=None):
        assert backends.is_local_config({}) is False


def test_f3_is_local_config_agrees_with_is_local_of_build():
    budgets = [{}, {"ollama_url": "http://ollama:11434"}, {"ollama_model": "x:cloud"},
               {"ollama_url": "http://localhost:11434", "ollama_model": "gpt-oss:120b-cloud"},
               {"backend": "off"}, {"enable_llm": False}, {"ollama_url": "http://[::1]:11434"}]
    with env(**CLEAN):
        for b in budgets:
            assert backends.is_local_config(b) is backends.is_local(backends.build(b)), b


# ================================================================== T2 / F1d: what the model may read


def _leaves(d: Any) -> list[str]:
    return [str(v) for _p, v in applicant._walk(d) if v is not None]


def test_t2_default_llm_extract_and_grounding_have_no_s_value():
    p = s_profile()
    blob = json.dumps(applicant.llm_extract(p), default=str) + applicant.grounding_text(p)
    assert_no_s(blob, "default extract/grounding")
    assert PHONE not in blob and "alex.testcase@example.com" not in blob
    assert "decline" not in json.dumps(applicant.llm_extract(p)), "no S leaf at all (us_self_id etc.)"


def test_t2_sensitive_true_adds_every_s_block_but_never_extra():
    p = s_profile()
    p["extra"] = {"pet": {"label": "pet", "value": "zzzextra", "sensitive": False}}
    ex = applicant.llm_extract(p, sensitive=True)
    blob = json.dumps(ex, default=str)
    for m in (DOB, GENDER, RACE, FAITH, RESIDENCY, PHONE):
        assert m in blob, m
    assert ex["declarations"] and ex["us_self_id"], "declarations and us_self_id are read"
    assert "extra" not in ex and "zzzextra" not in blob
    assert "zzzextra" not in applicant.grounding_text(p, sensitive=True)


def test_f1d_grounding_with_protected_false_keeps_contact_only():
    p = s_profile()
    g = applicant.grounding_text(p, sensitive=True, protected=False)
    assert PHONE in g and "alex.testcase@example.com" in g
    assert_no_s(g, "grounding_text(sensitive=True, protected=False)")
    # protected=True (the default with sensitive=True) is the full prompt-side view.
    full = applicant.grounding_text(p, sensitive=True)
    assert_no_s_missing(full, (DOB, GENDER, RACE, FAITH, RESIDENCY))
    # llm_extract agrees
    ex = json.dumps(applicant.llm_extract(p, sensitive=True, protected=False), default=str)
    assert PHONE in ex
    assert_no_s(ex, "llm_extract(protected=False)")


def assert_no_s_missing(text: str, markers) -> None:
    gone = [m for m in markers if m not in text]
    assert not gone, f"expected in text: {gone}"


def test_f1d_protected_strings_exclude_contact_and_add_the_birth_year():
    p = s_profile()
    prot = applicant.protected_strings(p)
    for m in (RACE, FAITH, RESIDENCY, GENDER, DOB, "2001"):
        assert m in prot, m
    assert PHONE not in prot and "alex.testcase@example.com" not in prot
    assert "1 Example Road" not in prot and "000001" not in prot
    assert PHONE in applicant.sensitive_strings(p), "sensitive_strings still includes contact"
    assert prot == sorted(prot, key=lambda s: (-len(s), s)), "longest first"


# ================================================================== T3: the prompt


def test_t3_user_prompt_holds_s_values_only_when_the_flag_is_on():
    f = field("q", "Tell us about yourself", FieldType.TEXTAREA)
    p = s_profile()
    off = R.user_prompt(f, "text", ctx_on(False, p), 1000)
    on = R.user_prompt(f, "text", ctx_on(True, p), 1000)
    assert_no_s(off, "prompt with the flag off")
    assert PHONE not in off
    for m in (RACE, FAITH, RESIDENCY, GENDER, DOB, PHONE):
        assert m in on, f"the model reads {m} when the flag is on"
    assert "zzzextra" not in on


def test_t3_the_model_is_asked_with_the_s_value_in_its_prompt_and_corpus_lacks_it():
    f = field("a", "Which cultural heritage do you identify with, for our diversity report?",
              FieldType.DROPDOWN, (RACE, "Other"))
    a, be, ctx = resolve_one(f, on=True, replies=[{"choice": 0, "evidence": PHONE}] * 2)
    assert len(be.calls) >= 1 and RACE in be.calls[0]["user"]
    assert RACE not in R.corpus_text(ctx)


# ================================================================== T4: routing untouched, zero model calls

T4_CASES = {
    "tier 2 sensitive no-fit": field("g", "What is your gender?", FieldType.DROPDOWN, ("Male", "Female")),
    "tier 1 SENSITIVE_CANONICAL stop": field("e", "Gender", FieldType.DROPDOWN, ("Male", "Female"),
                                             canonical=Canonical.EEO_GENDER),
    "tier 4 declaration": yes_no("p", "Are you a politically exposed person?"),
    "attestation": field("c", "I confirm I am not a politically exposed person", FieldType.CHECKBOX),
}


def test_t4_sensitive_routes_make_zero_model_calls_with_the_flag_on():
    for name, f in T4_CASES.items():
        for on in (False, True):
            a, be, _ctx = resolve_one(f, on=on, replies=[{"choice": 0, "evidence": "x"}] * 4)
            assert be.calls == [], f"{name} (flag {on}) reached the model"
            assert a.tier is not AnswerTier.LLM, name


def test_t4_the_answers_are_identical_with_the_flag_on_and_off():
    for name, f in T4_CASES.items():
        a0, _b, _c = resolve_one(f, on=False, replies=[])
        a1, _b, _c = resolve_one(f, on=True, replies=[])
        keep = lambda a: (a.status, a.tier, a.source, a.rule_id, a.sensitive, a.value, a.option_labels)  # noqa: E731
        assert keep(a0) == keep(a1), name


# ================================================================== F1: protected values never decide a tier-5 answer

F1A_LABEL = "Which cultural heritage do you identify with, for our diversity report?"


def f1a_field():
    return field("a", F1A_LABEL, FieldType.DROPDOWN, (RACE, "Other"))


def f1b_field():
    return field("b", "Tell us about yourself", FieldType.TEXTAREA)


F1B_REPLY = {"text": f"I am a {RESIDENCY} born in {DOB}, March 12, {FAITH.capitalize()}."}


def test_f1a_choice_naming_a_protected_value_is_ungrounded_and_private():
    reply = {"choice": 0, "evidence": f"race: {RACE}"}
    a, be, _ = resolve_one(f1a_field(), on=True, replies=[reply] * 2)
    assert a.status is AnswerStatus.UNGROUNDED and a.value is None and a.option_labels == ()
    assert a.sensitive is True, "captured as Private, so the owner answers it once"
    assert len(be.calls) == 1, "rejected on the first reply; no second sample"
    assert "private value" in a.note


def test_f1a_same_field_with_the_flag_off_is_ungrounded_not_sensitive():
    reply = {"choice": 0, "evidence": f"race: {RACE}"}
    a, be, _ = resolve_one(f1a_field(), on=False, replies=[reply] * 2)
    assert a.status is AnswerStatus.UNGROUNDED and a.sensitive is False and a.value is None
    assert "private value" not in a.note


def test_f1a_protected_label_with_an_innocent_evidence_still_stops():
    # The chosen option IS the protected value; evidence taken from the contact block grounds,
    # but the option label itself is the S value, so it must not fill.
    reply = {"choice": 0, "evidence": PHONE}
    a, _be, _ = resolve_one(f1a_field(), on=True, replies=[reply] * 2)
    assert a.status is AnswerStatus.UNGROUNDED and a.sensitive is True and a.value is None


def test_f1a_a_non_protected_option_may_fill_when_its_evidence_grounds():
    f = field("a", F1A_LABEL, FieldType.DROPDOWN, ("Other", "Prefer not to say"))
    reply = {"choice": 0, "evidence": "Singapore"}
    a, _be, _ = resolve_one(f, on=True, replies=[reply] * 2)
    assert a.status is AnswerStatus.FILLED and a.sensitive is False


def test_f1b_text_volunteering_protected_values_is_ungrounded_after_one_retry():
    a, be, _ = resolve_one(f1b_field(), on=True, replies=[F1B_REPLY, F1B_REPLY])
    assert a.status is AnswerStatus.UNGROUNDED and a.value is None and a.sensitive is True
    assert len(be.calls) == 2
    retry = be.calls[1]["user"]
    assert "REJECTED BECAUSE" in retry and "private value" in retry.split("REJECTED BECAUSE", 1)[1]
    assert_no_s(retry.split("REJECTED BECAUSE", 1)[1], "the retry instruction")


def test_f1b_a_clean_retry_may_fill():
    clean = {"text": "I built REST APIs in Python for shipment tracking."}
    a, be, _ = resolve_one(f1b_field(), on=True, replies=[F1B_REPLY, clean])
    assert a.status is AnswerStatus.FILLED and a.sensitive is False and len(be.calls) == 2
    assert_no_s(a.value, "the filled text")


def test_f1b_text_with_the_flag_off_is_rejected_by_the_old_rules_untagged():
    a, _be, _ = resolve_one(f1b_field(), on=False, replies=[F1B_REPLY, F1B_REPLY])
    assert a.status is AnswerStatus.UNGROUNDED and a.sensitive is False


def test_f1c_resume_grounded_answers_still_fill_and_the_model_still_reads_s_values():
    f = yes_no("r", "Do you have experience building REST APIs?")
    reply = {"choice": 0, "evidence": "Built REST APIs in Python"}
    a, be, _ = resolve_one(f, on=True, replies=[reply] * 2)
    assert a.status is AnswerStatus.FILLED and a.option_labels == ("Yes",) and a.sensitive is False
    assert RACE in be.calls[0]["user"], "the prompt carries the S values the model may read"


def test_f1c_a_contact_value_still_fills_and_is_tagged_private():
    f = field("t", "Anything else we should know before we call you?", FieldType.TEXTAREA)
    reply = {"text": f"Please call me on {PHONE}."}
    a, be, _ = resolve_one(f, on=True, replies=[reply] * 2)
    assert a.status is AnswerStatus.FILLED and a.value == reply["text"]
    assert a.sensitive is True, "a contact value is still private data"
    assert len(be.calls) == 1


def test_f1c_the_same_contact_value_does_not_ground_with_the_flag_off():
    f = field("t", "Anything else we should know before we call you?", FieldType.TEXTAREA)
    reply = {"text": f"Please call me on {PHONE}."}
    a, _be, _ = resolve_one(f, on=False, replies=[reply] * 2)
    assert a.status is AnswerStatus.UNGROUNDED and a.sensitive is False


def test_f1d_corpus_holds_contact_but_no_protected_value_when_on():
    p = s_profile()
    on, off = R.corpus_text(ctx_on(True, p)), R.corpus_text(ctx_on(False, p))
    assert PHONE in on and PHONE not in off
    assert_no_s(on, "corpus with the flag on")
    assert_no_s(off, "corpus with the flag off")


def test_f1d_evidence_only_an_s_line_supports_is_not_found():
    ctx = ctx_on(True)
    corpus = R.corpus_text(ctx)
    for ev in (f"race: {RACE}", RACE, FAITH, DOB):
        bad = R.grounded("choice", {"choice": 0, "evidence": ev}, ctx, n_options=2, corpus=corpus)
        assert any(v.startswith("evidence not found") for v in bad), (ev, bad)
    ok = R.grounded("choice", {"choice": 0, "evidence": PHONE}, ctx, n_options=2, corpus=corpus)
    assert ok == [], ok


def test_f1_non_local_equivalent_flag_off_behaves_like_before():
    """A remote backend means resolve_ctx hands model_sees_sensitive=False (T6): the resolver then
    shows the model no S value and tags nothing, whatever the config key says."""
    f = f1a_field()
    a, be, ctx = resolve_one(f, on=False, replies=[{"choice": 0, "evidence": "x"}] * 2)
    assert ctx.model_sees_sensitive is False
    for c in be.calls:
        assert_no_s(c["user"], "prompt to a non-local backend")
    assert a.sensitive is False


# ================================================================== F2: no S value in a note, ever


def _both_cases_on():
    a1, _b1, ctx = resolve_one(f1a_field(), on=True, replies=[{"choice": 0, "evidence": f"race: {RACE}"}] * 2)
    a2, _b2, _ = resolve_one(f1b_field(), on=True, replies=[F1B_REPLY, F1B_REPLY])
    return [(f1a_field(), a1), (f1b_field(), a2)], ctx


def test_f2a_answer_notes_with_the_flag_on_carry_no_s_value():
    cases, _ctx = _both_cases_on()
    for _f, a in cases:
        assert_no_s(a.note, "Answer.note", S_MARKERS + ("march",))
        assert not any(tok in a.note.split() for tok in ("03", "12")), a.note
        assert "private value" in a.note


def test_f2a_captured_question_notes_carry_no_s_value():
    cases, ctx = _both_cases_on()
    fields = [f for f, _a in cases]
    answers = {f.key: a for f, a in cases}
    caps = Q.capture(fields, answers, ctx, R.load_rules(REAL_RULES))
    assert len(caps) == 2
    for c in caps:
        assert c.sensitive is True, "tier-5 private-value answers are captured as Private"
        assert_no_s(c.note, "CapturedQuestion.note", S_MARKERS + ("march",))
        assert_no_s(c.label + " " + c.description + " ".join(c.options), "captured label/options", (DOB, FAITH, RESIDENCY, GENDER))


def test_f2a_flag_off_notes_are_unchanged():
    a, _be, _ = resolve_one(f1a_field(), on=False, replies=[{"choice": 0, "evidence": f"race: {RACE}"}] * 2)
    assert a.note.startswith("ungrounded: evidence not found: "), a.note
    t, _be, _ = resolve_one(f1b_field(), on=False, replies=[F1B_REPLY, F1B_REPLY])
    assert t.note.startswith("ungrounded: ") and "number 2001" in t.note, t.note


def test_f2b_llm_failed_scrubs_s_strings_from_a_note():
    f = f1a_field()
    ctx = ctx_on(True)
    note = f"ungrounded: evidence not found: date_of_birth: {DOB} {RACE} {FAITH} {RESIDENCY} {GENDER}"
    a = R._llm_failed(f, True, note, "m", "h", ctx=ctx, sensitive=True)
    assert_no_s(a.note, "_llm_failed note")
    assert "[private]" in a.note and a.sensitive is True
    off = R._llm_failed(f, True, note, "m", "h", ctx=ctx_on(False), sensitive=False)
    assert off.note == note[:300], "flag off: untouched"
    assert R._llm_failed(f, True, note, "m", "h").note == note[:300], "no ctx: untouched"


def test_f2b_note_for_reduces_token_violations_to_their_kind_only_when_on():
    bad = ["number 03", "year 2001", "month March", f"word {RACE}", f"evidence not found: {RACE}",
           "number not found: 12", "private value", "empty text"]
    off = R._note_for(bad, ctx_on(False))
    assert off == "; ".join(bad)
    on = R._note_for(bad, ctx_on(True))
    assert on == "number; year; month; word; evidence not found; number not found; private value; empty text"
    assert_no_s(on, "note kinds", S_MARKERS + ("march",))


def test_f2b_scrub_matches_the_redaction_rules_with_any_mark():
    vals = [RACE, DOB, PHONE, "cat"]
    s = applicant.scrub(f"Zzzrace on {DOB}, call +65{PHONE}, a captcha for cat", vals, "[private]")
    assert s == "[private] on [private], call +65[private], a captcha for [private]", s
    assert applicant.scrub("ab and abc", ["ab"], "#") == "ab and abc", "under 3 characters ignored"
    assert applicant.scrub("x 2001-03-12 y 2001", ["2001", "2001-03-12"], "#") == "x # y #", "longest first"
    assert applicant.scrub("anything", [], "#") == "anything"
    # apply_flow.redact delegates with its own mark
    line = f"{RACE} {PHONE}"
    assert apply_flow.redact(line, [RACE, PHONE]) == applicant.scrub(line, [RACE, PHONE], apply_flow.REDACTED)


# ================================================================== T6: apply_flow


def _run_for_ctx(on: bool, backend) -> tuple[Any, Say, Any]:
    w = make_world(profile=s_profile(), apply_block={"model_sees_sensitive": on})
    say = Say()
    run = apply_flow._Run(w.cfg, w.store, dry_run=True, backend=backend, http=object(),
                          browser_factory=FakeBrowserFactory(),
                          acfg=dataclasses.replace(w.cfg.apply, model_sees_sensitive=on),
                          say=say, evidence=w.tmp / "evidence")
    job = {"company": "Fake Co", "company_key": "fakeco", "company_id": None, "job_id": "j1", "jd_text": ""}
    tenant = type("T", (), {"board": "fakeco"})()
    ctx = run.resolve_ctx(job, tenant, FakeAdapter(), "", attempt_id=1)
    w.close()
    return ctx, say, w


def test_t6_key_on_and_local_backend_turns_the_flag_on():
    ctx, say, _w = _run_for_ctx(True, LocalFake())
    assert ctx.model_sees_sensitive is True
    assert "ignored" not in say.text


def test_t6_key_on_and_remote_backend_turns_it_off_with_one_log_line():
    for be in (LocalFake(url="http://ollama:11434"), LocalFake(model="x:cloud"), LocalFake(model="x-cloud"),
               OffBackend("off"), StubBackend()):
        ctx, say, _w = _run_for_ctx(True, be)
        assert ctx.model_sees_sensitive is False, be
        lines = [l for l in say.lines if "model_sees_sensitive ignored" in l]
        assert lines == ["[attempt 1] model_sees_sensitive ignored: model backend is not on this computer"], say.lines
        assert "ollama" not in say.text and "11434" not in say.text, "no URL in the log"


def test_t6_key_off_is_off_and_silent_for_every_backend():
    for be in (LocalFake(), LocalFake(url="http://ollama:11434"), OffBackend("off")):
        ctx, say, _w = _run_for_ctx(False, be)
        assert ctx.model_sees_sensitive is False and "ignored" not in say.text


def test_t6_a_flag_on_dry_run_logs_stores_and_captures_no_s_value():
    p = s_profile()
    w, ad, cid, jid = fake_world(profile=p, apply_block={"model_sees_sensitive": True})
    ad.fields.extend([f1a_field(), f1b_field()])
    be = LocalFake(replies=[{"choice": 0, "evidence": f"race: {RACE}"}] * 2 + [F1B_REPLY] * 2)
    say = Say()
    acfg = dataclasses.replace(w.cfg.apply, dry_run_hold_s=0, confirm_timeout_s=0)
    with registered(ad), page_signals():
        res = apply_flow.run(w.cfg, w.store, [jid], dry_run=True, backend=be, http=object(),
                             browser_factory=FakeBrowserFactory(), apply_cfg=acfg, say=say,
                             evidence_dir=w.tmp / "evidence")
    assert len(res) == 1
    assert len(be.calls) >= 1 and any(RACE in c["user"] for c in be.calls), "the local model did read S values"
    assert_no_s(say.text, "the job log", S_MARKERS + ("march",))
    rows = w.answers_by_key(res[0].attempt_id)
    for key in ("a", "b"):
        assert rows[key]["status"] != "filled", "protected values never decide a field"
    for r in rows.values():
        assert_no_s(str(r.get("note") or ""), f"audit note for {r['field_key']}", S_MARKERS + ("march",))
        assert_no_s(str(r.get("value_json") or ""), f"audit value for {r['field_key']}", (DOB, RACE, FAITH, RESIDENCY, GENDER))
    for q in w.store.conn.execute("SELECT * FROM questions").fetchall():
        assert_no_s(" ".join(str(x) for x in tuple(q)), "a captured question row", (DOB, FAITH, RESIDENCY, GENDER))
    w.close()


# ================================================================== T7: naming


def test_t7_ask_model_never_names_a_sensitive_question_with_the_flag_on():
    f = T4_CASES["tier 2 sensitive no-fit"]
    a, _be, ctx = resolve_one(f, on=True, replies=[])
    caps = Q.capture([f], {f.key: a}, ctx, R.load_rules(REAL_RULES))
    assert len(caps) == 1 and caps[0].sensitive is True
    spy = StubBackend([{"title": "x"}] * 3)
    assert Q.ask_model(spy, caps[0]) is None and spy.calls == []
    # control: a non-sensitive question is named
    g = field("z", "What was the name of your first pet?", FieldType.TEXT)
    ga, _b, gctx = resolve_one(g, on=True, replies=[{"unknown": True}] * 2)
    gcaps = Q.capture([g], {g.key: ga}, gctx, R.load_rules(REAL_RULES))
    if gcaps and not gcaps[0].sensitive:
        spy2 = StubBackend([{"title": "Pet name"}])
        assert Q.ask_model(spy2, gcaps[0]) is not None and len(spy2.calls) == 1


# ================================================================== T8: web payload + doctor


def _cfg_with(apply_on: bool, budget: dict) -> Config:
    w = make_world(apply_block={"model_sees_sensitive": apply_on})
    raw = yaml.safe_load(w.cfg_path.read_text(encoding="utf-8"))
    raw["budget"] = {**raw["budget"], **budget}
    w.close()
    return Config(raw)


def _gets(cfg: Config) -> tuple[dict, dict]:
    from fastapi.testclient import TestClient
    from jobscraper.store import Store
    from jobscraper.web.api import create_app
    app = create_app(cfg, store_factory=lambda: Store(cfg.db_path, check_same_thread=False))
    c = TestClient(app, base_url="http://localhost", raise_server_exceptions=False)
    a, q = c.get("/api/applicant"), c.get("/api/questions")
    assert a.status_code == 200 and q.status_code == 200, (a.status_code, q.status_code)
    return a.json(), q.json()


def test_t8_both_payloads_carry_model_sees_private_for_each_state():
    states = [
        (True, dict(backend="ollama", enable_llm=True), True),
        (True, dict(backend="ollama", enable_llm=True, ollama_url="http://ollama:11434"), False),
        (True, dict(backend="ollama", enable_llm=True, ollama_model="x:cloud"), False),
        (True, dict(backend="ollama", enable_llm=True, ollama_model="x-cloud"), False),
        (True, dict(backend="off"), False),
        (False, dict(backend="ollama", enable_llm=True), False),
    ]
    with env(**CLEAN):
        for on, budget, want in states:
            ap, qs = _gets(_cfg_with(on, budget))
            assert ap["model_sees_private"] is want, (on, budget, ap.get("model_sees_private"))
            assert qs["model_sees_private"] is want, (on, budget, qs.get("model_sees_private"))


def test_f3_a_get_builds_no_http_client():
    import httpx
    made: list[int] = []
    real = httpx.Client

    class Counting(real):
        def __init__(self, *a, **k):
            made.append(1)
            super().__init__(*a, **k)

    cfg = _cfg_with(True, dict(backend="ollama", enable_llm=True))
    with env(**CLEAN):
        httpx.Client = Counting
        try:
            from jobscraper.web.routers import applicant as router
            before = len(made)
            assert router.model_sees_private(cfg) is True
            assert len(made) == before, "model_sees_private must not construct a backend / httpx.Client"
        finally:
            httpx.Client = real


def _doctor(apply_on: bool, backend) -> str:
    w = make_world(apply_block={"model_sees_sensitive": apply_on})
    out = io.StringIO()
    real = cli.backends.build
    cli.backends.build = lambda _b: backend
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            cli.main(["--config", str(w.cfg_path), "doctor"])
    finally:
        cli.backends.build = real
        w.close()
    return out.getvalue()


def test_t8_doctor_prints_the_privacy_line_in_each_state():
    on = _doctor(True, LocalFake())
    assert "privacy        Private fields: the local AI may read them" in on, on
    remote = _doctor(True, LocalFake(url="http://ollama:11434"))
    assert "privacy        Private fields: kept from the AI (model backend is not on this computer)" in remote, remote
    cloud = _doctor(True, LocalFake(model="x:cloud"))
    assert "Private fields: kept from the AI (model backend is not on this computer)" in cloud, cloud
    off = _doctor(False, LocalFake())
    assert "privacy        Private fields: kept from the AI\n" in off, off
    assert "budget         llm=" in off, "F6: the budget label keeps its column"
    for text in (on, remote, cloud, off):
        assert "11434" not in text.split("privacy", 1)[1].split("\n", 1)[0]
