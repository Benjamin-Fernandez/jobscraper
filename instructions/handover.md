# Handover note (rewrite every session; ≤ 40 lines; history goes to `docs/planning/session_log.md`)

**Last session:** 2026-11-02, session 3 (resumed; agents: tester on `int/Q-35-M`, lane R R3 adapt, architect Q-48 on `arch/Q-48-declarations` (worktree `arch-Q-35`)). **Branch/commit:** `personal`, pushed (`git log -1`). Suite 920/920 Python, web 279 + 1 skipped.

## Where we are
- M19 DONE. M20: D-78 LLM-driven form filler (ADR-0006, `docs/architecture/llm_fill_design.md`, `llm_fill_build_plan.md`, contracts v5). Design READY (stage E + re-check; D-81..D-86).
- Merged this session: int/Q-30 (Profile form + questions), Q-36 lenient profile (D-79), Q-39 review fixes + `data/*.tmp` ignore, S-5b spike, Q-35 design, tester T0/T1/T3 + T2 core + T4 lane-N oracles, lanes N (N1–N5) + R (R1–R2) with review fixes (090daf8). Live DB backed up to `%LOCALAPPDATA%\JobScraper\backups\jobscraper-pre-Q35NR-20261102-1415.db` before the SCHEMA 4 merge.
- Live app: Workday attempts stop as `unsupported_ats` (no fill loop until N6a). Greenhouse emailed-code path is live (D-85; a lone footer word after the code sentence → fails closed).
- D-77 done: tenant A (S-5b) and tenant B (Q-41, 2026-11-02: Review read row by row, one Submit, "Applied"; merged 59967d7). Defects found: Q-46 (a–e), Q-47; owner rule D-87 (declaration-type questions → No; memory `declarations-default-no`) → Q-48.

## Not merged (branches kept; worktrees under `.claude/worktrees/`)
- `int/Q-35-M` 3a99dce (worktree `int-Q-35-M`) = lane M b79df03 + architect COMPOSE_NEEDED/Q-45 design (ab53597). The tester is committing pins there (incl. the QuestionReason set pin, Q-46 a–c). Then merge into personal; vitest + bundle rebuild (QuestionCard.vue changed). Lane M then switches `no_rule`+note → COMPOSE_NEEDED.
- Lane R R3 `eng/Q-35-R-page` adc8f08 (first cut of `pagefill.fill_page`, unreviewed): needs the 3 tester fixture gaps (its outbox), lane M's interface changes (`s_values(profile, account_email)`, `field_sig(key=facts.hash_key(rctx))`, pick `sensitive=`/`deny=`), then review. Its choices to confirm at review: deadline → `transport_failed` "transport: timed out"; cache stores no second/corrective replies.

## Next 1–3 actions
1. Tester report → merge `int/Q-35-M`. Architect Q-48 report → commit on `arch/Q-48-declarations` → engineer WP + tester WP. R3 review → merge. N6a (lane N F7 note + Q-46 e) → N6b.
2. After Q-48 builds: the Coordinator writes the owner's D-87 values into `data/applicant.yaml` (owner asked; values only there).
3. M20 gate: 5 Greenhouse dry runs + owner-approved Workday postings (D-83). Backlog: Q-44 refresh-from-resume, Q-43, Q-34, Q-32, Q-27, A04 (`country_bool` rows, before the gate), Q-15 docs.

## Owner notes
- 2026-11-02: new resume uploaded. On the owner's request the Coordinator re-ran `profile` (profile_version 4) and the master parse, and rewrote `data/applicant.yaml` experience/skills/education start (backup `data/applicant.prev.yaml`). Job locations = Singapore ×3 (owner, Q-41). Optional: Cantonese levels.
- Application Gmail + app password verified (address only in Coordinator memory). MyGreenhouse signed in on the JobScraper Edge profile.

## Watch out
- Agent worktrees start from master: briefs say `git switch -c <branch> personal`. Architect/researcher agents have no shell (Coordinator commits).
- Before every push: deny-list scan (session scratchpad `fixture_denylist.txt`, env `JOBSCRAPER_FIXTURE_DENYLIST`; personal, never commit). Live app on 8765; dev on 8768 with a DB copy.
- The scope guard blocks the Coordinator from writing `data/`; the auto-mode classifier blocks editing `.claude/scopes.json`.
