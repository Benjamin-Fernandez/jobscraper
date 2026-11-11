# Session log (append-only; newest at the bottom)

One entry per session. Older handover notes end up here, so `handover.md` stays short.

### 2026-11-01: session 1 (kickoff, retrofit)
- **Done:** project kickoff in retrofit mode on branch `personal`. Three research briefs (cloud port report, ATS resume tailor, auto-apply) in `docs/research/`. PRD r1 `docs/prd.md` (M19–M22) approved by the Coordinator under the owner's delegation. Harness scaffolded (CLAUDE.md, instructions/, agents, hooks, scopes, outboxes); hooks probed.
- **Decisions:** D-01, D-02, D-50 to D-63 (`instructions/02_status.md` §4). Owner: Standard team without a security reviewer; fully automatic submission that fails properly; IMAP for verification; merge and push allowed.
- **Next:** Q-01 to Q-04 in parallel.

## 2026-11-02 (session 1, continued)
- M19 merged and pushed (cab10af, bundle e6b33d7): 410/410 Python, 220+1 web; D-66 abort guard, TD-01.
- M20 dossier merged: test plans (Q-08), build plans (Q-09), tailor patch + D-68/D-69 (Q-19), seeds (Q-20).
- Owner: Workday is the biggest problem → D-70 (Workday-first M20, MyGreenhouse autofill, tailored resume always replaces autofilled; real accounts + auto-submit allowed at 2 Workday employers). Q-22 design delta merged (contracts v3).
- Lane T (tailor) and lane P (profile + resolver) merged; Q-21 oracles + guards; suite 469/469.
- Owner gave the application email (kept out of the repo; Coordinator memory). Stored IMAP secret is not an app password; MyGreenhouse sign-in landed outside the JobScraper profile.
- Owner stopped the session: lanes B, V, tester paused with work committed on their branches (see handover).

## 2026-11-02/03 · session 2 (continued, paused by the owner)
- Merged + pushed: int/Q-30 (D-74 Profile form + F-13 questions, D-75, tier-3 memory; review APPROVE WITH FIXES), Q-36 lenient profile (D-79), Q-39 review fixes F2/F6/F7 + `data/*.tmp` gitignore (Q-42 defect pin), S-5b spike (LLM-driven Workday: tenant A submitted + confirmed, tenant B fail-closed on a required field), Q-35 D-78 design (ADR-0006, contracts v5) + amendment + re-check READY, tester T0/T1/T3/T2-core/T4-lane-N, lanes N + R with review fixes (920/920).
- Decisions D-79 (lenient profile), D-80 (finish tenant B with spike tooling), D-81 (NF-07 Workday deviation + conditions), D-82 (locks stay deterministic), D-83 (gate count 5 GH dry runs; audit read row by row; fresh owner approval for gate postings), D-84 (re-check R1–R4), D-85 (Greenhouse code pattern), D-86 (lane M F7/F8 tightenings, F9 interim compose_needed).
- Owner: new resume; profile re-derived and applicant.yaml experience/skills rebuilt on request; address_line2 filled.
- Open at pause: lane M (b79df03) and R3 (adc8f08) unmerged; Q-41, Q-44, Q-45 queued.

## 2026-11-02 · session 3 (resumed, paused by the owner)
- Q-41 done: tenant B Workday application filled to Review by the S-5b tooling, read row by row by the Coordinator, submitted once, "Applied" (merged 59967d7). Owner gave job locations (Singapore ×3) and kept the tailored PDF and AWS.
- Owner rules: D-87 declaration-type questions → No; D-91 free from restrictive covenants, willing to sign NDAs. Coordinator decisions D-88 (military/NS labels sensitive), D-89 (government wording beats prior/current employment), D-90/D-90a (declaration frame gates after the WP-Q48 review), K-3 (possible flaky filter test).
- Q-46 defects (location from home city, ungrounded skills, cited-fact relevance, disability source, Workday Next wait) pinned and fixed by lane M; lane M hierarchical how-heard fit (e2414c5).
- Q-48 designed (architect), built (WP-Q48), reviewed: needs fixes (frame-blind classification). Fix round was running at the pause (8393f98, not verified).
- R3 reviewed (merge after fixes); lane R fixed F1–F6, F8, F9 (2add8ee); re-review was stopped at the pause.
- int/Q-35-M 3aadc13: lane M + WP-Q48 (first build) + tester pins; 1007/1024, the 17 = WP-Q48 fix-round pins. Nothing new merged into personal from the build this session (only Q-41 and records).

## 2026-11-02 · Q-60 session (separate Coordinator session, branch `int/Q-60-mail-status`; paused by the owner)
- Owner request D-90: application status from email (opt-in Gmail, incremental from the last processed message, automatic status updates), on a separate branch. Ran in parallel with the session-3 Coordinator on `personal`; IDs Q-60/D-90+/F-50 chosen to avoid collisions; all work in worktree `feat-Q-60`.
- Stage A brief (researcher; IMAP app password recommended over Gmail API OAuth: 7-day Testing-mode token expiry), stage B design + BP + ADR-0007 (architect), stage E by the Coordinator (READY; amendment E1 Oleeo `tal.net` tenants), R2 header-only scan of the application mailbox with owner consent (special-use folders present; ATS mail dkim/spf/dmarc pass; Oleeo found), rules v1 (researcher), S0 + T0 merged into int.
- Decisions D-90, D-91, D-92. Owner answers: application Gmail first; header scan yes.
- Paused mid-build: lanes S, I, F and the tester stopped on the owner's word; state in the handover Q-60 block.

## 2026-11-07 · Q-60 session (resumed; merged)
- Lane F review fixes (D-157, D-158, D-159), tester T5/T6 and pins merged on int; IDs renamed into D-150..D-169 (D-155). int e0e97e4: 1106/1106.
- X1 dev check on a DB copy (8769). Owner dry run on a fresh copy: 19 read, 0 changes (D-160; untracked tenant B application → Q-72).
- Live DB backed up; merged into personal c20332a; suite 1106/1106, vitest 296/1 skipped, bundle rebuilt, smoke OK; pushed.

### 2026-11-07 session (Q-70 UX + Q-71 details form)
- Resumed Q-70 after an interruption: merged lanes A, B, D; lane C + C4 KeepAlive; Overview page (E); tester pins for each. Owner reported the details form ("can't enter my desired salary"): fixed the salary defect, reviewer audit (24 gaps), lanes F (form) + G (schema), browser pass incl. 390px fixes (rail containing block, country rows, Companies switcher). Merged Q-60 from personal into int (Applications.vue conflict resolved; assessment stage colour moved into StatusSelect.vue). Merged into personal e5d939e, bundle 370feab, pushed. web 481/482, Python 1122/1122.
- Q-72: dismissed-job path found for the owner (Inbox → All runs → Not interested); re-test on a scratch copy confirmed the backfilled Rejected suggestion. D-161 row 7a `maybe_untracked` designed (architect), built (engineer), pinned (tester, 10 oracles + review F1/F2), reviewed APPROVE; merged into personal 4c6133f; 1139/1139, vitest 482/1 skipped.

## 2026-11-07 · Q-60 session (continued): M20 Q-35/Q-48 merged
- Q-48 fix round suite 1020/1024 → 3 stale pins/fixture fixed (test-only, spec-cited) → 1023/1024 (test_filter env). Re-review MERGE; F11 fixed + pinned on the sync branch.
- R3 re-review of lane R fixes: MERGE (F12-F14 → Q-80). Lane M fit e2414c5 + lane R + Q-48 merged into int/Q-35-M; personal merged into int (contracts/applicant/store conflicts: keep both).
- Merged into personal 7ba7597; 1262/1262, vitest 498/1 skipped; bundle 4b18695; smoke 16/16; pushed. Owner declarations written (D-162). Worktrees/branches removed. Coordinated order with the parallel session (wave 3 + Q-74 after).

## 2026-11-07 (jobscraper-89, UX session, continued): wave 3 merged; Q-74 in review
- Merged int/Q-75-wave3 into personal (da515d2, bundle 129e8ef, pushed): Q-75 lanes I+J, Q-76 application detail, Q-44/Q-73 resume refresh (D-106). Tester pins: vitest 623 + 1 expected fail; Python 1323/1323. Smoke 8774 on a DB copy: 17/17 GET, all tabs, no console errors. Coordinated with jobscraper-2f, which merged M20 (7ba7597) and built its bundle first.
- Q-74: review APPROVE WITH FIXES (F1 HIGH tier-5 grounding on S values) → fix round → re-review (R1 over-blocking, R2 form wording) → D-108 gate → pre-merge round (R1/R2/Q-77 + §4 llm_fill hooks, e9d54bb, 1313/1314). Decisions D-107..D-109. Pending: hook pins + re-review 2.
- Cleanup: wave-3 worktrees/branches removed; orphaned Vite processes stopped by PID. Lesson: TaskStop on an `npx vite` background shell can leave node/esbuild children holding the worktree; find them by command line and stop by PID.

## 2026-11-08 · Q-60 session (continued): WP-N6a merged
- Owner "do it for me": live mail steps done (D-163). Q-81 architect decisions D-164..D-166.
- N6a built (950eee4); tester settled 19 oracle failures, found D1 (typeahead fits → D-167 fit_type) and D2 (hidden resume input), both fixed; review MERGE, F1 (auto never submits before N6b) + F2 (warm num_ctx) fixed.
- Merge order with the UX session: N6a first (Q-74 hit a _MONTHS collision). personal → N6a 6199e9d 1369/1369; merged 6001452; vitest 623; smoke 17/17; pushed. D-168.

## 2026-11-08 (jobscraper-89): Q-74 merged
- Re-review 2 → MERGE after N1/N2 (D-110, bf96b6e) and N4 (pins). int/Q-74 full suite first showed 78 failures: a semantic merge collision (Q-74 `_MONTHS` tuple shadowed by Q-44's `_MONTHS` dict in applicant.py; git merged cleanly). Fixed a93fdf4 (`_MONTH_LABELS`). N6a (6001452) merged first by agreement; resolve_ctx hunk resolved on the Q-74 side (683ba02, af11b3b).
- Merged 1b4143b + bundle 2045f06, pushed. Python 1443/1443, vitest 635 + 1 expected fail, smoke 8774 17/17 GET + 32/32 assets. Worktrees/branches for Q-74 removed.
- Lesson: always run the full suite on the integration tree after merging personal, even when git reports no conflicts; module-level name collisions only show at runtime.

## 2026-11-08 · Q-60/M20 session (jobscraper-25): N6b, Q-80, Q-82, Q-83 merged
- N6b merged b684d2a (review MERGE; F3-F5 → Q-92). Q-80 declarations part a50510d (D-164, D-169b). Q-82 D-170 bf664cf (one status question per label; under-answer + MEDIUM 1-4 → Q-83).
- Q-83 D-171: architect spec 629990f, tester pins 5f4bb30 (59 rows), engineer 6bc59da (declarations.py only), d170 docstring by the tester 70d6588, review 1ff95ab MERGE WITH FOLLOW-UPS (MEDIUM-1 place/time words cover a TRUE value → Q-90). Merged branch: 1551/1551, apply_e2e 13/13, apply_flow 137/137.
- ID ranges agreed with jobscraper-07: peer Q-84..Q-89, D-111..D-119; mine D-172..D-179, Q-90+. Peer owns Q-84 (the full suite skips Edge tests silently; gate apply merges on separate e2e/flow runs until it lands).
- Lesson: the engineer's scope hook refuses all of `tests/`, so docstring-only test edits still go to the tester.
- Q-80 rest on eng/Q-80-flow-fixes: tester pins first (48bdc98; 7 red on personal), engineer 366c098/1bc591f/ce8f0e4; D-172 (file trigger) and D-173 (a failed Add stays fail-closed; the engineer's log-only version rejected). Review MERGE WITH FOLLOW-UPS; M1 (delete count fail-closed, 07ed5f4) and M2 pins (aec1552) fixed before merge; M3/L1/pick-path note → Q-93.
- Lesson: a pin that accepts "any signal" (a log line) let a fail-closed stop be removed; pins for stops should require the stop.

## 2026-11-10 · Q-60/M20 session (jobscraper-25): Q-93, Q-90/Q-91
- Q-93 on eng/Q-93-flow: tester pins + engineer in parallel; review MERGE WITH FOLLOW-UPS, MEDIUM-1 (D-175 dropped real resume buttons: Résumé, Curriculum Vitae, Add document) and MEDIUM-2 (no trace of a skipped hidden input) fixed before merge (cbd1008, 177a7f6).
- Lesson: a narrowing heuristic on the resume control needs a recall probe of real button texts before merge, not only the false positives it was meant to drop.
- Q-90/Q-91 on eng/Q-90-declarations: architect D-176 spec (no shell: Coordinator committed), tester pins, engineer; review found MEDIUM-1 (company filler let "suspended by a company" answer No: an over-answer) and MEDIUM-2 (bare legal nouns blocked skills questions from the model) → D-177 + addenda fixed before merge. 167/167 declarations pins.
- Lesson: a class filler added for one phrase widens every label of that class; put such words inside the phrase instead.
- Q-94 gate prep: researcher WP-A04 (no shell: Coordinator committed), engineer F11/Q-43, tester pins incl. Q-46 e in Edge; review found F1 (an unknown place like Spain/London/APAC fell back to the job's country SG: a false Yes) and F2 (US/Canadian citizen-or-PR answered Yes from the Singapore row, pre-existing) → D-180/D-181 + demonym addendum fixed before merge.
- Lesson: a fallback to a default country must require a recognised or generic place; an unrecognised place is the owner's question.
- Q-45 compose: K1 (tailor/compose.py + C1-C7), K2 (targets, L8, card copy), K3 (step 7b, §19.3 loop, apply.compose off) built by one engineer lane; tester T7 + retargets; review MERGE WITH FOLLOW-UPS: M1 (a made-up proper noun at a sentence start passed C3) → D-183, M3 (no timeout on the compose call) → D-184, M4 (hint named a non-existent toggle) → D-185, fixed before merge. Merge conflict in locks.py (COVER_RE + L1_KEPT_NOTE) resolved by keeping both.
- Lesson: a sentence-start exemption for capitalised words needs an anchor (a source text or a common-word list); without one it lets invented names through.
- Lesson: the full suite takes ~25 min when other suites run in parallel; an Edge test reaching the flow must probe the browser first (`browser_page()`), or it fails on the leaked loop instead of skipping.
- Q-97 Edge pins (real apply_flow → fill_page → step 7b on a local page) found D1: a composed FILE row's audit value was read as a path, so "CI/CD …" was cut to "CD …" (D-186, fixed before merge). Lesson: a value whose meaning depends on the row's source needs an end-to-end pin; the flow oracles replace fill_page and could not see it.

## 2026-11-11 · session jobscraper-c6: state check, Q-110 auto-apply from the Inbox, D-200/D-201
- Owner asked for a working app with search/shortlist and auto-apply kept separate, auto-apply only on the owner's click, the model free to read the whole profile, minimal testing.
- Found: the search pipeline never imports apply; the live DB had no apply settings and no attempts; the UI had no way to start an attempt (CLI and Questions Retry only). Built Q-110 (router + Inbox button) on one engineer lane, no new tests; merged with the bundle after clearing it with two peer sessions.
- D-201 (whole-profile read): architect delta, KA-2 design review by the apply/tailor session (approve, F1-F4), build queued as Q-112 after Q-45.
- Lesson: check every branch for an ID before taking it (Q-96/D-182 were in use on an unmerged lane), and scope a renumber script to your own rows (it edited a peer's row).
- Lesson: `wc -l` on the handover is not enough with three live sessions: add to it, never rewrite another session's notes.
- 2026-11-12, same session: Q-112 (D-201) built by one engineer lane, pinned by the tester (6 tests, mutation-checked), reviewed independently (MERGE WITH FOLLOW-UPS), merged 56f37d7 on top of Q-100 lane A. The review and the tester both found that a rejected model quote is stored verbatim in the audit and cache rows (open since D-105): Q-113, spec D-202 written, in review with the apply session.
- Lesson: when a brief adds an assertion beyond what the review made binding (the evidence column), a red pin on a pre-existing gap should become a known-gap pin plus a queued fix, not a blocked merge or an unplanned edit in another session's files.
