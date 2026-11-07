# ADR-0006: The local model fills every application page; site modules only navigate; deterministic locks and guards keep it fail-closed

**Status:** Proposed (D-78, Q-35); amended after stage E (review `docs/reviews/Q-35-design.md`; D-81, D-82, D-83), see "Amendment" below
**Date:** 2026-11-03
**Deciders:** owner (D-78: direction), Coordinator (acceptance), architect (shape)
**Relates to:** PRD F-31–F-34, F-12, F-13, F-37–F-39, NF-02–NF-07; `llm_fill_design.md`; `apply_design.md` §6–§9; ADR-0003 (fail-closed), ADR-0004 (no failure after the click), ADR-0005 (answers in the profile); contracts v5
**Supersedes in part:** `apply_design.md` §7.2 (tier-1 site tagging), §7.6 (per-field tier 5), §9.1.1 KEEP table, §9.4.2 step 3 ("Autofill with Resume is never clicked"), §9.4.5–§9.4.10 (Workday named steps, OVERWRITE table, review parse)

## Context

The M20 design answered fields deterministically first (tier 1: fields the adapter tags from site ids; tiers 2–4: label rules, owner answers, declarations) and asked the local model one field at a time last (tier 5). For Workday that meant a per-step table of `data-automation-id`s and a rebuild of every repeated section by hand.

The owner (D-78): "Calls should be made to the LLM to do the filling up of the forms. It should not be manual entry as manual entry hardcoded is vulnerable to systems changing … the LLM should be the one filling the information up, deciding whether the information comes from applicant.yaml / resume"; and "if there are options to 'import from resume', it should always choose that". Guard rails stay (D-78): standing answers as facts, grounding, unknown required → stop + Questions inbox, CAPTCHA stop, caps, NF-06.

Spike S-5b (`spikes/S-5b_llm_workday.md`) ran a prototype (generic page reader → one `qwen3:14b` call per page with a JSON schema → guards → generic fill) on two Workday tenants with no per-tenant code: one application submitted and confirmed; the other stopped correctly on a required field the profile could not back. About 9 of ~83 first-pass answers were wrong; all were caught before Submit, but some only by the agent's manual review, so the guards must grow.

Forces: the model is local and free but small (14B) and slow on long pages (~50 s for 54 fields); the repo is public and S values never go into a prompt (AD §5.3); a wrong submitted answer can't be taken back (ADR-0003, ADR-0004).

## Decision

1. **Per page, the model decides the source of every open field** (`profile` / `extra` / `standing` fact by exact ref, `resume` or `job` with a verbatim quote, `keep` the shown value, or `unknown`), in one schema-constrained call per chunk (an entry group = one chunk).
2. **The program writes every fact-sourced value** with the existing deterministic mappers (`resolve.fit_*`); the model's own text is used only for resume/job values, and only after guards (grounding, choice-vs-source, entry scope, a second agreeing run for every model-chosen Yes/No and required choice, prefill trust, sensitive). A fact the model cites is used only when it is relevant to the question and belongs to the field's entry. Sensitive facts are shown to the model as "private, set/empty" only, and S values are redacted from every prompt.
3. **Deterministic locks run first and the model can't override them:** the resume file, the account email, declarations (tier 4), D-75 work rights, sensitive tier-2 keys, consents, and the owner's own answers (`extra`, with the generic-label guard). They are shown to the model as context.
4. **Site modules implement `SiteNavigator` only** (open, take the resume import, account wall, step id, entry sections, Next, Submit, confirmation). Field reading and filling are generic (`page.py`, `widgets.py`, `pagefill.py`).
5. **Resume import is always taken**; the imported file is the tailored resume; every imported value is checked like any other (entries matched, junk deleted, descriptions rechecked).
6. **Unchanged:** the attempt state machine, submit once, `submitted_unconfirmed`, caps, CAPTCHA/bot stops, dry run default, the Questions inbox as the place an unknown required answer goes. New reason code `model_unavailable`.

## Options considered

### Option A: Keep the M20 design (deterministic tiers, site-tagged fields, per-field tier 5)

| Dimension | Assessment |
|---|---|
| Complexity | High per site: Workday named-step tables, panel rebuilds, prompt helpers; every new site or layout change is code |
| Cost | Free (local); fewest model calls |
| Robustness to site change | Low: an id or step change breaks a field (the owner's objection) |
| Safety | High: most answers deterministic |

**Pros:** built and tested for Greenhouse; predictable. **Cons:** contradicts D-78; Workday tables never validated against real pages; long tail of questions ends `unknown`.

### Option B: Per-page model fill with deterministic navigation, locks and guards (chosen)

| Dimension | Assessment |
|---|---|
| Complexity | Medium, once: a generic reader, widget families, prompt, guards. Per site: navigation only |
| Cost | Free (local); ~5–15 calls per attempt; Workday attempt ~5–6 min |
| Robustness to site change | High: S-5b ran unchanged on two tenants |
| Safety | High if the guards hold: facts are written by the program, model text is grounded, unknown required stops |

**Pros:** meets D-78; one code path for every ATS; long-tail questions get answered from the resume when grounded. **Cons:** slower; model errors need guards (S-5b found six error kinds); prompts must be tested with a fake model.

### Option C: A browser agent (browser-use / Skyvern style): the model also navigates and clicks

| Dimension | Assessment |
|---|---|
| Complexity | Low code, high unpredictability |
| Cost | Many more calls (each action is a model turn); a 14B local model is weak at multi-step agent loops |
| Robustness | High in theory |
| Safety | Low: Submit-once (NF-06), the CAPTCHA rule and caps would depend on the model's choices; hard to audit |

**Pros:** least site code. **Cons:** gives the model the Submit button; non-deterministic navigation; Skyvern is AGPL and its hosted product solves CAPTCHAs (against our rules).

## Trade-off analysis

B keeps the parts where a mistake is irreversible or private (navigation, Submit, sensitive values, declarations, the owner's explicit answers) deterministic and gives the model the part that breaks hand-written code: understanding varied questions and layouts. It costs latency (NF-07 deviation on Workday) and new test machinery (fake-model fixtures). A would keep latency low but fails the owner's goal; C trades away the safety properties ADR-0003/0004 exist for.

## Consequences

- Easier: a new ATS is navigation only (5 steps, `llm_fill_design.md` §9.4); tenant-specific questions and new layouts need no code; the Questions inbox still catches what can't be backed.
- Harder: correctness depends on guard quality; regressions need recorded pages plus fake model replies; a model change (version, quantisation) needs a re-run of the fixture suite and a dry run.
- Contracts v5 add types and `SiteNavigator`; `AtsAdapter`'s fill-side methods, `PrefillPolicy`/`PREFILL_POLICY` and tier-1 site tagging are removed by the cleanup WP (WP-C1) once both ATSs run on the new path. Lane B's Greenhouse fill code and WP-B11's prefill tables retire then.
- Revisit: the confidence of `keep` on resume-import values after the first real runs; whether the owner wants locks to move to the model (D-82 keeps them deterministic; a change needs an ADR-0003 change and the owner); `max_fields_per_call` and `long_list` after measuring; a bigger model if the guards reject too much.

## Amendment (stage E, 2026-11-03)

The decision stands; the review tightened how it is kept safe. Details: `llm_fill_design.md` (amended) and the change log in `comms/outbox/architect.md`.

- **Locks stay deterministic (D-82, answers O-1).** The owner may revisit.
- **ADR-0003 §3 holds unchanged:** every model-chosen Yes/No (required or optional) and every required choice or number whose value is the model's needs two agreeing runs (G5); with the second opinion switched off those answers end unknown.
- **Audit:** an answer whose fact the model chose (value written by the program) is recorded as tier LLM with source `profile:<path>` / `standing:<id>` / `memory:extra.<key>`, rule id `fill:v2`, the model and the prompt hash; a lock keeps its old tier. So F-39's audit always tells a model choice from a deterministic one.
- **Untrusted site values never stay by default:** an imported or site-default value the model didn't back with evidence is cleared, reset or flagged "unverified" (G9); only non-free-text MyGreenhouse values are trusted without a quote; a required resume-import value is kept only when grounded (D-83).
- **Revealed and required fields are re-scanned** before Next and before Submit, deterministically.
- **NF-07 (D-81):** Greenhouse ≤ 4 min (420 s deadline), Workday 900 s; both exclude the IMAP wait and are measured at the gate.
- **Gate (D-83):** 5 Greenhouse dry runs; each dry-run audit read row by row before a real submission; gate Workday postings need fresh owner approval.
- Contracts stay v5 (additive): `ResolveContext.resume_entries`/`other_employers`, `AttemptContext.pre_import`/`uploaded`, `PageOutcome.transport_failed`, `FillServices`.
- **Composed texts (Q-45, D-86 F9; `llm_fill_design.md` §19):** cover letters and "why join" answers are never written by the page model. The tailor composes them in a separate call, only when the owner opts in (`apply.compose.enabled`, default off). Every claim is checked deterministically against the master resume (numbers, facts, upgrade words, S values, other employers; tailor validator rules). Off, or a failed check → a `compose_needed` question for that posting. The audit row holds the whole text. Tailor contracts v2 (additive).

## Action items

1. [ ] Build per `llm_fill_build_plan.md` (lanes M, R, N; tester T1–T4).
2. [ ] Stage-E pointers in `apply_design.md` to the superseded sections (architect/planner).
3. [ ] PRD: D-78 sentence under F-32/F-34, NF-07 Workday deviation, reason code `model_unavailable` (planner).
4. [ ] M20 gate (D-83): 5 Greenhouse dry runs, audits read row by row, and the two Workday submissions on postings the owner approves afresh, on the new path.

## Sources

- browser-use (MIT; indexed interactive elements): https://pypi.org/project/browser-use/0.1.0 , https://besthub.dev/articles/behind-95k-stars-browser-use-s-llm-browser-automation-vs-playwright-c9798935fe64 (search, 2026-11-03)
- Stagehand (MIT; act/extract/observe, caching): https://browserbase.com/stagehand , https://docs.stagehand.dev/v3/basics/act (search)
- Skyvern (AGPL-3.0 core; cloud adds anti-bot and CAPTCHA solving): https://www.github.com/Skyvern-AI/skyvern/blob/main/README.md , https://landscape.jimmysong.io/projects/skyvern/ (search)
- AIHawk (AGPL-3.0; auto-apply removed from the open-source repo): https://awesome.ecosyste.ms/projects/github.com%2Ffeder-cr%2Fjobs_applier_ai_agent_aihawk , https://github.com/OnlineGBC/Jobs_Applier_AI_Agent (search)
- Small job-apply agents (shape only, licences not checked): https://github.com/torontodeveloper/job-application-agent , https://awesome.ecosyste.ms/api/v1/projects/github.com%2Fabhinav-reddy-k%2Fworkday-copilot (search)
- Ollama prefix reuse and keep_alive (third-party, unverified): https://leanpub.com/read/ollama/prompt-caching (search)
