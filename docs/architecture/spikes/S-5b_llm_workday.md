# Spike S-5b: LLM-driven generic form filling on Workday (Q-23b, D-78, 2026-11-02/03)

**Author:** software-engineer (spike), report written by the architect (Q-35) from the spike's findings and the structure of its local recordings. Prototype: `spikes/llm_fill/{llmfill,drive,recheck,keeper}.py` (merged, not production code).
**Public repo:** tenants are **tenant A (wd1)** and **tenant B (wd5)** (tenant B is S-5's tenant B). No employer name, requisition id, site name, outcome tied to the owner, or personal value appears here. The recordings (pages, field reads, prompts, answers) hold personal data and stay in the session scratchpad; they are never committed (fixtures are rebuilt from them with synthetic values, `llm_fill_design.md` §16).

## Setup

- Headed Edge (`msedge`) kept open by `keeper.py` (Playwright defaults + a remote-debugging port so step scripts attach); throwaway browser profile per tenant.
- One command per step (`drive.py`): `account`, `signin`, `verify`, `page` (read → model → guard → fill → record), `next`, `submit` (review page only, all guards held, once).
- Model: Ollama `qwen3:14b`, temperature 0, JSON schema output, `num_ctx` 32768, thinking off.
- Owner go-ahead for real accounts and automatic submission at the two tenants: D-77.

## What the prototype does

1. **Generic reader** (`READER_JS`): every visible, enabled control → `{id, kind, label, section, required, automation_id, html_id, current, options, parts, multi}`; options behind listbox buttons and prompts are opened, read and closed with Escape; honeypots and password inputs are skipped.
2. **One model call per page**: system rules + JOB + standing facts + today's date + the profile (sensitive keys redacted to `<SENSITIVE:key>`) + the resume text + the fields; the schema has one object per field (`value`, `source`, `profile_key`, `evidence`), choice values as enums.
3. **Guards**: required + unknown → stop; free text must be grounded in the sources (token overlap); sensitive fields only from the profile, mapped to an option by the program (the model never saw the value); a prefilled optional text nothing supports is cleared.
4. **Generic fill** with `apply/browser.py` primitives plus prompt/date glue; file inputs never reach the model (a resume slot gets the resume).

## Results

| | Tenant A (wd1) | Tenant B (wd5) |
|---|---|---|
| Entry | "Autofill with Resume" (D-78) | "Autofill with Resume" |
| Account | created; password stored in Credential Manager **before** the click | created the same way |
| Email verification | not asked | not asked |
| CAPTCHA / bot check | none | none |
| Steps | 7: Autofill with Resume, My Information, My Experience, Application Questions (2 pages), Voluntary Disclosures, Review | 6 (stopped at step 2) |
| Outcome | **submitted once**; the site's confirmation page and candidate home both showed it | **stopped by the guard** at My Information: a REQUIRED "Additional Address" field the profile had no value for (the model said unknown twice). Correct fail-closed; nothing submitted |

"Autofill with Resume" is wizard step 1: one file input; the generic reader found it and the resume was uploaded; the import then prefilled names, phone, work entries, education, languages and websites.

## Model accuracy and latency

About 83 final answers at tenant A; **9 wrong on the first pass, all caught before Submit**, some only by the agent's manual review (not by an automatic guard):

| # | Error | Fix found in the spike | Design answer (`llm_fill_design.md`) |
|---|---|---|---|
| 1 | Hierarchical "How did you hear" list: the model saw only the top-level categories and picked a wrong leaf | the reader expands chevron categories one level ("Category > Leaf"); lists > 15 get a free-text answer + a one-field pick call | §3.1 LL1, §6.4 LL2 `pick_option` |
| 2 | A job title kept the company name the parser put in it | prompt rule "only the part that belongs in each field" | §6.2 rule 5 |
| 3 | Every job's location taken from the resume header (the applicant's home) | prompt rule about per-entry facts; value cleared by hand | §6.2 rule 6, guard G6 (entry scope) |
| 4 | A language proficiency invented for a language the profile does not list (the enum allowed any level) | entry deleted by hand | guard G4 (choice vs source), rule E6 (delete an ungroundable optional entry) |
| 5 | Workday's parser put a whole projects section into one role description; the model kept it | one-field per-entry recheck (`recheck.py`) returned only that role's lines | §6.4 entry recheck, rule E4 |
| 6 | A listbox read back as filled but Workday held no value (error shown after Next) | read the field's error, one corrective pass | §3.2 strict listbox read-back, §8 step 8 |
| — | Dates: a prefilled "3/2026" vs the model's "2026-03" treated as different; the reader first returned the date placeholder as the value | date equivalence check; read section values, not `aria-valuetext` | §3.1, §3.2 |
| — | Skills: one of two searched skills found no option (optional) | — | §6.4 LL3: an optional search miss clears the typed text |

The "Are you a Singapore Citizen?" question was answered from the profile's (non-sensitive) nationality, because residency status was redacted. The design does not send nationality to the model and answers this with the deterministic `yes_if` lock instead (`llm_fill_design.md` §4 L5, §15); G7 now also keeps citizenship/residency labels off resume and job text.

Gender was filled by the program from the profile through the sensitive path (the model returned only the key). Declarations were answered from standing facts written into the prompt; the design instead locks them deterministically (tier 4) and shows them to the model only as private facts.

**Latency** (warm unless noted; input ~5k tokens, mostly profile + resume):

| Page | Fields | Seconds | Output tokens |
|---|---|---|---|
| Autofill with Resume | 1 | 1.3 | 38 |
| My Information (tenant A, 4 passes) | 13 | 8.4–9.1 | 612–676 |
| My Information (tenant B, first call, cold) | 15 | 32.9 | 723 |
| My Information (tenant B, re-ask) | 15 | 9.9 | 698 |
| My Experience (2 passes) | 47–54 | 47.5–53.8 | 3371–3779 |
| Application Questions 1 | 6 | 4.4–5.0 | ~310 |
| Application Questions 2 | 1 | 1.6 | 59 |
| Voluntary Disclosures | 2 | 2.0 | 96 |
| Per-entry recheck | 1 | 1.9 | — |

## Generic vs Workday-specific

- **Generic, unchanged across the two tenants:** the page reader (labels via `label[for]` / `aria-labelledby` / container / `legend`, required flags, current values, listbox options, prompt categories, radio groups, checkboxes, honeypot skip), the model call, the guards, text/listbox/radio/checkbox/date/file fill, the sensitive path, the required-unknown stop, the corrective pass on site errors.
- **Workday-specific (navigation and widget dialects):** Apply button and entry dialog ids; account form ids and the `click_filter` sibling click; Next/Submit = `bottom-navigation-next-button`; prompt pills (`selectedItem`, `DELETE_charm`), `promptOption` and chevron categories; segmented date sections (focus fallback when a display div covers the input); upload confirmed by file name (`input.files` is emptied); a Delete button per repeatable entry; the "step N of M" title prefix; the cookie banner; the post-submit URL `/jobTasks/completed/application`.

## Recommendations (all taken up in `llm_fill_design.md`)

1. Show the model only the **site's** prefill as "current"; our own earlier values bias it (§3.3).
2. Remove an imported optional entry whose required sub-answers can't be grounded instead of guessing (§10 E6).
3. Check choice answers against their source, not only against the option list (G4).
4. Always recheck parser-prefilled descriptions per entry (§6.4, E4).
5. Add today's date to the standing facts (§5.1 `standing:today`).
6. Two-step match for long lists (§6.4 `pick_option`).
7. Strict listbox read-back (§3.2).
8. Sensitive values filled by the program from `applicant.yaml` without the model seeing them (§5, G2, G7).

## Q-41 result: tenant B (wd5) finished, 2026-11-02

**Outcome: submitted, confirmed.** Two phases (D-83): the S-5b tooling filled every step up to Review and stopped; the Coordinator read the answers row by row and replied "submit"; Submit was clicked once. Post-submit page `/jobTasks/completed/application` (Candidate Home); My Applications lists the posting with status **Applied** and the date submitted. No CAPTCHA or bot check on any page. The current resume (new parse) replaced the earlier draft: the tailored PDF (deterministic tailor, coverage 63% → 68%; 10 bullets trimmed, still 2 pages) was uploaded through "Autofill with Resume", the old upload and the old work entries were gone, and the new parse prefilled 3 work entries. One optional question (restrictive agreements) was left blank because its fill did not save; the Coordinator kept it blank.

- **Step-3 Location stop.** At this tenant every work entry has a *required* Location. Neither the resume nor the profile had one, and the model filled the applicant's home city from `contact.city` (the rule-8 mistake again). The guard did not catch it (the token is in the corpus); the agent cleared it and stopped. The owner answered; the value now comes from the profile's `experience[i].location`. Design point: a sub-field of one entry (location, level) must be grounded in that entry, not anywhere in the corpus (G4 per entry).
- **Skill matcher picks.** Typing ~50 profile skills into the Workday skills prompt and matching each with `pick_option` produced 3 wrong picks (a web framework matched to an unrelated ML library, another ML library with no source, a database matched to a different database) plus one duplicate entry for HTML. A token-grounding check of every chosen pill against resume + profile found exactly those 3; the duplicate was removed on the owner's word. Design point: verify each pill after the pick, and allow "" (no match) when the closest option is a different product.
- **"Government work" basis mismatch.** The answer "No" was right, but the model's evidence quoted the wrong standing fact ("never worked for this employer"). The real basis is the profile work history (all private employers) and the question's own exclusion of mandatory military service. Design point: check that the cited fact is about the question (G4 basis check), not only that the quote exists.
- **Also seen:** after Save and Continue, Workday disables the Next button while it saves; the next click must wait until it is enabled again. A disability question was answered from the profile's US self-ID value on a Singapore form (program-filled, never shown to the model).
