# Q-100 design: UI overhaul and Connected accounts hub (D-190..D-193)

**Status: READY TO BUILD (Coordinator, 2026-11-11, D-194).** Architect, 2026-11-11. Revision 2 resolves `docs/reviews/Q-100-design-review.md` (REVISE: 1 blocking, 6 major, 9 minor) and the researcher's review (`comms/outbox/researcher.md`, 2026-11-11: 0 blocking, 2 major, 6 minor); see §9.

Inputs: `accounts_ux_current_state.md` (gaps G1–G12), `docs/research/ux_accounts_brief.md` (patterns P1–P23), `docs/reviews/Q-100-ui-audit.md` (A1–A15), ADR-0009 (D-191).

Settled and not reopened here:
- No app login and no app lock (D-190). The lock remains a future owner option (current-state §6).
- No secret goes from server to browser (D-191).
- Starting auto-apply belongs to Q-110 (D-192): `GET /api/apply/status {mode, missing, busy}` and `POST /api/apply` are merged (`web/routers/apply.py:100-105,108`). The hub links to the Inbox for it.
- Emails show in full (D-193).
- Q-111 will add `GET/PUT /api/apply/settings` with `writable` and `compose_enabled`.

Code claims cite `file:line` on `personal` as read on 2026-11-11.

## 1. Information architecture

**Decision: the hub is a Settings view, not a new tab.** Settings gets four views, switched like Profile's (`web/src/tabs/Profile.vue:91-113`): **Accounts** (the hub, the default view), **Apply**, **Search** (today's Cycle and Companies per run) and **Appearance**. Reasons:
1. The failure hints say "Settings → Accounts" and "Settings → Apply" (`apply/contracts.py:169,175,193`). For `:175`, "Set up the mailbox in Settings → Apply", the Apply view carries an **Application mailbox** row that links into Accounts (§4.3). Both hints become true, and the peer's copy stays unchanged.
2. A ninth tab would worsen A14.
3. Arrival-time visibility comes from the badge, the shell banner and the mode chip, not from a tab.

**Routes.** `route.js` accepts `#/<tab>[/<view>[/<item>]]`. Today only `#/<tab>` works; anything else is rewritten to the first tab (`web/src/route.js:6-8`, `web/src/App.vue:55-59`).
- An unknown tab falls back to the first tab, as today.
- An unknown view falls back to the tab's default view, and `replaceState` writes the canonical hash.
- An unknown item opens the view at the top.

| Hash | Lands on |
|---|---|
| `#/settings/accounts[/<item-id>]` | the hub; an item id scrolls to its card and focuses the card heading |
| `#/settings/apply`, `#/settings/search`, `#/settings/appearance` | that view |
| `#/profile/resume`, `#/profile/details` | Profile views (A6). The localStorage hand-off (`Profile.vue:96-112,244-247`) stays as the fallback when there is no view in the hash |

Contract (lane 0): `parseHash(hash, ids) -> {tab, view, item}`, `hashFor(tab, view?, item?)`, and `useView(tabId, views, fallback) -> Ref<viewId>`. `useView` reads the hash, follows `hashchange` and writes with `replaceState`. `normaliseHash` keeps the view and item.

**Shell signals (App.vue, lane C).**
- **Settings badge:** the count of items that `connections.js` `attentionCount(prev, cur)` says need attention (§2.2). It uses the tab field `badgeTone: 'attention'` (amber), with the screen-reader label "need attention". There is no badge when the count is 0 or the load failed.
- **Attention banner** under the masthead, on every tab except `#/settings/accounts`, with `role="status"`. One item: "**{Name} needs attention.** {line} [Fix it]". Several items: "**{n} connections need attention.** [Review]". The button reads **Fix it** when the fix is in the app (MailCard, Check again, a Profile link) and **See how to fix** when the fix is a CLI command (Wave 1 employer accounts and mailbox). [Dismiss] lasts for the session; the sessionStorage key is the sorted `id:code` list, so a new or changed problem brings the banner back.
- **Mode chip** "Auto-apply on", linking to `#/settings/apply`. It shows only when `GET /api/apply/status` says `mode = "auto"`, and is hidden on dry_run, 404 or error (researcher M2).
- **Cadence:** `GET /api/connections` and `GET /api/apply/status` run at boot, after any background job ends (`onFinish`, `App.vue:173-184`), and when the page becomes visible after more than 60 s. The hub polls every 30 s while open, and every 3 s (at most 5 times) while an item is `checking`. A failed load means no badge, no banner and no chip, never a false "all good".

## 2. One state vocabulary

### 2.1 States

| `state` | Chip (default text) | Tone | Counts for the badge | Meaning |
|---|---|---|---|---|
| `connected` | Connected; **Ready** for the Edge item | green | no | works; last check good |
| `attention` | Needs attention | amber | **yes** | the owner must act; the line says why and how |
| `neutral` | per code: "Not running", "Not confirmed", "Couldn't check" | grey | no | known but not blocking anything now |
| `not_set_up` | Not set up, or Optional | grey | no | never configured |
| `paused` | Paused | grey outline | no | switched off by the owner or by config; history kept |
| `checking` | Checking… | neutral | no | first probe not answered yet |

Setup steps (§4.2) draw the same states as done / to do / "Couldn't check". `doctor` will reuse these words later (§3.4).

### 2.2 Attention count (client, `connections.js`, lane 0)

`attentionCount(prev, cur)` counts the items whose state is `attention`. It also counts an item whose code is `check_failed` in **both** the previous and the current load (researcher m1). A single blip shows as neutral "Couldn't check".

### 2.3 Mapping (server computes `state`/`code`; the client maps `code` to copy, §4.4)

| Thing | Stored fact (source) | state · code | Primary action (wave) |
|---|---|---|---|
| Gmail mailbox | `enabled = 0` (`store.py:335`) | paused · `switched_off` | Switch on, in MailCard (W1) |
| | `consent_version ≠ CONSENT_VERSION` | attention · `consent` | Review and confirm, in MailCard |
| | `state = paused` (`AccountState`, `mailstatus/contracts.py:30-34`) with `state_code` ∈ {`login_refused`, `app_password_required`, `web_login_required`, `not_set_up`} (`SyncCode`, `:37-54`) | attention · that code | Update app password, in MailCard |
| | `state ∈ {error, backoff}`, `last_ok_at` within 24 h | connected · `retrying` | none; the line shows `retry_after` |
| | the same, with `last_ok_at` older than 24 h or null | attention · state_code | Check now, in MailCard |
| | `state = ok`, timer running (`timer_running`, `web/mailsync.py:137-139`) | connected · `ok` | none |
| | `state = ok`, `mail_status.enabled` true, timer not running | connected · `timer_off` (A9) | none |
| Gmail (none) | no `mail_accounts` rows | not_set_up · `none` (Optional) | Connect Gmail |
| Application mailbox | host and username set, vault entry present | connected · `ok` | none (Test: W2) |
| | username set, no vault entry | attention · `no_password` | W1: CLI command; W2: Enter app password |
| | username unset | not_set_up · `none` (Optional) | W1: CLI command; W2: Set up |
| Employer account (`ats_accounts` row, `store.py:217-227`) | `created` / `verified`, password present, `last_signin_ok ≠ 0` | connected · `ok` / `verified` | none |
| | `signin_failed` | attention · `signin_failed` | W1: CLI; W2: Enter password / Open sign-in page |
| | `exists_no_password` | attention · `exists_no_password` | same |
| | `created` / `verified` with no vault entry | attention · `password_missing` | same |
| | `creating` / `unknown` (`apply/contracts.py:614,618`) | neutral · `unconfirmed` | none |
| Employer accounts (summary) | worst row state; 0 rows → not_set_up · `none` (Optional) | — | View accounts |
| Apply browser | `profile_dir` (`config.py:104`, expanded as in `apply/browser.py:74`) missing | not_set_up · `none` (a note, not a step) | W1: none; W2: Open apply browser |
| | the web job manager runs an `apply` job (`web/jobs.py:347-350`), or Chromium's `<dir>/lockfile` exists and can't be opened for reading (a best-effort check of the CLI path; minor 4) | connected · `in_use` | none |
| | dir present, free | connected · `ok` (chip "Ready") | W2: Open apply browser |
| Local AI | `budget.enable_llm` false or backend `off` (`backends.py:256-262`) | paused · `ai_off` | none (copy points to `config.yaml`) |
| | unknown backend (`backends.py:270`) | attention · `misconfigured` | none (config) |
| | probe ok | connected · `ok` | Check again |
| | probe `unreachable` / `model_missing` **and** `need_now` | attention · that code | Check again |
| | probe `unreachable` / `model_missing`, not `need_now` | neutral · that code (chip "Not running" / "Model not downloaded") | Check again |
| | no probe result yet | checking · `probing` | — |

**`need_now` (exact rule).** It is true if any of the following holds. None of these needs new SQL.
- (a) `app.state.jobs.current(tail=0)` has `state = "running"` and a `kind` other than `mailtest`. Every other kind can call the model.
- (b) `store.attempts_in_flight()` (`store.py:1443`) is non-empty.
- (c) `store.last_attempts()` (`store.py:1431-1441`) has a row with `reason_code = "model_unavailable"` and `finished_at` within the last 24 h.
- (d) any `mail_accounts.last_counts_json` (`store.py:343`) has `pending_model > 0` (`COUNT_KEYS`, `mailstatus/contracts.py:330-331`).

Applicant readiness and the apply mode are **not** hub items: Settings → Apply and setup read them from their own endpoints (§4.2, §4.3).

## 3. `GET /api/connections` (read-only, no secrets)

### 3.1 Schema v1 (the contract; T0 writes a fixture with one item per row of §2.3)

```jsonc
{ "version": 1, "checked_at": "2026-11-11T09:12:00",    // UTC, store.TIME_FMT
  "attention": 1,                       // server-side count of state "attention" (doctor; the badge uses §2.2)
  "items": [ { "id": "gmail:3" | "apply-mailbox" | "apply-mailbox:backup" | "employer-accounts" | "edge" | "model",
      "kind": "gmail" | "apply_mailbox" | "employer_accounts" | "edge" | "model",
      "state": "connected" | "attention" | "neutral" | "not_set_up" | "paused" | "checking",
      "code": "ok", "message": null,    // message: Gmail only, SYNC_TEXTS copy (§3.2)
      "optional": false, "stored_in": "credential_manager" | "edge_profile" | "this_pc" | null,
      "checked_at": null, "next_check_at": null, "last_ok_at": null, "retry_after": null,
      "facts": { } } ],                 // per kind, below; never a secret or anything derived from one
  "employer_accounts": [ { "id": 12, "ats": "workday", "tenant_host": "acme.wd3.myworkdayjobs.com",
      "email": "…", "status": "signin_failed", "state": "attention", "code": "signin_failed",
      "has_password": true, "created_at": "…", "verified_at": null, "last_signin_at": "…",
      "last_signin_ok": false, "exported_to_edge_at": null, "created_by_attempt": 41 } ],
  "no_account_needed": ["greenhouse", "lever", "ashby"] }
```

`facts` by kind:
- gmail: `{address, enabled, shared_with_apply, counts, consent_current}`
- apply_mailbox: `{host, port, username, has_password, backup_separate}`
- edge: `{exists, in_use, sync, last_used_at}`. No path: it contains the Windows user name.
- model: `{backend, model, local, need_now}`
- employer_accounts: `{total, attention}`

### 3.2 Field sources (lane A; no new SQL and no edits to `store.py`, `applicant.py`, `facts.py`, `apply/`, `mailstatus/` or `routers/apply.py`/`mail.py`)

| Field | Source |
|---|---|
| Gmail items | Raw `store.mail_accounts()` rows (`store.py:2081-2085`), mapped **in `web/connections.py`** with `SyncCode`, `SYNC_TEXTS` and `CONSENT_VERSION` from `mailstatus.contracts`, plus a local 4-line `_sync_text` (rule 3; no import of `routers/mail.py`). The runner's `timer_running` and `status()` (`web/mailsync.py:137-139,281-291`) come via `request.app.state.mail`: status calls only, never a sync, connect or IMAP call (the mail owner's condition) |
| Application mailbox | `cfg.apply.with_settings(store.get_setting)` (`config.py:162`) plus `store.get_setting("apply.mail_backup.username")`. `vault.imap_service` + `vault.get(...) is not None` (`vault.py:61-86`), as a boolean only |
| Employer accounts | `store.accounts()` (`store.py:1623-1625`). `has_password` = `vault.get(row["vault_service"], row["email"]) is not None`. `vault_service` is never sent |
| Edge | `os.path.expandvars(acfg.profile_dir)`, `is_dir()`, the `lockfile` read test, and `app.state.jobs.current(tail=0)`. `last_used_at` = the max `started_at` in `store.last_attempts()`. `sync` = `acfg.edge_sync` |
| Model | `ModelHealth` (§3.3) over `backends.probe(cfg.budget)`; `need_now` per §2.3 |

Modules:
- `src/jobscraper/web/connections.py`: pure. `compose(cfg, store, mail_runner_view, job_view, model_snapshot, vault_has, lockfile_busy, now) -> dict` holds every mapping in §2.3 and is testable with fakes.
- `src/jobscraper/web/routers/connections.py`: the routes; auto-discovered (`web/api.py:75-82`).

`web/` may import `store`, `config`, `backends`, `vault` and the contracts (`tests/test_layering.py:74-79`), so no layering change is needed.

### 3.3 Model probe: never blocks a request, never leaks a client

- **New function (lane A):** `backends.probe(budget) -> Probe(ok, code, backend, model, local)`, with `code ∈ {"", "off", "misconfigured", "unreachable", "model_missing"}`. It builds a backend, reads `.available`, and in a `finally` closes the Ollama `httpx.Client` (`backends.py:116`) through a new `OllamaBackend.close()` (minor 3). `Backend` gains `unavailable_code = ""`. `OffBackend` takes a code: `"off"` from `:257,262`, `"misconfigured"` from `:270`. Ollama sets `"unreachable"` / `"model_missing"` next to `unavailable_reason` (`:128,135`). `unavailable_reason` is never sent, because it contains the URL.
- **`ModelHealth`** on `app.state.model_health` (`create_app`, `web/api.py:253-263`): `snapshot()` returns the cache immediately. Inside **one lock** it checks staleness (TTL 60 s after success, 15 s after failure; `off`/`misconfigured` read config only, so they are never stale) and sets `in_flight`. Only then does it start one daemon thread. The thread runs `probe()` and clears `in_flight` in `finally` (minor 2). It calls only `/api/tags`, so no model is loaded and no GPU is used.
- `POST /api/connections/model/check` → 202 and a forced probe ("Check again"). It writes nothing, but it is a POST, so `CrossSiteWriteGuard` applies.

### 3.4 Errors and limits

- A failing source (a `VaultError`, a busy store) gives that item `neutral · check_failed`. Its `message` is fixed copy and **never exception text**: a `VaultError` names the service and host (`vault.py:84-85`) (minor 1).
- A store that can't be opened gives 503 `{code: "unavailable"}`, like `/api/healthz`.
- The response is not cached; it costs 4 store reads and N+2 local vault reads.
- ADR-0009 action item 2 now names `/api/connections` explicitly.
- `doctor --json` over `connections.compose` is a follow-up (proposed Q-102). `doctor` writes today (`cli.py:101`).

## 4. Screens

All new controls: at least 44 px tall under 640 px (token `--touch-min`); `<code>` blocks wrap (`white-space: pre-wrap; overflow-wrap: anywhere`); the four Settings view tabs wrap onto two lines at 390 px (minor 5).

### 4.1 Settings → Accounts (the hub)

```
Settings
[ Accounts ● 1 ] [ Apply ] [ Search ] [ Appearance ]
Connected accounts
Everything JobScraper signs in to. Passwords stay in Windows Credential Manager on this PC; the app never shows them.
┌ ✉ Application updates from email ─────────────────── [Needs attention] ┐
│ 1 of 2 mailboxes needs attention · checks every 10 min                 │
│ ── MailCard embedded (embedded prop: no own title; connect form       │
│    collapsed behind "Connect another Gmail") ──                        │
│ See status changes from email → Applications                           │
└────────────────────────────────────────────────────────────────────────┘
┌ ⌂ Application mailbox ─────────────────────────────────── [Connected] ┐
│ Reads verification codes during applications. Also used for updates. │
└───────────────────────────────────────────────────────────────────────┘
┌ ◫ Apply browser ───────────────────────────────────────────── [Ready] ┐
│ Edge profile used only by JobScraper. Sign-ins are kept between       │
│ restarts. Last used today 09:02.          [Open apply browser] (W2)   │
└───────────────────────────────────────────────────────────────────────┘
┌ ◎ Local AI ──────────────────────────────────────────── [Not running] ┐
│ Ollama isn't running. Nothing needs it right now. [Check again]       │
└───────────────────────────────────────────────────────────────────────┘
┌ ⚿ Employer accounts ──────────────────────────────── [Needs attention] ┐
│ Site                          Email   Status                 Last sign-in │
│ acme.wd3.myworkdayjobs.com    you@…   Needs attention        3 Nov, failed│
│   Sign-in failed. JobScraper won't try again, so the account isn't      │
│   locked.  [See how to fix ▾]  (W2: [Enter password] [Open sign-in page])│
│ globex.wd1.myworkdayjobs.com  you@…   Connected · Verified   5 Nov        │
│ No account needed: Greenhouse, Lever, Ashby. They apply as a guest.     │
└─────────────────────────────────────────────────────────────────────────┘
```
- **The Gmail card** has one header for all its `gmail:<id>` items. The chip shows the worst state. With one mailbox the line is that item's summary; with several it reads "{k} of {n} mailboxes need attention". The per-mailbox reason stays only in MailCard's row, so it is not shown twice (minor 8).
- **Employer status column:** state chip · "Verified" / "Not verified" from `verified_at` (m4). At 390 px each row is one block.
- **"See how to fix ▾"** shows the exact CLI line, for example `python -m jobscraper accounts add --url https://acme.wd3.myworkdayjobs.com/ --email you@…`. The CLI prompts for the password; nothing is copied automatically.
- **Activity links (m3):** the Gmail card links to Applications ("See status changes from email"). Per-row attempt links need a job lookup and wait for W2.

### 4.2 First-run setup: two parts (A4, A6, A7)

```
Get set up                                                  Find jobs 3 of 4 · Apply for me 1 of 2
Find jobs        Upload your resume ✓ · Choose titles ✓ · Add companies ✓ · Run your first search ○
Apply for me     [Later]
  ○ Fill in your application details   3 missing                 [Fill in details] → #/profile/details
  ✓ Local AI                           Connected
  Optional  Application mailbox        For sites that email a code [Set up] → #/settings/accounts/apply-mailbox
  Optional  Email updates              Gmail                       [Connect] → #/settings/accounts/gmail
  Note: the apply browser is created the first time an application runs.
```
- `setup.js`: `setupSteps(facts)` stays as it is for "Find jobs", except that the resume href becomes `#/profile/resume` (A6).
- The new `applySteps({ connections, applicant })` builds part 2 from these sources:
  - **Details** come from `GET /api/applicant` `missing` / `completeness` (`web/routers/applicant.py:134-135`), as Profile already does. The step exists whether or not Q-110 is present (rule 4).
  - **Local AI** is a required step. It is done when the model item is `connected` or `paused · ai_off`; with AI off, the step reads "Off in settings" and is still done.
  - Mailbox and Gmail come from `connections.items` and are **Optional**. The browser line is a note, not a step.
- **Counting (m2, minor 6):** "n of m" counts **required** steps only, per part.
- **A7:** a failed check shows "Couldn't check" for that step and is not counted. If every check fails, "Couldn't check your setup just now. [Try again]" replaces the checklist; it is not "0 of 4". The Inbox "all caught up" under an error is already fixed: `!error` is in the condition at `web/src/tabs/Inbox.vue:513`, so R1 is closed.
- **Placement:** on Overview (`Overview.vue:136`) while there are no runs, or while part 2 has an unfinished required step and isn't dismissed ("Later" is stored in localStorage; Settings → Apply always shows readiness). Q-100 does not edit `Inbox.vue`.

### 4.3 Settings → Apply (UI owned by Q-100; backend by Q-110/Q-111)

```
Apply
Mode                 Dry run · JobScraper fills each form and leaves it open for you. Nothing is sent.
Limits               10 applications a day · 2 per employer · browser window shown
Human checks         JobScraper stops and leaves the page to you. It never solves them.
Application mailbox  Connected · Manage in Accounts →
Ready to apply       3 things to fill in first: phone, resume file, work permit     [Fill in details]
                     To apply, open a role in the Inbox and choose Auto-apply.      [Open Inbox]
Cover letters        [ ] Write a cover letter when a form requires one
                     Off: JobScraper stops and asks you instead.
```
Row by row:
- **Mode:** from `GET /api/apply/settings` (Q-111) when present, else from `GET /api/apply/status` `mode` (Q-110, merged). The row is hidden if both are unavailable.
- **Limits and human checks:** from `/api/apply/settings`; hidden on 404. Human checks, when `captcha_wait_s > 0`: "JobScraper waits up to {n} s for you to finish a human check in the window. It never solves them." (m6, minor 6).
- **Application mailbox:** the `apply-mailbox` item from `/api/connections`, as chip + "Manage in Accounts" → `#/settings/accounts/apply-mailbox`. This row makes `apply/contracts.py:175` true (rule 7).
- **Ready to apply:** `missing` from `GET /api/applicant` (always available) and `busy` from `/api/apply/status` when present. Paths become labels through `GET /api/applicant` `form` (`web/routers/applicant.py:140`); an unknown path shows as is.
- **Editable once Q-111 says so:** when `GET /api/apply/settings` returns `writable: true`. The UI never sends a probe PUT, because that would pin `apply.*` rows over `config.yaml` (`config.py:162-172`).
  - Mode becomes a radio. Switching to automatic confirms first: "Send applications automatically? JobScraper sends each one only after its final check passes, within your daily limits." [Switch to automatic] [Keep dry run]
  - Caps are 1–50 and the human-check wait is 0–600 s, checked on the client the same way as Q-111's 422.
  - A 404, 405 or 422 on PUT shows "Couldn't save: {detail}" and puts the controls back to read-only.
- **Cover letters:** `compose_enabled` in Q-111's GET/PUT (R4). The row is hidden until the GET carries the field.

### 4.4 Copy (design:ux-copy: sentence case, verbs on buttons, what happened + how to fix)

| Context | Copy |
|---|---|
| Gmail `timer_off` | "Automatic checks are off in this copy of the app. Use Check now." |
| Gmail `retrying` | "The last check couldn't reach Gmail. Trying again at {time}." |
| Gmail stale | "Gmail hasn't been checked since {date}. Check now to see why." |
| Mailbox `no_password` | "No app password is saved for {address}. Sites that email a code will stop at that step." |
| Mailbox not set up | "Optional. Needed only when an employer site emails you a code." |
| Employer `signin_failed` | "Sign-in failed. JobScraper won't try again, so the account isn't locked." |
| Employer `exists_no_password` | "An account already exists for this email, and JobScraper doesn't have its password." |
| Employer `password_missing` | "The password is missing from Windows Credential Manager." |
| Employer `unconfirmed` | "Not confirmed. The sign-up may not have finished; JobScraper signs in with it next time." |
| Employer empty | "No employer accounts yet. JobScraper creates one only when an application on a Workday site needs it, and lists it here." |
| Reading a password | "To see a password, open Windows Credential Manager (Windows asks for your password first), or run `accounts export-edge` to import them into Edge." |
| Browser not set up | "Created the first time an application runs. Sign-ins you make there are kept between restarts." |
| Browser `in_use` | "In use by an application right now." |
| AI `ai_off` | "Local AI is off in config.yaml (budget.enable_llm). Runs still work; screening and auto-apply wait for it." |
| AI `misconfigured` | "The AI setting in config.yaml isn't one JobScraper knows. Set budget.backend to ollama or off." |
| AI `unreachable`, attention | "Ollama isn't running, and {what} is waiting for it. Start Ollama, then check again." ({what}: "a run", "an application", "{n} emails") |
| AI `unreachable`, neutral | "Ollama isn't running. Nothing needs it right now." |
| AI `model_missing` | "The model {model} isn't downloaded. Run `ollama pull {model}`, then check again." |
| AI remote (`local: false`) | "{model} through Ollama (not on this PC)." (D-107) |
| `check_failed` | "Couldn't check this just now. Try again in a moment." |
| Hub load error | "Couldn't load your connections. [Try again]" (no chips are drawn) |
| Banner | "**{Name} needs attention.** {line} [Fix it] / [See how to fix]", or "**{n} connections need attention.** [Review]"; [Dismiss] |
| Mode chip | "Auto-apply on" (title: "JobScraper sends applications after a passing check. Change it in Settings → Apply.") |
| Setup, all checks failed | "Couldn't check your setup just now. [Try again]" |
| Mode, dry run / auto | "Dry run. JobScraper fills each form and leaves it open for you. Nothing is sent." / "Automatic. JobScraper sends an application only after its final check passes." |

## 5. Other audit findings adopted (excluding Runs and Companies, which belong to the Q-85/86/87 lanes)

| ID | Change |
|---|---|
| A9 | Gmail `timer_off`, `retrying` and stale states are shown in the hub header (§2.3) |
| A12 | `ApplicationDetails.vue:619`: "Nothing saved yet. Saving keeps your details on this PC." · `Settings.vue:239`: drop the "plan (local)" line |
| A10 (Settings) | `Settings.vue:67`: "No companies yet. Add some in Companies, or start a run to load your watchlist." |
| A13 | In `Applications.vue:393-419`, the three links become buttons: `min-height: 2rem` (`--touch-min` under 640 px), gap `var(--space-2)`. "Remove from Applications" moves last, after a divider, and asks first: "Remove {company} from Applications? Its notes go too." [Remove] [Keep] |
| A14 | Under 640 px the tab bar (`App.vue:296-331`) becomes a fixed bottom bar: Overview, Inbox, Applications, More. More opens a `dialog` sheet with Runs, Companies, Profile, Settings and Developer, their badges, and focus return. The More button sums the hidden tabs' attention badges. **Bar height:** `--bottom-nav-h` (lane 0, `style.css`). `main` gets `padding-bottom: calc(var(--bottom-nav-h) + env(safe-area-inset-bottom))`; the Profile `.save-bar` (`ApplicationDetails.vue:893-894`, today `bottom: 0`) and `.toast` (`ToastHost.vue:75-77`) use `bottom: calc(var(--bottom-nav-h) + …)`. The variable is `0px` at 640 px and wider (rule 5) |
| A15 (part) | Settings subtitle: "Accounts, applying, search and appearance." · `JobStatus.vue:21`: "No job is running. Past runs are in the Runs tab." · Overview "Your last run failed" (`Overview.vue:181-183`) appends the run's stored reason when present |
| A8 | MailCard `embedded` prop (rule 9, lane B; §6) |
| A1–A7 | §1–§4 |
| A11; the Companies/Runs parts of A15; the Runs part of A10 | excluded (Q-85/86/87) |

## 6. Waves

**Wave 1: UI-only fast track.** It reads existing state and changes no schema, credential path or account logic. Apply-settings writes go through Q-111's endpoints. The MailCard `embedded` prop (R2) is in Wave 1 lane B, under these conditions:
- Without the prop, the card renders and behaves **byte-for-byte as today**.
- With it, the h3 is hidden and the connect form collapses behind "Connect another Gmail" once a mailbox is connected.
- The connect, test, disconnect and opt-in flows are unchanged.
- Vitest rows cover both modes.
- The Coordinator sends the diff to jobscraper-91 before merge.

**Wave 2: KA-3, full dossier plus jobscraper-48's sign-off.**

| Gap | Outline | API asked of the peer |
|---|---|---|
| **G2** ATS password, clear `signin_failed`, Forget | "Enter password" on the employer row (MailCard pattern, write-only) → `PUT /api/connections/ats/{id}/password` (raw body) → child `accounts add --id N --password-stdin --json` → `vault.put` + row `created` (`verified` kept), as `cli.py:1144-1174`. Forget → `DELETE /api/connections/ats/{id}` after the confirm "Forget this account in JobScraper? Your account on {site} stays; JobScraper deletes its saved password." The detail at `apply/accounts.py:29-31` changes to "…or enter its password in Settings → Accounts". Row link to its last attempt (m3) | `accounts add --id --password-stdin --json`, `accounts forget --id --json`; `apply_flow.store_existing_password(store, account_id, secret) -> AccountStatus`; the copy change |
| **G4** Application mailbox setup | A form on the card: Gmail address (`apply.mail.username`) + app password, write-only, tested first. `PUT /api/connections/apply-mailbox {username}`. `PUT …/password` → child `mail set-password --password-stdin --test-first --json [--backup]`. Test → child `mail test --json` | those CLI flags; result codes reuse `SyncCode` |
| **G6** Open apply browser + a "signed in" record | `POST /api/connections/edge/open {url?}` → job kind `open-profile` inside the one-job slot. **Default target (m5):** a row's tenant sign-in page, otherwise `about:blank`; never my.greenhouse.io by default. The URL must be `https://` and a host in `ats_accounts` or a known ATS domain. Record: `browser_signins(site TEXT PRIMARY KEY, state TEXT CHECK (state IN ('signed_in','signed_out')), seen_at TEXT NOT NULL, attempt_id INTEGER)`, written by `apply_flow` from adapter reports (`apply/ats/greenhouse.py:515-522`) | `AttemptContext.note_signin(site, state)` (contract bump + ADR); `store.browser_signin_set`; job kind `open-profile` in `web/jobs.py` |
| **G7** Profile collision | `apply_flow` `browser()` (`apply_flow.py:720-723`): a launch error matched by `_names_profile_dir` (`:1677-1682`) → `ReasonCode.BROWSER_IN_USE`. Text: "The apply browser was already open, so JobScraper didn't start. Nothing was sent." Hint: "Close the apply browser window, then try again." | new reason code + text (contract bump) |
| **G11** Stale Edge CSV | `create_app` startup → `vault.purge_stale_exports(cfg.db_path.parent)` (`vault.py:248-267`), plus an hourly daemon (apply_design §10.3) | sign-off only |

Open requests:
- **R2** is now lane B work.
- **R3/R4** (to Q-111): `writable` and `compose_enabled` in `/api/apply/settings`; the Coordinator reports both agreed.
- **R1** is closed (already fixed).
- **New R6** (to Q-110): P15, a pre-fill summary on the apply card (which resume, new or existing tenant account, mode), owned by Q-110.

## 7. Requirement map

| Finding / pattern / review issue | Section | Wave |
|---|---|---|
| A1 employer accounts | §4.1 table + CLI hint; §6 G2 | 1 view, 2 fix |
| A2 Edge surface | §2.3, §4.1; §6 G6/G7 | 1, 2 |
| A3 model health | §3.3, §4.1, setup step, `need_now` | 1 |
| A4 setup for apply | §4.2 | 1 |
| A5 mode and start | §1 chip, §4.3; start = Q-110 | 1 |
| A6, A7 | §1 routes, §4.2 | 1 |
| A8 | §6 MailCard `embedded` | 1 (lane B) |
| A9, A10 (Settings), A12, A13, A14, A15 (part) | §2.3, §5 | 1 |
| P1–P3, P7, P8, P11, P13, P14, P16 (chip), P21, P22 | §1–§4 | 1 |
| P4, P5, P6 actions, P15 | §6 / R6 | 2 / Q-110 |
| P9 activity log | Gmail link in W1; row links in W2 | 1, 2 |
| P10 | MailCard (exists) + G2 Forget copy | 1, 2 |
| P12 parse-review diff | out of scope (profile owner) | — |
| P23 app lock | not built (D-190) | — |
| G3 Copy password | ADR-0009, apply_design §14.3 | done |
| G12 status comment | note for any later `store.py` edit | — |

## 8. Wave 1 lanes (disjoint files; at most 3 build lanes in parallel)

| Lane | Files (each listed once in this table) | Delivers |
|---|---|---|
| **T0** tester, first | `web/tests/fixtures/connections.sample.json` (one item per §2.3 row), `tests/fixtures/connections_rows.json` (raw store rows for the composer) | the mock contract |
| **0** shared web foundation, after T0 | `web/src/route.js` (`parseHash`, `hashFor`, `useView`), `web/src/connections.js` (new: code → copy, state → chip, `attentionCount`, `applySteps`), `web/src/connections_api.js` (new: `getConnections`, `checkModel`, `getApplyStatus`, `getApplySettings`, `putApplySettings`, `getApplicantSummary`; 404/405 → `null`), `web/src/api.js` (only `export` on `request`, `:23`), `web/src/style.css` (chip tones, `--bottom-nav-h`, `--touch-min`, `.code-wrap`), `web/src/components/StateChip.vue` (new; used by B and C) | the contracts B and C build on |
| **A** backend | `src/jobscraper/web/connections.py` (new), `src/jobscraper/web/routers/connections.py` (new), `src/jobscraper/web/api.py` (`model_health`), `src/jobscraper/backends.py` (`unavailable_code`, `OffBackend` codes, `close()`, `probe()`) | §3 |
| **B** hub + Settings | `web/src/components/ConnectionsHub.vue`, `ConnectionCard.vue`, `EmployerAccounts.vue`, `ApplySettings.vue` (all new), `web/src/tabs/Settings.vue` (views; A10/A12/A15 copy), `web/src/components/MailCard.vue` (`embedded` prop only) | §4.1, §4.3, A8 |
| **C** shell + onboarding + fixes | `web/src/App.vue` (loads, badge tone, banner, mode chip, bottom bar), `web/src/tabs.js`, `web/src/components/AttentionBanner.vue`, `web/src/components/ModeChip.vue` (both new), `web/src/setup.js`, `web/src/components/SetupChecklist.vue`, `web/src/tabs/Overview.vue`, `web/src/tabs/Profile.vue` (`useView`), `web/src/tabs/Applications.vue`, `web/src/components/ApplicationDetails.vue`, `web/src/components/JobStatus.vue`, `web/src/components/ToastHost.vue` | §1, §4.2, §5 |
| **T1** tester, one branch per build lane (T1-A, T1-B, T1-C) | **Updates** (by grep for Settings/Profile/Applications/Overview/App selectors, `tabFromHash`, `#/settings`, `#/profile`, `setupSteps`, MailCard): `web/tests/App.test.js`, `Settings.test.js`, `Profile.test.js`, `Applications.test.js`, `Overview.test.js`, `extensibility.test.js`, `ux1.test.js`, `q75-shell.test.js`, `q75-pages.test.js`, `q44-refresh.test.js`, `q76-detail.test.js`, `shell-job.test.js`, `MailCard.test.js`, `mailFake.js`. **New pins:** `web/tests/route.test.js`, `connections.test.js` (state → chip, `attentionCount` with the 2-failure rule, `applySteps` counting required steps only), `ConnectionsHub.test.js`, `ApplySettings.test.js` (404 hiding, `writable`), `AttentionBanner.test.js`, `MailCard.test.js` rows (default unchanged vs embedded); `tests/test_connections.py` (every §2.3 row; `need_now` a–d; no secret: a stub vault with marker values, then scan every `/api` GET body, including `/api/connections`; a parity row per `SyncCode`: hub `message` == `routers.mail.account_view(row)["message"]`; no `mail_command`/IMAP call during GET (a spy on the runner); probe lock and client close), `tests/test_backends_probe.py` | the failing tests fixed, plus the new pins |

**Disjointness.** Every file appears in exactly one row. The only shared file, `api.js`, belongs to lane 0 (one token). Q-110 appends at its end, so the hunks don't meet.

**Order.**
1. T0, then lane 0. Lane 0 is merged before A, B and C start building on it.
2. A, B and C in parallel and in any order. Each build lane merges together with its T1 branch, so `npx vitest run` and `python tests/run_tests.py` pass at every merge.
3. The bundle is built once, in the main checkout, after the last merge. Message the peer sessions first.

**Verify:**
- `python tests/run_tests.py -k connections`
- `cd web; npx vitest run`
- a browser check at 1440 px and 390 px on a DB copy on 8768 with `JOBSCRAPER_MAIL_SYNC=0`, covering the hub, the banner, the bottom bar over the Profile save bar and a toast, and that state persists across a restart.

No real account is created or used.

**Open questions:**
- **Q4:** is the `lockfile` read test reliable enough on Windows to show `in_use` for a CLI-started apply? If the tester finds false positives after a crash, drop it; `in_use` then covers only web jobs.
- **Q5:** should "Later" on "Apply for me" also hide the banner for `not_set_up` items? Proposed: no. Optional items never raise the banner anyway.

## 9. Review resolution

| ID | Resolution |
|---|---|
| Rev BLOCKING-1 | Lane 0 (§8) owns `route.js`, `connections.js`, `connections_api.js`, `api.js` export, `style.css` and `StateChip.vue`; it merges after T0, and A/B/C are then independent |
| Rev MAJOR-1 / Res M1 | `paused · ai_off`, `attention · misconfigured`, the `need_now` rule (§2.3), neutral "Not running"; `OffBackend` codes; remote copy (D-107) |
| Rev MAJOR-2 | Rows are mapped in `connections.py` with the mailstatus contracts; T1 parity pin; no IMAP or sync from GET (spy pin) |
| Rev MAJOR-3 | Details step from `GET /api/applicant` (§4.2, §4.3) |
| Rev MAJOR-4 | `--bottom-nav-h` applied to `main`, `.save-bar` and `.toast`; `ToastHost.vue` in lane C |
| Rev MAJOR-5 | T1 lists the files to update and the new pins |
| Rev MAJOR-6 | Application mailbox row in Settings → Apply; the hint is unchanged |
| Res M2 | "Auto-apply on" chip (§1) |
| Rev minor 1 | `check_failed` never carries exception text; ADR-0009 item 2 names `/api/connections` |
| Rev minor 2 | `in_flight` set inside the staleness lock, cleared in `finally` |
| Rev minor 3 | `backends.probe` closes the client |
| Rev minor 4 | Edge `lockfile` best-effort check (Q4); chip "Ready", not Connected |
| Rev minor 5 | 44 px under 640 px, `<code>` wraps, view tabs wrap |
| Rev minor 6 | Human-check wording, "See how to fix" for CLI fixes, required-only counting |
| Rev minor 7 | `unconfirmed` is neutral "Not confirmed" |
| Rev minor 8 | `timer_running`; one Gmail header with the reason shown once; several-mailbox summary |
| Rev minor 9 | Lines refreshed (`config.py:162`, `Inbox.vue:513`, `SyncCode :37`); unknown-view rule (§1); R1 closed |
| Res m1 | 2-failure rule (§2.2) |
| Res m2 | Required-only counts; optional steps marked; the browser is a note |
| Res m3 | Gmail → Applications link in W1. **Partly declined:** per-row attempt links need a job lookup (new SQL), so they wait for W2 G2 |
| Res m4 | Verified / Not verified in the status column. "Used by N applications" waits for W2 (needs a query) |
| Res m5 | W2 G6 default target: the tenant's sign-in page or `about:blank` |
| Res m6 | Human-check copy (§4.3) |
