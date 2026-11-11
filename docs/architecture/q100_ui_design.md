# Q-100 design: UI overhaul and Connected accounts hub (D-190..D-192)

**Status: DRAFT for cross-review.** Architect, 2026-11-11. Inputs: `accounts_ux_current_state.md` (gaps G1–G12), `docs/research/ux_accounts_brief.md` (patterns P1–P23), `docs/reviews/Q-100-ui-audit.md` (A1–A15), ADR-0009 (D-191). Already decided and not reopened here: no app login and no app lock (D-190; the lock remains a future owner option, current-state §6); no secret goes from server to browser (D-191); starting auto-apply belongs to the peer lane Q-110 (D-192), and the hub links to the Inbox for it. Code claims cite `file:line` on `personal` @ 3fdb1e6.

## 1. Information architecture

**Decision: the hub is a Settings view, not a new tab.** Settings gets four views, switched like Profile's (`web/src/tabs/Profile.vue:91-113`): **Accounts** (the hub), **Apply**, **Search** (today's Cycle and Companies per run) and **Appearance**. Reasons:
1. The failure texts already send the owner to "Settings → Accounts" and "Settings → Apply" (`apply/contracts.py:169,175,193`). Naming the views exactly that makes those hints true without touching the peer-owned copy.
2. A ninth tab would worsen A14 (5 of 8 tabs already hidden at 390 px).
3. The owner rarely visits the hub. Visibility on arrival comes from the nav badge and the shell banner (below), not from a tab. Home Assistant and GitHub Desktop both put this under Settings (brief §3).

**Routes and deep links.** `route.js` accepts `#/<tab>[/<view>[/<item>]]`. Today it accepts only `#/<tab>` and rewrites anything else to the first tab (`web/src/route.js:6-8`, `web/src/App.vue:55-59`).

| Hash | Lands on |
|---|---|
| `#/settings/accounts` | hub; `…/accounts/<item-id>` scrolls to that card and focuses its heading |
| `#/settings/apply` | Apply view (mode, limits, readiness, compose toggle) |
| `#/settings/search`, `#/settings/appearance` | today's sections |
| `#/profile/resume`, `#/profile/details` | Profile views (fixes A6; replaces the localStorage hand-off `Profile.vue:96-112,244-247` as the link mechanism, while the stored choice stays the fallback) |

Contract (lane C writes it, lanes B and C use it): `parseHash(hash, ids) -> {tab, view, item}`, `hashFor(tab, view?, item?)`, `useView(tabId, views, fallback) -> Ref<viewId>` (reads the hash, follows `hashchange`, writes with `history.replaceState`). `normaliseHash` keeps `view` and `item`.

**Nav attention badge.** The Settings tab shows the count of hub items whose state is `attention`. It uses a new tab field `badgeTone: 'attention'`, drawn amber with the label "need attention" for screen readers. The data comes from the shell (`connections.attention`), so `tabs.js` adds `badge: ({ connections }) => connections?.attention || null`. No badge when the count is 0 or the call failed.

**Shell banner (App.vue, under the masthead, above every tab; not in `Inbox.vue`).** It shows while any item is `attention`. One item: "**Gmail needs attention.** Gmail refused the app password. [Fix it]". Several: "**2 connections need attention.** [Review]" → `#/settings/accounts`. "Dismiss" hides it for the session (sessionStorage key = sorted `id:code` list), so a new or changed problem brings it back. It is hidden on `#/settings/accounts` itself. `role="status"`, not an alert.

**Refresh cadence (shell).** `GET /api/connections` runs at boot, after any background job ends (the `onFinish` hook, `App.vue:173-184`), and on `visibilitychange` → visible when the last load is older than 60 s. While the hub is open it polls every 30 s, and every 3 s (at most 5 times) while any item is `checking`. A failed load means no badge and no banner, never a false "all good".

## 2. One state vocabulary

| `state` | Chip | Colour | Meaning | Primary action |
|---|---|---|---|---|
| `connected` | Connected | green | works, last check good | none, or Check now |
| `attention` | Needs attention | amber | the owner must act; the line says why | the fix |
| `not_set_up` | Not set up | grey | never configured (optional items say "Optional") | Set up / Connect |
| `paused` | Paused | grey, outline | the owner switched it off; history kept | Switch on |
| `checking` | Checking… | neutral | first probe not answered yet | none |

Setup steps (§4.2) use the same enum and draw it as done (`connected`), to do (`attention`/`not_set_up`) or "Couldn't check" (call failed). `doctor` will use the same words later (§3.4).

**Mapping (server computes `state` and `code`; the client maps `code` to copy, §4.4):**

| Thing | Stored fact (source) | state · code | Primary action (Wave) |
|---|---|---|---|
| Gmail row | `enabled = 0` (`store.py:335`) | paused · `switched_off` | Switch on, in MailCard (W1) |
| | `consent_version ≠ CONSENT_VERSION` (`web/routers/mail.py:133`) | attention · `consent` | Review and confirm, in MailCard |
| | `state = paused`, code `login_refused` / `app_password_required` / `web_login_required` / `not_set_up` (`mailstatus/contracts.py:30-34,364-369`) | attention · same code | Update app password, in MailCard |
| | `state ∈ {error, backoff}` and `last_ok_at` within 24 h | connected · `retrying` | none; the line gives `retry_after` |
| | same, but `last_ok_at` older than 24 h or null | attention · state_code | Check now, in MailCard |
| | `state = ok` | connected · `ok` (`timer_off` when the runner's `next_at` is null, `web/mailsync.py:286-291`; A9) | none |
| Gmail (none) | no `mail_accounts` rows | not_set_up · `none` (optional) | Connect Gmail |
| Application mailbox | host+username set, vault entry present (`vault.get`, as `web/routers/mail.py:96-108`) | connected · `ok` | none (Test: W2) |
| | username set, no vault entry | attention · `no_password` | W1: shows the CLI command; W2: Enter app password |
| | username unset | not_set_up · `none` (optional: "only for sites that email a code") | W1: CLI command; W2: Set up |
| Employer account (per `ats_accounts` row, `store.py:217-227`) | `created`/`verified`, `has_password`, `last_signin_ok ≠ 0` | connected · `ok` / `verified` | none |
| | `signin_failed` (`apply/contracts.py:617`) | attention · `signin_failed` | W1: CLI; W2: Enter the password / Open sign-in page |
| | `exists_no_password` (`:619`) | attention · `exists_no_password` | same |
| | `created`/`verified` without a vault entry | attention · `password_missing` | same |
| | `creating` / `unknown` (`:614,618`) | connected · `unconfirmed` | none (the next attempt signs in, `apply/accounts.py:63-65`) |
| Employer accounts (summary) | worst row state; 0 rows → not_set_up · `none` (optional) | — | View accounts |
| Apply browser | job manager says an `apply` job is running (`web/jobs.py:347-350`) | connected · `in_use` | none |
| | `profile_dir` exists (`config.py:104`, expanded as `apply/browser.py:74`) | connected · `ok` | W2: Open apply browser |
| | dir missing | not_set_up · `none` (optional: "created the first time an application runs") | W1: CLI; W2: Open apply browser |
| Local AI | probe true (`backends.py:120-145`) | connected · `ok` | Check again |
| | probe false, Ollama unreachable | attention · `unreachable` | Check again |
| | probe false, model not pulled | attention · `model_missing` | Check again |
| | no cached result yet | checking · `probing` | — |

Applicant completeness and the apply mode are **not** hub items. Per addendum 2 they come from Q-110's `GET /api/apply/status` (§4.3); see open question Q1.

## 3. `GET /api/connections` (read-only, no secrets)

### 3.1 Schema (v1; the JSON is the contract between lanes; the tester writes a sample fixture from it first)

```jsonc
{
  "version": 1,
  "checked_at": "2026-11-11T09:12:00",          // UTC, store.TIME_FMT
  "attention": 1,                               // items with state "attention": the nav badge
  "apply_status": "/api/apply/status",          // reference only (Q-110); the UI calls it itself
  "items": [ {
    "id": "gmail:3" | "apply-mailbox" | "apply-mailbox:backup" | "employer-accounts" | "edge" | "model",
    "kind": "gmail" | "apply_mailbox" | "employer_accounts" | "edge" | "model",
    "state": "connected" | "attention" | "not_set_up" | "paused" | "checking",
    "code": "ok",                               // §2 codes; Gmail passes mail SyncCodes through
    "message": null,                            // Gmail only: account_view's message (peer copy)
    "optional": false,
    "stored_in": "credential_manager" | "edge_profile" | "this_pc" | null,
    "checked_at": null, "next_check_at": null, "last_ok_at": null, "retry_after": null,
    "facts": { }                                // per kind, below; never a secret or a derivative of one
  } ],
  "employer_accounts": [ {                      // one per ats_accounts row
    "id": 12, "ats": "workday", "tenant_host": "acme.wd3.myworkdayjobs.com", "email": "…",
    "status": "signin_failed", "state": "attention", "code": "signin_failed",
    "has_password": true, "created_at": "…", "verified_at": null,
    "last_signin_at": "…", "last_signin_ok": false, "exported_to_edge_at": null,
    "created_by_attempt": 41
  } ],
  "no_account_needed": ["greenhouse", "lever", "ashby"]
}
```

`facts` per kind: gmail `{address, enabled, shared_with_apply, counts}`; apply_mailbox `{host, port, username, has_password, backup_separate}`; edge `{exists, in_use, sync: bool, last_used_at}` (no path: it contains the Windows user name); model `{backend, model, local}`; employer_accounts `{total, attention}`.

### 3.2 Field sources (lane A; no new SQL, no edits to `store.py`, `applicant.py`, `facts.py`, `apply/` or `mailstatus/`)

| Field | Source |
|---|---|
| Gmail items | `store.mail_accounts()` (`store.py:2081-2085`) through `account_view` (`web/routers/mail.py:119-134`, imported read-only); `retry_after`/`fail_count` from the same row (`store.py:340`); runner `status()` / `timer_running` (`web/mailsync.py:137-139,281-291`) via `request.app.state.mail` |
| Application mailbox | `cfg.apply.with_settings(store.get_setting)` (`config.py:149-159`) plus `store.get_setting("apply.mail_backup.username")` (same as `web/routers/mail.py:88-93`); `vault.imap_service` + `vault.get(...) is not None` (`vault.py:61-86`) |
| Employer accounts | `store.accounts()` (`store.py:1623-1625`); `has_password` = `vault.get(row["vault_service"], row["email"]) is not None` (ADR-0009: a boolean only) |
| Edge | `os.path.expandvars(acfg.profile_dir)` + `Path.is_dir()`; `in_use` = `app.state.jobs.current(tail=0)` has kind `apply` and state `running` (`web/jobs.py:347-350`); `last_used_at` = the max `started_at` in `store.last_attempts()` (`store.py:1431-1441`); `sync` = `acfg.edge_sync` |
| Model | the `ModelHealth` cache (§3.3) over `backends.build(cfg.budget)` (`backends.py:250`), `.available`, `.describe()`, `backends.is_local` (`backends.py:296`) |

Module split: `src/jobscraper/web/connections.py` (pure: `compose(cfg, store, mail_status, job_view, model_snapshot, vault_has) -> dict`, every mapping in §2, unit-testable with fakes) and `src/jobscraper/web/routers/connections.py` (routes). `web/` may import `store`, `config`, `backends`, `vault` and the contracts (`tests/test_layering.py:74-79`). No layering change is needed.

### 3.3 Model probe: never blocks a request

`backends.OllamaBackend._probe` makes a 5 s HTTP GET to `/api/tags` and caches the answer for the life of the instance (`backends.py:117,120-141`), so one instance can never notice a recovery. Design:
- `ModelHealth` on `app.state.model_health` (created in `create_app`, `web/api.py:253-263`) holds `{available, code, model, backend, local, checked_at}` behind a lock.
- `snapshot()` returns the cached value at once. When it is missing or stale (TTL **60 s** after success, **15 s** after failure), it starts at most one daemon thread. That thread builds a **fresh** backend (so the per-instance cache doesn't matter), reads `.available`, and stores the result. A request never waits; before the first answer the item is `checking`.
- `POST /api/connections/model/check` → 202 and a forced background probe ("Check again"). It writes no data, but it is a POST so `CrossSiteWriteGuard` applies.
- It only calls `/api/tags`. It never loads the model and never takes GPU time, so it is safe while an apply or a run is going.
- `code` comes from a new attribute `unavailable_code` (`"unreachable" | "model_missing"`), set next to `unavailable_reason` at `backends.py:128,135` (lane A; a foundation file, so no peer needed). `unavailable_reason` is never sent: it contains the URL.

### 3.4 Errors, limits, doctor

- Any one source failing (vault error, store busy) turns its item into `attention` with code `check_failed`. The response is still 200. A store that can't be opened gives 503 `{code: "unavailable"}`, like `/api/healthz` (`web/routers/health.py:22-31`).
- No caching of the whole response; it is cheap: 3 store reads and N+2 local vault reads.
- `doctor` should later print the same items through `connections.compose` (`doctor --json`). That is a follow-up (proposed Q-102), because `doctor` writes today (`cli.py:101`) and that needs changing first. It is not in Wave 1.

## 4. Screens

### 4.1 Settings → Accounts (the hub)

```
Settings
[ Accounts ● 1 ] [ Apply ] [ Search ] [ Appearance ]
Connected accounts
Everything JobScraper signs in to. Passwords stay in Windows Credential Manager on this PC.

┌ ✉ Application updates from email ─────────────── [Needs attention] ┐
│ Gmail refused the app password for you@gmail.com.                  │
│ Checked 2 days ago · automatic checks every 10 min                 │
│ ── MailCard, embedded unchanged (connect, switch, Check now, …) ── │
└────────────────────────────────────────────────────────────────────┘
┌ ⌂ Application mailbox ─────────────────────────────── [Connected]  ┐
│ Reads verification codes during applications. Also used for       │
│ updates.  Stored in Windows Credential Manager.                    │
└────────────────────────────────────────────────────────────────────┘
┌ ◫ Apply browser ───────────────────────────────────── [Connected]  ┐
│ Edge profile used only by JobScraper. Sign-ins are kept between    │
│ restarts. Last used today 09:02.          [Open apply browser]*W2  │
└────────────────────────────────────────────────────────────────────┘
┌ ◎ Local AI ────────────────────────────────────────── [Connected]  ┐
│ qwen3:14b on this PC · checked 1 min ago            [Check again]  │
└────────────────────────────────────────────────────────────────────┘
┌ ⚿ Employer accounts ─────────────────────────── [1 needs attention]┐
│ Site                         Email        Status          Last sign-in │
│ acme.wd3.myworkdayjobs.com  you@…        Needs attention  3 Nov, failed│
│   Sign-in failed. JobScraper won't try again, so the account        │
│   isn't locked.  [How to fix ▾]  (W2: [Enter password] [Open sign-in page]) │
│ globex.wd1.myworkdayjobs.com you@…       Connected        5 Nov        │
│ No account needed: Greenhouse, Lever, Ashby. They apply as a guest. │
└────────────────────────────────────────────────────────────────────┘
```
At 390 px the cards stack, and the table becomes one block per row (site, then email, then the status chip and line). In Wave 1 every "How to fix ▾" disclosure shows the exact CLI command in a `<code>` block, for example `python -m jobscraper accounts add --url https://acme.wd3.myworkdayjobs.com/ --email you@…`. Nothing is copied to the clipboard automatically.

### 4.2 First-run setup: two parts (A4, A6, A7)

```
Get set up                                                      5 of 9 done
Find jobs                       Upload your resume ✓ · Choose titles ✓ · Add companies ✓ · Run your first search ○
Apply for me (optional)  [Later]
  ○ Fill in your application details   3 missing        [Fill in details] → #/profile/details
  ○ Start the local AI                 Ollama isn't running        [Check again]
  ○ Apply browser                      Created on first use        (no button; info only)
  ○ Application mailbox (optional)     For sites that email a code [Set up] → #/settings/accounts/apply-mailbox
  ○ Email updates (optional)           Gmail                        [Connect] → #/settings/accounts/gmail
```
- `setup.js` keeps `setupSteps(facts)` for "Find jobs" and changes only the resume href to `#/profile/resume` (A6). A new pure function `applySteps({ connections, applyStatus })` builds part 2: details from `applyStatus.missing` (Q-110); the AI, mailbox, browser and Gmail items from `connections.items`. When `/api/apply/status` returns 404 (before Q-110 merges), the details step is left out. No error is shown.
- Where it shows: Overview, while there are no runs (`Overview.vue:136`) or while part 2 has an unfinished required step and isn't dismissed ("Later" = localStorage; Settings → Apply always shows readiness). The Inbox's existing slot is unchanged (addendum 1: Q-100 does not edit `Inbox.vue`).
- **A7:** `SetupChecklist.vue:19-21` currently counts a failed check as not done. New rule: a failed check marks its step "Couldn't check" (no tick, not counted in "n of m"). When **every** check fails, the checklist isn't drawn; it is replaced by "Couldn't check your setup just now. [Try again]". The Inbox "You're all caught up" shown under an error (`Inbox.vue:459`, condition lacks `!error`) is a one-token fix in a file Q-100 may not touch. It goes as a request to Q-110's owner (§6, R1).

### 4.3 Settings → Apply

```
Apply
Mode           Dry run · JobScraper fills each form and leaves it open for you. Nothing is sent.
Limits         10 applications a day · 2 per employer · browser window shown · no CAPTCHA wait
Ready to apply 3 things to fill in first: phone, resume file, work permit   [Fill in details]
               To start an application, open a role in the Inbox.          [Open Inbox]
Cover letters  [ ] Write a cover letter when a form requires one
               Off: JobScraper stops and asks you instead.
```
Q-100 owns this section's UI (`ApplySettings.vue` inside `Settings.vue`). The backend belongs to Q-110/Q-111 (addendum 3). Nothing about apply is duplicated in `/api/connections`.
- **Readiness**: `GET /api/apply/status` → `{mode, missing, busy}` (Q-110). Missing paths become labels through the Application details form schema (`GET /api/applicant` `form`, `web/routers/applicant.py:140`); an unknown path shows as is. On 404 the Ready row is hidden.
- **Mode and limits**: `GET /api/apply/settings` → `{mode, daily_cap, per_employer_daily_cap, headed, captcha_wait_s}` (Q-111, planned). On 404 the Mode and Limits rows are hidden. If only `/api/apply/status` exists, Mode comes from its `mode`.
- **Read-only → editable.** The section becomes editable only when the server says so. Request **R3**: Q-111's GET adds `"writable": true` once its PUT exists. The UI must **not** find out by sending a test PUT: writing the current values would put `apply.*` rows into `settings`, and those then override `config.yaml` for good (`config.py:149-159`). A PUT that answers 404/405 or 422 shows "Couldn't save: {detail}" and puts the controls back to read-only. When editable: Mode is a two-option radio. Switching to Automatic asks "Send applications automatically? JobScraper sends each one only after its final check passes, within your daily limits." [Switch to automatic] [Keep dry run]. The caps are number inputs (1–50) and the CAPTCHA wait accepts 0–600 s, checked on the client the same way as the server's 422. Starting an application stays in the Inbox (Q-110, D-192).
- **Compose toggle** (`apply.compose.enabled`, default off; handed over from eng/Q-45-compose). Write path: **R4** asks Q-111 to carry `compose_enabled: bool` in the same GET/PUT `/api/apply/settings`, so that every `apply.*` key has one owner and one validator. `settings.py` is the wrong home: it is the search-settings router, with a strict body of `batch_size`/`cycle_days` (`web/routers/settings.py:27-31,42-68`). Fallback if Q-111 declines: lane A adds a route to `routers/connections.py`, after the Q-45 merge, that writes only `store.set_setting("apply.compose.enabled", …)`. The row is hidden until the GET returns `compose_enabled`.

### 4.4 Copy (design:ux-copy: sentence case, verbs on buttons, what happened + how to fix)

| Context | Copy |
|---|---|
| Hub intro | "Everything JobScraper signs in to. Passwords stay in Windows Credential Manager on this PC; the app never shows them." |
| Gmail `timer_off` | "Automatic checks are off in this copy of the app. Use Check now." |
| Gmail `retrying` | "The last check couldn't reach Gmail. Trying again at {time}." |
| Gmail `check_failed` 24 h | "Gmail hasn't been checked since {date}. Check now to see why." |
| App mailbox `no_password` | "No app password is saved for {address}. Sites that email a code will stop at that step." |
| App mailbox not set up | "Optional. Needed only when an employer site emails you a code." |
| Employer `signin_failed` | "Sign-in failed. JobScraper won't try again, so the account isn't locked." |
| Employer `exists_no_password` | "An account already exists for this email, and JobScraper doesn't have its password." |
| Employer `password_missing` | "The password is missing from Windows Credential Manager." |
| Employer `unconfirmed` | "Not confirmed yet. JobScraper signs in with it next time." |
| Employer empty | "No employer accounts yet. JobScraper creates one only when an application on a Workday site needs it, and lists it here." |
| No account needed | "No account needed: Greenhouse, Lever, Ashby. They apply as a guest." |
| How to read a password | "To see a password, open Windows Credential Manager (Windows asks for your password first), or run `accounts export-edge` to import them into Edge." |
| Browser not set up | "Created the first time an application runs. Sign-ins you make there are kept between restarts." |
| Browser `in_use` | "In use by an application right now." |
| AI `unreachable` | "Ollama isn't running. Start it, then check again." |
| AI `model_missing` | "The model {model} isn't downloaded. Run `ollama pull {model}`, then check again." |
| AI `checking` | "Checking the local AI…" |
| Item `check_failed` | "Couldn't check this just now. Try again in a moment." |
| Hub load error | "Couldn't load your connections. [Try again]" (no chips are drawn) |
| Banner, one | "**{Name} needs attention.** {line} [Fix it]" · several: "**{n} connections need attention.** [Review]" · [Dismiss] |
| Setup all failed | "Couldn't check your setup just now. [Try again]" |
| Apply mode | dry run: "Dry run. JobScraper fills each form and leaves it open for you. Nothing is sent." · auto: "Automatic. JobScraper sends an application only after its final check passes." |

## 5. Other audit findings adopted (excluding Runs and Companies: Q-85/86/87)

| ID | Change |
|---|---|
| A9 | Gmail state, next check and timer-off are shown in the hub card header (§2), so MailCard stays unchanged |
| A12 | `ApplicationDetails.vue:619` → "Nothing saved yet. Saving keeps your details on this PC." · `Settings.vue:239`: drop "The choices come from your plan (local)" |
| A10 (Settings part) | `Settings.vue:67` → "No companies yet. Add some in Companies, or start a run to load your watchlist." (`Runs.vue:241` is left to the Runs lanes) |
| A13 | `Applications.vue:393-419`: the three links become buttons with `min-height: 2rem` (≥ 24 px, WCAG 2.5.8; 44 px under 640 px), a gap of `var(--space-2)`, and "Remove from Applications" last, after a divider, with a confirm ("Remove {company} from Applications? Its notes go too." [Remove] [Keep]) |
| A14 | Under 640 px the tab bar (`App.vue:296-331`, CSS `:412-421`) becomes a fixed bottom bar: Overview, Inbox, Applications, More. More opens a sheet (Runs, Companies, Profile, Settings, Developer, with their badges); the More button shows the sum of the hidden tabs' attention badges. Each item is ≥ 44 px, and the sheet is a `dialog` with focus return. Desktop is unchanged |
| A15 (part) | Settings subtitle → "Accounts, applying, search and appearance." · `JobStatus.vue:21` → "No job is running. Past runs are in the Runs tab." · Overview "Your last run failed" (`Overview.vue:181-183`) appends the run's stored reason when present |
| A1–A4, A6, A7 | §1–§4 |
| A5 | Read-only mode and readiness in Settings → Apply (§4.3); starting an application belongs to Q-110 (link to Inbox) |
| A8 | MailCard behaviour is the peer's: request R2 (collapse the connect form behind "Connect another Gmail") |
| A11, A15 (Companies/Runs parts), A10 (Runs part) | excluded (Q-85/86/87 lanes) |

## 6. Waves

**Wave 1: UI-only fast track.** It reads existing state and changes no schema, credential path or account logic. The Apply section's writes go through Q-111's endpoints (R3/R4), not through Q-100's backend. Contents: §1, §2, §3, §4 (Wave 1 actions only), §5.

**Wave 2: KA-3, full dossier plus jobscraper-48's sign-off.** Outline and the exact ask of `apply/` / CLI:

| Gap | Outline | API asked of the peer |
|---|---|---|
| **G2** ATS password entry, clearing `signin_failed`, Forget | Employer row → "Enter password" form (MailCard pattern, write-only) → `PUT /api/connections/ats/{id}/password` (raw body) → child `accounts add --id N --password-stdin --json` → `vault.put` + row `created` (keeps `verified`), as `cli.py:1144-1174`. "Forget" → `DELETE /api/connections/ats/{id}` after a confirm ("Forget this account in JobScraper? Your account on {site} stays; JobScraper deletes its saved password.") → `vault.delete` + `store.delete_account`. The failure detail `apply/accounts.py:29-31` changes to "…or enter its password in Settings → Accounts." | CLI: `accounts add --id N --password-stdin --json` and `accounts forget --id N --json`; one function `apply_flow.store_existing_password(store, account_id, secret) -> AccountStatus` shared by the CLI and the child; the copy change in `apply/accounts.py` |
| **G4** Apply mailbox setup | Card form: Gmail address (settings `apply.mail.username`, host fixed to Gmail) + app password, write-only, tested first. `PUT /api/connections/apply-mailbox {username}`; `PUT /api/connections/apply-mailbox/password` (raw body) → child `mail set-password --password-stdin --test-first --json [--backup]`: log in read-only, then `vault.put` only on success, then `{result}`. "Test" → child `mail test --json` (the `mailtest` job kind exists, `web/jobs.py:110-111`, but a short child gives a direct answer) | the two CLI flags above + `--json` result codes reusing `mailstatus.contracts.SyncCode` |
| **G6** Open apply browser, and a "signed in" record | `POST /api/connections/edge/open {url?}` → JobManager kind `open-profile` (`apply open-profile [URL]`, `apply_flow.py:1685-1711`), inside the one-job slot, so `in_use` also covers it. The URL is restricted to `https://` and a host in `ats_accounts` or the known ATS domains; the default is my.greenhouse.io. Record: new table `browser_signins(site TEXT PRIMARY KEY, state TEXT CHECK (state IN ('signed_in','signed_out')), seen_at TEXT NOT NULL, attempt_id INTEGER)`, written by `apply_flow` when an adapter reports it (Greenhouse already logs it, `apply/ats/greenhouse.py:515-522`); the edge item gains `facts.signins` | a reporting channel `AttemptContext.note_signin(site, state)` (contract version bump + ADR), the store method `browser_signin_set` (engineer, `store.py`), job kind `open-profile` in `web/jobs.py` (reserved words already, `:117-118`) |
| **G7** Profile collision | In `apply_flow` `browser()` (`apply_flow.py:720-723`), a launch error for which `_names_profile_dir` is true (`:1677-1682`) → `ApplyFailure(ReasonCode.BROWSER_IN_USE)`. Text: "The apply browser was already open, so JobScraper didn't start. Nothing was sent." Hint: "Close the apply browser window, then try again." | new `ReasonCode` + `REASON_TEXTS` entry (contract bump) |
| **G11** Stale Edge CSV | `create_app` startup handler → `vault.purge_stale_exports(cfg.db_path.parent)` (`vault.py:248-267`), as apply_design §10.3 already specifies; plus once an hour on the mail timer thread or its own daemon | sign-off only (the credential-file lifecycle); no new API |

Requests to log now:
- **R1** (to Q-110's owner): add `!error` to the caught-up branch at `Inbox.vue:459`.
- **R2** (to jobscraper-48): for A8, collapse MailCard's connect form once a mailbox is connected, and drop MailCard's own h3 when embedded (an optional `embedded` prop).
- **R3** (to Q-111): `writable: true` in `GET /api/apply/settings` once the PUT exists.
- **R4** (to Q-111): `compose_enabled` in the same GET/PUT.
- **R5** (to Q-111, replaces Q1): nothing extra, since the limits come from `/api/apply/settings`.

## 7. Requirement map

| Finding / pattern | Section | Wave |
|---|---|---|
| A1 ATS accounts invisible / CLI-only | §4.1 table + CLI hints; §6 G2 | 1 (view), 2 (fix) |
| A2 Edge profile surface | §2, §4.1; §6 G6/G7 | 1, 2 |
| A3 model health | §3.3, §4.1, setup step | 1 |
| A4 setup covers apply | §4.2 | 1 |
| A5 mode and start | §4.3 read-only; Q-110 | 1 |
| A6 Upload lands wrong | §1 deep links, §4.2 | 1 |
| A7 false states on API error | §4.2 rule; R1 | 1 |
| A8 Gmail form stacked | R2 | peer |
| A9 health vs connected | §2 Gmail rows | 1 |
| A10, A12, A13, A14, A15 (non-Runs/Companies) | §5 | 1 |
| P1 hub, P2 vocabulary, P3 badge + banner | §1, §2, §4.1 | 1 |
| P4 reconnect in place | MailCard (exists); §6 G2/G4 | 2 |
| P5 test before save | G4 `--test-first` | 2 |
| P6 employer table (no Copy password: ADR-0009) | §4.1, §6 G2/G6 | 1, 2 |
| P7 no-account-needed, P8 last/next check, P11 where stored, P21 empty states | §3.1, §4.1, §4.4 | 1 |
| P12 resume first, P13 optional + Later, P14 readiness list | §4.2, §4.3 | 1 |
| P16 mode visible | §4.3 (Settings only; a header chip is Q-110's call) | 1 |
| P22 Edge card | §4.1 | 1 (view), 2 (open) |
| P9 activity log, P10 disconnect-in-⋯, P15, P17–P20 | not adopted now (P10 exists in MailCard; the rest belong to apply lanes) | — |
| P23 app lock | not built (D-190) | — |
| G3 Copy password | ADR-0009, apply_design §14.3 | done |
| G12 status comment | engineer note on `store.py:221` with any store edit | — |

## 8. Wave 1 build lanes (disjoint files; ≤ 3 in parallel)

| Lane | Files (only these) | Delivers |
|---|---|---|
| **T0** (tester, first, small) | `web/src/fixtures/connections.sample.json` (one item per state/code in §2), Python fixtures | the mock that lanes B and C build against |
| **A** backend | `src/jobscraper/web/connections.py` (new), `src/jobscraper/web/routers/connections.py` (new: `GET /api/connections`, `POST /api/connections/model/check`; the R4 fallback route only if Q-111 declines), `src/jobscraper/web/api.py` (`app.state.model_health`), `src/jobscraper/backends.py` (`unavailable_code`). Never `routers/apply.py`, `applicant.py` or `facts.py` | §3 |
| **B** hub + Settings | `web/src/connections.js` (new: code→copy, state→chip, `applySteps` helpers), `web/src/connections_api.js` (new: `getConnections`, `checkModel`, and `getApplyStatus` / `getApplySettings` / `putApplySettings`, each mapping 404/405 to `null` = "not available"), `web/src/api.js` (only: `export` on `request`, `:23`; Q-110 appends at the end, so the hunks don't meet), `web/src/components/ConnectionsHub.vue`, `ConnectionCard.vue`, `EmployerAccounts.vue`, `ApplySettings.vue` (new), `web/src/tabs/Settings.vue` (views, MailCard embedded unchanged, A10/A12/A15 copy) | §2 copy, §4.1, §4.3 |
| **C** shell + onboarding + fixes | `web/src/route.js`, `web/src/App.vue` (connections load, badge tone, banner, bottom bar), `web/src/tabs.js`, `web/src/components/AttentionBanner.vue` (new), `web/src/setup.js`, `web/src/components/SetupChecklist.vue`, `web/src/tabs/Overview.vue`, `web/src/tabs/Profile.vue` (`useView`), `web/src/tabs/Applications.vue` (A13), `web/src/components/ApplicationDetails.vue`, `web/src/components/JobStatus.vue` | §1, §4.2, §5 A6/A7/A13/A14/A15 |

**Order and contracts.** T0 comes first, because the §3.1 JSON is the contract. A, B and C then run in parallel. B and C mock with the fixture. C needs B's `connections.js` (copy) and `connections_api.js` for the banner and `applySteps`. B commits those two files as its first step, and until then C imports a local stub with the same exports. C's `route.js` (`parseHash`, `hashFor`, `useView`) is likewise its first commit, and B's `Settings.vue` uses it. Merge order: A, then C, then B (B's Settings views depend on C's `useView`). The bundle is built once, in the main checkout, after all three merge. Message the peer sessions before merging (handover). Verify: `python tests/run_tests.py -k connections`, `cd web; npx vitest run`, then a browser check at 1440 and 390 px against a DB copy on 8768 with `JOBSCRAPER_MAIL_SYNC=0`. No real account is created or used.

**Open questions.** **Q1** (settled by addendum 3) Limits and mode come from Q-111's `/api/apply/settings`; R3/R4 are pending Q-111's answer. **Q2** Show the employer account email in full (as MailCard shows the Gmail address) or masked (brief P6)? Proposed: in full, since it is local and the owner's own address. **Q3** Does R1 (`Inbox.vue:459`) land in Q-110, or wait for Q-100 Wave 2?
