# Resume tailor build plan (M20 lane T, M21 lane TL, M22 LLM rewrite group)

**Stage D** for queue Q-09. Author: planner, 2026-11-02. Status: DRAFT for stage E cross-review (Q-10).
**Inputs:** `docs/prd.md` r2 §5.3, §8; `docs/architecture/tailor_design.md` (cited as **TD §n**); `src/jobscraper/tailor/contracts.py` (CONTRACT_VERSION 1); `docs/architecture/apply_design.md` (**AD**) §2.3, §7.6, §19.1; spike S-2 report (`docs/architecture/spikes/S-2_tailor_llm.md`, branch `spike/Q-06-tailor-llm`); decisions D-58, D-59, D-60, D-65, D-67.
**Companion:** `apply_build_plan.md` (**AB**). Conventions (WP format, STATUS values, Verify rules, branches, NF-08 dev rule) are AB §0. The shared-file blocks for lane T are in AB §2.1; M20 merge order and gate are AB WP-I1.

Truthfulness rule for every WP here: code decides facts, the model only rewords (TD intro). No WP relaxes TD §8.

## 1. Prerequisites

#### WP-T00 · Seed `config/aliases.yaml`
- **STATUS:** TODO
- **Inputs:** TD §6.1 (format; loader rules: a string in at most one entry, canonicals unique by token key, `kind` from the list), TD §15 `aliases_golden.yaml` (the golden terms are the minimum), resume tailor brief §5 (true synonyms only; instances only as deliberate claims).
- **Files:** `config/aliases.yaml`.
- **Depends on:** nothing.
- **Lane:** researcher (`research/Q-09-aliases`).
- **Do:** `version: 1`, `ambiguous: [go, c, r]`, and `terms:` covering at least every canonical in TD §15's golden list plus common new-grad software, data and finance terms; variants are **true synonyms only** (swapping never changes the claim); `instances: []` unless a deliberate truth claim; `kind` on every entry.
- **Verify:** `python -c "import yaml,re; d=yaml.safe_load(open('config/aliases.yaml',encoding='utf-8')); t=d['terms']; seen={}; [seen.setdefault(s.lower(),[]).append(e['canonical']) for e in t for s in [e['canonical']]+e.get('variants',[])+e.get('instances',[])]; dup={k:v for k,v in seen.items() if len(v)>1}; assert not dup, dup; ks={'tool','language','framework','platform','practice','domain','soft'}; assert all(e.get('kind') in ks for e in t); c={e['canonical'] for e in t}; need={'PostgreSQL','Kubernetes','machine learning','REST APIs','CI/CD','Go','Kafka','Python','Git','GitHub Actions','SQL','Power BI','Excel','Tableau','pandas','A/B testing','stakeholder management','Java','Spring','Spring Boot','microservices','RabbitMQ','AML','KYC','Docker'}; assert need<=c, need-c; print(len(t),'terms ok')"`
- **Done when:** the command prints `N terms ok`.
- **Requirements:** F-22 (alias list), F-21 (dictionary).

#### WP-T01 · Golden fixtures and tailor tests (tester)
- **STATUS:** TODO
- **Inputs:** TD §15 (all of it: `aliases_golden.yaml`, masters A–C, JDs A–C, expected outputs, the 12-row rejection table, the LLM-filter oracle, the DOCX structure check); `tests/plans/tailor_test_plan.md` (Q-08).
- **Files:** `tests/fixtures/tailor/aliases_golden.yaml`, `master_a.json`, `master_b.json`, `master_c.json`, `jd_a.txt`, `jd_b.txt`, `jd_c.txt`, `applicant_golden.yaml` (`skills: []`, `attested_skills: []`, synthetic names), plus the test files in §5.
- **Depends on:** Q-08.
- **Lane:** tester (`test/Q-08-tailor-golden`), in parallel with lane T.
- **Do:** fixtures exactly as TD §15; each test file imports only the module its WP builds (so `-k` selects cleanly before later WPs land); golden tests use the fixture aliases, never `config/aliases.yaml`, and a mocked backend.
- **Verify:** `python -c "import json,yaml; m=json.load(open('tests/fixtures/tailor/master_a.json',encoding='utf-8')); y=yaml.safe_load(open('tests/fixtures/tailor/aliases_golden.yaml',encoding='utf-8')); assert len(y['terms'])==25; print('ok', m['contact']['name'])"`
- **Done when:** the fixtures and §5 test files are committed; each test fails only because its module is not built yet.
- **Requirements:** G3, F-21, F-22 (golden oracles).

## 2. M20 lane T (deterministic tailor)

Branch `eng/M20-T-tailor`, based on `personal`. **Own files:** `src/jobscraper/tailor/{__init__,master,terms,mapping,rewrite,validate,render,storage}.py`, `src/jobscraper/tailor_flow.py`. **Shared-file blocks** (exact positions in AB §2.1): `store.py` T-block, `cli.py` T-block + one line in `cmd_purge`, `config.py` T-block, `config/config.yaml` T-block, `requirements.txt` T-block, `web/jobs.py` T-block, and one line in `pipeline.py` (WP-T8). Lane T reads `applicant.py` (lane P, WP-P2) and the backend options (lane P, WP-P1); both land on `personal` first (AB WP-I1 step 3), so T rebases once before WP-T5.

Per-job tailoring in M20 makes **no** model call (`tailor.llm: false`, the default by D-67); only the master parse (WP-T5) calls the model, once per resume hash.

#### WP-T1 · Matcher, alias loader, dictionary, deterministic JD terms
- **STATUS:** TODO (build against TD §4.3 as patched for A-6; until the patch lands the rule above is the S-2 finding the golden oracles need)
- **Inputs:** TD §4.1 (tokens, token keys, ambiguous tokens, `find` spans and surfaces), §4.2, §4.3 (HTML detection, truncation, overlap rule, grouping, required vs preferred headings, knockouts) **including the architect's §4.3 step 4 patch (A-6): a line starting with a bullet marker (`-`, `*`, `•`) is never a heading** (S-2 found that `- Kafka` otherwise resets the "Nice to have" section), §6.1 loader rules + `aliases_hash`.
- **Files:** `src/jobscraper/tailor/__init__.py` (exact content TD §2), `src/jobscraper/tailor/terms.py`.
- **Depends on:** WP-A00 (layering), WP-T01.
- **Lane:** T.
- **Do:** `Aliases.load(path)` (raises `AliasError` naming both entries on a duplicate), `aliases_hash`, `tokens`, `token_key`, `find(text, term)`, `Dictionary(aliases, skills, attested, master_items)` with `canonical_of`, `extract_terms(jd_text, dictionary) -> (list[JdTerm], knockouts)`. HTML→text is injected (`html_to_text` parameter), never imported from `scrape/`.
- **Verify:** `python tests/run_tests.py -k tailor_terms`
- **Done when:** cases A–C yield exactly TD §15's term lists, required/preferred split and spellings; case C's knockout line is returned; "go-live" never yields Go; a duplicate alias string raises `AliasError`.
- **Requirements:** F-21 (deterministic dictionary extraction, required/preferred).

#### WP-T2 · Mapping and coverage
- **STATUS:** TODO
- **Inputs:** TD §5.1 (resume text for mapping, the four classification steps, `related`, `attested`), §5.2 (weights 2/1, JD spelling only, `title_match`, the name "JD keyword coverage").
- **Files:** `src/jobscraper/tailor/mapping.py`.
- **Depends on:** WP-T1.
- **Lane:** T.
- **Do:** `resume_text(master)`, `classify(terms, master, dictionary, attested) -> list[JdTerm]`, `coverage(terms, text) -> float` exactly as TD §5. The model never decides presence.
- **Verify:** `python tests/run_tests.py -k tailor_mapping`
- **Done when:** A–C statuses, `variant`/`via`, `related` ("Spring" for "Spring Boot") and before-coverage (0.2857, 0.50, 0.3846) match TD §15.
- **Requirements:** F-21 (classification, coverage).

#### WP-T3 · Deterministic swaps, skills order, bullet order, headline
- **STATUS:** TODO
- **Inputs:** TD §6.2 (where swaps apply and never apply; acronym direction; article fix; skills item rule; `via = "instance"`), §6.3 (skills order, bullet order by score, headline D-60).
- **Files:** `src/jobscraper/tailor/rewrite.py`.
- **Depends on:** WP-T2.
- **Lane:** T.
- **Do:** `swap(master, terms) -> (document_model, list[BulletChange])`, `order_skills(...)`, `order_bullets(...)` (stable sort by descending score), `headline(job_title, enabled)`. The document model is a deep copy of the master; protected fields are never touched. No LLM code (the LLM rewrite is M22, D-67).
- **Verify:** `python tests/run_tests.py -k tailor_rewrite`
- **Done when:** A–C post-swap bullets, article fix ("a machine learning model"), skills lists and bullet orders ([1,3,2] for B and C) match TD §15 exactly.
- **Requirements:** F-22 (swaps via `config/aliases.yaml`, reorder), D-60 (headline).

#### WP-T4 · Validator (bullet check and resume-wide invariants)
- **STATUS:** TODO
- **Inputs:** TD §8.1 (ids, empty, number multiset regex, fact tokens with the dictionary-span rule, alias mapping, keywords, length), §8.3 (invariants; violation → failure, never a silent fix).
- **Files:** `src/jobscraper/tailor/validate.py`.
- **Depends on:** WP-T1.
- **Lane:** T (can run beside WP-T2/T3).
- **Do:** `numbers(text)`, `facts(text, dictionary)`, `bullet(src, out, ctx) -> list[ValidationIssue]`, `entry_ids(input_ids, output_ids)`, `invariants(master, document, attested) -> list[str]`. §8.2 (summary) is M22 with the summary rewrite (D-67, TB §4). The swap output is passed through `bullet()` in the flow (TD §8.1 last line).
- **Verify:** `python tests/run_tests.py -k tailor_validate`
- **Done when:** all 12 rows of TD §15's rejection table yield exactly the listed issues; REST APIs vs REST endpoints raises nothing; each case's invariants hold on its deterministic output and fail on a doctored employer or date.
- **Requirements:** F-22 (numbers/tools guard, protected fields), G3.

#### WP-T5 · Master resume: parse, leaf check, cache
- **STATUS:** TODO
- **Inputs:** TD §3.1 (cache file, `load` rules, `page_count`), §3.2 (system prompt verbatim, schema, ids, summary handling), §3.3 (`norm`, the two text forms, one retry message, `MasterParseError`, count-only logging).
- **Files:** `src/jobscraper/tailor/master.py`.
- **Depends on:** WP-P1 (backend `format`/`temperature` on `personal`), WP-T01.
- **Lane:** T.
- **Do:** `norm`, `leaf_check(master, text) -> list[str]`, `parse(text, backend) -> MasterResume` (temperature 0, `max_tokens=6000`, schema as `format`), `load(path, resume_hash, text)`, `save(path, master)` (atomic), `page_count(path, word_pages)` (word_pages injected from render, WP-T6). `extract_text`, `find_resume`, `file_hash` are injected by the flow.
- **Verify:** `python tests/run_tests.py -k tailor_master`
- **Done when:** with a fake backend returning master A's JSON for its rendered text: ids are assigned in reading order; a leaf not in the text triggers exactly one retry and then `MasterParseError`; a cached file with a matching hash is reused without a model call; a hyphenated PDF line break passes the leaf check.
- **Requirements:** F-20.

#### WP-T6 · Render: DOCX template, Word PDF, page ceiling, round trip
- **STATUS:** TODO
- **Inputs:** TD §10.1 (template rules, fonts, headings, entry header tab stop, bullets, skills, order, core properties, file naming), §10.2 (page ceiling trimming, 10 rounds), §10.3 (Word COM in a worker thread, 90 s timeout, `PDF_UNAVAILABLE`), §10.4 (round-trip order and failure handling).
- **Files:** `src/jobscraper/tailor/render.py`, `src/jobscraper/tailor/storage.py` (file naming and paths only; purge in WP-T7).
- **Depends on:** WP-T3.
- **Lane:** T.
- **Do:** `TEMPLATE_VERSION = 1`; `render_docx(document, applicant, path)`; `word_pdf(docx, pdf) -> pages | None`; `fit_pages(...)` (TD §10.2 trimming with `BulletChange(source="trimmed")` + `PAGE_TRIM`); `roundtrip(path, document, extract_text) -> list[ValidationIssue]`; `storage.file_name(applicant, master)`, `storage.job_dir(tailored_dir, job_id)`.
- **Verify:** `python tests/run_tests.py -k tailor_render`
- **Done when:** case A's DOCX has no `w:tbl`, `w:txbxContent` or header/footer text, passes the round trip, and is named `Jane_Tan_Resume.docx` (from the golden applicant); with Word present the PDF is produced and round-trips; with `win32com` unavailable the result carries `PDF_UNAVAILABLE` and still succeeds.
- **Requirements:** F-23.

#### WP-T7 · `tailored` table, retention purge, tailor config
- **STATUS:** TODO
- **Inputs:** TD §11.1 (DDL, store methods), §11.3 (draft 7 d; sent → closed + 30 d via `app_events`; failed rows' files deleted at write; rows never deleted), §14 (config block, `TailorConfig`, paths), D-59.
- **Files:** `src/jobscraper/store.py` (T-block), `src/jobscraper/tailor/storage.py`, `src/jobscraper/config.py` (T-block), `config/config.yaml` (T-block), `requirements.txt` (T-block).
- **Depends on:** WP-T6.
- **Lane:** T.
- **Do:** the store block (AB §2.1: DDL at the end of `SCHEMA`, methods at the end of `Store`; no `SCHEMA_VERSION` change); `storage.purge(store, tailored_dir, now, draft_days, sent_days, closed_statuses) -> int` (store passed in as an object); `TailorConfig` with TD §14 defaults; the yaml block and path lines; `pywin32` line.
- **Verify:** `python tests/run_tests.py -k tailor_store`
- **Done when:** an 8-day-old draft's files are deleted and the row kept with `files_deleted_at` set and `changes_json` cleared; a `sent` row whose application went `rejected` 31 days ago is purged and one 29 days ago is not; `current_tailored` honours `inputs_hash`, status and on-disk SHA-256; `load_config().tailor.llm` is False.
- **Requirements:** F-24, D-59, NF-01 (paths under gitignored `data/`).

#### WP-T8 · Tailor orchestrator, CLI `tailor`, purge wiring, job kind
- **STATUS:** TODO
- **Inputs:** TD §2 (orchestrator API and steps; any exception → failed result and row), §4.3 step 1 (JD text; HTML → text), §11.2 (`inputs_hash`, current file, `force`), §12 (`tailor_for_apply`), §13.1 (CLI `--report` and default output, exit codes), §13.2 (job kind), §19 (log lines; never resume text), AB §2.1 (`cmd_purge` line, `pipeline.py` line).
- **Files:** `src/jobscraper/tailor_flow.py`, `src/jobscraper/cli.py` (T-block), `src/jobscraper/pipeline.py` (one line), `src/jobscraper/web/jobs.py` (T-block).
- **Depends on:** WP-T4, WP-T5, WP-T7, WP-P2 (`applicant.load` on `personal`).
- **Lane:** T.
- **Do:** `tailor(cfg, store, job_id, *, backend, report_only=False, force=False)`, `tailor_for_apply(cfg, store, job_id, *, backend)`, `purge(cfg, store, now)`. Injects `resume_ingest.extract_text/find_resume/file_hash` and `scrape.adapters.html_to_text` into the stage. JD missing → fetch it with the scrape adapter's `hydrate()` the same way `pipeline._hydrate` does, then `store.set_description`. Every swapped bullet goes through `validate.bullet`; then `invariants`; then render and round trip; coverage after on the DOCX's extracted text. `pipeline.py`: one call to `tailor.storage.purge(...)` beside `store.purge_descriptions` (an orchestrator may not import `tailor_flow`). CLI `tailor <job_id> [--report] [--force]` per TD §13.1; `cmd_purge` line per AB §2.1; job kind `tailor` per TD §13.2.
- **Verify:** `python tests/run_tests.py -k tailor_flow`
- **Done when:** the flow test (golden case A through a temp DB, fake backend, fixture master cache) prints/returns coverage 29% → 64%, writes `data`-style files under a temp `tailored_dir`, a second call returns the same current row, `--report` writes no row and no file, and captured stdout contains no bullet text. Smoke on a copied DB: `python -m jobscraper tailor <real_job_id> --report`, then a full `tailor <real_job_id>` produces DOCX + PDF that pass the round trip in ≤ 10 s (quoted in the handoff).
- **Requirements:** F-20 (cache by hash), F-21, F-22 (swaps), F-23, F-24 (row + files + purge), F-25 bullet 2 (`tailor_for_apply`), NF-04, NF-07, NF-09.

Lane T is integrated before lane B's WP-B9 (AB WP-I1 step 4); the M20 gate covers tailoring through `apply --dry-run` (the uploaded file is the tailored PDF/DOCX).

## 3. M20 tailor checks inside the gate (Coordinator, part of AB WP-I1)

- `python -m jobscraper tailor <job_id> --report` on the 5 gate jobs (coverage and missing terms printed; no files).
- The dry-run attempts record `resume_source = tailored` (or `original` with the tailor error in the job log).
- Golden tests: `python tests/run_tests.py -k tailor` green on `personal`.

## 4. M21 tailor scope after spike S-2 (D-67)

Spike S-2 (Q-06, report `docs/architecture/spikes/S-2_tailor_llm.md` on `spike/Q-06-tailor-llm`) found that the per-entry LLM bullet rewrite added **no** coverage over the deterministic swaps in 54 of 54 runs (about 6 s per resume) and that the §8.1 validator misses verb/seniority upgrades, direction flips, number words, unknown lowercase tools and capitalised words at sentence start. **D-67:** `tailor.llm: false` stays the default. M21's tailor scope is the deterministic tailor built in M20 (swaps, relevance reordering, render, storage and retention) plus the UI (lane W), plus the LLM JD-term extraction of TD §4.4 (WP-TL1, F-21). The per-entry LLM rewrite and the validator fixes move to **M22** (§4.3).

**Summary rewrite (TD §9): moved to M22.** D-67 keeps it in M21 only if the design's validator covers it. It does not: the summary check (TD §8.2) uses the same `facts()` definition and number rule as §8.1, so it has the same gaps the spike measured (sentence-start capitalised words exempt, number words not counted, unknown lowercase tools invisible, no verb-upgrade check). It joins the M22 group.

Lane **TL** (branch `eng/M21-TL-tailor-terms`) runs in lane L's slot after AB WP-L2. Own files: `src/jobscraper/tailor/terms.py`, `src/jobscraper/tailor_flow.py`. The tailor web UI and API are lane W (AB WP-W4, WP-W7).

#### WP-TL1 · LLM JD-term extraction and merge
- **STATUS:** BLOCKED (A-5) for the switch that turns the call on; the functions themselves are TODO.
- **Inputs:** TD §4.4 (system prompt, schema, the occurs-in-JD filter, ≤ 4 tokens, stop list, acronym pairs as run-time aliases, merge rules, `BackendError` → dictionary only); S-2 report (§4.4 was not measured).
- **Files:** `src/jobscraper/tailor/terms.py`, `src/jobscraper/tailor_flow.py`.
- **Depends on:** M20 merged.
- **Lane:** TL.
- **Do:** `llm_terms(jd, title, backend)` and `merge(dictionary_terms, llm_terms)` exactly as TD §4.4, temperature 0; `tailor_flow.tailor` calls them under the switch the architect names in A-5 (TD §14 has only `tailor.llm`, which D-67 keeps false, so as written F-21's LLM call would never run). `mode` and `inputs_hash` per TD §11.2.
- **Verify:** `python tests/run_tests.py -k tailor_llm_terms`
- **Done when:** the mocked model's extra "Terraform" (not in the JD) is dropped; `source = "both"` for terms from both; a `BackendError` falls back to dictionary terms and logs "jd terms: model unavailable, dictionary only"; golden cases A–C still give TD §15's outputs when the mock returns exactly the dictionary terms. Smoke on a copied DB: one real job tailors in ≤ 90 s with the call on (quoted).
- **Requirements:** F-21 (the JSON-schema LLM call whose terms must occur in the JD), NF-03, NF-07.

### 4.1 Tailor UI (lane W, listed in AB)
- AB **WP-W4** (`/api/tailor`, attest → `data/applicant.yaml` `attested_skills`, "Mark applied" → sent) and AB **WP-W7** (the panel: coverage, missing terms with "I have this", related, questions to expect, diff of swapped/trimmed bullets, downloads, status line). With `tailor.llm: false` every change in the diff has `source` `swap` or `trimmed`.

### 4.2 M21 tailor gate items (Coordinator, part of AB WP-I2)
- Golden cases A–C pass (`python tests/run_tests.py -k tailor`).
- On the 10 gate applications, coverage after ≥ before on ≥ 90% of tailored resumes and 0 fabrications (G3); NF-01 test passes.

### 4.3 M22 group: LLM rewrite (deferred by D-67; listed so nothing is lost)

Starts only after the architect revises TD §7–§9 with the S-2 "Recommendations" (§3 validator, §4 prompt and retry) and the Coordinator re-opens it. These WPs are **not READY** until that design revision lands; their content below is the S-2 list, not a design.

#### WP-TL2 · Validator hardening (S-2 recommendations §3)
- **STATUS:** BLOCKED (design revision of TD §8, M22)
- **Inputs:** S-2 report "Validator gaps" and "Recommendations" §3: `keywords_used` checked only against ALLOWED TERMS (or dropped); verb-class check with an upgrade block-list; `WORD_ADDED` word-level check with a function-word list; number words count as numbers; no sentence-start exemption except the source's own first word; direction-word polarity table; strict digit rule kept.
- **Files:** `src/jobscraper/tailor/validate.py`.
- **Depends on:** the TD §8 revision.
- **Lane:** TL (M22).
- **Do:** implement the revised §8.1/§8.2 exactly.
- **Verify:** `python tests/run_tests.py -k tailor_validate`
- **Done when:** every S-2 probe marked "Missed" is rejected, the 12 golden rows still yield their issues, and accepted S-2 examples still pass.
- **Requirements:** F-22, G3.

#### WP-TL3 · Per-entry LLM rewrite and summary rewrite
- **STATUS:** BLOCKED (design revision of TD §7, §9, M22)
- **Inputs:** TD §7 and §9 as revised (S-2 Recommendations §4: no retry, a "keep the first word's meaning" rule).
- **Files:** `src/jobscraper/tailor/rewrite.py`, `src/jobscraper/tailor_flow.py`.
- **Depends on:** WP-TL2.
- **Lane:** TL (M22).
- **Do:** `rewrite_entry` and `rewrite_summary` per the revised design behind `tailor.llm` (default false, D-67).
- **Verify:** `python tests/run_tests.py -k tailor_llm_rewrite`
- **Done when:** with a scripted fake model returning each bad rewrite, the bullet keeps its post-swap text with the listed issues; protected fields never appear in a captured prompt.
- **Requirements:** F-22 (LLM rewrite: M22, off by default).


## 5. Tests this plan relies on (tester; coordinated in `comms/outbox/planner.md`)

| WP | Test file (needle) | Fixtures |
|---|---|---|
| T1 | `tests/test_tailor_terms.py` (`tailor_terms`) | `tests/fixtures/tailor/aliases_golden.yaml`, `jd_*.txt`, `master_*.json` |
| T2 | `tests/test_tailor_mapping.py` (`tailor_mapping`) | same |
| T3 | `tests/test_tailor_rewrite.py` (`tailor_rewrite`) | same |
| T4 | `tests/test_tailor_validate.py` (`tailor_validate`) — golden rejection table, always kept | same |
| T5 | `tests/test_tailor_master.py` (`tailor_master`) | fake backend; master A rendered to text |
| T6 | `tests/test_tailor_render.py` (`tailor_render`) | `applicant_golden.yaml` |
| T7 | `tests/test_tailor_store.py` (`tailor_store`) | temp DB |
| T8 | `tests/test_tailor_flow.py` (`tailor_flow`) | temp DB, temp dirs, fixture master cache |
| TL1 | `tests/test_tailor_llm_terms.py` (`tailor_llm_terms`) | mocked model |
| TL2 (M22) | `tests/test_tailor_validate.py` (`tailor_validate`, extended with the S-2 probes) | S-2 probe pairs |
| TL3 (M22) | `tests/test_tailor_llm_rewrite.py` (`tailor_llm_rewrite`) | scripted fake model |

## 6. Requirement coverage

| Req | WPs |
|---|---|
| F-20 | T5, T8 |
| F-21 | T00, T1, T2, T8, TL1 (LLM call), W7 |
| F-22 | M20/M21: T00, T3, T4, T8, W4 ("I have this" → `attested_skills`), W7. LLM rewrite: M22 (TL2, TL3; off by default, D-67) |
| F-23 | T6, T8 |
| F-24 | T7, T8, W4 (sent on "Mark applied"), AB B7/B9 (sent on `submitted`) |
| F-25 | T8 (`tailor_for_apply`), AB B9, W4, W7 |
| NF-01 | T7 (paths), AB A00 (check-ignore test) |
| NF-03 | T5, TL1 (Ollama only) |
| NF-04 | T1 (no `scrape/` import; injected), T8 (pipeline calls the stage, not `tailor_flow`) |
| NF-07 | T8 (≤ 10 s deterministic), TL1 (≤ 90 s with the LLM term call) |
| NF-09 | T8 (count-only log lines, TD §19) |

## 7. Open questions

- **A-5 (architect):** TD §4.4's LLM JD-term extraction is an M21 F-21 requirement, but TD §14 has only `tailor.llm`, which D-67 keeps false. Which switch turns the §4.4 call on (e.g. a separate `tailor.llm_terms: true`, or §4.4 always on with dictionary fallback)? Blocks WP-TL1's switch only.
- **A-6 (architect, already announced by the Coordinator):** TD §4.3 step 4 patch: a line starting with a bullet marker (`-`, `*`, `•`) is never a heading (S-2 found `- Kafka` read as a heading, breaking golden A–C). WP-T1 builds against the patched rule.

Planner allocation (not a design change): TD §2 says `tailor_flow.purge` is called by "the end-of-run purge", and TD §18 says `pipeline.py` calls `tailor.storage.purge`; since `pipeline` may not import `tailor_flow` (orchestrator → orchestrator), WP-T8 follows TD §18 (`pipeline` → `tailor.storage.purge`, store passed in) and `cmd_purge` calls `tailor_flow.purge`. Noted to the architect in the planner outbox for confirmation.
