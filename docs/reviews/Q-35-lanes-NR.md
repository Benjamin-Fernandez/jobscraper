# Review: Q-35 lanes N and R, `int/Q-35-NR`

- **Reviewer:** reviewer agent, 2026-11-03
- **Diff:** `git diff personal...HEAD -- src config` at `1c4bf89`: 11 files, +3461/-29.
  - **Lane N:** `apply/accounts.py`, `apply/ats/workday.py`, `apply/ats/greenhouse.py` (navigator part), `apply/ats/__init__.py`, the `apply_flow.py` N-block, `store.py`, `config.py`, `config/config.yaml`, `cli.py accounts`.
  - **Lane R:** `apply/page.py`, `apply/widgets.py`.
- **Checked against:**
  - the amended `llm_fill_design.md` (**LF**) §3, §6.4 LL3, §9, §11, §13.4, §14;
  - `docs/reviews/Q-35-design.md` and its re-check;
  - ADR-0003 §5, ADR-0004, D-81, AD §4.2, §10 and §11;
  - NF-01, NF-02, NF-04, NF-06.
- **Evidence:** see "Suite" at the end.

## VERDICT: APPROVE WITH FIXES

**Merging into `personal` is safe for the live app.** Nothing new can fill a form yet:
- Workday stops as `unsupported_ats` in PLANNING, before Edge opens and before any vault or account call.
- `page.py` and `widgets.py` are not called by the Greenhouse path.
- The DB migration is additive.

**One behaviour does go live with the merge.** The Greenhouse emailed security code (AD §4.2) now waits for the mail and re-submits once, in `auto` mode only. I read that path and it is correct; F4 asks for its tests.

**F1 is HIGH: a wrong option can be written with no model and no guard involved.** It isn't reachable until WP-R3/N6a wire the widgets, so it doesn't block this merge. It **must be fixed before R3 or N6a merges.** F2–F9 are MEDIUM.

### What holds (read in the code)

**Submit once (ADR-0004, NF-06):**
- Workday `next_step` returns `is_review` for any nav-button label containing "submit" and never clicks it.
- `submit()` clicks only a button whose text is exactly "Submit".
- `submit_clicked_at` is still committed before the click (unchanged).
- `code_after_submit` allows one re-click (`code_resubmits` ≤ 1). A second code, or any error, ends `submitted_unconfirmed`. Its transitions (`submitting → verifying_email → submitting`) are the ADR-0004 ones.

**Enter (review M8):**
- There is exactly one `press("Enter")` in the new modules (`widgets.py:374`): a Workday prompt search. It sits behind `_ENTER_SAFE_JS`, which allows Enter only with no form, or in a form with no submit control, no untyped `<button>`, no button named Submit, and more than one text input. That matches HTML's implicit-submission rule.
- The reader never types, and the Workday navigator never presses Enter.

**Workday gated before N6a:** `apply_flow.py:794` checks `hasattr(adapter, "read_step")`, which is False for `WorkdayNavigator`, and raises `unsupported_ats` before `self.browser()`. The account code (`account()`, sign-in/up, email check) is reachable only through an account wall, which needs an open page.

**Vault and secrets (AD §10.2, NF-02):**
- Order: generate → `vault.put`, which reads the password back → account row `creating` → sign-up click.
- A field error rolls back both the vault entry and the row. Any other exception keeps them (`unknown`).
- `Secret.__repr__` is masked. The password appears in no log line, detail or DB column.
- The reader drops `type=password` inputs, and `page_text` skips them.
- `accounts add` uses `getpass` and prints only host and status.
- Failure details are redacted in `_Attempt.to`.

**Mail and the deadline (D-81):** Workday's deadline is 900 s and the others' is 420 s. `wait_for_mail` adds the time it waited back onto `ctx.deadline`. `check_email` opens only links the watcher let through (tenant host, Workday link domains, the employer's domain).

**Migration (live DB):**
- Additive: four `ALTER TABLE apply_answers ADD COLUMN` statements, `CREATE TABLE IF NOT EXISTS fill_cache` plus an index, and `SCHEMA_VERSION` 4.
- The `DROP TABLE fill_cache` runs only when an old-shape `fill_cache` exists. The live DB never had one, so it is a no-op there; on a dev DB it only loses cache rows, which can be rebuilt.
- A v3 build opening the v4 DB still works: its inserts name their columns and the version is never downgraded.
- `fill_cache` stores decisions only.

**Widgets (M14, H3):**
- Strict listbox read-back (button text equals the option, then no field error after blur).
- A search miss clears the typed text (prompt, combobox, react-select).
- `reset_field` reports ok only when the read-back is empty; a radio group reports "unsupported".
- A file input showing another file is emptied first.
- Dates are filled by section role, and a month is never guessed.
- Pills and chips: wrong ones are removed first.

**`shown_contains` (TR-1):**
- Correct for the cases checked: case-insensitive substring of 3+ characters; a phone matches by digits with or without `+65` or spaces; a postal code inside an address matches.
- Its only false positives withhold more than needed, which is the safe direction.

**H7 keys:** the reader keeps an element's existing `data-llmfill` mark across reads, so a re-read gives new keys only to fields that appeared (caveat in F6).

**Layering:** `accounts.py` imports only `contracts`. `page`/`widgets` import `browser`/`contracts`. `greenhouse.py` imports `..page` lazily (same stage). `apply_flow` (the orchestrator) imports `vault`, `mail` and `accounts`. No SQL outside `store.py` and no model call.

## Findings

### F1 HIGH: widgets accept a different option than the one decided, with no model and no guard
`widgets.py:432-447` (`_react_pick` calls `_match(..., contains=True)`); `widgets.py:131-137` (`fill_field` compares the read-back with `chosen`, not with `value`).

- **Why:**
  - LF §6.4 LL3 and review M14 say a searchable list takes an exact match, else `pick`. "A typeahead/combobox that selected another suggestion is `fill_failed`."
  - `_react_pick` instead takes "the only option containing the words" deterministically.
  - `fill_field` then checks the page against the option it chose, so `fill()` returns True although the page shows something else than the guarded value.
  - The `fill()` docstring promises the opposite.
- **Failure scenario:**
  - Greenhouse's searchable "Discipline" or "School" react-select. The guarded value is "Computer Engineering".
  - The search returns only "Computer Engineering Technology", so the contains-match picks it. The read-back equals the chosen option, and `ok=True`.
  - In `auto` mode the employer receives a discipline the applicant didn't study. "Java" → "JavaScript" is the same pattern.
- **Fix:**
  - Drop `contains=True` and fall through to `pick`.
  - In `fill_field`, require `same(pf, shown, value)` unless the option came from `pick`. Have the family report that, e.g. `(chosen, via_pick)`.
- **Tester:** a react-select stub whose only result contains the wanted words → `fill_failed` (`search_miss`), and `pick` is called.

### F2 MEDIUM: Workday `next_step` clicks a nav button with an empty label unless the step id is "review"
`workday.py:715-718`.

- **Why:** the check is `SUBMIT_ANY.search(label) or (not label and step == "review")`.
- **Failure scenario:** `_text` returns "" (text in a pseudo-element or icon) and `step_id` fails to read the progress bar (the label is in a hidden span the JS misses). On the review page this is the one path where Next could click Submit without `submit_clicked_at`.
- **Fix:**
  - Check `self.submit_ready(page)` first and return `is_review`.
  - An empty label → `PAGE_UNRECOGNISED` (fail closed) unless the button's `aria-label` matches `NEXT_NAME`.

### F3 MEDIUM: no test pins the Workday gate
`apply_flow.py:794`.

- **Why:** the existing `unsupported_ats` tests use an unknown provider. Nothing asserts that a `provider: workday` job ends `unsupported_ats` with `factory.started == 0`. Nothing asserts there are no vault or `ats_accounts` writes.
- **Risk:** this is the only thing stopping live Workday runs before N6a.
- **Tester:** add that oracle, using the real `REGISTRY`.

### F4 MEDIUM: the Greenhouse security-code path is live but its happy path is untested
`apply_flow.py` `code_after_submit`.

- **Why:** the only test is the "mailbox not set up" note.
- **Tester oracles:**
  - mail set up, a code arrives → `enter_code` once, a second `submit` once, then `submitted`;
  - a second `code_required` → `submitted_unconfirmed`, and `code_resubmits == 1`;
  - the IMAP wait does not consume the deadline;
  - no code value in the log.

### F5 MEDIUM: the Greenhouse `pre_import` keys don't match the reader's audit keys (M3 silently off for some fields)
`greenhouse.py` `_snapshot_pre_import` (`form:` + html id) vs `page.py:597-609` `AUDIT_IDS_JS`.

- **Why:** the reader's audit key prefers a `data-automation-id`, then `name`, then the id. For radio and checkbox groups it uses the first input's `name`.
- **Effect:** where those differ, `read_page` never finds the pre-import value. A site default after the MyGreenhouse click is then labelled `mygreenhouse`, and G8 trusts it.
- **Fix (in N6a):** take the snapshot with the generic reader itself, `page.read_page(page, options=False, step="form")` plus `page.audit_keys(..., "form")`, before the click, so both sides use one key function.

### F6 MEDIUM: H7 key stability depends on DOM attributes surviving re-renders
`page.py:21-25`, `read_page(known=...)`.

- **Why:** `known` (origin OURS) is keyed by the reader key, which lives in a `data-llmfill` attribute. If React re-creates an element after our fill, the re-read gives it a new key:
  - our own value comes back with the import's origin;
  - it is shown to the model as `current`, which LF §3.3 forbids;
  - G9 may clear a correct value;
  - `audit_keys` `#n` numbering can also shift when a revealed field appears between two repeats.
- **Fix (in R3):**
  - Keep origins and audit keys per field by audit key (site id) as a fallback.
  - Compute a field's audit key once, the first time it is seen.

### F7 MEDIUM: N6a integration order on Workday
`apply_flow.py` opening block (`account_wall` right after `open`); `check_email` reopen.

- **Why:**
  - On Workday the Start Your Application dialog comes first. The Create Account / Sign In form is wizard step 1 *after* `choose_entry` (S-5). So `account_wall` right after `open()` sees nothing.
  - `check_email`'s `adapter.open()` reopens the posting and lands on the dialog again.
- **Fix (N6a "Done when"):** open → `choose_entry` → account wall / `account()`. After an email-check reopen, call `choose_entry` again. Add a flow oracle.

### F8 MEDIUM: `accounts export-edge --confirm` marks rows it didn't export
`cli.py` (export-edge confirm branch).

- **Why:** it marks every not-yet-exported account that has a vault password, recomputed at confirm time.
- **Failure scenario:** an account created between the export and `--confirm` is marked "imported into Edge" but was never in the CSV. The owner never gets it in Edge (F-35).
- **Fix:** mark exactly the (host, email) rows listed in the newest export before deleting it.

### F9 MEDIUM (design gap the code exposes; lane M / R3): an LL3 pick happens after the guards
`widgets._match` with `pick`.

- **Why:** for search-driven lists the `pick` call runs inside the widget at fill time, so the picked option never meets G4 (option vs evidence or fact text).
- **Fix (in R3):** run the G4 check on a picked option (or on the read-back) before accepting it; a failure → `fill_failed`, or unknown if required.

## Notes (no action needed)
- **Enter on Workday:** if a tenant wraps the wizard in a `<form>` with untyped buttons, Workday prompt searches won't get Enter and end `search_miss`. That fails closed; check it on the `wd_a` fixtures and the first dry run.
- **Lane M:** `facts.s_values` should add the MM/DD/YYYY date of birth (Workday shows US order). `redact` relies on that list, and `shown_contains` matches only the formats it is given.
- **`fill: llm` default:** it is in config but nothing reads it yet. The Greenhouse path changes only when N6a lands.

## Suite
In the worktree at 1c4bf89, with the tester's uncommitted files present:

- `python tests/run_tests.py` printed `869/869 passed` (exit 0).
- `-k layering` printed `10/10 passed`.
- Oracles still waiting on unbuilt modules are skip-clean (for example `test_apply_mail` waits on `workday:choose_entry`).
