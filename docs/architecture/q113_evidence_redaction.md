# Q-113 / D-202: redact the model's quote before it is stored

Fast-track delta, KA-2 (2026-11-12). Source: review `docs/reviews/Q-112-d201-profile-read.md` F1. Builds on D-105/D-201 (`q74_model_sees_sensitive.md`, ADR-0008, which is unchanged: the model reads, code decides). No contract change, no ADR. Storage only: no answer, guard or log line changes.

## 1. Problem (evidence)
- A rejected quote is kept on the Answer: `guards._answer_unknown(..., evidence=d.evidence)` (guards.py:440-448; called at 727, 731, 733, 737, 790, 792, 796). It is stored verbatim as `"evidence": a.evidence` (apply_flow.py:324).
- `_cache_put` stores `"evidence": d.evidence` for every cached decision (pagefill.py:745). That includes fact-cited decisions and rejected optional ones; only required unknowns and stop keys are dropped (pagefill.py:729-734).
- With the switch on, FACTS prints `ref | title | private: <value>` (facts.py:403). A quote copied from that line (the review's case is `pay.current_salary ... private: 4321 SGD ...`) ends up in both tables. This contradicts contracts.py:966, apply_flow.py:623 and D-105 hook (b).

## 2. Decision D-202
At the two write points, a quote is stored **verbatim only when the guards checked it and the field took a value**. Every other quote is stored **redacted** with `llm_fill.redact` (`[private]`, llm_fill.py:123-145). The rule is the same with the switch on or off (constraint 3): the value set does not read the switch, and the redaction never tests it.
- **Checked** = `guards.quote_checked(a)` (review F1: the one definition, beside `CONF_KEEP_TRUSTED`; storage-only, no guard calls it): the Answer has its own non-empty `evidence` and `status in (FILLED, PREFILLED, FILL_FAILED)` and `confidence != CONF_KEEP_TRUSTED`. Only guards.py:747 (resume/job, after G3) and 804 (grounded keep) produce such an Answer. A checked quote is a substring of the resume, the posting or the non-private facts (`_grounded`, guards.py:606-613; `facts_corpus` = non-private facts only, guards.py:433). So it holds no value that only the private profile holds.
- **Redacted**: rejected quotes (constraint 1: redact, don't drop), the quote of a fact-cited decision (the fact route stores no evidence on the Answer, guards.py:573), unknowns, and a trusted keep (guards.py:782-784, the one route that stores an unchecked quote).

## 3. Value set and matching (the gap, resolved)
`s_values + enum_s_values` misses three D-201 leaves:
1. `pay.current_salary`: `_leaves` yields it as a dict (facts.py:210-211) and `enum_s_values` skips dicts (facts.py:993). `redaction_values` leaves numbers out on purpose (applicant.py:2150-2157).
2. Sensitive `extra` answers: `extra` is in `SKIP_KEYS` (facts.py:54), so `enum_s_values` never sees it.
3. `standing:account_email`: covered already by `s_values(profile, account_email)`.

These existing functions supply the missing values: **`facts.fact_catalogue`** (facts.py:343-383), the list that prints the `private: <value>` lines the model copies, called with the switch forced on so the set does not depend on it. New helper in facts.py (a union of existing lists, no hand-kept list):
```
quote_s_values(rctx, today) = dedupe, longest first, of
  s_values(rctx.profile, rctx.account_email) + enum_s_values(rctx.profile)
  + [f.value for f in fact_catalogue(rctx.profile, replace(rctx, model_sees_sensitive=True), today=today)
     if f.private and f.value and f.kind != "bool"]
  + for a private fact of kind "salary" or "number": each digit run of 3+ in f.value (the amount as its own token)
  minus "yes" / "no" / "true" / "false"
```
**Matching** is `llm_fill.redact`. It matches whole runs only: `(?<![A-Za-z0-9])v(?![A-Za-z0-9])`, a phone-like value of 6+ digits as a digit run, case-insensitive, and values under 3 characters are skipped (llm_fill.py:127-143). Do not use `applicant.scrub` / `apply_flow.redact`: they match a value with a digit anywhere, so "4321" would be blanked inside "143210".
- Salary amount: `4321` is redacted as a whole number token. `43210` and `ID4321` are left alone. The currency and period ("SGD", "per month") stay: they are ordinary words and not identifying on their own.
- Left out, with the reason: `months_per_year` ("12" to "14"), because the 3-character floor skips it and a two-digit number is ordinary text ("12 months"). The four `consents`, booleans and yes/no `extra` answers, because "yes"/"true" are ordinary words, the value is one bit, and the employer gets the same bit from lock L5 / D-87. Legal and preferred names stay unredacted: they are not private (`NAME_PATHS`, facts.py:50, 126-127), they are shown since M20, they are in the resume and they are typed into every form. The year of birth alone stays: the full date forms are in `s_values`, and a bare year is also a graduation or job year in the same quotes.
- Known cost (owner constraint 1): `enum_s_values` words such as the nationality, NS status or "decline" are blanked as whole tokens in an *unchecked* quote. Checked quotes keep them, because replay needs those verbatim (§5).

## 4. The two write points (engineer)
- **pagefill.py.** (a) Add `_Run.qv: list` and set `run.qv = F.quote_s_values(rctx, run.today)` in step 2, after `run.deny` (line 145). (b) New public `stored_quote(evidence, a, values) -> str`: return `evidence` when `a is not None and G.quote_checked(a)` (no status/confidence test of its own), else `L.redact(evidence or "", values)`. (c) In `_cache_put` (line 745): `"evidence": stored_quote(d.evidence, run.answers.get(key), run.qv)`. `run.answers` is filled at line 274, before `_cache_put` (line 788).
- **apply_flow.py.** `_Attempt` has no profile or rctx today (lines 185-204), so add `_Attempt.quote_values: tuple = ()`. Set `at.quote_values = tuple(F.quote_s_values(rctx, F.today_sg(self.now())))` in exactly two places (review F3): (i) right after each `rctx = self.resolve_ctx(...)` (lines 1052, 1186), and (ii) inside `account()` on the swapped context, just before its `return` (line 1577), so sign-in, sign-up and the email-check reopen (F7, 1207-1209) all refresh it. Both run before the first `record` on every path (1124, 1238, 1508). `record_all` on an early failure (1020, 1030) has no Answer with evidence yet. The corrective pass (1230-1233, a second `fill_page`) is recorded at 1238 with the same `at.quote_values`. Change the signature to `audit_row(step, f, a, quote_values=())` with `"evidence": pagefill.stored_quote(a.evidence, a, quote_values) or None` (line 324), and make `_Attempt.record` (line 269) pass `self.quote_values`. Every Answer that carries evidence comes from `fill_page`, which runs after line 1186.
- **guards.py.** Gains one function, `quote_checked(a: Answer) -> bool`, beside `CONF_KEEP_TRUSTED` (line 54). No guard logic changes.
- **facts.py.** `quote_s_values` next to `enum_s_values`. In the `enum_s_values` docstring, "`redact` must not use them" becomes "the job log (`apply_flow.redact`) must not use them; `llm_fill.redact` uses them for compose prompts and stored unchecked quotes (D-202)".
- Never mutate the Answer: `_picker` reads `ans.evidence` in memory (pagefill.py:479).

## 5. Replay: the guards do re-read `evidence`
`_cached` rebuilds `ModelDecision(..., d.get("evidence"))` (pagefill.py:709), and cached decisions go through the guards like fresh ones (pagefill.py:241-242, 270). The quote is read by G3 (`cnorm(d.evidence) in corpus`, guards.py:606-613), `copy_ok` (630), `ground_items` (724), G4 (732, 791) and grounded keep (788-791). It is never read on the fact route (`_fact_field`, guards.py:529-578), for unknown (815) or for a trusted keep (782-784).
- Checked quotes stay verbatim, so their replay is byte-identical. Redacting them would make G3 fail on replay ("quote not in the source").
- A redacted fact, unknown or trusted-keep quote replays the same way, because those routes never read it. A trusted keep that turns into a grounded keep on replay fails closed.
- A redacted rejected quote stays rejected on replay: it contains `[private]`, which the raw resume and posting corpus never holds. Only the note can change (G4/G5 becomes "G3: quote not in the source"). That affects optional fields only (BLANK_OPTIONAL either way), because required rejections stop the page and are not cached (pagefill.py:729-734).

## 6. Unchanged
The guard logic in `guards.py` (it only gains the storage-only `quote_checked`), `locks.py`, `llm_fill.py`, `resolve.py`, the web, the job log (`_Log` + `redaction_values`) and compose (apply_flow.py:1442-1443). Contracts too (constraint 5): after the change, contracts.py:966 "decision (no private value)" and the `cache_put` docstring (apply_flow.py:623) are true. A stored decision holds no value for a fact, a redacted unchecked quote, or a checked quote that is resume, posting or non-private-fact text. The only residue: a checked quote can repeat a contact detail the resume itself prints. That is resume text, already stored with the attempt, and it reads D-105 hook (b) as "no value only the private profile holds".

## 7. Existing rows (constraint 2; optional, owner only, NOT built)
- `fill_cache`: no step. Old rows purge in 30 days (`FILL_CACHE_DAYS`), and a replay never re-writes them (only `run.fresh` is put).
- `apply_answers`: only if the owner asks. Back up `data/jobscraper.db`. Then a store method updates `evidence` for rows whose `status`/`confidence` fail the §2 check, using `stored_quote` with today's profile set, and a CLI verb runs it with `--dry-run` first (it prints a count only, never values). This is off unless the owner asks.

## 8. Pins (tester; constraint 4)
1. Flip `tests/test_q74_llm_fill_hooks.py::test_d201_known_gap_q113_a_rejected_quote_is_stored_verbatim_in_evidence` (branch `tst/Q-112-pins`) to `..._is_redacted_in_evidence`, using the review scenario. The audit `evidence` has no "4321", still has `pay.current_salary | Current salary` and `[private]`, and the note is unchanged.
2. Same scenario: the `fill_cache` row's `decision.evidence` is redacted the same way.
3. Switch off twin: a rejected quote that holds the account email or the date of birth is redacted in both stores.
4. Cache-hit replay of an accepted resume quote that holds an `enum_s_values` word the resume also holds: stored verbatim in both stores; the second `fill_page` replays it (`via == "cache:page"`) to the same FILLED value.
5. Replay of a fact-cited decision whose quote held the `private:` line: stored redacted, replays to the same value (the quote was never needed).
6. Replay of a rejected optional: stored redacted, BLANK_OPTIONAL again.
7. Whole-token: "12 months", "yes"/"true", "43210" and "ID4321" are left intact; the legal first name is left intact.
8. A trusted keep with an unchecked private quote is redacted in both stores.
9. (Review F1) Drive each guard route that gives an Answer non-empty evidence: resume/job after G3 (guards.py:747), grounded keep (804), trusted keep (782-784), and the rejecting `_answer_unknown` paths (727, 731, 733, 737, 790, 792, 796). `quote_checked` is True only for the first two.
10. (Review F2) Rows that are not model decisions are unchanged by `stored_quote`. Their audit `evidence` is byte-identical before and after D-202 for: an L8 composed TEXTAREA row, a composed FILE row (D-186: value = whole text, note `composed file: … (sha256 …)`), a lock-decided row (L1-L7) and a tier-1/2 resolve row.
11. (Review F3) A rejected quote on the corrective pass (a second `fill_page` after `StepResult.errors`) is redacted in its audit row. A resumed attempt (account wall, email-check reopen) records with `quote_values` set from the swapped context.

**Verify (separate runs):** `python tests/run_tests.py -k q74`, `-k q113`, `-k llm_fill`, `-k guards`, then `-k apply_flow`, `-k apply_e2e` and `-k q97` (Edge), then the full suite.

READY TO BUILD: yes (KA-2 design review by the apply session, 2026-11-12, approve with F1-F3)
