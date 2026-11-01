# 05: Coordinator loop and build lifecycle

## 1. The Coordinator loop

Run this loop at the start of every session, after every owner message, and every time an agent returns.

| Step | Name | What the Coordinator does |
|---|---|---|
| 1 | **Orient** | Read the handover note, `02_status.md` Now/Next, the queue (`06`), and outbox entries with `STATUS: open`. Check `git branch` and `git worktree list`. |
| 2 | **Triage** | Enhance the prompt (`03` §1). Classify it as a decision, new work, a change request or a question. Add new work to the queue as `BACKLOG`; record decisions in `02` §4. |
| 3 | **Select** | Choose the next 1–3 items using §2. |
| 4 | **Delegate** | Do it directly if cheap (`04` §4). Otherwise use the delegation template, with a budget, a branch and the skills to load. Start independent build items as parallel engineer lanes. Set each item to `IN PROGRESS`. |
| 5 | **Review** | Check the deliverable against its acceptance criteria with §5: **accept**, **revise** (numbered defects to the same agent) or **reject**. After 2 revise cycles, escalate: re-scope, stronger model, or ask the owner. |
| 6 | **Integrate** | Merge into `personal` (`03` §3a): verify on the branch, `merge --no-ff`, rebuild the SPA bundle if `web/src` changed, smoke-check `personal`, delete the branch and worktree, push. Route outbox requests; queue follow-ups. |
| 7 | **Record** | Update the queue, the status and the handover note, and commit them on `personal`. |
| 8 | **Continue or report** | If the next item is ready and not behind an owner gate, go back to step 3. Otherwise report: what changed, what is blocked, and the decisions needed, each with a recommendation. |

Never stop without rewriting the handover note.

## 2. Selection rules (what to work on next)

0. **A working product first.** The walking skeleton (M20), then the MVP (M21), then live use, beat everything below except rule 1. Small improvements and test depth go last.
1. **Gates first.** Never start an item behind an unapproved gate, except work that prepares the gate decision.
2. **Unblock the owner.** Owner tasks (profile values, app password) are prepared early so they never block a build.
3. **Critical path; spikes before what depends on them** (S-1/S-3 before the browser driver, S-2 before the tailor LLM layer, S-4 before IMAP).
4. **Priority:** P0, then P1, then P2.
5. **Lifecycle order** (§3). No build before its design is `READY TO BUILD`.
6. **Parallelism by default** for disjoint READY items (M19's engine and UI lanes; M20's tailor, profile/resolver and browser/adapter lanes once contracts exist).
7. **Token discipline.** Lowest tier that meets the acceptance criteria; the top tier for KA design, KA builds, hard debugging and gate reviews.

## 3. Build lifecycle: design before build

### 3.1 Full dossier, for key areas (KA-1 auto-apply engine, KA-2 answer resolution, KA-3 accounts/vault/mailbox, KA-4 tailor truthfulness)

| Stage | Owner | Deliverable | Content |
|---|---|---|---|
| A. Domain brief | researcher | `docs/research/<area>_brief.md` | **Done** for all four: `auto_apply_brief.md` (KA-1 to KA-3), `resume_tailor_brief.md` (KA-4) |
| B. Design | architect | `docs/architecture/apply_design.md`, `tailor_design.md` + contracts + ADRs | Components, contracts, plug-in points, config schema, algorithms, errors and degradation, extension walkthrough ("add a new ATS in N steps"); maps every PRD requirement to a section |
| C. Test plan | tester | `tests/plans/<area>_test_plan.md` (≤ 2 pages) | Golden cases as oracle tests, one smoke/replay check, the key refusals, fixtures (recorded Greenhouse JSON, local HTML form pages) |
| D. Build plan | planner | `docs/planning/<area>_build_plan.md` | WPs ≤ ~1 day and ≤ ~8 files, with inputs, dependencies, `Verify:`, done-when, requirement IDs, and **lanes** with disjoint files |
| E. Cross-review | roles review each other; Coordinator chairs | outbox review entries | Exit: zero blocking issues → **READY TO BUILD** |
| F. Build | engineer(s) | code on a branch + handoff | Exactly as specified; parallel lanes in worktrees; frequent commits |
| G. Verify | tester / reviewer | tests, review | Per the testing profile |
| H. Accept | Coordinator (+ architect if contracts changed) | merge into `personal` + status ticks | `03` §5 |

### 3.2 Fast track, for everything else (cloud port, profile form, settings, UI panels)

1. The architect (or the Coordinator) writes **one lean design** with numbered build steps. For M19 the design is `docs/research/cloud_port_report.md` §1 and §3.
2. The Coordinator reviews it and marks it `READY TO BUILD`.
3. The engineer builds step by step and runs a smoke check.
4. The reviewer looks at it before the milestone closes.

### 3.3 Spikes

A spike answers one question within a time box. Its code is throwaway (in `docs/architecture/spikes/<id>/` or a scratch folder, never in `src/`). The report goes to `docs/architecture/spikes/<id>.md`. Spikes on real employer sites are **dry-run only**.

### 3.4 Changes after READY TO BUILD

A change goes back to the stage that owns it; a contract change needs the architect (and an ADR if significant). Record it in the queue.

## 4. The engineer only builds

The engineer receives only `READY` work packages with pointers to the WP and design sections. If a WP is ambiguous, the engineer stops it, writes a `question` in its outbox, and moves on. No research, algorithm or parameter choices, contract edits, or official tests.

## 5. Review checklists (loop step 5)

| Deliverable | Accept only if |
|---|---|
| Research or brief | Every external claim has a URL and date; unverified items marked; fact, inference, opinion separate |
| Design or contracts | Every PRD requirement it covers is mapped; depends only on contracts and foundation; plug-in points named; extension walkthrough works; degradation and every reason code defined; nothing contradicts `01` |
| Test plan | Fits product-first and its budget; every golden case becomes a test; no live network calls |
| Build plan | Every WP small and ordered with inputs, `Verify:`, done-when, requirement IDs; lanes have disjoint files; no WP needs a design decision |
| Code handoff | Committed on its own branch, merges cleanly into `personal`; matches the WP; `Verify:` quoted; no secrets or personal data; nothing outside scope; config changes listed; says how to run it |

## 6. Session start and end

- **Start:** loop step 1.
- **End:** rewrite `handover.md` (≤ 40 lines); append one dated entry to `docs/planning/session_log.md`; update `02_status.md`; commit on `personal`; list open branches and worktrees.

## 7. Feedback and lessons

- Each queue item carries a **rework count**; at 2 or more, add a one-line cause.
- At each milestone gate, write a short retrospective in `comms/outbox/coordinator.md` and update this file.
- Lessons for this project:
  - Merging into `personal` changes the owner's daily app: smoke-check after every merge (`python -m jobscraper doctor` and the touched suite).
  - Build the SPA bundle only in the main checkout; a worktree build hashes differently (M12).
  - Never copy cloud files wholesale; port hunks from the `019e975` snapshot (cloud report §0, §3a).
  - A fresh worktree lacks `data/`: copy the DB and resume in; never point a dev instance at the live DB.
  - Check "done" and "nothing left" claims with a grep or a run before relaying them.
