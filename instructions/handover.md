# Handover note (rewrite every session; ≤ 40 lines; history goes to `docs/planning/session_log.md`)

**Last session:** 2026-11-03, session 2 (continued). **Branch/commit:** `personal`, pushed (`git log -1`). Suite on personal 789/789 Python, web 253 + 1 skipped.

## Where we are
- M19 DONE. M20 (D-70: Workday first, Greenhouse with MyGreenhouse autofill) in build. D-77: the owner allowed real accounts + automatic submission at Kyndryl (DevOps Engineer) and PayPal (Software Engineer). D-78: the local LLM fills every form generically (resume first, "import from resume" always, adapters = navigation only).
- Merged into personal: dossier, D-70 delta, lanes T (tailor), P (profile + resolver), V part 1 (vault, mail CLI, IMAP watcher), B (browser + Greenhouse + review fixes, Q-31 tests), Q-21/Q-26/Q-28 tests, Q-29 resolver fix, Q-30 design (contracts v4), S-5 signed-out spike.

## Running / ready to merge (worktrees under `.claude/worktrees/`)
- int/Q-30 MERGED + bundle built + pushed (70169be; 752/752, web 253+1; smoke 8768 OK). Review `docs/reviews/Q-30.md`: APPROVE WITH FIXES; F1–F7 routed (Q-39, Q-40).
- S-5b DONE + merged (e79745c): tenant A submitted + confirmed; tenant B account made, stopped at a required "Additional Address" (profile `address_line2` empty) → Q-41/D-80 after the owner fills it. Recordings (personal) in the session scratchpad `s5b/`. Q-35 design committed on `arch/Q-35-llm-fill` (63c62b3, worktree `arch-Q-35`); stage C (tester plan) + stage E (reviewer) running there, uncommitted by design: the Coordinator commits, marks READY, merges, then starts lanes M1/R1/T0–T1 in parallel (D-81, D-82).
- int/Q-36 MERGED + pushed (5ef94a6; 789/789; owner profile errors 0).
- `int/Q-39` (worktree `int-Q-39`, 6665e1c = personal + Q-39 review fixes F2/F6/F7): tester Q-42 adding oracles; then merge, `npm run build` in the main checkout (web change), smoke 8768, push. Remove the worktree after (its `web/node_modules` is a real install).

## Waiting on the owner
- `contact.address_line2` (Q-41) and the template placeholders in `data/applicant.yaml` ("Example Pte Ltd" experience, default skills). Application Gmail + app password verified (address only in Coordinator memory). MyGreenhouse signed in on the JobScraper Edge profile. `data/applicant.yaml` filled by the owner.

## Next 1–3 actions
1. Merge int/Q-39 after Q-42 (+ bundle rebuild). Q-41 Kyndryl once the owner fills `address_line2`.
2. S-5b report → Q-35 architect redesign around D-78 (generic LLM filler; folds in review F1/F3/F4 = Q-40, F1 before WP-Q1b) → lane V V2 accounts half, V4–V7 adjusted, WP-Q1b question capture in `apply_flow.py`, WP-F1 Workday fixtures.
3. M20 gate: Greenhouse dry runs + the 2 real Workday submissions (D-77).
- Backlog: Q-27 (`ResolveContext.job_title`, §5.4 `backup_email`), Q-32 (how-heard option mapping), Q-34 (web reaper run lock, M21), Q-15 docs (planner pastes `questions_build_plan.md` into `apply_build_plan.md`, PRD F-13 + D-75), QD text per D-76, S-5 report → `docs/architecture/spikes/S-5_workday.md`.

## Watch out
- Agent worktrees start from master: briefs say `git switch -c <branch> personal`. Architect/researcher agents have no shell.
- Live app on 8765 runs from this checkout; dev instances use 8768 with a copied DB. Before every push: grep the diff for personal data (public repo).
- The scope guard blocks the Coordinator from writing `data/`; the auto-mode classifier blocks editing `.claude/scopes.json`.
