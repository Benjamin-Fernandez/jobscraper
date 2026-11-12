# Review: Q-119 page-reader fix (react-select helper input) and its pins

Reviewer, 2026-11-12. Scope: `git diff personal...eng/Q-119-greenhouse-live-fixes -- src` (code commit 1626279, `src/jobscraper/apply/page.py`, READER_JS) and `tst/Q-119-reader-pins` (16e7a9c: `tests/test_apply_page_select_helpers.py`, `tests/fixtures/apply/greenhouse_select_helpers.html`). KA-1 (reader feeds the pre-Submit scan).

## Verdict: MERGE WITH FOLLOW-UPS

The change removes the real defect (a second, label-less, required read of every empty react-select), is small, sits after the file / radio / checkbox / date / select / button branches (so it cannot touch them), and is pinned. It cannot cause a wrong or double submission: it only removes fields from the reader's list. No CRITICAL or HIGH finding. One MEDIUM (a hidden required helper of a custom widget the reader does not recognise now vanishes silently) and some LOW items; none block the merge.

Evidence (my own runs, on `git archive` exports in a temp directory, headless Edge present and used):
- `-k select_helpers` on `tst/Q-119-reader-pins`: 4/4. Same test file and fixture dropped onto `personal` code: 1/4 (the three Edge tests fail: 14 fields, four label-less `''` react_select rows), so the pins do pin the defect.
- `-k apply_page`: 33/33 (reader 10/10, select_helpers 4/4, pagefill 8/8, pagefill_review 11/11). `-k workday`: 31/31 (test_workday_nav 13/13, test_q94_gate_prep_edge 1/1, adapters, apply_flow_accounts, mail).
- Reader output, old vs new code, over all 46 `tests/fixtures/apply/**/*.html`: 40 identical, 6 differ (the new fixture and the 5 Greenhouse form fixtures). In each of the 5 old Greenhouse fixtures the old reader returned two `''`-labelled optional `text` fields (their twin `input.remix-css-requiredInput` sits outside `.select__container`, has no `required`); the new reader returns none. Nothing else changed in those lists. All Workday fixtures (`workday*`, `workday_nav/account.html`) are identical.
- The diff holds no employer names, emails, phone numbers, URLs or ids (grep over added lines). The fixture is generic, static, no script, no `http`.

## The five answers

**1. Can the skip rule hide a field a person must fill? PASS for the cases named; one MEDIUM for a custom widget (F1).**
Position: the skip is the first statement of the "inputs and textareas" tail of the loop (page.py:452-456). Before it, in order: input types hidden/submit/button/image/reset/password, `isDate`, `type=file`, `SELECT`, `BUTTON` / non-input `role=combobox`, radios, checkboxes. So file uploads (Greenhouse resume, Workday upload; the file branch looks at `t === 'file'` and never reaches the skip, even when the input is `aria-hidden` + `tabindex=-1`), native radios and checkboxes (an off-screen native checkbox replaced by a span stays read through `ctlVis`), date parts and selects are untouched. I confirmed with a probe page (`aria-hidden` + `tabindex=-1` + `required` file input behind an Attach button, and a hidden native checkbox with a styled span): both are read identically before and after.
Fixtures: only two kinds of `aria-hidden="true"` inputs exist under `tests/fixtures/apply/`: the Greenhouse `requiredInput` twins (the target) and Workday's `beecatcher` honeypot (`workday_nav/account.html:17`, already excluded by `honeypot()`; output identical). The `aria-hidden` `ul.iti__country-list` is not an input. No `tests/*.py` generated page has an `aria-hidden` input.
Honeypots are only more reliably skipped; no decision lost.
What the rule can hide: a text input or textarea that is aria-hidden AND tabindex < 0 and is the ONLY listed trace of a custom widget whose visible part is a `div` / `contenteditable` / `role=button` the reader does not list. Probe (`adv/a.html`): "Available from *" (div button + hidden required input) and "Cover note *" (contenteditable + hidden required textarea) were read by the old code as required text fields and are not listed by the new code at all. See F1.

**2. Is the required flag preserved; does the pre-Submit scan still catch it? YES for react-select; NO for F1 cases.**
Rule 2 reads the twin before it is dropped, so a react-select whose only required signal is the twin is `required: true` (pin (b): "How did you hear about us?" and "Degree" have no aria-required and no `*`). `scan_required` (page.py:748) and `pre_submit_scan` (apply_flow.py:1269) both work from `read_page`, so they still catch an empty required react-select (twin present while empty, so the flag is true while empty, which is exactly when the scan needs it). They cannot see a control the reader no longer lists (F1): then the only backstop is the site refusing Submit; nothing wrong is sent, the attempt ends as a failed one rather than a clean `validation_error` with the field name.

**3. Rule 2 selector false positives. PASS with LOW notes (F2, F3).**
`.select__container, [class*="select__container"]` is the same selector `reactCtl` already uses, so both agree on the shell. `select__value-container` and `select__input-container` do not contain the substring `select__container`. A container holding two selects would mark both required if one twin is present (probe: both "First" and "Second" became required) but `reactCtl` would already mis-pair them there; Greenhouse renders one container per select (F3, LOW). A filled required select: react-select removes the twin when it has a value, so the flag comes back only from `aria-required` or the `*` (probe: "Filled select", no signals: `required=False`). That matters little: `scan_required` only flags EMPTY fields and an emptied select grows its twin again, so the flag is true again exactly when it counts (F2, LOW, for the audit row and any logic that reads `required` of a filled/wrong-valued field).

**4. Workday and other adapters. PASS.**
Same reader, same skip. The only Workday hit is the `beecatcher` honeypot, which was already excluded, and every Workday HTML fixture reads identically old vs new. The python-built Workday pages (`tests/llm_fill_pages.py`) contain no `aria-hidden` input (grep). The engineer's `-k apply_flow` 137/137, `-k apply_e2e` 13/13 and 148/148 are consistent with that; I did not re-run those two (budget). Not coverable here: a real Workday tenant page; the assumption "Workday renders no text input that is both aria-hidden and out of the tab order apart from the honeypot" rests on the fixtures only.

**5. The pins. PASS with LOW notes (F4, F5).**
Four tests: fixture present (always runs; checks no script/http, 4 twins, 5 comboboxes), (a) five react_select fields with exact labels and no empty label, (b) required kept from the twin alone (and Pronouns without a twin stays optional), (c)+(d) a visible required input, an `aria-hidden` input with `tabindex=0` (still read) and the education block fields read, total exactly 10. They fail on the old code (1/4 pass) and pass on the new. The markup follows the engineer's description of the live page (twin as last child of `.select-shell`, in `.select__container`, `opacity:0; width:100%`, no `height:0`), which is exactly why the old fixtures (twin outside the container, `height:0`) hid the defect; I could not compare with the saved live page itself (not in the repo, and I do not open owner files). The fixture is anonymised and generic. Without Edge the browser tests print nothing and return, like `test_apply_page_reader.py`; `browser_page()` prints a note only when Edge fails to start, and says nothing when `edge_available()` is false (F4). Given the handover rule (apply merges gated on separate Edge runs of `-k apply_e2e` and `-k apply_flow`), acceptable if `-k select_helpers` is added to that list and the Coordinator confirms Edge ran (here it did: the old-code run proves it).

## Findings

**F1 (MEDIUM). A skipped helper that is the only trace of an unrecognised custom widget leaves no trace.** page.py:456. Scenario: a posting shows "Start date *" as a styled `div role=button` (not `button`, not `role=combobox`) or "Cover note *" as a `contenteditable`, with a hidden `input/textarea[required][aria-hidden=true][tabindex=-1]` holding the value. Old reader: one required text field (label from the container). New reader: nothing; `scan_required` passes; the form is submitted with the field empty; the site shows its error and the attempt fails with an unspecific reason (no field named). Not a safety issue (nothing wrong sent, no double submission), and the old behaviour (fill a transparent input) would rarely have worked on such widgets either. Suggested fix (follow-up, not blocking): when the skip fires and the helper is `required` (attribute) and rule 2 does not apply (no react-select shell in its ancestors, no other pushed field shares its `containerOf`), push a `skips` entry like the hidden-file one (`{skipped: 'helper', label}`) so the Python side logs "hidden required helper skipped" and, preferably, `pre_submit_scan` treats it as a stop in auto mode. Add a pin for it.

**F2 (LOW). Rule 2 sets `required` only while the select is empty.** page.py:471-473. Once filled the twin is gone, so a select whose only signal was the twin reads `required=False` afterwards. Harmless for the scan (see answer 3). Worth a comment in the code, and a note for the audit viewer that `required` is as of the read.

**F3 (LOW). Two selects inside one `.select__container` would both inherit a single twin's flag.** Same shell logic as `reactCtl`; Greenhouse does not do this. No action unless a real page shows it.

**F4 (LOW). Silent pass without Edge.** `browser_page()` returns None without a note when `edge_available()` is false, so the three behavioural pins pass without running. Add the pin file to the apply merge-gate command list in the handover; optionally make `edge_available()`'s negative path print the note.

**F5 (LOW). Gaps in the pins.** Not pinned: a filled select (flag falls back to aria-required/`*`), a visible aria-hidden/tabindex=-1 input (skipped by design), and F1 once decided. The five older Greenhouse fixtures still carry the twin outside `.select__container` with `height:0` and no `required`: they no longer produce phantom fields but do not exercise rule 2; leave them (changing them alters other suites) or note it in the fixture README.

Pre-existing, not from this diff: old fixtures contain an employer name (`Dataiku`) in test text; public company name, not personal data.

## Spec disagreements

None. The change follows the reader contract in `llm_fill_design` (one record per field, required from the page's own signals) and the fail-closed rule: it can only make the reader list fewer controls, and F1 is the one place where that could lose a stop.

## Open / not verified

- The live Greenhouse page itself (engineer reports 37 fields with 7 twins becoming 30, 0 label-less): not re-run by me; the engineer's description is consistent with what the pins' fixture does.
- `-k apply_flow` and `-k apply_e2e` not re-run by me (engineer: 137/137 and 13/13).
- The engineer's open items B (education grouping), E(i) (site restores data after the read) and the `apply_flow.py:1347-1349` empty-label fallback request are outside this diff and not reviewed here.
