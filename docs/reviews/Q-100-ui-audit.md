# Q-100 · UI audit: first run, connected accounts, whole-app pass (reviewer, 2026-11-11)

Read-only audit of `personal` @ 679c541 for the Q-100 UI overhaul (D-190). Builds on
`docs/reviews/Q-70-ux-audit.md` (G/N items) and `docs/reviews/Q-71-details-form-audit.md`; those
findings are not repeated. Skills: design:design-critique, design:accessibility-review (WCAG 2.2 AA).
Severity: **P0** blocks a core job or hides a failure that costs an application · **P1** hurts first
run or the daily loop, or fails WCAG AA · **P2** clear friction · **P3** polish.

## 1. Summary

The daily loop (Inbox → Applications) is in good shape after Q-70; the gaps are at the two ends.
**First run** is a four-step checklist that knows only resume, titles, companies and a run
(`web/src/setup.js:6-28`). The things auto-apply needs (application details, the AI model, the
Edge apply profile, employer accounts, Gmail) are not steps, and its first button lands on the wrong
sub-view. **Linked things** have one UI surface: the Gmail card in Settings. Employer (ATS)
accounts, the Edge profile and its sign-ins, Ollama health and the `doctor` checks are all
invisible in the app; ATS accounts and the Edge profile can only be inspected or repaired from the
CLI, and the error an apply attempt shows tells the user to run a CLI verb. Everything that matters
does persist across a restart (DB rows, Credential Manager, the on-disk Edge profile,
`jobs/current.json`), so the hub can be built on existing state without new storage. At 390px the
app is usable but the section nav hides five of eight tabs and Applications row actions are 18px.

## 2. How to reproduce

```bash
# from the repo root (bash). Reading data/ is fine; nothing is written there.
Q=<scratchpad>/q100; cp data/jobscraper.db $Q/jobscraper.db
JOBSCRAPER_DB=$Q/jobscraper.db JOBSCRAPER_PORT=8768 JOBSCRAPER_MAIL_SYNC=0 PYTHONPATH=src python -m jobscraper web &
# first run: a copy of config/config.yaml whose profile, overrides, resume_dir, db, shortlist,
# applicant, master_resume and tailored_dir point into an empty $Q/first
JOBSCRAPER_CONFIG=$Q/first/config.yaml JOBSCRAPER_DB=$Q/first/jobscraper.db JOBSCRAPER_PORT=8769 \
  JOBSCRAPER_MAIL_SYNC=0 PYTHONPATH=src python -m jobscraper web &
python $Q/scripts/shoot.py $Q 8768 dev overview,inbox,applications,runs,companies,profile,settings,developer 1440,390
python $Q/scripts/shoot.py $Q 8769 first overview,inbox,applications,runs,companies,profile,settings,developer 1440
python $Q/scripts/extra.py $Q      # focus, `?` sheet, every /api call forced to 500, 390px detail + mail card
python $Q/scripts/measure.py       # target sizes, table overflow
```
Playwright, `channel="msedge"`, headless, wait 2.5 s per tab, full-page. Nothing was clicked that
uploads, connects, starts a job or contacts an employer. Both servers stopped by PID (§6).

## 3. Accounts and connections map

| Thing | Where shown in UI | Actions in UI | CLI-only actions | Survives restart? | Gaps |
|---|---|---|---|---|---|
| **Gmail** (`mail_accounts` row + `jobscraper:imap:<host>` vault entry) | Settings → Email card (`MailCard.vue`) | connect (address + app password + consent), on/off toggle, Check now, Change app password, Disconnect, "use for apply" offer | `mail accounts list/add/set-password/on/off/remove`, `mail test`, `mail set-password` | Yes: row in DB, password in Credential Manager, 10-min timer restarts with the app (`web/api.py:241`) | Only "Checked N days ago"; no next-check time, no "timer off" state when `JOBSCRAPER_MAIL_SYNC=0` (A9); connect form always open under a connected box (A8) |
| **ATS accounts** (`ats_accounts` table + `jobscraper:<ats>:<host>` vault entries) | Nowhere. No `/api` route reads `ats_accounts` (route list in `web/routers/*`) | none | `accounts list`, `accounts add --url --email` (stores a password, resets a `signin_failed` row), `accounts export-edge [--confirm]` (`cli.py:1105-1206`) | Yes: DB + Credential Manager | Status (`signin_failed`, `exists_no_password`), created-by-attempt, last sign-in: all invisible; the attempt error text sends the user to the CLI (`apply/accounts.py:26-31`) (A1) |
| **Edge apply profile** (`apply.profile_dir`, default `%LOCALAPPDATA%\JobScraper\apply-profile`; holds cookies such as a MyGreenhouse sign-in) | Nowhere | none | `apply open-profile [URL]` to sign in by hand (`cli.py:1511-1515`) | Yes: a persistent user-data dir (`apply/browser.py:74-86`) | No "signed in to X" list, no open/clear, no "profile in use" warning until an attempt fails on the lock (`apply_flow.py:1696`) (A2) |
| **Ollama / model** | Only as failure text: Profile resume refresh (`ResumeRefresh.vue:157`), title recommendations (`TitleEditor.vue:31`) | none | `doctor` prints `model OK/UNAVAILABLE` (`cli.py:121-126`) | n/a (external service) | No health dot, no model name, no "start Ollama" guidance before an action fails; runs silently queue survivors (A3) |
| **Doctor checks** (watchlist, profile, DB, model, privacy, budget, batch) | Nowhere | none | `doctor` (`cli.py:92-141`) | n/a | Doctor itself lacks Edge, Credential Manager/keyring, mailbox and Playwright checks (A4) |
| **Apply start / mode** | Applications attempt pills (`attempts.js`); Questions "retry" (`routers/questions.py:294`) | retry after answering questions only | `apply JOB_ID… [--dry-run]`, `apply show` | attempts in DB | Apply mode (`dry_run`/auto) and how to start a first attempt are not in the UI (A5) |
| **Background job + log** | Developer tab, Runs tab | Start run, Cancel | — | Yes: `jobs/current.json` beside the DB (`web/jobs.py:9-16`) | Copy "Nothing has run since the web app started" reads as if a restart wipes history (P3, in A15) |

## 4. Findings

**A1 · P0 · Employer accounts are invisible and only fixable from the CLI.** Screen: none exists
(Settings `dev-settings-1440.png` has only Email). Evidence: no `/api` route for `ats_accounts`;
`apply/accounts.py:26-31` puts "add the password with `accounts add`" into a user-facing failure
detail. Failure: an attempt stops LOGIN_FAILED on a tenant; the user sees a pill and a CLI hint, has
no list of which tenants have accounts, which email each uses, or which are locked out.
Pro apps: a "Connected accounts" list with per-row status and Reconnect (1Password, Zapier).
Fix: Settings → Connected accounts → "Employer sites" table (ATS, tenant, email, status pill,
last sign-in, created by an attempt / by you); row actions "Add password" (web form → `vault.put`,
reset row, the `accounts add` path), "Export to Edge", "Forget". Never return the password.

**A2 · P1 · The Edge apply profile and its sign-ins have no surface.** Evidence: `apply/browser.py:74-86`,
`cli.py:1511`. Pro apps: "Signed-in services" with Open / Sign out (Zapier, Make). Fix: a row in the
hub: profile path, last used, "Open the apply browser" (starts `apply open-profile` as a background
job, with the same one-job lock), "in use" state when the lock is held, and a plain note that the
user signs in by hand (no bot-check handling).

**A3 · P1 · No model (Ollama) health anywhere.** Evidence: grep finds Ollama only in failure copy
(`ResumeRefresh.vue:157`); doctor has the check (`cli.py:121-126`). Failure: the user starts title
recommendations or an apply with Ollama stopped and learns it from a red box after the job.
Pro apps: a status indicator in the header with a details popover (VS Code, Docker Desktop).
Fix: `GET /api/health/model` (backends.describe / unavailable_reason, cached ~30 s); a small status
dot in the header and a hub row; disable model-only buttons with the reason.

**A4 · P1 · First-run checklist covers search only, not apply.** Screen: `first-overview-1440.png`,
`first-inbox-1440.png`. Evidence: `setup.js:6-28` (4 steps). Missing: application details
(15 required, `first-profile-1440.png`), AI model, Gmail (optional), apply browser / accounts
(optional). Pro apps: a setup checklist split into "required" and "recommended" with health.
Fix: two groups: "Find roles" (current 4) and "Apply for you" (details, model, apply browser,
Gmail optional); each step reads its state from the hub endpoints; add the doctor checks as a
"Check setup" button.

**A5 · P1 · Auto-apply cannot be started, and its mode cannot be seen, in the UI.** Screen:
`dev-inbox-1440.png` (job actions: Apply on company site, Mark applied, Save, Not interested).
Evidence: route list has no apply-start route; only `questions/retry` (`questions.py:294`).
Pro apps: the primary action reflects the automation ("Auto-apply (dry run)"). Fix: show the
effective mode in Settings and on the job card; owner-triggered "Dry run this job" behind the
existing one-job lock. (Real submission stays an explicit owner action; spec scope, D-190.)

**A6 · P1 · "Upload" in the checklist lands on Application details, not the uploader.** Screen:
`first-profile-1440.png` (opens on "Application details (15)"). Evidence: `Profile.vue:147`
switches a first visit to details when anything is missing; the step links to `#/profile`
(`setup.js:9`). Fix: deep links `#/profile/resume` and `#/profile/details`; checklist steps use them.

**A7 · P1 · An API failure shows the onboarding and "all caught up".** Screen:
`x-api500-overview-1440.png` (established install shows "Get your first matches 0 of 4"),
`x-api500-inbox-1440.png` (error box above "You're all caught up", `Inbox.vue:461`).
Evidence: `SetupChecklist.vue:18-21` counts failed checks as not done. Pro apps: one app-level
"Can't reach JobScraper" banner and no empty state while data is unknown. Fix: when the shell's
own load fails, show one banner with Retry and suppress empty/setup states; per-card errors stay.

**A8 · P2 · Gmail card: a connected box and a full connect form stacked.** Screen:
`dev-settings-1440.png`, `x-mailcard-390.png`. Evidence: `MailCard.vue:495-550` always renders the
consent text, an unchecked "Read this mailbox for application updates" box, address and password
under the connected row with an "on" switch labelled "Read this mailbox". Two near-identical
controls with opposite states. Pro apps: connected list + "Add another account" button that
expands the form. Fix: collapse the form behind "Connect another Gmail" once one is connected.

**A9 · P2 · Connection state is not "health".** Screen: `dev-settings-1440.png` ("Checked 2 days ago",
switch on). Evidence: only `mail_status.enabled` is surfaced (`MailCard.vue:34`); the
`JOBSCRAPER_MAIL_SYNC=0` timer-off state and staleness are not (`cli.py:258`). Fix: per-row
"Healthy · last check 5 min ago · next in 5 min" / "Paused" / "Needs a new app password" with one
fix action; same row model for every hub entry.

**A10 · P2 · First-run copy tells the user to do a CLI step that is not needed.** Screen:
`first-runs-1440.png`, `first-settings-1440.png` ("sync the watchlist first"). Evidence:
`Runs.vue:241`, `Settings.vue:67`; a run syncs the watchlist itself (`pipeline.py:147`).
Fix: "No companies yet. Add some in Companies, or start a run to load the watchlist."

**A11 · P2 · Wrong empty state on an empty Companies tab.** Screen: `first-companies-1440.png`
("No companies match. Try another spelling, or clear the filters" with no filter set).
Evidence: `WatchedCompanies.vue:352`. Fix: a first-run empty state with "Add companies" and
"Load the watchlist".

**A12 · P2 · Developer and internal words in user copy.** Evidence: "There is no data/applicant.yaml
yet. Saving creates it." (`ApplicationDetails.vue:619`, `first-profile-1440.png`); "The choices come
from your plan (local)" (`Settings.vue:239`). Fix: "Nothing saved yet." / drop the plan line.

**A13 · P1 (a11y) · Applications row actions are 18px tall, 12px text.** Screen:
`dev-applications-390.png`, `dev-applications-1440.png`. Evidence: measured 51×18, 37×18,
144×18 px (`measure.py`); stacked with no gap (`Applications.vue:397-418`). Fails WCAG 2.5.8
(24px). "Remove from Applications" sits next to "Details" with no confirmation spacing.
Fix: one overflow menu (≥ 44px) or a row of icon+label buttons ≥ 32px; destructive item last.

**A14 · P2 (a11y/nav) · At 390px the section nav hides 5 of 8 tabs.** Screen: `dev-overview-390.png`
(Runs cut off; Profile, Settings, Developer off-screen). Evidence: `App.vue:412-421`
(`overflow-x: auto`, hidden scrollbar, fade mask). Pro apps: bottom tab bar of 4 + "More".
Fix: below 640px, a bottom bar (Overview, Inbox, Applications, More) with the rest in a sheet.

**A15 · P3 · Smaller items.** Overview "Your last run failed" gives no reason (`Overview.vue:181-183`,
`dev-overview-1440.png`); Runs history status has no reason column (`dev-runs-1440.png`).
Companies renders all 433 rows (page 40,914px tall, `dev-companies-1440.png`); paginate or
virtualise. Settings subtitle says only cycle and run size although the page also holds Email.
Inbox first run shows search, sort and run filters over zero rows (`first-inbox-1440.png`).
Developer "Nothing has run since the web app started" (`JobStatus.vue:21`) suggests restarts lose
history. Section nav uses `role="tablist"` for page navigation, so only the current tab is in
the Tab order (`App.vue:300-316`); acceptable, but a `nav` with links is simpler for SR users.

What works: page heads and empty states are consistent; error boxes carry Retry; the `?`
shortcut sheet and visible focus ring are good (`x-shortcuts-1440.png`, `x-focus-tab3-1440.png`);
no horizontal page overflow at 390px on any tab; Runs table scrolls inside its own box; muted text
#5d5c64 on #f5f5f2 is about 6.2:1.

## 5. Top-15 ranking (whole app)

| # | ID | Area | Why it ranks here |
|---|---|---|---|
| 1 | A1 | Accounts | P0: an apply failure the user can only fix from the CLI |
| 2 | A4 | Onboarding | setup ends before anything auto-apply needs |
| 3 | A3 | Feedback | model down is found only after a job fails |
| 4 | A2 | Accounts | the Edge sign-ins auto-apply depends on are invisible |
| 5 | A7 | Feedback | a server blip shows onboarding and "all caught up" (false state) |
| 6 | A5 | Apply | mode and start of auto-apply not in the UI |
| 7 | A13 | A11y 390 | WCAG 2.5.8 fail on every Applications row |
| 8 | A6 | Onboarding | step 1 lands on the wrong view |
| 9 | A9 | Accounts | connected is not the same as healthy; no staleness |
| 10 | A8 | Consistency | duplicate opposite-state controls on the Gmail card |
| 11 | A14 | Navigation | 5 of 8 sections hidden on a phone |
| 12 | A10 | Onboarding | copy asks for a CLI step that is not needed |
| 13 | A11 | Empty states | first-run Companies blames a filter |
| 14 | A12 | Copy | file paths and cloud "plan" words in user copy |
| 15 | A15 | Density/hierarchy | failed-run reason, 40k-px Companies list, idle filters |

Suggested shape for the overhaul: one `GET /api/connections` (Gmail rows, ATS account rows without
secrets, Edge profile state, model health, doctor checks) feeding both a Settings → Connected
accounts hub and the two-group setup checklist; each row = name, status pill, last checked, one fix
action. A1–A4, A9 and the A4 checklist then share a single component.

## 6. Screenshot index

Folder: `C:\Users\Admin\AppData\Local\Temp\claude\b3f57f5c5f0c763d\77276fa0-bc65-40c5-b0f3-890a4d8922db\scratchpad\q100\`
(never committed; the dev shots contain real names and an email address).

- Dev copy (8768), 1440 and 390: `dev-{overview,inbox,applications,runs,companies,profile,settings,developer}-{1440,390}.png` (16)
- First run (8769): `first-{overview,inbox,applications,runs,companies,profile,settings,developer}-1440.png`, `first-{overview,inbox,profile,settings}-390.png` (12)
- Extras: `x-focus-tab3-1440.png`, `x-shortcuts-1440.png`, `x-api500-{overview,inbox,settings,profile}-1440.png`, `x-inbox-detail-390.png`, `x-mailcard-390.png` (8)
- Crops used while reading: `crops/` (not evidence). Checks: `dev-checks.json`, `first-checks*.json`.
- Servers: 8768 PID 30096, 8769 PID 10272, both stopped with `taskkill /PID … /T /F`; afterwards
  `netstat -ano | grep 876[89] | grep -v TIME_WAIT` printed nothing.
