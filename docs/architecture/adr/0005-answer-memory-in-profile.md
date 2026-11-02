# ADR-0005: The owner's answers to application questions live in `data/applicant.yaml` (`extra:`); the DB holds only the question queue

**Status:** Proposed (D-74, Q-30)
**Date:** 2026-11-03
**Deciders:** Coordinator (D-74); architect (shape)
**Relates to:** PRD F-10, F-12, F-13 (proposed), F-32, NF-01, NF-02; `questions_design.md` §6, §7; `apply_design.md` §7.4, §13 (`answer_memory`)

## Context

D-74 asks for questions that applications meet and can't answer to become new fields the owner fills in the web app, so later applications can reuse the answers. Two kinds of data come out of this:

1. **The queue**: which question, which options, which employer, job and attempt, and how many applications are waiting. This is employer text plus links between rows, and it changes on every run.
2. **The answers**: the owner's facts, some of them sensitive.

`apply_design.md` §7.4 planned a DB table `answer_memory`, keyed by `(label_norm, field_type, ats)`, with tier 3 reading it from M20 and M22's audit correction writing it. Lane B has already built the table and its two methods on its branch. Nothing writes to it yet.

## Decision

1. Answers are stored in `data/applicant.yaml` under `extra:`, one entry per question key: title, kind, `sensitive`, the normalised labels that mean it, and `value` or `picks`/`seen` for choices, plus optional `by_employer` overrides (`questions_design.md` §6.1). They are written only through `applicant.save` (validated, atomic, etag-guarded).
2. The DB holds only the queue: `questions` and `question_sightings` (§7). Neither table has an answer column.
3. Tier 3 reads `extra` first (from the profile already in `ResolveContext`; no new injected dependency), then the existing `answer_memory` lookup, unchanged.
4. `answer_memory` is frozen: it is kept as built (empty, harmless) so lane B isn't disturbed mid-build. M22's "Remember for this question" (F-12) writes to `extra` instead. A later cleanup may drop the table and the `memory` callable.

## Options considered

### A: answers in `applicant.yaml` `extra:` (chosen)
| Dimension | Assessment |
|---|---|
| Complexity | Low: the existing load/validate/save path; tier 3 reads a dict it already has |
| Privacy | All of the owner's facts are in one gitignored file, redacted from logs by the existing walk |
| Owner control | One file to read, back up or hand-edit; the Profile form shows every answer |
| Concurrency | Needs the etag guard (the form and the Questions card both write the file) |

**Pros:** "the profile stays one file"; one place to edit; no answers in the DB; the resolver needs no store access.
**Cons:** every answer rewrites the whole YAML (comments dropped; a one-time commented backup mitigates that); grouping metadata (labels, picks, seen) sits beside the facts.

### B: answers in the DB `answer_memory` table (the §7.4 plan)
| Dimension | Assessment |
|---|---|
| Complexity | Low for writes; needs a store-backed web editor for every answer |
| Privacy | Facts are split across two stores; the DB copy is not covered by the profile's redaction list |
| Owner control | Answers are invisible outside the app; editing needs the UI |

**Pros:** no file rewrite; easy per-label rows.
**Cons:** two homes for the owner's facts; the web Profile form wouldn't show them; redaction would need a second source.

### C: both (DB for answers keyed per label, YAML for promoted fields)
Rejected: the most moving parts for no gain at a single-user scale.

## Trade-off analysis

At one user and tens of answers, rewriting a small YAML file is free. Keeping every owner fact in one file that the Profile tab edits, the resolver reads and the redactor walks matters more than avoiding a file rewrite. The queue is different: it is relational, it changes on every run and it holds no personal value, so it belongs in SQLite.

## Consequences

- Easier: one editor (Profile → Application details) for every fact; tier 3 is pure; NF-01/NF-02 hold without new rules.
- Harder: the YAML needs a lost-update guard (etag, 409) and loses comments on the first web save (backup copy kept once).
- Revisit: promote frequent `extra` keys to first-class paths with a `questions.yaml` row (documented in §6.3, not built); drop `answer_memory` after M22 if nothing writes it.

## Action items

1. [ ] Lane Q: `applicant.py` `extra` validation, etag, commented backup (WP-W1); tier 3 `extra` lookup (WP-Q2).
2. [ ] Lane Q: `questions` / `question_sightings` DDL and methods (WP-Q1a).
3. [ ] Planner (M22): F-12's "Remember" writes `extra` via `applicant.save`, not `answer_memory_put`.
