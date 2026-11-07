# VERDICT: MERGE. Re-review of the Q-35 WP-R3 fix commits, `eng/Q-35-R-page` @ `2add8ee`

- **Reviewer:** reviewer agent, 2026-11-07. Read-only (no code touched, no server started, `data/` and port 8765 untouched).
- **Against:** `docs/reviews/Q-35-R3.md` (F1-F11), `llm_fill_design.md` §6.4, §8, §11, §13.3, G9.
- **Read:** `git show` of the F1-F6, F8, F9, F10 commits, `apply/pagefill.py` @ `2add8ee` (741 lines, whole file), `tests/test_apply_pagefill_review.py`.
- **Scope of this verdict:** the lane can merge into `int/Q-35-M`. **No CRITICAL or HIGH finding is open.** All of F1-F6, F8, F9 and F10 (the part in R3) are closed. I found 3 new findings (2 MEDIUM, 1 LOW). None blocks the merge. They belong in N6a, or in a small follow-up commit on the lane.

**One merge condition (a test state, not a finding against lane R):** two older pagefill oracles fail on this branch (below). Both fail because lane M's G2(e) fix (`36007cc`, already merged here) makes "How Did You Hear About Us?" unknown, so the wd_a/wd_b step-02 pages now stop at step 7. Lane M's `e2414c5` ("how-heard fit reads the whole option path") is not yet in this branch. The handover records 19/19 pagefill with `e2414c5`. I did not re-run that combination. The Coordinator should rerun `-k pagefill` after `e2414c5` is merged into `int/Q-35-M`. If the two still fail, the tester updates them.

## Findings table

| Finding | Fix commit | Closed? | Evidence |
|---|---|---|---|
| F1 HIGH: failed optional fill keeps the site value | `dcca216` | **Closed** | `_clear_failed_optional` (`pagefill.py:598`) runs after `_corrective`. It resets each optional key still in `run.failed`: BLANK_OPTIONAL "G9: cleared after failed fill (<note>)" when the read-back is empty. Otherwise PREFILLED, `G.CONF_UNVERIFIED`, `G.UNVERIFIED_NOTE`. Required keys stay in `failed`. Pin `test_f1_an_optional_prompt_whose_fill_failed_is_reset_or_flagged_never_kept` passes: pills `[]` or flagged, never FILLED. Not pinned: the optional radio group and the required twin (`reset_field` reports "unsupported" for a radio, which lands in the flagged branch; read from code). |
| F2 HIGH: entry delete never verified | `9d14dcf` | **Closed** (with F12 below) | `_delete_entries` (`:336`) clicks bottom-up, re-reads `run.sections`, and counts a delete only when the click took, the group's controls are gone from the page and the section shrank. An unconfirmed group is never skipped: required fields stop the page (UNKNOWN "E3: delete not confirmed"), optional ones are reset or flagged PREFILLED unverified. Replayed the review scenario (stub `review_entries`, delete click swallowed): `junk left: True`, `unknown: [WE2 Job Title, Company, From, To]`. Unswallowed control run: `junk left: False`, nothing reported. Pin `test_f2_a_swallowed_delete_never_leaves_the_junk_entry_silently` passes. |
| F3 MEDIUM: three ways to time out | `4072364` | **Closed** | `_time_left` is now called in `_second` (`:292`), before each `recheck_entry` (`:244`) and before the LL2 pick (`:276`). The fill-time `pick` sets `run.transport = TIMED_OUT_NOTE` and `_apply_one` raises `_Stop` (`:424`). `guards.py` has no `except`, so `_Stop` passes through `G.decide`'s `second` callback up to `fill_page`'s handler. Pins pass: deadline inside `second` gives `transport_failed`, "transport: timed out", `unknown_required == ()`, `capture_page == []`. The deadline between rechecks stops the next recheck (exactly 1 recheck call). |
| F4 MEDIUM: required search miss ended `fill_failed` with no question | `a481727` | **Closed** | `_required_misses` (`:622`) maps a required key whose note is in `MISS_NOTES` (`search_miss`, `no_option`) to UNKNOWN "LL3: no option found" and returns it as `unknown_required`. `readback`, `site_error` and `not_decided` stay `fill_failed`. It runs after `_clear_failed_optional` and before `_required_scan`. Pin `test_f4_..._is_unknown_and_captured` passes: key in `unknown_required`, not in `fill_failed`, exactly one capture. |
| F5 MEDIUM: Add compares stale sections, failed Add silent | `443b0f1`, `2793b60`, `2add8ee` | **Closed** (one small gap, F14) | `_delete_entries` re-reads `run.sections`. `_add_entry` (`:467`) takes `count` from the fresh section, finds the new entry by position (`sorted(...)[count:]`), not by a group id a deleted entry might have had, and `run.dead` keeps a deleted entry's keys from being inherited. A missing control, a failed click, no new entry or no fields calls `_add_failed`, which marks the section's keys (`run.entry_failed`) and `_outcome` reports them `fill_failed` "E5: entry not added". Replayed: normal run fills "Sample Analytics" and removes the junk; Add swallowed gives `failed: WE1 Job Title/Company/From/To "E5: entry not added"`. Pin passes. |
| F6 MEDIUM: wrong inheritance of another field's answer | `ccd1324`, `2793b60` | **Closed** | `_read` (`:177`) offers an old audit key for inheritance only when the old key is absent from the current read (`k not in here`), not dead, and not already an alias target. Pin `test_f6_a_revealed_field_on_a_reused_ordinal_is_filled_itself` passes: all three "Favourite tool" inputs show "Git". |
| F8 LOW: cache keeps rejected decision, `cache:recheck`, negative pick | `0ef9293`, `2793b60` | **Closed** | `_cache_put` (`:668`) skips `NO_CACHE_VIAS` (now `second`, `corrective`, `recheck`) and every key in `run.corrected`, and drops an empty `pick` (and any earlier row for that key). `_outcome` now calls `_cache_put` also on a step-7 stop (so the retry after an owner answer replays the rest, LF §13.3); `_transport` still never does. Pins pass: `test_f8_...rejected_is_not_cached`, `test_cache_round_trip_...`. New side effect: F13. |
| F9 LOW: dropped stop from the scan's own round | `b9052b6` | **Closed** (the optional "last-round fields" part stays open by design; the review called it optional) | `_required_scan` (`:583-585`) now returns the `_apply` stop. Read from code; no pin. |
| F10 LOW: unreadable upload crashes | `2bbf7eb` | **Closed for R3** | `_apply_one` (`:412-420`) catches `OSError` around the hash; an unreadable file counts as a failed upload (`run.failed`), never `ctx.uploaded`. Read from code; no pin. **Still for N6a:** an outcome's answers are "decided", not "applied" (a step-7 stop returns FILLED rows for fields never typed). N6a must write the audit only after a page that filled, or mark the rows. |
| F7 LOW, F11 LOW | not in scope | Carry-over to N6a | F7: follow-up budget per page, not per attempt. F11: duplicated constants (`L1_KEPT_NOTE`, `FACT_SOURCES`). |

**Merge of `int/Q-35-M` (`25500c3`, `12e8ebe`):** both merges leave `pagefill.py` exactly as lane R wrote it (their diff against the lane-R parent for that file is empty; the only `pagefill` diff is against the int parent, where the file didn't exist). Lane M has no pagefill code, so there was nothing to drop. The calls into lane M's API (`pick_option(sensitive=, deny=)`, `decide(blocks=)`, `recheck_targets(blocks=)`, `entry_blocks`) still match: `-k llm_fill` 72/72. `git merge-tree` of `int/Q-35-M` (3aadc13) with this head shows no conflict.

**Regression hunt on the fixes (no new HIGH):**
- Fail-closed order is intact: step 7 returns before any change; `services.classify` runs before step 9, before each reveal-round apply, before the added entry's fills and in `_corrective`.
- Privacy: still no `log()` of values. The two new `services.log` lines carry only a section name, an index and a reason (`E3: delete not confirmed for <section>#<n>`, `E5: add failed in <section>: <why>`).
- Layering: `tests/test_layering.py` imports are unchanged (same-stage modules plus `BackendError`); no SQL, no model I/O added. (`-k pagefill` and `-k llm_fill` do not run the layering file; the module's import block is unchanged from the version that passed 10/10.)
- The field locators are `data-llmfill` stamps, not index-based ids, so a renumbered entry cannot make `_present` match a surviving field (I checked this because it would have broken F2).

## New findings

### F12 MEDIUM: one failed delete makes the successful deletes in the same section look unconfirmed
`pagefill.py:346-361` (`want` and `left` are per section; the check is per group).

- **Why:** `want[section]` is lowered once per requested delete, whether or not the click worked. A group counts as confirmed only if `left[section] <= want[section]`. If two groups of one section are to be deleted and one click is swallowed, `left` is initial-1 and `want` is initial-2, so **both** groups fail the check, including the one that really went.
- **Failure scenario:** Workday My Experience, E3 marks "Work Experience 2" and "Work Experience 3" as junk. The delete on 3 works and the one on 2 is swallowed. Group 3 has `clicked` true and nothing alive, but is reported "not confirmed". Its required fields, which no longer exist on the page, are returned as `unknown_required`, and `capture_page` creates Questions cards for a job title and company of an entry that is gone. The page stops anyway (group 2 is really there), so nothing is submitted wrongly. The owner is shown extra, confusing cards.
- **Fix:** decide per group: confirmed = clicked and no member alive. Use the section count only as a cross-check on the whole section (`left <= initial - confirmed_count`), never to demote a group whose own controls are gone.
- **Tester pin:** two junk entries in one section, only the first delete swallowed: `unknown_required` holds only the first entry's keys.

### F13 MEDIUM: a step-7 stop now caches the model's `unknown`, so the retry after the owner adds the missing data replays "unknown"
`pagefill.py:668-693` (`_cache_put`), `:703-707` (`_outcome` calls it on a stop, `2793b60`); LF §13.3.

- **Why:** the fix for the retry path correctly caches the other decisions of a stopped page. It also stores the stopped field's own decision, which is `source: unknown`, `ref: ""`. A row with no cited fact has a constant `facts_used_hash`, so it never misses when the profile changes. Before `2793b60` only finished pages were cached, so a required unknown never reached the cache.
- **Reproduced (scratch run, stub `review_required_prompt`):**
  - run 1, model says unknown for a required field: `unknown_required: ('f1_…',)`, cached rows `[('unknown', 'page')]`;
  - run 2, same job and resume, a cache holding those rows and a model that would now answer from the resume: **0 `page` model calls** and `unknown_required` still holds the field.
- **Failure scenario:** the page stops on a required free-text question. The owner adds the missing fact in Profile (or Q-71's new application details) and retries. The field still cites nothing, so the stored `unknown` replays, the model is not asked again and the same card comes back until the 30-day purge or a model change. (A question answered through the Questions tab is saved as an `extra` entry. I did not check whether it also becomes a rule lock, which bypasses the model and would avoid this. If it does, the impact is limited to Profile edits.)
- **Spec note:** LF §13.3 says "the latest fresh decision per field" and does not exclude `unknown`, so the code follows the spec. The spec has a gap here. The review does not ask lane R to deviate silently.
- **Fix (one line):** in `_cache_put` skip `d.source is FillSource.UNKNOWN`, like the empty-pick rule. Amend LF §13.3 to say so.
- **Tester pin:** run, stop on a required unknown, change the profile, run with the stored rows: the model is asked again for that field.

### F14 LOW: a failed E5 add marks the section's already-filled entries `fill_failed`
`pagefill.py:498-511` (`_add_failed`).

- **Why:** the keys marked are "the section's fields on the page (its required ones, else all of them)". These are the existing entries' fields. Nothing is missing from them. The note "E5: entry not added" then sits on the audit row for a value we did type.
- **Observed (stub, Add swallowed):** `fill_failed` = Work Experience 1 Job Title/Company/From/To "E5: entry not added".
- **Effect:** fail-closed (the flow stops on a required `fill_failed`), so it is safe, and the audit text is accurate about the section. A section with no fields on the page is only logged (the code says `PageOutcome` has no entry channel).
- **Fix (optional, N6a):** keep it, but have N6a's audit writer show the note as a section note rather than a per-field failure. Or add an entry-level channel to `PageOutcome` in the next contracts version.

## Carry-overs (out of scope here)

- **F7** (follow-up budget per page) and **F11** (duplicated constants): N6a.
- **F10 audit:** write `apply_answers` only for pages that filled or mark stop rows as not applied: N6a.
- **N1:** `fill_page` returns `transport_failed` both for "model unavailable" and "timed out". N6a checks `services.deadline_left() <= 0` first.
- **Pin gaps** worth adding when the tester next touches the file: F1's radio/required twin, F9, F10.
- **Two stale oracles** (`test_a_page_that_stops_is_left_exactly_as_the_site_put_it`, `test_classify_runs_before_the_first_keystroke`): see the merge condition above.

## Test commands (run from the worktree root, `eng/Q-35-R-page` @ `2add8ee`, clean tree)

- `python tests/run_tests.py -k pagefill` printed `17/19 passed  (-k 'pagefill')`.
  - The two failures: `test_apply_pagefill::test_a_page_that_stops_is_left_exactly_as_the_site_put_it` (`assert [labels[k] for k in out.unknown_required] == ["Address Line 2"]`) and `test_apply_pagefill::test_classify_runs_before_the_first_keystroke` (`assert sv.classified and sv.classified[0] == 0`).
  - Diagnosis (scratch run of the same fixtures): wd_a step 02 returns `unknown: ['How Did You Hear About Us?']` ("G2e: no_option_fits"), wd_b returns that plus 'Address Line 2'; `classified: []`. Cause: lane M `36007cc`, not a lane R fix. All 11 review pins (F1-F6, F8, cache round trip, pick arguments) are among the 17 that pass.
- `python tests/run_tests.py -k llm_fill` printed `72/72 passed  (-k 'llm_fill')`.
- Not run, by instruction: the full suite.
