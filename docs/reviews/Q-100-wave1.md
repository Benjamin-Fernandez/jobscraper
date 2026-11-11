# Q-100 Wave 1 review (stage G): UI overhaul and Connected accounts hub

- **Reviewer:** reviewer, 2026-11-12. **Branch:** `int/Q-100-BC` @ b9fa9c2 (lane 0 + A already on `personal` at 52dc166; lanes B and C merged on the int branch).
- **Diff:** `git diff 3be4daa..int/Q-100-BC -- src/jobscraper/web/connections.py src/jobscraper/web/routers/connections.py src/jobscraper/web/api.py src/jobscraper/backends.py web/src` (28 files, +3360/-148).
- **Spec:** `docs/architecture/q100_ui_design.md` (READY, D-194, §9), ADR-0009, D-190..D-197, `Q-100-ui-audit.md`, `Q-100-design-review.md`.
- **Skills:** engineering:code-review, design:design-critique, design:accessibility-review (WCAG 2.2 AA).

## Verdict: FIX FIRST (one HIGH, a one-line fix)

Everything else is ready for merge. The backend matches §2.3/§3 row by row. No secret or path reaches the browser. Layering holds, and peer-owned files are untouched (MailCard changes only through the approved `embedded` prop). State persists across a restart. The HIGH is the "See how to fix" command for employer accounts: as written it fails every time. That line is the only Wave 1 way to fix the audit's P0 item.

## Evidence

| Check | Result |
|---|---|
| `python tests/run_tests.py -k layering` | `13/13 passed` |
| `python tests/run_tests.py -k connections` | `32/32 passed` |
| `python tests/run_tests.py -k backends_probe` | `21/21 passed` |
| `cd web; npx vitest run` | `Test Files 43 passed (43)`, `Tests 966 passed \| 1 skipped (967)` |
| Peer-owned paths (`mailstatus/`, `apply/`, `routers/apply.py`, `routers/mail.py`, `store.py`, `Inbox.vue`, `Runs.vue`, `Companies.vue`) in the range | empty diff |
| `/api/connections` body scan (live-copy DB, plus 3 dummy employer rows and a dummy mailbox username) | no `Users`/`AppData` path, no `vault_service`, no `password` key, no Ollama URL |
| Rendered DOM scan (hub, 1440 and 390) | no Windows path, no vault service name |
| Restart (stop 8768 by PID, start again on the same DB copy) | every item's state and code is identical before and after; the model is `checking · probing` on the first GET, then `connected` (the §3.3 cold start) |
| Browser pass | SPA built into a scratch outDir (`vite build --outDir`); `create_app(static_dir=<scratch>)` on 8768 (DB copy plus dummy rows) and 8769 (empty DB), `JOBSCRAPER_MAIL_SYNC=0`; Edge headless 1440/390, light and dark; 25 screenshots in the session scratchpad `q100w1/shots` (they show the owner's mailbox address: never commit) |

The dummy rows were three `ats_accounts` rows on made-up tenants (signin_failed, verified with no vault entry, creating) and `apply.mail.username` set to a placeholder address. They exist only in the scratch copy.

## Findings

### HIGH

**H1. The employer-account fix command is rejected by the CLI.** `web/src/components/EmployerAccounts.vue:26` builds `python -m jobscraper accounts add --url https://${row.tenant_host}/ --email …`. `cli._account_tenant` (`cli.py:1090`, through the Workday navigator's `match_url`) returns `None` for a bare host. Checked: `https://<tenant>.wd3.myworkdayjobs.com/` gives `None`, while `…/careers` and `…/en-US` give the tenant. The owner runs the line shown under "See how to fix" and gets `accounts add: not the URL of an ATS that needs an account` (exit 2). For signin_failed, exists_no_password and password_missing, that line is the only remedy Wave 1 offers (audit A1, P0). The spec's own example (§4.1, `…myworkdayjobs.com/ --email`) has the same defect. **Spec disagreement:** the spec's intent ("shows the exact CLI line") wins over its example.
- **Fix:** any site path works, because `accounts add` keys on `tenant.host` only (`cli.py:1159-1170`). For example: `--url https://${row.tenant_host}/careers`.
- **Also required:** a pin that the rendered command parses through `_account_tenant`, either in Python over the hub's command template or as a vitest literal plus a Python row, and a correction to the §4.1 example. Screenshot: `04-employer-fix-open-1440.png`.

### MEDIUM

**M1. The CLI lines only work from the project folder with `PYTHONPATH=src`.** Affected: `ConnectionsHub.vue:77-79` and `EmployerAccounts.vue:26`. Each command starts `python -m jobscraper …`, but jobscraper isn't installed (`pip show jobscraper`: not found). Pasted into a new terminal, it fails with `ModuleNotFoundError`. The note says only "Run this in a terminal". **Fix:** say "In the JobScraper folder, run" and use `.\run.ps1 accounts add …` / `.\run.ps1 mail set-password …`. `run.ps1` sets the folder and `PYTHONPATH`. The existing `apply/contracts.py` hints share the convention, so the copy change belongs in the hub only. Follow-up; it can ride with H1.

**M2. A backup mailbox with the same username as the primary is counted twice.** `web/connections.py:215-220` always emits `apply-mailbox:backup` when a backup username is set, even when `separate` is false (same user and host). It then asks the vault the same question as the primary item. If the password is missing, two attention items appear: the badge reads 2, the banner says "2 connections need attention", and the hub shows the backup card (`ConnectionsHub.vue` `backupShown`). That is one problem shown as two. **Fix:** when `not separate`, give the backup item `not_set_up · none` (or drop it). Add a T1 row.

**M3. A stuck in-flight attempt makes Local AI "needs attention" for good.** `need_reason` rule (b) (`web/connections.py:334`) is true while `store.attempts_in_flight()` holds any non-terminal attempt. After a crash that leaves an attempt in `filling`, an Ollama that is down shows "Ollama isn't running, and an application is waiting for it" with an amber badge, until something finishes that attempt. This follows the spec rule (b) exactly. Raised as a spec gap: bound (b) by recency (for example, `started_at` within 24 h, as rule (c) is), or confirm that the apply startup sweeps stale attempts. Not reproduced: the DB copy has 0 attempts.

### LOW

- **L1. 1440 employer table.** Hosts and emails break mid-word ("…myworkdayjobs.co / m", "you@example.co / m"). The hub column is about 735 px wide while about 450 px to the right stays empty, with the view tabs floating top-right (`02-hub-1440-light.png`). Let the hub card use the page width at ≥ 1024 px, or `overflow-wrap: break-word` with `word-break: normal` on `.cell-site`/`.cell-email`.
- **L2. `.cell-status { display: flex }` on a `<td>`** (`EmployerAccounts.vue`, scoped CSS). It renders acceptably in Edge, but it takes the cell out of table layout. Wrap the contents in a div instead. At 390 px the state chip stretches the full row width (`02-hub-390-dark.png`).
- **L3. Overview "Your last run failed".** It prints the raw stored reason ("Reason: cancelled (killed).") because `Overview.vue:88-90` only special-cases an exact `cancelled`. Match `startsWith('cancelled')`. An error reason is printed raw and could carry a local path. It is local-only, but consider trimming it to the first clause.
- **L4. Small targets at 1440.** The 32 px targets are "See how to fix" (`<summary>`) and "See status changes from email". They meet WCAG 2.5.8 (≥ 24 px). Under 640 px every hub control measured ≥ 44 px. Pass.
- **L5. "Later" in setup.** It is a link-style button at the far right of the "Apply for me" heading, and it reads like a label (`01-overview-banner-1440-light.png`). Optional: put it next to the part title as a ghost button.

## Spec conformance (§1-§5)

- **§1 routes:** pass.
  - The hub deep link `#/settings/accounts/employer-accounts` scrolls to the card and focuses `conn-title` "Employer accounts". `…/model` focuses "Local AI".
  - `#/settings/bogus/x` becomes `#/settings/accounts`, and `#/nope` becomes `#/overview`.
- **§1 shell signals:** pass.
  - The Settings badge is amber, with the hidden label "need attention". The Accounts view tab has `aria-hidden` digits plus a hidden "2 need attention".
  - The banner reads "2 connections need attention. [Review] [Dismiss]". It is `role=status`, hidden on Accounts and shown on Apply/Search/Overview.
  - The mode chip is hidden on dry_run.
  - Cadence: boot, `onFinish`, visible after 60 s, and leaving Settings. The hub polls 30 s, then 3 s up to 5 times.
- **§2.1-§2.3:** every mapping row matches. D-195 (2)/(4)/(5) and D-196 are applied.
  - Attention counting: the server count holds, and the client applies the 2-failure rule and `need_now` for the model.
  - `check_failed` carries fixed copy, and logs record the exception type only.
  - Edge sends no path. `in_use` comes from the web apply job or the lockfile test.
- **§3:** pass.
  - `GET` is read-only: no IMAP, runner status only, vault answers as booleans. The store is closed in `finally`. 503 `{code: unavailable}`. `no-store`.
  - The probe: one lock, `in_flight` set inside the lock and cleared in `finally`, a daemon thread, `/api/tags` with a 5 s cap, the client closed (`_owns_http`). `off`/`misconfigured` are read from config without a thread. `POST …/model/check` returns 202 and sits behind `CrossSiteWriteGuard`.
- **§4.1 hub:** matches the wireframe. One Gmail header; MailCard embedded (h3 hidden, "Connect another Gmail" fold with focus in and out). Verified / Not verified. The "No account needed" note and the Credential Manager hint are present. Gmail → Applications link. The command defect is H1.
- **§4.2 setup:** the two parts work. Empty DB: "Find jobs 0 of 4 · Apply for me 1 of 2". Optional steps are not counted. The browser line is a note. The resume href is `#/profile/resume` (A6). The all-failed state shows "Couldn't check your setup just now. Try again" (A7). `14-firstrun-*.png`.
- **§4.3 Apply:** shows Mode (from `/api/apply/status`), the Application mailbox chip with "Manage in Accounts →", and Ready to apply (15 labels, Fill in details, Open Inbox). Limits, human checks and cover letters are hidden because `/api/apply/settings` is absent (Q-111 not merged), as specified. `05-settings-apply-1440.png`, `11-settings-apply-390.png`.
- **§5:**
  - A12, A10, A15: copy present.
  - A13: row actions 32 px at 1440 and 44 px at 390. Remove comes last after a rule and asks first. Focus goes to Keep, and back to Remove on Keep.
  - A14: the bottom bar works. More is a modal `dialog`; focus lands on the first item, and Esc returns focus to More. The Profile save bar sits exactly on the bar (bottom 788 = nav top 788); the toast is 24 px above it (`12-profile-savebar-dirty-390-*.png`, `10-profile-savebar-toast-390.png`; the toast was injected into `.toast-region` for the layout check only).
- **Wave 1 lanes:** files match §8. `api.js` changes only the `request` export.

## Audit P0/P1 status

| Audit | Status |
|---|---|
| A1 P0 employer accounts invisible, CLI-only | **Partly fixed.** They are visible, with state, verified flag and last sign-in. The CLI fix line is broken (H1); the in-app fix waits for W2 G2 |
| A2 P1 Edge profile has no surface | Fixed for W1: Apply browser card (Ready / In use / not set up, last used). "Open apply browser" is W2 G6 |
| A3 P1 no model health | Fixed: Local AI card, cached probe, Check again, need_now rule |
| A4 P1 setup covers search only | Fixed: "Apply for me" part |
| A5 P1 auto-apply mode invisible / can't start | Partly fixed: mode visible (Apply view, chip when auto). Switching waits for Q-111 `writable`, as designed |
| A6 P1 Upload lands on Application details | Fixed (`#/profile/resume`, `#/profile/details`) |
| A7 P1 API failure shows onboarding / all caught up | Fixed: "Couldn't check" per step, all-failed line; the hub load error has Try again |
| A13 P1 row actions 18 px | Fixed (32 px desktop, 44 px phone; confirm before Remove) |

## Accessibility notes (WCAG 2.2 AA)

- **Chip contrast:** Connected 5.33:1, Needs attention 5.31:1, Not confirmed 9.93:1 (light, measured). The dark chips read clearly in screenshots.
- **1.4.1:** every chip and the banner state the problem in words.
- **Target size:** pass (L4).
- **Focus:** deep links, the More sheet, the Remove confirm and the MailCard fold all move and return focus correctly.
- **Live regions:** the banner is `role=status`, always in the DOM.
- **Tables:** the employer table has a hidden caption and `th scope`, and becomes labelled blocks at 390.
- No blocker found.

## Next step

Lane B: fix H1 (`EmployerAccounts.vue:26`) with a pin, and preferably M1's copy in the same change. Tester: one T1 row for M2. Architect: record the §4.1 example correction and the M3 rule-(b) recency question. Then MERGE; M2/M3/L* can follow as Q-100 follow-ups.
