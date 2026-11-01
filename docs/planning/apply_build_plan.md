# Auto-apply build plan (M20 walking skeleton, M21 MVP)

**Stage D** for queue Q-09. Author: planner, 2026-11-02. Status: DRAFT for stage E cross-review (Q-10).
**Revised for D-70 (Q-22, architect acting as planner, 2026-11-02):** Workday is first-class in M20. Lane V (V1–V7) moves into M20 after WP-B4 and spike S-5; new WPs A03, S5, S6, P7, P8, B10, B11, B12; WP-F1/F4 move into M20; the M20 gate now ends with real Workday submissions at the 2 owner-approved employers. Design references are to `apply_design.md` with the D-70 delta (contracts v3).
**Inputs:** `docs/prd.md` r2 §4, §5.2, §5.4, §5.5, §8; `docs/architecture/apply_design.md` (cited as **AD §n**); `src/jobscraper/apply/contracts.py` (CONTRACT_VERSION 1); spike report `docs/architecture/spikes/S-1_S-3_browser.md`; decisions D-50…D-65. The tailor half is in `tailor_build_plan.md` (**TB**); its lane T runs beside lanes P and B in M20.

## 0. How to read this plan

- **Work package (WP)** = ≤ ~1 day, ≤ ~8 files, one lane, one `Verify:` command. Every rule an engineer needs is in the cited design section; a WP never asks the engineer to choose. Anything still open is marked **BLOCKED (A-n)** with the question raised to the architect in `comms/outbox/planner.md`.
- **STATUS** values: `TODO` (buildable once Q-10 marks the plan READY TO BUILD), `BLOCKED (A-n)`, later `DONE`.
- **Verify commands** run on Windows from the repo root, in PowerShell or Git Bash, as one command. `python -c` snippets put `src` on `sys.path` themselves and use only single quotes inside. `python tests/run_tests.py -k <needle>` runs test files the **tester** writes (engineers may not write `tests/**`); §6 lists every test file and fixture this plan relies on, coordinated with the tester through the planner outbox. A WP is not done until its Verify test exists and passes.
- **Branches:** each lane has one branch based on `personal` (`<role>/<queue-id>-<slug>` convention: `eng/M20-P-resolver`, `eng/M20-B-greenhouse`, `eng/M20-T-tailor`; M21 lanes in §4). Commit after each WP. Only the Coordinator merges.
- **Dev rule (NF-08):** a copied DB (`JOBSCRAPER_DB=<copy>`), web on port 8768; real employer pages only in `--dry-run`; never the live DB or port 8765.

## 1. Prerequisites (before any M20 lane starts)

#### WP-A00 · Layering classification and NF-01 test
- **STATUS:** TODO
- **Inputs:** AD §2.3, §18 NF-01 row; TD (tailor design) §2; architect outbox 2026-11-02 request to tester.
- **Files:** `tests/test_layering.py`, `tests/test_privacy.py` (new).
- **Depends on:** nothing.
- **Lane:** tester (`test/Q-08-layering`).
- **Do:** apply AD §2.3 items 1–5 exactly (STAGES += apply, tailor; ORCHESTRATOR += apply_flow, tailor_flow; FOUNDATION += applicant, vault; the one apply_flow → tailor_flow edge; web may import only `apply.contracts` and `tailor.contracts`, reported as dotted names; apply ↛ tailor and tailor ↛ apply). `test_privacy.py`: `git check-ignore -q` succeeds for `data/applicant.yaml`, `data/master_resume.json`, `data/tailored/x`, `data/apply/x`, `data/edge_passwords_x.csv`, and fails for `config/applicant.example.yaml`.
- **Verify:** `python tests/run_tests.py -k layering`
- **Done when:** the command passes on a branch containing `arch/Q-04-designs` (today it fails with "modules ['apply'] belong to no layer"); `python tests/run_tests.py -k privacy` also passes.
- **Requirements:** NF-01, NF-04.

#### WP-A01 · Seed `config/questions.yaml`
- **STATUS:** TODO
- **Inputs:** AD §7.3.1 (format and the **minimum content** list), §7.3.2 (how values map onto options), §7.1 (phrase match: one-token phrases match only labels of ≤ 4 tokens).
- **Files:** `config/questions.yaml`.
- **Depends on:** nothing.
- **Lane:** researcher (`research/Q-09-questions`).
- **Do:** write `version: 1` and one `questions:` entry per key in AD §7.3.1's minimum list, with `kind` and `sensitive` exactly as listed (S paths from AD §5.3 get `sensitive: true`), synonyms in plain lowercase phrases taken from real Singapore and global application forms (auto-apply brief §6), `exclude` where a label about another country would otherwise match (e.g. sponsorship for the US), and `value_map` for every enum key (`residency_status` must cover "Singapore Citizen or PR"-style combined options). No personal values. Generic, public data only.
- **Verify:** `python -c "import yaml; d=yaml.safe_load(open('config/questions.yaml',encoding='utf-8')); q={e['key']:e for e in d['questions']}; need=['singapore_status.authorised_to_work.SG','singapore_status.requires_sponsorship.SG','singapore_status.residency_status','singapore_status.nationality','singapore_status.work_pass','singapore_status.ns_status','singapore_status.race','identity.gender','identity.date_of_birth','availability.notice_period_days','availability.earliest_start_date','availability.willing_to_relocate','availability.willing_to_travel_pct','pay.expected_salary','pay.current_salary','education[0].institution','education[0].degree','education[0].major','education[0].end','education[0].grade','computed.experience_years','computed.graduation_year','links.linkedin','links.github','links.portfolio','sourcing.how_heard_default','consents.certify_true','consents.privacy_consent','languages','identity.preferred_name']; miss=[k for k in need if k not in q]; assert not miss, miss; assert all(q[k]['synonyms'] for k in need); assert all(q[k].get('sensitive') for k in ['singapore_status.residency_status','singapore_status.ns_status','singapore_status.race','identity.gender','identity.date_of_birth']); assert all(q[k].get('value_map') for k in q if q[k]['kind']=='enum'); print(len(q),'keys ok')"`
- **Done when:** the command prints `N keys ok`; the file contains no name, email, number or address of a real person.
- **Requirements:** F-32 (tier 2), F-33 (status questions).

#### WP-A02 · M20 apply fixtures and tests (tester)
- **STATUS:** TODO
- **Inputs:** AD §9.1, §8.4, §15 step 6; the spike's recorded schemas `gh_vercel.json`, `gh_dataiku.json` (session scratchpad `spike-browser/`, public data); `tests/plans/apply_test_plan.md` (Q-08).
- **Files:** `tests/fixtures/greenhouse/gh_vercel.json`, `tests/fixtures/greenhouse/gh_dataiku.json`, `tests/fixtures/greenhouse/form.html` (a local static page with the Greenhouse ids from AD §9.1 "Locators", a minimal script that opens a `.select__menu` with `[role="option"]` items on typing, hidden `#resume` file input, a submit button, and a `?confirm=1` variant showing "Thank you for applying"), `tests/fixtures/apply/applicant_synthetic.yaml` (the AD §5.4 template with synthetic values, every REQUIRED_PATH filled), `tests/fixtures/apply/pages/` (`captcha_v2.html`, `recaptcha_invisible.html`, `cloudflare.html`, `two_factor.html`, `verify_email.html`, `closed.html`, `ok_form.html`), `tests/fixtures/apply/resume.pdf` (one-page synthetic).
- **Depends on:** Q-08 test plan.
- **Lane:** tester (`test/Q-08-apply-fixtures`), in parallel with lanes P and B.
- **Do:** create the fixtures above and the test files listed in §6 for the M20 WPs, each importing only the module its WP builds (so `-k` selects cleanly before other WPs land).
- **Verify:** `python -c "import json; d=json.load(open('tests/fixtures/greenhouse/gh_vercel.json',encoding='utf-8')); print(len(d['questions']),'questions'); assert d['questions']"`
- **Done when:** fixtures and the §6 M20 test files are committed; each test file fails only because its module is not built yet.
- **Requirements:** NF-01 (no personal data in fixtures), F-31, F-34, F-38 (test basis).

#### WP-A03 · `yes_if` rules in `config/questions.yaml` (D-70)
- **STATUS:** TODO
- **Inputs:** AD §7.3.3 (format, loader rules, bool-shaped fields, worked examples); the file's own header note on the enum yes/no gap.
- **Files:** `config/questions.yaml`.
- **Depends on:** WP-A01.
- **Lane:** researcher (`research/Q-22-yes-if`).
- **Do:** add `yes_if` to `singapore_status.residency_status` (at least `sg_citizen` [citizen], `sg_citizen_or_pr` [citizen, pr], `sg_pr` [pr], with the `exclude` phrases that keep "citizen" and "citizen or PR" labels apart), and where real forms ask Yes/No about them, to `singapore_status.ns_status` (e.g. `ns_completed` [completed]) and `singapore_status.work_pass` (e.g. `holds_ep` [ep]). Replace the header's "known design limits" line with a pointer to AD §7.3.3.
- **Verify:** `python -c "import yaml; d=yaml.safe_load(open('config/questions.yaml',encoding='utf-8')); q={e['key']:e for e in d['questions']}; r=q['singapore_status.residency_status']; ids={y['id']:y for y in r['yes_if']}; assert set(ids)>={'sg_citizen','sg_citizen_or_pr','sg_pr'}; assert all(set(y['values'])<=set(r['value_map']) and y['synonyms'] for y in r['yes_if']); assert all(e['kind']=='enum' for e in d['questions'] if 'yes_if' in e); print('yes_if ok')"`
- **Done when:** the command prints `yes_if ok`.
- **Requirements:** F-32 (tier 2), F-33 (status questions).

#### WP-S5 · Spike S-5: real Workday flow at 2 employers (Q-23, D-70)
- **STATUS:** BLOCKED (owner: email + Gmail app password, Q-14) — then TODO.
- **Inputs:** AD §9.4 (the 13-item S-5 checklist and the output table), §11.4 (Gmail app password), D-70 (owner allowed real accounts and automatic submission at these 2 employers).
- **Files:** scratch scripts in the session scratchpad only; outputs in `tests/fixtures/apply/workday/<tenant>/` are handed to the tester (engineers don't write `tests/**`).
- **Depends on:** owner choosing the 2 employers and giving the email + app password; Playwright Edge (S-1).
- **Lane:** software-engineer (spike, `spike/Q-23-workday`).
- **Do:** headed Edge on a throwaway profile copy; at each employer: open a posting, record the Apply choice, create the account with a generated password stored in Credential Manager (`jobscraper:workday:<host>`), verify via IMAP (read-only, `EXAMINE`/`BODY.PEEK`), walk every wizard step with the owner's real data, one deliberate empty Next on one step to record the error markup, **stop at Review** (no Submit). Record per AD §9.4's table; answer the 13 checklist items in `notes.md`.
- **Verify:** `python -c "import json,pathlib; d=[p for p in pathlib.Path('tests/fixtures/apply/workday').iterdir() if p.is_dir()]; assert len(d)>=2, d; [json.load(open(p/'automation_ids.json',encoding='utf-8')) for p in d]; assert all((p/'notes.md').exists() and list(p.glob('*review*.html')) for p in d); print(len(d),'tenants ok')"` (run after the tester commits the scrubbed recordings, WP-F1).
- **Done when:** both tenants recorded up to Review; checklist answered; the accounts exist in `ats_accounts`-compatible form (the spike writes a JSON note; lane V's `accounts add` imports them later).
- **Requirements:** F-31, F-35, F-36 (evidence for the Workday design).

#### WP-F1 · Workday fixtures from the S-5 recordings (moved into M20)
- **STATUS:** TODO after WP-S5.
- **Inputs:** WP-S5 outputs; AD §9.4; NF-01.
- **Files:** `tests/fixtures/apply/workday/<tenant>/**`, `tests/fixtures/apply/workday/README.txt`, the WP-V5…V7 tests.
- **Depends on:** WP-S5.
- **Lane:** tester (`test/Q-23-workday-fixtures`).
- **Do:** replace every personal value with the synthetic profile's (`tests/fixtures/apply/applicant.sample.yaml`); keep every `data-automation-id`, `aria-*` and `role`; strip scripts; add hand-built `confirm.html` (AD §9.4.11 text) and `already_registered.html` (AD §9.4.3 regex copy, or S-5's real copy if met), marked as hand-built in the README; write `tests/test_workday_account.py`, `tests/test_workday_widgets.py`, `tests/test_workday_steps.py`.
- **Verify:** `python -c "import pathlib; f=list(pathlib.Path('tests/fixtures/apply/workday').rglob('*.html')); s=' '.join(p.read_text(encoding='utf-8') for p in f); miss=[i for i in ['signInSubmitButton','createAccountLink','legalNameSection_firstName','bottom-navigation-next-button','reviewJobApplicationPage'] if i not in s]; assert not miss, miss; print(len(f),'pages ok')"`
- **Done when:** the command prints `N pages ok` and `python tests/run_tests.py -k test_nf01` still passes (no personal value committed).
- **Requirements:** F-31, F-35 (test basis), NF-01.

#### WP-F4 · Fake IMAP fixtures (moved into M20)
- **STATUS:** TODO
- **Inputs:** AD §11.1, §11.5 (`to_addr`).
- **Files:** `tests/fixtures/mail/*.eml` (synthetic Workday verification link to the primary address, the same to the backup address, a Greenhouse code, a foreign-domain phishing-style link), the WP-V3 test.
- **Depends on:** nothing.
- **Lane:** tester.
- **Do:** synthetic messages only; a fake `IMAP4_SSL` class in the test that records every command.
- **Verify:** `python -c "from pathlib import Path; f=list(Path('tests/fixtures/mail').glob('*.eml')); assert len(f)>=4; print(len(f),'messages')"`
- **Done when:** the command prints the count.
- **Requirements:** F-36.

#### WP-S6 · Spike S-6: MyGreenhouse in the JobScraper profile (D-70)
- **STATUS:** BLOCKED (owner task Q-24, which needs WP-B10) — then TODO.
- **Inputs:** AD §9.1.1 (defaults to confirm: button regex, not-signed-in signals, settle rule, `.select__single-value` read-back, the resume remove control, any consent dialog).
- **Files:** scratch only; recordings handed to the tester as `tests/fixtures/apply/greenhouse/mygreenhouse/` (`before.html`, `after_autofill.html`, `not_signed_in.html`, `notes.md`), scrubbed to the synthetic profile.
- **Depends on:** WP-B10, Q-24 (the owner signed in once with `apply open-profile`).
- **Lane:** software-engineer (spike).
- **Do:** on 2 open Greenhouse postings whose boards show the autofill button: click it signed in (record which fields filled, how long it took, whether a resume was attached and how to remove it); sign out in a copy of the profile and click it again (record the not-signed-in surface). No Submit.
- **Verify:** `python -c "import pathlib; d=pathlib.Path('tests/fixtures/apply/greenhouse/mygreenhouse'); assert (d/'notes.md').exists() and (d/'after_autofill.html').exists(); print('ok')"`
- **Done when:** `ok`; `notes.md` answers each §9.1.1 default (confirmed / differs).
- **Requirements:** F-34.

The tailor-side prerequisites (WP-T00 aliases seed, WP-T01 golden fixtures) are in TB §1.

## 2. M20 lanes

The architect's split (AD §19.1, TD §18) with one planner change: **`apply/plan.py` moves from lane B to lane P**, because `norm_label` and phrase matching (AD §7.1) are used by `resolve.py` and `declarations.py` (both lane P) and lane B only consumes them. Lane B uses no other plan.py content in M20 (Greenhouse plans come from the adapter's `plan_from_schema`).

| Lane | Branch | Own files (only these) | Shared-file blocks |
|---|---|---|---|
| **P** profile + resolver | `eng/M20-P-resolver` | `src/jobscraper/applicant.py`, `src/jobscraper/apply/__init__.py`, `src/jobscraper/apply/plan.py`, `src/jobscraper/apply/resolve.py`, `src/jobscraper/apply/declarations.py`, `src/jobscraper/backends.py`, `config/applicant.example.yaml` | `cli.py` P-block; `config.py` P-block |
| **B** browser + Greenhouse + flow | `eng/M20-B-greenhouse` | `src/jobscraper/apply/{detect,classify,browser}.py`, `src/jobscraper/apply/ats/{__init__,greenhouse}.py`, `src/jobscraper/apply_flow.py`, `src/jobscraper/models.py`, `src/jobscraper/web/data.py` | `store.py` B-block; `cli.py` B-block; `config.py` B-block; `config/config.yaml` B-block; `requirements.txt` B-block; `web/jobs.py` B-block; `apply/__init__.py` (identical one-line add) |
| **T** deterministic tailor | `eng/M20-T-tailor` | TB §2 | `store.py` T-block; `cli.py` T-block; `config.py` T-block; `config/config.yaml` T-block; `requirements.txt` T-block; `web/jobs.py` T-block; `pipeline.py` T-line |
| **V** vault, accounts, mail, Workday (D-70) | `eng/M20-V-workday` | §2.4 | §2.4 (`cli.py`, `store.py`, `apply_flow.py`, `apply/ats/__init__.py`, `web/jobs.py` V-blocks) |

### 2.1 Shared files: the exact block each lane adds (append-only; the Coordinator resolves the textual merge)

| File | Lane P | Lane B | Lane T |
|---|---|---|---|
| `src/jobscraper/store.py` | — | (1) `SCHEMA_VERSION = 3` (the only lane that changes this line); (2) AD §13 DDL appended at the **end of the `SCHEMA` string** after a comment line `-- M20 apply (apply_design §13)`; (3) in `_migrate`, one block after the existing column checks: add `app_events.by`, then the `meta.schema_version` upsert to 3; (4) a section `# ---------------- apply (M20) ----------------` at the **end of the `Store` class** with the AD §13 methods; (5) `set_application_status(..., by=None)` parameter (the only edit to an existing method) | — | (1) the `tailored` DDL (TD §11.1) appended at the end of the `SCHEMA` string after `-- M20 tailor (tailor_design §11)`; (2) a section `# ---------------- tailored (M20) ----------------` at the end of the `Store` class with TD §11.1 methods. No `SCHEMA_VERSION` or `_migrate` change (`CREATE TABLE IF NOT EXISTS` runs on every open) |
| `src/jobscraper/cli.py` | `cmd_applicant` function placed after `cmd_watchlist`; parser block `# --- applicant (M20 lane P)` placed before `return p` in `build_parser` | `cmd_apply` after `cmd_applicant`'s slot (i.e. after `cmd_watchlist` if P is not merged); parser block `# --- apply (M20 lane B)` before `return p` | `cmd_tailor` after `cmd_watchlist`; parser block `# --- tailor (M20 lane T)` before `return p`; **one line** in `cmd_purge` after the descriptions line: `print(f"tailored files deleted: {tailor_flow.purge(cfg, store, utcnow())}")` |
| `src/jobscraper/config.py` | section `# ---------------- applicant (M20) ----------------` at the end of `Config`: properties `applicant_path` (`paths.applicant`, default `data/applicant.yaml`) and `questions_path` (`paths.questions`, default `config/questions.yaml`) via the existing `_path` | frozen `ApplyConfig` dataclass (AD §16 fields and defaults, nested `mail` as `ApplyMailConfig`) defined above `Config`; property `apply` at the end of `Config` | frozen `TailorConfig` (TD §14) above `Config`; properties `tailor`, `aliases_path`, `master_resume_path`, `tailored_dir` at the end of `Config` |
| `config/config.yaml` | — | the `apply:` block (AD §16) appended at the end of the file; `applicant:` and `questions:` lines appended at the end of the existing `paths:` block | the `tailor:` block (TD §14) appended after lane B's position (end of file); `aliases:`, `master_resume:`, `tailored_dir:` lines appended at the end of `paths:` |
| `requirements.txt` | — | block `# M20 auto-apply (apply_design)`: `playwright>=1.64`, `keyring>=25.7` | block `# M20 tailor (tailor_design): optional, Word -> PDF on Windows`: `pywin32>=306; sys_platform == "win32"` |
| `src/jobscraper/web/jobs.py` | — | `"apply"` appended to `KINDS`; one `elif kind == "apply":` branch before the final `else` (AD §14.2 argv and validation) | `"tailor"` appended to `KINDS`; one `elif kind == "tailor":` branch before the final `else` (TD §13.2) |
| `src/jobscraper/apply/__init__.py` | creates it with exactly `"""Auto-apply stage package (docs/architecture/apply_design.md)."""` | creates it with the identical line | — |
| `src/jobscraper/pipeline.py` | — | — | one call beside `purge_descriptions` (TB WP-T8) |

`apply/ats/__init__.py` (lane B) holds `REGISTRY`; M21 lanes add one line each to it (§4.1).

### 2.2 Lane P: profile + resolver

#### WP-P1 · Backend per-call options
- **STATUS:** TODO
- **Inputs:** AD §7.6 "Backend change".
- **Files:** `src/jobscraper/backends.py`.
- **Depends on:** WP-A00 (merged with the designs).
- **Lane:** P. **First WP of the lane: lane T's master parse (TB WP-T5) needs it.**
- **Do:** `Backend.complete(system, user, max_tokens=4096, *, format=None, temperature=None, seed=None, top_k=None)` on the base class, `OffBackend` (accepts and ignores) and `OllamaBackend`: `format=None` → `"json"`; a dict → sent as the schema; `temperature=None` → 0; `seed`/`top_k` added to `options` only when given. Existing callers unchanged.
- **Verify:** `python tests/run_tests.py -k backend_options`
- **Done when:** the request body carries the schema, temperature, seed and top_k exactly as given (fake `client`), and `python tests/run_tests.py -k ollama` still passes.
- **Requirements:** F-32 (JSON schema), F-22 (temperature, used by the tailor), NF-03.

#### WP-P2 · Applicant profile: load, save, validate, completeness, template
- **STATUS:** TODO
- **Inputs:** AD §5.1 (API), §5.2 (rules, REQUIRED_PATHS, RECOMMENDED_PATHS), §5.4 (template, verbatim), D-55.
- **Files:** `src/jobscraper/applicant.py`, `config/applicant.example.yaml`, `src/jobscraper/config.py` (P-block, §2.1).
- **Depends on:** WP-A00.
- **Lane:** P.
- **Do:** `load`, `save` (validate first, atomic tempfile + `os.replace`, `yaml.safe_dump(sort_keys=False, allow_unicode=True)`), `validate` (every AD §5.2 rule, `FieldError(path, message)` with dotted paths and list indices, the NRIC-shape scan over the whole file), `missing_for_apply` (REQUIRED_PATHS + resume file reported as `documents.resume`; the resume is found as AD §5.2 says), `completeness`, `ApplicantError`. Create `config/applicant.example.yaml` verbatim from AD §5.4.
- **Verify:** `python -c "import sys; sys.path.insert(0,'src'); from jobscraper import applicant as a; p=a.load('config/applicant.example.yaml'); e=a.validate(p); assert not e, e; b=dict(p, contact=dict(p['contact'], postal_code='12', email='x')); got=sorted(x.path for x in a.validate(b)); assert got==['contact.email','contact.postal_code'], got; c=dict(p, singapore_status=dict(p['singapore_status'], nric_last4='S1234567A')); assert a.validate(c); print('ok', a.completeness(p))"`
- **Done when:** the command prints `ok (n, m)`; the template is byte-identical to AD §5.4's block.
- **Requirements:** F-10, F-11 (validation, missing list), NF-01 (template holds placeholders only).

#### WP-P3 · Applicant extracts, grounding text, redaction, computed facts, `applicant check`
- **STATUS:** BLOCKED (A-4) for the `experience_months` arithmetic only; everything else TODO.
- **Inputs:** AD §5.1 (`llm_extract`, `grounding_text`, `redaction_values`, `computed_facts`), §5.3 (S paths, allow-list), §7.7 (corpus sentences), §14.1 `applicant check`.
- **Files:** `src/jobscraper/applicant.py`, `src/jobscraper/cli.py` (P-block).
- **Depends on:** WP-P2.
- **Lane:** P.
- **Do:** the four functions exactly as AD §5.1/§5.3/§7.7 define them (`llm_extract` = the allow-list only; `computed_facts(profile, today)` → `experience_months` summed over `experience[]` (`end: null` = present, i.e. `today`; month arithmetic per A-4), `experience_years` = months // 12, `graduation_year` = year of `education[0].end`). CLI `applicant check`: prints each error `path: message`, the missing list, `completeness filled/needed`, `Resume: <file name> ok`; exit 0 only when no errors and nothing missing. `applicant init` is M21 (WP-W1).
- **Verify:** `python -c "import sys,datetime; sys.path.insert(0,'src'); from jobscraper import applicant as a; p=a.load('config/applicant.example.yaml'); x=a.llm_extract(p); assert 'contact' not in x or set(x['contact'])<={'city','country'}; assert 'declarations' not in x and 'us_self_id' not in x and 'identity' not in x; assert p['contact']['email'] in a.redaction_values(p); f=a.computed_facts(p, datetime.date(2026,11,2)); assert f['experience_years']==0 and f['graduation_year']==2025, f; print('ok')"`
- **Done when:** the command prints `ok`; `applicant check` against the template copy prints the errors/missing lines and exits non-zero only for missing items (smoke, quoted in the handoff).
- **Requirements:** F-10, F-11 (missing list before apply), F-32 (minimal extract), NF-02 (redaction list), NF-09.

#### WP-P4 · Label normalisation and resolver tiers 1–3
- **STATUS:** TODO
- **Inputs:** AD §6 (field keys, hidden, `alt_of`), §7 intro (tier rules, sensitive stop), §7.1, §7.2 (canonical table), §7.3 (questions.yaml loader, selection, ties), §7.3.2 (bool, enum, decline, number ranges, salary, date, country, url/text), §7.4 (memory through the injected `MemoryLookup`).
- **Files:** `src/jobscraper/apply/__init__.py`, `src/jobscraper/apply/plan.py`, `src/jobscraper/apply/resolve.py`.
- **Depends on:** WP-P3, WP-A01 (questions.yaml), WP-A02 (synthetic profile).
- **Lane:** P.
- **Do:** `plan.norm_label`, `plan.phrase_match` (AD §7.1 incl. the ≤ 4-token rule; HTML stripped with stdlib `html.parser`, since stages do not import `scrape/`). `resolve.QuestionRules.load(path)`; `resolve.resolve_all(fields, ctx, *, backend, rules, memory)` with tiers 1–3 and the post-tier `unknown`/`blank_optional` rule; tier 4 and 5 hooks call into WP-P5/P6 (until then they answer nothing). Fixed ISO→country-name table in `resolve.py` (SG → Singapore at minimum, plus every country in the questions.yaml country examples). `PREVIOUS_WORKER` calls `declarations.prior_employment` (WP-P5).
- **Verify:** `python tests/run_tests.py -k apply_resolve_rules`
- **Done when:** the tests for §7.1 normalisation, every §7.2 canonical, §7.3 selection and ties, every §7.3.2 mapping kind, and the sensitive-field stop pass.
- **Requirements:** F-32 (tiers 1–3, option mapping, recording of tier/source/confidence), F-33 (status questions via tier 1/2), F-12 (lookup only).

#### WP-P5 · Declarations (tier 4)
- **STATUS:** TODO
- **Inputs:** AD §7.5 (classifier phrases, attestation markers, rules, `company_match`, single-checkbox semantics), D-55.
- **Files:** `src/jobscraper/apply/declarations.py`, `src/jobscraper/apply/resolve.py` (tier-4 call).
- **Depends on:** WP-P4.
- **Lane:** P.
- **Do:** `classify(label_norm, description_norm) -> DeclarationLabel | AMBIGUOUS | None`, `company_match(a, b)`, `prior_employment(profile, employer, aliases)`, `answer(label, field, ctx)` per the AD §7.5 rules (AMBIGUOUS → `unknown`/`blank_optional`, never tier 5; `health` decline-or-unknown; required checkbox that must stay unticked → `unknown`); `source = "declaration:<label>"`, `sensitive=True`.
- **Verify:** `python tests/run_tests.py -k apply_declarations`
- **Done when:** the golden declaration tests pass (every class, ambiguity, the attestation-marker fallback, company matching examples "DBS Bank Ltd"~"DBS" and "Grab"~"Grab Financial Group", checkbox negation both ways).
- **Requirements:** F-33, F-10 (standing declarations), F-32 (tier 4).

#### WP-P6 · Tier 5 (local LLM) and the grounding check
- **STATUS:** BLOCKED (A-1) for grounding rule 3's dictionary terms only; everything else TODO.
- **Inputs:** AD §7.6 (eligibility, system prompt verbatim, user prompt, the four schemas, two-call agreement, text retry, max_tokens, `BackendError`), §7.7 (corpus, the five text rules, choice/number checks), §7.2 COVER_LETTER.
- **Files:** `src/jobscraper/apply/resolve.py`.
- **Depends on:** WP-P1, WP-P5.
- **Lane:** P.
- **Do:** exactly AD §7.6–§7.7. Record `model`, `prompt_hash = sha256(system + "\n\n" + user)[:16]`, `source="llm"`, `rule_id="llm:v1"`. A failed required field → `unknown` (`ungrounded` when grounding failed) with the violations in `note` (tokens only). Model unavailable on a required field → `unknown` with note `model unavailable`. Grounding rule 3 uses the dictionary terms supplied as the architect answers A-1.
- **Verify:** `python tests/run_tests.py -k apply_resolve_llm`
- **Done when:** with a scripted fake backend: two agreeing choice runs answer; disagreeing runs do not; an evidence quote absent from the corpus fails; a text answer adding a number, year, unknown capitalised word or dictionary term is rejected then retried once; sensitive and attestation fields never reach the backend (the fake asserts it is not called).
- **Requirements:** F-32 (tier 5, grounding, free text, recording), NF-02/NF-03 (no S value in prompts, Ollama only).

#### WP-P7 · `yes_if` in tier 2 (D-70)
- **STATUS:** TODO
- **Inputs:** AD §7.3.3 (loader validation, virtual entries `<key>#<id>`, bool-shaped fields, candidate sets per field type, value rule incl. decline, source/rule_id), §7.3.1 scoring (unchanged), §7.3.2 bool mapping.
- **Files:** `src/jobscraper/apply/resolve.py`.
- **Depends on:** WP-P4, WP-A03.
- **Lane:** P.
- **Do:** extend `load_rules` and tier 2 exactly as AD §7.3.3.
- **Verify:** `python tests/run_tests.py -k apply_resolve_rules`
- **Done when:** the tester's `yes_if` cases pass: "Are you a Singapore Citizen?" Yes/No with residency `citizen` → Yes, `pr` → No; "…Citizen or Permanent Resident?" → Yes for citizen and pr, No for foreigner; a 3-option citizen/PR/foreigner dropdown still uses `value_map`; an invalid `yes_if` (value not in `value_map`) raises `ValueError` naming `<key>#<id>`; an empty residency status → `unknown`, never tier 5.
- **Requirements:** F-32, F-33.

#### WP-P8 · `contact.backup_email` and the account email (D-70)
- **STATUS:** TODO
- **Inputs:** AD §10.5 (profile field, validation, template line), §5.2–§5.4, §7.2 EMAIL row (`ctx.account_email`).
- **Files:** `src/jobscraper/applicant.py`, `config/applicant.example.yaml`, `src/jobscraper/apply/resolve.py`.
- **Depends on:** WP-P2, WP-P4.
- **Lane:** P.
- **Do:** optional `contact.backup_email` (email regex; must differ from `contact.email`; sensitive; in `redaction_values`); template line per AD §10.5; tier-1 EMAIL answers `ctx.account_email or contact.email`.
- **Verify:** `python tests/run_tests.py -k apply_contracts`
- **Done when:** the profile tests and the template-vs-sample oracle pass with the new field; a backup equal to the primary is a validation error; EMAIL resolves to `account_email` when set.
- **Requirements:** F-10, F-11, F-35.

### 2.3 Lane B: browser + Greenhouse + flow

#### WP-B1 · Apply tables, store methods, `posting_key` move
- **STATUS:** TODO
- **Inputs:** AD §13 (DDL, migration, method names), §4.1 (`set_attempt_state` refuses transitions not in `TRANSITIONS`), §4.3 (reaper), §12.1–§12.3 (duplicate, caps, previously applied), D-65 (`app_events.by`).
- **Files:** `src/jobscraper/store.py` (B-block, §2.1), `src/jobscraper/models.py`, `src/jobscraper/web/data.py`.
- **Depends on:** WP-A00.
- **Lane:** B.
- **Do:** the store block in §2.1; every method named in AD §13 (`apply_counts` counts `submit_clicked_at ≥ day_start`, Asia/Singapore day boundary computed by the caller); `reap_attempts(now)` per AD §4.3; `apply_duplicate` per AD §12.1 (2) including twins by `posting_key`; `applied_to_company`. Move `posting_key` from `web/data.py` to `models.py` and import it back in `web/data.py` (behaviour unchanged).
- **Verify:** `python tests/run_tests.py -k apply_store`
- **Done when:** `test_apply_store.py` passes and `python tests/run_tests.py -k test_store` (the existing store tests) still passes: migration from a v2 DB to v3 keeps data; a forbidden transition raises `ValueError`; a second `submitted` row for one job violates the unique index; duplicate rules (applied, twin, earlier submit, same batch) and cap counts are right; the reaper maps clicked → `submitted_unconfirmed`, not clicked → `failed(cancelled)`.
- **Requirements:** F-30 (duplicates, caps), F-37 (applied with `by`), F-39 (answer rows), NF-06.

#### WP-B2 · Apply config, dependencies, package skeleton
- **STATUS:** TODO
- **Inputs:** AD §16, §2.1, §9.0 (registry).
- **Files:** `src/jobscraper/config.py` (B-block), `config/config.yaml` (B-block), `requirements.txt` (B-block), `src/jobscraper/apply/__init__.py`, `src/jobscraper/apply/ats/__init__.py`.
- **Depends on:** WP-A00.
- **Lane:** B.
- **Do:** `ApplyConfig`/`ApplyMailConfig` with AD §16 defaults (used when the yaml block is absent); `Config.apply`; the yaml block; requirements lines; `ats/__init__.py` with `REGISTRY: dict[str, AtsAdapter] = {}` (Greenhouse registered in WP-B5). Install: `pip install playwright keyring` (no `playwright install`: Edge is used through `channel="msedge"`).
- **Verify:** `python -c "import sys; sys.path.insert(0,'src'); from jobscraper.config import load_config; a=load_config().apply; assert (a.mode,a.daily_cap,a.per_employer_daily_cap,a.headed,a.confirm_timeout_s,a.mail.wait_s)==('dry_run',10,2,True,60,300), a; print('ok')"`
- **Done when:** the command prints `ok`; `python -m jobscraper doctor` still runs.
- **Requirements:** F-40 (config defaults), D-61, NF-05.

#### WP-B3 · Page classifier
- **STATUS:** TODO
- **Inputs:** AD §8.4 (order of checks, exact selectors and regexes, visibility rule, the invisible reCAPTCHA exception from S-3).
- **Files:** `src/jobscraper/apply/classify.py`.
- **Depends on:** WP-B2, WP-A02 (page fixtures).
- **Lane:** B.
- **Do:** `classify(page, status=None) -> PageSignal`, `PageSignal` as an `Enum` in classify.py with the seven values; checks in AD §8.4 order; adapters can pass extra markers (`extra_closed`, `extra_errors` keyword tuples).
- **Verify:** `python tests/run_tests.py -k apply_classify`
- **Done when:** each fixture page classifies as named (the invisible-reCAPTCHA page is `ok`); runs headless Edge locally, no network.
- **Requirements:** F-38 (captcha, bot, 2FA, closed), F-36 (verify-email signal).

#### WP-B4 · Browser session, fill primitives, evidence
- **STATUS:** TODO
- **Inputs:** AD §8.1 (launch arguments verbatim), §8.2 (every primitive; "never press Enter"; scope options to `.select__menu`), §8.3 (screenshot names, `failed.html`), NF-05 pace.
- **Files:** `src/jobscraper/apply/browser.py`.
- **Depends on:** WP-B2, WP-A02 (`form.html`).
- **Lane:** B.
- **Do:** `BrowserSession` (context manager; `new_page`, `hold`), the nine primitives returning True/False after read-back, `screenshot(page, attempt_dir, seq, step)` → `NN-<step>.png`, `dump_html(page, attempt_dir)` → `failed.html`. No stealth flags.
- **Verify:** `python tests/run_tests.py -k apply_browser`
- **Done when:** against `form.html` served by a local `http.server`, headless: `fill_text` reads back, `choose_react_select` picks the exact option without Enter, `set_checkbox` and `upload` verify, screenshots are named `NN-<step>.png`.
- **Requirements:** F-34, NF-05.

#### WP-B5 · Detection and the Greenhouse plan
- **STATUS:** TODO
- **Inputs:** AD §9.0, §9.1 rows Tenant, Plan, Mapping; §6 (required, hidden, `alt_of`).
- **Files:** `src/jobscraper/apply/detect.py`, `src/jobscraper/apply/ats/greenhouse.py`, `src/jobscraper/apply/ats/__init__.py`.
- **Depends on:** WP-B2, WP-A02 (`gh_*.json`).
- **Lane:** B.
- **Do:** `detect(job) -> (adapter, Tenant)` or `ApplyFailure(UNSUPPORTED_ATS, detail=provider or host)`; Greenhouse `match_url` (AD regex), `tenant_from_company`, `plan_from_schema` (GET through `ctx.http`; 404 → `ApplyFailure(POSTING_CLOSED)`; every mapping rule in AD §9.1, incl. `candidate-location`, compliance, demographic, data_compliance and the extra `country` field). Register `"greenhouse"` in `REGISTRY`.
- **Verify:** `python tests/run_tests.py -k greenhouse_plan`
- **Done when:** both recorded schemas map to the expected FormPlans (field keys, types, required flags, canonicals, `alt_of`), a 404 raises `posting_closed`, and an unknown provider/URL raises `unsupported_ats`.
- **Requirements:** F-31.

#### WP-B6 · Greenhouse browser steps
- **STATUS:** TODO
- **Inputs:** AD §9.1 rows Open, Locators, Fill, Next, Submit, Confirmation, Code after Submit, Errors, Account; AD contracts `AtsAdapter`.
- **Files:** `src/jobscraper/apply/ats/greenhouse.py`.
- **Depends on:** WP-B3, WP-B4, WP-B5.
- **Lane:** B.
- **Do:** `open` (embed fallback, `#first_name` within `step_timeout_s` else `page_unrecognised`), `account_wall` → None, `read_step` (schema plan already known: returns `("application", plan.fields)`), `fill` (per-type primitive per AD; `country` before `phone`), `next_step` → `is_review=True`, `submit`, `after_submit` (`confirmed:url`/`confirmed:text`/`code_required`), `visible_errors`, `enter_code`, `password_rules`, `mail_domains`, `otp_pattern` as AD §9.1.
- **Verify:** `python tests/run_tests.py -k greenhouse_fill`
- **Done when:** on `form.html` the adapter fills every planned field, reads them back, and `after_submit` on the `?confirm=1` page returns `confirmed:text`; on a page without `#first_name` `open` raises `page_unrecognised`.
- **Requirements:** F-34, F-37 (confirmation signal), F-38 (validation errors).

#### WP-B7 · Apply orchestrator
- **STATUS:** TODO
- **Inputs:** AD §3 (flow), §4.1–§4.4 (transitions, NF-06 rule, Greenhouse code without mail → `submitted_unconfirmed` with detail "security code needed; mailbox not set up", reaper, reason codes), §6 (resolution timing), §7.8 (audit rows), §8.3 (evidence), §8.4 captcha wait, §12.1 (guard order, one in flight), §12.3, §17 (log lines, `redact`), TD §12 (resume choice).
- **Files:** `src/jobscraper/apply_flow.py`.
- **Depends on:** WP-B1, WP-B5, WP-B6 (lane B only; uses a **stub resolver** returning tier-1 answers and a **stub `tailor_for_apply`** returning the original resume until WP-B9).
- **Lane:** B.
- **Do:** `run(cfg, store, job_ids, *, dry_run, backend) -> list[AttemptResult]` as AD §3: reap; per job create `queued`; guards (profile → duplicate → caps (skipped in dry run) → one in flight); tailoring; planning (resolve all; a required `unknown`/`ungrounded` fails before Edge opens); one `BrowserSession` per run; open → classify → fill → read back → screenshot → classify → next; review: dry run → `ready_to_submit`, auto → `mark_submit_clicked` committed **before** the click, then confirmation within `confirm_timeout_s`; every exception after the click → `submitted_unconfirmed`; `submitted` → `set_application_status(job, 'applied', by='jobscraper')` + the stub tailor's `mark_sent` no-op (WP-B9 replaces it with `store.mark_tailored_sent`); `attempt_timeout_s` deadline; `dry_run_hold_s` hold at the end. `redact(line, values)` lives in `apply_flow.py`; every log line passes through it. `apply_answers` rows written per AD §7.8 (file fields: name + SHA-256).
- **Verify:** `python tests/run_tests.py -k apply_flow`
- **Done when:** with a fake adapter and fake browser: the guard order and refusals (`profile_incomplete`, `duplicate`, `cap_reached`) are right; a required unknown fails before the browser; `submit_clicked_at` is written before `submit()`; an exception after the click ends `submitted_unconfirmed`; dry run ends `ready_to_submit` without calling `submit`; audit rows exist for every field; no profile value appears in captured stdout.
- **Requirements:** F-30 (guards), F-34 (resume upload, screenshots), F-37, F-38, F-39 (rows), NF-02, NF-05, NF-06, NF-09.

#### WP-B8 · CLI `apply` and the `apply` job kind
- **STATUS:** TODO
- **Inputs:** AD §14.1 `apply` row (output and exit codes), §14.2 (argv, id regex, ≤ 20 ids), §14.3 last paragraph (settings keys fall back to config).
- **Files:** `src/jobscraper/cli.py` (B-block), `src/jobscraper/web/jobs.py` (B-block).
- **Depends on:** WP-B7.
- **Lane:** B.
- **Do:** `cmd_apply`: builds the **effective** `ApplyConfig` = `dataclasses.replace` of `cfg.apply` with any of the AD §14.3 settings keys present in the `settings` table (`apply.mode`, caps, `headed`, `captcha_wait_s`, mail host/port/username); `--dry-run` forces dry run; prints one line per state change and the final table (job id, state, reason); exit 0/1/2 per AD. Job kind `apply` per AD §14.2 (job ids validated, at most 20; bad ids → `ValueError`).
- **Verify:** `python tests/run_tests.py -k apply_cli`
- **Done when:** with a fake flow, exit codes 0/1/2 are right, the settings table overrides config, `--dry-run` wins; `cli_command()('apply', {'job_ids': [...], 'dry_run': True})` builds the AD argv and rejects a bad id. Smoke: the Developer tab shows the job's log lines when the kind is started from a test client (NF-09).
- **Requirements:** F-30 (CLI start, batch of ids), F-37 (`apply.mode`), F-40 (settings precedence), NF-09.

#### WP-B9 · Swap in the real resolver and tailor
- **STATUS:** BLOCKED (A-2) for `ResolveContext.resume_text`'s source only; otherwise TODO.
- **Inputs:** AD §3, §7 (`resolve_all` signature, `MemoryLookup` = `store.answer_memory_get`), §12.3, TD §12 (`tailor_for_apply` hand-off, `apply.resume_format`), AD §19.1 integration order.
- **Files:** `src/jobscraper/apply_flow.py`.
- **Depends on:** lanes P and T merged into `personal` and lane B rebased on it (WP-I1 steps 3–4).
- **Lane:** B.
- **Do:** replace the stubs: `resolve.resolve_all(..., backend=backend, rules=QuestionRules.load(cfg.questions_path), memory=store.answer_memory_get)`; `ResolveContext` filled from the profile, company name, aliases (watchlist key, board), `store.applied_to_company`, `jobs.jd_text`, resume text (per A-2), the chosen resume path; `tailor_flow.tailor_for_apply` with the resume choice of TD §12 and the attempt's `resume_source`/`tailored_id`/file name/SHA-256; `mark_tailored_sent` on `submitted`.
- **Verify:** `python tests/run_tests.py -k apply_e2e`
- **Done when:** the end-to-end fixture test (synthetic profile, deterministic tailor on a fixture master, `form.html`, fake backend) ends `ready_to_submit` with a tailored resume uploaded and an `apply_answers` row per field with the expected tiers.
- **Requirements:** F-25 bullet 2 (auto-tailor), F-32, F-33, F-34 (tailored or original resume), F-39.

#### WP-B10 · CLI `apply open-profile` (D-70; needed by owner task Q-24)
- **STATUS:** TODO
- **Inputs:** AD §14.1 `apply open-profile [URL]` row (headed forced, default URL, message, hold until closed, locked-profile message, reserved words), §8.1.
- **Files:** `src/jobscraper/cli.py` (B-block), `src/jobscraper/apply/browser.py`.
- **Depends on:** WP-B4.
- **Lane:** B.
- **Do:** the subcommand; `BrowserSession` gains a `headed` override argument if it has none; a launch error that names the user-data directory → the AD message, exit 1.
- **Verify:** `python tests/run_tests.py -k apply_cli`
- **Done when:** with a fake session factory: default URL `https://my.greenhouse.io/`, headed forced even when `apply.headed` is false, a locked profile exits 1 with the message, `apply show` still works. Manual smoke (owner, Q-24): the window opens on the JobScraper profile.
- **Requirements:** F-34 (MyGreenhouse sign-in), F-35 (manual sign-ins).

#### WP-B11 · Prefill policies and the corrective retry in the flow (D-70, both ATSs)
- **STATUS:** TODO
- **Inputs:** AD §3 (prefill step), §9.1.1 (KEEP table, planning change), §9.4.6 (OVERWRITE table), §9.4.9 "Split of work" (flow does the re-resolve/re-fill and the second Next), contracts v3 (`PREFILL_POLICY`, `ALWAYS_OURS`, `EMPLOYER_SPECIFIC_DECLARATIONS`, `AnswerStatus.PREFILLED`, `AnswerSource`, adapter `prefill`/`read_values`).
- **Files:** `src/jobscraper/apply_flow.py`.
- **Depends on:** WP-B7 (and WP-B9 if already merged; this WP rebases on it).
- **Lane:** B.
- **Do:** call `adapter.prefill` once after the account wall; per step `read_values` when a policy applies; implement both tables exactly (audit rows: tier 0, `source` = the prefill source, status `prefilled`, conflict note); the planning deferral for Greenhouse when `apply.mygreenhouse` is on; the generic "errors after Next" retry (re-fill, or re-resolve with `required=True`; second failure → `validation_error`). `ApplyConfig` gains `mygreenhouse`, `mygreenhouse_wait_s`, `workday_entry`, `max_wizard_steps`, `mail_backup` (AD §16; B-block in `config.py`/`config.yaml`).
- **Verify:** `python tests/run_tests.py -k apply_flow`
- **Done when:** with a fake adapter: KEEP keeps a non-empty field as `prefilled` and fills only empty ones, always replaces the resume and overwrites a differing email and an employer-specific declaration; OVERWRITE replaces differing values, keeps an optional unanswerable one as `prefilled`, fails a required unanswerable one; a required `unknown` in planning reaches the browser only with MyGreenhouse on, and fails if still empty after prefill; the retry happens once.
- **Requirements:** F-32, F-34, F-38, F-39.

#### WP-B12 · Greenhouse: MyGreenhouse `prefill` and `read_values`; label canonicals by phrase
- **STATUS:** TODO; selectors BLOCKED (S-6) — build with the AD §9.1.1 defaults, then confirm on the S-6 recordings.
- **Inputs:** AD §9.1.1 (`prefill` steps 1–5, `read_values` per type, the resume remove control), §9.1.2 (link canonicals by phrase match, decided).
- **Files:** `src/jobscraper/apply/ats/greenhouse.py`.
- **Depends on:** WP-B6, WP-B11; WP-S6 for the confirmation step.
- **Lane:** B.
- **Do:** `prefill` and `read_values` as AD; switch the label → LINKEDIN/GITHUB/WEBSITE tagging in `plan_from_schema` to §9.1.2's phrase rule.
- **Verify:** `python tests/run_tests.py -k greenhouse`
- **Done when:** on `form.html` plus the tester's MyGreenhouse fixture variants (signed in: fields appear after a delay; not signed in: a dialog with an email input; no button): `prefill` returns `mygreenhouse` / `""` / `""`, the dialog is closed without typing, values are read back per type; Dataiku's "LinkedIn URL" / "Github URL" get LINKEDIN / GITHUB.
- **Requirements:** F-31, F-34.

### 2.4 Lane V: vault, accounts, mail, Workday (moved into M20 by D-70)

Branch `eng/M20-V-workday`. Starts in the first engineer slot freed by lane P or T (≤ 3 engineer lanes at once). V1 and V3 need no browser or store and can start at once; V2 and V4 need lane B merged (store methods); V5–V7 need WP-B4 (`browser.py`) merged and the S-5 fixtures (WP-F1); V4 needs lane B merged (it adds a V-block to `apply_flow.py`).

| Own files | Shared-file blocks |
|---|---|
| `src/jobscraper/vault.py`, `src/jobscraper/apply/mail.py`, `src/jobscraper/apply/accounts.py`, `src/jobscraper/apply/ats/workday.py`, `src/jobscraper/apply/ats/workday_widgets.py` | `cli.py` V-block (`accounts`, `mail` verbs); `store.py` V-block (section `# ---------------- apply accounts (M20 lane V) ----------------` at the end of `Store`: `accounts_for_tenant`, `applied_on_tenant`, `annotate_answers`; no DDL change); `apply_flow.py` V-block (identity, mail, account rows; after lane B merged); `apply/ats/__init__.py` one `REGISTRY` line; `web/jobs.py` V-block (`mailtest` kind) |

#### WP-V1 · Vault and Edge CSV export
- **STATUS:** TODO
- **Inputs:** AD §10.1 (API, generator), §10.3 CSV (columns, file name, zero-overwrite delete, 1-hour cleanup), §10.4; ADR-0002.
- **Files:** `src/jobscraper/vault.py`.
- **Depends on:** WP-A00.
- **Lane:** V.
- **Do:** `service_for`, `IMAP_SERVICE`, `get`/`put` (read-back compare, else `VaultError`)/`delete`, `generate(rules)` (one of each required class, `SystemRandom` shuffle, length clamped), `export_edge_csv(rows, out_dir)`, `delete_export(path)` (overwrite with zeros, unlink), `purge_stale_exports(data_dir, now)` (> 1 hour). Never log a secret.
- **Verify:** `python tests/run_tests.py -k apply_vault`
- **Done when:** generated passwords meet every rule over 1000 draws; put/get/delete round-trips through a fake keyring backend; the CSV has the header `name,url,username,password,note` and one row per account; stale exports are removed.
- **Requirements:** F-35, NF-02.

#### WP-V2 · CLI `accounts` (list, add, export-edge) and `mail set-password [--backup]`
- **STATUS:** TODO
- **Inputs:** AD §14.1 rows `accounts list`, `accounts add`, `accounts export-edge [--confirm]`, `mail set-password [--backup]`; §10.4; §11.5.
- **Files:** `src/jobscraper/cli.py` (V-block).
- **Depends on:** WP-V1; lane B merged (`upsert_account`/`accounts` from WP-B1 reach `personal` only then). The `mail set-password` half may land first.
- **Lane:** V.
- **Do:** `cmd_accounts` (`list`; `add --url --email` with `getpass`, tenant via the Workday `match_url` — import `apply.ats.workday` lazily; until WP-V5 lands, the AD §9.4.1 regex A is enough; resets `signin_failed`/`exists_no_password` to `created`; `export-edge`, `--confirm`); `cmd_mail set-password [--backup]`.
- **Verify:** `python tests/run_tests.py -k accounts_cli`
- **Done when:** `accounts list` prints no password; `accounts add` writes the vault entry and the row (and resets a failed row); export writes the CSV and `--confirm` deletes it and stamps rows; `--backup` stores under the backup mailbox's username.
- **Requirements:** F-35, F-36, F-40, NF-02.

#### WP-V3 · IMAP mail watcher, two mailboxes, `mail test`, `mailtest` kind
- **STATUS:** TODO (real-mailbox check: owner task Q-14 / S-4, done inside WP-S5)
- **Inputs:** AD §11.1 (EXAMINE only, PEEK, SINCE window, sender/link domain rules, code extraction, polling, logging), §11.3, §11.5 (mailbox per address, `to_addr` filter), §14.1 `mail test [--backup] [--find-from]`, §14.2 `mailtest`.
- **Files:** `src/jobscraper/apply/mail.py`, `src/jobscraper/cli.py` (V-block), `src/jobscraper/web/jobs.py` (V-block).
- **Depends on:** WP-V1, WP-F4.
- **Lane:** V.
- **Do:** `MailWatcher.wait_for(..., to_addr=None)`, `test_connection`, `employer_domain(careers_url)`, `mailbox_for(address, profile, settings) -> (host, port, username) | None` (AD §11.5), `mail test`, kind `mailtest`.
- **Verify:** `python tests/run_tests.py -k apply_mail`
- **Done when:** against the fake `IMAP4_SSL`: only `select(..., readonly=True)` and `FETCH … BODY.PEEK[]`; a foreign-domain link is never returned; a code is extracted with the adapter pattern; `to_addr` keeps only the backup address's message; the backup address without `apply.mail_backup` maps to the main mailbox; timeout raises `email_verification_timeout`.
- **Requirements:** F-36, NF-02.

#### WP-V4 · Identity, accounts and mail in the orchestrator
- **STATUS:** TODO
- **Inputs:** AD §10.5 (`choose_identity` rules 1–4, the `already_registered` branch, one backup retry, `signin_failed` never retried), §10.2 (vault write before the sign-up click; outcomes; field-error rollback; exception keeps both), §4.1 (incl. `signing_up → signing_up`), §4.2 (Greenhouse code after Submit, one re-submit), §11.2, §11.5, §12.4.
- **Files:** `src/jobscraper/apply/accounts.py`, `src/jobscraper/apply_flow.py` (V-block), `src/jobscraper/store.py` (V-block: `accounts_for_tenant`, `applied_on_tenant`, `annotate_answers`).
- **Depends on:** WP-V1, WP-V3, WP-P8, lane B merged (WP-B11 included).
- **Lane:** V.
- **Do:** `choose_identity` (pure); the account-wall branch (`ctx.email` and `ResolveContext.account_email` = the identity); sign-up with §10.2 order and the backup retry; `verifying_email` via `MailWatcher` on the identity's mailbox with `to_addr`; `ctx.applied_on_tenant`; review notes through `annotate_answers`; Greenhouse `code_required` with `code_resubmits ≤ 1`.
- **Verify:** `python tests/run_tests.py -k apply_flow_accounts`
- **Done when:** with fakes: every `choose_identity` rule and both login-failed details; `already_registered` on the primary → one backup sign-up (vault entry for the primary deleted, row `exists_no_password`); on the backup too → `login_failed`; a `signin_failed` row → `login_failed` without a sign-in click; the vault entry exists before `sign_up`; a sign-up field error deletes the vault entry and the row; an exception after the sign-up click keeps both (`unknown`); no mailbox → `mail_not_set_up` before Submit and `submitted_unconfirmed` after it.
- **Requirements:** F-35, F-36, F-37, NF-02, NF-06.

#### WP-V5 · Workday: tenant, open and the Apply choice, account wall, sign in / sign up
- **STATUS:** TODO after WP-F1 (S-5 recordings).
- **Inputs:** AD §9.4 checklist items 1–4, §9.4.1, §9.4.2 (entry rule), §9.4.3 (forms, outcomes incl. `already_registered`, one sign-in submit), §9.4.4, §9.4.12; contracts v3 `WorkdayEntry`, `SignUpOutcome`.
- **Files:** `src/jobscraper/apply/ats/workday.py`, `src/jobscraper/apply/ats/__init__.py`.
- **Depends on:** WP-F1, WP-B4.
- **Lane:** V.
- **Do:** first check each S-5-marked selector this WP uses against the recordings and list confirmed/differing ids in the handoff (the recording wins); then `match_url` (forms A and B, canonical host), `tenant_from_company`, `open` (apply button, entry rule, `/apply/applyManually` fallback, `ctx.prefill`), `account_wall`, `sign_in`, `sign_up`, `enter_code`, `prefill`, constants; register `"workday"`.
- **Verify:** `python tests/run_tests.py -k workday_account`
- **Done when:** on the recorded pages served locally: both URL forms give the same tenant/vault service and agree with `parse_workday`; the entry rule picks "Use My Last Application" only with `applied_on_tenant`, never "Autofill with Resume"; sign-in and sign-up fill the right controls; each sign-up outcome is classified, including `already_registered` on the hand-built page.
- **Requirements:** F-31, F-34, F-35.

#### WP-V6 · Workday widgets
- **STATUS:** TODO after WP-F1.
- **Inputs:** AD §9.4 checklist items 7–10, §9.4.7 (every helper, the one allowed Enter, date sections by role, panels).
- **Files:** `src/jobscraper/apply/ats/workday_widgets.py`.
- **Depends on:** WP-F1, WP-B4.
- **Lane:** V.
- **Do:** `prompt_select`, `prompt_options`, `fill_date`, `panels`/`add_panel`/`delete_panel`, each with read-back; confirm the selectors on the recordings first.
- **Verify:** `python tests/run_tests.py -k workday_widgets`
- **Done when:** on the recorded my_experience and questions pages (with the tester's minimal script stubs for search and add/delete): a two-level how-heard prompt picks the leaf, dates fill in either section order, panels add and delete to the profile's count.
- **Requirements:** F-34.

#### WP-V7 · Workday wizard: steps, named and generic fields, review cross-check, submit, confirmation
- **STATUS:** TODO after WP-V5, WP-V6.
- **Inputs:** AD §9.4 checklist items 5, 6, 11–13; §9.4.5 (step id by container then title, `custom_<slug>`, guards), §9.4.6 (`read_values`), §9.4.8 (every named step; my_experience resume replace + exact section rebuild), §9.4.9 (adapter side: flagged labels in `StepResult.errors`), §9.4.10 (review parse, `review.json`, mismatch rules), §9.4.11, §6 Workday keys.
- **Files:** `src/jobscraper/apply/ats/workday.py`.
- **Depends on:** WP-V5, WP-V6, WP-V4 (for the end-to-end run).
- **Lane:** V.
- **Do:** confirm the step and field selectors on the recordings; `read_step`, `read_values`, `fill`, `next_step`, `submit`, `after_submit`, `visible_errors`.
- **Verify:** `python tests/run_tests.py -k workday_steps`
- **Done when:** on each tenant's recordings in dry-run mode the adapter reaches `review` with every field filled and read back; an unknown step title is read generically; a flagged required field yields `StepResult.errors`; a review value differing on a required field raises `validation_error`; the hand-built `confirm.html` yields `confirmed:*`.
- **Requirements:** F-31, F-34, F-37, F-38, F-39.

## 3. M20 integration and gate (Coordinator)

#### WP-I1 · M20 merge order and gate run
- **STATUS:** TODO (A-3 answered by D-68: `apply show`).
- **Inputs:** PRD §8 M20 gate; AD §19.1; TD §18; `05_workflow.md`; CLAUDE.md git rules.
- **Files:** none written by this WP besides `instructions/**` status (Coordinator scope).
- **Depends on:** all M20 WPs.
- **Lane:** Coordinator (integration branch `int/M20`).
- **Do (in order; full suite `python tests/run_tests.py` green and a smoke `python -m jobscraper doctor` after every merge; smoke-check `personal` after each merge because the live app runs from it):**
  1. `int/M19` → `personal` (Q-12), then WP-A00 (tester), then `arch/Q-04-designs` and this plan branch → `personal`.
  2. Data and fixtures: WP-A01, TB WP-T00 (researcher), WP-A02, TB WP-T01 (tester) → `personal`.
  3. Lane P (WP-P1…P6) → `personal`.
  4. Lane T (TB WP-T1…T8) → `personal` (it depends on WP-P1/P2 already there).
  5. Lane B rebased on `personal`; WP-B9, B10, B11, B12 on lane B; then lane B → `personal`. `store.py`, `cli.py`, `config.py`, `config/config.yaml`, `requirements.txt`, `web/jobs.py`: keep every lane's block per §2.1; `SCHEMA_VERSION` = 3 exactly once.
  5a. (D-70) WP-S5 → WP-F1 (tester) → `personal`; lane V (V1–V3 may merge early; V4–V7 after lane B) rebased on `personal` → `personal`. Owner task Q-24 (`apply open-profile`, MyGreenhouse sign-in) after lane B merges, then WP-S6 and the WP-B12 confirmation.
  6. Owner task Q-13: the owner copies `config/applicant.example.yaml` to `data/applicant.yaml`, fills it, and gives the application email; `python -m jobscraper applicant check` exits 0.
  7. **Gate (D-70):** (a) Greenhouse: the owner picks 5 open Greenhouse postings; in the main checkout with a copy of the DB (`JOBSCRAPER_DB=<copy>`), `python -m jobscraper apply <id1> … <id5> --dry-run`; each ends `ready_to_submit` or a correct reason code, at least one through MyGreenhouse autofill (`apply show` lists `mygreenhouse` sources) with the tailored resume attached. (b) Workday: Workday dry runs at the 2 owner-approved employers end `ready_to_submit` with no review mismatch; then the owner (who approved automatic submission there, D-70) runs `python -m jobscraper apply <job_id>` for each with `apply.mode: auto` against the live DB; each ends `submitted` (or `submitted_unconfirmed` resolved by the owner) and shows "Applied by JobScraper"; the first saves `confirm.html` for the tester. (c) The owner reads every attempt with `python -m jobscraper apply show <id>` and finds no wrong answer. The Coordinator never clicks Submit or runs a real submission.
- **Verify:** `python tests/run_tests.py`
- **Done when:** the suite is green on `personal`, the 5 dry-run outcomes and the owner's audit verdict are recorded in `02_status.md`, the owner's submission ended `submitted`, NF-07 timings noted (attempt ≤ 4 min, tailoring ≤ 10 s deterministic).
- **Requirements:** PRD §8 M20 gate (re-scoped by D-70): F-10, F-11, F-20, F-21, F-22 (swaps), F-23, F-31–F-39; NF-02, NF-06, NF-07, NF-08.

## 4. M21 lanes (MVP)

At most 3 engineer lanes run at once (CLAUDE.md rule 6). Slots: **W** and **L** start at once after M20; when L is done its slot runs the small **tailor lane TL** (TB §4: LLM JD-term extraction only; by D-67 the LLM bullet and summary rewrite moved to M22). Lane V moved into M20 (D-70, §2.4); only `apply/edge_save.ps1` (the Edge sync route) remains for M21, as a W-lane task when the owner chooses the sync route.

| Lane | Branch | Own files | Shared-file blocks |
|---|---|---|---|
| **L** Lever + Ashby | `eng/M21-L-lever-ashby` | `src/jobscraper/apply/ats/lever.py`, `src/jobscraper/apply/ats/ashby.py` | `apply/ats/__init__.py` two `REGISTRY` lines |
| **W** web API + UI | `eng/M21-W-web` | `src/jobscraper/web/routers/{applicant,apply,tailor}.py`, `src/jobscraper/applicant.py` (M21: `from_resume`), `web/src/**` new files and the tabs named per WP | `cli.py` W-block (`applicant init` subcommand inside `cmd_applicant`); `web/src/api.js` W-block |
| **F** fixtures (tester) | `test/M21-fixtures` | `tests/fixtures/{lever,ashby}/**`, the §6 M21 test files (Workday and mail fixtures moved to M20: WP-F1, WP-F4) | — |

`web/routers/applications.py` (existing) gets one W-block (WP-W4). No M21 WP changes `store.py` (the M20 methods cover M21).

### 4.1 Lane V

Moved into M20 by D-70: see §2.4 (WP-V1…V7).

### 4.2 Lane L: Lever and Ashby

#### WP-L1 · Lever adapter
- **STATUS:** TODO
- **Inputs:** AD §9.2 (all rows; K selectors confirmed on the fixture first); AD §15.
- **Files:** `src/jobscraper/apply/ats/lever.py`, `src/jobscraper/apply/ats/__init__.py`.
- **Depends on:** M20 merged, WP-F2 (recorded Lever page).
- **Lane:** L.
- **Do:** first confirm each AD §9.2 selector on the recorded page and list confirmed/differing ones in the handoff (the fixture wins); then the adapter: tenant/URL, `open`, `read_step` (standard fields + custom cards from `[baseTemplate]` JSON + EEO + consent), `fill`, `next_step` (single page → review), `submit`, `after_submit`, `visible_errors`; register `"lever"`.
- **Verify:** `python tests/run_tests.py -k apply_lever`
- **Done when:** on the recorded page served locally, a dry run reaches review with every field resolved and filled; the thanks fixture yields `confirmed:*`.
- **Requirements:** F-31, F-34, F-37, F-38.

#### WP-L2 · Ashby adapter
- **STATUS:** TODO
- **Inputs:** AD §9.3 (all rows; selectors confirmed on the fixture first).
- **Files:** `src/jobscraper/apply/ats/ashby.py`, `src/jobscraper/apply/ats/__init__.py`.
- **Depends on:** M20 merged, WP-F2 (recorded Ashby page).
- **Lane:** L.
- **Do:** same pattern as WP-L1: selector check first; tenant (incl. `#ashby_embed` employer pages via `external_id`), `open` (wait for "Fetching application form" to go), system fields (never the autofill-from-resume input), custom fields by control type incl. Yes/No button pairs, submit, confirmation, errors; register `"ashby"`.
- **Verify:** `python tests/run_tests.py -k apply_ashby`
- **Done when:** as WP-L1 on the Ashby fixture.
- **Requirements:** F-31, F-34, F-37, F-38.

### 4.3 Lane W: web API and UI

Each Vue WP also adds its calls to `web/src/api.js` (W-block at the end of the file). UI copy is AD §14.4 / TD §13.4 verbatim. The SPA bundle is built only by the Coordinator in the main checkout after merging.

#### WP-W1 · Applicant API and `applicant init`
- **STATUS:** TODO
- **Inputs:** AD §5.5 (`from_resume`, `applicant init`), §14.3 `GET/PUT /api/applicant` (shapes, 422).
- **Files:** `src/jobscraper/web/routers/applicant.py`, `src/jobscraper/applicant.py`, `src/jobscraper/cli.py` (W-block: `init` subcommand of `applicant`).
- **Depends on:** M20 merged.
- **Lane:** W.
- **Do:** router (no stage import; foundation only); `applicant.from_resume(profile_derived, master)` (education/experience copied verbatim from master entries of kind education/experience, `from_resume: true`; skills from `profile.derived.yaml`; links from master contact); `applicant init` refuses when the file exists.
- **Verify:** `python tests/run_tests.py -k web_applicant`
- **Done when:** GET returns `{profile, errors, missing, completeness, from_resume, sensitive}`; PUT with a bad postal code returns 422 naming `contact.postal_code` and saves nothing; `init` writes entries with `from_resume: true` from a fixture master.
- **Requirements:** F-10 (prefill), F-11 (validation API), NF-03 (loopback host check unchanged).

#### WP-W2 · Apply API: start, attempts, screenshots, outcome
- **STATUS:** TODO
- **Inputs:** AD §12.2 (preflight with foundation calls only), §14.3 rows `POST /api/apply`, `GET /api/apply/attempts[?job_id]`, `GET /api/apply/attempts/{id}`, screenshots (name regex), `POST …/outcome` (§4.3).
- **Files:** `src/jobscraper/web/routers/apply.py`.
- **Depends on:** WP-W1.
- **Lane:** W.
- **Do:** endpoints as specified; `text`/`hint` from `REASON_TEXTS`; reap first when no apply job runs; batch: only eligible ids go to the job (≤ 20); 409 busy; 422 `profile_incomplete` with `missing`. "It went through" also marks the current tailored file sent (`store.mark_tailored_sent`).
- **Verify:** `python tests/run_tests.py -k web_apply_attempts`
- **Done when:** refusals carry reason codes (duplicate, cap, profile); screenshot names outside the regex return 404; outcome on a non-`submitted_unconfirmed` attempt returns 409.
- **Requirements:** F-30 (batch, refusals, caps), F-37 (owner outcome), F-38 (reason + "Open the posting" data), F-39 (detail API), NF-06.

#### WP-W3 · Apply API: settings, mailbox, accounts
- **STATUS:** TODO
- **Inputs:** AD §14.3 rows settings, mail-password, mail-test, accounts (list, add, password, export-edge, confirm); §10.3 (stale CSV cleanup on startup and on Accounts load), §10.4.
- **Files:** `src/jobscraper/web/routers/apply.py`.
- **Depends on:** WP-W2, WP-V1 (vault on `personal`).
- **Lane:** W.
- **Do:** endpoints as specified (`Cache-Control: no-store` on the password response; 422 ranges: caps 1–50, wait 0–600, port 1–65535); `vault.purge_stale_exports` on the accounts list call and once at router import; mail username stored only in the settings table.
- **Verify:** `python tests/run_tests.py -k web_apply_settings`
- **Done when:** settings round-trip and validate; the password endpoint never appears in any other response; export/confirm create and delete the CSV.
- **Requirements:** F-35 (Copy password, export, add account), F-36 (mailbox settings, test), F-40, NF-02.

#### WP-W4 · Tailor API and "Mark applied" → sent
- **STATUS:** TODO
- **Inputs:** TD §13.3 (four endpoints), §11.3 (`mark_tailored_sent` on the web "Mark applied"), TD §13.2.
- **Files:** `src/jobscraper/web/routers/tailor.py`, `src/jobscraper/web/routers/applications.py` (W-block: one call when status becomes `applied`).
- **Depends on:** M20 merged.
- **Lane:** W.
- **Do:** endpoints as specified (attest appends the JD spelling to `attested_skills` through `applicant.save`, deduped by normalised text); setting an application to `applied` marks the job's current draft `sent`.
- **Verify:** `python tests/run_tests.py -k web_tailor`
- **Done when:** POST starts a `tailor` job (409 busy, 404 unknown job); GET returns the TD §13.3 shape; file download sets the `<First>_<Last>_Resume.<ext>` name and 404s after purge; attest is idempotent.
- **Requirements:** F-22 ("I have this" → `attested_skills`), F-24 (sent status), F-25.

#### WP-W5 · Profile → Application details form
- **STATUS:** TODO
- **Inputs:** AD §14.4 Profile bullet; §5.4 group order; §5.3 sensitive groups.
- **Files:** `web/src/tabs/Profile.vue`, `web/src/components/ApplicationDetails.vue` (new), `web/src/api.js`.
- **Depends on:** WP-W1.
- **Lane:** W.
- **Do:** form groups in AD §5.4 order, meter "N of M needed details filled", "From resume, check" chips (cleared on save of that entry), "Never sent to the AI" on sensitive groups, declarations as Yes/No switches with plain question text, inline errors from the 422 response.
- **Verify:** `npm --prefix web test -- tests/ApplicationDetails.test.js`
- **Done when:** the component test renders the groups, shows the meter from the GET payload, and shows `contact.postal_code`'s error inline after a 422.
- **Requirements:** F-11, F-10 (from-resume chips, declarations editable).

#### WP-W6 · Inbox: Auto-apply, multi-select, attempt panel
- **STATUS:** TODO
- **Inputs:** AD §14.4 Inbox and Attempt panel bullets; F-38 bullet 3.
- **Files:** `web/src/tabs/Inbox.vue`, `web/src/components/AttemptPanel.vue` (new), `web/src/api.js`.
- **Depends on:** WP-W2.
- **Lane:** W.
- **Do:** "Auto-apply" primary button, disabled with "Finish your application details first" when `missing` is non-empty; "Auto-apply to selected (N)"; confirm dialog only in `auto` mode with AD copy; refusals as a toast list; `AttemptPanel` (state chips, reason text + hint, "Open the posting" on failure, "It went through" / "It didn't go through", link to the audit).
- **Verify:** `npm --prefix web test -- tests/AttemptPanel.test.js`
- **Done when:** chips and copy match AD §14.4 for each state; the outcome buttons appear only on `submitted_unconfirmed`; the Inbox button is disabled when the profile is incomplete.
- **Requirements:** F-30 (start from Inbox, batch), F-37 (owner check), F-38 (reason and "Open the posting").

#### WP-W7 · Tailor panel (Inbox and Applications)
- **STATUS:** TODO
- **Inputs:** TD §13.4 (all bullets, copy verbatim, issue-code texts).
- **Files:** `web/src/components/TailorPanel.vue` (new), `web/src/tabs/Inbox.vue`, `web/src/tabs/Applications.vue`, `web/src/api.js`.
- **Depends on:** WP-W4, WP-W6 (Inbox.vue edited after it, same lane).
- **Lane:** W.
- **Do:** "Tailor resume" button and progress text; coverage headline with the "Not an ATS score" help; missing chips with the "I have this" confirm → attest → "Tailor again"; possibly related; application questions to expect; per-entry Before/After word diff, trimmed struck through, fallback "Kept original: <issue text>"; downloads; status line.
- **Verify:** `npm --prefix web test -- tests/TailorPanel.test.js`
- **Done when:** the component test shows "JD keyword coverage: 29% → 64%" for case A's payload, the attest confirm copy, and a fallback label for a `number_added` issue.
- **Requirements:** F-25, F-21 (coverage naming), F-22 ("I have this"), F-24 (status line).

#### WP-W8 · Applications: "What I told this employer"
- **STATUS:** TODO
- **Inputs:** AD §14.4 "What I told this employer" bullet; §14.3 attempt detail and screenshot endpoints.
- **Files:** `web/src/components/AuditView.vue` (new), `web/src/tabs/Applications.vue`, `web/src/api.js`.
- **Depends on:** WP-W2, WP-W7 (Applications.vue edited after it).
- **Lane:** W.
- **Do:** outcome line; resume file sent (name, tailored/original, link to the tailor diff); table Question · Answer · Source badge (Form field / Your profile / Remembered / Declaration / AI) · Confidence; sensitive answers first under "Personal declarations"; "written by AI" flag; screenshot strip with enlarge; the attempt panel (WP-W6) on Applications detail.
- **Verify:** `npm --prefix web test -- tests/AuditView.test.js`
- **Done when:** given a fixture attempt payload, sensitive rows render first and tier-5 rows carry the AI flag and badge.
- **Requirements:** F-39, F-38 (failed attempts in the role's panel).

#### WP-W9 · Settings → Apply and Accounts
- **STATUS:** TODO
- **Inputs:** AD §14.4 Settings bullets; §11.4 (mailbox steps text); §10.3 (import path text, first-export note).
- **Files:** `web/src/tabs/Settings.vue`, `web/src/components/ApplySettings.vue` (new), `web/src/components/AccountsList.vue` (new), `web/src/api.js`.
- **Depends on:** WP-W3.
- **Lane:** W.
- **Do:** Apply section (mode, limits, headed, captcha wait, mailbox with "Saved" state and Test connection); Accounts table with Copy password (clipboard only, never rendered), "Export new passwords for Edge" (shows the import path and the first-export note), "I've imported it", "Add an account you already have".
- **Verify:** `npm --prefix web test -- tests/ApplySettings.test.js`
- **Done when:** the settings form posts the AD shape and shows 422 errors; the password is never placed in the DOM.
- **Requirements:** F-40, F-35 (accounts UI), F-36 (mailbox UI), NF-02.

### 4.4 Lane F: M21 fixtures (tester)

WP-F1 (Workday fixtures) moved into M20 (§1), built from the S-5 recordings.

#### WP-F2 · Record a Lever page and an Ashby page
- **STATUS:** TODO
- **Inputs:** AD §9.2, §9.3.
- **Files:** `tests/fixtures/lever/apply.html`, `tests/fixtures/lever/thanks.html`, `tests/fixtures/ashby/application.html`, `tests/fixtures/ashby/submitted.html`, plus the WP-L1/L2 tests.
- **Depends on:** nothing.
- **Lane:** F.
- **Do:** as WP-F1, one public posting each, dry-run only; the thanks/submitted pages may be hand-built from the AD confirmation text.
- **Verify:** `python -c "from pathlib import Path as P; a=P('tests/fixtures/lever/apply.html').read_text(encoding='utf-8'); b=P('tests/fixtures/ashby/application.html').read_text(encoding='utf-8'); assert 'email' in a and 'resume' in a; assert '_systemfield_email' in b; print('ok')"`
- **Done when:** the command prints `ok`.
- **Requirements:** F-31.

WP-F4 (fake IMAP fixtures) moved into M20 (§1).

### 4.5 M21 integration and gate (Coordinator)

#### WP-I2 · M21 merge order and gate
- **STATUS:** TODO
- **Inputs:** PRD §8 M21 gate, §3 G1/G2; TB WP-I-T (tailor gate items).
- **Files:** none (Coordinator records status).
- **Depends on:** all M21 WPs (Workday and mail were proven at the M20 gate).
- **Lane:** Coordinator (`int/M21`).
- **Do:** merge order: lane F fixtures → lane L → lane W (`vault.py` is already on `personal` from M20) → lane TL (TB §4). Coordinator builds the SPA in the main checkout after W merges (`cd web; npm run build`) and commits the bundle. Full suites green after each merge. Gate (owner-triggered submissions only, `apply.mode: auto` set by the owner in Settings): 10 real applications submitted automatically across ≥ 3 ATSs including Workday; record per-ATS rates against G1 (≥ 70% Greenhouse/Lever/Ashby, ≥ 50% Workday) and G2 (every failure has reason, step, screenshot; 0 duplicates); tailoring golden A–C pass; NF-01 test passes; NF-07 timings recorded.
- **Verify:** `python tests/run_tests.py`
- **Done when:** the suite and `cd web; npx vitest run` are green on `personal`, and the gate numbers are recorded in `02_status.md`.
- **Requirements:** PRD §8 M21 gate: F-11, F-22–F-25, F-30, F-35–F-37, F-40, NF-01–NF-09; G1, G2.

## 5. Critical path

**M20 (D-70), two chains that meet at the gate:**

- **Greenhouse chain:** WP-A00 + designs merged → WP-P1 → lane P (P2…P8) ∥ lane T ∥ lane B (B1…B8 on stubs, then B10, B11) → merge P, then T → WP-B9 → lane B merged → owner task Q-24 (`apply open-profile`) → WP-S6 → WP-B12 confirmation.
- **Workday chain (longest):** owner gives email + Gmail app password (Q-14) → **WP-S5** (real flow at 2 employers, to Review) → **WP-F1** (scrubbed fixtures) → WP-V5 ∥ WP-V6 (both also need WP-B4) → **WP-V7**; in parallel V1 → V3 (needs WP-F4) → **WP-V4** (needs lane B merged and WP-P8) → lane V merged.
- Then owner fills `data/applicant.yaml` incl. `backup_email` (Q-13) → **M20 gate** (WP-I1 step 7: Greenhouse dry runs incl. MyGreenhouse; Workday dry runs then the owner's 2 real submissions).

Longest M20 chain: Q-14 → S5 → F1 → V6 → V7 → (V4 merged) → I1. It is gated by the owner's email/app password and the 2 employer choices, so S-5 should start the moment those arrive; V1–V3 and lane B proceed meanwhile.

**M21:** lane W ∥ lane L → TL → **M21 gate** (WP-I2).

## 6. Tests and fixtures this plan relies on (tester; coordinated in `comms/outbox/planner.md`)

| WP | Test file (needle) | Fixtures |
|---|---|---|
| A00 | `tests/test_layering.py` (`layering`), `tests/test_privacy.py` (`privacy`) | — |
| P1 | `tests/test_backend_options.py` (`backend_options`) | fake httpx client |
| P4 | `tests/test_apply_resolve_rules.py` (`apply_resolve_rules`) | `tests/fixtures/apply/applicant_synthetic.yaml`, `config/questions.yaml` |
| P5 | `tests/test_apply_declarations.py` (`apply_declarations`) — golden, always kept | synthetic profile |
| P6 | `tests/test_apply_resolve_llm.py` (`apply_resolve_llm`) | scripted fake backend |
| B1 | `tests/test_apply_store.py` (`apply_store`) — duplicate guards always kept | a v2 DB built in the test |
| B3 | `tests/test_apply_classify.py` (`apply_classify`) | `tests/fixtures/apply/pages/*.html` |
| B4 | `tests/test_apply_browser.py` (`apply_browser`) | `tests/fixtures/greenhouse/form.html`, `tests/fixtures/apply/resume.pdf` |
| B5 | `tests/test_apply_greenhouse_plan.py` (`greenhouse_plan`) | `tests/fixtures/greenhouse/gh_vercel.json`, `gh_dataiku.json` |
| B6 | `tests/test_apply_greenhouse_fill.py` (`greenhouse_fill`) | `form.html` |
| B7 | `tests/test_apply_flow.py` (`apply_flow`) | fake adapter, fake browser |
| B8 | `tests/test_apply_cli.py` (`apply_cli`) | fake flow |
| B9 | `tests/test_apply_e2e.py` (`apply_e2e`) | all of the above + `tests/fixtures/tailor/master_a.json` |
| A03, P7 | `tests/test_apply_resolve_rules.py` (`apply_resolve_rules`): `yes_if` cases (AD §7.3.3 worked examples) | `config/questions.yaml`, synthetic profile |
| P8 | `tests/test_apply_contracts.py` profile/template oracles + backup-email cases | `applicant.sample.yaml` (+ `backup_email`) |
| B10 | `tests/test_apply_cli.py` (`apply_cli`): `open-profile` | fake session factory |
| B11 | `tests/test_apply_flow.py` (`apply_flow`): KEEP / OVERWRITE tables, planning deferral, corrective retry | fake adapter with `prefill`/`read_values` |
| B12 | `tests/test_apply_greenhouse_fill.py` (`greenhouse_fill`): MyGreenhouse variants; `tests/test_apply_greenhouse_plan.py`: §9.1.2 label rule | `form.html` variants (button + delayed fill; sign-in dialog; none), `tests/fixtures/apply/greenhouse/mygreenhouse/` after S-6 |
| V1 | `tests/test_apply_vault.py` (`apply_vault`) | fake keyring backend |
| V2 | `tests/test_accounts_cli.py` (`accounts_cli`) | fake keyring |
| V3 | `tests/test_apply_mail.py` (`apply_mail`) | `tests/fixtures/mail/*.eml` (incl. the backup-address message) |
| V4 | `tests/test_apply_flow_accounts.py` (`apply_flow_accounts`) | fakes (identity rules, backup retry, mailbox per address) |
| V5, V6, V7 | `tests/test_workday_account.py` (`workday_account`), `tests/test_workday_widgets.py` (`workday_widgets`), `tests/test_workday_steps.py` (`workday_steps`) | `tests/fixtures/apply/workday/<tenant>/` (S-5 recordings, scrubbed; hand-built `confirm.html`, `already_registered.html`) |
| L1, L2 | `tests/test_apply_lever.py` (`apply_lever`), `tests/test_apply_ashby.py` (`apply_ashby`) | `tests/fixtures/lever/`, `tests/fixtures/ashby/` (M21) |
| W1–W4 | `tests/test_web_applicant.py` (`web_applicant`), `tests/test_web_apply_attempts.py` (`web_apply_attempts`), `tests/test_web_apply_settings.py` (`web_apply_settings`), `tests/test_web_tailor.py` (`web_tailor`) | FastAPI TestClient, copied fixture DB |
| W5–W9 | `web/tests/ApplicationDetails.test.js`, `AttemptPanel.test.js`, `TailorPanel.test.js`, `AuditView.test.js`, `ApplySettings.test.js` | JSON payloads |

Note: `-k apply_flow` also selects `test_apply_flow_accounts.py` once it exists; both must pass.

## 7. Requirement coverage (M20, M21)

| Req | WPs |
|---|---|
| F-10 | P2, P3, P5, P8, W1, W5 |
| F-11 | P2, P3, P8, W1, W5 |
| F-12 (lookup only; M22 writes) | P4 |
| F-30 | B1, B7, B8, W2, W6 |
| F-31 | B5, B12, S5, F1, V5, V7, L1, L2 |
| F-32 | P1, P4, P5, P6, P7, A03, B9, B11 |
| F-33 | P4, P5, P7, A03, B9 |
| F-34 | B4, B6, B7, B9, B10, B11, B12, S6, V5, V6, V7, L1, L2 |
| F-35 | S5, V1, V2, V4, V5, P8, B10, W3, W9 |
| F-36 | S5, F4, V3, V4, W3, W9 |
| F-37 | B1, B6, B7, B8, V4, V7, I1 (real Workday submissions), W2, W6 |
| F-38 | B3, B6, B7, B11, V7, W2, W6, W8 |
| F-39 | B1, B7, B9, B11, V7 (review cross-check), W2, W8 |
| F-40 | B2, B8, V2, W3, W9 |
| NF-01 | A00, A02, P2 |
| NF-02 | P3, P6, B7, V1–V4, W3, W9 |
| NF-03 | P1, P6, W1 |
| NF-04 | A00 (every WP keeps it green) |
| NF-05 | B2, B4, B7 |
| NF-06 | B1, B7, V4, W2 |
| NF-07 | I1, I2 |
| NF-08 | §0 dev rule, I1 |
| NF-09 | P3, B7, B8 |

Tailor requirements (F-20–F-25) are covered in TB §6. M20 now covers F-35 and F-36 (were M21) and the Workday half of F-31/F-34/F-37 (D-70).

## 8. Open questions to the architect (raised in `comms/outbox/planner.md`; not invented here)

| # | Gap | Blocks | Planner's note (a suggestion only; the architect decides) |
|---|---|---|---|
| A-1 | Grounding rule 3 (AD §7.7) needs the `aliases.yaml` dictionary terms, but `ResolveContext` and `resolve_all` carry no such input, and `apply/` may not import `tailor/` | WP-P6 rule 3 | e.g. a `dictionary_terms: tuple[str, ...]` field on `ResolveContext`, filled by `apply_flow` from `config/aliases.yaml` (contract change) |
| A-2 | `ResolveContext.resume_text` = "master resume text" (AD §7.6), but `tailor_flow`'s public API (TD §2) returns no master text, and there is no master when tailoring is off or failed | WP-B9 | e.g. a `tailor_flow.master_text(cfg)` function, or the extracted text of the resume file actually uploaded |
| A-3 | The M20 gate needs the owner to "read the audit", but the audit view is M21 web UI and no CLI prints an attempt's `apply_answers` | WP-I1 step 7 | e.g. `apply show <attempt_id>` printing Question · Answer · Tier · Source to the terminal (not a job log) |
| A-4 | `computed_facts.experience_months` (AD §5.1): month arithmetic for `YYYY-MM` spans is not defined (inclusive or not; overlapping entries) | WP-P3 (that function only) | — |

Planner allocations made here (not design changes): `apply/plan.py` moved from lane B to lane P (§2); `SCHEMA_VERSION` bump owned by lane B (§2.1); `paths.applicant`/`paths.questions` config lines owned by lane B, the `Config` properties by lane P; effective settings resolved in `cmd_apply` (WP-B8); `redact()` placed in `apply_flow.py` (WP-B7); M21 fixture recording done by the tester (engineers may not write `tests/**`).
