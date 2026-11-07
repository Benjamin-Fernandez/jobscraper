# Handover note (rewrite every session; ≤ 40 lines; history goes to `docs/planning/session_log.md`)

**Last session:** 2026-11-02, session 3, paused by the owner. All agents stopped; every worktree clean. **Branch/commit:** `personal`, pushed (`git log -1`).

## Q-60 email status: MERGED into `personal` 2026-11-07 (c20332a)
- Feature live at the next app launch: Settings → Email updates (opt-in Gmail, IMAP app password, read-only). Timer every 10 min while the app runs; `JOBSCRAPER_MAIL_SYNC=0` for dev copies. Live DB backed up first: `data/jobscraper.pre-Q60-2026-11-07.db` (schema 4); migration 4→5 runs at launch.
- Verified on personal: full suite 1106/1106; vitest 296 passed / 1 skipped; bundle rebuilt; smoke on 8769 (DB copy): schema 5, 112 applications, 16/16 GET endpoints 200.
- Owner dry run (DB copy, D-160): 19 read, 0 changes, 0 suggestions, 0 errors; the owner confirmed the 17 skips. The 2 status emails were about tenant B the tenant B DevOps role (Q-41), which has no application row → matched only the 3 closed tenant-B rows → NONE `terminal` (by design). Owner: mark the tenant B DevOps role Applied in the live app, then connect Gmail; expect a `backfilled` suggestion → Rejected. Follow-up Q-72.
- Owner still to do (live app): Inbox → run selector All runs → open the collapsed "Not interested" section → Acme DevOps Engineer <req id> (dismissed 2026-10-26) → Applied; then Settings → Email updates → connect (address + app password) → Check now → accept the "Rejected" suggestion. Re-tested on a scratch copy 2026-11-07: ack → NONE owner_newer, rejection → SUGGEST backfilled (strong match). Q-60 worktrees and branches removed. Q-72 DONE (merged 4c6133f): mail matching only closed applications by employer alone → "may be about an application you haven't added" suggestion (D-161); expect occasional false hints from late generic rejections (one click).

## Q-70 UX + Q-71 details form: MERGED into `personal` 2026-11-07 (e5d939e, bundle 370feab, pushed)
- In the live app at its next launch: Overview home page (default route), Inbox flow (A), Applications (Active view, StatusSelect, Undo, follow-up cues) (B), shell job pill + toasts + KeepAlive (C), Profile drafts/save states (D); Q-71: expected salary now enterable, country/nationality as a name list (ISO validated), error summary with Go to, blank entries pruned, "4,500" accepted, section rail + Next needed, Yes/No declarations, show-when fields, file status, 2-column at ≥ 900px, 390px fits on every tab.
- Verified: vitest 481/482 (1 skip), Python 1122/1122, built bundle smoke on a DB copy (Overview default, no console errors), browser pass of the audit flows on a test applicant file.
- Owner to do: restart the live app; Profile → Application details: enter Expected salary; re-check Country and Nationality (old text box could save "SI").
- Kept: worktree `int-Q-70-ux` (branch int/Q-70-ux, merged) holds the owner's preview entries in its gitignored data/ (resume upload + details typed into the dev preview); delete only with the owner.
- Follow-ups: `shell-job.test.js` visibility test flakes under CPU load (fake timers); scope hook `python .claude/hooks/scope_guard.py` is relative and fails when an agent's cwd is web/ (keep agents at the worktree root, or make it `$CLAUDE_PROJECT_DIR`-based: owner/permission change); Q-71 audit §7 backlog (Q-44 refresh from resume for experience/skills; new fields); "Resume and titles" view shows the raw CLI log with paths after an upload (Q-73 candidate).

## Where we are
- M19 DONE. M20: D-78 LLM form filler. Design READY plus amendments D-87..D-91 (declarations). D-77 done: tenant A (S-5b) and tenant B (Q-41, "Applied").
- Live app unchanged by the build: Workday stops as `unsupported_ats`; Greenhouse path live. Known live defect until Q-48 merges: prior-employment phrases answer questions that don't name the employer (review F4); dry-run audits are read row by row before any real submit (D-83).
- Owner profile: job locations Singapore ×3 set. After Q-48 merges, the Coordinator writes the owner's values: `declarations.government_employment: false`, `declarations.willing_to_sign_nda: true` (owner asked, D-87/D-91). Memory `declarations-default-no`.

## Branches (not merged into personal; worktrees under `.claude/worktrees/`)
- `int/Q-35-M` 3aadc13 (worktree `int-Q-35-M`): lane M + WP-Q48 first build + all tester pins; 1007/1024, the 17 = WP-Q48 fix-round pins.
- `eng/Q-48-declarations` 8393f98 (worktree `agent-aaa227e35c71208c5`): fix round for review `docs/reviews/Q-48-and-lane-M-fixes.md` F1–F10 + D-90/D-90a/D-91. Stopped while running its final full suite: UNVERIFIED. Includes lane M 19495da.
- `eng/Q-35-M-llmfill` e2414c5 (worktree `agent-a4c24933cbd328c18`): hierarchical how-heard fit (`resolve.how_heard_fit`, `path_hits`); verified 72/72 llm_fill, 19/19 pagefill with lane R. Touches `deterministic_pick` (possible overlap with WP-Q48 F9).
- `eng/Q-35-R-page` 2add8ee (worktree `agent-ae3916b4525b736d9`): R3 + review fixes F1–F6, F8, F9 (F10 part); 1015/1017 before lane M's fit fix. Re-review of the fix commits not done (stopped).
- `arch/Q-48-declarations` 549e511 (worktree `arch-Q-35`): D-87..D-91 spec; already in int via eng/Q-48 merges up to edc7a04; merge the rest.

## Next 1–3 actions
1. WP-Q48: run the full suite on 8393f98 (merge int 3aadc13 + arch 549e511 if not yet in); make the 17 pins pass; then re-review (Q-48 review F1–F10, D-90/91).
2. Merge into int/Q-35-M: e2414c5 (lane M fit), eng/Q-48-declarations, then lane R after its re-review (resume the R3 reviewer: `docs/reviews/Q-35-R3.md`, append "Re-review (fixes)"). Full suite → merge int into personal; vitest + bundle rebuild (QuestionCard.vue); smoke on 8768; write the owner's D-87/D-91 values; push.
3. N6a (carry-overs: R3 F7 attempt-wide follow-up budget, F10 audit rows for applied answers, N1 deadline vs model_unavailable, Q-46 e Workday Next wait, FillServices builder name for `test_apply_flow_llm`) → N6b → M20 gate (D-83). Backlog: Q-47, Q-44, Q-45 build, Q-43, Q-34, Q-32, Q-27, A04, Q-15, review F7 (compound question).

## Watch out
- Agent worktrees start from master: briefs say `git switch -c <branch> <base>`. Architect/researcher have no shell (Coordinator commits).
- Before every push: deny-list scan (scratchpad `fixture_denylist.txt`; never commit it). Employer names → "Acme" or tenant labels. Live app 8765; dev 8768 with a DB copy.
- Concurrent full-suite runs slow everything and may flake `test_filter` (K-3).
- The scope guard blocks the Coordinator from writing `data/`; owner-requested profile edits go via a surgical Python replace.
