"""Workday navigator oracles (Q-35 WP-T4, lane N WP-N2; llm_fill_design §9.1, D-78;
apply_design §9.4.1-§9.4.3, §9.4.11; spike S-5 (a)-(f); review M7, M8).

Pure parts: `job_url`, `entry_choice` (D-78: Autofill with Resume when offered, never Use My
Last Application), `step_from_title` (M7: question pages keep N), `match_url` forms A and B give
one canonical host, `tenant_from_company` (external_id wins), no Enter key in the module (M8).
Browser parts (headless Edge on local synthetic pages, tests/fixtures/apply/workday_nav and the
llm_fill wd_a/wd_b pages): the entry dialog, the account form beating the progress bar, the
honeypot untouched on sign-in, the click_filter sibling fallback, step ids and entry sections on
the wizard pages, `next_step` never clicking Submit, errors as labels, the confirmation reads.
No network beyond 127.0.0.1; synthetic tenant names only (exampleco, REQ placeholders).
Verify: python tests/run_tests.py -k workday_nav
"""
from __future__ import annotations

import contextlib
import inspect
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_support import WAITING, needs  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
APPLY_FIX = ROOT / "tests" / "fixtures" / "apply"
_W0 = len(WAITING)
WD = "jobscraper.apply.ats.workday"
NEEDS = (f"{WD}:entry_choice", f"{WD}:step_from_title", f"{WD}:job_url", f"{WD}:NAVIGATOR")

EMAIL = "alex.testcase@example.com"
HOST = "exampleco.wd3.myworkdayjobs.com"
A_URL = "https://exampleco.wd3.myworkdayjobs.com/en-US/External_Careers/job/Singapore/Graduate-Engineer_REQ-0001"
B_URL = "https://wd3.myworkdaysite.com/en-US/recruiting/exampleco/External_Careers/job/Singapore/Graduate-Engineer_REQ-0001"


def test_the_navigator_fixtures_are_present():
    for rel in ("workday_nav/entry.html", "workday_nav/account.html", "workday_nav/click_filter.html",
                "workday_nav/jobtasks/completed/application.html", "workday_nav/thanks.html",
                "workday_nav/userhome/index.html", "workday_nav/errors.html", "workday_nav/plain.html",
                "llm_fill/wd_a/03-my_experience/page.html", "llm_fill/wd_a/07-review/page.html"):
        assert (APPLY_FIX / rel).is_file(), rel


# ------------------------------------------------------------------ pure helpers

@needs(*NEEDS)
def test_job_url_strips_the_apply_suffix_query_and_fragment():
    from jobscraper.apply.ats.workday import job_url
    assert job_url(A_URL + "/apply/applyManually?source=LinkedIn#top") == A_URL
    assert job_url(A_URL + "/apply") == A_URL
    assert job_url(A_URL + "?q=1") == A_URL
    assert job_url(A_URL) == A_URL
    assert job_url("") == ""


@needs(*NEEDS)
def test_entry_choice_takes_the_resume_import_and_never_the_last_application():
    """D-78 / LF §9.1: Autofill with Resume when offered (origin resume_import), else Apply
    Manually (site_default); `manual` forces Apply Manually; no dialog = direct."""
    from itertools import combinations
    from jobscraper.apply.ats.workday import entry_choice
    from jobscraper.apply.contracts import WorkdayEntry as E
    A, M, L = "autofill_with_resume", "apply_manually", "use_last_application"
    assert entry_choice(frozenset()) == (E.DIRECT, "site_default")
    assert entry_choice(frozenset({A, M, L})) == (E.AUTOFILL_WITH_RESUME, "resume_import")
    assert entry_choice(frozenset({A})) == (E.AUTOFILL_WITH_RESUME, "resume_import")
    assert entry_choice(frozenset({M, L})) == (E.APPLY_MANUALLY, "site_default")
    assert entry_choice(frozenset({L})) == (E.APPLY_MANUALLY, "site_default"), "by URL when not offered"
    assert entry_choice(frozenset({A, M, L}), "manual") == (E.APPLY_MANUALLY, "site_default")
    assert entry_choice(frozenset({A, M}), " Manual ")[0] is E.APPLY_MANUALLY
    for n in (1, 2, 3):
        for offered in combinations((A, M, L), n):
            for setting in ("auto", "manual", ""):
                got, origin = entry_choice(frozenset(offered), setting)
                assert got is not E.USE_LAST_APPLICATION, (offered, setting)
                assert origin == ("resume_import" if got is E.AUTOFILL_WITH_RESUME else "site_default")


@needs(*NEEDS)
def test_step_ids_keep_the_position_for_question_and_unknown_pages():
    """Review M7: two "Application Questions" pages get different ids; named pages fixed ids."""
    from jobscraper.apply.ats.workday import step_from_title as s
    assert s("current step 4 of 7 Application Questions") == "questions_4"
    assert s("Step 5 of 7 Application Questions") == "questions_5"
    assert s("current step 4 of 7Application Questions") == "questions_4"     # hidden span, no space
    assert s("Application Questions") == "questions_1"
    assert s("current step 2 of 7 My Information") == "my_information"
    assert s("current step 3 of 7My Experience") == "my_experience"
    assert s("Voluntary Disclosures") == "voluntary_disclosures"
    assert s("Self Identify") == "self_identify"
    assert s("current step 7 of 7 Review") == "review"
    assert s("Autofill with Resume") == "autofill_with_resume"
    assert s("current step 1 of 7 Create Account/Sign In") == "custom_create_account_sign_in_1"
    assert s("current step 5 of 8 Terms & Conditions") == "custom_terms_and_conditions_5"
    assert s("Additional Information") == "custom_additional_information"
    assert s("") == "" and s("   ") == "" and s("current step 3 of 7") == ""


@needs(*NEEDS)
def test_forms_a_and_b_give_one_canonical_tenant():
    """AD §10.4: one tenant = one host = one vault service, whichever URL form a posting used."""
    from jobscraper.apply.ats.workday import NAVIGATOR as N
    a, b = N.match_url(A_URL), N.match_url(B_URL)
    assert a is not None and b is not None
    assert (a.ats, a.host, a.board, a.site, a.posting_id) == ("workday", HOST, "exampleco",
                                                              "External_Careers", "REQ-0001")
    assert (b.host, b.board, b.site, b.posting_id) == (a.host, a.board, a.site, a.posting_id)
    assert a.vault_service == b.vault_service == f"jobscraper:workday:{HOST}"
    up = N.match_url(A_URL.replace("exampleco", "ExampleCo"))
    assert up is not None and up.host == HOST, "the host is lower-case"
    assert N.match_url("https://exampleco.wd3.myworkdayjobs.com/External_Careers").posting_id == ""
    for url in ("https://job-boards.greenhouse.io/exampleco/jobs/1", "https://example.com/careers", ""):
        assert N.match_url(url) is None, url


@needs(*NEEDS)
def test_tenant_from_company_needs_the_workday_provider_and_prefers_external_id():
    from jobscraper.apply.ats.workday import NAVIGATOR as N
    t = N.tenant_from_company({"provider": "workday", "url": A_URL})
    assert t is not None and t.host == HOST and t.posting_id == "REQ-0001"
    t = N.tenant_from_company({"provider": "Workday", "url": B_URL, "external_id": "REQ-0099"})
    assert t is not None and t.host == HOST and t.posting_id == "REQ-0099"
    assert N.tenant_from_company({"provider": "greenhouse", "url": A_URL}) is None
    assert N.tenant_from_company({"provider": "workday", "url": "https://example.com/x"}) is None


@needs(*NEEDS)
def test_the_navigator_is_registered_and_never_presses_enter():
    """Contracts v5 SiteNavigator; review M8: no Enter key anywhere in the module."""
    from jobscraper.apply import contracts as C
    from jobscraper.apply.ats import REGISTRY
    from jobscraper.apply.ats import workday as W
    assert REGISTRY.get("workday") is W.NAVIGATOR
    assert isinstance(W.NAVIGATOR, C.SiteNavigator)
    assert W.NAVIGATOR.needs_account is True
    src = inspect.getsource(W)
    code = "\n".join(line.split("#", 1)[0] for line in src.splitlines())
    for needle in ('"Enter"', "'Enter'", "keyboard.press", ".press("):
        assert needle not in code, needle


# ------------------------------------------------------------------ browser

def _ctx(url: str, title: str = "Graduate Engineer"):
    from jobscraper.apply.contracts import AttemptContext, Tenant
    lines: list[str] = []
    return AttemptContext(attempt_id=1, job={"url": url, "title": title, "provider": "workday"},
                          tenant=Tenant("workday", HOST, "exampleco"), dry_run=True, email=EMAIL,
                          resume_path="", log=lines.append, screenshot=lambda p, s: "",
                          deadline=time.monotonic() + 600)


@contextlib.contextmanager
def _browser():
    """(page, server) or (None, None) when headless Edge is unavailable."""
    from llm_fill_support import FixtureDir, browser_page
    got = browser_page()
    if got is None:
        yield None, None
        return
    pw, b, pg = got
    try:
        with FixtureDir(APPLY_FIX) as fx:
            yield pg, fx
    finally:
        b.close()
        pw.stop()


def _data(pg, key: str) -> str:
    return pg.evaluate(f"document.body.dataset.{key} || ''")


@needs(*NEEDS)
def test_the_entry_dialog_takes_autofill_and_never_use_my_last_application():
    from jobscraper.apply.ats.workday import NAVIGATOR as N
    with _browser() as (pg, fx):
        if pg is None:
            return
        ctx = _ctx(fx.url("workday_nav/job"))
        pg.goto(fx.url("workday_nav/entry.html?offer=a,m,l"))
        assert N.choose_entry(pg, ctx) == "resume_import"
        assert _data(pg, "chosen") == "autofillWithResume"
        pg.goto(fx.url("workday_nav/entry.html?offer=m,l"))
        assert N.choose_entry(pg, ctx) == "site_default"
        assert _data(pg, "chosen") == "applyManually"
        pg.goto(fx.url("workday_nav/entry.html?offer=l"))           # only the last application offered
        assert N.choose_entry(pg, ctx) == "site_default"
        assert pg.url.endswith("/workday_nav/job/apply/applyManually"), "Apply Manually by URL"


@needs(*NEEDS)
def test_the_account_form_wins_over_the_progress_bar_and_sign_in_skips_the_honeypot():
    """S-5 c: the account form is wizard step 1 with the progress bar showing; S-5 e: the
    `beecatcher` input is never filled; M8: no Enter is pressed."""
    from jobscraper.apply.ats.workday import NAVIGATOR as N
    from jobscraper.apply.contracts import Secret
    with _browser() as (pg, fx):
        if pg is None:
            return
        ctx = _ctx(fx.url("workday_nav/job"))
        pg.goto(fx.url("workday_nav/account.html?mode=signup"))
        assert N.account_wall(pg) == "sign_up"
        pg.goto(fx.url("workday_nav/account.html"))
        assert N.account_wall(pg) == "sign_in"
        assert N.choose_entry(pg, ctx) == "site_default", "the account form means direct entry"
        N.sign_in(pg, ctx, Secret("Synthetic-Passw0rd!"))
        assert _data(pg, "signins") == "1"
        assert pg.input_value("#e1") == EMAIL
        assert pg.input_value('[data-automation-id="beecatcher"]') == ""
        assert _data(pg, "enters") == "0" and _data(pg, "formSubmits") == "0"
        assert N.account_wall(pg) is None
        assert N.step_id(pg, ctx) == "my_information"


@needs(*NEEDS)
def test_a_covered_next_button_is_clicked_through_its_click_filter():
    """S-5 a: a click that times out goes to the sibling `click_filter`."""
    from jobscraper.apply.ats.workday import NAVIGATOR as N
    with _browser() as (pg, fx):
        if pg is None:
            return
        ctx = _ctx(fx.url("workday_nav/job"))
        pg.goto(fx.url("workday_nav/click_filter.html"))
        assert N.step_id(pg, ctx) == "my_information"
        res = N.next_step(pg, ctx)
        assert res.step == "my_experience" and not res.is_review and not res.errors
        assert _data(pg, "filterClicks") == "1" and _data(pg, "buttonClicks") == "0"


@needs(*NEEDS)
def test_step_ids_scope_and_entry_sections_on_the_wizard_pages():
    from jobscraper.apply.ats.workday import FLOW_PAGE, NAVIGATOR as N
    want = {"01-autofill_with_resume": "autofill_with_resume", "02-my_information": "my_information",
            "03-my_experience": "my_experience", "04-questions_1": "questions_4",
            "05-questions_2": "questions_5", "06-voluntary_disclosures": "voluntary_disclosures",
            "07-review": "review"}
    with _browser() as (pg, fx):
        if pg is None:
            return
        ctx = _ctx(fx.url("workday_nav/job"))
        for step, sid in want.items():
            pg.goto(fx.url(f"llm_fill/wd_a/{step}/page.html"))
            assert N.step_id(pg, ctx) == sid, step
            assert N.scope(pg, ctx) == FLOW_PAGE
        pg.goto(fx.url("llm_fill/wd_a/03-my_experience/page.html"))
        secs = {s.section: s for s in N.entry_sections(pg, ctx)}
        assert {k: len(v.entries) for k, v in secs.items()} == {
            "work_experience": 3, "education": 1, "languages": 2, "websites": 1}
        for s in secs.values():
            assert s.add_locator and pg.locator(s.add_locator).count() == 1, s.section
            assert [e.index for e in s.entries] == list(range(1, len(s.entries) + 1))
            for e in s.entries:
                assert e.section == s.section
                assert pg.locator(e.locator).count() == 1, e.locator
                assert e.delete_locator and pg.locator(e.delete_locator).count() == 1, e.title
        again = {s.section: [e.locator for e in s.entries] for s in N.entry_sections(pg, ctx)}
        assert again == {k: [e.locator for e in v.entries] for k, v in secs.items()}, "marks are stable"


@needs(*NEEDS)
def test_next_step_never_clicks_submit_and_reports_errors_as_labels():
    from jobscraper.apply.ats.workday import NAVIGATOR as N
    with _browser() as (pg, fx):
        if pg is None:
            return
        ctx = _ctx(fx.url("workday_nav/job"))
        pg.goto(fx.url("llm_fill/wd_a/07-review/page.html"))
        res = N.next_step(pg, ctx)
        assert res.is_review and res.step == "review" and not res.errors
        assert _data(pg, "submitCount") == "0" and _data(pg, "nextClicks") == "0"
        assert N.submit_ready(pg) is True
        pg.goto(fx.url("llm_fill/wd_b/02-my_information/page.html"))   # a required field is empty
        res = N.next_step(pg, ctx)
        assert res.step == "my_information" and not res.is_review
        assert res.errors and any("Address Line 2" in e for e in res.errors), res.errors
        text = " ".join(res.errors)
        for value in ("Testcase", "91234567", "Example Road", "000001"):
            assert value not in text, "errors carry labels and site messages, never values"


@needs(*NEEDS)
def test_after_submit_reads_text_url_home_and_errors():
    from jobscraper.apply.ats.workday import NAVIGATOR as N
    with _browser() as (pg, fx):
        if pg is None:
            return
        ctx = _ctx(fx.url("workday_nav/job"))
        for rel, want in (("workday_nav/thanks.html", "confirmed:text"),
                          ("workday_nav/jobtasks/completed/application.html", "confirmed:url"),
                          ("workday_nav/userhome/", "confirmed:home"),
                          ("workday_nav/errors.html", "errors"),
                          ("workday_nav/plain.html", None)):
            pg.goto(fx.url(rel))
            assert N.after_submit(pg, ctx) == want, rel
        pg.goto(fx.url("workday_nav/userhome/"))
        assert N.after_submit(pg, _ctx(fx.url("workday_nav/job"), title="Another Role")) is None, \
            "Candidate Home confirms only the job it lists"


if WAITING[_W0:]:
    print(f"[test_workday_nav] {len(WAITING[_W0:])} oracle tests wait for modules not built yet: "
          + ", ".join(sorted({m for _n, m in WAITING[_W0:]})))
