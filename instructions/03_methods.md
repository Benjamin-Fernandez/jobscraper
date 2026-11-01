# 03: Methods

## 1. Prompt enhancement (every owner prompt)

The `UserPromptSubmit` hook reminds the Coordinator. Before acting, turn the raw prompt into an **enhanced prompt**:

1. **Goal:** what the owner actually wants, in one sentence, and the outcome it serves.
2. **Scope and owner:** which requirement IDs and milestone it touches, and which role(s) own the work.
3. **Context:** the files, docs and earlier decisions that must be read (paths and D-numbers).
4. **Constraints:** write scopes, approval gates, hard limits, and the budget (tokens, agents, test time).
5. **Deliverable:** exact output (paths, structure, length).
6. **Acceptance criteria:** how we will know it is done and correct.
7. **Ambiguities:** ask the owner only if an ambiguity truly blocks; otherwise state the assumption.

Show the owner a compact **Enhanced prompt** block (≤ 7 lines) for non-trivial requests, and a one-line restatement for trivial ones. Then act on the enhanced prompt.

**Inside the app**, every prompt sent to Qwen goes through one builder per task (judge, tailor rewrite, JD terms, answer resolution, free text). Each builder attaches only the context the task needs, states the output as an Ollama JSON schema, and adds the guardrails: no invented facts, choose only among offered options, say `UNKNOWN` when the data doesn't answer it. Code then checks the output (grounding check) before it is used.

## 2. Delegation template (Coordinator → subagent)

```
ROLE: <role>. You may only write: <paths>
GOAL: <one sentence>
CONTEXT TO READ: <paths and sections only, not "everything">
TASK: <numbered steps>
BRANCH: <role>/<queue-id>-<slug> (worktree + background for parallel lanes; "none" for read-only work)
SKILLS: <skills to load from §8, or "none">
CONSTRAINTS: <scope; hard limits; budget, e.g. "≤ 20 web searches", "≤ 5 min of tests", "touch ≤ 8 files">
DELIVERABLE: <file paths and their structure>
ACCEPTANCE CRITERIA: <checklist, including the Verify: command>
REPORT BACK (≤ 15 lines): status (done | blocked | needs-fix), branch and last commit hash, files written, evidence (command + summary line), open issues, next step. Log requests and handoffs in comms/outbox/<role>.md.
```

## 3. Engineering approach

- **Contracts first.** The architect writes `src/jobscraper/apply/contracts.py` and `src/jobscraper/tailor/contracts.py` (dataclasses, enums, Protocols) before lanes build. Modules depend on contracts, never on each other's internals.
- **Plug-in points:** one adapter per ATS (`apply/ats/<name>.py`) behind the `AtsAdapter` protocol; question synonyms in `config/questions.yaml`; term variants in `config/aliases.yaml`.
- **Config over code** for domain knowledge; personal values only in `data/` (gitignored).
- **Deterministic core, probabilistic edge.** Code decides facts; Qwen rewords and picks among options; code checks every LLM output.
- **Follow the surrounding code:** module docstrings that explain *why*, PRD references in comments, `store.py` as the only SQL, `backends.py` as the only model I/O, new CLI verbs as self-contained functions in `cli.py`, background work as `web/jobs.py` job kinds.
- **Small, focused changes.** Keep the tree runnable after every edit (create a module before registering it).
- **Secrets** live in Windows Credential Manager (`keyring`) or `.env` (gitignored, never read by agents); `.env.example` documents them.
- **Architecture changes** get an ADR (`docs/architecture/adr/NNNN-title.md`).
- **Stack:** Python 3.12 (system), FastAPI + uvicorn, SQLite, httpx, PyYAML, pypdf, python-docx, Ollama/Qwen3-14B; new: playwright (Edge channel), keyring, pywin32; Vue 3 + Vite 7 + Vitest.

## 3a. Git workflow

- **`personal` is the integration branch and is always runnable** (the owner's live app runs from it). Only the Coordinator commits to it directly (instructions, status, handover, built SPA bundle) and only the Coordinator merges into it. `master` is the old public line: never commit there.
- **One branch per work item or lane:** `<role>/<queue-id>-<slug>` (e.g. `eng/Q-04-engine-port`), branched from current `personal`.
- **Commit early and often:** one commit per verified step, at least one per finished WP, and always before handoff or stopping. Conventional Commits with the queue or requirement ID (`feat(apply): greenhouse plan (Q-14, F-31)`). Never commit secrets, `.env`, anything under `data/`, screenshots or generated files.
- **Parallel engineers are the default for independent READY work:** each lane is spawned with `isolation: "worktree"` and `run_in_background: true`, on its own branch and disjoint files, within the agent cap (`04` §4).
- **Merging:** the Coordinator reviews `git diff personal...<branch>`, runs the WP's `Verify:` on the branch, merges with `git merge --no-ff`, rebuilds the SPA bundle in the main checkout if `web/src` changed, re-runs the smoke check on `personal`, then deletes the branch and worktree.
- **Conflicts:** trivial ones (lists, imports) the Coordinator resolves; logic conflicts go back to the owning lane, which updates its branch from `personal` and re-verifies.
- **Never:** force-push, amend or rebase pushed commits, rewrite `personal`'s history, `--no-verify`, or delete an unmerged branch without the owner.
- **Pushes:** the Coordinator may push `personal` to `origin` after a verified merge (D-62). Before each push, `git diff origin/personal..personal --stat` is checked for anything under `data/` or personal files.
- **Session end:** commit status, queue and handover on `personal`; the handover lists open branches and worktrees.

## 4. Testing profile: product first

The priority order is: a usable product, then working in real use, then new capability, then improvements, then testing depth.
- Before handoff an engineer runs a **smoke check** (what was built starts and does its main job once), the existing tests for the touched area (`python tests/run_tests.py -k <area>`, `npx vitest run <file>`), and keeps the full suite green when the lane touches shared code.
- The tester is spawned when (a) real use breaks something (reproduce, pin, fix, then test that area), (b) a safety rule or critical behaviour changes, or (c) ported cloud tests need bringing over.
- **Always kept:** golden tests for the tailor's truthfulness validator (cases A–C), the resolver's declaration rules, duplicate-submission guards and the NF-01 gitignore check; no live network calls in tests (recorded fixtures; a local static HTML page per ATS form for browser tests); no secrets in the tree; a pin for each defect.
- **Real employer sites:** agents may *read* public postings and fill forms in **dry-run** mode during spikes, never click Submit or create accounts. Real submissions happen only when the owner triggers them.

**Budgets:** engineer ≤ 5 min of test runtime before handoff (the full Python suite takes ~2 min); tester ≤ 30 min per batch; the full suites once per milestone gate. When a budget runs out, stop and report what is and isn't covered.

## 5. Evidence and definition of done

A work item is **done** when: the code matches the WP and the design; its `Verify:` command passes and the output is quoted; the changed files have no new warnings; the testing profile's checks pass; no secrets or personal data were added and nothing outside scope was touched; docs and status are updated; the reviewer has passed it (key areas and milestone gates); the architect has signed off if a contract changed.

Evidence is the command plus its summary line, or a screenshot for UI.

## 6. Research and evidence standards

Every external claim carries a URL and a date. Mark unverified items. Keep fact, inference and opinion separate. Prefer primary sources. Respect terms of service, robots.txt and rate limits.

## 7. Writing for the reader

The owner reads the docs: plain words, jargon explained on first use (PRD §11 glossary). Keep instruction files short; put history in logs.

## 8. Skills to use (installed ones only)

- github-gem-seeker: stage A / new adapters — prior art before designing — researcher
- anthropic-skills:deep-research: stage A — multi-source questions (ToS, ATS behaviour) — researcher
- engineering:system-design: stage B — components, contracts, data model — architect
- engineering:architecture: stage B — each significant choice as an ADR — architect
- engineering:testing-strategy: stage C — the area's lean test plan — tester
- engineering:documentation: README, OVERVIEW, user guide — planner
- engineering:debug: something breaks in real use or a build — software-engineer
- desktop-commander:terminal: background dev servers, ports, PowerShell quirks — software-engineer
- engineering:code-review: stage G, before merging key-area lanes and at gates — reviewer
- design:design-critique, design:accessibility-review: before a UI milestone closes — reviewer
- design:ux-copy: button labels, failure reasons, empty states — architect (UI design)
- engineering:tech-debt: milestone retrospective — Coordinator / architect
- engineering:standup: session-log entry — Coordinator
