# Handover note (rewrite every session; ≤ 40 lines; history goes to `docs/planning/session_log.md`)

**Last session:** 2026-11-02, session 3, paused by the owner. All agents stopped; every worktree clean. **Branch/commit:** `personal`, pushed (`git log -1`).

## Q-60 email status (branch `int/Q-60-mail-status`, worktree `.claude/worktrees/feat-Q-60`; resumed 2026-11-07)
- Owner asked (D-90→D-150): opt-in Gmail; while the app runs, read mail after the last processed one → update application status. IMAP app password, read-only, forward-only automatic updates. Application Gmail first. Merge into `personal` only with the owner's go-ahead; the first real sync from the owner's click.
- IDs: Q-60 reserves D-150..D-169 (D-155); old D-90/91/92/103/104 renamed to D-150..D-154 everywhere except dated outbox/session-log history.
- On int e2b3998: design + rules v1 + lanes S, I (with review fixes D-154 F1–F8 + T4 punctuation) + tester T0–T4 + review pins. Full suite 1040/1040, `-k mail_` 108/108 (5409278). Review `docs/reviews/Q-60-stage-imap-ui.md`.
- Lane F merged (136d44c): store + schema 5, `mailstatus_flow.py`, CLI `mail`, web timer `web/mailsync.py` + `routers/mail.py`. `-k mail_` 109/109, layering 13/13. D-156 settles lane F's open questions.
- Review of lane F: `docs/reviews/Q-60-flow.md` APPROVE WITH FIXES (FL-1 MAJOR poison mail wedges a mailbox; FL-2 no tests; FL-3..10 minor). Re-review: F1–F8 closed except F3 residual (5+ char names). Decisions D-157 (supersedes D-156 (2)). P1 docs committed 6fa1570. Full suite 1041/1041 at 136d44c.
- Built, reviewed, fixed: lanes S, I, F + tester T0–T6 + all review pins (D-154, D-157, D-158, D-159) merged; IDs renamed (e0e97e4). int e0e97e4: full suite 1106/1106, vitest 296 passed / 1 skipped, `-k mail` 191/191.
- X1 dev check done on a read-only backup copy of the live DB (scratchpad `x1/dev.db`), port **8769** (8768 is held by another session's dev instance since 10:00, not ours: leave it): migration 4→5 clean (schema 5, 5 mail tables, 112 applications intact), `/api/mail` + suggestions 200, timer off, `mail accounts list` / `mail sync` read nothing. No browser here: Settings card not seen visually.
- Waiting on the owner: (1) go-ahead for the first real sync (the owner's click, application Gmail) and where (dry run on a DB copy first, recommended); (2) go-ahead to merge into `personal` (back up live DB first; personal moved on with Q-70: expect conflicts in instructions/ and maybe Settings.vue; build the bundle in the main checkout; smoke).

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
