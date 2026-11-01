# Resume tailor test plan (stage C, M20 → M21)

Design: `docs/architecture/tailor_design.md` (KA-4) · contracts `src/jobscraper/tailor/contracts.py` · PRD F-20–F-25, NF-01, NF-07. Profile: product first. Queue Q-08, tester, 2026-11-02.

**Rules:** synthetic people only; golden tests use `tests/fixtures/tailor/aliases_golden.yaml`, never `config/aliases.yaml`; deterministic mode needs no model; LLM steps use a scripted backend in unit tests and the real model only in evals.

## 1. What runs, and when

| Check | Command | Runs |
|---|---|---|
| Fixture integrity (6) | `python tests/run_tests.py -k tailor_golden` | now |
| Golden oracles (15) | `-k tailor_golden` | when `tailor/{terms,mapping,rewrite,validate}.py` exist (`@needs`) |
| NF-01 (`data/master_resume.json`, `data/tailored/`) | `-k nf01` | now |
| **Smoke / replay (lane T Verify)** | `PYTHONPATH=src python -m jobscraper tailor <job_id> --report` then `tailor <job_id>` on a copied DB → coverage before → after printed, DOCX (+ PDF with Word) under `data/tailored/<job_id>/`, round trip passes, ≤ 10 s | once per lane T handoff |

## 2. Golden cases → oracle tests (`tests/test_tailor_golden.py`)

Expected values live in `case_*/expected.json` (copied from design §15).

| Case | Tests | Expected (key values) |
|---|---|---|
| A backend (variant mirroring) | `test_case_a_terms_and_status`, `test_case_a_coverage_29_to_64`, `test_case_a_variant_swaps_and_article_fix`, `test_case_a_validator_rejections` | exact {Python, REST APIs}; variant {PostgreSQL←Postgres, Kubernetes←k8s, machine learning←ML}; missing {CI/CD, Go, Kafka}; 4/14 → 9/14; "a machine learning model"; order [1,2,3]; skills [Python, PostgreSQL, Kubernetes, machine learning, GitHub Actions, Git]; no Go/Kafka/CI/CD |
| B analyst (no tool swap) | `test_case_b_terms_and_status`, `test_case_b_coverage_50_unchanged`, `test_case_b_no_tool_swapping_and_reorder`, `test_case_b_validator_rejections` | exact {SQL, Excel, Python}; missing {Power BI, stakeholder management, A/B testing}; 5/10 → 5/10; bullets unchanged, order [1,3,2]; skills [SQL, Excel, Python, pandas, Tableau] |
| C fintech (no claim upgrade) | `test_case_c_terms_status_and_knockouts`, `test_case_c_coverage_38_to_54`, `test_case_c_no_claim_upgrade`, `test_case_c_validator_rejections` | variant {REST APIs←REST endpoints}; missing Spring Boot (related "Spring"), Kafka, AML, Docker; knockouts ["- Must be a Singapore Citizen/PR"]; 5/13 → 7/13; order [1,3,2]; "Spring" never becomes "Spring Boot" |
| All | `test_invariants_reject_a_changed_employer_or_date`; inside each rewrite test: protected fields, headings, contact byte-equal; swaps carry no issues |
| Design-fixed APIs | `test_find_matches_tokens_and_ambiguous_terms_only_when_capitalised` (go-live ≠ Go, Node.js one token, APIs = API, Git ∉ GitHub); `test_coverage_counts_only_the_jd_spelling` (variant = 0, 2/3, empty = 0) |
| Fixture integrity (now) | `test_golden_masters_load_into_the_contracts_with_ids_in_reading_order`, `test_golden_leaves_occur_in_the_resume_text`, `test_golden_terms_occur_in_the_jd_with_their_spelling`, `test_golden_coverage_follows_the_f21_weights`, `test_golden_rewrites_keep_every_number_and_every_protected_field`, `test_golden_number_rejections_really_change_the_numbers` |

## 3. Refusals and fail-closed paths

| Path | Oracle |
|---|---|
| Grounding: invented number | 12 validator rows: `NUMBER_ADDED` "12"/"10"/"5", `NUMBER_DROPPED` "82%"/"1.2M"/"2M" |
| Grounding: invented tool/employer | `FACT_ADDED` jenkins/git/power bi/sql/kafka/spring boot with the matching `FACT_DROPPED`; a failing bullet keeps its post-swap text (`source=fallback`) |
| Protected fields | `test_invariants_reject_…` → tailoring fails (`error = "invariant: …"`), never a silent fix |
| Missing terms reported, never added | `absent` lists per case, checked on the tailored text |
| Round trip (§10.4) | lane T test: delete the dates from a rendered DOCX → `ROUNDTRIP`, files deleted, row `failed`; DOCX has no `w:tbl`, `w:txbxContent`, header text |
| Master parse leaf check (§3.3) | lane T test: scripted backend returns a leaf not in the text → one retry → `MasterParseError`, nothing cached |
| Logs (F-24) | lane T test: capture stdout of `tailor`; no bullet text, no contact value appears |
| Retention (D-59) | `storage.purge`: draft > 7 days deleted, sent + rejected > 30 days deleted, row kept |

## 4. Fixtures

`tests/fixtures/tailor/aliases_golden.yaml` (§15 verbatim) and `case_{a,b,c}/`: `master.json` (the §3.1 `master` shape; loads into the contracts), `resume.txt` (text every leaf occurs in), `jd.txt`, `expected.json` (terms with status/variant/via/related, coverage fractions, bullets after, scores, order, skills, absent words, knockouts, numbers per bullet, 4 validator rows).

## 5. Evals for the M21 LLM layer (not in the unit suite)

`python tests/evals/tailor_llm.py` (to write in M21, after spike S-2), real model, cases A–C + 3 recorded real JDs (public postings, no resume of the owner's), 3 runs each at temperature 0.25, seed 7. **Thresholds:** 0 invented facts or numbers in the final output (hard: §8 validator re-run on the output and §8.3 invariants); ≤ 25 % of rewritten bullets fall back; coverage after ≥ the deterministic after on every case; LLM term extraction keeps no term absent from the JD (oracle: model adds "Terraform" → dropped); summary passes §8.2 on ≥ 2 of 3 runs; ≤ 90 s per job (NF-07).

## 6. Open points (raised to the architect, `comms/outbox/tester.md`)

- Stage call shapes for extraction, classify, swap, reorder, invariants, the validator context and `resume_text` are **assumed** in one `_api` block; the design fixes only `find`, `coverage`, `validate.bullet`.
- §8.1 number rule (no left boundary) reads `k8s` as the number 8: case A's swap would be flagged `NUMBER_DROPPED "8"`. The fixture check excludes digits inside dictionary terms, matching the design's expected output.
- §8.1 fact rule: a single capital letter (`S` in `S$1.2M`) may count as a fact, so case B row 2 could raise an extra `FACT_DROPPED "s"`. The oracle expects only `NUMBER_DROPPED`.
