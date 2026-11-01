# Handover note (rewrite every session; ≤ 40 lines; history goes to `docs/planning/session_log.md`)

**Last session:** 2026-11-02, session 1 (continued). **Branch/commit:** `personal` (see `git log -1`), pushed.

## Where we are
- M19 (cloud port) DONE and pushed. M20 dossier (designs, plans, test plans, seeds) merged into `personal`.
- D-70 (owner): Workday is the priority; M20 now = Workday end to end + Greenhouse with MyGreenhouse autofill; tailored resume always replaces an autofilled one.
- Full suite on personal: 425/427; the 2 failures are D-69 state-machine oracles awaiting the tester (Q-21).

## Running (background worktree agents, branched from personal)
- Q-22 architect `arch/Q-22-workday-first`: Workday adapter spec, MyGreenhouse path, `apply open-profile`, backup email, `yes_if`, lane V into M20.
- Lane P `eng/M20-P-profile-resolver` (WP-P1..P6), lane B `eng/M20-B-browser-greenhouse` (WP-B1..B8), lane T `eng/M20-T-tailor` (WP-T1..T8).

## Waiting on the owner
- Application email (primary) in chat; confirm the backup `benjaminwrka@gmail.cm` (likely `.com`).
- Gmail app password into Credential Manager: target `jobscraper:imap:imap.gmail.com`, user = the Gmail address (command given in chat). A second one if the backup address is also used for verification.
- MyGreenhouse sign-in once in the JobScraper Edge profile (`%LOCALAPPDATA%\JobScraper\apply-profile`).
- Later: `data/applicant.yaml` from the template lane P ships.

## Next 1–3 actions
1. Q-21 tester (D-69 oracles + 3 dropped layering guards) once an agent slot frees.
2. On Q-22: merge it; spike S-5 (Q-23) on 2 owner-approved Workday employers — real sign-up + IMAP verify, record every step; stop at Review. Real submissions there happen through the built product at the M20 gate (owner allowed them, D-70).
3. Merge lanes P → T → B (B9 swap), then lane V (Workday), M20 gate.

## Watch out
- Agent worktrees start from master: every brief says `git switch -c <branch> personal`.
- Live app on 8765 runs from this checkout; dev instances use 8768 with a copied DB.
