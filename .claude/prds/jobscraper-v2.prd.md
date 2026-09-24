# JobScraper v2 — Product Requirements & Build Specification

**Status:** ACTIVE — in implementation, parallel lanes (§0.6)
**Created:** 2026-09-23
**Supersedes:** the v1 pipeline described in `docs/DESIGN.md`
**Owner:** Benjamin (single user, personal job search)

---

## 0. How to use this document

> **Read this section first, every session. It is the contract that lets a fresh
> agent continue without any memory of previous sessions.**

### 0.1 The resumption protocol

0. Read **§0.5 (State of play)** first. It records live on-disk state and two
   correctness landmines that the ledger does not surface.
1. Read **§0.6 (Parallel lanes)** and identify which lane you are. Then read §10
   (Build Ledger) and find the first task **in your lane** whose `STATUS` is not
   `DONE`. If you were not told a lane, you are the Lead (Lane A).
2. **Do not trust the flag. Verify it.** Every task carries a `Verify:` command.
   Run it. If it passes, the task is actually done — set the flag to `DONE` and
   move on. If it fails, the task is not done regardless of what the flag says.
3. Do the task. Only that task. Tasks are sized for one sitting.
4. When it passes its `Verify:` command, edit this file: set `STATUS: DONE` and
   fill in `Completed:` with the date.
5. Run the full test suite before finishing (`python tests/run_tests.py`).

### 0.2 Status vocabulary

| Flag | Meaning |
|---|---|
| `NOT_STARTED` | No work done. |
| `IN_PROGRESS` | Partially done. The task's `Notes:` line says exactly where it stopped. |
| `DONE` | Complete **and** its `Verify:` command passes. |
| `BLOCKED` | Cannot proceed. `Notes:` states what is blocking and who must unblock it. |
| `REUSE` | Already exists from v1 and is being carried over unchanged. Do not rewrite. |

### 0.3 Rules for the implementing agent

- **Never** mark a task `DONE` without running its `Verify:` command.
- **Never** delete v1 files until the milestone that explicitly retires them (M9).
  Archive instead (`git mv` or move to `archive/`).
- If a task turns out to be wrong or impossible, set `BLOCKED`, write why in
  `Notes:`, and stop. Do not improvise a different design.
- Prefer extending the modules listed in §9 over writing new ones.
- Every new module gets a module docstring explaining *why it exists*, matching
  the house style already in `src/jobscraper/`.

### 0.4 Use the ECC toolkit

This repo has the ECC skill/agent bundle installed. **Use it — it measurably
improves the build.** Invoke a skill with the `Skill` tool, an agent with the
`Agent` tool. Do not hand-roll what a listed tool already does.

| When you are… | Use | Why |
|---|---|---|
| Starting any milestone | `/ecc:plan` | Restates requirements and risks, then waits for confirmation before touching code |
| Writing a new module | `/ecc:tdd-workflow` or `ecc:tdd-guide` | This PRD is test-anchored; every task has a `Verify:` |
| Finishing a Python task | `/ecc:python-review` | Catches type-hint, security and idiom problems before they compound |
| Finishing a web task | `/ecc:vue-review`, `/ecc:fastapi-review` | Covers reactivity pitfalls, async correctness, DI, OpenAPI quality |
| A build or type error blocks you | `/ecc:build-fix` | Minimal-diff resolution instead of architectural drift |
| Touching the SQLite schema (§8.4) | `ecc:database-reviewer` | Migration safety and query correctness |
| Anything writes user data or opens a port | `/ecc:security-review` | The web app binds a socket; the pipeline writes files |
| Reviewing a finished milestone | `/ecc:code-review` | Diff-scoped correctness pass |
| Adding coverage after a milestone | `/ecc:test-coverage` | Finds the gaps the `Verify:` command misses |
| Unsure how a v1 module works | `ecc:code-explorer` | Traces execution paths before you change them |
| The API/docs feel stale after a change | `/ecc:update-docs`, `/ecc:update-codemaps` | Keeps §8 and the README true |

**Rules for tool use:** run the reviewer *for the language you just wrote*, not all
of them. Treat reviewer findings as advice, not orders — if a finding contradicts
this PRD, the PRD wins and you note the disagreement in the task's `Notes:`.
Within a task, do not spawn subagents for work you can do inline; a task sized
for one sitting rarely needs one. Parallelism happens **between lanes** (§0.6),
under its 4-agent cap — not inside a task.

### 0.5 State of play — read before touching anything

*Last updated: 2026-09-24, after the first parallel-lane wave (§0.6). On-disk
fact, verified at handoff.*

**Where things stand:** 31/40 tasks `DONE`; **191/191 Python tests, 26/26
Vitest** green on `v2-rebuild`. Lanes B (filter), C (web) and D (profile) are
merged and their worktrees removed; only the main checkout remains. The
pipeline is end to end: `python -m jobscraper run` syncs the watchlist,
schedules, scrapes, prefilters, hydrates survivors, extracts, decides via
`claude -p` and writes `data/shortlist.json`; `python -m jobscraper web` serves
Inbox + Applications on 127.0.0.1:8765. `data/jobscraper.db` is the v2 schema
holding 229 companies, **no scraped jobs yet**, and the 3 migrated v1
applications. `data/profile.derived.yaml` was generated from the real resume.

**Not yet on GitHub.** `gh` is installed (`C:\Program Files\GitHub CLI`) but
the user has not run `gh auth login`, so there is no `origin`. Everything is
committed locally. Once authenticated:
`gh repo create jobscraper --public --source . --remote origin` then
`git push -u origin master v2-rebuild` (the user chose **public**; `data/`,
`archive/` and resumes are git-ignored).

**Remaining, in order:** M1-T5 (watchlist verbs) and M8-T2 (status vocabulary)
are small and independent — a good pair for two lanes. **M4-T4 is the first real
run**: it spends model quota and needs the user's hand audit of 30 accepted
roles, so do it with the user present. Then M9 (retire v1, README, acceptance)
and M10 (Docker), serial. M1-T3 (prune) is the user's.

**Reviews done at the merge gate:** `ecc:python-reviewer` (no critical findings;
three fixed, one declined — `job_id` includes the provider, but an ATS
migration brings new external ids anyway, so closing the old board's postings
is correct and applications re-link by URL) and `ecc:database-reviewer` (four
fixed; foreign keys deferred — orphaned applications are allowed by design,
SQLite cannot add constraints to existing tables, and they belong with the
Postgres port).

#### Two landmines

**1. ~~`cli.py::_sync` is a bridge that reintroduces the exact bug §8.4 prevents.~~
RESOLVED 2026-09-24 by M3-T1b** — `_sync` is gone; sync keys on `key`. Kept below for history.
M1-T4 removed the Excel workbook from the config, which broke `cfg.input_workbook`
and with it `doctor`, `sync`, `resolve` and `run`. `_sync` was repointed at the
watchlist to keep them alive — but it still routes through **v1's
`sync_companies`, which keys rows on the display name**. So today, renaming a
company in `watchlist.yaml` silently resets its scrape history and orphans its
failure counters. The stable-`key` guarantee in §8.4 is written down but **not yet
real**. **M3-T1b is what makes it real.** Do not treat §8.4 as implemented until
that task is `DONE`.

**2. ~~`data/jobscraper.db` exists and is a v1-schema database.~~ RESOLVED
2026-09-24 by M3-T1** — archived to `archive/v2-bridge-db-2026-09-24/`; the file
at `data/jobscraper.db` is now v2. Kept below for history. Created by the
bridge sync above; it has `tier`/`category` columns and **no `last_scraped_at`**.
It is not the v2 database and holds nothing worth keeping — 224 company rows and
no jobs. **M3-T1 should delete it and create the v2 schema fresh.** Do not migrate
it. The real v1 data you may need lives at
`archive/v1-2026-09-23/data/jobscraper.db` (inputs for M1-T2, already used, and
M3-T3b, not yet).

#### Blocked on the user, not on you

- ~~**M2-T0**~~ — **resolved 2026-09-24.** The resume is at `data/resume.pdf`
  (renamed from the user's original filename so the `data/resume.*` ignore rule
  covers it; `data/*.pdf` and `data/*.docx` are now ignored as well, because the
  repo is **public**). M2 is unblocked and runs as Lane D (§0.6). It is ignored by
  git, so **a fresh worktree does not have it** — copy it in from the main checkout.
- **M1-T3** — pruning the 229 seeded companies. Non-blocking; the list works as
  seeded. Fewer companies directly eases R-7's cadence problem.

Work now proceeds in **parallel lanes** — see §0.6 for who does what.

#### Environment facts that will cost you time otherwise

- **A `GateGuard` hook intercepts every `Write`, `Edit` and first `Bash` call.**
  It refuses the call and demands you first state importers/callers, affected API,
  data schemas, and the user's verbatim instruction. Present those in the message
  *before* retrying. This is normal here, not a malfunction. It also blocks
  `git commit --amend` outright — write a follow-up commit instead.
- **Windows / PowerShell.** Every `Verify:` in the ledger is a Python or `git`
  one-liner for this reason. POSIX shell (`2>/dev/null`, `| wc -l`) does not run.
  Beware `$?` after a pipe: it reports the *last* command's status, not Python's.
- **`tests/run_tests.py -k <needle>` gates imports as well as tests.** A file that
  will not import is skipped when the needle does not name it, and fails hard when
  it does. This is deliberate — without it, `test_web.py` needing FastAPI would
  fail M3's acceptance commands. Do not "simplify" it away.
- The first commit's subject carries a stray `@` from a quoting slip. Cosmetic;
  the body is intact; amend was refused. Leave it.

#### Trust levels

- **Verified by execution:** every `DONE` task's `Verify:` command, the 49-test
  suite, the layering guard (proved non-vacuous by injecting a real violation),
  `-k` exit codes, config env overrides, and `doctor` end to end.
- **Written but never executed:** everything in M2–M10. The schema in §8.4, the
  due query in §8.3[0] and the rules contract in §8.3[3] are *designs*, not
  working code. Expect them to need adjustment on contact, and update §8 when
  they do.
- **Unmeasured assumptions:** the ≤800-char vital extract (Q5/R-1) and the share
  of postings with vague locations (D-2). Both are quantified at M4-T4. Do not
  tune the filter against a guess before then.

### 0.6 Parallel lanes — worktrees, GitHub, roles

*Added 2026-09-24. This section overrides §10's "milestones run in numeric
order" — ordering now holds **within a lane**, not across the whole ledger.*

**Why lanes at all.** Most of the ledger is one dependency chain
(store → sync → scheduler → pipeline → decide → shortlist → API). Three blocks of
work touch disjoint files and can run beside that chain without waiting on it.
Parallelism beyond that buys merge conflicts, not speed.

#### The cap: at most 4 agents at once

**Never more than 4 agents running at the same moment, reviewers included** —
one Lead plus up to three lane agents. A lane agent **never spawns agents of its
own**: it uses skills inline (`ecc:tdd-workflow`, `ecc:verification-loop`) and
leaves reviewer agents to the Lead, who runs them only when a slot is free. If
all four slots are busy, review waits; it does not squeeze in a fifth.

#### Lanes and roles

| Lane | Role | Tasks, in order | Owns (may edit) | Branch / worktree |
|---|---|---|---|---|
| **A** | **Lead & integrator.** Builds the critical chain, reviews and merges every PR, sole editor of §0.5/§0.6, decides when a lane is blocked. | M1-T5 → M3-T1 → M3-T1b → M3-T2 → M3-T3 → M3-T3b → M3-T4 → M4-T3 → M5-T1 → M4-T4. After all lanes merge: M8-T2, M9, M10 (serial). | `store.py`, `scheduler.py`, `pipeline.py`, `shortlist.py`, `watchlist.py`, `config.py`, `models.py`, `scrape/`, `cli.py`, `config/config.yaml`, `requirements.txt`, `tests/run_tests.py`, `tests/test_layering.py`, `tests/test_{store,scheduler,scrape,watchlist}.py`, `.github/`, the PRD | main checkout, `v2-rebuild` |
| **B** | **Filter.** The free prefilter and the vital extract. | M4-T2 → M4-T1 → M4-T1b (`filter test` first; `filter explain` after M3-T1 merges, since it reads the `prefilter` table). | `filter.py`, `decide.py` (`vital_extract` only — the rest of `decide.py` is Lead's M4-T3), `config/rules.yaml`, `tests/test_filter.py`, `tests/test_decide.py`, `tests/fixtures/jd_*` | `../JobScraper-lane-b`, `lane/b-filter` |
| **C** | **Web.** API and UI end to end. | M7-T1 → M7-T2 → M7-T3 (against a fixture `shortlist.json`), then M6-T1 → M6-T2 once M3-T1 merges, then M7-T4 → M8-T1. | `web/` (Vue source, `package.json`), `src/jobscraper/web/`, `tests/test_web.py` | `../JobScraper-lane-c`, `lane/c-web` |
| **D** | **Profile.** Resume → derived profile → keyword scorer. | M2-T1 → M2-T2 → M2-T3. | `src/jobscraper/profile/`, `config/profile.overrides.yaml`, `tests/test_profile.py`, `tests/fixtures/make_resume_fixture.py` | `../JobScraper-lane-d`, `lane/d-profile` |

When Lane D finishes, its slot is free: the Lead may hand it M5-T1 or M4-T4, or
leave it empty. Re-cutting lanes is a Lead decision recorded here.

#### Shared files — the only exceptions to ownership

- **`cli.py`** is the Lead's. Lanes B, C and D may each add **one** verb
  (`filter`, `web`, `profile`) as a self-contained `cmd_<verb>` function plus one
  `add_parser` block, and touch nothing else in the file. The Lead resolves any
  merge conflict.
- **`requirements.txt`** — a lane may *append* the dependencies it introduces;
  never edit or reorder other lines.
- **This PRD** — a lane edits only `STATUS`, `Completed:` and `Notes:` of **its own**
  tasks in §10. A lane that believes the design is wrong says so in its PR
  description; it does not edit §7–§9.
- **`tests/test_layering.py` is law for every lane.** A lane that needs a
  boundary changed stops and asks the Lead.

#### Interface contracts — so no lane waits on another

Stages may not import each other (§8.2); `pipeline.py` wires them. These
signatures are the seams. Build against them with stubs; do not change one
without the Lead.

1. **Profile shape** (D produces → B, A consume). A plain `dict` with the §8.3[1]
   keys: `profile_version: int`, `summary: str`, `skills: list[str]`,
   `target_titles: list[str]`, `title_aliases: dict[str, str]`,
   `years_experience: int`. D exposes
   `profile.resume_ingest.load_derived_profile(cfg) -> dict` returning derived +
   overrides already merged. B tests with a hand-written dict of this shape.
2. **Overlap scorer** (D produces → B consumes *by injection*).
   `profile.keywords.overlap(text: str, skills: list[str]) -> tuple[int, list[str]]`
   — score and the matched skills. `filter.py` never imports it; it receives it.
3. **Filter API** (B produces → A consumes in M3-T4/pipeline).
   `filter.load_rules(path) -> RuleSet` (carrying `.hash`, the §8.4 `rules_hash`)
   and `filter.evaluate(posting, ruleset, profile, scorer) -> FilterResult` where
   `posting` has `title`, `location`, `description`, and `FilterResult` has
   `passed`, `reject_rule`, `reject_detail`, `overlap_score` and a per-rule
   `trace` (which is what `filter explain` prints).
4. **Vital extract** (B produces → A consumes in M4-T3).
   `decide.vital_extract(title: str, location: str, jd_text: str, limit: int = 800) -> str`.
5. **Store API for the web** (A produces in M3-T1 → C consumes in M6).
   `Store.list_runs()`, `Store.applications()`, `Store.application_events(job_id)`,
   `Store.set_application_status(job_id, status, notes=None) -> bool`
   (returns whether an `app_events` row was appended — this is M6-T2's idempotency).
6. **Shortlist file** (A produces in M5-T1 → C consumes): exactly §8.3[6]. C builds
   the UI against a fixture of that shape until M5-T1 lands.

#### GitHub workflow

- **Remote:** `origin` (see the README for the URL). The repo is **public** — nothing
  from `data/` or `archive/` is ever committed. `master` = v1 restore point, never
  pushed to. **`v2-rebuild` = the integration branch; every PR targets it.**
- **Open a lane** (PowerShell, from the main checkout):
  ```powershell
  git fetch origin
  git worktree add ..\JobScraper-lane-b -b lane/b-filter origin/v2-rebuild
  ```
  Git-ignored inputs are **not** in a new worktree. Lane D copies
  `data\resume.pdf` in from the main checkout; `archive\` stays with the Lead.
- **Start the lane agent** — a new Claude Code session opened *in the worktree
  folder* (desktop app: new session → that folder; terminal: `cd` there, run
  `claude`), with this kickoff prompt:
  > You are **Lane B** of `.claude/prds/jobscraper-v2.prd.md`. Read §0 in full,
  > then work your lane's tasks per §0.1 and §0.6. Edit only files your lane owns.
  > Do not spawn agents. Open a PR to `v2-rebuild` when a coherent chunk is done.
- **Per task:** the §0.1 protocol, then one commit named `M4-T2: <what>`. Run the
  **full** suite (`python tests/run_tests.py`) before every push, not just `-k`.
- **Pick up others' work:** `git fetch origin; git merge origin/v2-rebuild`. Merge,
  never rebase a pushed branch; never force-push.
- **Hand in:** `git push -u origin lane/b-filter`, then
  `gh pr create --base v2-rebuild`, with a body listing each task done, its
  `Verify:` output, and anything the Lead must know. One PR per coherent chunk.
- **Merge gate (Lead):** (1) CI green — `.github/workflows/tests.yml` runs the full
  suite on every PR; (2) each task's `Verify:` re-run on the PR branch; (3)
  `git diff --name-only origin/v2-rebuild...HEAD` lists only files the lane owns,
  plus the exceptions above; (4) a `/code-review` pass on the diff. Then
  `gh pr merge --merge`, and update §0.5.
- **Close a lane:** after its last PR merges, `git worktree remove ..\JobScraper-lane-b`.
- **Stop conditions for a lane agent:** its tasks are done, or it is `BLOCKED`
  (§0.3), or it is waiting on a contract above that has not merged yet. In all
  three cases: push, open or update the PR, say which, and stop. Never work
  around a missing dependency by writing into another lane's files.

#### ECC skills for orchestrating this

| When | Skill | Who |
|---|---|---|
| Re-cutting lanes, deciding what may run in parallel | `ecc:parallel-execution-optimizer` | Lead |
| Lane contracts, ownership, board state, merge gates | `ecc:team-agent-orchestration` | Lead |
| Branch, worktree and commit conventions | `ecc:git-workflow` | All |
| PRs, `gh`, reviewing and merging | `ecc:github-ops` | All |
| Proving a chunk before opening its PR | `ecc:verification-loop` | Lanes |
| Building each task test-first | `ecc:tdd-workflow` | Lanes |
| The merge-gate review of a PR diff | `/code-review` or `/ecc:code-review` | Lead |
| Stack reviews at merge (spawn agents → count toward the cap) | `/ecc:python-review` (A, B, D), `/ecc:fastapi-review` + `/ecc:vue-review` (C), `ecc:database-reviewer` (M3) | Lead |
| Snapshot before a risky merge | `/ecc:checkpoint` | Lead |
| Handing a lane to a fresh session | `/ecc:save-session`, `/ecc:resume-session` | All |

**Not recommended here:** `ecc:dmux-workflows` (needs tmux, i.e. WSL on this
Windows machine), `ecc:claude-devfleet` (needs its own server running), the
`ecc:epic-*` family (GitHub-issue coordination: more ceremony than four lanes
need; worth it only if the lane count grows), and the `multi-*`/`gan-*` families
(multi-model loops; this project uses one cheap model by design).

---

## 1. Problem

The v1 app works but three things make it unpleasant to live with. The company
list is a 9-column, 3-sheet Excel workbook carrying tiering, categories and
application-status columns that duplicate state the app also keeps — so adding a
company means editing a spreadsheet and the two sources of truth drift. Every run
writes another HTML file (`matches_run1..9.html`, plus `all_matches.html` and
`latest_matches.html`), so reviewing results means hunting through a folder of
near-identical pages. And the matching funnel was designed around a paid API with
tier-based model routing, second opinions and 3,000-character prompts per
posting — expensive machinery for a decision that only needs three facts.

Left unsolved: the watchlist stays hard to extend, the output folder keeps
growing, and every run costs far more tokens than the decision warrants.

## 2. Evidence

- **Observed, this repo.** `data/job_tracker_04_2026.xlsx` has 3 sheets, of which
  `Job Tracker` and `May26` are byte-identical 230-row duplicates, plus a
  `Legend` sheet explaining a tier taxonomy. Columns `Status`, `Date Applied` and
  `Notes` duplicate the `applications` table in SQLite.
- **Observed, this repo.** `output/` holds 11 HTML files across 9 runs. The user
  had `latest_matches.html` open showing 0 matches while 55 matches from the
  previous run sat in a different file.
- **Measured, 2026-09-23.** A 3-posting judging probe sent ~15k input tokens per
  call and took ~60s/call, because the prompt carried 2,500–3,000 characters of
  job-description boilerplate per posting ("Entrepreneur Magazine's Top Company
  Cultures list…") to decide questions answerable from a location line.
- **Measured, 2026-09-23.** Of 5 postings reviewed by hand, 2 were rejected purely
  on location (Cloudflare roles listing only US/EU offices) — postings the rules
  layer had already exported to the tracker.
- **Assumption — needs validation via first live run.** That a ≤800-character
  vital extract preserves decision quality versus the full JD. Measured in M4-T4.

## 3. Users

- **Primary:** one final-year NTU Computer Engineering student, graduating August
  2026, searching for new-graduate backend/infrastructure roles **in Singapore**.
  Triggered fortnightly, when a scrape cycle completes and there are new postings
  to triage and apply to.
- **Not for:** multi-user deployment, recruiters, non-Singapore searches, or
  anyone needing an audit trail beyond their own application history.

## 4. Hypothesis

We believe **a hand-editable watchlist, a hard local prefilter feeding a single
cheap model a minimal extract, and one persistent web page** will **cut the cost
and noise of each run while making the whole thing pleasant to operate** for
**a single job-seeker running it fortnightly**.

We'll know we're right when **a full cycle costs under 15% of v1's tokens, every
accepted role is genuinely Singapore-based, and adding a company is a two-line edit.**

## 5. Success Metrics

| Metric | Target | How measured |
|---|---|---|
| Tokens per posting reaching the model | ≤ 2,000 input (v1: ~15,000) | `runs.stats_json` ledger ÷ postings judged |
| Postings reaching the model | ≤ 10% of new postings | Prefilter survivor count ÷ new count, per run |
| Location precision | 100% of accepted roles are Singapore | Manual audit of first 30 accepted |
| Adding a company | ≤ 2 lines, no code change | Edit `watchlist.yaml`, run `doctor` |
| HTML artifacts in `output/` | 0 generated per run | `ls output/*.html` after a run |
| Time to triage a run | Single page, no file hunting | Observation |
| Staleness of the oldest company | ≤ 14 days **at ≥1.6 runs/day**; otherwise surfaced, never silent | `status` report, §8.3[0]. See R-7 — below that rate the tail legitimately exceeds 14 days and the metric is "is it visible", not "is it ≤14" |
| Spin-up from clone | 1 command | `docker compose up` → reachable on :8765 |
| Adding a filter rule | Config only, no code | Add an `extra:` entry, confirm via `filter test` |

## 6. Scope

### MVP

The vertical slice that tests the hypothesis end to end:

1. `config/watchlist.yaml` — seeded with all 229 v1 companies (D-4); name + careers
   URL required, everything else optional.
2. Staleness scheduler — 10 companies per run, 14-day window, per-company
   timestamps (D-9, D-13).
3. Resume ingest from `data/resume.pdf` (or `.docx`), re-run only when the file
   changes; emits `skills` **and** `target_titles` (D-10).
4. Local keyword/skill engine derived from the resume.
5. Scrape via the existing adapters, unchanged.
6. Hard local prefilter — declarative, reorderable, user-extensible rules
   (title deny, title allow, location, 3-year cap, keyword floor) plus
   `filter explain` / `filter test` for tuning.
7. Vital extract → single cheap model → binary accept/reject, with location and
   experience enforced in code.
8. `data/shortlist.json` — the accepted queue, with URLs.
9. One web page: Inbox tab (scroll, open, apply) + Applications tab (mark status).
10. `docker compose up` spin-up, with the no-Docker path preserved.

### Out of scope

| Item | Why deferred |
|---|---|
| Tiering, categories, category priors | The user asked for them gone. Model routing goes with them. |
| Second opinions / `contested` verdicts | Single cheap model only. |
| Excel outputs (`application_tracker.xlsx`, `run_tracker.xlsx`) | Replaced by the web app and SQLite. |
| Multi-user, auth, hosting | Local single-user tool. |
| Email/push notifications | Not requested. |
| Résumé tailoring or cover letters | Not requested. |
| Stats/analytics tab | Tab shell must *support* it (§8.5); content is post-MVP. |
| Migrating v1 job data | User chose a clean slate (§7, D-4). |

---

## 7. Decision Register

Decisions that shape the build. An agent must not silently reverse these.

| # | Decision | Rationale | Consequence |
|---|---|---|---|
| **D-1** | Resume arrives as **PDF or DOCX** in `data/`, parsed on hash change only | User choice. Keeps the resume the single source of profile truth. | Adds `pypdf` + `python-docx`. Parse runs ~never, so cost is irrelevant. |
| **D-2** | Vague/blank location → **send to the model** to read the description | User choice. Rejecting unstated locations outright would lose real Singapore roles, since ATS feeds routinely leave the field blank. *(The share of blank/vague locations is **unmeasured** — quantify it at M4-T4 from the `prefilter` table before tuning this.)* | Slightly more model calls than a hard reject. Explicit non-SG is still rejected free. |
| **D-3** | Web = **FastAPI + Vue 3 + Vite** | User chose FastAPI + a JS framework. Vue picked over React: single-file components read more like HTML for a human reviewer, and no extra state library is needed at this size. | Adds a node build step to a Python repo. React is a drop-in swap if preferred — only §8.5 changes. |
| **D-4** | **Seed the watchlist with all 229 v1 companies**, carrying their resolved `provider`/`slug`/`feed_url`. Job/decision data still starts clean. | *Revised 2026-09-23 — supersedes the earlier "clean slate" choice.* All 229 have a resolved provider and careers URL; discarding that means re-paying for a full discovery crawl. | M1-T2 generates `watchlist.yaml` from the v1 DB. The user prunes rather than builds from nothing. Old jobs/verdicts are **not** carried over. |
| **D-5** | `shortlist.json` is **engine-owned and disposable**; application status lives **only in SQLite** | Avoids two writers on one file. The engine regenerates the shortlist freely; user state is never in a regenerated file. | Web app joins the two at read time. |
| **D-6** | **One** model tier (cheapest), reached via the existing Claude Code CLI backend | No API key exists. Tier routing was tied to the tiering being deleted. | `backends.py` carries over unchanged. `model_high`/`model_low` collapse to `model`. |
| **D-7** | Singapore means **explicitly Singapore**. Remote — including "Remote (APAC)" and "Remote, Global" — is rejected. | User: "singapore only, not even remote". | A location allow-list of exactly `singapore`/`sg`. The v1 `ambiguous_hints` escape hatch is deleted. |
| **D-8** | Prefilter is **hard and free**; the model is the last step, never the first | Cost control. A posting the rules can reject must never reach the model. | Order in §8.3 is normative, not advisory. |
| **D-9** | Scheduling is **per-company staleness**, not a global cursor. A company is due when `last_scraped_at` is null or older than `cycle_days`. | User: decide whether to loop back to company 1 "based on whether it has been scraped within the past 2 weeks". A cursor cannot express that; a timestamp can. | `cursor.py` retires. Self-healing: failures, additions and removals all resolve naturally. See §8.3[0]. |
| **D-10** | The resume parser emits **`target_titles`**, used as a positive title filter alongside the deny-list. | User request. A generated allow-list catches "Site Reliability Engineer" without hand-maintaining every variant. | New `title_allow` prefilter rule. Generated list is merged with a user `extra:` list that is never overwritten (§8.4). |
| **D-11** | **Docker packages the app**; the model transport is the one thing Docker cannot carry. | User wants easy spin-up and eventual cloud. But `claude -p` authenticates against the host's Claude Code login, which does not exist inside a container. | Local: mount `~/.claude` read-only. Cloud (later): needs an API key or a hosted transport. **Called out as Risk R-8 — do not discover this at deploy time.** |
| **D-12** | Experience hard cap: **reject anything requiring > 3 years**. | User instruction. | `ceiling_years: 3` in `config/rules.yaml`. Applies in the free prefilter *and* as a post-condition on the model's `yoe_min`. |
| **D-13** | Batch size **10 companies per run** to start. | User instruction. v1 used 30. | See R-7: at 229 companies this needs ~1.6 runs/day to complete a 14-day cycle, where 30 needed ~0.5. The staleness queue degrades gracefully if that is not met, and the value is one config line. |
| **D-14** | **Migrate v1 `applications` history.** Jobs and decisions still start clean. | The user's own application record is the one thing in the v1 DB that cannot be regenerated by re-scraping. "Migrating v1 job data is out of scope" (§6) was never meant to cover it. | M3-T3 ports the `applications` rows, matching on job URL. Rows whose job is not re-scraped are kept as orphans with their URL, so nothing the user recorded is lost. |
| **D-15** | **`git init` the repo before M0.** | There is no `.git` here (verified 2026-09-23). §0.3's "archive, never delete" and M7-T4's "the diff touches exactly 3 files" both assume version control. | M0-T0. Without it, a multi-day agent-driven rebuild has no undo. |

---

## 8. System Design

### 8.1 High-level flow

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  A. ON CHANGE ONLY                                                           ║
║                                                                              ║
║   data/resume.pdf ──▶ ┌───────────────────┐ ──▶ data/profile.derived.yaml    ║
║   (you drop it in)    │ [1] Resume Ingest │     skills · titles · yoe        ║
║                       └───────────────────┘                                  ║
║                        skipped unless the file hash changed                  ║
╚══════════════════════════════════════════════════════════════════════════════╝
                                      │
                                      ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║  B. EVERY RUN            config/watchlist.yaml   ← you edit: name + url       ║
║                                      │                                       ║
║                                      ▼                                       ║
║   ┌────────────────────────────────────────────────────────────────────┐     ║
║   │ [0] SCHEDULER  — who is due?                           FREE        │     ║
║   │                                                                    │     ║
║   │     SELECT … WHERE last_scraped_at IS NULL                         │     ║
║   │                 OR last_scraped_at <= now - 14 days                │     ║
║   │     ORDER BY never-scraped first, then oldest      LIMIT 10        │     ║
║   │                                                                    │     ║
║   │     ↳ nobody due  ▸ print when the next one is, exit 0             │     ║
║   │     ↳ "loop back to company 1" happens by itself: it becomes       │     ║
║   │       the oldest row 14 days after its own last scrape             │     ║
║   └────────────────────────────────────────────────────────────────────┘     ║
║                                      │  ≤10 due companies                    ║
║                                      ▼                                       ║
║   ┌────────────────────────────────────────────────────────────────────┐     ║
║   │ [2] SCRAPE                                             FREE        │     ║
║   │     resolve ATS ▸ fetch listings ▸ drop already-seen job ids        │     ║
║   │     ▸ stamp companies.last_scraped_at = now (attempt, not success) │     ║
║   └────────────────────────────────────────────────────────────────────┘     ║
║                                      │  new postings                         ║
║                                      ▼                                       ║
║   ┌────────────────────────────────────────────────────────────────────┐     ║
║   │ [3] LOCAL PREFILTER                                    FREE        │     ║
║   │     ✗ title on deny-list (senior/staff/lead/intern/non-eng)        │     ║
║   │     ✗ location explicitly outside Singapore  (incl. all Remote)    │     ║
║   │     ✗ "N+ years" above ceiling                                     │     ║
║   │     ✗ keyword overlap below floor                                  │     ║
║   │     → target: ≤10% survive                                         │     ║
║   └────────────────────────────────────────────────────────────────────┘     ║
║                                      │  survivors                            ║
║                                      ▼                                       ║
║   ┌────────────────────────────────────────────────────────────────────┐     ║
║   │ [4] VITAL EXTRACT                                      FREE        │     ║
║   │     location line + experience/qualification block                 │     ║
║   │     + responsibilities head          ────────▶  ≤ 800 chars        │     ║
║   │     (discards culture copy, benefits, EEO boilerplate)             │     ║
║   └────────────────────────────────────────────────────────────────────┘     ║
║                                      │                                       ║
║                                      ▼                                       ║
║   ┌────────────────────────────────────────────────────────────────────┐     ║
║   │ [5] DECIDE                                    CHEAP MODEL          │     ║
║   │     cheapest model via `claude -p`, batched ~20 postings/call      │     ║
║   │     ──▶ { accept | reject , is_singapore , yoe_min , reason }      │     ║
║   │     cached by hash(job_id + vital_text + profile_version)          │     ║
║   └────────────────────────────────────────────────────────────────────┘     ║
║                                      │  accepted                             ║
║                                      ▼                                       ║
║   ┌────────────────────────────────────────────────────────────────────┐     ║
║   │ [6] SHORTLIST  ──▶  data/shortlist.json   { id, url, why, run }    │     ║
║   └────────────────────────────────────────────────────────────────────┘     ║
╚══════════════════════════════════════════════════════════════════════════════╝
                                      │
                                      ▼
╔══════════════════════════════════════════════════════════════════════════════╗
║  C. ANY TIME        [7] WEB APP        http://localhost:8765                  ║
║                                                                              ║
║    data/shortlist.json ──┐                                                   ║
║      (the queue)         ├──▶ FastAPI ──▶ Vue SPA  (ONE page, tabs)          ║
║    data/jobscraper.db ───┘    /api/*          ┌──────────┬────────────────┐  ║
║      (your status)                            │  INBOX   │  APPLICATIONS  │  ║
║                                               │  scroll  │  status +      │  ║
║                               ▲               │  open ↗  │  history       │  ║
║                               │               └──────────┴────────────────┘  ║
║                               └─── POST /api/applications ◀────┘             ║
║                                                                              ║
║    Run selector ▼ [ run 12 · 23 Sep · 41 roles ]  ← same page, new run       ║
╚══════════════════════════════════════════════════════════════════════════════╝
```

### 8.2 Module map

Arrows are "depends on". Nothing below a layer may import from above it.

```
        ┌──────────────────────────────────────────────────┐
  CLI   │  cli.py        run · doctor · web · watchlist     │
        └───────┬──────────────────────────┬───────────────┘
                │                          │
        ┌───────▼──────────┐       ┌───────▼───────────────┐
 ORCH   │  pipeline.py     │       │  web/api.py  (FastAPI)│
        │  orchestrates    │       │  + web/ui  (Vue SPA)  │
        │  stages 0→6      │       └───────┬───────────────┘
        └───────┬──────────┘               │
                │                          │
  ┌─────────┬───┴────────┬─────────────┬───┼──────────┬─────────────┐
  │         │            │             │   │          │             │
┌─▼───────┐┌▼─────────┐┌─▼────────┐┌───▼───▼──┐┌──────▼───┐┌────────▼───────┐
│schedule ││ scrape/  ││filter.py ││decide.py ││shortlist ││ profile/       │
│r.py     ││ adapters ││ prefilter││vital ext.││.py       ││ resume_ingest  │
│who's due││ discovery││ (free)   ││+ model   ││          ││ keywords.py    │
└─┬───────┘└┬─────────┘└─┬────────┘└───┬──────┘└──────┬───┘└────────┬───────┘
  │         │            │             │              │             │
  └─────────┴────────────┴─────────────┴──────────────┴─────────────┘
                               │
                    ┌──────────▼───────────┐
   FOUNDATION       │ store.py  config.py  │
                    │ net.py    backends.py│
                    │ models.py watchlist.py│
                    └──────────────────────┘
```

**Boundary rules (enforced by review, and by M0-T4's import test):**
- `store.py` must not import any stage module.
- Stage modules (`scheduler`, `scrape/`, `filter`, `decide`, `profile/`) must not
  import each other; `pipeline.py` wires them.
- `pipeline.py` is the **orchestrator**: the one module allowed to import every
  stage, and one that nothing may import back. An import of it from below is a
  cycle waiting to happen.
- `shortlist.py` is a **publisher**, not a stage: it only turns stored decisions
  into a file, and is the one module both `pipeline.py` and `web/` may import.
- `web/` may import `store.py`, `shortlist.py`, `config.py` and `models.py` —
  and no stage module. (M0-T4 encodes exactly this list; the earlier wording
  called `shortlist.py` a stage and a web dependency at once, which is unencodable.)
- `backends.py` stays the single place that talks to a model.
- **`store.py` is the only module containing SQL.** Every other module asks it for
  data. This is what makes the Postgres path in §8.4 one module's work.

### 8.3 The pipeline, stage by stage

#### [0] Scheduler — `scheduler.py` — the 14-day cycle (D-9)

**Why this replaces v1's cursor.** v1 kept a global `cursor` plus a
`cycle_started_at`, walked companies 1→N, and blocked at the end until 14 days
had passed. That cannot answer "has *this company* been scraped in the past two
weeks" — only "how far through the list are we". Per-company timestamps answer it
directly, and looping back to company 1 stops being a special case.

**The due query** (SQLite; `cycle_days` from config, default 14):

```sql
SELECT * FROM companies
WHERE enabled = 1
  AND (last_scraped_at IS NULL
       OR last_scraped_at <= datetime('now', '-' || :cycle_days || ' days'))
ORDER BY (last_scraped_at IS NOT NULL),   -- never-scraped first
         last_scraped_at ASC,             -- then longest-neglected
         id ASC                           -- stable tie-break
LIMIT :batch_size;                        -- 10 (D-13)
```

**Semantics preserved from v1**
- A company is scraped at most once per 14-day window.
- Every company is eventually covered; none can starve — the longest-neglected
  always sorts first.

**Semantics improved**
| Situation | v1 cursor | v2 staleness |
|---|---|---|
| Company added mid-cycle | Waits for the next cycle | `last_scraped_at IS NULL` → next run |
| Company removed | Ordinals shift, cursor misaligns | Row disappears; nothing else moves |
| A company's fetch failed | Skipped until next cycle | Stays stale → naturally retried |
| End of list reached | Blocks on a global date | Company 1 is simply due again |
| Runs happen irregularly | Cycle boundary drifts | Queue self-levels by staleness |

**`last_scraped_at` is stamped on *attempt*, not success.** A company that returns
403 is still stamped — otherwise it would be retried every single run and consume
the whole batch. "Attempt" means *the run reached the end*; a run that crashes
stamps nothing (see Crash recovery below).
Failure handling stays where v1 put it: `consecutive_failures`, quarantine, and
probation (§9 — carried over unchanged).

**Reporting.** `python -m jobscraper status` must show: due now, due within 7
days, never scraped, quarantined, and the projected date the current sweep
completes at the observed run rate.

**Crash recovery (normative).** A run that dies mid-flight leaves `runs.status =
'running'` and may have stamped `last_scraped_at` for companies whose jobs were
never persisted. On startup the pipeline:
1. Marks any `running` row older than `per_run_timeout` as `failed`.
2. **Does not** roll back `last_scraped_at`. Those companies simply come round
   again next cycle; re-fetching them early would let a crash loop monopolise the
   queue. A crash costs at most one cycle of freshness for ≤10 companies.
3. Leaves `decisions` and `prefilter` rows intact — both are content-hashed
   (§8.4) and therefore safe to resume against.

Ordering inside a run is chosen so a crash is never worse than a no-op:
fetch → persist jobs → prefilter → decide → **then** stamp `last_scraped_at` and
close the run. A crash before the stamp means the work is simply redone.

**Cadence, stated plainly.** 229 companies ÷ 10 per run = **23 runs per 14-day
cycle ≈ 1.6 runs/day**. Below that rate the sweep does not complete in 14 days.
This is not a failure — the queue degrades to strict longest-neglected-first — but
staleness will exceed 14 days for the tail. See R-7 and Q1.

#### [1] Resume ingest — `profile/resume_ingest.py`

- **Input:** `data/resume.pdf` or `data/resume.docx` (first found).
- **Trigger:** SHA-256 of the file differs from `profile.derived.yaml`'s
  `source_hash`. Otherwise this stage is a no-op and prints "resume unchanged".
- **Process:** extract text (`pypdf` / `python-docx`) → one cheap model call →
  structured profile.
- **Output:** `data/profile.derived.yaml`:
  ```yaml
  source_file: resume.pdf
  source_hash: "sha256:9f2c…"
  parsed_at: 2026-09-23
  profile_version: 1          # bump invalidates all cached decisions
  summary: "One paragraph, <=80 words, used verbatim in the decide prompt."
  skills: [python, java, spring boot, fastapi, kubernetes, postgresql, kafka]
  years_experience: 0
  graduation: 2026-08

  # D-10: role names the scraper should look out for. Generated from the
  # resume, then used as a POSITIVE title filter in the prefilter (§8.3[3]).
  target_titles:
    - software engineer
    - backend engineer
    - platform engineer
    - infrastructure engineer
    - site reliability engineer
    - devops engineer
    - cloud engineer
    - systems engineer
    - data engineer
  # Abbreviations and variants folded onto a canonical title before matching.
  title_aliases:
    sre: site reliability engineer
    swe: software engineer
    sde: software engineer
  ```

**Generating `target_titles` (D-10).** The model is asked for the job titles this
resume would plausibly be hired under — *not* the titles it literally contains. A
resume listing "Ansible, Kubernetes, ArgoCD" should yield `site reliability
engineer` and `devops engineer` even if those words never appear in it. The prompt
must say so explicitly, and must return titles in lowercase singular form.

- **Hand overrides:** `config/profile.overrides.yaml` is merged on top and is never
  regenerated. This is how the user corrects a bad parse without editing generated
  files. Its `target_titles` and `skills` lists are **additive** — they extend the
  generated lists rather than replacing them — while scalars like `summary`
  override outright. A `target_titles_remove:` list drops generated entries the
  user disagrees with.

#### [2] Scrape — `scrape/` (reuses v1 modules verbatim)

Unchanged from v1: resolve provider → fetch listings → diff against known job ids.
Which companies to fetch comes from the scheduler (§8.3[0]) — **not** from
`cursor.py`, which is retired by D-9. Failure classes, quarantine and probation
carry over unchanged. **Do not rewrite this layer.**

#### [3] Local prefilter — `filter.py` — FREE, runs on every new posting

Evaluated in declared order; **first rejection wins** and is recorded with the
rule id and the matched text, so every rejection is explainable.

| # | Rule | Rejects when |
|---|---|---|
| 1 | `title_deny` | Title matches senior/staff/principal/lead/manager/director/intern/non-engineering patterns |
| 2 | `title_allow` | Title matches **none** of `target_titles` (D-10), after alias folding |
| 3 | `location_explicit` | Location names a place and **no** token is `singapore`/`sg` — including every `Remote*` form (D-7) |
| 4 | `experience_ceiling` | Any "N+ years" in title/description exceeds **3** (D-12) |
| 5 | `keyword_floor` | Skill overlap with the derived profile below `min_overlap` |

Deny runs before allow so an explicit "Senior Software Engineer" is rejected even
though it matches `software engineer`.

**Location precedence (normative — resolves the D-7 / `vague_tokens` conflict).**
`location_explicit` evaluates in this exact order, first match wins:

| Order | Test on the location string | Result |
|---|---|---|
| 1 | Contains an allow token (`singapore`, `sg`) | **pass** — even `"Remote — Singapore"` |
| 2 | Contains `remote`/`anywhere`/`distributed` (and failed 1) | **reject** (D-7) — so `Remote, Global` and `Remote (APAC)` reject here, *before* `global`/`apac` are ever read as vague |
| 3 | Empty, or only vague tokens (`apac`, `global`, `multiple`, `various`, `all offices`, `worldwide`) | **pass to [4]/[5]** for the model to read the description (D-2) |
| 4 | Names any other place | **reject** |

Rule 2 preceding rule 3 is the whole resolution: without it, `Remote (APAC)` would
hit the vague list and survive, contradicting D-7.

**Reuse `matching.py::location_verdict()`** — v1 already strips the matched
residue before judging what remains, which is what stops `Singapore` inside
`Singapore-based role, US only` producing a false pass. Port that logic; do not
re-derive it.

**Years semantics (normative — resolves the v1 conflict).** Use the **lowest**
stated requirement, matching v1's `matching.py::min_years_required()` and its
existing test. `"2-5 years"` → 2 → **passes** the 3-year cap; `"4+ years"` → 4 →
**rejects**. Rationale: a range's floor is the real bar, and the generous reading
keeps recall while the model still sees the range in the vital extract. *(An earlier
draft of this PRD said "highest wins" — that was wrong and is corrected here.)*

**`config/rules.yaml` — the flexible, extensible filter contract**

Rules are *declared*, not coded. Adding, reordering, disabling or tuning a rule is
a YAML edit. Adding a new rule *kind* is a new function in a registry.

```yaml
version: 1
ceiling_years: 3            # D-12

rules:
  - id: title_deny
    kind: regex_deny        # registry: regex_deny | any_match | max_number | overlap_floor
    field: title
    enabled: true
    patterns:
      - '\b(senior|staff|principal|lead|head|director|manager|vp)\b'
      - '\b(intern|internship|apprentice|working student)\b'
      - '\b(sales|marketing|recruit|legal|finance|hr)\b'
    extra: []               # ← yours; merged with the above, never overwritten

  - id: title_allow
    kind: any_match
    field: title
    enabled: true
    source: profile.target_titles   # generated (D-10)
    extra: []                       # ← yours; e.g. "solutions engineer"
    match: token_subset             # all words of a target title present, any order

  - id: location_explicit
    kind: regex_deny
    field: location
    enabled: true
    allow_tokens: [singapore, sg]
    vague_tokens: [apac, global, multiple, various, all offices, worldwide]
    reject_remote: true             # D-7

  - id: experience_ceiling
    kind: max_number
    fields: [title, description]
    enabled: true
    pattern: '(\d+)\s*\+?\s*(?:years|yrs)'
    max: 3                          # D-12

  - id: keyword_floor
    kind: overlap_floor
    enabled: true
    source: profile.skills
    extra: []
    min_overlap: 2
```

Three properties this buys, all of which M4-T1 must verify:
1. **Disable without deleting** — every rule has `enabled`, so tuning is reversible.
2. **Extend without forking** — every list has an `extra:` the generator never
   touches, so regenerating the profile cannot clobber hand-tuning.
3. **Reorder freely** — evaluation follows declaration order.

**Tuning tools (part of M4-T1, not optional):**
- `python -m jobscraper filter explain <job_id>` — every rule, verdict, matched text.
- `python -m jobscraper filter test --title "…" --location "…" [--desc "…"]` —
  dry-run the rules with no scrape and no database write.

Without these, tuning a filter over 20,000 postings is guesswork.

#### [4] Vital extract — `decide.py::vital_extract()` — FREE

Reduces a JD to only what the decision needs. Budget **≤ 800 characters**.

```
LOCATION: <location field verbatim> | <first line in body matching a place pattern>
EXPERIENCE: <sentences containing "years", "experience", "degree", "graduate", "entry">
REQUIREMENTS: <first 400 chars of the requirements/qualifications section>
ROLE: <first 200 chars after the responsibilities heading>
```

Section headings are found by heuristics already present in
`matching.py::extract_requirements()` — extend it, don't duplicate it. If a section
is not found, emit the literal `UNSTATED` so the model can distinguish *absent*
from *empty*.

#### [5] Decide — `decide.py` — the only paid step

- **Transport:** `backends.py` (existing Claude Code CLI backend, D-6).
- **Model:** cheapest available, `budget.model` in config.
- **Batch:** ~20 postings per call (tunable; the per-call overhead dominates).
- **Prompt:** system = fixed screening instruction; user = derived summary + the
  vital extracts. No tier, no category, no company prestige signal.
- **Output contract, one object per posting:**
  ```json
  { "id": "<verbatim>", "decision": "accept",
    "is_singapore": true, "yoe_min": 0,
    "reason": "<=15 words, names the deciding fact" }
  ```
  `decision` is `accept` or `reject`; `is_singapore` is `true`, `false` or `null`.
- **Post-conditions (enforced in code, never trusted to the model).**
  An `accept` is downgraded to `reject` when either holds:

  | Condition | Stored reason |
  |---|---|
  | `is_singapore` is not exactly `true` | `location not confirmed Singapore` (D-7) |
  | `yoe_min > 3` | `requires more than 3 years` (D-12) |

  Both guarantees are structural: the model cannot talk the pipeline into a
  non-Singapore or over-experienced role, however confident it sounds.
- **Cache:** `hash(job_id + vital_text + profile_version)`. Carry over v1's caching
  discipline — a posting is never judged twice.

#### [6] Shortlist — `shortlist.py`

`data/shortlist.json` — regenerated every run, engine-owned, safe to delete (D-5):

```json
{
  "version": 1,
  "generated_at": "2026-09-23T14:30:00",
  "profile_version": 1,
  "runs": [{ "run_no": 12, "finished_at": "2026-09-23T14:30:00", "accepted": 41 }],
  "jobs": [
    { "id": "a1b2c3", "run_no": 12, "company": "OKX",
      "title": "DevOps / Site Reliability Engineer",
      "url": "https://job-boards.greenhouse.io/okx/jobs/7767872003",
      "location": "Singapore", "posted_at": "2026-09-18",
      "yoe_min": 0, "reason": "Singapore-based; K8s and CI/CD match",
      "decided_at": "2026-09-23T14:29:41" }
  ]
}
```

### 8.4 Data contracts

#### `config/watchlist.yaml` — the thing the user edits

Minimum viable entry is **two lines**. Everything else is optional and may be
written back by discovery.

```yaml
version: 1
companies:
  - name: Jane Street
    careers_url: https://www.janestreet.com/join-jane-street/open-roles/

  - name: OKX
    key: okx                      # optional stable id; defaults to slug(name)
    careers_url: https://www.okx.com/careers
    provider: greenhouse          # optional - learned and cached by discovery
    slug: okx                     # optional
    enabled: true                 # optional, default true
    notes: "SG office confirmed"  # optional, free text, ignored by the engine
```

**Identity and sync semantics (normative — M3-T2 implements this).**
The YAML is the source of truth for *which* companies exist; the `companies` table
is the source of truth for their *history* (staleness, failures, quarantine). They
are reconciled at the start of every run.

- **Key.** `key` is the stable identity, defaulting to a slug of `name`. It is what
  the database row is matched on — **never the display name.** Without this,
  renaming "Shopee" to "Shopee / Sea Group" silently creates a new row, resets
  `last_scraped_at` to null, and orphans the failure counters.
- **New key** → insert, `last_scraped_at = NULL` (due immediately).
- **Existing key** → update `name`, `careers_url`, `provider`, `slug`, `enabled`.
  **Never** touch `last_scraped_at`, `last_success_at`, failure counters or
  quarantine state — those belong to the database.
- **`careers_url` changed** → clear `provider`/`slug`/`feed_url` so discovery re-runs,
  and reset `consecutive_failures`. A new URL is a new board.
- **Key absent from the YAML** → set `enabled = 0`. **Do not delete the row.** Jobs,
  decisions and applications reference it; deleting orphans your own history. A
  disabled company is skipped by the scheduler and hidden from `status`.
- **Duplicate keys** → hard validation error naming both entries (M1-T1).

Removed versus v1: `#`, `Tier`, `Category`, `Role Type`, `Status`, `Date Applied`,
`Notes` columns, the `Legend` sheet, and the duplicate `May26` sheet.

**Seeded with all 229 v1 companies (D-4).** M1-T2 generates the initial file from
the v1 database, which holds a resolved `provider` for **all 229** and a
`feed_url` for **133**. The user then prunes and extends by hand. Verified against
the live v1 DB on 2026-09-23:

| Field available to seed | Count |
|---|---|
| `name` + `careers_url` | 229 / 229 |
| `provider` (greenhouse, lever, ashby, workday, smartrecruiters, workable, recruitee, generic_html) | 229 / 229 |
| `feed_url` | 133 / 229 |

Companies v1 quarantined as unscrapable (Google/DeepMind, Meta, Microsoft, DRW,
Fionics) are seeded with `enabled: false` and a `notes:` line explaining why, so
the user can decide rather than rediscover the problem.

#### SQLite schema — `data/jobscraper.db` (new file, D-4)

```
companies    id, name, careers_url, provider, slug, feed_url, enabled,
             last_scraped_at,          -- D-9: stamped on ATTEMPT; drives the due query
             last_success_at,          -- last time a fetch actually worked
             consecutive_failures, last_error_class, last_error,
             quarantined_at, probation_due_run
             INDEX (enabled, last_scraped_at)   -- the due query runs every run

jobs         job_id PK, company_id, external_id, title, location, url,
             posted_at, jd_hash, jd_text, vital_text,
             first_seen_run, last_seen_run, closed_at

decisions    job_id, profile_version, vital_hash, decision, is_singapore,
             yoe_min, reason, model, decided_at
             PK(job_id, profile_version, vital_hash)
             -- vital_hash = sha256(vital_text). A posting whose description
             -- changes gets a new hash and is re-decided; an unchanged one is
             -- never paid for twice. Without this column the cache key in
             -- §8.3[5] has nowhere to live.

prefilter    job_id, profile_version, rules_hash, passed, reject_rule,
             reject_detail, overlap_score, evaluated_at
             PK(job_id, profile_version, rules_hash)
             -- rules_hash = sha256(canonicalised rules.yaml). A prefilter verdict
             -- is only valid for the rules that produced it, so editing a rule
             -- during the M4-T1b tuning loop correctly re-evaluates every posting
             -- instead of serving stale rejections.

applications job_id PK, status, applied_at, notes, updated_at

app_events   id PK, job_id, from_status, to_status, at
             -- append-only history; powers the Applications tab timeline

runs         run_no PK, started_at, finished_at, status, stats_json
             -- status: running | ok | failed | aborted_unhealthy
             -- A row left at `running` means the process died mid-run; the next
             -- run marks it `failed` before starting. See R-12.
             -- stats_json is the instrument for the §5 metrics; it MUST carry:
             --   companies_due, companies_fetched, companies_failed,
             --   postings_seen, postings_new,
             --   prefilter_passed, prefilter_rejected_by_rule {rule_id: count},
             --   judged, accepted, rejected_by_postcondition,
             --   model_calls, input_tokens, output_tokens,
             --   vital_chars_p50, vital_chars_max
             -- Metric 1 (§5) = input_tokens / judged. Nothing else measures it.

coverage     run_no, company_id, status, postings_found, new_count,
             accepted_count, error_class, error, checked_at
```

`applications.status` is an open vocabulary, ordered:
`to_apply → applied → interviewing → offer | rejected | withdrawn`.
Adding a status is a config change, not a migration.

**Why SQLite is the right database for the scheduling decision (D-9).**
The scheduler's question — *which companies have not been scraped in 14 days* —
is a single indexed range scan over ~229 rows.

| Requirement | SQLite | Why not the alternatives |
|---|---|---|
| Durable timestamps across runs | ✅ ACID, single file | A JSON/YAML state file has no atomic read-modify-write; a crashed run corrupts it |
| Query "due now, oldest first" | ✅ One indexed `ORDER BY … LIMIT` | In-memory or flat files need a full re-read and sort in Python |
| Concurrency | ✅ Sufficient — one writer, WAL mode | Postgres/MySQL solve a contention problem this app does not have |
| Operational cost | ✅ Zero. No server, no container, no credentials | A DB server contradicts the "very easy to spin up" requirement (§8.6) |
| Cloud path later | ✅ Behind the `store.py` interface | — |

**Cloud-readiness constraint (design-time only, not implemented):** all SQL lives
in `store.py`. No stage module writes SQL. A future Postgres swap is therefore one
module, not a search-and-replace — which is what makes §8.6's "cloud later"
credible rather than aspirational. Use plain SQL and avoid SQLite-only syntax where
an ANSI equivalent exists; `datetime('now', …)` in the due query is the known
exception and is isolated to one function.

### 8.5 Web application

**Backend** — `src/jobscraper/web/api.py`, FastAPI, one router per domain so a new
tab is a new router file, not an edit to a growing module.

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/runs` | Run list for the selector: `run_no`, date, accepted count |
| `GET` | `/api/shortlist?run=latest\|<n>\|all` | Jobs joined with application status |
| `GET` | `/api/applications` | Everything with a status, for the Applications tab |
| `POST` | `/api/applications/{job_id}` | `{status, notes}` → upsert + append `app_events` |
| `GET` | `/api/stats` | Counts per status/run. Stub for a future tab. |
| `GET` | `/` | Serves the built SPA |

**Frontend** — `web/` (Vue 3 + Vite, built into `src/jobscraper/web/static/`).

Deliberately one page. The run selector changes the dataset in place — this is
the direct replacement for v1's per-run HTML files.

```
┌────────────────────────────────────────────────────────────────┐
│  JobScraper           [ run 12 · 23 Sep · 41 roles  ▼ ]        │
├────────────────────────────────────────────────────────────────┤
│  ┌────────┬──────────────┬─ ── ── ── ── ─┐                     │
│  │ Inbox  │ Applications │  (future tab) │                     │
│  └────────┴──────────────┴─ ── ── ── ── ─┘                     │
│                                                                │
│   OKX · DevOps / Site Reliability Engineer                     │
│   Singapore · 0 yrs · seen 23 Sep                              │
│   "Singapore-based; K8s and CI/CD match"                       │
│   [ Open ↗ ]  [ Mark applied ]  [ Dismiss ]                    │
│  ──────────────────────────────────────────────────────────    │
│   GovTech · Platform Infrastructure Engineer, AISO             │
│   …                                                            │
└────────────────────────────────────────────────────────────────┘
```

**Extensibility requirement (normative).** Tabs are declared in one registry:

```js
// web/src/tabs.js - adding a tab is one entry + one component file
export const TABS = [
  { id: 'inbox',        label: 'Inbox',        component: () => import('./tabs/Inbox.vue') },
  { id: 'applications', label: 'Applications', component: () => import('./tabs/Applications.vue') },
]
```

A reviewer must be able to add a "Stats" tab by adding one line here, one `.vue`
file, and one FastAPI router — touching nothing else. **M7-T4 verifies this by
actually doing it with a throwaway tab.**

---

### 8.6 Deployment & spin-up

**Requirement: one command from clone to running app.**

```bash
docker compose up          # → http://localhost:8765
```

| Concern | Decision |
|---|---|
| Image | Multi-stage: node builds the Vue bundle → slim Python runtime. Node is absent from the final image. |
| State | `data/` is a mounted volume. The container is disposable; the database is not. |
| Config | `config/` mounted read-only. Overridable by env var (`JOBSCRAPER_CONFIG`, `JOBSCRAPER_DB`). |
| Model auth | **The hard part — see D-11.** `~/.claude` mounted read-only so `claude -p` works. |
| Scheduling | `docker compose run --rm app run` for a batch. No in-container cron for MVP. |
| Non-Docker path | Must remain: `pip install -e .` + `python -m jobscraper web` works with no Docker and no node (built assets are committed). |

**The Docker/auth tension, stated plainly (D-11, R-8).** The pipeline reaches its
model through the Claude Code CLI, which authenticates against a login on the
*host*. A container has no such login. Locally this is solved by mounting
`~/.claude` read-only. **In cloud there is no host login to mount**, so a cloud
deployment needs either an API key (`budget.backend: api`, already supported) or a
different transport. This is why `backends.py` stays pluggable and why cloud is out
of scope here rather than half-built.

**Cloud considerations recorded now, built later (explicitly NOT in scope):**
- No writes outside `data/`; nothing depends on the working directory.
- No hardcoded `localhost` in the frontend — API base is relative.
- Port and bind address from env, defaulting to `127.0.0.1:8765` (**not** `0.0.0.0`
  — binding wide by default on a personal machine is a security regression).
- The web app is read-mostly; the pipeline is a batch job. They can split into two
  services later without a redesign.
- **No auth exists.** Acceptable on `127.0.0.1`. Any cloud exposure requires auth
  first — recorded as R-9.

## 9. What already exists — reuse, do not rewrite

Audited against the working tree on 2026-09-23.

| Module | Status | Disposition |
|---|---|---|
| `net.py` — HTTP client, robots, rate limit, retries | `REUSE` | Carry over unchanged. |
| `adapters.py` — 8 ATS providers + generic HTML | `REUSE` | Carry over unchanged. The most valuable asset in the repo. |
| `discovery.py` — ATS resolution + corroboration | `REUSE` | Carry over; swap its input from Excel rows to watchlist entries. |
| `backends.py` — Claude Code CLI transport, no API key | `REUSE` | This *is* the cheap-model transport (D-6). Built and verified 2026-09-23. |
| `cursor.py` — global cursor + 14-day cycle | `RETIRE` | Replaced by the staleness scheduler (D-9, §8.3[0]). Its 14-day *semantics* survive; its cursor mechanism does not. Retire in M9, not before — its tests port to `scheduler.py` first. |
| `config.py` — YAML loading, path resolution | `ADAPT` | Keep the loader and root-relative path logic. Add `watchlist`/`rules` paths, `batch_size: 10`, `cycle_days: 14`, `budget.model`; drop `model_high`/`model_low` (D-6) and the whole `Profile` class (replaced by the derived profile, §8.3[1]). Env-var overrides per §8.6. |
| `models.py` — dataclasses | `ADAPT` | Drop `tier`/`category`; replace `Verdict` with `Decision`; drop `ScoreBreakdown`. Add `last_scraped_at` to `Company` (D-9). |
| `matching.py::extract_requirements` | `ADAPT` | Becomes the basis of vital extract (§8.3 [4]). |
| `matching.py` — BM25, tier bonus, category priors | `RETIRE` | Replaced by the keyword floor. Tiering is gone. |
| `llm.py` — Judge, prompts, `_parse_json` | `ADAPT` | Keep `_parse_json` and the cache-key discipline. Prompts and tier routing go. |
| `store.py` | `REWRITE` | New schema (§8.4). Keep the "all writes on the orchestrator thread" rule. |
| `output.py` — xlsx + HTML writers | `RETIRE` | Replaced by the web app. Retire in M9. |
| `serve.py` — stdlib viewer | `RETIRE` | Replaced by FastAPI. Retire in M9. |
| `ingest.py` — Excel reader | `RETIRE` | Replaced by the watchlist loader. Retire in M9. |
| `runner.py` — v1 orchestrator | `RETIRE` | `pipeline.py` replaces it. **Read it before writing `pipeline.py`** — its failure policy (global-failure-abort, quarantine-after-N, probation, "persist jobs only after matching") is hard-won and must survive the move. Retire in M9. |
| `cli.py` — argparse surface | `ADAPT` | Keep `_boot`, the subparser layout and the output style. Commands change: add `watchlist`, `scheduler`/`status`, `filter`, `web`; drop `view`, `export`, `sync`, `resolve`. |
| `__main__.py` | `REUSE` | Two lines; unchanged. |
| `review.py` — in-session handoff review | `KEEP` | Orthogonal to this redesign; still useful. Point it at the new schema in M9. |
| `tests/test_core.py` — 29 passing tests | `ADAPT` | Split per §10 M0-T3. Location and cursor tests carry over. |

---

## 10. Build Ledger

> Eleven milestones, M0–M10. Each task is one sitting. **The `Verify:` command is
> the truth, not the flag.** See §0.1. Tasks within a milestone run in listed order;
> milestones run in numeric order. Every `Verify:` here is a Python or `git`
> one-liner, never POSIX shell — this machine is Windows/PowerShell.

Legend: `STATUS` · `Completed` (date) · `Verify` (command that proves it) · `Notes`

---

### M0 — Foundations

**Outcome:** the new skeleton exists and the old app still runs untouched.

#### M0-T0 · Put the repo under version control
- **STATUS:** `DONE`
- **Completed:** 2026-09-23
- **Do:** `git init`, a `.gitignore` covering `data/*.db*`, `archive/`,
  `node_modules/`, `web/dist/`, `__pycache__/`, `output/`, and one commit of the
  current v1 tree as the restore point (D-15).
- **Verify:** `python -c "import subprocess;print(subprocess.run(['git','rev-parse','--is-inside-work-tree'],capture_output=True,text=True).stdout.strip())"` prints `true`, and `git log --oneline` shows ≥ 1 commit.
- **Notes:** Verified — prints `true`, commit `9009eb3` holds 27 files / 411 KB.
  The 92 MB of `.db` files are correctly excluded and remain on disk for M1-T2
  and M3-T3b. `data/resume.*` is also ignored (personal, per M2-T0).
  **Work happens on branch `v2-rebuild`; `master` holds only the v1 restore point.**
  Cosmetic defect: the commit subject carries a stray `@` from a shell-quoting
  slip; `git commit --amend` was refused by a local safety hook, so it stands.
  Body is intact. Harmless — fix by hand if it bothers you.

#### M0-T1 · Create the v2 package skeleton
- **STATUS:** `DONE`
- **Completed:** 2026-09-23
- **Do:** Create `src/jobscraper/{scrape,profile,web}/__init__.py` and empty
  `filter.py`, `decide.py`, `shortlist.py`, `pipeline.py`, `watchlist.py`,
  `scheduler.py`, each with a module docstring stating its single responsibility
  per §8.2.
- **Verify:** `python -c "import importlib;mods=['filter','decide','shortlist','pipeline','watchlist','scheduler'];[print(m, len((importlib.import_module('jobscraper.'+m).__doc__ or '').strip()) ) for m in mods];assert all(len((importlib.import_module('jobscraper.'+m).__doc__ or '').strip())>40 for m in mods), 'every module needs a real docstring'"`
- **Notes:** The assertion is on the docstring, not just the import — an empty file
  imports fine, which would let this task pass having done nothing.
  Verified: docstrings 460–676 chars on the six modules, 264–301 on the three
  subpackages. v1's 29 tests still pass, so the skeleton broke nothing.
- **Notes:** Do not move v1 files yet. M9 does that.

#### M0-T2 · Archive v1 outputs and database
- **STATUS:** `DONE`
- **Completed:** 2026-09-23
- **Do:** Move **everything** under `output/`, plus `data/jobscraper.db*`, into
  `archive/v1-2026-09-23/{output,data}/`. Leave the Excel workbook in place until
  M1-T2 is done. The archived DB is the **input** for M1-T2 (watchlist seed) and
  M3-T3b (applications migration) — do not delete it after either.
  *(Refined during execution: the original wording named only `*.html` and
  `*.xlsx`, which would have stranded `output/backups/`, `review_queue.json` and
  `review_verdicts.json` — all v1 artefacts — in a directory the §5 metric
  requires to be empty.)*
- **Verify:** `python -c "import glob,sys; h=glob.glob('output/*.html'); a=glob.glob('archive/v1-2026-09-23/*'); print('html:',len(h),'archived:',len(a)); sys.exit(0 if not h and a else 1)"`
- **Notes:** Archive, never delete (§0.3). Verify is a Python one-liner, not shell —
  this machine is Windows/PowerShell and `2>/dev/null | wc -l` does not run here.
  Verified: 20 items archived, `output/` empty, and the archived DB still reads
  229 companies / 5 applications. **Canonical archive paths for later tasks:**
  `archive/v1-2026-09-23/data/jobscraper.db` (M1-T2, M3-T3b) and
  `archive/v1-2026-09-23/output/` (reference only).

#### M0-T3 · Split the test suite
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** Split `tests/test_core.py` into `tests/test_filter.py`,
  `tests/test_scrape.py`, `tests/test_store.py`, `tests/test_decide.py` and
  `tests/test_legacy_v1.py`. *(The remaining files named in an earlier draft —
  `test_scheduler.py`, `test_web.py`, `test_watchlist.py`, `test_profile.py` —
  are created by the milestones that produce the code they test: M3-T3, M6-T1,
  M1-T1, M2-T1. Creating them empty here would only add files that assert
  nothing.)*

  **Disposition for all 29 existing tests — decide each explicitly, none may be
  dropped silently:**
  | v1 tests | Destination |
  |---|---|
  | 3 location tests (`test_location_is_default_deny`, `test_remote_pinned_*`, `test_stage_a_*`) | `test_filter.py` — carry over, then extend per M4-T1 |
  | `test_min_years_takes_the_lowest_stated` | `test_filter.py` — carries over unchanged (§8.3[3] adopts its semantics) |
  | **3** cursor tests *(the table first said 4; there are 3)* | `test_legacy_v1.py` until M3-T3 ports them to `test_scheduler.py` as staleness equivalents. Do not delete in M0. |
  | 4 discovery tests | `test_scrape.py` — carry over |
  | `test_failed_fetch_must_not_close_jobs` | `test_store.py` — carry over, it guards a real invariant |
  | 9 backend/review tests (added 2026-09-23) | `test_decide.py` — carry over; `backends.py` is REUSE |
  | 6 `test_applied_*` + `sync_applied` | `test_legacy_v1.py` until M6-T2 **rewrites** them against the new API into `test_web.py`. The behaviours they assert (date set once, never walk back a status, leave the user's own columns alone) are v2 requirements; only the transport changes. |
  | 2 `test_html_view_*` / `test_cards_from_tracker_*` | **Delete.** They test `output.py`, which M9-T1 retires. Record the deletion in `Notes:`. |

  Add `tests/run_tests.py`: discovers `tests/test_*.py`, runs every `test_*`
  function it *defines* (not ones it merely imports), prints a per-file and total
  tally, exits non-zero on any failure **and** on a `-k` that matches nothing.
  **It must accept `-k <substring>`** filtering on function *and* file name —
  thirteen later tasks verify with it.

  **`-k` must also gate importing.** The ledger builds one milestone at a time,
  so at any moment some test file imports something not yet installed —
  `test_web.py` needs FastAPI long before M7 adds it. If a selective run imported
  every file regardless, one not-yet-buildable module would fail an *earlier*
  task's acceptance command for unrelated reasons. Rule: when `-k` is given and a
  file's name does not match it, an import failure skips that file and is
  reported as skipped; when the name does match, or no `-k` was given, an import
  failure is a hard failure.
- **Verify:** `python tests/run_tests.py` exits 0 and reports ≥ 27 tests;
  `python tests/run_tests.py -k filter` runs a strict subset and exits 0.
- **Notes:** The old "≥20" bar let all 13 retired-module tests vanish while still
  passing. The table above is the accounting; `-k` is the contract thirteen tasks
  depend on.
  **Verified 2026-09-24:** 27/27 pass. `-k filter` → 4/4, `-k location` → 1/1,
  `-k legacy` → 9/9, all exit 0; `-k zzzznope` exits **1**, so a typo in a later
  acceptance command cannot pass vacuously. Tests were moved by extracting exact
  AST source ranges, so not one assertion was retyped or altered in transit.
  The two `output.py` tests were deleted deliberately and are named in
  `test_legacy_v1.py`'s docstring so the loss stays auditable.

#### M0-T4 · Add the layering guard
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** `tests/test_layering.py` parses each module's imports via `ast` — no
  importing, no executing — and asserts the §8.2 boundary rules. Six rules, one
  test each, plus a seventh that fails when a new module belongs to no layer.
- **Verify:** `python tests/run_tests.py -k layering` passes (7/7), and the full
  suite passes.
- **Notes:** Verified 2026-09-24, 34/34 overall. **Proved non-vacuous:** injecting
  `from . import decide` into `filter.py` makes the guard exit 1 with
  "stages must be composed by pipeline.py"; the file was then restored and
  confirmed unchanged. Two rules were added beyond the original three because the
  guard exposed the gaps: only `store.py` may contain SQL (§8.4's Postgres path
  depends on it), only `backends.py` may reach a model, and nothing may import
  `pipeline.py`. The classification test immediately caught `pipeline` having no
  assigned layer — hence the new `ORCHESTRATOR` set, now also named in §8.2.

---

### M1 — Watchlist

**Outcome:** companies live in a file the user can edit in seconds.

#### M1-T1 · Watchlist schema + loader + validator
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** `watchlist.py` — load `config/watchlist.yaml` per §8.4, validate
  (name non-empty and unique, `careers_url` parses as http(s)), and raise a
  message naming the offending entry and line. Support the two-line minimal entry.
- **Verify:** `python tests/run_tests.py -k watchlist` passes, including a case for
  a duplicate name and a malformed URL.
- **Notes:** Verified 2026-09-24, 15/15 (49/49 overall). Line numbers come from a
  `yaml.SafeLoader` subclass that records `node.start_mark`, so a duplicate cites
  **both** offending lines rather than leaving you to find the first one.
  Two additions beyond the task as written, both closing silent-failure holes:
  **unknown fields are refused** — a misspelled `carers_url` would otherwise
  scrape nothing and look like a 404 — and `render_entry()` emits one entry as
  text rather than re-dumping the document, which is what lets M1-T5's `add`
  append without destroying hand-written comments.
  A test asserting a pure "duplicate name" error for two identical names was
  **wrong and was corrected**: equal names slug to equal keys, so the key check
  fires first. Both paths are now covered separately.

#### M1-T2 · Seed the watchlist with all 229 v1 companies
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** One-off script `scripts/seed_watchlist.py` reading `archive/v1-2026-09-23/data/jobscraper.db`
  and writing `config/watchlist.yaml` with all 229 companies — `name`, `careers_url`,
  and the cached `provider`/`slug`/`feed_url` where present (D-4). The 5 companies
  v1 quarantined get `enabled: false` plus a `notes:` line quoting the v1 error.
  Emit a schema comment header so the file teaches its own format. Sort
  alphabetically by name — the v1 ordinal no longer means anything.
- **Verify:** `python -c "from jobscraper.watchlist import load; w=load(); print(len(w), sum(1 for c in w if c.enabled)); assert len(w)==229 and sum(1 for c in w if c.enabled)==224"`
- **Notes:** Uses M1-T1's loader directly — `watchlist list` (M1-T5) and `doctor`
  do not exist yet, and v1's `doctor` reads the Excel workbook M0-T2 archived.
  The script is one-off and lives in `scripts/`, not the package. Run it once,
  commit the YAML, then the YAML is the source of truth forever.
  **Verified 2026-09-24:** 229 companies, 224 enabled, 229 with a resolved
  provider, 133 with a cached feed URL — the full discovery asset preserved, as
  D-4 intended. Keys are unique and the awkward real names slug cleanly
  (`Google / DeepMind` → `google-deepmind`, `JD.com` → `jd-com`). The five v1
  quarantines (DRW, Fionics, Google/DeepMind, Meta, Microsoft) arrive
  `enabled: false` carrying the v1 error as a note. Result: 1,194 lines, 32 KB.
  Two safeguards added beyond the task as written: the script **re-parses the
  file it just wrote** before saving, so a broken watchlist can never be
  committed and then fail at the next run far from its cause; and it refuses to
  overwrite an existing `watchlist.yaml` without `--force`, because that file is
  hand-edited and regenerating it would discard the user's pruning.

#### M1-T3 · Prune the seeded watchlist
- **STATUS:** `NOT_STARTED`
- **Completed:** —
- **Do:** **User task, not an agent task.** Review the 229 seeded entries and
  remove or disable the ones not worth monitoring. Agents must not invent, reorder
  or delete entries.
- **Verify:** `python -m jobscraper watchlist list` still validates after editing.
- **Notes:** Optional and non-blocking — M1-T2 leaves a working 229-company list, so
  the build proceeds whether or not the user prunes. Fewer companies makes the
  cadence in R-7 easier to meet.

#### M1-T4 · v2 configuration file
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** Rewrite `config/config.yaml` for v2 and adapt `config.py` per §9. Add
  `paths.watchlist`, `paths.rules`, `paths.shortlist`; `run.batch_size: 10` (D-13),
  `run.cycle_days: 14`; `budget.model` (single, cheapest — D-6); `web.host:
  127.0.0.1`, `web.port: 8765`. Remove `input_workbook`, `input_sheet`,
  `model_high`, `model_low`, `second_opinion_tiers`, `min_score_to_export`,
  `export_verdicts`. Env-var overrides per §8.6. Archive the v1 file.
- **Verify:** `python -c "from jobscraper.config import load_config; c=load_config(); assert c.run['batch_size']==10 and c.run['cycle_days']==14 and c.budget.get('model'); assert 'model_high' not in c.budget and 'input_workbook' not in c.raw['paths']; print('config v2 ok')"`
- **Notes:** M3, M4 and M10 all read keys defined here. Without this task they each
  invent their own.
  **Verified 2026-09-24**, 49/49 suite green. Env overrides confirmed working:
  `JOBSCRAPER_DB`, `JOBSCRAPER_HOST`, `JOBSCRAPER_PORT`, `JOBSCRAPER_CONFIG`.
  Also added `budget.decide_batch: 20` and `budget.vital_chars: 800` — M4 needs
  both and neither had a home — plus `applications.statuses` for M8-T2.

  **Two deviations, deliberate:**

  1. **`Profile` and `load_profile` are kept**, not dropped as this task first
     said. Five live modules and two test files import them
     (`matching.py`, `llm.py`, `review.py`, `runner.py`, `cli.py`,
     `test_filter.py`, `test_decide.py`). They die with those modules at M9-T1;
     removing them now would break 13 passing tests for no gain.
  2. **`cli.py::_sync` was repointed at the watchlist.** Removing
     `paths.input_workbook` broke `cfg.input_workbook`, which `doctor`, `sync`,
     `resolve` and `run` all call — four commands raising `AttributeError` until
     M3. `_sync` now feeds watchlist entries through v1's `sync_companies`. It is
     a **bridge**: that function still keys on the display name and wants
     tier/category. **M3-T1b must replace it with `store.sync_watchlist`**, which
     keys on the stable `key`. Until then, renaming a company in the watchlist
     still resets its history — the exact bug §8.4 exists to prevent.
     `doctor` now reports the watchlist and the single `budget.model`.

#### M1-T5 · `watchlist` CLI verbs
- **STATUS:** `NOT_STARTED`
- **Completed:** —
- **Do:** `python -m jobscraper watchlist list|add|disable` — `add` appends a
  minimal entry preserving comments and key order. **`add` does not run discovery**
  (that lives in `scrape/` and is not relocated until M3-T2); resolution happens on
  the next run like any other new company.
- **Verify:** A test adds a company to a temp file, reloads it, and asserts the new
  entry validates and pre-existing comments survive; `python -m jobscraper watchlist list` prints 229.

---

### M2 — Resume & keyword engine

**Outcome:** the match vocabulary comes from the actual resume.

#### M2-T0 · Supply the resume
- **STATUS:** `DONE`
- **Completed:** 2026-09-24 — supplied by the user; renamed to `data/resume.pdf`.
  Verify passes (`['data\\resume.pdf']`).
- **Do:** **User task.** Place `resume.pdf` (or `.docx`) in `data/`. `data/` currently
  holds only the workbook and the database — verified 2026-09-23.
- **Verify:** `python -c "import glob;f=glob.glob('data/resume.*');assert f, 'no resume in data/';print(f)"`
- **Notes:** `BLOCKED` until supplied. M2-T1 and M2-T2 cannot complete without it.
  An agent must **not** substitute a sample resume — a wrong profile silently
  mis-filters every posting downstream. `.gitignore` should exclude `data/resume.*`.

#### M2-T1 · Resume text extraction
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** `profile/resume_ingest.py` — find `data/resume.pdf|docx`, extract text
  (`pypdf`, `python-docx`), compute SHA-256, short-circuit when unchanged.
  Generate the test fixture by writing a 1-page PDF with `pypdf`/`reportlab` in
  `tests/fixtures/make_resume_fixture.py` — do **not** commit the real resume.
- **Verify:** `python tests/run_tests.py -k resume` passes against the generated
  fixture; running ingest twice performs extraction once (assert via a call counter).
- **Notes:** Verified 9/9 (`-k resume`), full suite 58/58. API:
  `find_resume`, `file_hash` (`"sha256:<hex>"`), `extract_text`,
  `load_resume(dir, previous_hash, force) -> ResumeText`; unchanged hash returns
  `changed=False` with no extraction (`test_resume_unchanged_is_extracted_once`).
  DOCX extraction includes table cells; an empty text layer (scanned PDF) raises
  `ResumeError` rather than deriving a profile from nothing. The fixture PDF is
  hand-written PDF syntax, read back by pypdf - **no reportlab dependency** - and
  both fixtures are generated into a temp dir at test time; nothing binary is
  committed. Real `data/resume.pdf` extracts (5.6k chars).

#### M2-T2 · Derived profile via one cheap model call
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** Resume text → `data/profile.derived.yaml` per §8.3[1]. Merge
  `config/profile.overrides.yaml` on top. Bumping `profile_version` must invalidate
  cached decisions.
- **Verify:** `python -m jobscraper profile --show` prints skills, `target_titles`
  and `profile_version`; a test with a **stub backend** (no live model, no host auth)
  asserts the derived YAML is written, that `profile.overrides.yaml` merges
  additively, and that `target_titles_remove` drops a generated entry.
- **Notes:** The cache-key assertion belongs to M4-T3, which is where the decision
  cache is built — do not try to verify it here.
  **Verified 2026-09-24:** 19 stub-backend tests in `tests/test_profile.py`
  (full suite 77/77), and a live run against the real resume via `claude -p`
  (haiku): `profile --show` prints 51 skills, 9 target titles, `profile_version: 1`.
  Contract 1 = `profile.resume_ingest.load_derived_profile(cfg)`; read-only, never
  calls the model — the pipeline calls `ingest(cfg)` first (a no-op unless
  something changed). CLI: `profile` (ingest if changed, then show), `--show`
  (read only), `--refresh` (force the model call), `--bump`.
  **`profile_version`** is engine-owned and only rises: on a re-derive whose
  content differs, on an overrides *content* change (no model call; comments do
  not count), or by `profile --bump`. An identical re-derive keeps the version.
  M4-T3 just keys on the merged profile's `profile_version`.
  **Extensions beyond 8.3[1]:** `skills_remove` (mirror of `target_titles_remove`);
  unknown override keys and `profile_version` in overrides are errors.
  **Live-model findings, now handled:** sent bare, haiku wrote Markdown instead
  of JSON (resume is now fenced, contract restated after it); `graduation` came
  back as an object and `title_aliases` as a list (both coerced); bundled skills
  like `typescript/javascript` are split; invented titles (`backend software
  engineer`) are prevented by anchoring the prompt to common posting titles.
  **Open:** Q3 (re-decide on bump) left as specced. The model still reports
  `years_experience: 1` for an all-internship resume — correct it in
  `config/profile.overrides.yaml` if wrong.

#### M2-T3 · Keyword/skill matcher
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** `profile/keywords.py` — overlap score between a posting and the derived
  skills. Simple, explainable, no BM25: normalised token overlap with weights for
  multi-word skills. Must report *which* skills matched, for the UI.
- **Verify:** Test asserts a backend JD scores above the floor and a marketing JD below it.
- **Notes:** Verified 9/9 (`-k keywords`), full suite 86/86. Contract 2 exactly:
  `profile.keywords.overlap(text, skills) -> (score, matched)`, matched in skill
  order, as given. Whole-token consecutive match after light folding (plural
  `s`, `.js`, k8s/postgres/golang aliases); each skill counts once; multi-word
  skills weigh 2, single 1. `go`/`c`/`r` match only capitalised or spelled out,
  so "go-to-market" is not Go. Against the **real** derived skills: synthetic
  backend JD 12, marketing JD 0 (floor 2). Known limit: a skill the model
  wrote with a filler word (`ci/cd pipelines`) will not match plain "CI/CD" -
  fix such entries with `skills_remove`/`skills` in the overrides.

---

### M3 — Scrape

**Outcome:** postings flow from the watchlist into the new store.

#### M3-T1 · Port the store to the new schema
- **STATUS:** `DONE`
- **Completed:** 2026-09-24 — `-k store` 17/17, full suite 63/63.
  **How v1 keeps running:** v1's store was `git mv`'d to `store_v1.py` unchanged
  (LEGACY, retired in M9-T1) and its seven importers repointed, rather than
  rewriting `store.py` in place and breaking them all. Each store refuses the
  other's database (`SchemaMismatch` / `RuntimeError`) because both default to
  `data/jobscraper.db`. The bridge DB was **archived, not deleted**, to
  `archive/v2-bridge-db-2026-09-24/`.
  **Schema additions beyond §8.4, deliberate:** `companies.key` (the §8.4 sync
  semantics need it and the table list omitted it), `resolve_method`/`resolved_at`
  (discovery writes them), `applications.company/role/url` (an orphaned
  application must stay legible, D-14), `coverage.http_status`, a `meta` table
  holding `schema_version`. `models.WatchedCompany` is the v2 row type; v1
  `Company` stays for legacy modules. Timestamps are UTC `YYYY-MM-DDTHH:MM:SS`
  text; cut-offs are computed in Python (`store.shift`) so the SQL stays plain.
  §0.6 contract 5 is implemented and tested. Until M3-T1b lands, the v1 commands
  (`doctor`, `run`, …) fail cleanly against the v2 DB instead of corrupting it.
- **Do:** Rewrite `store.py` to §8.4. Keep the single-writer rule and the
  `known_job_ids` / `close_missing` semantics (a failed fetch must never close jobs).
  **First delete the existing `data/jobscraper.db`** — it is a v1-schema file the
  M1-T4 bridge created (224 company rows, no jobs, no `last_scraped_at`). It holds
  nothing worth keeping and will not migrate. See §0.5.
- **Verify:** `python tests/run_tests.py -k store` passes, including the carried-over
  `test_failed_fetch_must_not_close_jobs`.

#### M3-T1b · Watchlist → `companies` sync
- **STATUS:** `DONE`
- **Completed:** 2026-09-24 — `-k sync` 9/9 (8 new + v1's `sync_applied`),
  full suite 71/71. `_sync` deleted; `doctor` and `sync` run on the v2 store
  (live: first sync 229 added / 224 enabled, second sync 0 added — idempotent).
  Beyond the Verify list: a resolution discovery *learned* survives a sync whose
  YAML omits it (`COALESCE`), while a `careers_url` change keeps only what the
  YAML states; `last_scraped_at` survives a URL move (staleness is history, not
  resolution); `enabled: false` in the YAML is honoured. Legacy `run`/`resolve`/
  `status` now stop with a clear "v2 database" error until M3-T3/M3-T4 replace them.
- **Do:** `store.sync_watchlist(entries)` implementing the identity and sync
  semantics in §8.4 exactly: match on `key`, insert new as due, update descriptive
  fields only, clear resolution when `careers_url` changes, disable (never delete)
  keys absent from the YAML. Called at the start of every run, before the scheduler.
  Read v1's `store.py::sync_companies` first — it solved the same problem.
- **Verify:** `python tests/run_tests.py -k sync` passes and **must include:**
  renaming a company's `name` keeps its `last_scraped_at` and failure counters;
  changing its `careers_url` clears `provider`/`slug`/`feed_url`; removing an entry
  sets `enabled=0` and leaves its jobs and applications intact; re-adding it
  restores it without resetting history.
- **Notes:** **This task is why nothing else works without it.** The scheduler reads
  SQL; the watchlist is YAML; before this, nothing bridged them.
  **There is a bridge in place right now and it is wrong** (§0.5): M1-T4 repointed
  `cli.py::_sync` at the watchlist to keep four commands alive, but it still routes
  through v1's `sync_companies`, which keys rows on the **display name**. Until this
  task lands, renaming a company resets its scrape history — the precise failure
  §8.4 exists to prevent. Delete `_sync` as part of this task; do not leave both.

#### M3-T2 · Point discovery and adapters at the watchlist
- **STATUS:** `DONE`
- **Completed:** 2026-09-24 — `-k scrape` 7/7 (all four discovery corroboration
  tests), full suite 83/83, layering guard green with the three files now checked
  as the `scrape` stage. `git mv` into `scrape/` (history preserved); the only
  edits are import paths and the input annotation `Company` → `WatchedCompany`
  (the fields they read — name, careers_url, provider, slug, feed_url — are
  identical). No logic changed. Importers repointed: `cli.py`, legacy `runner.py`,
  `tests/test_scrape.py`. `net` is still listed in the guard's FOUNDATION set;
  harmless (no top-level `net` remains) and tidied in M9.
- **Do:** Move `adapters.py`, `discovery.py`, `net.py` under `scrape/`. Change only
  their *input type* (watchlist entry instead of Excel-derived `Company`). No logic changes.
- **Verify:** `python tests/run_tests.py -k scrape` passes, including the four
  carried-over discovery corroboration tests (`test_board_must_corroborate_the_company_name`,
  `test_slug_alone_corroborates_*`, `test_demo_boards_are_rejected`,
  `test_aggregator_urls_never_yield_a_slug`).

#### M3-T3 · Staleness scheduler
- **STATUS:** `DONE`
- **Completed:** 2026-09-24 — `-k scheduler` 10/10, full suite 81/81; live
  `status` on the real DB: 224 due, 23 runs to drain, "a full sweep needs 1.6/day".
  All five mandatory cases are tested. The last one ("with all 229 fresh the
  runner exits 0 reporting the next due date") is proved at the scheduler level
  here (`plan()` returns empty + `next_due_at` = oldest stamp + 14 days); the
  runner half is asserted end to end in M3-T4, which builds the runner.
  **Design notes:** the due query lives in `store.due_companies` (only store.py
  holds SQL) with a Python-computed cut-off instead of `datetime('now', …)`, so
  the §8.4 "SQLite-only exception" no longer exists and tests pin the clock.
  "NULLs first" is spelled `CASE WHEN … IS NULL` (portable). **Quarantined
  companies are excluded from the due query** — §8.3[0]'s SQL omits the clause,
  but its prose keeps v1's quarantine/probation; they return only via
  `store.due_probation`, which M3-T4 merges into the batch. The three v1 cursor
  tests are ported as staleness equivalents; v1's `--force` test is retired (a
  staleness queue has no cycle boundary to force past). `status` CLI now reads
  the scheduler. **Pending:** the `ecc:database-reviewer` pass on the due query
  is deferred until an agent slot frees up (4-agent cap, §0.6).
- **Do:** `scheduler.py` per §8.3[0] — the due query, `batch_size: 10` (D-13),
  `cycle_days: 14`, stamping `last_scraped_at` on **attempt**. Port the meaningful
  `cursor.py` tests onto it. Add the `status` report (due now / due in 7 days /
  never scraped / quarantined / projected sweep completion).
- **Verify:** `python tests/run_tests.py -k scheduler` passes and **must include**:
  a company scraped 13 days ago is not due; at 15 days it is; never-scraped sorts
  ahead of both; a failed fetch still stamps `last_scraped_at`; and with all 229
  fresh, the runner exits 0 reporting the next due date rather than scraping.
- **Notes:** This is the task that makes "loop back to company 1" work. Use
  `ecc:database-reviewer` on the due query and its index.

#### M3-T3b · Migrate v1 application history
- **STATUS:** `DONE`
- **Completed:** 2026-09-24 — `scripts/migrate_v1_applications.py`; Verify reports
  **3**, and re-running adds 0 (idempotent). **The "≥ 5" threshold below was
  wrong and is corrected to ≥ 3:** two of the five v1 rows were test fixtures that
  leaked into the live v1 DB (`C4`/`R4` at `https://e/4`, `C5`/`R5` at
  `https://e/5` — no real host). They are reported and skipped, not migrated as
  fake applications. Migrated: 2 × Jane Street `applied` (applied date
  2026-09-16 preserved exactly via `applied_at=`) and 1 × Jane Street `to_apply`
  (v1 `applied = 0`: ticked, then unticked). Each got one `app_events` row. All
  three are orphans until re-scraped; `Store.relink_orphan_applications()` moves
  an application and its history onto the real job id by URL, and **M3-T4 calls
  it after every run's persist step.**
- **Do:** Port the `applications` rows from `archive/v1-2026-09-23/data/jobscraper.db`
  into the new
  `applications` + `app_events` tables (D-14), matching on **job URL** — v1 job ids
  are hashed with a company id that no longer means anything. Rows whose posting is
  never re-scraped are kept as orphans, retaining company, role, URL and applied
  date. Seed one `app_events` row per migrated application.
- **Verify:** `python -c "import sqlite3;c=sqlite3.connect('data/jobscraper.db');print(c.execute('select count(*) from applications').fetchone()[0])"` reports ≥ 3 — every archived row with a real URL (v1 held 5 rows, 2 of them test fixtures; 2 applied, dated 2026-09-16).
- **Notes:** Small in volume, but it is the only data in the v1 DB that re-scraping
  cannot regenerate. §6's "migrating v1 job data is out of scope" does not cover it.

#### M3-T4 · Scrape stage in the pipeline
- **STATUS:** `DONE`
- **Completed:** 2026-09-24 — **live Verify:** `run --dry-run` twice selected the
  same 10 (1Password → Alibaba), fetched 1,275 postings (8 ok, 2 failed), and
  left `jobs`/`runs`/stamps at 0/0/0. `-k pipeline` 8/8 with a stub fetcher;
  full suite 91/91. `pipeline.run` replaces `runner.run_batch` behind `run`;
  `--force` is gone (no cycle boundary to force past).
  **Failure policy carried over** (isolation, classify-and-skip, threshold →
  one re-resolve → quarantine, probation) **with one v1 bug fixed:** v1's
  global-failure guard called `rollback_failures` without ever having recorded
  that run's failures, so an outage silently *forgave an earlier genuine
  failure*. v2 records none and **stamps none** on `aborted_unhealthy` — a local
  outage should not cost the batch a whole cycle; re-running retries it.
  Crash recovery: stale `running` rows are reaped at start (`run.per_run_timeout`,
  new config key, 3600 s); stamping is the last write. Dry run still syncs the
  watchlist (config reconciliation, idempotent) but persists nothing a run
  produces, including discovery results. `relink_orphan_applications` runs after
  every persist. **Not yet wired:** stages [3]–[6] (prefilter → decide →
  shortlist) — M4-T3/M5-T1, now that lanes B and D have landed their pieces.
  Postings without a description are not hydrated yet; v1 hydrated only
  prefilter survivors, and that belongs with the M4 wiring.
- **Do:** `pipeline.py` stage [2]: sync watchlist (M3-T1b) → take the due batch
  (M3-T3) → resolve → fetch (parallel, isolated) → diff → persist jobs and coverage.
  Carry over quarantine/probation and the global-failure-abort guard from
  `runner.py`. **`--dry-run` semantics:** fetches and reports, but writes **nothing**
  — no jobs, no coverage, and **it does not stamp `last_scraped_at`**, so a dry run
  never consumes the queue.
- **Verify:** `python -m jobscraper run --dry-run` selects exactly 10 due companies
  and fetches them; re-running it immediately selects **the same 10** (proving the
  queue was not consumed) and the `jobs` table row count is unchanged.

---

### M4 — Filter & decide

**Outcome:** the expensive step is small, cheap and correct.

#### M4-T1 · Prefilter rules + the rules.yaml contract
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** `filter.py` per §8.3[3]. Implement the four rule *kinds* (`regex_deny`,
  `any_match`, `max_number`, `overlap_floor`) behind a registry so a fifth kind is a
  new function, not a rewrite. Honour declaration order, `enabled:`, and the
  `extra:` merge. Record rule id + matched text for every rejection in `prefilter`.
- **Verify:** `python tests/run_tests.py -k filter`. **Must include:**
  - D-7 — `Remote, Global`, `Remote (APAC)`, `Hybrid — Austin, US` all reject;
    `Singapore`, `Singapore, Singapore` and blank all pass through.
  - D-10 — `Site Reliability Engineer` passes `title_allow` via `target_titles`;
    `Technical Writer` is rejected by it.
  - Order — `Senior Software Engineer` is rejected by `title_deny`, not accepted by
    `title_allow`.
  - D-12 — `4+ years` rejects, `3+ years` passes, `2-5 years` **passes** (lowest
    stated wins, per §8.3[3]; this is the semantics `test_min_years_takes_the_lowest_stated`
    already asserts, so the carried-over test and this one must agree).
  - Extensibility — setting `enabled: false` disables a rule, and an `extra:` entry
    takes effect without editing code.
- **Notes:** Verify = `-k filter` 19/19 (14 new + the 4 carried-over v1 tests,
  `test_min_years_takes_the_lowest_stated` included, + 1 watchlist match). Contract
  3 as written: `load_rules(path)` (path optional, defaults to `config/rules.yaml`)
  → `RuleSet(.hash = sha256 of the canonical-JSON of the parsed YAML, 64 hex, so
  comments/spacing don't change it)`; `evaluate(posting, ruleset, profile, scorer)`
  → `FilterResult(passed, reject_rule, reject_detail, overlap_score, trace)`;
  posting may be a dict or an object. `filter.render(result)` formats it for the
  CLI. Registry: `@filter.rule_kind(name, prepare=)`, proven by a test that adds a
  fifth kind. No `profile/` or `matching.py` import — location/years logic ported.
  **Deviations from the §8.3[3] YAML, all deliberate:** (1) the `experience_ceiling`
  pattern is range-aware (`(?<!\d)(\d{1,2})…(?:-|–|to)…years?|yrs?`) — the PRD's
  `(\d+)\s*\+?\s*(?:years|yrs)` reads "2-5 years" as **5** and would reject it,
  contradicting D-12's lowest-wins; `filter.min_years_required` is held equal to
  v1's by a test. (2) `keyword_floor` has `skip_when_empty: description` — a
  posting with no JD text is passed to the model rather than rejected for 0
  overlap (listing-only adapters would otherwise lose everything). (3)
  `location_explicit` is `regex_deny` in default-deny mode (`allow_tokens` set);
  a location that is only filler (`Hybrid`, `On-site`) passes as vague. (4) Every
  rule is evaluated for the trace; the first reject still decides. Per the §8.3[3]
  table, `Singapore-based role, US only` **passes** (allow token wins) — the
  prose claim that v1's residue logic rejects it is not what v1 did either.
  Persisting the result into the `prefilter` table is the store's/pipeline's job
  (M3-T1/M3-T4): `FilterResult` carries every column it needs.

#### M4-T1b · Filter tuning tools
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** `filter explain <job_id>` and `filter test --title/--location/--desc`
  per §8.3[3]. Both read-only; `test` touches no database.
- **Verify:** `python -m jobscraper filter test --title "Senior Backend Engineer"
  --location "Singapore"` prints the deciding rule (`title_deny`) and the matched
  token (`senior`).
- **Notes:** Do not defer this. Tuning five rules against 20,000 postings without
  an explain command is guesswork.
  *2026-09-24 (Lane B):* **`filter test` done** — the Verify command prints
  `REJECT by title_deny: senior` and marks the deciding rule; tests
  `test_filter_cli_*`. Extra flag `--rules <file>` dry-runs a draft rules file.
  Profile source: `data/profile.derived.yaml` when present (via Lane D's
  `load_derived_profile(cfg)` once merged; raw YAML, overrides unapplied, until
  then). When absent, every rule whose `source`/`aliases` reads `profile.*`
  (today `title_allow`, `keyword_floor`) is shown `DISABLED` and a WARNING goes
  to stderr — not silently skipped. Scorer: `profile.keywords.overlap` once
  merged, else none (overlap rules show `SKIP`). **`filter explain <job_id|url>`
  done after merging `v2-rebuild` (M3-T1 landed):** reads the job via the v2
  `Store.get_job`/`find_job_by_url`, shows the stored `prefilter` row for
  (profile_version, current rules hash) — or says why there is none — beside a
  live re-evaluation giving every rule's verdict and matched text. Read-only; it
  refuses to create a missing DB. Tests `test_filter_cli_explain_*`.

#### M4-T2 · Vital extract
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** `decide.py::vital_extract()` per §8.3[4], ≤800 chars, `UNSTATED` markers.
- **Verify:** Test asserts output ≤800 chars on a real 12k-char JD fixture **and**
  that the location and years-of-experience strings survive the reduction.
- **Notes:** Verify = `python tests/run_tests.py -k vital` (4/4). Two *real* JDs,
  copied verbatim from the v1 archive's `jobs` table, no composition needed:
  `tests/fixtures/jd_edge_infrastructure_warsaw.json` (12,004 chars → 606) and
  `jd_account_executive_singapore.json` (12,076 → 792). Budget is spent in
  post-condition order (LOCATION, EXPERIENCE, REQUIREMENTS, ROLE) so location and
  years are never the part that gets cut; numbered-years sentences outrank other
  experience sentences. REQUIREMENTS drops sentences EXPERIENCE already carries.
  v1's `REQ_HEADINGS` was **ported** into decide.py and extended (`what we require`,
  role headings, stop-headings) rather than imported: matching.py is LEGACY (M9).
  `title` is accepted per contract 4 but not echoed — the decide prompt carries it.

#### M4-T3 · Decision call + accept guard
- **STATUS:** `DONE`
- **Completed:** 2026-09-24 — `-k decide` 24/24 (11 new), full suite 183/183.
  All three mandatory stub cases store `reject`: `is_singapore: null`,
  `is_singapore: false`, and `yoe_min: 4`. Also covered: a merely truthy
  `"yes"` is not Singapore; the cache means a posting is never paid for twice; a
  changed extract is re-decided; batches split by `decide_batch`; malformed
  output and dead transports store nothing (retried next run); fenced JSON parses.
  **Shape:** `decide.decide(postings, summary, backend, model, lookup, save, …)`
  — the store is injected as two callables, so `decide` stays a stage that knows
  no SQL and the pipeline owns persistence. `guard()` is the §8.3[5]
  post-condition, applied before anything is stored. Prompt carries only the
  derived summary + extracts (no company prestige, no tier), wraps each posting
  in `<posting>` tags and tells the model that text is data, not instructions.
  Wiring into `pipeline.run` lands with M5-T1.
- **Do:** Batched cheap-model call via `backends.py`, cached by
  `hash(job_id + vital_text + profile_version)`. Implement **both** §8.3[5]
  post-conditions (location and the 3-year cap).
- **Verify:** Tests feed a stub backend and assert the stored decision is `reject` for
  `{"decision":"accept","is_singapore":null}`, for `is_singapore:false`, and for
  `{"decision":"accept","is_singapore":true,"yoe_min":4}` (D-12).

#### M4-T4 · Measure the hypothesis
- **STATUS:** `NOT_STARTED`
- **Completed:** —
- **Do:** Run one real batch. Record in this file: tokens/posting, survivor rate,
  and a hand-audit of 30 accepted roles for the location metric (§5).
- **Verify:** Numbers written into §5's table and into `runs.stats_json`.
- **Notes:** This is where the §2 assumption about vital extract gets validated or falsified.

---

### M5 — Shortlist

#### M5-T1 · Shortlist writer
- **STATUS:** `DONE`
- **Completed:** 2026-09-24 — `tests/test_shortlist.py` 5/5: delete + regenerate
  is byte-identical modulo `generated_at`; no `status`/`applied`/`applied_at` key
  even with an application recorded (D-5); closed roles kept with
  `"closed": true` (Q4); order `(run_no DESC, company ASC, id ASC)`, runs
  `run_no DESC`. Written atomically (tmp + `os.replace`) so the web app never
  reads half a file. `runs` lists `ok` runs only.
  **Stages [1] and [3]–[6] are now wired into `pipeline.run`** (`_funnel`):
  resume ingest (no-op unless the resume changed) → prefilter over every open
  posting lacking a verdict for the current `(profile_version, rules_hash)` →
  descriptions hydrated **only for postings that already passed title +
  location** (v1's discipline), then re-checked → vital extract → decide (cache
  first; skipped with an `awaiting_model` count if the backend is off) →
  shortlist. Selection is by *what is missing*, not by run number, so a rules
  edit re-checks the corpus and a failed model call is retried next run.
  `stats_json` now carries the §8.4 metric keys. `-k pipeline` 11/11 (3 new
  funnel tests with a stub model), full suite 191/191.
  **Incident, fixed:** the first wiring ran the existing pipeline tests against
  the *real* `claude -p` backend and the real `data/shortlist.json`, because the
  tests used the live config. Stopped within ~2 minutes; the shortlist it wrote
  held 0 jobs and has been regenerated from the real DB. The pipeline tests are
  now hermetic (temp paths, a fixed profile, `OffBackend` by default).
  **Not built:** `matched_skills` on shortlist jobs (the Inbox renders it if
  present; §8.3[6] does not list it) and per-company `coverage.accepted_count`.
- **Do:** `shortlist.py` writes `data/shortlist.json` per §8.3[6]. Regenerated,
  never hand-edited, never holds application status (D-5). **Deterministic order:**
  `jobs` sorted by `(run_no DESC, company ASC, id ASC)`; `runs` by `run_no DESC`.
  Include jobs whose `closed_at` is set, with a `"closed": true` flag — the web app
  marks them stale rather than hiding them, so a role you were about to apply to
  does not vanish without explanation *(resolves Q4)*.
- **Verify:** Delete the file, re-run the writer, byte-compare against the previous
  copy modulo `generated_at` — identical. A second test asserts **no** key named
  `status`, `applied` or `applied_at` appears anywhere in the output (D-5).

---

### M6 — Web API

#### M6-T1 · FastAPI app + read endpoints
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** `web/api.py` with `/api/runs`, `/api/shortlist`, `/api/applications`,
  `/api/stats`. One router file per domain (§8.5).
- **Verify:** `python tests/run_tests.py -k web` passes with `TestClient` and
  **must assert:** each route returns 200 with the documented shape; `?run=latest`
  and `?run=<n>` return different sets; `?run=99999` returns an empty list, not a
  500; a shortlisted job with no application row still appears, with a null status
  (the join must not drop it).
- **Notes:** Verified 2026-09-24 (Lane C): `-k web` 20/20, against the real M3-T1
  store in a temp dir and `tests/fixtures/shortlist.json`. Routers live in
  `web/routers/{runs,shortlist,applications,stats}.py` and are auto-discovered;
  the D-5 join is in `web/data.py`. `/api/shortlist` returns a bare list;
  `?run=` other than `latest|all|<n>` is a 422. `/api/applications` inlines each
  row's `events` (oldest first) for M8-T1. `/api/stats` also serves the ordered
  `statuses` vocabulary from config, for M8-T1's dropdown.
  Web modules import `jobscraper.*` absolutely: the layering guard reads the first
  segment of a relative import (`from .deps`) as a top-level module and would
  flag it.

#### M6-T2 · Write endpoint + event history
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** `POST /api/applications/{job_id}` upserts `applications` and appends to
  `app_events`. Idempotent; re-posting the same status must not duplicate an event.
- **Verify:** Test posts `applied` twice and asserts exactly one `app_events` row.
- **Notes:** Verified 2026-09-24 (Lane C):
  `test_web_posting_applied_twice_appends_exactly_one_event` passes (the second
  POST returns `event_appended: false`). Body is `{status, notes}` plus optional
  `company`/`role`/`url`, passed to `set_application_status` so the row still
  describes the job after the posting leaves the shortlist. A status outside
  `applications.statuses` is a 422 with no write. A non-JSON body is a 422, so a
  cross-site HTML form cannot write.

---

### M7 — Web UI

#### M7-T1 · Vite + Vue scaffold, builds into the package
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** `web/` project, output to `src/jobscraper/web/static/`. Document the build
  in README. FastAPI serves the built assets at `/`. Add **Vitest** + Vue Test Utils
  so M7-T3 and M8-T1 have something falsifiable to assert; wire `npm test`.
- **Verify:** `npm run build` produces `src/jobscraper/web/static/index.html`,
  `npm test` runs and passes (≥1 real component test), and `python -m jobscraper web`
  serves the page at `http://127.0.0.1:8765`.
- **Notes:** Without a frontend test runner, every UI task below is manual-only and
  nothing guards against regression on day 4.
  Verified 2026-09-24 (Lane C): `npm run build` writes `static/index.html` + hashed
  assets; `npm test` 1/1 (Vitest 5, jsdom); `python -m jobscraper web` served the
  mounted Vue page at `http://127.0.0.1:8765`, no console errors. Build docs are in
  `web/README.md` (README is the Lead's; link it from there). Routers in
  `web/routers/` are auto-discovered so M7-T4 stays a 3-file change. Vitest pinned
  to 5.x: 3.x carries advisory GHSA-82fw-gwwq-j7x9.

#### M7-T2 · Tab shell + run selector
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** The `TABS` registry (§8.5), plus the run selector that swaps the dataset
  in place. **One page for all runs** — this is the core of requirement (2).
- **Verify:** Changing the run selector issues one `GET /api/shortlist?run=<n>` and
  navigates nowhere; no new HTML file is produced anywhere.
- **Notes:** Verified 2026-09-24 (Lane C) in the browser against
  `tests/fixtures/shortlist.json` and a scratch v2 store: selecting run 11 made
  exactly one request (`/api/shortlist?run=11`), with the same document (a
  `window` marker survived) and the same URL; `git status` showed no HTML beyond the
  rebuilt `static/index.html`. Also asserted in Vitest (`web/tests/App.test.js`).
  `/api/runs` and `/api/shortlist` landed here because the selector needs them;
  they already run on the real M3-T1 store. Runs come from `Store.list_runs()`,
  with per-run `accepted` taken from the shortlist, so a run that accepted nothing
  still appears in the selector.

#### M7-T3 · Inbox tab
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** Scrollable list: company, title, location, yoe, reason, matched skills,
  `Open ↗`, `Mark applied`, `Dismiss`.
- **Verify:** Manual — open the page, mark one applied, reload, status persisted.
- **Notes:** Verified 2026-09-24 (Lane C) in the browser, on the fixture shortlist
  and a scratch v2 store: marked OKX applied, reloaded, and OKX showed `applied`
  with its button disabled. The DB held one `applications` row and one `app_events`
  row (`None -> applied`). Covered by 11 Vitest tests (`web/tests/Inbox.test.js`).
  Dismiss is **session-local** (sessionStorage, no server write) pending Q2.
  Only `http(s)` URLs become links, since posting URLs are third-party data.
  §8.3[6] has no matched-skills field, so the card shows `matched_skills` only
  when a job carries it.

#### M7-T4 · Prove extensibility with a throwaway tab
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** Add a trivial "Stats" tab by touching **only** `tabs.js`, one `.vue`
  file, and one router. Record in `Notes:` every file changed. Then revert it.
- **Verify:** `git status --porcelain` lists exactly 3 changed/added files (requires
  M0-T0). If it lists more, the tab architecture has failed its requirement — fix
  the architecture, not the diff. Then `git checkout -- .` to revert the probe.
- **Notes:** Verified 2026-09-24 (Lane C). `git status --porcelain` listed exactly
  3 files: ` M web/src/tabs.js`, `?? web/src/tabs/Stats.vue`,
  `?? src/jobscraper/web/routers/stats_probe.py`. The probe router answered
  `/api/stats-probe` with no other edit (discovery works), `npm test` passed with the
  tab bar rendering both tabs, a scratch-dir `vite build` emitted a `Stats` chunk,
  and the layering guard stayed green. Reverted with `git checkout -- .` plus
  deleting the two untracked files, which `checkout` leaves behind. The router is
  named `stats_probe` because `/api/stats` already exists (M6-T1). The committed
  `static/` bundle was not rebuilt, so shipping a real tab also means committing a
  rebuilt bundle (see `web/README.md`).

---

### M8 — Application tracking

#### M8-T1 · Applications tab
- **STATUS:** `DONE`
- **Completed:** 2026-09-24
- **Do:** Table of everything with a status, grouped by status, with the
  `app_events` timeline per row and inline status change.
- **Verify:** Manual — advance a role through `applied → interviewing`, confirm
  both events appear in order.
- **Notes:** Verified 2026-09-24 (Lane C) in the browser on a scratch v2 store: OKX
  (applied in M7-T3) moved to `interviewing` with the inline dropdown. After a
  reload it sat in the `interviewing` group with timeline `applied 00:53 UTC` →
  `interviewing 00:57 UTC`, no console errors. 6 Vitest tests in
  `web/tests/Applications.test.js`. The tab ignores the run selector, since an
  application outlives its run. The dropdown's options come from `/api/stats`
  `statuses` (config `applications.statuses`), so M8-T2 should need no UI change.

#### M8-T2 · Status vocabulary in config
- **STATUS:** `NOT_STARTED`
- **Completed:** —
- **Do:** Put the application-status list in **`config/config.yaml`** under
  `applications.statuses`, served to the UI by `/api/stats` or a small
  `/api/meta` endpoint. **Not** `rules.yaml` — that file is the prefilter contract
  (§8.3[3]) and mixing an unrelated vocabulary into it breaks its `rules_hash`
  (§8.4), needlessly re-evaluating every posting whenever a status is added.
- **Verify:** Add `on_hold` to config, restart, confirm it appears in the UI dropdown
  with no code change and `prefilter` rows are **not** invalidated.

---

### M9 — Cutover

#### M9-T1 · Retire v1 modules
- **STATUS:** `NOT_STARTED`
- **Completed:** —
- **Do:** Move `output.py`, `serve.py`, `ingest.py`, `cursor.py`, `runner.py` and the
  retired half of `matching.py` to `archive/`. Point `review.py` at the new schema.
- **Verify:** `python -c "import ast,pathlib,sys; bad=[(p,n.lineno) for p in pathlib.Path('src').rglob('*.py') for n in ast.walk(ast.parse(p.read_text(encoding='utf-8'))) if (isinstance(n,ast.ImportFrom) and (n.module or '').split('.')[-1] in {'output','serve','ingest','cursor','runner'}) or (isinstance(n,ast.Import) and any(a.name.split('.')[-1] in {'output','serve','ingest','cursor','runner'} for a in n.names))]; print(bad); sys.exit(1 if bad else 0)"` exits 0, and `python tests/run_tests.py` passes.
- **Notes:** The check parses imports with `ast` rather than grepping for
  `import output` — v1's actual style is `from .output import (...)`, which a
  naive grep misses entirely, letting this task pass while every import remains.

#### M9-T2 · Rewrite README and DESIGN for v2
- **STATUS:** `NOT_STARTED`
- **Completed:** —
- **Do:** README reflects the watchlist, the new workflow, the web app and the build
  step. `docs/DESIGN.md` gets the §8.1 diagram and the §7 decision register.
- **Verify:** Follow the README top to bottom in a clean clone and a fresh venv,
  executing only commands it contains, and reach a working page at
  `http://127.0.0.1:8765`. Record in `Notes:` every step where you had to know
  something the README did not say; each one is a defect to fix before `DONE`.

#### M9-T3 · End-to-end acceptance
- **STATUS:** `NOT_STARTED`
- **Completed:** —
- **Do:** One full cycle on the curated watchlist: sync → schedule → scrape →
  filter → decide → shortlist → apply in the web app → status persists.
- **Verify:** Every §5 metric **except** "spin-up from clone" measured and recorded
  in this file (that one belongs to M10-T2, which runs after this milestone).
- **Notes:** Run `/ecc:code-review` over the full diff before closing M9.

---

### M10 — Spin-up (Docker)

**Outcome:** `docker compose up` and it works. Cloud is *considered*, not built.

#### M10-T1 · Dockerfile
- **STATUS:** `NOT_STARTED`
- **Completed:** —
- **Do:** Multi-stage build per §8.6 — node stage builds the Vue bundle, slim
  Python stage runs the app. No node in the final image. Non-root user.
- **Verify:** `docker build -t jobscraper .` succeeds and
  `docker run --rm jobscraper python -m jobscraper doctor` runs.

#### M10-T2 · docker-compose + volumes
- **STATUS:** `NOT_STARTED`
- **Completed:** —
- **Do:** One service; `data/` as a named volume; `config/` read-only; `~/.claude`
  read-only for the model transport (D-11); port 8765 bound to `127.0.0.1`.
  Document `docker compose run --rm app run` for a batch.
- **Verify:** `docker compose up` serves the app; stopping and restarting preserves
  application statuses (proves the volume works).
- **Notes:** Run `/ecc:security-review` on the compose file. Do **not** bind `0.0.0.0`.

#### M10-T3 · Keep the no-Docker path working
- **STATUS:** `NOT_STARTED`
- **Completed:** —
- **Do:** Commit the built frontend assets so a plain `pip install -e .` +
  `python -m jobscraper web` works with no Docker and no node.
- **Verify:** In a clean venv with node absent, `python -m jobscraper web` serves a
  working UI.
- **Notes:** This is what stops the node toolchain becoming a single point of failure
  (R-3).

---

## 11. Open Questions

- [x] **Q1 — Scheduling. RESOLVED 2026-09-23 (D-9).** Per-company staleness
  timestamps, batch of 10, 14-day window. `cursor.py` retires.
- [ ] **Q6 — Run cadence.** 229 companies ÷ 10 per run = **23 runs per 14-day cycle,
  ~1.6 runs/day**. How will runs actually be triggered — by hand, Task Scheduler,
  or a container loop? If the real rate is lower, either the batch rises above 10 or
  the watchlist shrinks (M1-T3). *Decide after M3-T3 measures a real run's duration.*
- [ ] **Q2 — Dismiss semantics.** Does `Dismiss` in the Inbox hide the role forever,
  or only for that run? *Decide at M7-T3.*
- [ ] **Q3 — Re-decide on profile change.** Bumping `profile_version` invalidates every
  cached decision, which re-runs the model over the whole corpus. Acceptable, or should
  re-decision be opt-in per run? *Decide at M2-T2.*
- [x] **Q4 — Closed postings. RESOLVED 2026-09-23.** Keep them in the shortlist with
  a `"closed": true` flag; the UI marks them stale rather than hiding them.
  Specified in M5-T1.
- [ ] **Q5 — Is 800 characters enough?** The vital-extract budget is an estimate.
  *Validated or falsified at M4-T4.*

## 12. Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | Vital extract drops the deciding sentence, causing wrong rejects | Medium | High | M4-T2 asserts location and YOE survive; M4-T4 hand-audits 30 decisions before trusting it |
| R-2 | Hard Singapore-only filter (D-7) rejects genuine SG roles labelled `Remote` | Medium | Medium | D-2 routes vague/blank locations to the model; `prefilter` records every rejection with its rule, and `filter explain` (M4-T1b) makes misses findable |
| R-3 | Node/Vite build rots or blocks a Python-only environment | Medium | Medium | M10-T3 commits built assets and verifies the app runs with node absent |
| R-4 | `title_allow` (D-10) is too narrow and silently hides good roles | **Medium** | **High** | The generated list is *additive* with a user `extra:`; M4-T4's audit must count `title_allow` rejections specifically, and the rule can be disabled with one YAML line |
| R-5 | Scope creep in the web app | Medium | Medium | Tabs are the only extension point; M7-T4 enforces the 3-file rule |
| R-6 | A cheap model is too weak for borderline calls | Low | Medium | The M4-T3 post-conditions make the two costly failure modes (wrong location, too senior) impossible by construction |
| R-7 | **Run cadence unmet** — 23 runs per cycle needed at batch 10 | **High** | Medium | Staleness queue degrades gracefully (longest-neglected first, no starvation) instead of breaking; `status` surfaces projected completion so drift is visible, not silent; batch size is one config line |
| R-8 | **Docker cannot carry Claude Code auth** (D-11) | **High** | **High** | Local: mount `~/.claude` read-only, verified in M10-T2. Cloud: needs an API key or another transport — which is *why* cloud is out of scope, not an oversight |
| R-9 | Web app has no authentication | High | Low *(now)* / High *(if exposed)* | Binds `127.0.0.1` by default, never `0.0.0.0`. Any cloud exposure requires auth first — a blocking prerequisite, recorded here |
| R-10 | Agent marks tasks done without verifying | Medium | High | §0.1 makes the `Verify:` command the sole source of truth |
| R-11 | Seeded 229-company watchlist (D-4) carries v1's stale/dead careers URLs | Medium | Low | v1 measured 66 companies that never fetched successfully; M1-T2 disables the 5 quarantined ones and `status` surfaces repeat failures for pruning |
| R-12 | Run crashes mid-flight, leaving `runs.status='running'` and partial state | Medium | Low | Ordering in §8.3[0] makes a crash a no-op: the stamp happens last, content-hashed caches resume safely, and the next run reaps stale `running` rows |
| R-13 | Tripled scrape frequency (D-13: 10/run instead of 30) breaches a site's rate limit or robots policy | Low | Medium | `net.py` carries over unchanged with per-host delay and robots support; frequency rises but per-host concurrency does not, since a batch of 10 spans 10 different hosts |
| R-14 | Renaming a company in the YAML silently resets its history | **Was High** | High | Eliminated by design: §8.4 keys rows on `key`, not `name`, and M3-T1b tests the rename case explicitly |

## 13. Glossary

| Term | Meaning |
|---|---|
| **Watchlist** | `config/watchlist.yaml`. The companies to monitor. Replaces the Excel workbook. |
| **Prefilter** | Stage [3]. Free, local, hard rejections. Never calls a model. |
| **Vital extract** | Stage [4]. The ≤800-character reduction of a JD sent to the model. |
| **Decision** | Stage [5]. Binary accept/reject + reason. Replaces v1's 4-way `verdict`. |
| **Shortlist** | `data/shortlist.json`. Engine-owned queue of accepted roles. Disposable. |
| **Run** | One invocation of the scrape→decide pipeline. Numbered, recorded in `runs`. |
| **profile_version** | Integer in the derived profile. Bumping it invalidates cached decisions. |
| **Due** | A company whose `last_scraped_at` is null or older than `cycle_days`. The scheduler's only selection criterion (D-9). |
| **Staleness queue** | The ordering that replaces v1's cursor: never-scraped first, then longest-neglected. |
| **target_titles** | Role names generated from the resume that the scraper looks out for; drives the `title_allow` rule (D-10). |
| **Rule kind** | One of `regex_deny`, `any_match`, `max_number`, `overlap_floor`. Adding a kind is a registry entry, not a rewrite. |

---

*Status: in implementation. Next actions: see §0.5 and each lane in §0.6.*
