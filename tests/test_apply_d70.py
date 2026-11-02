"""D-70 oracles beyond the mail watcher (queue Q-26, tester half).

Run now (modules exist): contracts v3, `yes_if` (apply_design 7.3.3, via a temp rules file so the
test does not depend on the researcher's WP-A03 content), backup_email validation (P8).
Skip-clean until the module exists (`needs`): the identity rule (10.5), the Workday Apply choice
rule (9.4.2), the MyGreenhouse KEEP table (9.1.1) and the MyGreenhouse browser fill.

ASSUMED APIs (change in the helpers named below if the engineers choose differently):
  apply/accounts.py:  choose_identity(primary, backup, rows, has_password) -> Identity(email, action)   [design 10.5, exact]
  apply/ats/workday.py:  choose_entry(offered: set[str], applied_on_tenant: bool, setting: str = "auto")
                         -> (WorkdayEntry, prefill_source)    [ASSUMED; offered holds
                         "apply_manually" / "use_last_application" / "autofill_with_resume"]
  apply_flow.py:  keep_decision(field: FormField, answer: Answer, shown, ctx_email: str) -> str
                  one of "keep" | "overwrite" | "fill"        [ASSUMED name; rules from the 9.1.1 table]
  GreenhouseAdapter.prefill(page, ctx) -> "mygreenhouse" | ""  [design, exact]
No network, no src changes.
"""
from __future__ import annotations

import importlib
import sys
import tempfile
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import ROOT, WAITING, needs, profile  # noqa: E402

from jobscraper.apply import contracts as C  # noqa: E402
from jobscraper.apply.contracts import (  # noqa: E402
    ALWAYS_OURS, EMPLOYER_SPECIFIC_DECLARATIONS, PREFILL_POLICY, PREFILL_SOURCES, Answer,
    AnswerSource, AnswerStatus, AnswerTier, AttemptState as S, Canonical, DeclarationLabel,
    FieldType, FormField, Option, PrefillPolicy, ResolveContext, SignUpOutcome, WorkdayEntry,
)


class NoModel:
    """Tier 5 must not run in these tests."""
    available = False

    def complete(self, *a, **k):
        raise AssertionError("the model must not be called")


# ================================================================== contracts v3 (run now)

def test_contract_version_is_at_least_3():
    assert C.CONTRACT_VERSION >= 3   # v3 = D-70; later versions only add (v4 = D-74/D-75)


def test_prefilled_never_fills_and_its_sources_parse():
    for src in PREFILL_SOURCES:
        a = Answer("f", "x", AnswerTier.NONE, src.value, 0.95, AnswerStatus.PREFILLED)
        assert a.fills is False, "a kept site value is not sent again"
        assert a.source_kind is src
    assert PREFILL_SOURCES == {AnswerSource.MYGREENHOUSE, AnswerSource.WORKDAY_LAST_APPLICATION,
                               AnswerSource.SITE_DEFAULT}
    assert Answer("f", "x", AnswerTier.PROFILE_RULE, "profile:contact.email", 0.9).source_kind \
        is AnswerSource.PROFILE
    assert Answer("f", "x", AnswerTier.LLM, "llm", 0.5).source_kind is AnswerSource.LLM
    assert Answer("f", "x", AnswerTier.LLM, "whatever", 0.5).source_kind is None


def test_prefill_policies_per_source():
    assert PREFILL_POLICY[AnswerSource.MYGREENHOUSE] is PrefillPolicy.KEEP
    assert PREFILL_POLICY[AnswerSource.WORKDAY_LAST_APPLICATION] is PrefillPolicy.OVERWRITE
    assert PREFILL_POLICY[AnswerSource.SITE_DEFAULT] is PrefillPolicy.OVERWRITE
    assert set(PREFILL_POLICY) == set(PREFILL_SOURCES)


def test_always_ours_and_employer_specific_sets():
    assert ALWAYS_OURS == {Canonical.RESUME, Canonical.EMAIL}
    assert EMPLOYER_SPECIFIC_DECLARATIONS == {
        DeclarationLabel.PRIOR_EMPLOYMENT, DeclarationLabel.CURRENT_EMPLOYEE,
        DeclarationLabel.PREVIOUSLY_APPLIED, DeclarationLabel.RELATIVES,
        DeclarationLabel.SHAREHOLDING}
    for keep in (DeclarationLabel.PEP, DeclarationLabel.CRIMINAL_RECORD, DeclarationLabel.HEALTH):
        assert keep not in EMPLOYER_SPECIFIC_DECLARATIONS, "not about this employer: a saved answer may stand"


def test_signing_up_may_repeat_once_but_no_other_state_may():
    assert C.can_transition(S.SIGNING_UP, S.SIGNING_UP)
    for st in S:
        if st not in (S.SIGNING_UP, S.FILLING):   # FILLING repeats per wizard step (pre-D-70)
            assert not C.can_transition(st, st), f"{st} -> {st} must stay forbidden"


def test_account_signup_and_workday_enums():
    assert {s.value for s in C.AccountStatus} >= {
        "creating", "created", "verified", "signin_failed", "unknown", "exists_no_password"}
    assert SignUpOutcome.ALREADY_REGISTERED == "already_registered"
    assert {e.value for e in WorkdayEntry} == {
        "apply_manually", "use_last_application", "autofill_with_resume", "direct"}


def test_resolve_context_account_email_defaults_empty():
    assert ResolveContext(profile={}, employer_name="X").account_email == ""


# ================================================================== yes_if (run now, apply_design 7.3.3)

YES_IF_YAML = textwrap.dedent("""
    version: 1
    questions:
      - key: singapore_status.residency_status
        kind: enum
        sensitive: true
        synonyms: [residency status, singapore citizen pr]
        value_map:
          citizen: [singapore citizen]
          pr: [permanent resident, singapore pr]
          foreigner: [foreigner, non singapore]
        yes_if:
          - id: sg_citizen
            values: [citizen]
            synonyms: [singapore citizen]
            exclude: [or permanent resident, or pr]
          - id: sg_citizen_or_pr
            values: [citizen, pr]
            synonyms: [singapore citizen or permanent resident, singapore citizen or pr]
""")


def _rules(text: str = YES_IF_YAML):
    R = importlib.import_module("jobscraper.apply.resolve")
    p = Path(tempfile.mkdtemp()) / "q.yaml"
    p.write_text(text, encoding="utf-8")
    return R, R.load_rules(p)


def _drop(label: str, options) -> FormField:
    return FormField(key="q", label=label, type=FieldType.DROPDOWN, required=True,
                     options=tuple(Option(o) for o in options))


def _answer(label: str, residency: str, options=("Yes", "No")) -> Answer:
    R, rules = _rules()
    p = profile()
    p["singapore_status"]["residency_status"] = residency
    ctx = ResolveContext(profile=p, employer_name="Example", ats="greenhouse")
    return R.resolve_field(_drop(label, options), ctx, backend=NoModel(), rules=rules,
                           memory=lambda *_a: None)


def test_yes_if_citizen_question_answers_yes_for_a_citizen():
    a = _answer("Are you a Singapore Citizen?", "citizen")
    assert a.tier is AnswerTier.PROFILE_RULE and a.fills
    assert a.option_labels == ("Yes",) and a.sensitive
    assert a.source == "profile:singapore_status.residency_status"
    assert a.rule_id == "singapore_status.residency_status#sg_citizen"


def test_yes_if_citizen_question_answers_no_for_a_pr():
    assert _answer("Are you a Singapore Citizen?", "pr").option_labels == ("No",)


def test_yes_if_citizen_or_pr_excludes_the_narrow_rule():
    q = "Are you a Singapore Citizen or Permanent Resident?"
    a = _answer(q, "citizen")
    assert a.rule_id == "singapore_status.residency_status#sg_citizen_or_pr"
    assert a.option_labels == ("Yes",)
    assert _answer(q, "pr").option_labels == ("Yes",)
    assert _answer(q, "foreigner").option_labels == ("No",)


def test_yes_if_not_used_for_a_three_way_dropdown():
    a = _answer("Singapore Citizen / PR", "citizen",
                options=("Singapore Citizen", "Singapore PR", "Foreigner"))
    assert a.option_labels == ("Singapore Citizen",), "the plain enum entry and its value_map, unchanged"
    assert "#" not in a.rule_id


def test_yes_if_loader_rejections():
    bad = {
        "kind not enum": YES_IF_YAML.replace("kind: enum", "kind: text"),
        "value outside value_map": YES_IF_YAML.replace("values: [citizen]", "values: [nope]", 1),
        "no synonyms": YES_IF_YAML.replace("synonyms: [singapore citizen]\n", "synonyms: []\n", 1),
        "duplicate id": YES_IF_YAML.replace("id: sg_citizen_or_pr", "id: sg_citizen"),
    }
    for why, text in bad.items():
        try:
            _rules(text)
        except ValueError:
            continue
        raise AssertionError(f"{why}: load_rules must raise ValueError")


# ================================================================== backup_email (run now, P8)

def _backup_errors(p) -> list:
    from jobscraper import applicant
    return [e for e in applicant.validate(p) if "backup_email" in str(e)]


def test_backup_email_validation():
    assert not _backup_errors(profile(email="alex.testcase@example.com",
                                      backup_email="alex.backup@example.net"))
    assert not _backup_errors(profile(backup_email=""))
    assert _backup_errors(profile(email="alex.testcase@example.com",
                                  backup_email="alex.testcase@example.com")), "must differ"
    assert _backup_errors(profile(backup_email="not-an-email"))


def test_backup_email_is_sensitive():
    from jobscraper import applicant
    assert applicant.is_sensitive("contact.backup_email")


def test_tier1_email_uses_the_account_email_when_set():
    R = importlib.import_module("jobscraper.apply.resolve")
    p = profile(email="alex.testcase@example.com", backup_email="alex.backup@example.net")
    f = FormField(key="email", label="Email", type=FieldType.TEXT, required=True,
                  canonical=Canonical.EMAIL)
    for acct, want in (("", "alex.testcase@example.com"),
                       ("alex.backup@example.net", "alex.backup@example.net")):
        ctx = ResolveContext(profile=p, employer_name="X", account_email=acct, ats="workday")
        a = R.resolve_field(f, ctx, backend=NoModel(), rules=R.QuestionRules(),
                            memory=lambda *_a: None)
        assert a.value == want, (acct, a.value)


# ================================================================== identity rule (10.5)

@needs("jobscraper.apply.accounts:choose_identity")
def test_identity_choice():
    from jobscraper.apply.accounts import choose_identity
    from jobscraper.apply.contracts import ApplyFailure, ReasonCode
    P, B = "alex.testcase@example.com", "alex.backup@example.net"

    def pick(rows, have, backup=B):
        i = choose_identity(P, backup, rows, lambda e: e in have)
        return i.email, i.action
    assert pick({}, set()) == (P, "sign_up")                                   # rule 4
    assert pick({P: "verified"}, {P}) == (P, "sign_in")                        # rule 1
    assert pick({B: "created"}, {B}) == (B, "sign_in")                         # rule 1, backup
    assert pick({P: "exists_no_password"}, set()) == (B, "sign_up")            # rule 3
    for rows, have, backup, needle in (
        ({P: "signin_failed"}, {P}, "", "retry"),                              # rule 2
        ({P: "exists_no_password"}, set(), "", "backup email"),                # rule 3, no backup
        ({P: "exists_no_password", B: "exists_no_password"}, set(), B, "both your emails"),
    ):
        try:
            pick(rows, have, backup)
        except ApplyFailure as e:
            assert e.reason is ReasonCode.LOGIN_FAILED and needle in e.detail, (rows, e.detail)
        else:
            raise AssertionError(f"{rows}: expected LOGIN_FAILED")


# ================================================================== Workday Apply choice (9.4.2)

@needs("jobscraper.apply.ats.workday:choose_entry")
def test_workday_apply_choice_rule():
    from jobscraper.apply.ats.workday import choose_entry
    M, L, A = "apply_manually", "use_last_application", "autofill_with_resume"
    assert choose_entry({M, L, A}, True) == (WorkdayEntry.USE_LAST_APPLICATION,
                                             AnswerSource.WORKDAY_LAST_APPLICATION.value)
    assert choose_entry({M, L, A}, False) == (WorkdayEntry.APPLY_MANUALLY,
                                              AnswerSource.SITE_DEFAULT.value)
    assert choose_entry({M, A}, True)[0] is WorkdayEntry.APPLY_MANUALLY       # last app not offered
    assert choose_entry({M, L, A}, True, "manual")[0] is WorkdayEntry.APPLY_MANUALLY   # config forces
    for offered in ({M, L, A}, {M}, {M, L}):
        assert choose_entry(offered, True)[0] is not WorkdayEntry.AUTOFILL_WITH_RESUME, "never chosen"
    try:
        choose_entry({A}, False)
    except Exception as e:      # ApplyFailure(page_unrecognised, "workday: only resume autofill offered")
        assert "only resume autofill" in str(e) or "only resume autofill" in getattr(e, "detail", "")
    else:
        raise AssertionError("only Autofill with Resume offered must fail page_unrecognised")


# ================================================================== MyGreenhouse KEEP table (9.1.1)

def _gf(key, label, type=FieldType.TEXT, canonical=None):
    return FormField(key=key, label=label, type=type, required=False, canonical=canonical)


def _ans(f, value, tier=AnswerTier.PROFILE_RULE, source="profile:x", rule_id=""):
    return Answer(f.key, value, tier, source, 0.9, rule_id=rule_id)


@needs("jobscraper.apply_flow:keep_decision")
def test_keep_table_four_always_ours_exceptions_and_the_rest_kept():
    from jobscraper.apply_flow import keep_decision
    EM = "alex.testcase@example.com"
    resume = _gf("resume", "Resume/CV", FieldType.FILE, Canonical.RESUME)
    assert keep_decision(resume, _ans(resume, "C:/r.pdf"), "old.pdf", EM) == "overwrite"       # 1
    email = _gf("email", "Email", canonical=Canonical.EMAIL)
    assert keep_decision(email, _ans(email, EM), "other@example.org", EM) == "overwrite"       # 2
    box = _gf("gdpr", "I consent", FieldType.CHECKBOX)
    assert keep_decision(box, _ans(box, "true"), "true", EM) == "overwrite"                    # 3
    decl = _gf("rel", "Do you have relatives working at Example Employer?", FieldType.DROPDOWN)
    d = _ans(decl, "No", AnswerTier.DECLARATION, "declaration:relatives_at_company",
             rule_id=DeclarationLabel.RELATIVES.value)
    assert keep_decision(decl, d, "Yes", EM) == "overwrite"                                    # 4
    other = _gf("city", "City")
    assert keep_decision(other, _ans(other, "Singapore"), "Johor Bahru", EM) == "keep"
    assert keep_decision(other, _ans(other, "Singapore"), "", EM) == "fill", "only empty fields are filled"
    pep = _gf("pep", "Are you a politically exposed person?", FieldType.DROPDOWN)
    p = _ans(pep, "No", AnswerTier.DECLARATION, "declaration:pep", rule_id=DeclarationLabel.PEP.value)
    assert keep_decision(pep, p, "No", EM) == "keep", "not employer-specific: the saved answer stands"


# ================================================================== MyGreenhouse in the browser (9.1.1)

@needs("jobscraper.apply.ats.greenhouse:GreenhouseAdapter.prefill")
def test_mygreenhouse_fixtures_have_the_autofill_button():
    gh = ROOT / "tests" / "fixtures" / "apply" / "greenhouse"
    for n in ("form_mygreenhouse_signed_in.html", "form_mygreenhouse_signed_out.html"):
        assert "autofill" in (gh / n).read_text(encoding="utf-8").lower(), n
    # TODO once lane B is merged: drive GreenhouseAdapter.prefill on both pages through the real
    # browser layer: signed in -> "mygreenhouse", fields changed, no email typed anywhere;
    # signed out -> "" and the sign-in dialog closed.


if WAITING:
    print(f"[test_apply_d70] {len(WAITING)} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING})))
