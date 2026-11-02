# Handover note (rewrite every session; ≤ 40 lines; history goes to `docs/planning/session_log.md`)

**Last session:** 2026-11-02, session 3 (resumed; 4 agents: tester on `int/Q-35-M`, lane R R3 adapt, architect COMPOSE_NEEDED + Q-45, S-5b agent Q-41 phase 1). **Branch/commit:** `personal`, pushed (`git log -1`). Suite 920/920 Python, web 279 + 1 skipped.

## Where we are
- M19 DONE. M20: D-78 LLM-driven form filler (ADR-0006, `docs/architecture/llm_fill_design.md`, `llm_fill_build_plan.md`, contracts v5). Design READY (stage E + re-check; D-81..D-86).
- Merged this session: int/Q-30 (Profile form + questions), Q-36 lenient profile (D-79), Q-39 review fixes + `data/*.tmp` ignore, S-5b spike, Q-35 design, tester T0/T1/T3 + T2 core + T4 lane-N oracles, lanes N (N1–N5) + R (R1–R2) with review fixes (090daf8). Live DB backed up to `%LOCALAPPDATA%\JobScraper\backups\jobscraper-pre-Q35NR-20261102-1415.db` before the SCHEMA 4 merge.
- Live app: Workday attempts stop as `unsupported_ats` (no fill loop until N6a). Greenhouse emailed-code path is live (D-85; a lone footer word after the code sentence → fails closed).
- S-5b: tenant A (wd1) submitted + confirmed. Tenant B (wd5): account exists, stopped at My Information; the owner has since filled `address_line2` → Q-41 READY.

## Not merged (branches kept; worktrees under `.claude/worktrees/`)
- Lane M `eng/Q-35-M-llmfill` b79df03 (worktree `agent-a4c24933cbd328c18`): M1–M5, review `docs/reviews/Q-35-lane-M.md` F1–F9 fixed, WP-Q5 built. Needs: tester pins for the review probes (in its outbox) + M5 capture/G-table oracles; architect adds `QuestionReason.COMPOSE_NEEDED` (rows saved as `no_rule` + note until then); merge; vitest + bundle rebuild (QuestionCard.vue changed).
- Lane R R3 `eng/Q-35-R-page` adc8f08 (first cut of `pagefill.fill_page`, unreviewed): needs the 3 tester fixture gaps (its outbox), lane M's interface changes (`s_values(profile, account_email)`, `field_sig(key=facts.hash_key(rctx))`, pick `sensitive=`/`deny=`), then review. Its choices to confirm at review: deadline → `transport_failed` "transport: timed out"; cache stores no second/corrective replies.

## Next 1–3 actions
1. Tester: lane-M probe pins + M5/G2–G12 oracles + R3 fixture gaps + T5 + `test_apply_flow_llm.py` (open list in `comms/outbox/tester.md`). Architect: COMPOSE_NEEDED + Q-45 (cover-letter compose, design gaps). Merge lane M, then R3 (after review), then N6a (lane N's F7 note) → N6b.
2. Q-41: resume the S-5b tooling at tenant B, two-phase per D-83 (fill to Review, stop, Coordinator reads answers row by row, then Submit). Use the CURRENT resume (changed 2026-11-02: StraitsX, no Tencent) and replace the earlier upload.
3. M20 gate: 5 Greenhouse dry runs + owner-approved Workday postings (D-83). Backlog: Q-44 refresh-from-resume, Q-43, Q-34, Q-32, Q-27, A04 (`country_bool` rows, before the gate), Q-15 docs.

## Owner notes
- 2026-11-02: new resume uploaded. On the owner's request the Coordinator re-ran `profile` (profile_version 4) and the master parse, and rewrote `data/applicant.yaml` experience/skills/education start (backup `data/applicant.prev.yaml`). Optional for the owner: job locations, Cantonese levels.
- Application Gmail + app password verified (address only in Coordinator memory). MyGreenhouse signed in on the JobScraper Edge profile.

## Watch out
- Agent worktrees start from master: briefs say `git switch -c <branch> personal`. Architect/researcher agents have no shell (Coordinator commits).
- Before every push: deny-list scan (session scratchpad `fixture_denylist.txt`, env `JOBSCRAPER_FIXTURE_DENYLIST`; personal, never commit). Live app on 8765; dev on 8768 with a DB copy.
- The scope guard blocks the Coordinator from writing `data/`; the auto-mode classifier blocks editing `.claude/scopes.json`.
