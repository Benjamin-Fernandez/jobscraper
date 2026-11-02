# Handover note (rewrite every session; ≤ 40 lines; history goes to `docs/planning/session_log.md`)

**Last session:** 2026-11-03, session 2 (resumed; lanes B, V, tester Q-26, researcher A03 running). **Branch/commit:** `personal`, pushed (`git log -1`). Suite 469/469.

## Where we are
- M19 DONE. M20 (re-scoped D-70: Workday first, Greenhouse with MyGreenhouse autofill) in build.
- Merged into personal: dossier (designs, plans, tests, seeds), D-70 design delta (contracts v3), lane T (tailor, CLI `tailor`), lane P (profile + resolver, CLI `applicant check`), Q-21 oracles.

## Paused lanes (worktrees kept under `.claude/worktrees/`; resume each on its branch)
- Lane B `eng/M20-B-browser-greenhouse` (agent-ac5b…): B1–B6 committed (incl. MyGreenhouse prefill). Next: `git merge personal` (conflict in `config.py`: keep both append blocks; earlier attempt aborted), then B7 orchestrator, B8 CLI, B10 `apply open-profile`, B9 swap real resolver/tailor (`tailor_flow.tailor_for_apply`, `applicant.load`), B11, B12.
- Lane V part 1 merged (V1 vault, V2 `mail set-password`/`mail test`, V3 IMAP watcher; 501/501). Next lane V: V2 `accounts` half + V4 after lane B merges; V5–V7 after spike S-5.
- Tester Q-26 merged (487/487): fake IMAP (F4), D-70 oracles; gated helper names to confirm with lanes B/V (`keep_decision`, `choose_identity`, `workday.choose_entry`).
- Not started: WP-A03 `yes_if` rows (researcher; Q-26), Q-27 architect small items (`ResolveContext.job_title`, §5.4 `backup_email`).

## Waiting on the owner
- D-72: the owner switched the application Gmail account (address in Coordinator memory, not the repo); no backup email. Old Credential Manager entry deleted. Still needed: a 16-letter app password for the new account in `jobscraper:imap:imap.gmail.com` (the password pasted in chat was the account password: Gmail rejected it, not stored). Check: IMAP login test.
- MyGreenhouse sign-in inside the JobScraper Edge profile (`%LOCALAPPDATA%\JobScraper\apply-profile` does not exist yet).
- Fill `data/applicant.yaml` from `config/applicant.example.yaml`; `applicant check` passes.

## Next 1–3 actions
1. Resume lanes B, V and the tester (≤ 4 agents); researcher A03.
2. When the app password works: spike S-5 (Q-23) on 2 owner-approved Workday employers, stop at Review; tester records WP-F1 fixtures; lane V V4–V7.
3. M20 gate: Greenhouse dry runs + the 2 real Workday submissions (owner-allowed, D-70).

## Watch out
- Agent worktrees start from master: briefs say `git switch -c <branch> personal` (resumed lanes: just continue on their branch).
- Live app on 8765 runs from this checkout; dev instances use 8768 with a copied DB.
