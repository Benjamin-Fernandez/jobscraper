# Plan: M15 — Cycle length, run ranges, and job titles (tier-ready)

**Source PRD**: `.claude/prds/jobscraper-v2.prd.md` (M15, added with this plan)
**Selected Milestone**: M15 — the user controls cycle, runs shown and titles searched
**Complexity**: Large (backend, CLI, web API, three tabs; ~25 files)
**Planned**: 2026-09-28 with the ECC `plan` skill. The user asked for plan → PRD →
implementation in one request, which is the confirmation gate.

## Summary
Three user controls, each built so a future tier (Free / Plus / Pro, see
`mullti_user_prd.md` §11, now in the jobscraper-cloud repo) only changes numbers, not code: (1) how often the
company cycle restarts, chosen in Settings from the options the plan allows;
(2) a run selector that opens on **All runs** and offers **Past week**, **Past
month** and **Choose runs…**, which opens a picker on the Runs tab (0-match runs
say "0 matches"); (3) a job-title editor on the Profile tab with up to 20
titles and Qwen recommendations (up to 20) drawn from the resume, field of
study, past internships and the current selection.

## Requirements (restated)
1. **Cycle** — the user picks the restart interval (1 / 3 / 7 / 14 / 30 days) in
   Settings; runs, `status` and the cadence hint all use it. Stored, not a config
   edit (config/ is read-only in Docker). Which intervals are offered is a
   property of the **plan**, not of the UI.
2. **Runs shown** — the selector's first option is **All runs** (and the default
   view). Then **Past week**, **Past month**, then **Choose runs…**, which takes
   the user to the Runs tab where any runs can be ticked and shown together. A run
   that accepted nothing says **0 matches** (and has nothing to show).
3. **Job titles** — the user adds/removes the titles the title filter searches
   for (max 20 on this plan) and can ask for recommendations (max 20), generated
   by Qwen from the resume, field of study, past internships and the titles already
   chosen. Recommendations are one-click adds. Limits come from the plan.
4. **Tier-ready** — one `Plan` object carries every limit (`cycle_day_options`,
   `max_target_titles`, `max_title_suggestions`); the server validates against it
   and the UI renders from it. The local install runs the `local` plan (= Pro).

## Design decisions
| # | Decision | Why |
|---|---|---|
| M15-D1 | `Plan` dataclass + `PLANS` registry in `config.py`; `config.yaml` `plan: local`. Free (7/14/30 days, 5 titles, 5 suggestions), Plus (3/7/14/30, 10, 10), Pro and local (1/3/7/14/30, 20, 20). | `config` is importable by every layer (web may not import stages). One place to change when tiers arrive. |
| M15-D2 | Effective cycle = stored `cycle_days` setting if the plan allows it, else `run.cycle_days`. Resolved by `Config.effective_cycle_days(stored)`, a pure function called by `pipeline`, `cli` and `web/control` with `store.get_setting("cycle_days")`. | Mirrors M11's batch-size precedence, but in one function instead of two copies that "must agree". |
| M15-D3 | Run selection is `all \| week \| month \| n[,n…]` end to end (`?run=`); `latest` stays accepted for old links. Week/month = runs that **finished** in the last 7 / 30 days. | One query string covers every choice; the server owns the clock. |
| M15-D4 | The Inbox opens on **All runs**. | Since M13 the Inbox is a queue of untouched roles; hiding older untouched roles behind "newest run" contradicts that. |
| M15-D5 | User titles live in the `settings` table (`target_titles`, JSON). While unset, the resume's titles are used. Setting them replaces `profile.target_titles` for the prefilter only. | User state belongs in the DB, not in a regenerated file (D-5). |
| M15-D6 | The prefilter cache key becomes `rules_hash` when titles are the resume's, and `sha256(rules_hash + titles)[:16]` when the user set them. Decisions (the model's cache) are untouched. | Changing titles re-runs only the free prefilter; nothing already judged is paid for again, and nothing is re-checked on upgrade. |
| M15-D7 | Recommendations run as a background job (`jobscraper titles suggest`, job kind `titles`) and are stored in the `settings` table (`title_suggestions`, JSON with `field_of_study`, `experience`, `suggestions[{title, why}]`). | The web layer may not import a stage or a model transport (PRD 8.2); M11's job runner already gives progress, cancel and logs. |
| M15-D8 | The title prompt excludes titles already chosen and returns ≤ `max_title_suggestions`; the server filters again at read time. | A recommendation list that repeats your own titles is noise. |

## Patterns to Mirror
| Category | Source | Pattern |
|---|---|---|
| Stored setting + precedence | `src/jobscraper/web/control.py:28-45` | `stored_batch_size` / `effective_batch_size` / `settings_view` |
| API validation | `src/jobscraper/web/routers/settings.py:45` | `HTTPException(422, detail=...)` with the allowed range in the message |
| Background job | `src/jobscraper/web/jobs.py:39,66` | `KINDS` + `build(kind, opts)` → CLI argv |
| CLI verb | `src/jobscraper/cli.py:341,453` | `cmd_profile` + subparser with flags |
| Model call | `src/jobscraper/profile/resume_ingest.py:523` | fenced input, contract restated last, `backend.complete`, `_parse_json` |
| Python web tests | `tests/test_web_control.py:43,67` | `_world()` fixture, `TestClient`, one behaviour per test |
| Vue job polling | `web/src/composables/useJob.js:19` | `useJob({ kind, onFinish })` |
| Vitest | `web/tests/helpers.js` | `fakeApi` plays the contract; tests assert calls made |

## Files to Change
| File | Action | Why |
|---|---|---|
| `src/jobscraper/config.py` | UPDATE | `Plan`, `PLANS`, `Config.plan`, `effective_cycle_days` |
| `config/config.yaml` | UPDATE | `plan: local` with the tier table in a comment |
| `src/jobscraper/pipeline.py` | UPDATE | effective cycle; user titles + prefilter key |
| `src/jobscraper/profile/titles.py` | CREATE | user titles (parse, apply, cache key) and the Qwen suggestion call |
| `src/jobscraper/cli.py` | UPDATE | `titles show|suggest`; `status`/`doctor` use the effective cycle; `filter` uses user titles |
| `src/jobscraper/web/control.py` | UPDATE | cycle in `settings_view`; `titles_view` |
| `src/jobscraper/web/routers/settings.py` | UPDATE | `PUT` accepts `cycle_days` and/or `batch_size` |
| `src/jobscraper/web/routers/titles.py` | CREATE | `GET/PUT/DELETE /api/titles` |
| `src/jobscraper/web/routers/jobs.py`, `web/jobs.py` | UPDATE | `POST /api/jobs/titles`, kind `titles` |
| `src/jobscraper/web/data.py`, `routers/shortlist.py` | UPDATE | `week`, `month`, run lists |
| `src/jobscraper/web/api.py` | UPDATE | mount the titles router |
| `web/src/components/RunSelector.vue` | UPDATE | All runs / Past week / Past month / chosen / Choose runs… |
| `web/src/App.vue`, `web/src/runs.js` | UPDATE / CREATE | default `all`; run-value helpers (label, query, window) |
| `web/src/tabs/Runs.vue` | UPDATE | the picker: tick runs, "0 matches", Show in Inbox |
| `web/src/tabs/Settings.vue` | UPDATE | cycle choice from `cycle_day_options` |
| `web/src/tabs/Profile.vue`, `web/src/components/TitleEditor.vue` | UPDATE / CREATE | titles editor + recommendations |
| `web/src/tabs/Inbox.vue`, `Applications.vue` | UPDATE | new selector values |
| `web/src/api.js`, `components/JobStatus.vue` | UPDATE | titles API; job kind label |
| tests (Python + Vitest) | CREATE / UPDATE | every behaviour above |

## Tasks
### Task 1: Plans and the effective cycle
- **Action**: `Plan`/`PLANS`/`Config.plan`/`effective_cycle_days`; pipeline, `status`, `doctor` and `settings_view` use it; `PUT /api/settings` takes `cycle_days` (must be in the plan's options) and/or `batch_size`.
- **Mirror**: `effective_batch_size`, settings 422.
- **Validate**: `python tests/run_tests.py` (new: plan limits, cycle round trip, refused off-plan value, pipeline uses the stored cycle).

### Task 2: Run ranges
- **Action**: `resolve_run` handles `week`, `month`, `n,n`; `/api/shortlist` pattern widened.
- **Validate**: shortlist tests for each selector with a fixed clock.

### Task 3: User titles in the engine
- **Action**: `profile/titles.py` (`load_user_titles`, `apply`, `prefilter_key`, `normalise`); pipeline + `filter test/explain` use them.
- **Validate**: pipeline test — setting titles re-checks the prefilter, not the model.

### Task 4: Title recommendations
- **Action**: `titles.suggest(backend, resume_text, profile, current, limit)`; `jobscraper titles suggest` stores the result; job kind `titles`; `GET/PUT/DELETE /api/titles`.
- **Validate**: stub-backend tests (cap, excludes chosen, bad JSON), web API tests (limits from the plan).

### Task 5: Web — selector, Runs picker, Settings, Profile
- **Action**: as in Files to Change.
- **Validate**: `npm test`; `npm run build`; browser pass.

### Task 6: Docs and PRD
- **Action**: M15 in the v2 PRD with results; README commands.

## Validation
```bash
python tests/run_tests.py
cd web && npm test && npm run build
PYTHONPATH=src python -m jobscraper titles suggest   # live Qwen, stores recommendations
```

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| Changing titles re-checks every stored posting (21k+) | High (by design) | The prefilter is free and local; the model cache is untouched (M15-D6) |
| A short cycle (daily) outruns the batch size | Medium | Settings shows the runs/day the choice needs (existing hint, now with the new cycle) |
| Qwen returns titles that are too senior or too broad | Medium | Prompt pins the candidate's level and field; user picks, nothing is auto-added |
| Selector values change shape (`number` → list / range) | Medium | One helper module (`runs.js`) owns label, query and matching; tests cover each |
| Inbox default moves from newest run to All runs | Low | Decision M15-D4, stated in the PRD; one click back to Past week |

## Acceptance
- [x] All tasks complete (2026-09-28)
- [x] Validation passes - Python 296/296, Vitest 131/131, build, live Qwen run
- [x] Patterns mirrored, not reinvented
