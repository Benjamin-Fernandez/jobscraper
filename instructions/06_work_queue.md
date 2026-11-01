# 06: Work queue

**Owner:** Coordinator. **Protocol:** `05_workflow.md`.
**States:** `BACKLOG` · `READY` · `IN PROGRESS` · `IN REVIEW` · `REWORK` · `BLOCKED` · `DONE`

The handover note lives in `handover.md`. This file holds only the queue and short notes. **∥** marks items that can run as parallel lanes now.

| ID | Item | Owner role | Depends on | Pri | State | Rework | Acceptance |
|---|---|---|---|---|---|---|---|
| Q-01 ∥ | **Spike S-1 + S-3 (browser):** Playwright drives Edge 156 headed on a dedicated persistent profile; which Playwright default flags block password saving and sync; dry-run fill of 2 real Greenhouse postings (no submit), react-select + upload; detect reCAPTCHA iframes | software-engineer (spike) | — | P0 | IN PROGRESS | 0 | `docs/architecture/spikes/S-1_S-3_browser.md` answers each question with evidence (screenshots under the scratch folder, not `data/`) |
| Q-02 ∥ | **M19 engine port** C-1 to C-8, C-22 (cloud report §1, §3a) | software-engineer (top) | — | P0 | IN PROGRESS | 0 | `python tests/run_tests.py` green; behaviour per F-01 to F-05, F-07 |
| Q-03 ∥ | **M19 UI port** C-10, C-12 to C-18 (cloud report §1, §3) | software-engineer | — | P1 | IN PROGRESS | 0 | `cd web; npx vitest run` green; `npm run build` succeeds; F-06 |
| Q-04 ∥ | **Design KA-1/2/3:** `docs/architecture/apply_design.md`, `src/jobscraper/apply/contracts.py`, store tables, config schema, ADRs (browser route, vault) | architect | research done | P0 | IN PROGRESS | 0 | `05` §5 design checklist; maps F-10, F-30 to F-40, NF-01 to NF-09 |
| Q-05 | **Design KA-4:** `docs/architecture/tailor_design.md`, `src/jobscraper/tailor/contracts.py` | architect | Q-04 (same agent) | P0 | IN PROGRESS | 0 | maps F-20 to F-25 |
| Q-06 | **Spike S-2:** Qwen3-14B bullet rewrite on golden cases A–C + 3 real JDs at temp 0.25: validator rejections, latency | software-engineer (spike) | Q-05 draft | P0 | BACKLOG | 0 | `docs/architecture/spikes/S-2_tailor_llm.md` with numbers |
| Q-07 | Port cloud tests for M19 (test_h1, test_small_model*, test_schedule_rule, test_net, D-33 adapter cases, web h1/ux1) | tester | Q-02, Q-03 merged | P1 | BACKLOG | 0 | ported tests pass on `personal` |
| Q-08 | Test plans: `tests/plans/apply_test_plan.md`, `tests/plans/tailor_test_plan.md` | tester (top) | Q-04, Q-05 | P0 | BACKLOG | 0 | `05` §5 test-plan checklist |
| Q-09 | Build plans M20 + M21: `docs/planning/apply_build_plan.md`, `tailor_build_plan.md` with lanes | planner | Q-04, Q-05 | P0 | BACKLOG | 0 | `05` §5 build-plan checklist |
| Q-10 | Cross-review (stage E) → READY TO BUILD | Coordinator chairs | Q-04, Q-05, Q-08, Q-09, Q-01 | P0 | BACKLOG | 0 | zero blocking issues |
| Q-11 | M20 build lanes (from Q-09) | software-engineer ×3 | Q-10 | P0 | BACKLOG | 0 | per WP `Verify:` |
| Q-12 | M19 merge + live check on a copied DB (port 8768) | Coordinator | Q-02, Q-03 | P0 | BACKLOG | 0 | M19 gate |
| Q-13 | Owner: fill `data/applicant.yaml` from the template; give the application email | owner | Q-04 (template) | P0 | BACKLOG | 0 | `python -m jobscraper applicant check` passes |
| Q-14 | Owner: Gmail app password into Credential Manager (instructions from the design) | owner | Q-04 | P0 | BACKLOG | 0 | spike S-4 reads a test message |
| Q-15 | Docs: OVERVIEW/README/DESIGN updated for tailor and auto-apply ("never logs in anywhere" changes) | planner | M20 | P1 | BACKLOG | 0 | docs match the app |

## Notes
- 2026-11-01: `personal` is the integration branch (plays `main`); the paused M18 worktree is not touched (D-63).
