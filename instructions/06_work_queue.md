# 06: Work queue

**Owner:** Coordinator. **Protocol:** `05_workflow.md`.
**States:** `BACKLOG` · `READY` · `IN PROGRESS` · `IN REVIEW` · `REWORK` · `BLOCKED` · `DONE`

The handover note lives in `handover.md`. This file holds only the queue and short notes. **∥** marks items that can run as parallel lanes now.

| ID | Item | Owner role | Depends on | Pri | State | Rework | Acceptance |
|---|---|---|---|---|---|---|---|
| Q-01 ∥ | **Spike S-1 + S-3 (browser):** Playwright drives Edge 156 headed on a dedicated persistent profile; which Playwright default flags block password saving and sync; dry-run fill of 2 real Greenhouse postings (no submit), react-select + upload; detect reCAPTCHA iframes | software-engineer (spike) | — | P0 | DONE | 0 | `docs/architecture/spikes/S-1_S-3_browser.md` answers each question with evidence (screenshots under the scratch folder, not `data/`) |
| Q-02 ∥ | **M19 engine port** C-1 to C-8, C-22 (cloud report §1, §3a) | software-engineer (top) | — | P0 | DONE | 0 | `python tests/run_tests.py` green; behaviour per F-01 to F-05, F-07 |
| Q-03 ∥ | **M19 UI port** C-10, C-12 to C-18 (cloud report §1, §3) | software-engineer | — | P1 | DONE | 0 | `cd web; npx vitest run` green; `npm run build` succeeds; F-06 |
| Q-04 ∥ | **Design KA-1/2/3:** `docs/architecture/apply_design.md`, `src/jobscraper/apply/contracts.py`, store tables, config schema, ADRs (browser route, vault) | architect | research done | P0 | DONE | 0 | `05` §5 design checklist; maps F-10, F-30 to F-40, NF-01 to NF-09 |
| Q-05 | **Design KA-4:** `docs/architecture/tailor_design.md`, `src/jobscraper/tailor/contracts.py` | architect | Q-04 (same agent) | P0 | DONE | 0 | maps F-20 to F-25 |
| Q-06 | **Spike S-2:** Qwen3-14B bullet rewrite on golden cases A–C + 3 real JDs at temp 0.25: validator rejections, latency | software-engineer (spike) | Q-05 draft | P0 | DONE | 0 | `docs/architecture/spikes/S-2_tailor_llm.md` with numbers |
| Q-07 | Port cloud tests for M19 (test_h1, test_small_model*, test_schedule_rule, test_net, D-33 adapter cases, web h1/ux1) | tester | Q-02, Q-03 on int/M19 | P1 | DONE | 0 | ported tests pass on `personal` |
| Q-08 | Test plans: `tests/plans/apply_test_plan.md`, `tests/plans/tailor_test_plan.md` | tester (top) | Q-04, Q-05 | P0 | DONE | 0 | `05` §5 test-plan checklist |
| Q-09 | Build plans M20 + M21: `docs/planning/apply_build_plan.md`, `tailor_build_plan.md` with lanes | planner | Q-04, Q-05 | P0 | DONE | 0 | `05` §5 build-plan checklist |
| Q-10 | Cross-review (stage E) → READY TO BUILD | Coordinator chairs | Q-04, Q-05, Q-08, Q-09, Q-01 | P0 | DONE | 0 | zero blocking issues |
| Q-11 | M20 build lanes (from Q-09) | software-engineer ×3 | Q-10 | P0 | IN PROGRESS | 0 | per WP `Verify:` |
| Q-12 | M19 merge + live check on a copied DB (port 8768) | Coordinator | Q-02, Q-03 | P0 | DONE | 0 | M19 gate |
| Q-13 | Owner: fill `data/applicant.yaml` from the template; give the application email | owner | Q-04 (template) | P0 | BACKLOG | 0 | `python -m jobscraper applicant check` passes |
| Q-14 | Owner: Gmail app password into Credential Manager (instructions from the design) | owner | Q-04 | P0 | BACKLOG | 0 | spike S-4 reads a test message |
| Q-17 | D-66 abort guard counts due companies only + TD-01 start-failure ERROR log | software-engineer | Q-07 | P0 | DONE | 0 | pipeline/web_control tests pass; a real 6-company run on a DB copy stamps its batch |
| Q-18 | Pins for D-66 and TD-01 (un-park `_skip_td01_…`) | tester | Q-17 | P1 | DONE | 0 | tests pass |
| Q-19 | Tailor design patch: bullet lines never headings; D-67 scope moves | architect | Q-06 | P0 | DONE | 0 | golden cases A–C still reproduce |
| Q-20 | Seed `config/questions.yaml` + `config/aliases.yaml` | researcher | Q-09 | P0 | DONE | 0 | WP Verify per build plans |
| Q-21 | Update the 4 D-69 oracles; restore the 3 guard tests dropped in the layering merge (`test_apply_and_tailor_meet_only_through_their_flows`, `test_foundation_modules_import_no_stage_or_orchestrator`, `test_the_layering_guard_catches_what_it_claims_to`) | tester | — | P0 | DONE | 0 | full suite green (447/447 on personal) |
| Q-22 | D-70 design delta: Workday-first M20, MyGreenhouse autofill then fill-the-gaps, tailored resume replaces autofilled, backup email on "already registered", enum yes/no labels (researcher gap), Greenhouse label match rule (tester item 4) | architect | — | P0 | DONE | 0 | design + plan updated; lane V WPs ready |
| Q-23 | Spike S-5: real Workday flow at 2 employers (sign-up, IMAP verify, every step recorded as fixtures), stop at Review; the real submissions there go through the built product at the M20 gate (owner-allowed, D-70) | software-engineer (spike) | Q-22; owner email + app password | P0 | BLOCKED | 0 | recorded pages + selector map |
| Q-24 | Owner: MyGreenhouse sign-in in the JobScraper Edge profile | owner | — | P0 | BACKLOG | 0 | autofill button works in S-6 |
| Q-25 | Lane V part 1: WP-V1 vault, V2 mail half, V3 IMAP watcher (`eng/M20-V-vault-mail`) | software-engineer (top) | Q-22 | P0 | IN PROGRESS (paused; V1 done, V3 WIP) | 0 | WP Verify |
| Q-26 | WP-A03 `yes_if` rows in `config/questions.yaml`; WP-F4 fake IMAP fixtures; new D-70 oracles (architect outbox) | researcher; tester | Q-22 | P0 | IN PROGRESS (tester WIP paused; A03 not started) | 0 | WP Verify |
| Q-27 | Architect small items: `ResolveContext.job_title` (contracts, additive), §5.4 template `backup_email` line | architect | — | P1 | BACKLOG | 0 | contracts import; B9 passes the title |
| Q-16 | Owner (optional): Edge sync test with `owner_sync_test.py` (spike report S-1c); if it passes, set `apply.edge_sync: true` | owner | Q-01 | P2 | BACKLOG | 0 | test password appears in the Default profile |
| Q-15 | Docs: OVERVIEW/README/DESIGN updated for tailor and auto-apply ("never logs in anywhere" changes) | planner | M20 | P1 | BACKLOG | 0 | docs match the app |

## Notes
- 2026-11-02: session stopped by the owner; lane B paused after B6 (B1–B6 committed, personal re-merge aborted on a config.py conflict). See handover.
- 2026-11-02: lane P merged (469/469). Owner can now fill `data/applicant.yaml` from `config/applicant.example.yaml` and run `applicant check`.
- 2026-11-02: lane T merged (CLI `tailor <job_id> [--report] [--force]`; `tailor_flow.tailor_for_apply` for B9); 440/442, the 2 = D-69 oracles (Q-21 running). Lane T reads `data/applicant.yaml` directly until P2 lands: swap to `applicant.load` in B9.
- 2026-11-02: designs on `arch/Q-04-designs` (ec5a471, 718b40e); merged into personal via int/M19 with the tester's layering update (Q-07 add-on). Q-06/Q-08/Q-09 branch from it.
- 2026-11-02: `int/M19` (worktree `.claude/worktrees/int-M19`) = personal + Q-02 (faddaa2) + Q-03 (eddc704); baseline 299/323 Python, 179/180 web, all known. Tester works on `test/Q-07-m19-tests` there; merge int → personal after green + a dry run on a copied DB. Known: Cancel on a stuck run can take ~30 s to answer (D-64 trade-off).
- 2026-11-01: Q-03 is done on `eng/Q-03-ui-port` (eddc704); held for an M19 integration branch with Q-02 so the tester (Q-07) fixes `web/tests/m16.test.js:278` (JD now renders blocks) and ports cloud tests before merging.
- 2026-11-01: `isolation: worktree` branches from `master` (origin HEAD); every lane brief must say "base your branch on `personal`".
- 2026-11-01: `personal` is the integration branch (plays `main`); the paused M18 worktree is not touched (D-63).
