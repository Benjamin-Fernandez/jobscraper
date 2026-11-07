# Review: Q-72 (a) `maybe_untracked` (MS §8 row 7a, D-161)

Reviewer, 2026-11-07. Branch `int/Q-72-mail-untracked` @ 130d177, diff `10c6d01..130d177` (src, web/src, tests, web/tests). Spec: `docs/architecture/mail_status_design.md` changelog (4), §3, §8 row 7a and note, §9, §11.3, §16.

## Verdict: APPROVE

No BLOCKER or MAJOR. Two MINOR test gaps and two NITs; none blocks the merge.

## Evidence
- `python tests/run_tests.py -k layering` -> `13/13 passed`
- `python tests/run_tests.py -k mail` -> `206/206 passed` (includes `test_mail_q72_pins`, `test_mail_transition`, `test_store_mail`, `test_web_mail`)
- Vitest not run by me (the worktree has no `node_modules`). The engineer reports `vitest 296 passed / 1 skipped` (software-engineer outbox, Q-72). The new Vue test reads correctly against the template (see 3).

## Checklist

### 1. Correctness vs MS
- All four 7a conditions are in `_maybe_untracked` (`src/jobscraper/mailstatus/transition.py:204-215`): category in {acknowledged, rejected} (`:39`), pool non-empty, none of role / req_id / thread in `match.signals` (`:41`, `:212`), and `received_at > last_event_at` for every candidate, a missing value counting as older (`:215`). The "every candidate settled NONE terminal" condition is checked by the callers.
- Row-4 path (`transition.py:151-158`): fires only when `left` is empty (every candidate settled NONE) and every settled reason is `terminal`. An open sibling settles `same_status` or stays in `left`, so old behaviour stands. Rows 5/6 (`custom_status`, `backfilled`, `owner_newer`) are SUGGEST or a non-terminal NONE, so also excluded.
- Single path (`:164-167`): fires only when `_settle` returned NONE `terminal`. `_after_owner` returns `terminal` only for a terminal-status application, so rows 5, 6, 8, 9, 10, 11 are untouched. The reopen categories (assessment/interview/offer) are not in `_UNTRACKED_CATEGORIES`, so row 7 `reopen` and row 4 `several_applications` are unchanged.
- The model-verdict path goes through the same `mtrans.decide`, so the rule applies there as MS says.
- The `received_at` / `last_event_at` comparison is a plain string compare, the same convention as row 7.

### 2. Flow storage (`src/jobscraper/mailstatus_flow.py:451-482`)
- `untracked` forces `job_id = None`, so `mail_messages.job_id` is NULL for STRONG too (the thread never attaches). For STRONG/WEAK, evidence has `job_id=None`, `from_status=None`, `candidates_json=[that one]`. Outcome `SUGGESTED`, which feeds the `suggested` count.
- AMBIGUOUS goes to the existing `elif ambiguous:` branch. `remaining_candidates` returns `()` for it (every candidate settles NONE, `transition.py:186-190`), so `left or tuple(cands)` yields every matched candidate, as MS requires. Confirmed by reading; no test pins it (F1).
- Accept: `store._mail_accept_tx` returns `not_open` when `to_status` is empty (`src/jobscraper/store.py:2518`), so Got it (dismiss) is the only answer; no candidate can be picked.
- Supersede: `_mail_open_suggestions` takes the candidate branch (candidates_json non-empty), so the suggestion stays live while any candidate still has its recorded status. That is the ambiguous rule MS names. Sensible: it goes stale only once the owner has changed all the closed rows.

### 3. UI (`web/src/components/MailSuggestions.vue`)
- `appLine` falls back to `candidates[0].company` (`:47-50`). `s.to_status` is null, so the select (`v-if="s.to_status && ambiguous(s)"`, `:137`) and Accept/Dismiss are hidden. The `v-else` shows "Got it", plus "Open in Gmail" when the server gave a Gmail URL. "Check the email" is the existing no-target line. `reason_text` comes from `REASON_TEXTS`; the string is verbatim MS §3 / §11.3 ("This email may be about an application you haven't added.") and the pins test asserts equality.
- The `appLine` fallback also changes other ambiguous cards (they showed no company before); MS §11.3 says this is intended.
- No built bundle in the diff, correct per CLAUDE.md. `MailSuggestions.vue` changed, so the Coordinator must rebuild in the main checkout after merge for the live app to show it.

### 4. Tests
- `tests/test_mail_q72_pins.py` oracles 2 to 10 assert the MS values (kind/reason/to_status) from the design, not from the build. Oracle 6 covers older, equal and a strictly-newer control; oracle 5 covers the open sibling both ways including the offered list `["acme-4"]`; oracle 8 covers the unchanged categories and the reopen path; oracle 9 flow keeps `backfilled`; oracle 10 covers the custom status. The flow test covers STRONG storage and the "a later rejection in the same thread is not silent" consequence.
- `tests/test_mail_transition.py` row-7 edit, compared with 10c6d01: the two replaced assertions (`rejected` in the terminal-target loop and the `acknowledged` terminal line) are exactly the ones MS row 7a changes (late, no signals). They are now `suggest / maybe_untracked / to=None`, and the old `terminal` value is kept for each of role / req_id / thread. `withdrawn`, `posting_closed`, `kept_on_file`, the reopen assertions and the `older` / equal-time assertions are untouched. No oracle was weakened; `_m`/`_decide` gained an optional `signals` argument defaulting to `()`, so other callers are unchanged.
- Gaps: F1, F2.

### 5. Privacy
Added lines contain only "Acme" / "Northwind" fixtures, `no-reply@acme.example`, and `Candidate Role Zed`. No real employer, address, req id, URL or personal data in src, tests or docs. I did not have the deny-list file; I scanned the diff for addresses, names, req-id patterns and URLs.

### 6. Layering
`transition.py` imports only `.contracts` (adds `Signal`); `mailstatus_flow.py` adds no import. `-k layering` 13/13.

## Findings

**F1 (MINOR, test gap)** `tests/test_mail_q72_pins.py`, `test_q72_o1_*`. The "all three candidates offered" check is `assert [a.job_id for a in apps] == ["acme-1","acme-2","acme-3"]`, which compares the fixture with itself and proves nothing. No test asserts that `remaining_candidates` returns `()` for 7a, or that the flow stores all three in `candidates_json` for the AMBIGUOUS case (the actual D-160 scenario); the only flow test is STRONG with one candidate. Failure scenario: someone changes `left or tuple(cands)` or `remaining_candidates`, the 3-candidate card shows an empty or partial list, or the staleness check supersedes it at once; the suite stays green. Fix: add a flow test with two closed applications asserting `candidates_json` holds both and `mail_suggestions` returns it; assert `_offered(...) == []` in o1. The code is correct today.

**F2 (MINOR, test gap)** No test for Accept on a `maybe_untracked` suggestion (expect `(False, "not_open")`, status unchanged) or for dismiss through `mail_dismiss`. Behaviour is right by `store.py:2518`, but not pinned for this reason. Fix: one store test.

**F3 (NIT)** `mailstatus_flow.py:475-479`: `matched = [app] if app is not None else []` cannot be empty for a non-ambiguous match that reached 7a; harmless dead guard.

**F4 (NIT, behaviour note, not a defect)** By spec, any late generic acknowledgement or rejection that names no tracked role, at an employer whose applications are all closed, becomes a card. Expect a few false hints on the real mailbox after merge; each is one "Got it". Messages processed before the merge are not re-run (dedupe by X-GM-MSGID), so the D-160 mails only show if re-read, for example in a fresh window; new mail of that kind will show.

## Disagreements with the spec
None.

## Suggested next step
Merge into `personal` (F1/F2 can be a follow-up tester task). After merge: rebuild the bundle in the main checkout (`cd web; npm run build`) so the company fallback ships, then smoke on 8768.
