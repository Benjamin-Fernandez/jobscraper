"""Pins for the lane M review probes (Q-35; docs/reviews/Q-35-lane-M.md F1-F9; lane M's
handoff "PROBES for the tester to pin"; D-84 R4, D-86).

  F1  a sensitive pick never reaches the model: label "Race", `sensitive=True`, or a wanted
      value among `facts.enum_s_values(profile)` -> None and 0 calls; a neutral pick = 1 call;
  F2  R4 through the resume: the applicant's own name on an emergency contact / referee /
      next of kin question (resume or keep) -> UNKNOWN "R4: applicant's own detail";
  F3  G7 reads a generic label's context: "Please specify" after "Race" -> UNKNOWN "G7";
      after "Religion" a prefill is shown only as `current_set`; after "Do you hold other
      offers?" it is not sensitive;
  F4  `s_values` needs the account email; the DOB is redacted in 10 date spellings;
  F5  help text doesn't make the applicant's own email/phone "about another person"; the
      label, entry heading and a generic label's context still do;
  F6  a "(Yes/No)" suffix is no negation (L3 fills); a real "never" is still L7;
  F7  how-heard maps by the program's leaf fit; a model option citing the fact with no
      program fit -> UNKNOWN "G2e: no_option_fits";
  F8  `field_sig` is keyed (HMAC with `hash_key`): stable per key, different across keys,
      no key -> TypeError;
  F9  a required cover letter / "why join" left unknown stops the page and is captured with
      a `compose_needed` note, per posting (reason `compose_needed`, or `no_rule` until the
      enum exists; tighten when the architect adds it).
Synthetic sample profile, FakeFillBackend, no browser. Verify: python tests/run_tests.py -k llm_fill_probes
"""
from __future__ import annotations

import copy
import dataclasses
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

_W0 = len(WAITING)
NEEDS = ("jobscraper.apply.llm_fill:pick_option", "jobscraper.apply.facts:enum_s_values",
         "jobscraper.apply.facts:hash_key", "jobscraper.apply.guards:decide",
         "jobscraper.apply.questions:capture_page")


def test_the_probe_pins_load():
    import llm_fill_t2 as T
    assert T.TODAY == "2026-11-03"


def _pf(key, label, type=None, *, required=True, options=(), shown="", origin=None, context="",
        description="", group="", group_title=""):
    from jobscraper.apply.contracts import FieldType as FT, ValueOrigin as VO
    import llm_fill_t2 as T
    p = T.pf(key, label, type or FT.TEXT, required=required, options=options, shown=shown,
             origin=origin or (VO.SITE_DEFAULT if shown else VO.EMPTY), group=group, group_title=group_title)
    if description:
        p = dataclasses.replace(p, field=dataclasses.replace(p.field, description=description))
    return dataclasses.replace(p, context=context) if context else p


def _decide(fields, decisions, ctx=None, *, second=None):
    from jobscraper.apply import facts as F, guards as G, locks
    import llm_fill_t2 as T
    ctx = ctx or T.rctx()
    rules = T.rules()
    lk = locks.lock_page(list(fields), ctx, rules, today=T.TODAY, uploaded={})
    cat = F.fact_catalogue(ctx.profile, ctx, today=T.TODAY)
    return G.decide(list(fields), lk, decisions, cat, ctx, matches={},
                    second=second or (lambda pf: None), today=T.TODAY, rules=rules), lk


def _md(key, source, value, evidence="", ref=""):
    from jobscraper.apply.contracts import FillSource, ModelDecision
    return ModelDecision(field_key=key, source=FillSource(source), ref=ref, value=value, evidence=evidence)


# ------------------------------------------------------------------ F1

@needs(*NEEDS)
def test_f1_a_sensitive_pick_makes_no_model_call():
    from jobscraper.apply import facts as F, llm_fill as L
    from llm_fill_support import FakeFillBackend
    from apply_flow_support import sample_profile
    import llm_fill_t2 as T
    p = sample_profile()
    p["identity"]["race"] = "chinese"
    deny = F.enum_s_values(p)
    assert any(d.lower() == "chinese" for d in deny), "the race value is an enum S value"
    opts = ["Chinese (Han)", "Malay", "Indian", "Others"]
    be = FakeFillBackend(replies=[{"kind": "pick", "match": "WANTED", "raw": {"choice": "Malay"}, "repeat": True}])
    s = T.secrets()
    assert L.pick_option(be, _pf("r", "Race"), "Chinese", opts, s_values=s, deny=deny) is None
    assert L.pick_option(be, _pf("n", "Which option fits?"), "Chinese", opts, s_values=s, sensitive=True) is None
    assert L.pick_option(be, _pf("n", "Which option fits?"), "Chinese", opts, s_values=s, deny=deny) is None
    assert be.calls == [], "a refused pick makes no call"
    got = L.pick_option(be, _pf("n", "Preferred office"), "Malay Road office", ["Malay", "Others"], s_values=s,
                        deny=["something-else"])
    assert len(be.calls) == 1 and got == "Malay"
    from llm_fill_support import find_secrets
    assert not find_secrets(be.prompts_text(), [d for d in deny if len(d) >= 5 and d.lower() != "malay"])


# ------------------------------------------------------------------ F2 (D-84 R4)

@needs(*NEEDS)
def test_f2_the_applicants_own_name_never_answers_a_question_about_another_person():
    from jobscraper.apply.contracts import AnswerStatus as AS, ValueOrigin as VO
    import llm_fill_t2 as T
    name = "Alex Testcase"
    assert name in T.rctx().resume_text, "the name is in RESUME, so G3 alone would pass it"
    for label in ("Emergency contact name", "Referee name", "Next of kin"):
        f = _pf("k", label)
        d, _ = _decide([f], [_md("k", "resume", name, evidence=name)])
        a = d.answers["k"]
        assert a.status is AS.UNKNOWN and a.note == "R4: applicant's own detail", (label, a.status, a.note)
        assert "k" in d.unknown_required
        kept = _pf("k", label, shown=name, origin=VO.RESUME_IMPORT)
        d, _ = _decide([kept], [_md("k", "keep", name, evidence=name)])
        assert d.answers["k"].status is AS.UNKNOWN and d.answers["k"].note.startswith("R4"), (label, "keep")


# ------------------------------------------------------------------ F3 (G7 + context)

@needs(*NEEDS)
def test_f3_a_generic_follow_up_of_a_sensitive_question_is_sensitive():
    from jobscraper.apply import guards as G, llm_fill as L
    from jobscraper.apply.contracts import AnswerStatus as AS, ValueOrigin as VO
    import llm_fill_t2 as T
    ctx = T.rctx(resume_text=T.rctx().resume_text + "\nLanguages: Chinese\n")
    f = _pf("k", "Please specify", context="Race")
    d, _ = _decide([f], [_md("k", "resume", "Chinese", evidence="Languages: Chinese")], ctx)
    a = d.answers["k"]
    assert a.status is AS.UNKNOWN and a.note.startswith("G7"), (a.status, a.note)
    pre = _pf("k2", "Please specify", context="Religion", shown="Buddhism", origin=VO.MYGREENHOUSE)
    view = L.field_view(pre, s_values=T.secrets())
    assert view.get("current_set") is True and "current" not in view, view
    assert "Buddhism" not in str(view)
    assert G.sensitive_label(_pf("k3", "Please specify", context="Do you hold other offers?")) is False
    assert G.sensitive_label(f) is True


# ------------------------------------------------------------------ F4

@needs(*NEEDS)
def test_f4_s_values_need_the_account_email_and_cover_more_date_forms():
    from jobscraper.apply import facts as F, llm_fill as L
    from apply_flow_support import sample_profile
    p = sample_profile()
    try:
        F.s_values(p)                                        # type: ignore[call-arg]
    except TypeError:
        pass
    else:
        raise AssertionError("account_email must be required (review F4)")
    s = F.s_values(p, "alex.account@example.net")
    assert p["identity"]["date_of_birth"] == "2002-03-14"
    for form in ("14 Mar 2002", "March 14 2002", "2002/03/14", "Mar 14, 2002", "2002.03.14", "20020314",
                 "14-Mar-2002", "2002-03-14", "14/03/2002"):
        out = L.redact(f"Born {form} in Singapore.", s)
        assert form not in out, form
    assert "alex.account@example.net" not in L.redact("mail alex.account@example.net", s)


# ------------------------------------------------------------------ F5

@needs(*NEEDS)
def test_f5_help_text_does_not_make_the_applicants_own_details_about_someone_else():
    from jobscraper.apply import facts as F, locks
    from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT
    import llm_fill_t2 as T
    ctx = T.rctx()
    email = _pf("e", "Email address", FT.EMAIL, description="The hiring manager will contact you here")
    lk = locks.lock_page([email], ctx, T.rules(), today=T.TODAY, uploaded={})
    assert "e" in lk and lk["e"].status is AS.FILLED and lk["e"].value == T.EMAIL, lk.get("e")
    phone = _pf("p", "Mobile number", description="For reference checks")
    assert F.relevant("profile:contact.phone_number", phone, T.rules(), rctx=ctx) is True
    assert F.about_other_person(phone) is False
    for other in (_pf("o1", "Emergency contact phone"),
                  _pf("o2", "Phone", group="referee#1", group_title="Referee 1"),
                  _pf("o3", "Please specify", context="Name of your next of kin")):
        assert F.about_other_person(other) is True, other.field.label


# ------------------------------------------------------------------ F6

@needs(*NEEDS)
def test_f6_a_yes_no_suffix_is_not_a_negation():
    from jobscraper.apply import locks
    from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT
    import llm_fill_t2 as T
    ctx = T.rctx()
    q = _pf("c", "Have you ever been convicted of a criminal offence? (Yes/No)", FT.RADIO, options=("Yes", "No"))
    a = locks.lock_page([q], ctx, T.rules(), today=T.TODAY, uploaded={}).get("c")
    assert a is not None and a.status is AS.FILLED and a.value == "No", (a and (a.status, a.value, a.note))
    neg = _pf("n", "I have never been convicted of a criminal offence (Yes/No)", FT.RADIO, options=("Yes", "No"))
    b = locks.lock_page([neg], ctx, T.rules(), today=T.TODAY, uploaded={}).get("n")
    assert b is not None and b.status is not AS.FILLED and "L7" in b.note, (b and (b.status, b.note))


# ------------------------------------------------------------------ F7

@needs(*NEEDS)
def test_f7_how_heard_maps_by_the_programs_leaf_and_the_model_cannot_pick_for_a_fact():
    from jobscraper.apply import facts as F
    from jobscraper.apply.contracts import AnswerStatus as AS, FieldType as FT
    import llm_fill_t2 as T
    ctx = T.rctx()
    opts = ("Online > Company careers website", "Online > LinkedIn", "Referral > Employee")
    hh = _pf("h", "How did you hear about us?", FT.DROPDOWN, options=opts)
    fit = F.fact_value("standing:how_heard", hh, ctx, T.rules(), today=T.TODAY)
    assert fit is not None and "Online > Company careers website" in (fit[1] or (fit[0],)), fit
    odd = _pf("h2", "How did you hear about us?", FT.DROPDOWN, options=("Radio", "Newspaper", "Billboard"))
    d, lk = _decide([odd], [_md("h2", "standing", "Newspaper", evidence="Newspaper", ref="standing:how_heard")])
    assert "h2" not in lk, "how-heard is the model's to cite, not a lock"
    a = d.answers["h2"]
    assert a.status is AS.UNKNOWN and a.note.startswith("G2e"), (a.status, a.note)


# ------------------------------------------------------------------ F8

@needs(*NEEDS)
def test_f8_field_sig_is_keyed():
    from jobscraper.apply import facts as F
    import llm_fill_t2 as T
    ctx = T.rctx()
    other = T.rctx(account_email="someone.else@example.org")
    f = _pf("k", "Mobile Phone", shown="91234567")
    k1, k2 = F.hash_key(ctx), F.hash_key(other)
    assert k1 != k2
    s1 = F.field_sig(f, "mobile phone", key=k1)
    assert s1 == F.field_sig(f, "mobile phone", key=k1), "stable"
    assert s1 != F.field_sig(f, "mobile phone", key=k2), "another key, another sig"
    assert s1 != F.field_sig(_pf("k", "Mobile Phone", shown="98765432"), "mobile phone", key=k1)
    assert "91234567" not in s1
    try:
        F.field_sig(f, "mobile phone")                       # type: ignore[call-arg]
    except TypeError:
        pass
    else:
        raise AssertionError("field_sig without a key must fail (review F8)")


# ------------------------------------------------------------------ F9 (D-86 interim)

@needs(*NEEDS)
def test_f9_a_required_compose_field_stops_the_page_and_is_captured_per_posting():
    from jobscraper.apply import questions as Q
    from jobscraper.apply.contracts import FieldType as FT
    import llm_fill_t2 as T
    fields = [_pf("cl", "Cover Letter", FT.FILE), _pf("why", "Why do you want to join us?", FT.TEXTAREA)]
    caps = {}
    for jd in ("Build data pipelines.", "Design chips."):
        ctx = T.rctx(jd_text=jd)
        d, _ = _decide(fields, [], ctx)
        assert set(d.unknown_required) >= {"cl", "why"}
        got = {c.field_key: c for c in Q.capture_page(fields, d.answers, ctx, T.rules())}
        assert set(got) == {"cl", "why"}, set(got)
        for c in got.values():
            assert c.note.startswith("compose_needed"), c.note
            assert c.reason.value in ("compose_needed", "no_rule"), c.reason   # tighten once the enum exists
            assert "compose @" in c.label_norm, c.label_norm
        caps[jd] = got
    a, b = caps.values()
    assert a["why"].label_norm != b["why"].label_norm, "per posting"


if WAITING[_W0:]:
    print(f"[test_llm_fill_probes] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
