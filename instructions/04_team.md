# 04: Team and coordination

## 1. Coordinator (the main session)

- Runs on the top tier (`opus`), set in `.claude/settings.json`. It is the only agent that talks to the owner.
- Duties: enhances prompts; chooses what the product needs next; does the work directly or delegates it (§4); writes delegation prompts from the template (`03` §2); reviews deliverables; routes cross-scope requests; merges lanes into `personal`; builds the SPA bundle after merges; records state; enforces gates.
- Writes `CLAUDE.md`, `instructions/**`, `docs/planning/session_log.md`, `comms/outbox/coordinator.md`, `.claude/**`, `.gitignore`, `.worktreeinclude`, and the built bundle under `src/jobscraper/web/static/` (by running the build). It never writes production code or tests.

## 2. Roster

Definitions live in `.claude/agents/<role>.md`. Write scopes are enforced from `.claude/scopes.json`; keep that file and this table in sync.

**Model tiers.** Match model strength to the task: **top** for open-ended judgement, design and costly-if-wrong work; **mid** for well-specified execution; **light** for clerical work. Move up a tier for key-area builds (KA-1 to KA-4), hard debugging or after a second failed attempt; down for mechanical edits. Override per task with the Agent tool's `model` parameter.

Tier → model alias today: **top = `opus`, mid = `sonnet`, light = `haiku`** (re-map here when new models arrive).

| Role | Default tier | Spawn when | Write scope (only these paths) |
|---|---|---|---|
| researcher | top (mid for lookups) | Stage A briefs, ToS questions, new ATS adapters' prior art, question-synonym data | `docs/research/**`, `config/questions.yaml`, `config/aliases.yaml` |
| architect | top | Stage B designs, contracts, ADRs, spike reports | `docs/architecture/**`, `src/jobscraper/apply/contracts.py`, `src/jobscraper/tailor/contracts.py` |
| planner | top for build plans, mid for docs | Stage D build plans; README, OVERVIEW, DESIGN, user guide | `docs/prd.md`, `docs/planning/**` (not `session_log.md`), `docs/user/**`, `docs/OVERVIEW.md`, `docs/DESIGN.md`, `README.md` |
| software-engineer | mid; top for KA builds and the engine port | READY WPs and spikes; parallel lanes in worktrees | `src/**` (not contracts, not `web/static/`), `web/src/**`, `web/index.html`, `web/package*.json`, `web/vite.config.js`, `requirements.txt`, `run.ps1`, `config/config.yaml`, `config/rules.yaml`, `config/applicant.example.yaml`, `.env.example` |
| tester | mid; top for golden/oracle design | Test plans (stage C), ported cloud tests, golden tests, defect pins | `tests/**`, `web/tests/**` |
| reviewer | mid; top for KA and gate reviews | Before merging KA lanes; at milestone gates | `docs/reviews/**` |

Every role may also write its own `comms/outbox/<role>.md`.

**Shared-file exceptions** (the only places two roles may write): none. The engineer owns `src/jobscraper/store.py` and `cli.py`; when two lanes both need them, each lane adds its own self-contained block (new tables/methods at the end of `store.py`'s class, one new CLI verb function) and the Coordinator resolves the textual merge.
**Protected** (no agent writes here, the Coordinator included): `.env`, `.env.local`, `data/**`, `config/watchlist.yaml`, `config/profile.overrides.yaml` (the owner's files).

## 3. Scope rules

- An agent writes **only** inside its scope. Reading anything is allowed.
- Need a change outside your scope? Write a `request` in **your own** outbox (§5), mention it in your reply, and continue with independent work. The Coordinator routes it.
- Enforcement: (a) each agent definition limits its tools; (b) `.claude/hooks/scope_guard.py` blocks Edit and Write outside the role's scope; (c) the Coordinator reviews diffs.
- Shell commands bypass (b), so **never write outside your scope with the shell.**
- Spawn named roles (`subagent_type: <role>`). If a named role isn't loadable yet (new definitions load at the next session), use `general-purpose` with the role file's text as the brief.

## 4. Spawning rules (token discipline)

1. First ask: can the Coordinator do this in a few tool calls without writing code? If yes, do it directly.
2. Spawn the **minimum** set. Usual feature sequence: architect (only if contracts change) → engineer → reviewer, with the tester per the testing profile.
3. **Reuse** a running or recent agent with SendMessage instead of a fresh one.
4. **Prefer parallel engineer lanes** for READY WPs with disjoint files (`run_in_background: true`, `isolation: "worktree"`, own branch).
5. At most **4** agents at once, reviewers included (at most **3** engineer lanes). A subagent doesn't spawn agents.
6. Every delegation states a budget. Never spawn an agent to "double-check" without a specific hypothesis.

## 5. Communication protocol

- **Primary channel:** the delegation prompt, the agent's final reply (≤ 15 lines) and SendMessage.
- **Persistent channel:** each role appends to its own `comms/outbox/<role>.md`:

```
### <YYYY-MM-DD> <role> → <recipient role | coordinator>
TYPE: handoff | request | question | blocker | review
RE: <requirement IDs / paths>
BODY: <concise message>
STATUS: open | resolved (by <role>, <date>)
```

- Handoffs: Engineer → Coordinator: "ready", branch and commit hash, what changed, how to run it. Tester → Engineer: defects with a reproduction. Engineer → Architect: contract change request.
- The owner is contacted only through the Coordinator.

## 6. Approval gates and autonomy

**Autonomy (D-01):** the Coordinator decides routine matters, records them, merges into `personal` and pushes it (D-62).

The owner approves: any change to `01_scope_and_goals.md` or the PRD's scope; new roles; paid services; anything destructive to the owner's data (`data/`, the live DB); real job submissions and real account creation during development; force-pushes and history rewrites.

The Coordinator never changes its own permission settings.

## 7. Owner tasks vs agent tasks

Agents never create accounts, enter the owner's credentials, sign in to the owner's Microsoft or Google account, pay, or submit an application on a real employer site. For each such step the agent prepares exact instructions and the config that reads the result (Credential Manager entry names, `data/applicant.yaml` fields), and the Coordinator lists it under "Waiting on the owner" in the handover note. **The product itself** creating accounts and submitting applications is the feature; it runs only when the owner starts it.
