# Q-35 lane M code review (KA-2: locks, facts, guards, model call)

- **Branch:** `eng/Q-35-M-llmfill` @ a4f1c8c, `git diff personal...HEAD`. Files: `apply/facts.py`, `locks.py`, `guards.py`, `llm_fill.py`, `resolve.py` (F1/F4), `plan.py`, `questions.py` (`capture_page`), `backends.py` (keep_alive / warm).
- **Checked against:**
  - `llm_fill_design.md`: §4 L1–L7, §5, §6 (incl. §6.5), §7 G1–G12, §11, §12, §13.3.
  - `docs/reviews/Q-35-design.md` (review and re-check), D-84 R1–R4, ADR-0003, AD §5.3.
- **Reviewer:** Reviewer agent, 2026-11-03.

## Verdict: APPROVE WITH FIXES

The core is sound:
- A lock is final.
- The model never writes a fact value; the program does, through `fact_value` → `resolve.fit_*`.
- Every prompt is redacted as a whole.
- A transport failure, a cut reply or a malformed reply always raises `BackendError`, never a guess.
- Layering holds.

Three HIGH findings must be fixed and pinned before merge; each is a few lines:
- F1: an S value reaches the `pick` prompt.
- F2: D-84 R4 is bypassed through the resume.
- F3: G7 is blind to a generic label's context.

The rest are MEDIUM: false positives that fail closed, privacy hardening, and plan gaps.

## Evidence

- `python tests/run_tests.py -k layering`: `test_layering 10/10`, `10/10 passed`.
- `python tests/run_tests.py` on the branch: `813/813 passed` (there are no lane-M oracle files yet, so this shows no regressions, not coverage of lane M).
- Scratch probes (fake backend; synthetic profile; run from `docs/reviews/.probe_M*.py`, deleted, not committed). Output, quoted:
  - `P1 account email in s_values() without arg: False`
  - `P1 DOB form '05 Mar 2001' redacted: False`, `'March 5 2001'`: False, `'2001/03/05'`: False (`'5 March 2001'`, `'05/03/2001'`: True)
  - `P2 emergency contact name from resume: filled 'Testa Personne'`
  - `P3 sensitive_label('Please specify' | ctx Race): False`, then `P3 'Please specify' (ctx Race) from resume: filled 'Chinese'`
  - `P4 pick for 'Race' sent the S enum value: True -> Chinese (Han)`
  - `P5 cut x3 -> BackendError: model reply cut by the output cap | calls: 2`
  - `P5 malformed x2 -> BackendError: model reply is not a JSON object | calls: 2`
  - `P5 partial reply -> [('a', 'resume')]` (the missing id gets no decision, so `decide` notes it "model: no reply")
  - `P6 L2 on 'Email' with help mentioning reference: None`
  - `L2 with 'hiring manager' help: None`
  - `'have you ever been convicted of a criminal offence yes no' -> ('unknown', 'L7: negated declaration')`; the same label without "(Yes/No)" → `filled`.

## Findings

### F1 HIGH: an enum S value is sent to the model in the `pick` prompt
`llm_fill.py:539-558`; the prompt line is `f"WANTED: {wanted}"` at :549.

- **Why:** §6.5 leaves enum S values (gender, race, nationality, residency, NS, marital status) out of `s_values` because "the model never receives them as fact values". `pick_option` breaks that premise. When a locked or private answer doesn't equal an option exactly, the widget calls `pick`, and `pick` sends the S value to the model. `redact` can't help, because the value is not in `s_values`. This happens with:
  - an L5 race or nationality lock on a searchable list (LL3);
  - a list whose wording differs ("Chinese" vs "Chinese (Han)").
- **Scenario:** in probe P4, `pick_option(field "Race", wanted="Chinese", ...)` sends `WANTED: Chinese` to the model. The widgets on `int/Q-35-NR` call `pick` for any value with no exact option. `pagefill` is still being built against fakes, so nothing stops it today.
- **Fix:**
  - (a) In lane M, `pick_option` returns `None` without a call when `guards.sensitive_label(field)`. It also takes `sensitive: bool` and returns `None` when it is True.
  - (b) WP-R3 passes `pick=None` (or `sensitive=answer.sensitive`) for every `Answer.sensitive` row.
  - With no pick, LL3 already gives the right result: required → unknown, optional → cleared.
  - Pin: no recorded prompt contains a sensitive answer's value (extend the TR-1 deny list with the profile's enum S values).

### F2 HIGH: D-84 R4 is bypassed through the resume: the applicant's own name fills a question about another person
`guards.py:606-638` (`_model_field`), `guards.py:647-693` (`_keep_field`). R4 is only built into `facts.relevant` (`facts.py:534`) and L2 (`locks.py:139`).

- **Why:** R4 says the applicant's own contact and identity details never answer a field about another person. Only the fact route is closed. A `resume` decision whose value is the applicant's name (or city) passes:
  - G3: the name line is in the resume;
  - the copy rule;
  - G5, which doesn't apply to text.
- **Scenario:** in probe P2, required "Emergency contact name": the model gives `source=resume`, value and evidence "Testa Personne", and the field is `filled 'Testa Personne'`. The same holds for "Referee name" and "Next of kin". A wrong answer is submitted on a required field. Phone, email and address are safe, because they are redacted from RESUME and the "[private]" check rejects them.
- **Fix:** in `_model_field` and `_keep_field`, when `F.about_other_person(pf)` and the value contains the applicant's name tokens, return unknown with the note "R4: applicant's own detail". The name tokens are `standing:full_name` or `identity.*` (and `contact.city` for a location field). This is captured and goes to the Questions inbox, as R4 intends.
- **Pin:** P2 must end UNKNOWN.
- This is a design gap: R4's text names only relevance. The architect should widen R4 to "any source" when folding D-84 in.

### F3 HIGH: G7 doesn't see a generic label's context, so a sensitive follow-up is answered from the resume
`guards.py:151-153`: `sensitive_label` reads `label + description` only. `llm_fill.py:157` (`_withhold`) uses the same check.

- **Why:** a generic follow-up ("Please specify", "If other, please state") belongs to its CONTEXT question (§12.1, SYSTEM rule 7). When that question is Race, Religion, Gender or Nationality, the field is an S field. G7 must allow only a lock or a private profile fact. As built:
  - the field takes a `resume` value;
  - L5 doesn't lock it, because its label has no row;
  - `current` (for example a MyGreenhouse prefill) is shown to the model.
- **Scenario:** in probe P3, "Please specify" with context "Race": the model gives `resume`, "Chinese", evidence "Languages: Chinese", and the field is `filled 'Chinese'`. An S answer comes from a model guess. This happens when the applicant's race is "Others" and the site reveals the follow-up.
- **Fix:** `sensitive_label` also reads `pf.context` (and `group_title`) when `is_generic(norm_label(label))`. `_withhold` then follows automatically.
- **Pin:** P3 must end UNKNOWN with "G7".

### F4 MEDIUM: `s_values` takes the account email as optional, and some date forms are missed
`facts.py:811` (`account_email: str = ""`), `facts.py:795-808` (`_date_forms`).

- **Why:** under D-72 the account mailbox differs from `contact.email`. With the default, a caller that forgets the account email (WP-R3 / N6a; no caller exists yet) silently stops redacting it (probe P1). Exposure is low, because EMAIL fields and email labels already get `current_set`, but the redaction backstop goes.
- Also not redacted: DOB as "05 Mar 2001", "March 5 2001" and "2001/03/05". Singapore resumes sometimes print the DOB. These forms are beyond §6.5's list, and adding them is cheap.
- **Fix:**
  - Make `account_email` required (no default), and pin that `pagefill` passes `ctx.account_email`.
  - Add `{d} {Mon} {y}`, `{Month} {d} {y}` and `{y}/{mo}/{d}` to `_date_forms`.

### F5 MEDIUM: `about_other_person` reads help text, so the applicant's own email or phone is refused (fails closed)
`facts.py:110-112` (OTHER_PERSON includes `manager`, `partner`, `parent`, `reference`), `facts.py:505-511` (label + description + section + group_title + context).

- **Scenario:** required "Email address" with help "The hiring manager will contact you here":
  1. L2 is skipped (probe: `None`);
  2. the model's `standing:account_email` fails G2b because of R4;
  3. the field ends UNKNOWN, so the page stops and the question is captured.
- "for reference checks" and "partner companies" in help texts do the same. No wrong value is written, but fill rate suffers.
- **Fix:** match OTHER_PERSON on the label, `group_title` and section. Use the help text or context only when the label is generic.

### F6 MEDIUM: L7 treats a "(Yes/No)" suffix as a negation
`locks.py:211-213`; NEGATIONS contains `("no",)`.

- **Scenario:** "Have you ever been convicted of a criminal offence? (Yes/No)" normalises to `... offence yes no`, which gives `L7: negated declaration` and `attestation_unclear`. The same label without the suffix is filled. This fails closed, but every such form adds to the inbox.
- **Fix:** before `_negated`, strip a trailing `yes no` / `yes or no` / `y n`.

### F7 MEDIUM: G2(e) and G4 accept the model's own unverified evidence for a fact-cited option
`guards.py:544`: `g4_ok(opt, (d.evidence or "") + " " + fact.value)`.

- **Why:** the design (G4: "with the evidence or the fact's text") allows it. But on the fact route the evidence is never checked against any corpus, so the model can justify any option by naming it in its evidence. Required choices and Yes/No still get G5; an optional non-Yes/No choice is written at confidence 0.8 with no check.
- **Fix:** on the fact route, run G4 against `fact.value` only, or require the evidence in `facts_corpus`. The spec allows the current code; this is noted as a disagreement for the architect.

### F8 MEDIUM: `field_sig` hashes the shown value unkeyed
`facts.py:866-873`.

- Per §13.3, `field_sig` is the plain sha256[:16] of the shown value among the other parts. For a site-prefilled phone (10^8 values), postal code or DOB, the stored `fill_cache` key can be brute-forced back in seconds. `facts_used_hash` is already keyed with the S values (`:901`), which is good.
- **Fix:** use the same HMAC key for `field_sig`, or hash the marker `current_set` instead of the value for withheld fields (§6.5).
- The spec allows the current code. The DB is local and the profile sits next to it, so this is hardening, not a blocker.

### F9 MEDIUM (plan gap): L1b cover-letter compose has no owner
`locks.py:121-126`.

- LF §4 L1b says a required cover-letter FILE is composed (one call, G3 compose, G12) and uploaded. Lane M returns unknown with the note "L1b: cover letter not composed".
- FILE is in `NOT_CAPTURED_TYPES` (`questions.py:72`). So a Greenhouse posting with a required cover letter always stops with nothing in the Questions inbox.
- This fails closed, but the owner can't see why.
- **Fix (Coordinator):** assign a WP for L1b. Until then, give pagefill a distinct stop note or reason so the owner sees "required cover letter".

## Lane M open questions: defect or design gap

| # | Question | Ruling |
|---|---|---|
| 1 | L1b compose with no WP owner | **Plan gap** (F9). Not lane M's defect; the Coordinator assigns it |
| 2 | `links.*` facts allowed outside entry chunks (`guards.py:316`) | **Design gap, keep the code.** §7 G2(a) says "refs with no entry", but Greenhouse shows LinkedIn and GitHub as plain fields; the strict reading would never fill them. Links are LLM_ALLOW (visible). The architect folds it into G2(a) |
| 3 | One-word labels are generic | **As designed** (§12.1: "fewer than 2 content tokens"). Cost: a one-word question with no profile row ("Pronouns", "Hobbies") is captured per employer, step and position, and its answer is reused only there. Profile and standing facts still answer one-word labels (`allowed_refs` filters only `extra:`). The architect may relax this for non-sensitive one-word labels |
| 4 | `profile_gap` lost without a tier-2 row | **Design gap** (§5.1 hides empty non-private facts, so G2(c) never fires). `_rule_gap` recovers it when a unique row exists; otherwise the answer goes to `extra`, not the profile. Acceptable for M20 |
| 5 | G12 rejects captured as `no_rule` | **As designed** (§11: "any other guard no_rule"); the note keeps "G12: …". No defect |

## Focus walk

**1. S values and the account email**
- Every user prompt is redacted as a whole: `llm_fill.py:370` (main and second), `:547` (pick) and `:571` (recheck). Schemas are redacted too (`:322`, `:554`).
- FACTS shows private facts as "private, set|empty" only (`facts.py:392`).
- `current` is withheld for EMAIL/PHONE kinds, G7 labels, contact words and S matches.
- A locked answer is shown only when FILLED, not sensitive and ≤ 100 chars. L2, L5, EEO and private-fact rows are `sensitive=True`.
- FILE fields never enter a chunk, so the resume path is never in a prompt.
- CallLog keeps hashes only. Lane M modules don't log. Notes carry guard tags and rule keys, never values.
- `Answer.evidence` comes from the redacted prompt.
- Open gaps: F1, F3 (`current` for a sensitive generic field), F4 and F8.

**2. Model vs locks and fact values**
- `decide` copies the lock (`guards.py:774`) and never reads a decision for a locked key.
- Locked keys are left out of the schema (`_open`).
- Fact values come only from `fact_value`. The model's value is compared and never written (`:513-536`).
- The model's own option is used only on the G2(e) route (non-private, choice, G1 + G4 + G5); see F7.
- Private facts without a matching rule end unknown (G2d).
- Ruling: closed, apart from F7.

**3. The six S-5b error kinds through the code**

| # | Error | Code path | Result |
|---|---|---|---|
| 1 | Hierarchical how-heard | `standing:how_heard` → `field_map_fit`; no fit → G2(e): `option_for` leaf match + G4 + G5 (required) | Closed (F7 caveat) |
| 2 | Title keeps the employer | `g11_fails` in `_model_field` and `_keep_field`; `recheck_targets` adds failing titles | Closed |
| 3 | Job location from the header | entry corpus = block + entry facts; copy rule ties the value to the in-block quote | Closed |
| 4 | Invented language level | unmatched group → `allowed_refs` = [] and E3; G4 with LEVEL_SYNONYMS | Closed |
| 5 | Projects in a role description | `recheck_entry` keeps only lines in the block; `_grounded` re-checks `lines_in_block` for `via=recheck`; without a recheck the copy rule against a ≤ 240-char quote still blocks it | Closed |
| 6 | Listbox read back while empty | lane R (strict read-back) | n/a here |

**H1–H7 through the code**
- H1: copy rule, G6 corpus and G4 for choices. Closed.
- H2: G2(a)–(e). Closed (F7).
- H3: `_leftovers` clears, resets, unticks, or flags unverified. Closed.
- H4: see focus 1. Gaps F1, F3 and F4.
- H5:
  - generic labels cite only `extra` entries scoped to this employer;
  - L6 matches a generic label only on its qualified label and through `by_employer`;
  - a MyGreenhouse keep is checked against G12.
  - Closed.
- H6: L1 keeps an attachment only if it was uploaded in this attempt (`locks.py:107`). Closed.
- H7: lane R (`scan_required` and revealed rounds); not in lane M.

**4. D-84 R1–R4**
- R1: `other_employers(composed=True)` drops profile experience and education names and the resume entries (`facts.py:262-276`), and is used only by the compose rule (`guards.py:598`). Built.
- R2: G2(d) agreement on a Yes/No runs `_second_agrees` (`guards.py:527-532`). `_decision_value` treats "same fact, other option" as a disagreement. Built.
- R3: `recheck_targets` takes every TEXTAREA of a matched entry whose answer isn't a fact, whatever its origin (`guards.py:362-386`). A program-added entry is covered once it is matched on the next read. `decide` doesn't require that the recheck ran, but G3/G6 still hold without it. Built.
- R4: `relevant` (`facts.py:534`) and L2 (`locks.py:139`). Built for facts; F2 (resume route) and F5 (false positives) remain.

**5. Transport**
- `_call` turns a timeout into `BackendError`.
- A cut reply is split once; a single field is retried once; then `BackendError` (P5).
- A malformed reply is retried once, then `BackendError` (P5).
- `_one_shot` (pick and recheck) gets one retry, then `BackendError`.
- `second` raises out of `decide`, so `pagefill` must map that to `transport_failed`.
- A pick choice that isn't an option gives `None`.
- A missing id gets no decision; `decide` turns that into unknown ("model: no reply"), which is captured, never filled.
- `capture_page` skips transport notes.
- Ruling: closed. Pin for WP-R3: a `BackendError` raised inside `decide` (from `second`) ends `transport_failed`.

**7. Layering:** `test_layering 10/10`. `llm_fill` reaches the model only through the injected backend, and imports only `BackendError` from `backends`. No SQL. `facts`, `locks` and `guards` are pure.

## Notes (no action needed for merge)
- `guards.py:533` also rejects a private fact when the model wrote any value. That is stricter than §7 G2(d) ("a non-private fact's model value must equal…"). It fails closed and costs only fill rate; consider ignoring `mv` for private facts.
- `relevant` matches on title words, so "Expected salary" is relevant to "Expected start date". Fit and kind checks usually stop it. A pin in T2 would help.
