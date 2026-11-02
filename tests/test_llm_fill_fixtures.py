"""WP-T1: the synthetic llm_fill fixtures and the fake model (Q-35; LF §16, plan §2-§3).

Verify: `python tests/run_tests.py -k llm_fill_fixtures`.

Privacy (public repo): the fixtures are built by tests/llm_fill_pages.py from the synthetic
sample profile and placeholders only. Two scans guard them:
  (a) generic patterns, always;
  (b) a deny-list of the owner's real values, read from the file named by the environment
      variable JOBSCRAPER_FIXTURE_DENYLIST (one value per line, '#' comments). The file lives
      OUTSIDE the repo and is never committed; without it the scan says so and checks nothing.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import llm_fill_pages as P  # noqa: E402
from llm_fill_support import (  # noqa: E402
    FIX, KINDS, SOURCES, FakeFillBackend, FixtureDir, browser_page, field_views, find_secrets,
    sample_secrets, steps, view_key,
)

from jobscraper.apply.contracts import FieldType  # noqa: E402
from jobscraper.backends import BackendError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WIDGETS = {"segmented_date", "file", "native_select", "aria_listbox", "prompt", "react_select", "combobox",
           "radio", "checkbox", "text"}
SCANNED = [p for p in FIX.rglob("*") if p.is_file()] + [ROOT / "tests" / "llm_fill_pages.py",
                                                          ROOT / "tests" / "llm_fill_support.py"]
SAMPLE_PHONE = "91234567"


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------- the fixture tree
def test_every_step_has_a_page_its_expected_fields_and_its_replies():
    assert [s.name for s in steps("wd_a")] == ["01-autofill_with_resume", "02-my_information", "03-my_experience",
                                               "04-questions_1", "05-questions_2", "06-voluntary_disclosures",
                                               "07-review"]
    assert [s.name for s in steps("wd_b")] == ["02-my_information"]
    for tenant in ("wd_a", "wd_b"):
        for s in steps(tenant):
            for f in ("page.html", "fields.json", "reply.json"):
                assert (s / f).is_file(), s / f


def test_fixtures_are_in_sync_with_their_builder():
    """Edit tests/llm_fill_pages.py, then run it; never hand-edit a generated file."""
    built = P.build_all()
    for rel, text in built.items():
        on_disk = (FIX / rel).read_text(encoding="utf-8").replace("\r\n", "\n")
        assert on_disk == text, f"{rel} is stale: run python tests/llm_fill_pages.py"
    generated = {str(p.relative_to(FIX)).replace("\\", "/") for p in FIX.rglob("*") if p.is_file()}
    assert generated - set(built) <= {"shim.js", "README.txt"}, generated - set(built)


def test_expected_fields_use_contract_types_and_widget_families():
    types = {t.value for t in FieldType}
    for p in list(FIX.glob("wd_*/*/fields.json")) + list(FIX.glob("stubs/*.fields.json")):
        for f in json.loads(_text(p)):
            assert f["type"] in types and f["widget"] in WIDGETS, (p, f["label"])
            assert isinstance(f["required"], bool) and isinstance(f["options_complete"], bool)
            if f["group"]:
                assert re.fullmatch(r"(work_experience|education|languages|websites|certifications|other_[a-z0-9_]+)#\d+",
                                    f["group"]), f["group"]
                assert re.fullmatch(r".+ \d+", f["group_title"])
            if f["type"] == "multi_choice":
                assert isinstance(f["shown"], list)


def test_the_six_s5b_error_patterns_are_on_the_pages():
    exp = {f'{f["group_title"]}|{f["label"]}': f for f in
           json.loads(_text(FIX / "wd_a/03-my_experience/fields.json"))}
    assert "Example Logistics" in exp["Work Experience 1|Job Title"]["shown"]                 # 2 company in title
    assert "Projects:" in exp["Work Experience 1|Role Description"]["shown"]                   # 5 parser junk
    assert exp["Work Experience 3|Job Title"]["shown"] == "Campus Robot League"                # E3 junk entry
    assert exp["Languages 2|Language"]["shown"] == "Japanese"                                  # 4 invented level
    assert exp["Languages 2|Overall"]["shown"] == "Advanced"
    mi = {f["label"]: f for f in json.loads(_text(FIX / "wd_a/02-my_information/fields.json"))}
    assert "Company Website > Careers Page" in mi["How Did You Hear About Us?"]["options"]     # 1 hierarchy
    assert '"drop": {' in _text(FIX / "wd_a/03-my_experience/page.html")                      # 6 empty listbox
    replies = json.loads(_text(FIX / "wd_a/03-my_experience/reply.json"))["calls"]
    loc = [c["reply"]["Work Experience 2|Location"] for c in replies if "Work Experience 2|Location" in c.get("reply", {})]
    assert loc and "Alex Testcase" in loc[0]["evidence"]                                       # 3 header city
    wd_b = {f["label"]: f for f in json.loads(_text(FIX / "wd_b/02-my_information/fields.json"))}
    assert wd_b["Address Line 2"]["required"] and wd_b["Address Line 2"]["shown"] == ""


def test_reply_files_are_well_formed_and_name_fields_that_exist():
    for tenant in ("wd_a", "wd_b"):
        for s in steps(tenant):
            keys = {f'{f["group_title"]}|{f["label"]}' for f in json.loads(_text(s / "fields.json"))}
            for call in json.loads(_text(s / "reply.json"))["calls"]:
                assert call["kind"] in KINDS, (s, call)
                if "reply" in call:
                    for k, d in call["reply"].items():
                        assert k in keys, (s.name, k)
                        assert set(d) == {"source", "ref", "value", "evidence"}, (s.name, k)
                        assert d["source"] in SOURCES and len(d["evidence"]) <= 240, (s.name, k)
                        if d["source"] in ("profile", "extra", "standing"):
                            assert d["ref"].startswith(d["source"] + ":"), (s.name, k)
                else:
                    assert "match" in call and "raw" in call, (s, call)


def test_pages_load_nothing_remote_and_carry_no_spike_marks():
    for p in list(FIX.rglob("*.html")):
        t = _text(p)
        assert "data-llmfill" not in t, p
        for bad in ("<link", "<iframe", "<img", "srcset", "<base", "nonce="):
            assert bad not in t.lower(), (p, bad)
        for url in re.findall(r"https?://[^\s\"'<>)]+", t):
            assert re.match(r"https?://(www\.)?(github\.com|linkedin\.com)/(in/)?example-", url), (p, url)
        scripts = re.findall(r"<script([^>]*)>", t)
        assert all('id="shim-data"' in s or "shim.js" in s for s in scripts), (p, scripts)


# ---------------------------------------------------------------------------- privacy scans
def test_the_fixture_tree_passes_the_generic_privacy_scan():
    bad: list[str] = []
    for p in SCANNED:
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".docx"):
            bad.append(f"{p.name}: binary capture")
            continue
        t = _text(p)
        for m in re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", t):
            if not re.search(r"@example\.(com|org)$", m):
                bad.append(f"{p.name}: e-mail")
        for m in re.findall(r"(?<![\w.])(?:\+65[\s-]?)?[689]\d{3}[\s-]?\d{4}(?!\d)", t):
            if re.sub(r"\D", "", m)[-8:] != SAMPLE_PHONE:
                bad.append(f"{p.name}: phone-like number")
        if re.search(r"\b[STFGM]\d{7}[A-Z]\b", t):
            bad.append(f"{p.name}: NRIC-like id")
        if re.search(r"myworkdayjobs\.com|myworkdaysite\.com|\bwd\d+\.myworkday", t, re.I):
            bad.append(f"{p.name}: tenant host")
        if re.search(r"\b(?:R|JR)-?\d{5,}\b", t):
            bad.append(f"{p.name}: requisition id")
    assert not bad, bad


def _denylist() -> list[str] | None:
    path = os.environ.get("JOBSCRAPER_FIXTURE_DENYLIST", "")
    if not path:
        return None
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def test_the_fixture_tree_holds_none_of_the_owners_denylisted_values():
    deny = _denylist()
    if deny is None:
        print("  note: JOBSCRAPER_FIXTURE_DENYLIST not set; owner deny-list scan not run")
        return
    assert deny, "the deny-list file is empty"
    hits = {p.name for p in SCANNED if find_secrets(_text(p), deny)}
    assert not hits, f"deny-listed values found in {sorted(hits)}"   # never print the values


def test_the_synthetic_resume_header_carries_sample_s_values_for_the_privacy_oracle():
    """Review H4 / TR-1: a prompt built from this resume must have them redacted."""
    head = _text(FIX / "resume_sample.txt").splitlines()[:2]
    assert find_secrets("\n".join(head), sample_secrets()), "the resume header must carry S values"


# ---------------------------------------------------------------------------- the fake model
def _prompt(views: list[dict], *, entry: bool = False) -> str:
    block = "RESUME ENTRY resume:experience[0]:\n..." if entry else "RESUME:\n..."
    return f"FACTS:\n...\n{block}\nJOB:\n...\nPAGE: My Information\nFIELDS (JSON):\n{json.dumps(views)}\n" \
           "Answer with one JSON object keyed by field id."


def test_the_fake_answers_by_group_and_question_whatever_the_ids():
    fb = FakeFillBackend.from_file(FIX / "wd_a/02-my_information/reply.json")
    views = [{"id": "f9_zz1", "question": "Given Name(s)", "kind": "text"},
             {"id": "f2_ab3", "question": "Phone Extension", "kind": "text"}]
    out = json.loads(fb.complete("SYSTEM", _prompt(views), temperature=0, seed=7).text)
    assert out["f9_zz1"]["ref"] == "profile:identity.legal_first_name"
    assert out["f2_ab3"]["source"] == "unknown"
    assert fb.calls[0].kind == "page" and fb.calls[0].keys == ("|Given Name(s)", "|Phone Extension")
    assert re.fullmatch(r"[0-9a-f]{16}", fb.calls[0].prompt_hash)
    assert fb.calls[0].kwargs["seed"] == 7


def test_the_fake_routes_entry_pick_second_and_corrective_calls():
    fb = FakeFillBackend.from_file(FIX / "wd_a/03-my_experience/reply.json")
    v = [{"id": "a1", "question": "Job Title", "group_title": "Work Experience 1"}]
    assert "a1" in json.loads(fb.complete("S", _prompt(v, entry=True)).text)
    assert fb.calls[-1].kind == "entry"
    cv = [{"id": "c1", "question": "Degree", "group_title": "Education 1", "site_error": "required"}]
    assert json.loads(fb.complete("S", _prompt(cv, entry=True)).text)["c1"]["source"] == "profile"
    assert fb.calls[-1].kind == "corrective"
    pick = FakeFillBackend.from_file(FIX / "wd_a/02-my_information/reply.json")
    r = pick.complete("Pick the one option that means the same as the wanted answer.",
                      "QUESTION: How Did You Hear About Us?\nOPTIONS: ...")
    assert json.loads(r.text) == {"choice": "Company Website > Careers Page"}
    second = FakeFillBackend(replies=[{"kind": "second", "reply": {"|Q": {"source": "resume", "ref": "",
                                                                           "value": "No", "evidence": "x"}}}])
    second.complete("S", _prompt([{"id": "q", "question": "Q"}]), temperature=0.7, seed=7)
    assert second.calls[0].kind == "second"


def test_the_fake_refuses_an_unscripted_call_and_scripts_transport_faults():
    fb = FakeFillBackend(replies=[])
    try:
        fb.complete("S", _prompt([{"id": "x", "question": "Nobody scripted this"}]))
    except AssertionError as e:
        assert "Nobody scripted this" in str(e)
    else:
        raise AssertionError("strict fake must refuse")
    assert FakeFillBackend(strict=False).complete("S", _prompt([{"id": "x", "question": "Q"}])).text == "{}"
    v = [{"id": "x", "question": "Q"}]
    for entry, exc in (({"raise": "BackendError"}, BackendError), ({"raise": "timeout"}, TimeoutError)):
        fb = FakeFillBackend(replies=[dict(entry, kind="page", reply={"|Q": {}})])
        try:
            fb.complete("S", _prompt(v))
        except exc:
            pass
        else:
            raise AssertionError(f"expected {exc.__name__}")
    cut = FakeFillBackend(replies=[{"kind": "page", "reply": {"|Q": {}}, "done_reason": "length", "text": '{"x": {"so'}])
    c = cut.complete("S", _prompt(v))
    assert c.done_reason == "length" and c.text.startswith('{"x"')


def test_the_secret_scan_finds_a_planted_s_value_and_ignores_a_clean_prompt():
    deny = sample_secrets(account_email="apply.alex@example.com")
    fb = FakeFillBackend(replies=[{"kind": "page", "reply": {"|Q": {}}, "repeat": True}])
    fb.complete("S", _prompt([{"id": "x", "question": "Q", "current": "(private, set)"}]))
    fb.assert_no_secrets(deny)
    fb.complete("S", _prompt([{"id": "x", "question": "Q", "current": "+65 9123 4567"}]))
    try:
        fb.assert_no_secrets(deny)
    except AssertionError as e:
        assert "9123" not in str(e)          # the message never repeats the value
    else:
        raise AssertionError("a phone number in a prompt must be caught")
    assert field_views(_prompt([{"id": "x", "question": "Q"}]))[0]["id"] == "x"
    assert view_key({"question": " Job  Title ", "group_title": "Work Experience 2"}) == "Work Experience 2|Job Title"


# ---------------------------------------------------------------------------- the shim (browser)
def test_the_shim_opens_lists_shows_errors_and_walks_the_wizard():
    got = browser_page()
    if got is None:
        return
    pw, browser, page = got
    try:
        with FixtureDir() as srv:
            page.goto(srv.url("wd_a/02-my_information/page.html"))
            page.click("#listbox-1, button[aria-haspopup='listbox'][name='country']")
            opts = page.locator("[data-automation-id='activeListContainer'] [role='option']").all_inner_texts()
            assert [o.strip() for o in opts] == ["Select One", "Singapore", "Malaysia", "United States of America"]
            page.keyboard.press("Escape")
            page.click("[data-automation-id='pageFooterNextButton']")
            assert page.locator("[data-automation-id='inputAlert']").count() >= 2     # required empties
            assert page.evaluate("document.body.dataset.nextClicks") == "1"
            page.goto(srv.url("wd_a/01-autofill_with_resume/page.html"))
            page.set_input_files("input[type=file]", files=[{"name": "Alex_Testcase_Resume.pdf",
                                                              "mimeType": "application/pdf", "buffer": b"%PDF-1.4"}])
            assert page.inner_text("[data-automation-id='file-upload-item-name']") == "Alex_Testcase_Resume.pdf"
            page.click("[data-automation-id='pageFooterNextButton']")
            page.wait_for_url("**/02-my_information/page.html")
            page.goto(srv.url("wd_a/07-review/page.html"))
            assert page.inner_text("[data-automation-id='pageFooterNextButton']").strip() == "Submit"
    finally:
        browser.close()
        pw.stop()
