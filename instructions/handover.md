# Handover note (rewrite every session; ≤ 40 lines; history goes to `docs/planning/session_log.md`)

**Last session:** 2026-11-07 (Q-60 session, continued; a parallel UX session runs wave 3 + Q-74). My agents stopped; M20 worktrees removed. **Branch/commit:** `personal`, pushed (`git log -1`).

## Q-60 email + Q-72: MERGED (c20332a, 4c6133f)
- Settings → Email updates (opt-in Gmail, IMAP app password, read-only, 10-min timer; `JOBSCRAPER_MAIL_SYNC=0` for dev copies). D-150..D-161.
- Owner to do (live app): Inbox → All runs → "Not interested" → Acme DevOps Engineer → Applied; then connect Gmail → Check now → accept "Rejected".

## Q-70 UX + Q-71 details form: MERGED into `personal` 2026-11-07 (e5d939e, bundle 370feab, pushed)
- In the live app at its next launch: Overview home page (default route), Inbox flow (A), Applications (Active view, StatusSelect, Undo, follow-up cues) (B), shell job pill + toasts + KeepAlive (C), Profile drafts/save states (D); Q-71: expected salary now enterable, country/nationality as a name list (ISO validated), error summary with Go to, blank entries pruned, "4,500" accepted, section rail + Next needed, Yes/No declarations, show-when fields, file status, 2-column at ≥ 900px, 390px fits on every tab.
- Verified: vitest 481/482 (1 skip), Python 1122/1122, built bundle smoke on a DB copy (Overview default, no console errors), browser pass of the audit flows on a test applicant file.
- Owner to do: restart the live app; Profile → Application details: enter Expected salary; re-check Country and Nationality (old text box could save "SI").
- Kept: worktree `int-Q-70-ux` (branch int/Q-70-ux, merged) holds the owner's preview entries in its gitignored data/ (resume upload + details typed into the dev preview); delete only with the owner.
- Follow-ups: `shell-job.test.js` visibility test flakes under CPU load (fake timers); scope hook `python .claude/hooks/scope_guard.py` is relative and fails when an agent's cwd is web/ (keep agents at the worktree root, or make it `$CLAUDE_PROJECT_DIR`-based: owner/permission change); Q-71 audit §7 backlog (Q-44 refresh from resume for experience/skills; new fields); "Resume and titles" view shows the raw CLI log with paths after an upload (Q-73 candidate).

## M20: Q-35 lanes M + R and Q-48 declarations MERGED into `personal` 2026-11-07 (7ba7597, bundle 4b18695, pushed; D-162)
- Verified: Python 1262/1262, vitest 498/1 skipped, smoke on a DB copy 16/16. Reviews: `docs/reviews/Q-35-R3-rereview.md`, `Q-48-and-lane-M-fixes.md` (re-review section) both MERGE.
- Owner values written: `declarations.government_employment: false`, `willing_to_sign_nda: true` (backup in the session scratchpad). F4 live defect (employer not named) is fixed.

## Where we are
- M19 DONE. M20: D-78 LLM form filler built through lanes M/N/R + declarations; Workday still stops as `unsupported_ats` live until the gate. Dry-run audits are read row by row before any real submit (D-83).
- Parallel session (jobscraper-89): wave 3 (int/Q-75-wave3: UI, Q-76, Q-44/Q-73) and Q-74 (model sees sensitive; hooks llm_fill: facts_text, field_view, recheck_entry, pick_option redaction, G3 guards, fill-cache key) merge after 7ba7597. Agreed: Q-80 waits for Q-74.

## Next 1–3 actions
1. After Q-74 lands: Q-80 (R3 F12-F14, Q-48 F12/F14; fill cache + pagefill reporting) with tester pins.
2. N6a (carry-overs: R3 F7 attempt-wide follow-up budget, F10 audit rows for applied answers, F11 constants, N1 deadline vs model_unavailable, Q-46 e Workday Next wait, FillServices builder for `test_apply_flow_llm`) → N6b → M20 gate (D-83).
3. Q-81 architect decisions (Q-48 F13/F15/F16 + the F11 closed-vocabulary line in §7.5 D-91). Backlog: Q-47, Q-45 build, Q-43, Q-34, Q-32, Q-27, A04, Q-15.

## Watch out
- Re-read queue/status before taking IDs (parallel session: Q-73..Q-79, D-100..D-109; mine Q-80/81, D-150..D-169). Message jobscraper-89 before merging into personal or building the bundle.
- Before every push: deny-list scan incl. req ids and employer names from real mail. Live app 8765; dev 8768/8769 with a DB copy.
- The scope guard blocks the Coordinator from writing `data/`; owner profile edits go via a surgical Python replace.
