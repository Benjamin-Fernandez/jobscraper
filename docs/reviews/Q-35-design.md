# Review: Q-35 stage-E design review, D-78 LLM-driven form filling (KA-1, KA-2)

- **Reviewer:** reviewer agent, 2026-11-03
- **Diff:** worktree `arch-Q-35`, `git diff e79745c..63c62b3` (branch `arch/Q-35-llm-fill`): 7 files, +1227/-6. Under review: `docs/architecture/llm_fill_design.md` (cited **LF**), `adr/0006-llm-driven-form-filling.md`, `llm_fill_build_plan.md` (**BP**), `src/jobscraper/apply/contracts.py` v5, `spikes/S-5_workday.md`, `spikes/S-5b_llm_workday.md`.
- **Checked against:** D-70, D-74–D-79 (`instructions/02_status.md` §4); `docs/prd.md` F-11–F-13, F-30–F-39, NF-01–NF-07; ADR-0003, ADR-0004, ADR-0005; `apply_design.md` (**AD**) §5.3, §7.5, §7.7, §17; `docs/reviews/Q-30.md` F1/F3/F4; `docs/reviews/M20-lane-B.md` F1/F9; `tests/test_layering.py`.
- **Evidence (worktree at 63c62b3, tester's uncommitted files present):** `python tests/run_tests.py -k layering` printed `10/10 passed`; `-k apply_contracts` printed `49/49 passed`. The added lines were grepped for employer names, owner names, e-mail addresses, SG phone numbers and Workday tenant hosts: no match.

## VERDICT: READY WITH FIXES (not READY for the work packages the fixes touch)

Seven HIGH findings. Each one is a text change to the guard, lock or page rules. None needs a new architecture. The shape is sound: deterministic navigation and Submit, facts written by the program, locks first, and a stop when a required field is unknown. But four routes let a wrong answer reach Submit, one breaks D-70, and one puts S values in the prompt.

- **Can start now:** T0, T1, T3, R1, R2, N1–N5. Their scope doesn't depend on the fixes.
- **Not READY until the architect folds H1–H7 (and M1, M5, M6) into LF and BP:** M1–M5, R3, N6, T2, T4, T5. Their oracles would encode the gaps.

### What holds (read, not run)
- **Submit once, outside the model.** The model never navigates or clicks. `next_step` never clicks a button labelled Submit (LF §9.1). Submit is `nav.submit()` once, after `submit_clicked_at` is committed. The ADR-0004 states are unchanged, and so are caps, duplicate and twin refusal, and the dry-run default (LF §8, ADR-0006 §6).
- **Fail closed.** G10 lists every required unknown, and a stopped page is not typed (except M9). Transport failures end as `model_unavailable` before anything is sent. A cut or malformed reply is retried once.
- **Locks are final.** A locked field isn't in the schema, so the model can't answer it. Private S facts are shown only as `set`/`empty`. `ref` is a schema enum, and fact values are written by `fact_value`.
- **Contracts v5 are additive.** `Answer` still builds with 6 positional arguments and the new fields have defaults. There are new enum members and new types. `contracts.py` imports are unchanged. No HTTP or SQL is planned in `apply/`, and `layering` is 10/10.
- **No CAPTCHA or bot-check evasion.** Skipping honeypots and clicking through the `click_filter` sibling is what a person's input does. Cookie banners are declined. No stealth flags.
- **No per-site value hardcoding (D-78).** Workday ids appear only as widget-dialect detection or navigation. O-1 (locks vs "the LLM fills") is correctly raised to the owner.
- **Q-30 F3 and F4** are resolved as that review proposed (LF §12.2, §12.3). **Spike reports** are anonymised.

### S-5b error kinds walked through the locks and G1–G10

| # | Error | Guards that apply | Closed? |
|---|---|---|---|
| 1 | Hierarchical "How did you hear" | L1 expansion, `pick_option`, G1, G2/G4 | Mostly. A fact-fallback choice gets no second opinion (H2c) |
| 2 | Title kept the employer's name | prompt rule 5 only | **Open** (H1a, M12) |
| 3 | Job location taken from the resume header | G6 checks where the *evidence* is, not the value | **Open** (H1) |
| 4 | Language level invented | G4, E2/E3/E6 | Closed for `resume`. **Open** through a cross-entry profile ref (H2a) |
| 5 | Projects section put into one role's description | E4 recheck, then G3/G6 | **Open** if the recheck keeps other blocks' lines or returns unknown (H1c) |
| 6 | Listbox read back as filled while empty | strict read-back, corrective pass, `validation_error` | Closed (M14 widens it) |
| — | Dates | section values, equivalence check | Closed |

## Findings

### H1 HIGH: grounding doesn't tie the value to its evidence or to its entry
LF §7 G3, G6, G8 (lines 251, 254, 256); §6.4 entry recheck (line 237); §16 G6/E4 oracles.

- **Why:**
  - G3 checks only that the evidence quote is in the corpus. It runs `resolve.grounded` on the value against the **whole** corpus (resume + profile + JD).
  - G6 checks only where the **evidence** lies.
  - Nothing requires the value to come from the evidence or from the entry's block.
  - `grounded` rule 4 allow-lists "Singapore" (AD §7.7).
- **Failure scenario (S-5b failure 3 again):** work entry #2 is a Kuala Lumpur job. For its Location field the model returns `source=resume`, value "Singapore", and evidence "Software Engineer Intern, Example Sdn Bhd" (inside entry #2's block). The guards don't stop it:
  - G3 passes: the evidence is in the corpus and "Singapore" is allow-listed.
  - G6 passes: the evidence is inside the block.
  - G5 doesn't apply to text.
  - Result: a wrong location is submitted.
  - The same path works for `keep` of a resume-import value (G8 → G3/G6).
- **Failure 5 is also open:**
  - If the recheck returns the role's lines plus the appended Projects lines, every token is in the resume corpus, so G3 passes.
  - If the recheck returns unknown, LF doesn't say what happens to the imported text. A `keep` with an in-block quote then passes G8.
- **Fix:**
  - (a) For TEXT values from `resume`/`job`/`keep`: every content token of the normalised value must be in the evidence. Dates and numbers already follow this rule.
  - (b) In an entry group, run `grounded` with the corpus set to that entry's block plus its entry facts, not the whole corpus.
  - (c) The recheck is a copy task: every returned line must occur (normalised) in the block. If the recheck returns unknown or is rejected, the imported TEXTAREA is unsupported (optional: clear it; required: unknown). Never keep it.
  - (d) Oracles: an in-block quote with a value from the resume header; a recheck reply with extra lines; a recheck that returns unknown.

### H2 HIGH: the model's choice of fact is trusted without a relevance check
LF §7 G2, G4, G5 (lines 250, 252, 253); §5.3; the answer-mapping table; §13.2 (one shared FACTS block).

- **Why:** for a fact ref, the program writes `fact_value(ref)`, and "the program's value wins" if the model disagreed. Nothing checks that this fact answers this question:
  - (a) **Other entries' facts.** G6 covers only `resume`/`keep`. A field in work entry #2 can cite `profile:experience[0].*`. `Fact.entry` exists but no guard reads it. Every chunk gets every entry's facts and the full ref enum.
  - (b) **Polarity.** A bool fact is mapped literally onto Yes/No, whatever the question's polarity.
  - (c) **No fit.** When `fact_value` has no fit, the model's own option is used if G4 passes. But Yes/No is exempt from G4, and G5 applies only to `resume`/`job`, so a Yes/No from a fact is never checked.
  - (d) **Audit.** These answers are recorded as tier PROFILE_RULE/MEMORY, confidence 0.95, with no model or prompt hash. The audit shows a model's choice as a deterministic rule (F-32 last bullet, F-39).
- **Failure scenarios:**
  1. "Are you able to work in Singapore without sponsorship?" misses the L4 row (or `exclude: [without]` moves it off the sponsorship row). The model cites `profile:singapore_status.requires_sponsorship` (false). `fit_bool` gives "No", and the program's "No" wins over the model's "Yes". The employer gets a false work-rights statement at confidence 0.95.
  2. A reworded "Are you a Singapore Citizen or PR?" misses the `yes_if` row. The model cites `standing:work_rights` and picks "Yes". There is no fit, so the model's option is used. Yes/No is exempt from G4 and there is no G5. An Employment Pass holder declares citizenship.
  3. A language entry "Malay" takes its level from `profile:languages[0].level` (English: Native). This is S-5b failure 4 again, through a fact.
- **Spec conflict:** this weakens ADR-0003 §3 ("choice answers need two agreeing runs"), which ADR-0006 lists as unchanged. The spec wins.
- **Fix:**
  - (a) **Entry scope for facts.** In a group that E2 matched to source entry X, a ref whose `Fact.entry` isn't X → unknown. An entry chunk's ref enum = that entry's refs + refs that belong to no entry.
  - (b) **Bool or enum fact on a choice.** Use the program's value only if a tier-2 row for that path matches the label (its synonyms and `exclude` decide polarity), or if the model's own option equals the program's value. A disagreement → unknown and captured, never "program wins". A private ref (the model sends `""`) needs either a matching tier-2 row or label tokens that overlap the fact's title; else unknown.
  - (c) **No-fit fallback.** Yes/No and required choices also need G5, or end unknown.
  - (d) **Audit.** Record `rule_id="fill:v1"`, `model` and `prompt_hash` on every fact answer the model chose. Give them a distinct tier or source marker and confidence ≤ 0.9.

### H3 HIGH: optional fields keep what the import or site put there when the model says unknown or a guard rejects
LF §7 G5, G8, G9 (lines 253, 256, 257); §8 step 8 (line 289); §3.3; F-39 / AD §7.8 ("the exact value sent").

- **Why:**
  - G8 clears only a **failed `keep`** on optional text.
  - A field whose decision is `unknown`, or that G2–G7 rejected, is never cleared. Step 8 fills or clears only FILLED and G8 rows.
  - Optional choices with an unsupported site value are deliberately left as they are (PREFILLED, 0.5).
  - G9 limits ticking a box, not keeping one the site pre-ticked.
  - G5 covers only required answers. An optional Yes/No from `resume`/`job` is checked only by G3, and any quote from the corpus passes it.
- **Failure scenario:**
  - The Workday parser fills an optional "Website", "Address Line 2" or "Middle Name" with header text or another entry's text. The model says unknown, so the value stays and is submitted.
  - The audit row says UNKNOWN with value "", but the employer received the parser's value.
  - A pre-ticked optional marketing opt-in stays ticked.
- **Fix:** for any field with a non-empty, untrusted shown value whose final status isn't FILLED or a guard-passed PREFILLED:
  - Optional text: clear it.
  - Optional choice: reset it to the placeholder when the widget allows. Otherwise record it with value = shown and a distinct status (e.g. PREFILLED, note "unverified"). In an entry, apply E6 (delete the entry).
  - Optional checkbox the site ticked: untick it unless a fact or lock backs it.
  - The audit value is what the page holds after read-back.
  - Also apply G5 to optional Yes/No answers from `resume`/`job` (1–2 s each), or leave those fields blank.

### H4 HIGH: S values still reach the prompt
LF §3.3 / §6.2 field view `current` (lines 116, 213); §5.2 RESUME fallback (line 166). This contradicts AD §5.3 and LF §15's "spike deviation closed", and LF §16's privacy oracle would fail.

- **Why:**
  - `current` is sent for every site-origin value. Only locked private fields are exempt.
  - The import and MyGreenhouse prefill phone, address lines, postal code, DOB and gender. Those fields aren't always locked: L5 depends on synonym rows, and phone has no lock at all.
  - LF §5.2: RESUME falls back to "the extracted file". `tailor_flow.master_text` excludes contact details (`tailor_flow.py:353-357`), but the fallback `resume_ingest.extract_text` keeps the header with the e-mail and phone.
- **Failure scenario:** the Workday import fills "Phone Number" and "Address Line 1" from the resume header. The field view carries `current: "<owner's number>"`. With `debug_dump: true` it is written to `data/apply/<id>/prompts/`. With a stale master cache, the whole contact header goes into RESUME.
- **Fix:**
  - Withhold `current` (send `current_set: true` only) when any of these holds:
    - the field kind is EMAIL or PHONE;
    - the label matches the G7 or L5 sensitive patterns, or a contact word (address, postal, phone, mobile, email, NRIC/ID);
    - the shown value contains any `applicant.redaction_values(profile)` item.
  - In the RESUME fallback, drop lines that contain redaction values, or require the master text.
  - T2 oracle: S values pre-filled on the fixture pages never appear in a recorded prompt.

### H5 HIGH: Q-30 F1 is closed for L6 but reopened through the model and MyGreenhouse
LF §5.1 `extra:` facts (line 159); §12.1 (lines 383-390); §7 G8; `docs/reviews/M20-lane-B.md` F9.

- **Why:**
  - The F1 guard limits only (a) L6 label matching and (b) which *generic-label* `extra` entries are listed.
  - A non-generic `extra` entry with a base value is a visible fact at every employer. The model may cite it for any field, including a generic follow-up or a question about one employer. G2 then writes it as a program value, with no grounding.
  - G8 also keeps MyGreenhouse free text without grounding. MyGreenhouse stores "saved answers to common questions" (lane B review F9, still open).
- **Failure scenario:**
  - The owner answered Shopee's "Why do you want to join Shopee?" (non-generic, base value).
  - At Grab, "Why do you want to join us?" → the model cites `extra:why_join_shopee` → Grab receives text that names Shopee.
  - The same happens when a relatives-details entry is cited for Grab's "If yes, please specify".
- **Fix:**
  - (a) A field with a generic label (`plan.is_generic`) may cite only `extra` entries scoped to this employer (the same rule as L6).
  - (b) An `extra` or MyGreenhouse text that names a company matching another employer (the entry's sightings' employers, the watchlist) and not this one is not listed and not kept. The field becomes unknown and is captured.
  - (c) G8: MyGreenhouse TEXTAREA and cover-letter values need G3 like any import.
  - Oracles for both scenarios.

### H6 HIGH: L1 keeps an attached resume when its file name equals ours (a regression of lane B review F1)
LF §4 L1 (line 126); §10 E1; §1 "holds by construction, and is still checked".

- **Why:**
  - F-23 gives every tailored file the name `<First>_<Last>_Resume.*`. So MyGreenhouse's stored resume, or a Workday candidate profile's resume from an earlier application, usually has our file name.
  - Equal names is exactly the shortcut lane B review F1 blocked.
  - L1 also matches FILE inputs by **page text** (`resume|cv|autofill`). On a step with both a resume input and a cover-letter input, the cover-letter input matches too.
- **Failure scenario:** MyGreenhouse autofill attaches an earlier job's tailored resume (same name). L1 keeps it, so the employer receives another job's resume while the audit records ours. D-70 is broken.
- **Fix:**
  - Replace any attachment this attempt didn't upload. Track our upload across steps (origin OURS) together with its SHA-256, and keep a file only when this attempt uploaded it.
  - Match by page text only when the step has exactly one FILE input.
  - A FILE input labelled cover letter, transcript or anything else never gets the resume.

### H7 HIGH: fields revealed by our own fills aren't read before a Submit page, and nothing checks deterministically before the click
LF §8 steps 1 and 8 (lines 279, 289); §9.2 Greenhouse `next_step → is_review=True` (line 328); ADR-0003 §4; F-30/F-38.

- **Why:**
  - `fill_page` reads the page once (step 1). Step 8 reads back only the fields found in step 1.
  - On Workday, a required follow-up revealed by our answer shows up as a site error after Next, and the retry covers it.
  - On Greenhouse, `next_step` returns `is_review` without clicking. The first time the site validates the form is the Submit click itself.
- **Failure scenario:**
  - Ticking "Yes" reveals a required "Please give details" field, which is never read.
  - Submit is clicked and the site refuses the form.
  - The attempt ends `submitted_unconfirmed` (ADR-0004), and F-30 then refuses that posting for good. An optional revealed follow-up is sent empty.
- **Fix:**
  - After step 8, re-read the scope. If new fields appeared, run one more lock/ask/guard/fill round (at most 2).
  - Before `nav.submit()`, and before `next_step` on every page, run a deterministic scan: if any visible required control is empty or shows an error, stop with `validation_error` before the click.
  - Oracle: a stub page where "Yes" reveals a required textarea.

### M1 MEDIUM: the order of the locks is not specified; two F-13 retry loops
LF §4 (lines 122-132); §12.1 line 386.

- **The order.** F-32 orders field map → profile rules → memory → declarations, but the LF table lists L3 before L6 and says a lock is final. If an L3 `AMBIGUOUS` or an L7 unknown wins over L6:
  - An `attestation_unclear` question is captured.
  - The owner answers it.
  - On retry the lock still stops, and the question is captured again.
- **Context-less generic labels.** A generic label with no help text and no context is "unmatchable". The owner's answer is never used, even at the same employer, so the same loop happens.
- **Fix:**
  - State the order: L1, L2, L4/L5, L6, L3/L7.
  - An UNKNOWN lock falls through to L6 for the same qualified label, never to the model.
  - Match context-less generic labels by employer + step + position (or job id).

### M2 MEDIUM: G7's sensitive pattern leaves out S-path topics
LF line 255.

- **Missing:** citizenship / citizen, permanent resident / PR, residency or resident status, nationality, national service / NS, ORD. Residency and NS are S paths in AD §5.3, so `resume`/`job`/`keep` can answer these questions today.
- **Fix:** add them to the pattern.

### M3 MEDIUM: value origins are too coarse
LF §3.3 (line 114).

- **Why:** after the MyGreenhouse autofill, every non-empty value on the first read, including the form's own defaults, is labelled `mygreenhouse`, and G8 trusts it.
- **Fix:** take a snapshot in `choose_entry` before the import. A value that was already there gets `site_default`.

### M4 MEDIUM: the decision cache misses its own use case and stores S values
LF §13.3 (line 420), §14.

- **Why:**
  - `facts_hash` covers the whole profile file. Answering a question writes `extra` into `applicant.yaml`, so the hash changes. "A retry after the owner answers" therefore never hits the cache.
  - `decision_json` stores `Answer` values, including values from private facts.
- **Fix:**
  - Store each decision's cited fact refs and hash only those facts.
  - Re-run the locks and G2 at replay.
  - Cache the decision (source/ref/evidence) and recompute the value.

### M5 MEDIUM: O-2 is load-bearing but nobody owns it
LF §5.2, §15 (line 469).

- **Why:**
  - `ResolveContext.resume_entries` isn't in v5, and the fallback heuristic "WP-F3" doesn't exist in BP.
  - With empty profile `experience[]`/`education[]`, E2 has no sources, so E3 deletes every imported entry, and G6 has no block to check against.
- **Fix:**
  - Add the field to v5 now (it's additive) and assign the `tailor_flow` helper and the N6 fill.
  - State that G6 rejects when there is no block (fail closed).

### M6 MEDIUM: the interface between lanes M and R isn't pinned, and `fill_page` doesn't classify
BP WP-M4, WP-R3; LF §8, §11.

- **Unpinned signatures:**
  - `ask(backend, chunk, …)`;
  - `pick_option`, `recheck_entry`, `second_opinion`;
  - `match_entries`;
  - the `services` dict.
- **No classify call.** AD §8.4 requires "classify before each fill", and model calls can take minutes between reading the page and typing. `services` has no `classify`.
- **Fix:**
  - Pin the signatures in a Protocol in contracts v5, or in a table in LF §8.
  - Add `classify` to `services`, called before step 8 and before the corrective pass.
  - Add `PageOutcome.transport_failed` instead of parsing `transport:` notes.

### M7 MEDIUM: two Workday pages get the same step id
LF §9.1 `step_id` (line 317) with the line 295 loop guard.

- **Why:** once the "step N of M" prefix is stripped, tenant A's two "Application Questions" pages get the same id. The loop guard ("same step id twice") then ends the attempt as `page_unrecognised`.
- **Fix:** keep N in the id, or compare field signatures as well.

### M8 MEDIUM: the Enter key
`apply/browser.py` line 9 ("never press Enter" rule) vs. LF §3.2 prompt "search on Enter".

- **Why:** pressing Enter in an input inside a `<form>` can submit the form implicitly. That submission would bypass `submit_clicked_at` (NF-06).
- **Fix:**
  - Scope the exception to the Workday prompt search box.
  - Never send Enter in an input inside a `<form>` that has a submit control.
  - Add an oracle.

### M9 MEDIUM: entries are changed before anything is resolved
LF §8 step 2 vs. step 7 ("nothing on this page is typed") and the T4 "nothing typed on a stopped page" oracle.

- **Why:** step 2 deletes and adds entries before the locks and guards run.
- **Fix:** move E3/E5 after `decide`, or amend the rule and the oracle.

### M10 MEDIUM: gaps in the plan mapping
BP §0, §7 (line 242).

- **Gate count.** BP §7 asks for 2 Greenhouse dry runs. The PRD M20 gate and ADR-0003 §7 say 5. The spec wins unless a D-row changes it.
- **Unmapped WPs:**
  - WP-I1 (gate run);
  - WP-L1, L2, F2 (M21: navigators only, LF §9.3);
  - WP-W8 (the audit view gains evidence/shown/origin).
- **WP-N6 is large** (loop, capture, review check, cache, warm-up). Consider splitting it into N6a and N6b.

### M11 MEDIUM: the NF-07 deviation is acceptable, with conditions
LF §13.1, §15.

- **Why acceptable:**
  - NF-07 is P1.
  - The owner's D-78 goal outranks it.
  - NF-07 literally covers attempts with no account, which first-time Workday attempts aren't.
- **Conditions:**
  - The Coordinator records a D-row.
  - Greenhouse stays ≤ 4 min, and both ATSs are measured at the gate.
  - The 900 s deadline either excludes the IMAP wait (up to 5 min, F-36) or budgets for it.
  - The deadline is checked between chunks, so a timeout mid-page stops before typing.

### M12 MEDIUM: S-5b failure 2 has only a prompt rule
LF §6.2 rule 5; §16 "Title rule".

- **Why:** H1(a) catches part of it. Nothing else stops a title that still contains the employer's name.
- **Fix:** a TEXT value in an entry must not contain the matched entry's employer unless the block's title does. Otherwise recheck it as in E4.

### M13 MEDIUM: D-77 needs reading against D-78
BP §7 step 3.

- **Why:** D-77 allows real submissions "only when every required answer comes from the profile/resolver". Under D-78, a required answer may be resume or job text, or a kept import value.
- **Fix:** make the gate explicit:
  - The Coordinator reads the dry-run audit (`apply show`) row by row before each automatic run.
  - A required `resume_import` value is never kept without G3 passing.

### M14 MEDIUM: strict read-back is defined for listboxes only
LF §3.2.

- **Why:** a typeahead or combobox can select its first suggestion instead of the intended option.
- **Fix:**
  - Every widget family must read back equal (normalised) to the intended value, else `fill_failed`.
  - A search miss on an optional field clears the typed text.

## Requests
- **Architect:** amend LF §3.3, §4, §6.2, §7, §8, §10, §12.1, §13.3 and §15, and BP §0/§7, for H1–H7 and M1–M14. Contracts v5: add `ResolveContext.resume_entries`, a fill-services Protocol, and optionally `PageOutcome.transport_failed`. Re-mark the affected WPs READY afterwards.
- **Tester:** keep writing T0, T1 and T3. Hold the G2/G3/G6/G8/L1 oracles in T2/T4 until the amendment lands. Add the oracles named in H1–H7.
- **Coordinator:**
  - D-row for NF-07 (M11).
  - Gate count, 5 vs 2 (M10).
  - D-77 reading (M13).
  - O-1 goes to the owner as the architect asked.
