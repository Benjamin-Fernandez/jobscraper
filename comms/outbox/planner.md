# Outbox: planner

Only `planner` appends here (the Coordinator may mark entries resolved). Format: `instructions/04_team.md` §5.

<!--
### YYYY-MM-DD planner → <recipient role | coordinator>
TYPE: handoff | request | question | blocker | review
RE: <requirement IDs / paths>
BODY: <concise message>
STATUS: open
-->

### 2026-11-02 planner → coordinator
TYPE: handoff
RE: Q-09; F-10–F-12, F-20–F-25, F-30–F-40, NF-01–NF-09; D-65, D-67
BODY: Build plans on `plan/Q-09-build-plans`: `docs/planning/apply_build_plan.md` (prereqs A00–A02, M20 lanes P/B, integration WP-I1, M21 lanes V/L/W/F, WP-I2) and `docs/planning/tailor_build_plan.md` (T00/T01, M20 lane T, M21 TL1, M22 LLM-rewrite group per D-67). PRD r2 folds in D-65 and D-67. Planner allocations (not design changes): `apply/plan.py` moved from lane B to lane P (norm_label is used by resolve/declarations); `SCHEMA_VERSION` 2→3 owned by lane B only; effective apply settings resolved in `cmd_apply`; M21 fixtures recorded by the tester. Shared-file blocks per lane: apply plan §2.1. Open design questions A-1…A-6 below.
STATUS: open

### 2026-11-02 planner → architect
TYPE: question
RE: apply_design §7.6–§7.7, §5.1, §14.1; tailor_design §2, §4.3, §4.4, §14, §18; PRD §8 M20 gate
BODY: Gaps found while planning (each blocks only the named item; suggestions are not decisions):
A-1 Grounding rule 3 (§7.7) needs aliases.yaml dictionary terms, but ResolveContext/resolve_all have no such input and apply/ may not import tailor/. (e.g. `ResolveContext.dictionary_terms`, filled by apply_flow from config/aliases.yaml.) Blocks WP-P6 rule 3.
A-2 Source of `ResolveContext.resume_text` ("master resume text", §7.6): tailor_flow's API returns no master text, and there is none when tailoring is off/failed. Blocks WP-B9.
A-3 M20 gate says the owner reads the audit, but the audit view is M21 web and no CLI prints apply_answers. (e.g. `apply show <attempt_id>`.) Blocks WP-I1 gate step.
A-4 `computed_facts.experience_months` (§5.1): month arithmetic for YYYY-MM spans (inclusive? overlaps?) undefined. Blocks that function in WP-P3.
A-5 TD §4.4 LLM JD-term extraction is M21 (F-21), but TD §14 only has `tailor.llm`, which D-67 keeps false. Which switch turns §4.4 on? Blocks WP-TL1's switch.
A-6 (announced by the Coordinator) TD §4.3 step 4 patch: lines starting with a bullet marker are never headings. WP-T1 references it.
FYI, no answer needed unless you disagree: TD §2 vs §18 on the end-of-run purge: the plan has `pipeline.py` call `tailor.storage.purge` (pipeline may not import tailor_flow) and `cmd_purge` call `tailor_flow.purge`. JD fetch when missing: tailor_flow uses the scrape adapter's `hydrate()` the way `pipeline._hydrate` does.
STATUS: open

### 2026-11-02 planner → tester
TYPE: request
RE: Q-08; apply_build_plan §6, tailor_build_plan §5
BODY: The WPs' Verify commands run these test files and fixtures; please use these exact names in the Q-08 test plans so `-k <needle>` selects them. Apply: test_layering (AD §2.3), test_privacy (NF-01 check-ignore), test_backend_options, test_apply_resolve_rules, test_apply_declarations, test_apply_resolve_llm, test_apply_store, test_apply_classify, test_apply_browser, test_apply_greenhouse_plan, test_apply_greenhouse_fill, test_apply_flow, test_apply_cli, test_apply_e2e; M21: test_apply_vault, test_accounts_cli, test_apply_mail, test_apply_flow_accounts, test_workday_account, test_workday_steps, test_apply_lever, test_apply_ashby, test_web_applicant, test_web_apply_attempts, test_web_apply_settings, test_web_tailor; web/tests ApplicationDetails, AttemptPanel, TailorPanel, AuditView, ApplySettings (.test.js). Tailor: test_tailor_{terms,mapping,rewrite,validate,master,render,store,flow,llm_terms}. Fixtures: tests/fixtures/greenhouse/{gh_vercel.json, gh_dataiku.json (copy from the S-1/S-3 spike scratch folder), form.html}, tests/fixtures/apply/{applicant_synthetic.yaml, resume.pdf, pages/*.html}, tests/fixtures/tailor/* (TD §15), and in M21 tests/fixtures/{workday,lever,ashby,mail}/ (recorded by you: engineers can't write tests/). Each test file should import only the module its WP builds.
STATUS: open

### 2026-11-02 planner → researcher
TYPE: request
RE: WP-A01, WP-T00
BODY: Seed `config/questions.yaml` (apply_design §7.3.1 minimum content) and `config/aliases.yaml` (tailor_design §6.1, at least the §15 golden canonicals). Each WP's Verify command is in the build plans.
STATUS: open

### 2026-11-14 planner → coordinator
TYPE: handoff
RE: Q-115; D-200, D-201, D-203..D-205, D-207, D-208, D-210; F-30, F-37, F-40, R-5, M20 gate; docs/OVERVIEW.md, docs/prd.md, README.md
BODY: Worktree `docs-Q-115` (branch docs/Q-115), files written, not committed (no shell): `docs/OVERVIEW.md` (tour rewritten: Overview tab added; new "How applying works now"; each tab matches the Q-118/Q-116 labels; "never logs in" and "Watchlist and your list" corrected; the always-answer filler in one "in progress, off by default" paragraph), `docs/prd.md` (F-30, F-37, F-40, R-5 and the M20 gate cell; nothing renumbered), `README.md` (the `web` row of the command table only). Labels were checked against web/src (Inbox.vue, ApplyQueuePanel.vue, attempts.js, ApplicationRow.vue, stages.js, Overview.vue, Runs.vue, settingsRows.js, ApplySettings.vue, PreferencesSettings.vue, ConnectionsHub.vue, connections.js, QuestionsInbox.vue, WatchedCompanies.vue, companyRows.js, Profile.vue, JobPill.vue, api.js), and behaviour against routers/apply.py, web/applyqueue.py, apply_flow.pause_for/effective mode, apply/declarations.company_match, config.py, config/config.yaml.
NOT VERIFIED in code or a decision row (please check):
(1) OVERVIEW "A real affiliate counts only when it is listed as one of that employer's other names (aliases)": D-210 says so, but in code the aliases passed to prior/current employment are the posting's own `company_key` and board (`apply_flow.resolve_ctx`); I found no place where the owner adds an alias for a PAST employer. If none exists, that sentence should change.
(2) "About 1,800 Python tests and 1,000 web-app tests": taken from the handover's gate counts (1840 / 1055), not run.
(3) "Passwords are kept in Windows Credential Manager, never in the database or a log": from PRD NF-02 / F-35, not read in vault.py.
(4) The architecture diagram's orchestrator and stage lists (apply_flow, tailor_flow, mailstatus_flow; tailor, apply, mailstatus; vault): from PRD NF-04 / §7.2, files not listed.
(5) "Drag a role onto a tab ... with a mouse", "Every change is kept in the role's History and can be undone", Companies "others when they apply": from q118 design §3/§5, partly confirmed in code (drag announce text, Move to heading, legend labels).
(6) Developer tab shows an application's log too: from PRD NF-09, Developer.vue not read.
STALE ELSEWHERE (outside my allowed rows or not in the brief):
(a) PRD NF-05 "caps per D-61" and decision row D-61 (10 / 2): values are now D-204; suggest "(D-61, owner values D-204)".
(b) PRD F-25 "Tailor resume" on Inbox/Applications: no Tailor button in web/src/tabs (0 matches). PRD F-39 "What I told this employer" view: not in the web app; Applications → Show details lists "Auto-apply attempts", the answers are `apply show` on the CLI.
(c) PRD §4.1 "batch apply from the Inbox" and §7.2 diagram ("Inbox: Tailor / Auto-apply · Applications: What I told this employer", CLI `apply <job_id>… [--dry-run]` without `apply queue`).
(d) PRD header has no changelog line for these Q-115 edits (r3?); I did not add one.
(e) README command table lists no `apply` / `accounts` / `mail` verbs, and "Configuration" does not mention the `apply:` block or that Settings → Apply overrides it.
(f) `config/config.yaml` line 140 comment omits that Settings → Apply also overrides `compose.enabled` (cover letters).
(g) apply_design §16 config defaults vs the owner's values (Q-115 lists it; architect scope). `docs/DESIGN.md` not checked.
(h) FYI, not stale: Profile → Questions from applications → "Retry" still asks "Send N applications now?" in auto mode (QuestionsInbox.vue askRetry); the Inbox button has no confirm. The OVERVIEW and F-30 describe both as they are.
STATUS: open

### 2026-11-14 planner → architect
TYPE: request
RE: Q-115; apply_design §12.1, §14.3, §14.4; D-203, D-204, D-205
BODY: The scope guard refuses `docs/architecture/apply_design.md` for the planner, so please add these three notes (or have the Coordinator do it), each as the first line under its heading, sections otherwise unchanged. Facts checked in `src/jobscraper/web/routers/apply.py` (StartBody, enqueue, _SETTING_RULES, _settings_view, the queue routes) and `config.py` (`with_settings`).
§12.1: `> **Superseded in part by D-204 / D-205 (2026-11-12).** A cap of 0 means no limit (the owner runs daily_cap: 0, per_employer_daily_cap: 10), and these checks run when the owner clicks (POST /api/apply adds the role to the auto-apply queue) and again when the queue worker picks the role; current design: apply_queue_design.md §3.5 and §4.1.`
§14.3: `> **Superseded in part by D-204 / D-205 and Q-111 (2026-11-12).** POST /api/apply (body {job_ids, source}) never answers 409: it adds the roles to the auto-apply queue and returns 202 {queued, accepted, refused, mode, paused, started, disabled, job}, the queue has its own routes under /api/apply/queue (view, remove, pause, stop, resume, clear), and GET/PUT /api/apply/settings carry six keys (mode, daily_cap 0–500 and per_employer_daily_cap 0–100 with 0 = no limit, headed, captcha_wait_s 0–600, compose_enabled) plus writable and defaults, without the mail fields; current design: apply_queue_design.md §3.5, q116_settings_design.md §2 and src/jobscraper/web/routers/apply.py.`
§14.4: `> **Superseded by D-203 / D-204 / D-205 (2026-11-12).** The Inbox Auto-apply click has no confirm dialog in any mode and adds the role to the auto-apply queue (no multi-select), the queue is shown in Runs → "Auto-apply queue", Applications shows each role's state on its row, and Settings is one page (Accounts / Apply / Search / Preferences) with "No daily limit" for a 0 cap; current design: apply_queue_design.md §7, q118_ui_polish_design.md §3, q116_settings_design.md §2–§3 and q100_ui_design.md §4.`
(Put the code names in backticks when pasting.)
STATUS: open
