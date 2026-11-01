# Instructions: index and read order

| # | File | Purpose | Who may edit | Read when |
|---|---|---|---|---|
| 0 | `README.md` (this file) | Index | Coordinator | Session start |
| — | `handover.md` | Where the last session stopped; the next 1–3 actions (≤ 40 lines) | Coordinator | Every session (imported by CLAUDE.md) |
| 1 | `01_scope_and_goals.md` | Vision, users, constraints, principles, out of scope | Coordinator, owner-approved changes only | Before planning or any scope question |
| 2 | `02_status.md` | Live status: Now/Next, milestones, requirement status, decisions, known issues | Coordinator | Session start (Now/Next); when recording |
| 3 | `03_methods.md` | Prompt enhancement, delegation template, engineering method, git workflow, testing profile, evidence, skills | Coordinator | Before delegating; before building or testing |
| 4 | `04_team.md` | Roster, model tiers, write scopes, communication, spawning, approval gates | Coordinator | Before spawning; on a scope question |
| 5 | `05_workflow.md` | Coordinator loop, selection rules, build lifecycle, review checklists, lessons | Coordinator | Every loop iteration |
| 6 | `06_work_queue.md` | Live queue | Coordinator | Every loop iteration |

## Key documents outside this folder

| Document | Path | Owner |
|---|---|---|
| Product requirements, M19–M22 | `docs/prd.md` | planner |
| Previous PRD and build ledger, M0–M17 | `.claude/prds/jobscraper-v2.prd.md` | read-only history |
| App tour / architecture | `docs/OVERVIEW.md`, `docs/DESIGN.md` | planner |
| Research and domain briefs | `docs/research/` | researcher |
| Architecture, designs, ADRs, spikes | `docs/architecture/` | architect |
| Build plans | `docs/planning/` | planner |
| Reviews | `docs/reviews/` | reviewer |
| Session history (append-only) | `docs/planning/session_log.md` | Coordinator |
| Agent outboxes | `comms/outbox/<role>.md` | each role, its own file |

## Quick start for a new session

1. Read the handover note (already in context), then `02_status.md` Now/Next and the open outbox entries (the session-start hook lists them).
2. Enhance the owner's prompt (`03` §1).
3. Run the Coordinator loop (`05` §1): select, delegate or do it directly, review, record.
4. Before ending: rewrite `handover.md`, append to the session log, update `02_status.md`, commit on `personal`.
