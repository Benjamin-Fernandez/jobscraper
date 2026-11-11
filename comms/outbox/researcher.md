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
