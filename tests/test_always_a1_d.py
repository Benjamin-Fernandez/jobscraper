"""Q-121 Amendment A1 oracles, part 4: the protected-class matrix and the Coordinator's ruling
(llm_first_fill_design §17.1 "Adverse declarations", §17.2, §17.3 "When the model's class is wrong";
pin groups (26) class MISSING, (27) class FORCED to `ordinary`, and the ruling).

THE TABLE below lists one HARMFUL model answer per protected class: agreeing to a refused consent, opting in
to marketing, a declaration that applies, a work right the rows do not give, an owner-only fact nobody gave,
a self-ID guess, an applicant's contact in another person's field. Each row carries the end that is
PROTECTIVE (what the design allows). The same table is run with the model's class missing (a cut schema),
forced to `ordinary` (a blind model), right, the code key's own class (the fake's default) and with a
silent model: in EVERY column every row must end protectively. This is the real-model proof of the veto path
(§17.8 (h)) in fake form.

Ruling (Coordinator on review Q1): for a declaration named by EITHER key, a value stating that a declaration
applies is never written, assumed or not, when the profile's truth is false; the end is the none-applies
option, unticked, or the designed stop / empty.

Fakes only. Verify: python tests/run_tests.py -k always_a1_d
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from always_a1_support import (  # noqa: E402
    DELETE, INVENTED_DOB, NO_CLASS, NO_DOB, YN, FakeAsk, attempt, digits, is_stop, is_ticked, is_unticked,
    labels, lie, pick_by, profile_with, report, say, shown, stop_is, what, _pf)

PRIVACY = "I consent to the processing of my personal data"


def _rows():
    from apply_flow_support import EMAIL
    R = []

    def add(name, make, harmful, klass, ok, edits=None, rctx_kw=None, ok_code_only=None):
        # ok_code_only: the end when ONLY the code key names the class (the model's class missing or
        # `ordinary`) and the one confirmation call is unusable (D-211 F, address / phone / postal code)
        R.append(dict(name=name, make=make, harmful=harmful, klass=klass, ok=ok, edits=edits or {}, rctx_kw=rctx_kw or {},
                      ok_code_only=ok_code_only))

    nothing = lambda res: not is_stop(res)                                         # noqa: E731
    no_or_empty = lambda res: (not is_stop(res)) and shown(res) in ("No", "")      # noqa: E731
    add("privacy consent, key false", lambda: _pf("c", PRIVACY, "CHECKBOX"), "true", "consent_privacy",
        lambda r: stop_is(r, "consent_refused", "consents.privacy_consent"), {"consents__privacy_consent": False})
    add("retention yes/no, key false", lambda: _pf("c", "May we keep your details on file for future roles?", options=YN),
        "Yes", "consent_retention", lambda r: shown(r) == "No", {"consents__data_retention_consent": False})
    add("certification box, key false", lambda: _pf("c", "I certify that the information above is true and complete", "CHECKBOX"),
        "true", "certification", lambda r: stop_is(r, "consent_refused", "consents.certify_true"), {"consents__certify_true": False})
    add("marketing box, opt-in unset", lambda: _pf("c", "Sign me up for job alerts", "CHECKBOX"), "true", "marketing",
        is_unticked, {"consents__talent_pool_opt_in": DELETE})
    add("PEP yes/no", lambda: _pf("c", "Are you a politically exposed person?", options=YN), "Yes", "declaration:pep", no_or_empty)
    add("PEP checkbox", lambda: _pf("c", "Tick if you are a politically exposed person", "CHECKBOX"), "true", "declaration:pep", is_unticked)
    add("declaration radio list", lambda: _pf("c", "Do any of the following apply?", "RADIO",
                                              options=("Criminal conviction", "Bankruptcy", "None of the above")),
        "Bankruptcy", "declaration:bankruptcy", lambda r: not is_stop(r) and shown(r) in ("None of the above", ""))
    add("declaration multi list", lambda: _pf("c", "Please select all that apply to you", "MULTI_CHOICE",
                                              options=("I am a politically exposed person", "I am bankrupt", "None of the above")),
        ["I am bankrupt"], "declaration:bankruptcy", lambda r: not is_stop(r) and not ({"I am bankrupt", "I am a politically exposed person"} & set(labels(r))))
    add("criminal record yes/no", lambda: _pf("c", "Have you ever been convicted of a criminal offence?", options=YN), "Yes",
        "declaration:criminal_record", no_or_empty)
    add("bankruptcy yes/no", lambda: _pf("c", "Have you ever been declared bankrupt?", options=YN), "Yes", "declaration:bankruptcy", no_or_empty)
    add("dismissal yes/no (C3)", lambda: _pf("c", "Have you ever been dismissed or asked to resign from any employment?", options=YN),
        "Yes", "declaration:other", no_or_empty)
    # D-212 U4 / W: the protective end never writes code's own reading, so with the fake's unusable
    # confirmation a vetoed work-rights over-claim ends EMPTY (the confirmation that names the truth is
    # pinned in test_always_a1_final::test_w_*)
    add("work right in the US", lambda: _pf("c", "Are you legally authorised to work in the United States?", options=YN), "Yes",
        "work_right", lambda r: not is_stop(r) and shown(r) == "")
    add("sponsorship in the US", lambda: _pf("c", "Will you now or in the future require sponsorship for employment visa status in the United States?", options=YN),
        "No", "sponsorship", lambda r: not is_stop(r) and shown(r) == "", {"singapore_status__requires_sponsorship": {"SG": False, "US": True}})
    add("date of birth, none in the profile", lambda: _pf("c", "Date of birth", "TEXT"), INVENTED_DOB, "owner_fact:date_of_birth",
        lambda r: stop_is(r, "owner_fact_missing"), NO_DOB)
    # D-211 F: both keys / a right class / a silent model -> the profile value. The code key ALONE (class
    # missing / ordinary) -> ONE own-fact confirmation: Yes -> the profile value (pinned in test_a1_m1_*),
    # No or unusable (this fake's pick is "") -> the model's own value, written assumed (never a stop).
    add("home address", lambda: _pf("c", "Home address", "TEXT"), "88 Orchard Road", "owner_fact:address",
        lambda r: not is_stop(r) and "1 Example Road" in shown(r),
        ok_code_only=lambda r: not is_stop(r) and shown(r) == "88 Orchard Road" and r.assumed)
    add("mobile number", lambda: _pf("c", "Mobile number", "PHONE"), "98765432", "owner_fact:phone",
        lambda r: not is_stop(r) and "91234567" in digits(shown(r)),
        ok_code_only=lambda r: not is_stop(r) and digits(shown(r)) == "98765432" and r.assumed)
    add("social security number", lambda: _pf("c", "Social security number", "TEXT"), "123-45-6789", "owner_fact:national_id",
        lambda r: stop_is(r, "owner_fact_missing"))
    add("class of degree, none anywhere", lambda: _pf("c", "Class of degree", "TEXT"), "First Class Honours", "owner_fact:grade",
        lambda r: stop_is(r, "owner_fact_missing"),
        {"education": [{"institution": "Nanyang Example University", "degree": "Bachelor of Engineering", "major": "Computer Engineering",
                        "start": "2021-08", "end": "2025-06", "grade_type": "cap", "grade": "", "grade_scale": "", "from_resume": False}]},
        {"resume_text": "Alex Testcase. Skills: Python."})
    add("current salary (number)", lambda: _pf("c", "Last drawn salary", "NUMBER"), "5000", "owner_fact:salary_current",
        lambda r: stop_is(r, "owner_fact_missing"))
    add("gender, profile declines", lambda: _pf("c", "Gender", "DROPDOWN", options=("Male", "Female", "Other", "Prefer not to say")),
        "Male", "self_id:gender", lambda r: shown(r) == "Prefer not to say")
    add("disability, default No", lambda: _pf("c", "Do you have a disability?", options=YN), "Yes", "self_id:disability",
        lambda r: shown(r) == "No")
    add("referral email", lambda: _pf("c", "Referral email", "EMAIL"), EMAIL, "other_person",
        lambda r: EMAIL not in shown(r) and "alex.testcase" not in shown(r).lower())
    add("mentor's phone", lambda: _pf("c", "Your mentor's phone number", "TEXT"), "91234567", "other_person",
        lambda r: "91234567" not in digits(shown(r)))
    return R


def _run_rows(column: str):
    bad = []
    for row in _rows():
        for _ in (0,):
            if column == "silent":
                ask = FakeAsk()
            else:
                klass = {"missing": NO_CLASS, "ordinary": "ordinary", "right": row["klass"], "code": None}[column]
                ask = FakeAsk(lambda v, r=row, k=klass: lie(r["harmful"], k))
            res = attempt(row["make"](), ask, profile_with(**row["edits"]), rctx_kw=row["rctx_kw"])
            ok = row["ok_code_only"] if (column in ("missing", "ordinary") and row["ok_code_only"]) else row["ok"]
            if not ok(res):
                bad.append((row["name"], column, "harmful value ended unprotected:", what(res)))
    return bad


def test_a1_matrix_has_every_protected_class_and_every_row_is_an_input_the_old_code_could_get_wrong():
    names = [r["name"] for r in _rows()]
    assert len(names) == len(set(names)) >= 22, names
    classes = {r["klass"].split(":")[0] for r in _rows()}
    assert classes == {"consent_privacy", "consent_retention", "certification", "marketing", "declaration", "work_right",
                       "sponsorship", "owner_fact", "self_id", "other_person"}, classes


def test_a1_26_class_missing_on_every_protected_row_the_code_key_alone_ends_protectively():
    bad = _run_rows("missing")
    assert not bad, report(bad, 10)


def test_a1_27_class_forced_to_ordinary_on_every_protected_row_every_one_ends_protectively():
    bad = _run_rows("ordinary")
    assert not bad, report(bad, 10)


def test_a1_27b_the_right_class_on_every_protected_row_ends_protectively():
    bad = _run_rows("right")
    assert not bad, report(bad, 10)


def test_a1_27c_the_code_keys_own_class_on_every_protected_row_ends_protectively():
    """The fake's default class (= `always.code_key`): both keys agree."""
    bad = _run_rows("code")
    assert not bad, report(bad, 10)


def test_a1_27d_a_silent_model_on_every_protected_row_ends_protectively():
    bad = _run_rows("silent")
    assert not bad, report(bad, 10)


# ================================================================== the ruling

RULING_YN = (("Are you a politically exposed person?", "Yes"),
             ("Have you ever been convicted of a criminal offence?", "Yes"),
             ("Have you ever been declared bankrupt?", "Yes"),
             ("Do you have any relatives employed by the company?", "Yes"),
             ("Have you ever been subject to disciplinary proceedings?", "Yes"),
             ("Have you ever been dismissed or asked to resign from any employment?", "Yes"),
             ("Any pending litigation or legal proceedings against you?", "Yes"),
             ("Is it untrue that you have never been bankrupt?", "Yes"),
             ("Do you deny that you are a politically exposed person?", "No"))
RULING_BOXES = ("Tick if you are a politically exposed person", "I am a politically exposed person",
                "Check this box if you have been convicted of a criminal offence",
                "I have a relative working at Example Employer")
RULING_LISTS = (("MULTI_CHOICE", "Please select all that apply to you", ("I am a politically exposed person", "I have a relative working at Example Employer", "None of the above"),
                 ["I am a politically exposed person"]),
                ("RADIO", "Do any of the following apply?", ("Criminal conviction", "Bankruptcy", "None of the above"), "Bankruptcy"),
                ("RADIO", "Conflict of interest", ("I have no conflict of interest", "I have a conflict of interest"), "I have a conflict of interest"))
ADVERSE_OPTIONS = {"Criminal conviction", "Bankruptcy", "I have a conflict of interest", "I am a politically exposed person",
                   "I have a relative working at Example Employer", "I am bankrupt"}


def test_a1_ruling_a_declaration_that_applies_is_never_written_assumed_or_not_when_the_profile_says_false():
    """Owner declarations are all false (D-87). Class by either key (or both, or none), any basis, assumed
    flag on or off, a confirm call that helps or does not: the adverse value is never in the result."""
    bad = []
    for klass_kind in ("declared", "ordinary", NO_CLASS):
        for assumed in (True, False):
            for basis in ("assumption", "default", "resume"):
                for label, adverse in RULING_YN:
                    k = "declaration:other" if klass_kind == "declared" else klass_kind
                    res = attempt(_pf("r", label, options=YN),
                                  FakeAsk(lambda v, k=k, a=assumed, b=basis, x=adverse: say(x, b, "default:no_declaration" if b == "default" else "", a, klass=k)))
                    if shown(res) == adverse:
                        bad.append((label, klass_kind, f"assumed={assumed}", basis, what(res)))
                for label in RULING_BOXES:
                    k = "declaration:pep" if klass_kind == "declared" else klass_kind
                    res = attempt(_pf("r", label, "CHECKBOX"),
                                  FakeAsk(lambda v, k=k, a=assumed, b=basis: say("true", b, "", a, klass=k)))
                    if is_ticked(res):
                        bad.append((label, klass_kind, f"assumed={assumed}", basis, what(res)))
                for tn, label, options, adverse in RULING_LISTS:
                    k = "declaration:pep" if klass_kind == "declared" else klass_kind
                    res = attempt(_pf("r", label, tn, options=options),
                                  FakeAsk(lambda v, k=k, a=assumed, b=basis, x=adverse: say(x, b, "", a, klass=k)))
                    if ADVERSE_OPTIONS & set(labels(res)):
                        bad.append((label, klass_kind, f"assumed={assumed}", basis, what(res)))
    assert not bad, report(bad, 10)


def test_a1_ruling_a_declaration_the_code_cannot_read_is_never_written_adverse_on_the_models_class_alone():
    """No code key (a French wording, a form of words no list holds), the model names the class: it can only
    veto. D-212 U2 / U3 / U6 (replaces D-211 P3 "agree -> written with no further call"): there is no code
    reading, so ONE confirmation is asked. It AGREES with the model's adverse first answer -> ONE meaning call:
    "no" -> written (assumed, three-call note: the accepted residual that two model calls AND the meaning
    check all say it), "yes" / unusable -> empty. A confirmation that DIFFERS (the right option) or is
    unusable -> empty, never the adverse value (U8, pinned in the U file, adds the meaning call on the
    confirmation's value, so 1 or 2 calls)."""
    bad = []
    for label, options, adverse, right in (("Es-tu une personne politiquement exposée ?", ("Oui", "Non"), "Oui", "Non"),
                                           ("Sind Sie eine politisch exponierte Person?", ("Ja", "Nein"), "Ja", "Nein"),
                                           ("¿Ha sido condenado por un delito?", ("Sí", "No"), "Sí", "No")):
        for assumed in (True, False):
            def run(pick, meaning=""):
                ask = FakeAsk(lambda v, a=assumed, x=adverse: say(x, "assumption", "", a, klass="declaration:criminal_record"),
                              pick=pick_by(pick, meaning))
                return attempt(_pf("r", label, options=options), ask), ask
            for meaning, want in (("no", adverse), ("yes", ""), ("", "")):
                res, ask = run(adverse, meaning)
                if shown(res) != want or len(ask.picks) != 2 or (want and not res.assumed):
                    bad.append((label, f"assumed={assumed}", f"confirm=adverse, meaning {meaning!r}", what(res), len(ask.picks)))
            for pick in ("", right):
                res, ask = run(pick)
                # the Spanish row has a plain "No" option, which gives the reader an option (U3: a confirmation
                # equal to the READER's option is written, assumed): the owner's truth, never the adverse value
                if shown(res) not in (("", right) if right == "No" else ("",)) or not 1 <= len(ask.picks) <= 2:
                    bad.append((label, f"assumed={assumed}", f"confirm={pick!r}", "differ / unusable -> empty",
                                what(res), len(ask.picks)))
    assert not bad, report(bad)


def test_a1_ruling_does_not_block_a_declaration_that_is_true_in_the_profile():
    """The rule protects the owner's truth, it does not replace it: pep=True -> Yes stays Yes (no call), the box
    is ticked (no call). D-212 U2 / U3 (replaces "the wrong No is corrected the other way by code"): a wrong
    No gets ONE confirmation, the pick Yes writes Yes (assumed), an unusable pick leaves it empty; an
    unticked box gets the box question ("Should the box ... be ticked?") and "yes" ticks it (assumed)."""
    p = profile_with(declarations__pep=True)
    label = "Are you a politically exposed person?"
    ask = FakeAsk(lambda v: lie("Yes", "declaration:pep"), pick=pick_by("No", "no"))
    res = attempt(_pf("r", label, options=YN), ask, p)
    assert shown(res) == "Yes" and not ask.picks, what(res)
    ask = FakeAsk(lambda v: lie("No", "declaration:pep"), pick=pick_by("Yes", ""))
    res = attempt(_pf("r", label, options=YN), ask, p)
    assert shown(res) == "Yes" and res.assumed and len(ask.picks) == 1, what(res)
    ask = FakeAsk(lambda v: lie("No", "declaration:pep"), pick=pick_by("", ""))
    res = attempt(_pf("r", label, options=YN), ask, p)
    assert shown(res) == "" and len(ask.picks) == 1, what(res)
    ask = FakeAsk(lambda v: lie("true", "declaration:pep"), pick=pick_by("No", "no"))
    res = attempt(_pf("r", "I am a politically exposed person", "CHECKBOX"), ask, p)
    assert is_ticked(res) and not ask.picks, what(res)
    ask = FakeAsk(lambda v: lie("false", "declaration:pep"), pick=pick_by("yes", ""))
    res = attempt(_pf("r", "I am a politically exposed person", "CHECKBOX"), ask, p)
    assert is_ticked(res) and res.assumed and len(ask.picks) == 1, (what(res), len(ask.picks))
