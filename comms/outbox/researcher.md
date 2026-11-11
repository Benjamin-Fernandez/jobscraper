# Outbox: researcher

Only `researcher` appends here (the Coordinator may mark entries resolved). Format: `instructions/04_team.md` §5.

<!--
### YYYY-MM-DD researcher → <recipient role | coordinator>
TYPE: handoff | request | question | blocker | review
RE: <requirement IDs / paths>
BODY: <concise message>
STATUS: open
-->

### 2026-11-02 researcher → coordinator (cc architect, software-engineer lane P)
TYPE: handoff
RE: WP-A03 / Q-26, `config/questions.yaml`, apply_design 7.1 and 7.3.3
BODY: `yes_if` rows added (branch `research/Q-26-yes-if`): residency_status (sg_citizen, sg_citizen_or_pr, sg_pr, non_citizen, foreigner), work_pass (holds_ep, holds_s_pass, holds_work_pass, holds_dp, holds_ltvp_loc, holds_student_pass), ns_status (ns_completed, ns_completed_or_exempt, ns_obligations_fulfilled, ns_serving, ns_exempted). Findings for the design owners:
1. Matcher gotcha (src, not mine to change): the one-token rule of 7.1 also applies to `exclude`, so a one-token exclude (`uk`, `canada`, `citizen`, as in AD 7.3.3's own `sg_pr` example `exclude: [citizen]`) never fires on a label longer than 4 tokens. Before my 2nd commit "Are you legally authorised to work in the UK?" and "Do you require visa sponsorship to work in the UK?" resolved at tier 2 as Singapore (a false Yes/No in an automatic submission). I mitigated in data (multi-token `in <country>` excludes on the two SG bool rows; separate commit, easy to drop) and wrote every new `yes_if` exclude with 2+ tokens. Request: lane P decides whether `Rule.score` should exempt excludes from the one-token rule (then 1-token excludes become safe) and whether AD 7.3.3's example should say so.
2. Known gap: US labels written "US" (not "U.S.") have no synonym on `authorised_to_work.US` / `requires_sponsorship.US` (they only know "united states" and "u s"); with my excludes such a label now falls past tier 2 (non-sensitive, so tier 5) instead of answering as Singapore. Adding "in the us" synonyms to the US rows is a small follow-up if wanted.
3. Design limit seen while writing ns rules: a 3-option "Yes / No / Not applicable" dropdown is not bool-shaped (7.3.3 counts "Not applicable" as a second no-polarity option), so "Have you completed National Service?" with those options goes to the plain enum entry, finds no `value_map` phrase and stops at `unknown` (sensitive, fail-closed). Request (architect, optional): treat a "not applicable" option like a decline option in `bool_shaped`.
4. `not_applicable` NS (female / foreigner) answers No to "Have you completed NS?" (literally true) and Yes to "Have you fulfilled your NS obligations?". "Are you liable for NS?" is deliberately not mapped.
STATUS: open

### 2026-11-02 researcher → coordinator (cc architect)
TYPE: handoff
RE: Q-60 / F-50, `docs/research/mail_status_brief.md`, `docs/research/prior_art.md` (section Q-60), branch `int/Q-60-mail-status` (not committed: no shell)
BODY: The stage-A brief is ready for the architect.
1. Access route: IMAP with the existing app password (D-52/D-72), read-only, headers first. Gmail API `gmail.readonly` is the documented fallback if Google withdraws app passwords. IMAP + XOAUTH2 is rejected: it needs the full `https://mail.google.com/` scope.
2. Cursor, per (account, `\All` or `\Junk` mailbox found by special-use): the resolved name, UIDVALIDITY, the highest fully processed UID and the last scan time. Plus an account-wide X-GM-MSGID dedupe set. First sync: from the earliest open `applied_at` minus 1 day, at most 180 days back.
3. Finding (src, not mine): `apply/mail.py` hard-codes `[Gmail]/Spam`, so on accounts showing `[Google Mail]` Spam is silently skipped. It should use the `\Junk` lookup. Also, `VERIFY_WORDS` contains "confirm", which also appears in acknowledgements.
4. Decisions needed. Owner: which mailboxes; whether offer and rejected are set automatically or only proposed. Architect: HireVue as assessment or interview; posting-closed as its own state or rejected; "kept on file" alone.
5. Request: an owner-consented, header-only From-domain census of the application mailbox (S-4 style, nothing committed). It would confirm the senders tagged K in §3 and give shapes for synthetic golden cases.
STATUS: open

### 2026-11-02 researcher → coordinator (cc tester, architect)
TYPE: handoff
RE: Q-60 WP-R1, F-50k/t, `config/mail_rules.yaml` (new), `docs/research/mail_status_brief.md` Appendix A; worktree `.claude/worktrees/feat-Q-60` (not committed: no shell)
BODY: `config/mail_rules.yaml` v1 is written (187 lines, ASCII, schema MS §6.1 with E1).
1. **Contents.**
   - 26 platforms: 15 ATS, 8 assessment, 3 scheduler. Workday has `tenant_from_local_part` with `tenant_sites: [myworkdayjobs.com]`; Oleeo has `tenant_from_subdomain` with `tenant_sites: [tal.net]`.
   - 12 job boards, 31 company suffixes, 20 common-word names.
   - Gates: auto_reply 3, account 6, job_alert 6, outreach 4.
   - Phrases: acknowledged 5, assessment 9, interview 11 (one with `calendar: true`), offer 6, rejected 11, withdrawn 5, posting_closed 5, kept_on_file 3, portal_update 3.
   - Weak words in every category. `dominates` is copied verbatim from MS §6.1.
2. **Checked by reading only:**
   - 77 unique ids matching `[a-z0-9_.]+`;
   - every lookbehind is a fixed-width literal;
   - every `re` is single-quoted and has no apostrophes (`.` stands for one);
   - domains are lower-case with no `@`;
   - parentheses checked by hand.
   Please run `python tests/run_tests.py -k mail_rules` once S1 and T2 land. A `re.error` would name the entry.
3. **Tester:** golden cases worth adding for the guards (Appendix A.3).
   - An acknowledgement that says "if you have not heard from us within 4 weeks, please assume your application has been unsuccessful" → acknowledged.
   - An acknowledgement that says "if shortlisted, we will contact you to schedule an interview" → acknowledged.
   - "we are pleased to offer you the opportunity to attend an interview" → interview.
   - "we'd be pleased to offer you feedback" inside a rejection → rejected.
   - An acknowledgement whose privacy footer says "we will keep your CV on file for 12 months" → acknowledged.
   - "Please confirm your email address" → account gate. "This email confirms we received your application" → acknowledged.
4. **Architect, questions:**
   (a) A HireVue on-demand invite whose subject is a bare "Interview invitation" resolves as interview, because interview dominates. Should the platform's `kind: assessment` tie-break interview vs assessment? That is code, not data.
   (b) Assessment centre and superday invitations are filed under interview. Veto if you prefer assessment.
   (c) The account gate holds the phrase "confirm your email" (not the bare word). Confirm that this fits MS §6.2.
5. **K entries** (unverified domains and the new additions) are listed in brief Appendix A.2.
STATUS: open

### 2026-11-10 researcher → coordinator (cc tester, software-engineer)
TYPE: handoff
RE: Q-94 / WP-A04 (D-75, F-32, F-33), `config/questions.yaml`, branch `eng/Q-94-gate-prep` (NOT committed: this agent has no shell)
BODY: The four rows `singapore_status.authorised_to_work.SG/.US` and `requires_sponsorship.SG/.US` are replaced by two `kind: country_bool` rows keyed `singapore_status.authorised_to_work` and `singapore_status.requires_sponsorship`. Synonyms = the QD 8.3 minimum set plus every phrase of the four old rows (country-suffixed phrases kept). No country excludes. `without ...` phrases only on the authorised row; sponsorship row `exclude: [without]`. Residency and work-pass rows untouched (one comment updated: `requires_sponsorship.SG` -> `requires_sponsorship, D-75`); "require an employment pass" stays on the sponsorship row, so the line-338 behaviour holds.
Consumers of the old keys:
1. src/jobscraper/apply/locks.py:179-184 (L4, `country_bool` branch -> `resolve._tier2_country_bool`): works with the new keys. locks.py:44,151-162,185-188 (`WORK_RIGHTS_PREFIXES` / `_work_rights_bool`, per-country rows) is now reached only by fixtures still using per-country keys (tests/fixtures/apply/questions.sample.yaml:5,10); harmless, optional cleanup later.
2. src/jobscraper/apply/resolve.py:63-64 (`COUNTRY_BOOL_KEYS`), 317-322 (loader), 924-925, 968-992 (`_tier2_country_bool`, `which = r.key.rsplit(".",1)[1]`): built for the new keys (WP-P9). No change.
3. src/jobscraper/apply/facts.py:454-461: handles profile paths `...authorised_to_work.<CC>`; `rule_match` now returns None for those paths (rule key has no country), so the value comes from `work_right` and `_kind`. Should still work; not run.
4. src/jobscraper/applicant.py:121 REQUIRED_PATHS already uses the map keys (WP-P9). No change.
5. TEST THAT WILL BREAK (tester scope): tests/test_apply_resolve_excludes.py:21,33-35 (`SG_KEY = "singapore_status.authorised_to_work.SG"`, `_sg_rule()` does `next(...)` over the real file -> StopIteration in tests at lines 57, 67, 81). This Q-29 pin tests the country excludes that D-75 removes by design. Needs: either point the three real-file tests at the new `singapore_status.authorised_to_work` row and assert the UK label resolves via `label_countries` to UK (not SG), or drop them (the two synthetic `_rule` tests at lines 38, 48 stay valid).
6. tests/test_apply_questions.py:214-240 (`"cfl"` US-or-Canada label expects rule_id `singapore_status.authorised_to_work` + CONFLICT): consistent with the new key; verify by running.
Verify not run (no shell): build-plan WP-A04 one-liner, `-k apply_resolve_rules`, `-k questions`, `-k locks`. Hand-checked against the one-liner's asserts: all pass by inspection.
STATUS: open

### 2026-11-11 researcher → coordinator (cc architect)
TYPE: handoff
RE: Q-100 / D-190, KA-3 (F-35, F-36, F-50), `docs/research/ux_accounts_brief.md` (written in the main checkout, NOT committed: no branch per the delegation; the Coordinator commits)
BODY: The brief benchmarks 8 job tools, 6 local/desktop apps and Workday/MyGreenhouse candidate accounts, and ranks 23 patterns with S/M/L effort (§5) plus 12 don't-copy items (§6). Top patterns: (1) a Connected accounts hub with one card each for Gmail, apply mailbox, Edge apply browser, Ollama and employer accounts; (2) one state vocabulary (Connected / Needs attention / Not connected / Paused); (3) a global attention badge plus an Inbox banner; (4) reconnect in place that keeps history (HA reauth rule); (5) test before save and Test now later; (6) an Employer accounts table, one row per Workday tenant, with Copy password and Open sign-in page and no password resets; (7) "No account needed" labels for Greenhouse, Lever and Ashby; (8) last checked, next check and last success on every card. Pattern 23 (an optional local app lock) is assess-only per D-190. Web calls: 28 of 30.
Open questions for the architect or owner: (a) a hub as its own tab, or a Settings section? (b) Should "Open sign-in page" for a tenant open in the Edge apply profile (pattern 6/22), given it holds the session? (c) Does the owner want pattern 23 (Windows Hello lock) assessed? (d) Should a board view (pattern 19) replace or sit beside the grouped Applications list?
Gaps: Raycast and 1Password were not researched. Teal, Huntr and Careerflow onboarding screens are known only from snippets or third parties. AIApply and LazyApply dashboards were not found.
STATUS: open

### 2026-11-11 researcher → coordinator (cc architect)
TYPE: review
RE: Q-100 stage E cross-review of `docs/architecture/q100_ui_design.md` (draft b3de745) against `docs/research/ux_accounts_brief.md` §5–§6; D-190..D-193
BODY: Verdict: **no BLOCKING points, 2 MAJOR, 6 MINOR.** The design adopts the brief well. The Gmail split, where `retrying` stays connected for 24 h and a refused login turns to attention, is a good adaptation of Home Assistant's rule: when a service is offline, retry quietly; when the password is invalid, ask the user (brief L2). No web calls used.
(1) Patterns 1–16:
| P | Verdict | Right? |
|---|---|---|
| 1 hub | adopted, as a Settings view | yes: the failure texts already point to Settings → Accounts |
| 2 vocabulary | adopted, plus `checking` | yes (see M1 and m1 on what counts as attention) |
| 3 badge + banner | adopted; dismiss is per session, keyed by id:code | yes |
| 4 reconnect in place | adapted: Gmail now, ATS accounts and the apply mailbox in W2 | yes (KA-3) |
| 5 test before save | adapted: model "Check again" in W1, `--test-first` in W2; no test PUT (R3) | yes; avoiding the test PUT also honours don't-copy #10 |
| 6 employer table | adapted: Copy password dropped (D-191); Open sign-in page and Enter password in W2 | yes. Missing the verified and usage columns (m4) |
| 7 no account needed | adopted | yes (see m5) |
| 8 last/next check | adopted for Gmail, model, Edge (last used) and employer accounts (last sign-in) | yes |
| 9 activity log | missing | the deferral is acceptable, but W1 links are cheap (improvement 4) |
| 10 disconnect with consequences | adapted: MailCard now; W2 "Forget" copy states what stays and what goes | yes |
| 11 where stored | adopted (`stored_in`, intro line, card lines) | yes |
| 12 resume first | adapted: deep link `#/profile/resume`; the parse-review diff is not in scope | acceptable; belongs to the profile owner later |
| 13 optional + Later | adopted | yes, but the counter mixes in optional steps (m2) |
| 14 readiness list, not a score | adopted ("3 things to fill in first: …") | yes |
| 15 pre-fill summary | deferred to Q-110 (D-192) | right owner; log it as a request to Q-110 |
| 16 mode visible | adapted to Settings → Apply only; the header chip was called "Q-110's call" | **no** (M2) |
MAJOR
- **M1** Local AI `unreachable` maps to attention, which lights the badge and the shell banner. If the owner doesn't keep Ollama running, both stay on permanently, and the banner stops meaning anything (it defeats P3). Fix (W1): attention only when something needs the model now (a run or apply is queued or running, or the last one failed for lack of the model). Otherwise show grey "Not running · Check again", not counted in the badge.
- **M2** Auto mode is visible only inside Settings → Apply. The shell (`App.vue`) is Q-100's file, and once Q-111 makes the mode editable, a live "Automatic" mode would be invisible everywhere else. Fix (W1): a masthead chip "Auto-apply on" linking to `#/settings/apply`, shown only when `/api/apply/status` returns `mode = auto` and hidden on 404 (LoopCV's master switch, brief U20). This is not a don't-copy issue; it is a safety gap.
MINOR
- m1 `check_failed` (a store-busy or vault blip) counts as attention, so one blip flashes the banner. Show it as neutral "Couldn't check", and count it only after 2 failed loads in a row.
- m2 The setup counter "5 of 9" counts optional and info-only steps, so it can never reach done for an owner who doesn't want Gmail. "Apply browser: created on first use" has no action. Count required steps only; render optional ones as "Optional"; make the browser line a note, not a step.
- m3 P9: add W1 links only, no new view: the Gmail card → "From your email" evidence; an employer row → the attempt behind `created_by_attempt` or the last sign-in.
- m4 The employer table wireframe omits `verified_at`, which is already in the schema. Show "Verified" or "Not verified" in the status column (it ties to F-36). "Used by N applications" can wait for W2, since it needs a query.
- m5 G6 (W2) defaults "Open apply browser" to my.greenhouse.io. That nudges a MyGreenhouse sign-in, which sits awkwardly next to "Greenhouse: no account needed". Its effect on forms is also unverified (auto_apply_brief open item 15; MyGreenhouse Quick Apply fills from a saved profile, brief E1). Default to the tenant's sign-in page or a blank page instead.
- m6 The Limits copy "no CAPTCHA wait" and the editable `captcha_wait_s` should say in plain words that JobScraper waits for **you** to complete the human check in the window and never solves it. That keeps the copy clear of don't-copy #9.
(2) Top improvements: M1 (attention only when it blocks something the owner uses; HA L2), M2 (auto-mode chip; LoopCV U20), m2 (required-only counter with optional items shown as optional; Teal's skip-and-reprompt, U6). Then m3 (Obsidian's log reached from the status, L5) and m5.
(3) Don't-copy check: no cloud account, no OAuth, no mass apply, no vanity score (readiness lists items), no silent accounts (the empty-state copy explains), no password reset ("won't try again"), no test that writes settings, no upsells. Only m5 and m6 sit near the list, and both are wording or defaults.
STATUS: open
