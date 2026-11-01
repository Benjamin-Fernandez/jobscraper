# Handover note (rewrite every session; ≤ 40 lines; history goes to `docs/planning/session_log.md`)

**Last session:** 2026-11-01, session 1 (kickoff). **Branch/commit:** `personal`, kickoff commit (see `git log -1`).

## Where we are
- Kickoff done: research (cloud port, tailor, auto-apply) in `docs/research/`, PRD r1 `docs/prd.md` (approved under the owner's delegation), harness (instructions, agents, hooks, scopes).
- M19 (cloud port) and M20 design start now. Nothing built yet.
- Open worktrees not ours: `../JobScraper-frontend` (M18, paused, branch `frontend-ux`, don't touch).

## Running or awaiting review
- See `06_work_queue.md` rows marked IN PROGRESS (Q-01 to Q-04 once started).

## Waiting on the owner
- Nothing blocking yet. Coming: `data/applicant.yaml` values + the application email (Q-13, after the design ships the template); a Gmail app password (Q-14).

## Next 1–3 actions
1. Start Q-01 (browser spike), Q-02 (engine port), Q-03 (UI port), Q-04 (apply design) in parallel.
2. When Q-04 lands: Q-05 tailor design with the same architect; then Q-06, Q-08, Q-09.
3. Merge M19 lanes (Q-12), rebuild the bundle in the main checkout, push.

## Watch out
- The live app runs from this checkout on 8765; dev instances use 8768 with a copied DB.
- New agent definitions load next session; until then spawn `general-purpose` with the role brief.
