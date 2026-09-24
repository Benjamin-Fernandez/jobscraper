# JobScraper v2 - Design

The shape of the system and the decisions behind it. This file is generated from
the specification (`.claude/prds/jobscraper-v2.prd.md`, sections 7, 8.1 and 8.2)
so the two cannot drift; the PRD remains the source of truth, including the
stage-by-stage detail (8.3), the data contracts (8.4), the web app (8.5),
deployment (8.6) and the risks (12).

v1's design document is kept at `archive/v1-src/docs/DESIGN.md`.

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
