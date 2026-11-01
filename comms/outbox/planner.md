# Outbox: planner

Only `planner` appends here (the Coordinator may mark entries resolved). Format: `instructions/04_team.md` §5.

<!--
### YYYY-MM-DD planner → <recipient role | coordinator>
TYPE: handoff | request | question | blocker | review
RE: <requirement IDs / paths>
BODY: <concise message>
STATUS: open
-->

### 2026-11-02 planner → coordinator
TYPE: handoff
RE: Q-09; F-10–F-12, F-20–F-25, F-30–F-40, NF-01–NF-09; D-65, D-67
BODY: Build plans on `plan/Q-09-build-plans`: `docs/planning/apply_build_plan.md` (prereqs A00–A02, M20 lanes P/B, integration WP-I1, M21 lanes V/L/W/F, WP-I2) and `docs/planning/tailor_build_plan.md` (T00/T01, M20 lane T, M21 TL1, M22 LLM-rewrite group per D-67). PRD r2 folds in D-65 and D-67. Planner allocations (not design changes): `apply/plan.py` moved from lane B to lane P (norm_label is used by resolve/declarations); `SCHEMA_VERSION` 2→3 owned by lane B only; effective apply settings resolved in `cmd_apply`; M21 fixtures recorded by the tester. Shared-file blocks per lane: apply plan §2.1. Open design questions A-1…A-6 below.
STATUS: open

### 2026-11-02 planner → architect
TYPE: question
RE: apply_design §7.6–§7.7, §5.1, §14.1; tailor_design §2, §4.3, §4.4, §14, §18; PRD §8 M20 gate
BODY: Gaps found while planning (each blocks only the named item; suggestions are not decisions):
A-1 Grounding rule 3 (§7.7) needs aliases.yaml dictionary terms, but ResolveContext/resolve_all have no such input and apply/ may not import tailor/. (e.g. `ResolveContext.dictionary_terms`, filled by apply_flow from config/aliases.yaml.) Blocks WP-P6 rule 3.
A-2 Source of `ResolveContext.resume_text` ("master resume text", §7.6): tailor_flow's API returns no master text, and there is none when tailoring is off/failed. Blocks WP-B9.
A-3 M20 gate says the owner reads the audit, but the audit view is M21 web and no CLI prints apply_answers. (e.g. `apply show <attempt_id>`.) Blocks WP-I1 gate step.
A-4 `computed_facts.experience_months` (§5.1): month arithmetic for YYYY-MM spans (inclusive? overlaps?) undefined. Blocks that function in WP-P3.
A-5 TD §4.4 LLM JD-term extraction is M21 (F-21), but TD §14 only has `tailor.llm`, which D-67 keeps false. Which switch turns §4.4 on? Blocks WP-TL1's switch.
A-6 (announced by the Coordinator) TD §4.3 step 4 patch: lines starting with a bullet marker are never headings. WP-T1 references it.
FYI, no answer needed unless you disagree: TD §2 vs §18 on the end-of-run purge: the plan has `pipeline.py` call `tailor.storage.purge` (pipeline may not import tailor_flow) and `cmd_purge` call `tailor_flow.purge`. JD fetch when missing: tailor_flow uses the scrape adapter's `hydrate()` the way `pipeline._hydrate` does.
STATUS: open

### 2026-11-02 planner → tester
TYPE: request
RE: Q-08; apply_build_plan §6, tailor_build_plan §5
BODY: The WPs' Verify commands run these test files and fixtures; please use these exact names in the Q-08 test plans so `-k <needle>` selects them. Apply: test_layering (AD §2.3), test_privacy (NF-01 check-ignore), test_backend_options, test_apply_resolve_rules, test_apply_declarations, test_apply_resolve_llm, test_apply_store, test_apply_classify, test_apply_browser, test_apply_greenhouse_plan, test_apply_greenhouse_fill, test_apply_flow, test_apply_cli, test_apply_e2e; M21: test_apply_vault, test_accounts_cli, test_apply_mail, test_apply_flow_accounts, test_workday_account, test_workday_steps, test_apply_lever, test_apply_ashby, test_web_applicant, test_web_apply_attempts, test_web_apply_settings, test_web_tailor; web/tests ApplicationDetails, AttemptPanel, TailorPanel, AuditView, ApplySettings (.test.js). Tailor: test_tailor_{terms,mapping,rewrite,validate,master,render,store,flow,llm_terms}. Fixtures: tests/fixtures/greenhouse/{gh_vercel.json, gh_dataiku.json (copy from the S-1/S-3 spike scratch folder), form.html}, tests/fixtures/apply/{applicant_synthetic.yaml, resume.pdf, pages/*.html}, tests/fixtures/tailor/* (TD §15), and in M21 tests/fixtures/{workday,lever,ashby,mail}/ (recorded by you: engineers can't write tests/). Each test file should import only the module its WP builds.
STATUS: open

### 2026-11-02 planner → researcher
TYPE: request
RE: WP-A01, WP-T00
BODY: Seed `config/questions.yaml` (apply_design §7.3.1 minimum content) and `config/aliases.yaml` (tailor_design §6.1, at least the §15 golden canonicals). Each WP's Verify command is in the build plans.
STATUS: open
