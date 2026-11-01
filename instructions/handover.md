# Handover note (rewrite every session; ≤ 40 lines; history goes to `docs/planning/session_log.md`)

**Last session:** 2026-11-02, session 1 (stopped by the owner: "stop here for now"). **Branch/commit:** `personal`, pushed (`git log -1`). Suite 469/469.

## Where we are
- M19 DONE. M20 (re-scoped D-70: Workday first, Greenhouse with MyGreenhouse autofill) in build.
- Merged into personal: dossier (designs, plans, tests, seeds), D-70 design delta (contracts v3), lane T (tailor, CLI `tailor`), lane P (profile + resolver, CLI `applicant check`), Q-21 oracles.

## Paused lanes (worktrees kept under `.claude/worktrees/`; resume each on its branch)
- Lane B `eng/M20-B-browser-greenhouse` (agent-ac5b…): B1–B6 committed (incl. MyGreenhouse prefill). Next: `git merge personal` (conflict in `config.py`: keep both append blocks; earlier attempt aborted), then B7 orchestrator, B8 CLI, B10 `apply open-profile`, B9 swap real resolver/tailor (`tailor_flow.tailor_for_apply`, `applicant.load`), B11, B12.
- Lane V `eng/M20-V-vault-mail` (agent-a379…): V1 vault committed; V3 `apply/mail.py` is a WIP commit (unverified). Next: finish V3 (+ V2 mail half), verify with the tester's fake IMAP.
- Tester `test/Q-26-d70-oracles` (agent-a0b5…): WIP commit (fake IMAP fixtures, MyGreenhouse fixtures, `tests/test_apply_mail.py`, `tests/apply_support.py`), not yet run. Next: finish D-70 oracles, run suite.
- Not started: WP-A03 `yes_if` rows (researcher; Q-26), Q-27 architect small items (`ResolveContext.job_title`, §5.4 `backup_email`).

## Waiting on the owner
- Real Gmail app password for the application address (the stored entry `jobscraper:imap:imap.gmail.com` is the normal password: Google rejects it). Check: IMAP login test.
- MyGreenhouse sign-in inside the JobScraper Edge profile (`%LOCALAPPDATA%\JobScraper\apply-profile` does not exist yet).
- Backup email spelling (`…@gmail.cm` → `.com`?).
- Fill `data/applicant.yaml` from `config/applicant.example.yaml`; `applicant check` passes.

## Next 1–3 actions
1. Resume lanes B, V and the tester (≤ 4 agents); researcher A03.
2. When the app password works: spike S-5 (Q-23) on 2 owner-approved Workday employers, stop at Review; tester records WP-F1 fixtures; lane V V4–V7.
3. M20 gate: Greenhouse dry runs + the 2 real Workday submissions (owner-allowed, D-70).

## Watch out
- Agent worktrees start from master: briefs say `git switch -c <branch> personal` (resumed lanes: just continue on their branch).
- Live app on 8765 runs from this checkout; dev instances use 8768 with a copied DB.
