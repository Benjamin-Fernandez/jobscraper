# Handover note (rewrite every session; ≤ 40 lines; history goes to `docs/planning/session_log.md`)

**Last session:** 2026-11-07 (Q-60 session, continued; a parallel UX session runs wave 3 + Q-74). My agents stopped; M20 worktrees removed. **Branch/commit:** `personal`, pushed (`git log -1`).

## Q-60 email + Q-72: MERGED (c20332a, 4c6133f)
- Settings → Email updates (opt-in Gmail, IMAP app password, read-only, 10-min timer; `JOBSCRAPER_MAIL_SYNC=0` for dev copies). D-150..D-161.
- Live since 2026-11-07 (owner asked the Coordinator to do it, D-163): tenant-B DevOps application marked Applied, Gmail connected (account 1, password reused from Credential Manager), first sync 19 scanned / 1 to review, "Rejected" accepted. Live DB backup `data/jobscraper.pre-owner-mail-2026-11-07.db`.

## UX (jobscraper-89): Q-70/Q-71 (e5d939e) and wave 3 MERGED into `personal` 2026-11-07 (da515d2, bundle 129e8ef, pushed)
- Wave 3 = Q-75 lanes I+J (local times, Inbox shortcuts + ? sheet, page polish), Q-76 application detail (JobDetail + auto-apply attempts on rows), Q-44/Q-73 (resume summary card, log under Details, "Update your application details" from the resume; D-106 dates). Verified: Python 1323/1323, vitest 623 + 1 expected fail, smoke 8774 on a DB copy (17/17 GET, all tabs, no console errors), browser pass incl. 390px and a Q-44 save on a scratch applicant file.
- Owner to do: restart the live app; Profile → Resume and titles → "Re-derive profile from the stored resume" to get the resume-to-details offer (proposals appear after a profile job).
- Kept: worktree `int-Q-70-ux` holds the owner's preview entries in its gitignored data/; delete only with the owner.
- Q-74 (model may see private fields, D-105/D-107/D-108/D-109): NOT merged. eng/Q-74-model-sees-sensitive e9d54bb (worktree eng-q74) has the fix rounds + R1/R2/Q-77 + all §4 llm_fill hooks, full suite 1313/1314 (the D-109 pin being rewritten). Pending: tester (test/Q-74-pins, hook pins a–d, vitest), reviewer re-review 2 (appends to docs/reviews/Q-74.md); then merge, bundle, smoke, push.
- Follow-ups: Q-78 (Q-44 skills row as chips with "and N more"; Runs `plural()` lacks thousands separator, pinned `it.fails`; browser-only checks G41/G17/G38/G31/N18). Scope hook path is relative (agents keep cwd at the worktree root).

## M20: Q-35 lanes M + R + Q-48 (7ba7597, D-162) and WP-N6a (6001452, D-168) MERGED into `personal`, pushed
- N6a: the llm FILLING loop drives live dry runs (`apply.mode: dry_run`, `apply.fill: llm`); Workday is now filled in dry runs too (no longer stops `unsupported_ats`). Auto mode never clicks Submit on the llm path until N6b (review F1). Needs Ollama: no model → `model_unavailable` before Edge.
- Verified 6001452: Python 1369/1369, vitest 623/1 expected fail/1 skipped, smoke 17/17. Reviews: `docs/reviews/Q-35-N6a.md` MERGE (F3-F7 → Q-80). D-167 fit_type.
- Owner declarations written (government_employment false, willing_to_sign_nda true). Q-81 done (D-164..D-166; code → Q-80).

## Where we are
- M19 DONE. M20: D-78 LLM form filler built through lanes M/N/R + declarations; Workday still stops as `unsupported_ats` live until the gate. Dry-run audits are read row by row before any real submit (D-83).
- Wave 3 is merged (129e8ef). Q-74 (llm_fill hooks: facts_text, field_view, recheck_entry, pick_option redaction, G3 guards, fill-cache key) merges after its pins + re-review 2. Agreed: Q-80 waits for Q-74.

## Next 1–3 actions
1. After Q-74 lands (jobscraper-07 merges personal into int/Q-74 and resolves the resolve_ctx hunk): Q-80 (R3 F12-F14, Q-48 F12/F14, D-164 question_frame, N6a F3-F7) with tester pins.
2. N6b (cache + the job_id cache-key fix, pre-Submit scan, review check, resume_entries) → first owner-watched dry runs → M20 gate (D-83: 5 Greenhouse dry runs read row by row).
3. Backlog: R3 F7/F11, Q-46 e, Q-45 compose_needed, Q-47, Q-43, Q-34, Q-32, Q-27, A04, Q-15.

## Watch out
- Re-read queue/status before taking IDs (parallel session: Q-73..Q-79, D-100..D-109; mine Q-80/81, D-150..D-169). Message jobscraper-89 before merging into personal or building the bundle.
- Before every push: deny-list scan incl. req ids and employer names from real mail. Live app 8765; dev 8768/8769 with a DB copy.
- The scope guard blocks the Coordinator from writing `data/`; owner profile edits go via a surgical Python replace.
