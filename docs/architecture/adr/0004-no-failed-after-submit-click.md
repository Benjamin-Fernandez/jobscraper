# ADR-0004: No `failed` after the Submit click (contract v2)

**Status:** Accepted (implements D-69 item 1)
**Date:** 2026-11-02
**Deciders:** Coordinator (D-69); architect (contract shape)
**Relates to:** PRD NF-06, F-37, F-38; ADR-0003 decision 5; `apply_design.md` §4.1, §4.2, §4.4, §8.4; `src/jobscraper/apply/contracts.py`

## Context

`apply_design.md` §4.1 said that once `submit_clicked_at` is set an attempt ends only `submitted` or `submitted_unconfirmed` (NF-06), but contract v1 added `failed` to every non-terminal state, including `submitting`, and §4.4 let `captcha` end an attempt "at any point, including after Submit". The tester (Q-08) found the conflict. A `failed` row after a click is dangerous: it frees the posting for a new attempt (the partial unique index only covers success states), so a later run could submit the same application twice.

## Decision

1. `TRANSITIONS` no longer contains `submitting → failed`. Every other non-terminal state still may fail.
2. `verifying_email → submitted_unconfirmed` is added: after the Greenhouse emailed-code click (§4.2) a timeout, missing mailbox or error must end there, not in `failed`.
3. `POST_CLICK_STATES` and `can_transition(src, dst, *, clicked=None)` encode the rule for the one state reachable both before and after a click (`verifying_email`): with `clicked=True` only post-click states are allowed; with `clicked=False` none of `submitting`/`submitted`/`submitted_unconfirmed`. `store.set_attempt_state` passes `clicked` and raises `ValueError` otherwise.
4. Any challenge, error page or exception after the click → `submitted_unconfirmed` with a `reason_detail` note ("captcha after submit"); never retried. Only the owner's "It didn't go through" (a dedicated store method outside `TRANSITIONS`) can make it `failed`.
5. `CONTRACT_VERSION` 1 → 2 (also carries the additive D-68 `ResolveContext` fields and the D-69 `DeclarationLabel.CURRENT_EMPLOYEE`).

## Consequences

- The owner sees "may have been sent" instead of "failed" for post-click problems, and the posting stays blocked until they resolve it: a duplicate submission is impossible by construction.
- Callers of `can_transition(src, dst)` without `clicked` keep v1 table semantics minus the removed edge.
- Tester oracles to update: `test_every_non_terminal_state_may_fail_and_terminal_states_are_final` must exempt `submitting`; `test_only_the_review_page_leads_to_submit_and_a_dry_run_never_submits` must allow `verifying_email → submitted_unconfirmed` as a second source of that success state.
