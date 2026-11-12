"""WP-Q0 oracles for the capture stage `jobscraper.apply.questions` and the store's question tables
(questions_design.md 4.2, 5, 7, 7.1; WP-Q1a). Contracts v4 types (`CapturedQuestion`, `QuestionKind`,
`QuestionReason`, `QuestionStatus`) exist now, so the fixture checks below run today; everything that
calls `questions.*` or the new `Store` methods is skip-clean until they exist.

ASSUMED call shapes (QD names the functions, not every parameter). Each sits in ONE helper below:
  questions.capture(fields, answers, ctx, rules) -> list[CapturedQuestion]            [QD 4.2, exact]
  questions.kind_for(field) -> QuestionKind                                           [QD 4.2, exact]
  questions.signature(q: CapturedQuestion) -> str                                     -> _sig
  questions.slug_key(label_norm: str) -> str                                          -> _slug
  questions.assign_key(q, extra, rows, suggestion=None) -> key | (key, ...) | obj     -> _assign
      extra = the profile's `extra` mapping; rows = dicts {key, label_norm, kind, title, sensitive}
      of the stored questions; suggestion = what `parse_naming` returned (rule 4) or None.
      The result carries `key` and `named_by` ("profile" | "model" | "rule").
  questions.naming_user_prompt(q, existing) -> str    existing = [(key, title, kind, sensitive)]  -> _prompt
  questions.parse_naming(reply: dict|str, existing, q) -> None | obj/dict/tuple(key, title, description)
  Store.upsert_question(q: dict, now) -> int, add_sighting(...), question_groups(status), retry_candidates(),
  questions_by_key(key), set_questions_status(key, status, now): QD 7.1 (dict shape: tests/questions_support.py)
The store tests need lane B's attempts API (Store.create_attempt, set_attempt_state) as well.
No network; the model is a scripted stub; synthetic data only.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from questions_support import (  # noqa: E402
    FIX, LATER, NOW, BackendError, StubBackend, ctx_for, extra_block, failed_attempt, field, make_job,
    make_store, needs, profile, profile_with_extra, question_row, report_waiting, seed_question,
    unknown, waiting_mark, yes_no,
)

from jobscraper.apply.contracts import (  # noqa: E402
    Answer, AnswerStatus, AnswerTier, CapturedQuestion, Canonical, FieldType, QuestionKind,
    QuestionReason, QuestionStatus,
)
from jobscraper.apply.plan import norm_label  # noqa: E402

_MARK = waiting_mark()
RULES = FIX / "questions.sample.yaml"
CAP = ("jobscraper.apply.questions:capture", "jobscraper.apply.questions:kind_for")
KEYS = ("jobscraper.apply.questions:assign_key", "jobscraper.apply.questions:slug_key")
NAMING = ("jobscraper.apply.questions:parse_naming", "jobscraper.apply.questions:naming_user_prompt",
          "jobscraper.apply.questions:NAMING_SYSTEM", "jobscraper.apply.questions:NAMING_SCHEMA")
STORE = ("jobscraper.store:Store.upsert_question", "jobscraper.store:Store.question_groups",
         "jobscraper.store:Store.retry_candidates", "jobscraper.store:Store.create_attempt")
R_ = QuestionReason
K_ = QuestionKind


def _Q():
    return importlib.import_module("jobscraper.apply.questions")


def _rules():
    return importlib.import_module("jobscraper.apply.resolve").load_rules(RULES)


# ------------------------------------------------------------------ the ASSUMED-shape adapters (change here only)

def _capture(pairs, prof=None, *, employer="Shopee Pte Ltd", ats="greenhouse"):
    fields = [f for f, _a in pairs]
    answers = {f.key: a for f, a in pairs}
    return _Q().capture(fields, answers, ctx_for(prof or profile(), employer=employer, ats=ats), _rules())


def _sig(q) -> str:
    return _Q().signature(q)


def _slug(label_norm: str) -> str:
    return _Q().slug_key(label_norm)


def _get(res, name, idx=None):
    if res is None:
        return None
    if isinstance(res, dict):
        return res.get(name)
    if isinstance(res, tuple):
        return res[idx] if idx is not None and idx < len(res) else None
    return getattr(res, name, None)


def _assign(q, extra=None, rows=(), suggestion=None):
    res = _Q().assign_key(q, extra if extra is not None else {}, list(rows), suggestion)
    key = res if isinstance(res, str) else _get(res, "key", 0)
    named_by = None if isinstance(res, str) else _get(res, "named_by", None)
    if named_by is None and isinstance(res, tuple):
        named_by = next((x for x in res if x in ("profile", "model", "rule")), None)
    return key, named_by


def _prompt(q, existing=()):
    return _Q().naming_user_prompt(q, list(existing))


def _cq(label="What is your visa status?", kind=K_.CHOICE, options=("Citizen", "PR"), reason=R_.NO_RULE,
        target_path="", sensitive=False, employer_norm="shopee", description="", **kw) -> CapturedQuestion:
    return CapturedQuestion(label=label, label_norm=norm_label(label), kind=kind, reason=reason,
                            field_key=kw.pop("field_key", "q1"), field_type=kw.pop("field_type", FieldType.DROPDOWN),
                            sensitive=sensitive, description=description, options=tuple(options),
                            option_norms=tuple(norm_label(o) for o in options), target_path=target_path,
                            employer_norm=employer_norm, **kw)


def _by_key(captured):
    return {c.field_key: c for c in captured}


# ================================================================== contracts and fixtures (run now)

def test_question_contract_types_are_the_ones_the_design_names():
    assert {k.value for k in QuestionKind} == {"yes_no", "choice", "multi", "text", "date", "number"}
    assert {r.value for r in QuestionReason} == {"no_rule", "ungrounded", "profile_gap", "no_option_fits",
                                                 "attestation_unclear", "conflict", "compose_needed",
                                                 "assumed"}   # contracts v7 (D-208): assumed
    # contracts v5 (LF §19, D-86 F9): compose_needed is additive
    assert {s.value for s in QuestionStatus} == {"open", "answered", "dismissed",
                                                 "assumed"}   # contracts v7 (D-208): assumed
    q = _cq()
    assert q.required is True and q.sensitive is False and q.target_path == ""
    try:
        q.label = "x"
    except Exception:
        pass
    else:
        raise AssertionError("CapturedQuestion is frozen")


def test_the_question_row_helper_computes_the_design_signature():
    row = question_row(key="visa_status", label="What is your visa status?", kind="choice",
                       options=("PR", "Citizen"))
    want = hashlib.sha256(("choice\nwhat is your visa status\ncitizen\npr").encode("utf-8")).hexdigest()[:16]
    assert row["sig"] == want, "sig = sha256(kind \\n label_norm \\n sorted option_norms joined by \\n)[:16] (QD 5.1)"


# ================================================================== kind_for (QD 4.2)

@needs(*CAP)
def test_kind_for_maps_the_field_type_and_yes_no_shape():
    kf = _Q().kind_for
    T = FieldType
    assert kf(field("f", "x", T.CHECKBOX)) is K_.YES_NO
    assert kf(field("f", "x", T.DROPDOWN, ("Yes", "No"))) is K_.YES_NO, "a bool-shaped dropdown"
    assert kf(field("f", "x", T.RADIO, ("Yes", "No", "Prefer not to say"))) is K_.YES_NO
    assert kf(field("f", "x", T.DROPDOWN, ("Citizen", "PR"))) is K_.CHOICE
    assert kf(field("f", "x", T.RADIO, ("Email", "Phone"))) is K_.CHOICE
    assert kf(field("f", "x", T.MULTI_CHOICE, ("A", "B"))) is K_.MULTI
    assert kf(field("f", "x", T.DATE)) is K_.DATE
    assert kf(field("f", "x", T.NUMBER)) is K_.NUMBER
    for t in (T.TEXT, T.TEXTAREA, T.EMAIL, T.PHONE, T.URL, T.TYPEAHEAD):
        assert kf(field("f", "x", t)) is K_.TEXT, t


# ================================================================== which fields qualify (QD 4.2)

@needs(*CAP)
def test_only_required_unknown_or_ungrounded_askable_fields_are_captured():
    f_ok = field("ok", "Describe your ideal weekend.", FieldType.TEXTAREA)
    pairs = [
        (f_ok, unknown(f_ok, note="model unavailable")),
        (field("opt", "Anything else?", FieldType.TEXTAREA, required=False), None),
        (field("file", "Upload a portfolio", FieldType.FILE), None),
        (field("hid", "tracking", FieldType.HIDDEN), None),
        (field("filled", "Nickname?", FieldType.TEXT), None),
        (field("skip", "Alt input", FieldType.TEXT), None),
    ]
    fixed = []
    for f, a in pairs:
        if a is None:
            a = unknown(f, status={"opt": AnswerStatus.BLANK_OPTIONAL, "file": AnswerStatus.UNKNOWN,
                                   "hid": AnswerStatus.UNKNOWN, "filled": AnswerStatus.FILLED,
                                   "skip": AnswerStatus.SKIPPED}[f.key])
        fixed.append((f, a))
    got = _by_key(_capture(fixed))
    assert set(got) == {"ok"}, f"only the required unknown text question qualifies, got {sorted(got)}"


@needs(*CAP)
def test_an_employer_specific_declaration_is_not_captured_but_a_standing_one_that_stopped_is():
    stops = []
    for key, label in (("a", "Have you previously worked for us?"),
                       ("b", "Do you have any relatives working at the company?"),
                       ("c", "Do you hold shares in this company?"),
                       ("d", "Have you previously applied to this company?")):
        f = yes_no(key, label)
        stops.append((f, unknown(f)))
    assert _capture(stops) == [], "tier 4 owns these; an unknown there is a real stop, not a missing answer"
    f = yes_no("pep", "Please declare any matters we should be aware of.")
    got = _capture([(f, unknown(f))])
    assert [c.reason for c in got] == [R_.ATTESTATION_UNCLEAR]


@needs(*CAP)
def test_each_reason_and_target_path_follows_the_design_table():
    p = profile()
    p["links"]["linkedin"] = ""
    p["availability"]["notice_period_days"] = None
    p["singapore_status"]["residency_status"] = ""
    p["contact"]["postal_code"] = ""
    fields = {
        "li": field("li", "LinkedIn Profile", FieldType.URL, canonical=Canonical.LINKEDIN),
        "pc": field("pc", "Postal code", FieldType.TEXT, canonical=Canonical.POSTAL_CODE),
        "co": field("co", "Country", FieldType.DROPDOWN, ("France", "Japan"), canonical=Canonical.COUNTRY),
        "np": field("np", "Notice period", FieldType.TEXT),
        "rs": yes_no("rs", "Are you a Singapore Citizen?"),
        "fit": field("fit", "Expected pay band", FieldType.DROPDOWN, ("Low", "High")),
        "cmp": field("cmp", "Years of experience band", FieldType.DROPDOWN, ("0-1", "2-3")),
        "att": yes_no("att", "Please declare any matters we should be aware of."),
        "ung": field("ung", "Tell us about a project you are proud of.", FieldType.TEXTAREA),
        "cfl": yes_no("cfl", "Are you authorised to work in the U.S. or Canada?"),
        "nor": field("nor", "Describe your ideal weekend.", FieldType.TEXTAREA),
    }
    answers = {
        "li": unknown(fields["li"]), "pc": unknown(fields["pc"]), "co": unknown(fields["co"]),
        "np": unknown(fields["np"], rule_id="availability.notice_period_days"),
        "rs": unknown(fields["rs"], rule_id="singapore_status.residency_status#sg_citizen", sensitive=True),
        "fit": unknown(fields["fit"], rule_id="pay.expected_salary"),
        "cmp": unknown(fields["cmp"], rule_id="computed.experience_years"),
        "att": unknown(fields["att"]),
        "ung": unknown(fields["ung"], status=AnswerStatus.UNGROUNDED, note="ungrounded: number 12"),
        "cfl": unknown(fields["cfl"], rule_id="singapore_status.authorised_to_work",
                       note="work rights differ: CA, US"),
        "nor": unknown(fields["nor"], note="model unavailable"),
    }
    got = _by_key(_capture([(fields[k], answers[k]) for k in fields], p))
    want = {
        "li": (R_.PROFILE_GAP, "links.linkedin", False),
        "pc": (R_.PROFILE_GAP, "contact.postal_code", True),         # an S path: Private
        "co": (R_.NO_OPTION_FITS, "", False),                        # the canonical has a value, no option fits
        "np": (R_.PROFILE_GAP, "availability.notice_period_days", False),
        "rs": (R_.PROFILE_GAP, "singapore_status.residency_status", True),   # virtual k#id maps to k
        "fit": (R_.NO_OPTION_FITS, "", False),                       # profile key with a value
        "cmp": (None, "", False),                                    # computed.* is never a profile gap
        "att": (R_.ATTESTATION_UNCLEAR, "", True),
        "ung": (R_.UNGROUNDED, "", False),
        "cfl": (R_.CONFLICT, "", False),
        "nor": (R_.NO_RULE, "", False),
    }
    assert set(got) == set(want), sorted(set(want) ^ set(got))
    for k, (reason, target, sensitive) in want.items():
        c = got[k]
        if reason is not None:
            assert c.reason is reason, (k, c.reason)
        else:
            assert c.reason is not R_.PROFILE_GAP, (k, c.reason)
        assert c.target_path == target, (k, c.target_path)
        assert c.sensitive is sensitive, (k, "sensitive")


@needs(*CAP)
def test_a_captured_question_carries_employer_text_only_and_the_field_facts():
    p = profile_with_extra()
    long_label = "Please explain in detail " + "very " * 80 + "carefully why?"
    opts = tuple(f"Option number {i}" for i in range(60))
    f1 = field("c1", long_label, FieldType.DROPDOWN, opts, description="d" * 400, step="step_two")
    f2 = field("c2", "What is your visa status?", FieldType.DROPDOWN, ("Citizen", "PR"))
    got = _by_key(_capture([(f1, unknown(f1, note="no rule")), (f2, unknown(f2, note="no rule"))], p,
                           employer="Shopee Pte Ltd", ats="workday"))
    assert list(got) == ["c1", "c2"], "one per qualifying field, in form order"
    c1, c2 = got["c1"], got["c2"]
    assert c1.label == long_label[:300] and len(c1.label) == 300, "verbatim, cut at 300"
    assert c1.label_norm in (norm_label(long_label), norm_label(long_label[:300]))
    assert len(c1.description) == 300 and len(c1.options) == 50 and len(c1.option_norms) == 50
    assert c1.options[0] == "Option number 0" and c1.option_norms[0] == norm_label("Option number 0")
    assert c1.step == "step_two" and c1.ats == "workday" and c1.field_type is FieldType.DROPDOWN
    assert c1.kind is K_.CHOICE and c1.required is True and c1.note == "no rule"
    assert c2.options == ("Citizen", "PR") and c2.employer_norm == "shopee", "employer name normalised like a company match"
    dumped = json.dumps([c.__dict__ for c in got.values()], default=str)
    for secret in ("Testcase", "alex.testcase@example.com", "91234567", "2002-03-14", "Mandarin"):
        assert secret not in dumped, f"a profile value reached a captured question: {secret}"


# ================================================================== signature and keys (QD 5.1, 5.2)

@needs("jobscraper.apply.questions:signature")
def test_signature_is_stable_under_option_order_and_changes_with_kind_label_options():
    a = _cq(options=("Citizen", "PR", "Other"))
    b = _cq(options=("Other", "Citizen", "PR"))
    assert _sig(a) == _sig(b), "option order does not matter"
    want = hashlib.sha256(("choice\nwhat is your visa status\ncitizen\nother\npr").encode("utf-8")).hexdigest()[:16]
    assert _sig(a) == want and len(_sig(a)) == 16
    assert _sig(_cq(options=("Citizen", "PR"))) != _sig(a), "another option set is another variant"
    assert _sig(_cq(label="Visa status?")) != _sig(a)
    assert _sig(_cq(kind=K_.MULTI)) != _sig(a)
    same_options = _cq(employer_norm="grab", options=("Citizen", "PR", "Other"))
    assert _sig(same_options) == _sig(a), "the employer is not part of the signature"


@needs(*KEYS)
def test_key_rule_1_a_target_path_is_the_key_and_named_by_profile():
    q = _cq(reason=R_.PROFILE_GAP, target_path="availability.notice_period_days", kind=K_.TEXT,
            label="What is your notice period?", options=())
    assert _assign(q) == ("availability.notice_period_days", "profile")


@needs(*KEYS)
def test_key_rule_2_an_extra_entry_that_lists_the_label_wins_over_rows_and_naming():
    q = _cq(label="What is your visa status?", options=("Citizen", "PR", "Others"))
    rows = [{"key": "other_row_key", "label_norm": "what is your visa status", "kind": "choice",
             "title": "x", "sensitive": False}]
    sugg = {"key": "model_key", "title": "Model", "description": "", "same_as": ""}
    assert _assign(q, extra_block(), rows, sugg)[0] == "visa_status", "the answered entry already owns this wording"


@needs(*KEYS)
def test_key_rule_3_a_stored_row_with_the_same_label_and_kind_gives_its_key_a_kind_clash_does_not():
    q = _cq(label="Preferred contact method?", kind=K_.CHOICE, options=("Email", "Phone"))
    same = [{"key": "contact_method", "label_norm": "preferred contact method", "kind": "choice",
             "title": "Contact method", "sensitive": False}]
    assert _assign(q, {}, same)[0] == "contact_method"
    clash = [{"key": "contact_method", "label_norm": "preferred contact method", "kind": "text",
              "title": "Contact method", "sensitive": False}]
    key, named_by = _assign(q, {}, clash)
    assert key != "contact_method" and named_by == "rule", "a different kind is a different field: slug"


@needs(*KEYS, *NAMING)
def test_key_rule_4_the_models_suggestion_is_used_for_a_non_sensitive_question_and_same_as_joins():
    q = _cq(label="Are you open to hybrid work?", kind=K_.YES_NO, options=("Yes", "No"))
    sugg = {"key": "hybrid_ok", "title": "Open to hybrid", "description": "Hybrid work.", "same_as": ""}
    assert _assign(q, {}, [], sugg) == ("hybrid_ok", "model")
    join = {"key": "ignored_new_key", "title": "Remote or hybrid", "description": "", "same_as": "work_mode_ok"}
    existing = [{"key": "work_mode_ok", "label_norm": "are you ok with remote work", "kind": "yes_no",
                 "title": "Work mode", "sensitive": False}]
    assert _assign(q, {}, existing, join) == ("work_mode_ok", "model"), "same_as joins an existing key of the same kind"


@needs(*KEYS)
def test_key_rule_4_never_names_a_sensitive_question_with_the_model():
    q = _cq(label="What is your mother tongue?", kind=K_.TEXT, options=(), sensitive=True)
    sugg = {"key": "mother_tongue", "title": "Mother tongue", "description": "", "same_as": ""}
    key, named_by = _assign(q, {}, [], sugg)
    assert named_by == "rule" and key == "mother_tongue", "slug of the label, not the model's suggestion"
    q2 = _cq(label="What is your native language?", kind=K_.TEXT, options=(), sensitive=True)
    key2, by2 = _assign(q2, {}, [], {"key": "totally_different", "title": "x", "description": "", "same_as": ""})
    assert by2 == "rule" and key2 == "native_language"


@needs(*KEYS)
def test_key_rule_5_slug_drops_stop_words_keeps_four_tokens_and_is_a_valid_key():
    import re
    from jobscraper.apply.contracts import EXTRA_KEY_PATTERN
    cases = {
        "what is your visa status": "visa_status",
        "please select your preferred working arrangement and location": "preferred_working_arrangement_location",
        "describe your most recent project outcome": "describe_most_recent_project",
        "3 years of python experience": "q_3_years_python_experience",      # a letter first, else the q_ prefix
        "what is your": "question",                                        # nothing left
    }
    for label_norm, want in cases.items():
        assert _slug(label_norm) == want, (label_norm, _slug(label_norm))
        assert re.fullmatch(EXTRA_KEY_PATTERN, _slug(label_norm)), label_norm
    long = _slug("internationalization characteristics distinguishing multidimensional")
    assert len(long) <= 40 and re.fullmatch(EXTRA_KEY_PATTERN, long), long


@needs(*KEYS)
def test_key_rule_5_a_clash_with_another_label_or_kind_gets_a_numbered_suffix():
    q = _cq(label="What is your visa status?", kind=K_.CHOICE, options=("A", "B"))
    taken = [{"key": "visa_status", "label_norm": "visa status of your spouse", "kind": "choice",
              "title": "Spouse visa", "sensitive": False}]
    assert _assign(q, {}, taken) == ("visa_status_2", "rule")
    taken.append({"key": "visa_status_2", "label_norm": "another visa status question", "kind": "choice",
                  "title": "y", "sensitive": False})
    assert _assign(q, {}, taken) == ("visa_status_3", "rule")
    same_kind_same_label = [{"key": "visa_status", "label_norm": "what is your visa status", "kind": "choice",
                             "title": "Visa", "sensitive": False}]
    assert _assign(q, {}, same_kind_same_label)[0] == "visa_status", "the same label and kind is rule 3, not a clash"


# ================================================================== naming (QD 5.3)

def _existing():
    return [("work_mode_ok", "Work mode", "yes_no", False), ("visa_status", "Visa status", "choice", False)]


@needs(*NAMING)
def test_naming_prompt_has_the_question_and_existing_fields_and_no_profile_value_or_employer():
    Q = _Q()
    q = _cq(label="Are you open to hybrid work?", kind=K_.YES_NO, options=("Yes", "No"),
            description="Three days in the office.", employer_norm="shopee")
    prompt = _prompt(q, _existing())
    assert prompt.startswith("QUESTION: Are you open to hybrid work?")
    for want in ("HELP: Three days in the office.", "TYPE: yes_no", "OPTIONS:", "- Yes", "- No",
                 "EXISTING FIELDS:", "- work_mode_ok: Work mode (yes_no)", "- visa_status: Visa status (choice)"):
        assert want in prompt, want
    low = prompt.lower()
    for secret in ("shopee", "testcase", "alex", "example.com", "91234567", "2002-03-14", "mandarin"):
        assert secret not in low, f"{secret!r} must not reach a naming prompt"
    assert "never answer" in Q.NAMING_SYSTEM.lower()
    props = Q.NAMING_SCHEMA["properties"]
    assert set(props) == {"key", "title", "description", "same_as"}
    assert set(Q.NAMING_SCHEMA["required"]) == {"key", "title", "description", "same_as"}


@needs(*NAMING)
def test_naming_prompt_lists_only_non_sensitive_existing_fields_and_at_most_fifty():
    q = _cq()
    existing = [("secret_key", "Mother tongue", "text", True)] + \
               [(f"field_{i:02d}", f"Field {i}", "text", False) for i in range(70)]
    prompt = _prompt(q, existing)
    assert "secret_key" not in prompt and "Mother tongue" not in prompt, "sensitive keys are never listed"
    assert prompt.count("\n- field_") <= 50


@needs(*NAMING)
def test_parse_naming_accepts_a_valid_reply_and_rechecks_everything_else():
    P = _Q().parse_naming
    q = _cq(label="Are you open to hybrid work?", kind=K_.YES_NO, options=("Yes", "No"))
    ex = _existing()
    ok = {"key": "hybrid_ok", "title": "Open to hybrid", "description": "Hybrid work.", "same_as": ""}
    got = P(json.dumps(ok), ex, q)
    assert _get(got, "key", 0) == "hybrid_ok" and _get(got, "title", 1) == "Open to hybrid"
    assert P(ok, ex, q) is not None, "a parsed dict is accepted too"
    # a key that breaks the pattern: no suggestion (the caller falls back to the slug)
    assert P({**ok, "key": "Hybrid OK!"}, ex, q) is None
    assert P({**ok, "key": "x"}, ex, q) is None, "one character is below the pattern's minimum"
    assert P("not json at all", ex, q) is None and P({}, ex, q) is None
    # an empty title: the label is used instead
    no_title = P({**ok, "title": ""}, ex, q)
    assert no_title is not None and "hybrid" in str(_get(no_title, "title", 1)).lower()
    # same_as must be a listed key of the same kind, else it is ignored
    unknown_same = P({**ok, "same_as": "no_such_key"}, ex, q)
    assert _get(unknown_same, "key", 0) == "hybrid_ok"
    kind_clash = P({**ok, "same_as": "visa_status"}, ex, q)           # visa_status is a choice, q is yes_no
    assert _get(kind_clash, "key", 0) == "hybrid_ok", "same_as of another kind is ignored"
    joined = P({**ok, "same_as": "work_mode_ok"}, ex, q)
    assert _get(joined, "key", 0) == "work_mode_ok", "same_as of the same kind joins"
    # the model proposes a key that already exists for another kind: no suggestion
    assert P({**ok, "key": "visa_status"}, ex, q) is None, "a key held by another kind is a clash: slug instead"


@needs(*NAMING)
def test_the_naming_schema_matches_the_design_and_the_key_pattern():
    """QD 5.3. (The call itself, `complete(NAMING_SYSTEM, user, max_tokens=200, format=NAMING_SCHEMA,
    temperature=0, seed=7)`, is made by apply_flow: tests/test_apply_flow_questions.py checks it.)"""
    import re
    from jobscraper.apply.contracts import EXTRA_KEY_PATTERN
    s = _Q().NAMING_SCHEMA
    assert s["type"] == "object" and set(s["required"]) == {"key", "title", "description", "same_as"}
    assert s["properties"]["key"]["pattern"] == EXTRA_KEY_PATTERN
    assert s["properties"]["title"]["maxLength"] == 60 and s["properties"]["description"]["maxLength"] == 160
    assert s["properties"]["same_as"]["maxLength"] == 40
    assert re.fullmatch(s["properties"]["key"]["pattern"], "visa_status")
    sysmsg = _Q().NAMING_SYSTEM
    for phrase in ("never answer", "JSON only", "snake_case", "same_as"):
        assert phrase.lower() in sysmsg.lower(), phrase


# ================================================================== store (QD 7, 7.1)

def _st_with_job():
    st = make_store()
    cid = st.insert_company("x", "Shopee", "https://x.example")
    return st, cid, make_job(st, cid, 1)


def _status(st, key) -> list[str]:
    return [r["status"] for r in st.questions_by_key(key)]


@needs(*STORE)
def test_upsert_reopens_an_answered_question_but_never_a_dismissed_one():
    st, cid, jid = _st_with_job()
    aid = failed_attempt(st, jid, cid)
    qid = seed_question(st, attempt_id=aid, job_id=jid, company_id=cid, key="visa_status",
                        label="What is your visa status?", kind="choice", options=("Citizen", "PR"))
    assert _status(st, "visa_status") == ["open"]
    st.set_questions_status("visa_status", "answered", LATER)
    st.commit()
    assert _status(st, "visa_status") == ["answered"]
    again = st.upsert_question(question_row(key="visa_status", label="What is your visa status?", kind="choice",
                                            options=("Citizen", "PR"), reason="no_option_fits"), LATER)
    st.commit()
    assert again == qid, "the same sig is the same row"
    row = st.questions_by_key("visa_status")[0]
    assert row["status"] == "open", "the saved answer did not fit this time: it is asked again"
    assert row["reason"] == "no_option_fits" and row["last_seen_at"] == LATER
    st.set_questions_status("visa_status", "dismissed", LATER)
    st.upsert_question(question_row(key="visa_status", label="What is your visa status?", kind="choice",
                                    options=("Citizen", "PR")), LATER)
    st.commit()
    assert _status(st, "visa_status") == ["dismissed"], "a dismissed question stays dismissed"
    st.close()


@needs(*STORE)
def test_a_sighting_is_unique_per_question_attempt_and_field_and_nothing_stores_a_value():
    st, cid, jid = _st_with_job()
    aid = failed_attempt(st, jid, cid)
    qid = seed_question(st, attempt_id=aid, job_id=jid, company_id=cid, key="q_one", label="Weird question?",
                        kind="text")
    st.add_sighting(qid, aid, jid, cid, "shopee", "greenhouse", "", "q1", "Weird question?", True, NOW)
    st.commit()
    cand = {c["job_id"]: c for c in st.retry_candidates()}
    assert cand[jid]["open"] == 1, "the same (question, attempt, field) twice is still one sighting"
    cols = {r[1] for r in st.conn.execute("PRAGMA table_info(questions)")} | \
           {r[1] for r in st.conn.execute("PRAGMA table_info(question_sightings)")}
    assert not (cols & {"value", "answer", "value_json", "picks"}), "no answer value is ever stored in these tables"
    st.close()


@needs(*STORE)
def test_question_groups_join_variants_by_key_and_count_the_applications_waiting():
    st, cid, _ = _st_with_job()
    j1, j2, j3 = make_job(st, cid, 11), make_job(st, cid, 12), make_job(st, cid, 13)
    a1, a2 = failed_attempt(st, j1, cid), failed_attempt(st, j2, cid)
    seed_question(st, attempt_id=a1, job_id=j1, company_id=cid, employer_norm="shopee", key="visa_status",
                  label="What is your visa status?", kind="choice", options=("Citizen", "PR"),
                  title="Visa status")
    seed_question(st, attempt_id=a2, job_id=j2, company_id=cid, employer_norm="shopee", key="visa_status",
                  label="Current work pass type", kind="choice", options=("EP", "S Pass"), title="Visa status")
    a3 = failed_attempt(st, j3, cid, reason="validation_error")      # not waiting on a question
    seed_question(st, attempt_id=a3, job_id=j3, company_id=cid, key="visa_status",
                  label="What is your visa status?", kind="choice", options=("Citizen", "PR"))
    groups = {g["key"]: g for g in st.question_groups("open")}
    g = groups["visa_status"]
    assert g["kind"] == "choice" and g["status"] == "open" and not g["sensitive"]
    assert len(g["variants"]) == 2, "one variant per option set"
    assert set(g["labels"]) == {"What is your visa status?", "Current work pass type"}
    assert g["waiting"] == 2, "j1 and j2 are waiting; j3's newest attempt failed for another reason"
    assert "Shopee" in g["employers"]
    assert {"key", "title", "description", "kind", "sensitive", "target_path", "status", "named_by", "labels",
            "variants", "employers", "waiting", "first_seen_at", "last_seen_at"} <= set(g)
    st.set_questions_status("visa_status", "answered", LATER)
    st.commit()
    assert "visa_status" not in {x["key"] for x in st.question_groups("open")}
    assert "visa_status" in {x["key"] for x in st.question_groups("answered")}
    assert "visa_status" in {x["key"] for x in st.question_groups("all")}
    st.close()


@needs(*STORE)
def test_retry_candidates_are_ready_only_when_every_question_of_the_newest_failed_attempt_is_answered():
    st, cid, _ = _st_with_job()
    j1, j2, j3 = make_job(st, cid, 21), make_job(st, cid, 22), make_job(st, cid, 23)
    a1, a2, a3 = (failed_attempt(st, j, cid) for j in (j1, j2, j3))
    seed_question(st, attempt_id=a1, job_id=j1, company_id=cid, key="k_open", label="Open one?", kind="text")
    seed_question(st, attempt_id=a2, job_id=j2, company_id=cid, key="k_done", label="Done one?", kind="text")
    seed_question(st, attempt_id=a3, job_id=j3, company_id=cid, key="k_skip", label="Skipped one?", kind="text")
    st.set_questions_status("k_done", "answered", LATER)
    st.set_questions_status("k_skip", "dismissed", LATER)
    st.commit()
    cand = {c["job_id"]: c for c in st.retry_candidates()}
    assert set(cand) == {j1, j2, j3}
    assert {"job_id", "attempt_id", "company", "title", "open", "dismissed"} <= set(cand[j1])
    ready = {j for j, c in cand.items() if c["open"] == 0 and c["dismissed"] == 0}
    assert ready == {j2}, "an open question blocks; a dismissed one means the owner finishes it by hand"
    assert cand[j1]["open"] == 1 and cand[j3]["dismissed"] == 1
    # a newer attempt for j2 that failed for another reason removes it from the candidates
    failed_attempt(st, j2, cid, reason="validation_error")
    assert j2 not in {c["job_id"] for c in st.retry_candidates()}, "only the NEWEST attempt counts"
    st.close()


report_waiting("test_apply_questions", _MARK)
