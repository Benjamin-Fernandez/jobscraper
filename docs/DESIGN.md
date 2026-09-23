# JobScraper — System Design

Fortnightly monitor of 229 company career sites for new-grad SWE roles matching Benjamin's profile.

---

## 0. Grounding: what actually exists

**Input workbook** (`job_tracker_04_2026.xlsx`) — 3 sheets:
- `Legend` — tier (T1/T2/T3/T4/Gov), status, and category vocabularies
- `Job Tracker` — 229 rows, columns: `# | Company | Tier | Category | Careers Page | Role Type | Status | Date Applied | Notes`
- `May26` — a dated snapshot of the same shape (existing manual "monthly copy" habit)

Critical finding: **`Careers Page` is already populated for all 229 rows (0 blanks).**
Step 1 is therefore *not* careers-site discovery from scratch — it is **ATS resolution**:
mapping each known careers URL to a machine-readable job feed.

Tier spread: T1=20, T2=80, T3=107, T4=19, Gov=3.
Category spread: Big Tech 37, Fintech 28, Semiconductor 28, Quant 22, Crypto 20,
Intl Bank 20, Regional Tech 18, Chinese Tech 12, Cloud/Infra 12, Cybersecurity 9,
IT Services 7, AI Lab 7, SG Bank 5, Gov 3.

**Profile** (from resume): NTU Computer Engineering, graduating Aug 2026, Singapore.
Backend / infra / platform / quant-dev. Python, Go, Java, TypeScript, C/C++.
Spring Boot, FastAPI, React. K8s, Docker, ArgoCD, CI/CD, PostgreSQL, Kafka, ClickHouse.
Distributed systems, low-latency, payments, exchange infra, LLM/RAG tooling.
Internships: Tencent (payments), Crypto.com (exchange), AMD.
→ Target band: **new-grad / graduate-programme / 0–2 YOE SWE**, Singapore-primary.

---

## 1. Design principles (the token economics)

The single most important decision:

> **This is a standalone Python program, not a Claude Code agent loop.**

Claude Code writes the code once. At **runtime** there is no Claude Code session, no
agent, no tool-calling loop. The scheduled job is `python -m jobscraper run`. The only
LLM contact at runtime is a small number of direct Anthropic API calls to Haiku, for one
narrow task (ambiguous-match adjudication), batched and permanently cached.

Everything else follows from that:

| Principle | Consequence |
|---|---|
| **Deterministic first** | ATS JSON APIs return structured jobs. No parsing by LLM, no HTML in context. ~85% of companies need zero tokens, ever. |
| **Delta-only** | Every posting gets a stable `job_id`. Only *unseen* IDs enter the matching funnel. Steady-state fortnightly delta ≈ 100–250 new postings across 229 companies, not ~15,000. |
| **Funnel, not fan-out** | Hard filters → local scoring → LLM. Each stage is cheaper than the next and kills ≥80% of what enters it. The LLM sees only the genuinely ambiguous band. |
| **Cache forever** | An LLM verdict is keyed by `hash(job_id + jd_text + profile_version)`. A given posting is judged at most once in its lifetime. |
| **Spend where it changes the answer** | Tokens are not minimized — they are *allocated*. Every increment of spend is tied to a named quality gain (§5), and anything a regex settles correctly never reaches a model. |
| **Buy durable data, not one-off opinions** | Extra budget goes first to *extracting structured fields* that persist in the DB and improve every future run, not to re-judging the same posting more expensively. |
| **Never fail the run** | Company fetches are fully isolated. A site that breaks is retried, then quarantined, then resurrected on probation — the run always completes and always writes both trackers (§3.9). |

---

## 2. Architecture

```
                    ┌──────────────────────────────┐
  job_tracker.xlsx  │  1. INGEST                   │
  (229 companies) ──▶  parse workbook → companies  │
                    └───────────────┬──────────────┘
                                    ▼
                    ┌──────────────────────────────┐
                    │  2. ATS RESOLVE  (one-time)  │  ← cached in DB forever
                    │  careers URL → provider+slug │     re-run only on failure
                    └───────────────┬──────────────┘
                                    ▼
                    ┌──────────────────────────────┐
                    │  3. FETCH  (0 tokens)        │
                    │  adapter per ATS → job list  │
                    └───────────────┬──────────────┘
                                    ▼
                    ┌──────────────────────────────┐
                    │  4. DELTA                    │
                    │  job_id not in DB → new      │
                    └───────────────┬──────────────┘
                                    ▼
         ┌──────────────────────────────────────────────────┐
         │  5. MATCH FUNNEL                                 │
         │   5a hard filters      (0 tokens)  ~15% survive  │
         │   5b local score BM25  (0 tokens)  ~30% survive  │
         │   5c LLM adjudicate    (Haiku, batched, cached)  │
         └───────────────────────┬──────────────────────────┘
                                 ▼
        ┌────────────────────────┴────────────────────────┐
        ▼                                                 ▼
┌──────────────────────┐                    ┌──────────────────────────┐
│ 6. RUN TRACKER       │                    │ 7. APPLICATION TRACKER   │
│ coverage + errors    │                    │ matched roles + links    │
│ (program-owned)      │                    │ (append-only; you edit)  │
└──────────────────────┘                    └──────────────────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────────┐
                    │  8. DIGEST (optional email)  │
                    └──────────────────────────────┘
```

---

## 3. Component specifications

### 3.0 The batch cursor — 10 companies per invocation

The run is **manually triggered** and processes exactly `batch_size` (10) companies,
then stops. A cursor in `cycle_state` remembers the position:

```
Mon        run -> companies 1-10
Tue        run -> companies 11-20
Tue again  run -> companies 21-30
```

229 companies / 10 = **23 invocations per cycle**. When the cursor reaches the end,
the cycle is complete and a new one may not begin until `cycle_days` (14) have elapsed
since that cycle's *first* batch. Running early prints the date the next cycle opens
and exits without processing; `--force` overrides it.

**Design decision — the clock does not reset the cursor mid-list.** Hitting the 14-day
mark while only at company 150 does *not* jump back to company 1. The list is finished
first, so every company is checked exactly once per cycle. The alternative (reset on
elapsed time alone) would mean companies late in the list were almost never checked,
since 23 invocations in 14 days is a cadence the user may not sustain. The cycle is
therefore "at least 14 days", not "exactly 14 days".

The cursor advances **even when companies in the batch fail**. A failed company is
skipped and picked up by the quarantine/probation machinery (§3.9), never retried in
place — otherwise a single permanently-broken site would wedge the cursor forever.

Quarantined companies due for probation are appended to the batch *in addition to* the
10, so probation never consumes the batch budget.

### 3.1 Ingest

Read the `Job Tracker` sheet with `openpyxl`. Normalize to a `Company` record:
`name, tier, category, careers_url, role_type_hint, notes`.

`Tier` and `Category` are not decoration — they feed the matcher:
- Tier sets **priority ordering** in the application tracker (T1 rows surface first).
- Category sets a **domain prior** (e.g. `Quant` → boost "Quantitative Developer",
  "Low Latency", "C++"; `Semiconductor` → boost "Firmware", "Verification", "RTL",
  though the profile's exclusion rules still apply).
- `Role Type` (e.g. "SWE / Quant Dev", "SWE / Platform") is a **per-company title hint**
  used as extra query terms in local scoring.

The workbook is read-only input. The program never writes back to it.

### 3.2 ATS resolution — one-time, cached

For each company, resolve `careers_url` → `(provider, slug/tenant, feed_url)`.

**Resolution ladder**, stopping at first success:

1. **URL fingerprint** — regex the known careers URL for provider markers
   (`boards.greenhouse.io`, `jobs.lever.co`, `jobs.ashbyhq.com`, `*.wdN.myworkdayjobs.com`,
   `smartrecruiters.com`, `*.recruitee.com`, `apply.workable.com`, `icims.com`,
   `taleo.net`, `successfactors.com`, `eightfold.ai`, `avature.net`, `phenompeople.com`).
   Only 6 of 229 URLs self-identify today, so this is a fast path, not the workhorse.

2. **Slug probing** — derive slug candidates from the company name
   (`Two Sigma` → `twosigma`, `two-sigma`; strip `Inc/Group/Ltd`, split on `/`)
   and hit the provider APIs directly:
   ```
   GET  https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
   GET  https://api.lever.co/v0/postings/{slug}?mode=json
   POST https://api.ashbyhq.com/posting-api/job-board/{slug}
   GET  https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100
   GET  https://apply.workable.com/api/v1/widget/accounts/{slug}
   GET  https://{slug}.recruitee.com/api/offers/
   ```
   A 200 with a plausible job array is a hit. Cheap, parallel, deterministic.

3. **HTML sniff** — fetch the careers page, scan HTML for iframe/script/anchor hosts
   matching provider domains, plus `link[rel=canonical]` and any `__NEXT_DATA__` /
   `window.__INITIAL_STATE__` JSON blobs. Follow one redirect hop.

4. **Network sniff (headless)** — Playwright loads the page, records XHR/fetch requests,
   and looks for a JSON endpoint returning job-shaped payloads. This is how Workday,
   Eightfold and most bespoke SPAs give themselves away. Slow (~8s/company) but run
   **once per company, ever**.

5. **Sitemap scan** — `robots.txt` → `sitemap.xml`, filter URLs matching
   `/job|/career|/opening|/position/` for sites that publish job pages statically.

6. **Manual queue** — anything unresolved writes to `output/needs_review.xlsx` with the
   careers URL and whatever was observed. You paste the correct feed URL; the program
   learns it permanently. Expect ~20–35 companies here on first run, trending to ~0.

Resolution results live in the `companies` table with `resolved_at`. Re-resolution is
triggered only by N consecutive fetch failures.

### 3.3 Fetch adapters — the core of the zero-token claim

Each adapter implements one interface:

```python
class Adapter(Protocol):
    provider: str
    def fetch(self, company: Company) -> list[RawJob]: ...
    # RawJob: external_id, title, location, url, department,
    #         employment_type, posted_at, description_html
```

**Build order by coverage** (estimates against your actual 229-company list):

| # | Adapter | Est. companies | Notes |
|---|---|---|---|
| 1 | **Workday** | ~60–70 | Almost every bank (GS, JPM, MS, UBS, HSBC, StanChart, Citi, BNP, Macquarie, Nomura, BNY, State Street, Wells Fargo, DBS, OCBC, UOB) plus NVIDIA, Intel, Qualcomm, Broadcom, Micron, AMD, Applied Materials, Lam, KLA, Seagate, WD, NXP, ST, Renesas, Salesforce, Dell, HPE, Cisco, ServiceNow, Workday, SIG, Virtu. `POST /wday/cxs/{tenant}/{site}/jobs` with `{limit, offset, searchText, appliedFacets}`. Highest single ROI in the project. |
| 2 | **Greenhouse** | ~30–40 | Figma, Notion, Databricks, Anthropic, Scale, Vercel, Supabase, Temporal, Grafana, Robinhood, Plaid, Fireblocks, Alchemy, Chainalysis, Anchorage, Groq, Cerebras, HRT, DRW, Jump, Akuna, Two Sigma. Clean public JSON, no auth. |
| 3 | **Bespoke big-tech** | ~12 | Each a small hand-written adapter against a public JSON endpoint: Google, Meta, Amazon, Apple, Microsoft, Netflix (Eightfold), Bytedance, Tencent, Alibaba, Shopee/Sea, Grab, Tesla. Justified because these are T1/T2 and you care most about them. |
| 4 | **Ashby** | ~8 | OpenAI, Perplexity, Mistral, xAI and similar. |
| 5 | **Lever** | ~8 | Mostly crypto/fintech mid-caps. |
| 6 | **SmartRecruiters** | ~8 | Visa and enterprise Europeans. |
| 7 | **Eightfold / Phenom / Avature** | ~6 | Shared patterns; one adapter each. |
| 8 | **Generic HTML** | remainder | Heuristic: find repeated DOM structures containing a link plus a title-like string; optional headless render. Lower precision, flagged `low_confidence` in output. |

**Expected coverage: ~85% high-confidence, ~10% generic-HTML, ~5% manual queue.**

Shared HTTP layer for all adapters: `httpx` client, 1.5 req/s per host, exponential
backoff on 429/5xx, 20s timeout, honest User-Agent with contact email, `robots.txt`
respected, ETag/Last-Modified conditional requests, on-disk response cache.

### 3.4 Delta detection

```
job_id = sha256(f"{company_id}|{provider}|{external_id or canonical_url}")
```

Falls back to `sha256(company_id|normalized_title|normalized_location)` when a provider
gives no stable ID. On each run:
- `job_id` not in `jobs` → **new**, enters the funnel
- `job_id` in `jobs` → update `last_seen_run`, skip entirely
- in `jobs` but absent from this fetch → set `closed_at` (feeds "role disappeared" notes)

**Run 0 (baseline):** the first run sees ~8,000–15,000 open postings. Config flag
`baseline_mode`:
- `seed` — record all, match none. Clean slate; first real output comes at run 1.
- `seed_and_match_top` *(recommended)* — record all, run the funnel, emit only the top
  `N=60` by score, so you get immediate value without a 400-row dump.

### 3.5 Matching engine

Three stages. Stage inputs shrink by roughly an order of magnitude each time.

**Profile spec** — `config/profile.yaml`, generated once from the resume, then hand-tuned.
This file is the highest-leverage artifact in the project; it should be edited by hand.

```yaml
profile_version: 3
identity:
  graduation: 2026-08
  eligible_programmes: [new_grad, graduate_programme, associate_programme, 2027_intake]
locations:
  # DECIDED: Singapore only. Tightest filter, near-zero geographic noise.
  allow:   [Singapore]
  primary: [Singapore]
  allow_remote_anchored_to: [Singapore]   # "Remote - Singapore" style postings count
  deny:    ['*']                          # everything not matching allow is rejected
titles:
  allow_patterns:
    - '(?i)software (engineer|developer)'
    - '(?i)(backend|back-end|platform|infrastructure|systems|distributed)'
    - '(?i)quant(itative)? (developer|technologist|engineer)'
    - '(?i)(graduate|associate) (programme|program|analyst|engineer)'
    - '(?i)(new ?grad|campus|university|early career|2026|2027)'
    - '(?i)(site reliability|devops|cloud|data) engineer'
  deny_patterns:
    - '(?i)\b(senior|staff|principal|lead|director|manager|head of|vp|vice president)\b'
    - '(?i)\b(intern|internship|working student|apprentice)\b'
    - '(?i)\b(sales|marketing|recruit|hr|legal|finance analyst|accountant)\b'
    - '(?i)\b(1[0-9]|[5-9])\+? years'
experience_ceiling_years: 3
skills:
  core:    [python, go, java, typescript, kubernetes, docker, postgresql, kafka,
            fastapi, spring boot, rest api, distributed systems, ci/cd, linux]
  strong:  [react, node.js, clickhouse, mongodb, argocd, github actions, aws,
            grpc, microservices, terraform, ansible, prometheus]
  domain:  [payments, exchange, trading, fintech, crypto, low latency, market data,
            settlement, fx, llm, rag, backtesting]
  weak:    [c++, verilog, solidity, next.js, selenium]
weights:
  bm25: 0.45
  skill_overlap: 0.30
  title_affinity: 0.15
  tier_bonus: 0.05
  category_prior: 0.05
thresholds:
  auto_reject_below: 25      # widened: only obvious junk dies without a model looking
  llm_band: [25, 88]         # see §5 budget ladder
  auto_accept_above: 88
budget:
  profile: thorough          # lean | standard | thorough | max  (§5)
  max_tokens_per_run: 2_000_000
  extraction_for_all_stage_a_survivors: true
  second_opinion_tiers: [T1, T2]
```

**Stage A — hard filters (0 tokens).** Deliberately **conservative**: a rule may only
reject what is unambiguous. With a loosened budget, a false negative here is the most
expensive error in the system, because a posting killed at Stage A is never seen again.

- **Unambiguous rejects** (rule-only): deny-list titles (`senior|staff|principal|director|
  manager|vp`), non-engineering functions (`sales|marketing|hr|legal`), internships,
  explicit YOE floors ≥ 5 parsed from the JD (`r'(\d+)\+?\s*years'`).
- **Location — two paths.** Singapore-only is a hard filter, but location strings are
  filthy in practice (`"APAC"`, `"Asia Pacific — SG/HK"`, `"Multiple Locations"`,
  `"Remote - Asia"`, `""`). So: if the string *unambiguously* contains or excludes
  Singapore, decide by rule and spend nothing. If it is **ambiguous or empty, do not
  reject** — route it to Stage C1 for normalization. This single change is the difference
  between catching and silently missing Singapore roles at banks and big tech, which are
  exactly the postings with the messiest location metadata.
- Everything else (employment type, posting age) is rule-only.

**Stage B — local scoring (0 tokens, ~70% of survivors eliminated).**
Composite 0–100 score:
- **BM25** (`rank_bm25`) of the JD against a corpus built from resume text + `skills.*`
- **Skill overlap** — weighted set intersection (core 3×, strong 2×, domain 2×, weak 1×),
  with `rapidfuzz` for surface variants (`k8s`↔`kubernetes`, `postgres`↔`postgresql`)
- **Title affinity** — fuzzy match against the company's `Role Type` hint + allow patterns
- **Tier bonus** — small nudge so T1 ties break upward
- **Category prior** — per-category term boosts from the Legend vocabulary

Optional upgrade: local embeddings (`sentence-transformers/all-MiniLM-L6-v2`, CPU,
~80MB, free forever) for cosine similarity between JD and resume. Adds semantic recall
that BM25 misses, at zero marginal token cost. **Recommended once the rule layer is stable.**

**Stage C1 — structured extraction (Haiku 4.5, batched, cached).**
Runs on **every Stage-A survivor**, not just the ambiguous band. This is the primary
place the loosened budget is spent, because it buys *durable data* rather than a one-off
opinion — the extracted fields persist in `job_facts` and make every future rescore,
filter and rank better at zero additional cost.

Extracted per posting (strict JSON, 8 jobs per request):

```json
{ "id": "...",
  "countries": ["Singapore"],          // normalized from filthy location strings
  "is_singapore": true,
  "seniority": "new_grad",             // intern|new_grad|junior|mid|senior|lead|unknown
  "yoe_min": 0, "yoe_max": 2,
  "intake_year": 2027,                 // null if not a dated programme
  "is_graduate_programme": true,
  "sponsorship": "unclear",            // yes|no|unclear  (SG work-pass reality)
  "role_family": "backend",            // backend|infra|platform|quant_dev|sre|data|ml|fullstack|embedded|other
  "tech_stack": ["java","kubernetes","kafka"],
  "requires_clearance": false }
```

These fields then feed **back into the rule layer**, which re-filters with precision the
regexes never had: `is_singapore == false` → reject; `seniority in (mid,senior)` → reject;
`yoe_min > 3` → reject; `sponsorship == "no"` → flag, don't reject. Cheap, deterministic,
and permanently reusable.

**Stage C2 — adjudication (tier-routed, batched, cached).**
Everything still alive after C1 gets a verdict. Batched **10 jobs per request**:

```
System: You are screening graduate software engineering roles for one candidate.
Candidate: <320-token profile summary — fixed, prompt-cached>
Return for each job: {id, verdict, confidence, reason, concerns[]}
  verdict:    strong | possible | weak | reject
  confidence: 0.0-1.0
  reason:     <=25 words, concrete — name the specific overlap or gap
Return JSON only.

Jobs:
[1] id=... | Company (Tier) | Title | Location | <full requirements section, ~3000 chars>
[2] ...
```

Model routing by company tier — spend more where you care more:
- **T1 / T2** → `claude-sonnet-5`
- **T3 / T4 / Gov** → `claude-haiku-4-5-20251001`

**Stage D — second opinion (optional, `thorough`+ only).**
For T1/T2 postings where C2 returned `possible` or `confidence < 0.6`, re-judge
individually (not batched) with Sonnet and a fuller JD. Disagreement between C2 and D is
surfaced in the tracker as `Verdict: contested` — worth your eyes rather than silently
resolved. Catches the "Associate, Technology — Singapore" postings at banks that are
genuinely graduate roles but read like generic corporate filler.

Invariants that hold at every budget level:
- Profile summary is a **prompt-cache prefix**, written once and reused across all batches
- Results keyed by `hash(job_id|jd_hash|profile_version|stage)` — **nothing is ever
  judged or extracted twice**; bumping `profile_version` is the only re-run trigger
- A run that dies mid-way loses no work: verdicts are committed per batch, not per run

### 3.6 Run tracker (`output/run_tracker.xlsx`) — "what was checked"

Program-owned, rewritten each run. Two sheets:

**`Runs`** — one row per fortnightly run:
`run_id | window_start | window_end | started | finished | companies_total |
companies_ok | companies_failed | postings_seen | new_postings | matched | llm_calls |
input_tokens | output_tokens | est_cost_usd | duration_min`

**`Coverage`** — one row per company per run (the real answer to "what has been checked"):
`run_id | company | tier | provider | feed_url | status (ok/empty/failed/skipped) |
postings_found | new | matched | http_status | error | checked_at`

This makes gaps visible: if Jane Street silently returned 0 for three runs, `Coverage`
shows it instead of it quietly vanishing.

### 3.7 Application tracker (`output/application_tracker.xlsx`) — "what to apply to"

**Append-only. The program never edits or reorders rows you have touched.**

Columns — program-written (locked, grey) then yours (editable, white):

```
job_id | Date Found | Run | Company | Tier | Category | Title | Location |
Apply Link | Match Score | Verdict | Why Matched | Posted Date | Source
‖ Status | Date Applied | Resume Version | Referral | Notes | Outcome
```

Write protocol, in order:
1. Read the existing workbook fully into memory (including your edits)
2. Index by `job_id`
3. For each new match: if `job_id` unseen, append a row; if seen, update **only** the
   program-owned columns (e.g. `Posted Date`, or set `Status`→`Closed` if delisted) and
   never touch columns to the right of the `‖` divider
4. Write to `output/application_tracker.xlsx.tmp`, then atomic-replace
5. Keep the last 5 runs' workbooks in `output/backups/` — cheap insurance

Sorting: new rows appended in `(tier, -score)` order so T1 strong matches sit at the top
of each batch. Conditional formatting: score ≥ 72 green, 60–72 amber, verdict `strong` bold.
`Status` gets the Legend's data-validation dropdown (To Apply / Applied / OA / Interview /
Offer / Rejected) so it stays compatible with your existing workflow.

### 3.8 Digest (optional)

At run end, a plain-text email via SMTP: counts, top 10 matches with links, and any
companies that failed. Zero tokens (template string, no LLM). Makes the fortnightly
cadence actually land instead of relying on you remembering to open the file.

### 3.9 Resilience: error isolation, quarantine, resurrection

**Requirement: a failing site must never stop the run, and must drop itself out of the
rotation rather than being retried forever.**

**Isolation boundary.** Every company fetch runs inside its own `try/except` with its own
wall-clock budget (90s) and its own retry counter, dispatched across a thread pool
(8 workers, per-host rate limiting preserved). No exception crosses the boundary. The
orchestrator collects `Result[ok | failed]` per company and always proceeds.

**Error taxonomy** — determines retry, not just logging:

| Class | Examples | In-run retry | Counts toward quarantine |
|---|---|---|---|
| `transient` | timeout, connection reset, DNS blip, 429, 502/503/504 | 3× exponential backoff + jitter | Only if all retries fail |
| `blocked` | 403, Cloudflare challenge, bot-wall | 1× with longer delay | Yes |
| `gone` | 404, NXDOMAIN, empty domain | none | Yes (fast-tracked) |
| `schema` | 200 but payload no longer parses | none | Yes — signals ATS migration |
| `empty` | 200, valid parse, zero jobs | none | No — recorded, not punished |

**Quarantine (the drop-off).** Each company carries `consecutive_failures`:

1. **1–2 failures** → recorded in `Coverage` with the error; still fetched next run.
2. **3rd failure** → one automatic **re-resolution attempt** (§3.2 ladder). ATS migration
   is the most common cause, and this repairs it without you noticing.
3. **Re-resolution fails** → **quarantined**: `active = 0`, skipped in subsequent runs,
   written to `needs_review.xlsx` with the last error and last-good timestamp, and
   summarized in the run digest.
4. **Probation** → a quarantined company is retried once every **4th run** (≈2 months).
   One success clears `consecutive_failures` and reactivates it. Recovery is automatic;
   you are never required to intervene, only permitted to.

**Global circuit breaker.** If **>30% of companies fail in a single run**, the cause is
local (your network, a proxy, a bad deploy), not 70 simultaneous site outages. In that
case the run: aborts further fetching, **quarantines nobody**, rolls back all
`consecutive_failures` increments, marks itself `status = aborted_unhealthy` in the run
tracker, and exits non-zero. This prevents one bad night from wiping the registry.

**Correctness trap — do not mark jobs closed on failure.** A company's jobs are marked
`closed_at` *only* after a **successful** fetch that omits them. A failed or empty-due-to-
error fetch must leave existing jobs untouched, or a single timeout would mass-close a
company's postings and corrupt the next delta. This is the single easiest bug to
introduce here and is called out as a required test in Phase 3.

**Budget guards.** Per-run wall clock ceiling (45 min) and per-run token ceiling
(`budget.max_tokens_per_run`). On hitting either, the run stops *cleanly*: everything
fetched so far is persisted, both trackers are written, and the run is marked `partial`
with the unprocessed companies rolled to the front of the next run's queue.

### 3.10 Evaluation harness — proving the extra spend is worth it

Spending more only counts if it measurably finds more. One-time setup, then automatic:

1. `cli label` presents ~60 stored postings (stratified across tiers and score bands) and
   you mark each `good` / `bad`. Takes ~15 minutes, once.
2. That becomes `tests/fixtures/golden_set.json`.
3. `cli eval --budget lean|standard|thorough|max` replays the **stored** `jd_text` at each
   budget level and reports **precision, recall, F1, and token cost** per level.
4. The run tracker's `Runs` sheet carries `precision_est` per run thereafter.

This turns "more tokens should mean better results" from an assumption into a number, and
tells you the point where extra spend stops buying recall. Re-runnable any time at zero
fetch cost because `jd_text` is stored.

---

## 4. Data model (SQLite — `data/jobscraper.db`)

SQLite is the source of truth; Excel is a read/write *surface*. This matters: Excel alone
cannot safely express delta state, and concurrent manual edits would corrupt it.

```sql
companies(id PK, name, tier, category, careers_url, role_type_hint,
          provider, slug, feed_url, resolve_method, resolved_at,
          -- resilience state (§3.9)
          consecutive_failures, last_success_at, last_error_class, last_error,
          quarantined_at, probation_due_run, active)

jobs(job_id PK, company_id FK, external_id, title, location, url, department,
     employment_type, posted_at, jd_hash, jd_text,
     first_seen_run, last_seen_run, closed_at)

scores(job_id PK FK, profile_version, bm25, skill_overlap, title_affinity,
       total_score, stage_a_pass, filter_reason, scored_at)

-- Stage C1 output: durable structured facts, reused by every future rescore (§3.5)
job_facts(job_id PK FK, profile_version, countries_json, is_singapore, seniority,
          yoe_min, yoe_max, intake_year, is_graduate_programme, sponsorship,
          role_family, tech_stack_json, requires_clearance, model, extracted_at)

llm_verdicts(cache_key PK, job_id FK, profile_version, stage, verdict, confidence,
             reason, concerns_json, model, input_tokens, output_tokens, created_at)
             -- stage: c2 | d ; a contested pair (c2 != d) surfaces in the tracker

runs(run_id PK, window_start, window_end, started_at, finished_at, stats_json)

coverage(run_id FK, company_id FK, status, postings_found, new_count,
         matched_count, http_status, error, checked_at,
         PRIMARY KEY(run_id, company_id))

exported(job_id PK, exported_run, exported_at)   -- guards against double-append
```

`jd_text` is stored so re-scoring after a `profile_version` bump requires **zero refetching
and zero tokens** for anything the rules can settle.

---

## 5. Token & cost budget

**Build phase (Claude Code, one-time).** The dominant cost is *me*, not the runtime.
Controls: this document is the spec, so no session re-derives context; build in the phase
order below, one phase per session; no subagent fan-out; run tests yourself locally and
paste back only failures. Realistic: **6–9 focused sessions.**

**Runtime — the budget ladder.** Tokens are allocated, not minimized. Each rung is a
config value (`budget.profile`), and each buys a *named* improvement. Fetching, delta,
and rule filtering are always free; the ladder only governs what reaches a model.

| Rung | What it adds | What it buys | ~Tokens/run |
|---|---|---|---|
| **lean** | Stage C2 only, Haiku, band `[42,72]`, 900-char JD | Baseline. Ambiguous titles adjudicated. | ~10k |
| **standard** | + band widened to `[25,88]`, full requirements section (~3000 chars) | Fewer false negatives from crude BM25; correct YOE and intake-year reads. | ~120k |
| **thorough** *(default)* | + **Stage C1 extraction on all Stage-A survivors**, + ambiguous-location normalization, + Sonnet for T1/T2, + **Stage D** second opinion | The big one. Recovers Singapore roles hidden behind `"APAC"`/`"Multiple Locations"` strings; durable `job_facts` that improve every future run; contested verdicts surfaced rather than silently resolved. | ~400–600k |
| **max** | + **LLM-assisted HTML extraction** for sites with no JSON feed, + LLM-assisted ATS resolution for the manual queue | **Coverage**, not just precision: converts the ~15% generic-HTML/manual-queue tail into monitored companies. Biggest single gain in roles *found*. | ~1.2–1.8M |

Recommended: **`thorough` as the standing default**, `max` on the first run and after any
batch of quarantine failures (when the tail needs re-resolving). The ceiling
`budget.max_tokens_per_run: 2_000_000` is a hard stop, not a target — §3.9 spends it
tier-first, so if it binds, T1/T2 are already done.

Two properties make this safe to spend against:
- **Nothing is ever paid for twice.** `job_facts` and `llm_verdicts` are cached by content
  hash. A steady-state run only pays for genuinely *new* postings — at `thorough` that is
  ~150 new → ~25 extractions → maybe 8 verdicts. The per-run figures above are upper
  bounds for a busy fortnight, not a floor.
- **Retuning costs nothing.** `cli rescore` replays stored `jd_text` and `job_facts`
  against a new `profile_version` with no refetch, and `cli eval` (§3.10) tells you which
  rung is actually paying for itself on your golden set.

Run 0 at `max` is the one real spike — ~10,000 postings, ~2M tokens, once.

A fully offline mode still exists (`llm_band: [0,0]`, rules + local embeddings) if you
ever want it, but it is no longer the design target.

**Build phase note.** The loosened runtime budget does not loosen the *build* budget —
those are different pockets. §7's phase gates still exist to keep Claude Code sessions
focused and cheap.

---

## 6. Repository layout

```
JobScraper/
├─ config/
│  ├─ config.yaml             # cadence, paths, thresholds, feature flags
│  ├─ profile.yaml            # the matching spec (hand-tuned)
│  └─ overrides.yaml          # manual company→feed_url fixes
├─ data/
│  ├─ job_tracker_04_2026.xlsx    # input, read-only
│  ├─ jobscraper.db
│  └─ http_cache/
├─ output/
│  ├─ application_tracker.xlsx
│  ├─ run_tracker.xlsx
│  ├─ needs_review.xlsx
│  └─ backups/
├─ src/jobscraper/
│  ├─ cli.py                  # run | resolve | rescore | export | doctor
│  ├─ config.py  models.py  store.py
│  ├─ net/          http.py  robots.py  cache.py
│  ├─ ingest/       workbook.py
│  ├─ discovery/    fingerprint.py  probe.py  sniff_html.py  sniff_network.py  resolve.py
│  ├─ adapters/     base.py  registry.py  workday.py  greenhouse.py  ashby.py
│  │                lever.py  smartrecruiters.py  eightfold.py  generic_html.py
│  │                bespoke/{google,meta,amazon,apple,microsoft,netflix,
│  │                         bytedance,tencent,alibaba,sea,grab,tesla}.py
│  ├─ matching/     profile.py  filters.py  score.py  embeddings.py  llm_judge.py  pipeline.py
│  ├─ trackers/     run_tracker.py  application_tracker.py  excel_io.py
│  └─ notify/       digest.py
├─ tests/
│  ├─ fixtures/               # saved JSON/HTML per provider — offline, deterministic
│  └─ test_*.py
├─ scripts/run_fortnightly.ps1
└─ docs/DESIGN.md
```

Dependencies, deliberately lean:
`httpx, selectolax, openpyxl, rapidfuzz, rank_bm25, pyyaml, pydantic, tenacity, anthropic`
Optional extras: `playwright` (network sniff + generic fallback),
`sentence-transformers` (local embeddings).

---

## 7. Build phases

Each phase ends in something runnable and verifiable. Do not start the next until the
current one passes its gate.

| Phase | Deliverable | Gate |
|---|---|---|
| **0 — Scaffold** | Package layout, config loading, SQLite schema, `cli doctor` | `doctor` prints 229 companies parsed from the workbook |
| **1 — Resolve** | Fingerprint + slug probe + HTML sniff; `cli resolve` | ≥120/229 resolved to a provider automatically; rest listed in `needs_review.xlsx` |
| **2 — Adapters A** | Workday + Greenhouse + shared HTTP layer | ≥90 companies returning real postings; fixtures committed |
| **3 — Resilience** | Error taxonomy, retry policy, quarantine/probation, global circuit breaker, budget guards (§3.9) | Kill the network mid-run: the run completes, both trackers are written, **nobody is quarantined**, exit code signals `aborted_unhealthy`. Point a company at a 404 three times: it quarantines, lands in `needs_review`, and returns on probation. |
| **4 — Delta + Run tracker** | `jobs`/`runs`/`coverage` tables; run tracker export | Two consecutive runs: the second reports ~0 new. **And: a forced fetch failure closes zero jobs** (the §3.9 trap). |
| **5 — Matching A** | `profile.yaml`, Stage A + Stage B, `cli rescore` | On a 300-posting sample, top-25 by score is manually judged ≥80% sensible |
| **6 — App tracker** | Append-only Excel writer, backups, formatting | Edit `Status` by hand, re-run, confirm the edit survives |
| **7 — Matching B** | Stage C1 extraction, C2 adjudication, Stage D, tier routing, caching, token accounting | Second run over the same jobs makes **0** API calls (cache proven); `job_facts` populated for every survivor |
| **8 — Eval harness** | `cli label`, golden set, `cli eval` across budget rungs (§3.10) | Precision/recall/F1 + token cost reported per rung; the `thorough` rung demonstrably beats `lean` on recall |
| **9 — Adapters B** | Ashby, Lever, SmartRecruiters, Eightfold, 12 bespoke | ≥190/229 covered |
| **10 — Schedule + digest** | Task Scheduler task, email digest, LLM-assisted HTML fallback (`max` rung) | Unattended fortnightly run completes; digest arrives; tail companies converted from manual queue to monitored |

Phases 0–6 give a genuinely useful system. 7–8 are where the loosened budget earns its
keep, and 9–10 are coverage and automation. **Phase 3 is deliberately early** — resilience
is cheaper to build in than to retrofit, and every later phase depends on runs that finish.

---

## 8. Failure modes and mitigations

| Risk | Mitigation |
|---|---|
| Career site blocks scraping / Cloudflare | Honest UA + contact email, ≤1.5 req/s, robots respected, backoff. Classified `blocked` → quarantined after 3 → probation every 4th run (§3.9). Never a crash. |
| Workday tenant/site IDs vary per company | Discovered once via network sniff, stored in `companies.feed_url`, overridable in `overrides.yaml`. |
| ATS migration breaks an adapter | Classified `schema`; `consecutive_failures ≥ 3` auto-triggers re-resolution before quarantine, so most migrations self-heal (§3.9). |
| One bad network night wipes the registry | Global circuit breaker: >30% failure rate in a run → quarantine nobody, roll back all failure counters, mark the run `aborted_unhealthy` (§3.9). |
| Token spend runs away | Hard `budget.max_tokens_per_run` ceiling, spent tier-first; on hit the run ends cleanly as `partial` with remaining companies queued to the front of the next run. |
| Unstable job IDs cause duplicate rows | Composite fallback key (company+title+location) plus the `exported` table guard. |
| Excel corruption / lost manual edits | Read-modify-atomic-write, 5-run backup rotation, DB remains source of truth. |
| Match quality drifts / too noisy | `cli rescore` replays all stored `jd_text` against a new `profile_version` at zero fetch and near-zero token cost. Tune `profile.yaml`, re-run, compare. |
| Silent under-reporting | The `Coverage` sheet makes "0 postings found" visible per company per run. |
| Legal / ToS | Public postings, low rate, no auth bypass, personal single-user use. Sites that explicitly forbid it → manual queue. |

---

## 9. Decisions

**Settled (2026-09-14):**

1. **Geography — Singapore only.** `locations.allow: [Singapore]`, everything else
   rejected at Stage A. Remote postings count only when anchored to Singapore.
   *Consequence:* this is the single most aggressive filter in the system. It will cut
   the funnel hard — expect Stage A to eliminate ~95% rather than ~85%, and the
   fortnightly matched count to land in the low single digits for most runs. That is the
   intended behaviour, but if output feels too sparse after 2–3 runs, widening to
   `[Singapore, Hong Kong, Tokyo]` is a one-line change plus a `cli rescore` — no refetch,
   no tokens.
2. **LLM stage — on.** Needs `ANTHROPIC_API_KEY` in the environment.
3. **Budget — `thorough` by default, not minimal.** Token usage has leeway, and the ladder
   in §5 ties every increment to a named quality gain: wider adjudication band, full
   requirements text, Stage C1 structured extraction on all survivors, ambiguous-location
   normalization, Sonnet routing for T1/T2, and Stage D second opinions. `max` adds
   LLM-assisted HTML extraction, which buys *coverage* rather than precision. §3.10's eval
   harness exists to verify the extra spend is actually paying, rather than assuming it.
4. **Fetch errors never stop a run.** Per-company isolation, typed retry policy,
   quarantine after 3 failures with one automatic re-resolution attempt, probation retry
   every 4th run, and a global circuit breaker so a local network fault cannot mass-
   quarantine the registry. Full spec in §3.9.

**Still open (defaults apply until you say otherwise):**

5. **Intake year.** Assumed Aug 2026 graduation → 2026 new-grad and 2027 graduate
   programmes both in scope, internships excluded.
6. **Run 0 behaviour.** Defaulting to `seed_and_match_top` (N=60), at the `max` rung.
7. **Email digest.** Off by default; needs an SMTP app password to enable.

---

## 10. Status — IMPLEMENTED

Revision 3 (2026-09-14). **The system is built and verified end to end.**

Added in revision 3: §3.0 batch cursor (10 companies per manual invocation, 14-day
cycle gate).

### What was verified against live sites

- Two consecutive real runs over companies 1-10 and 11-20; cursor advanced correctly
  and unattended.
- 780 postings fetched across 15 working companies; Stage A cut them to 35.
- Manual `Status`/`Notes` edits in the tracker survived a subsequent run untouched.
- Fetch failures (Citadel 403 bot-wall, DRW and Microsoft JS-only pages) were skipped
  without stopping the run.
- The global circuit breaker fired correctly on an early run where 6/10 failed, and
  quarantined nobody.
- 7/7 offline regression tests pass (`tests/test_core.py`).

### Defects found and fixed during verification

1. **robots.txt was applied to public ATS JSON APIs**, blocking six companies whose
   resolution had already succeeded (the probe path bypassed robots, the fetch path did
   not). Fixed with an allowlist of documented public job-board API hosts; robots is
   still enforced for generic HTML scraping of company sites.
2. **Empty probe hits were accepted as valid resolutions.** `HRT` resolved to
   `ashby/hrt` and `Optiver` to `greenhouse/optiver`, both real slugs returning zero
   postings — the system would have monitored empty boards forever. Probes now require
   at least one posting before accepting a provider.
3. **Slugs were derived from the display name only.** Added derivation from the careers
   domain, which is a far better signal (`HRT` → `hudsonrivertrading`).
4. **Location filtering was default-allow.** Unknown location strings fell through as
   "ambiguous", so the top 13 exports were Zug, Switzerland and Aarhus, Denmark. With a
   single allowed country an enumerated deny list can never be complete, so the logic is
   now default-deny: anything concrete that is not Singapore is elsewhere, and only
   genuinely vague strings (`APAC`, `All Offices`, blank) are routed onward.

### Deferred from §7

Phases 8-10 are not built: no eval harness (`cli label` / `cli eval`), no bespoke
big-tech adapters, no email digest, no scheduled-task automation (the run is manual by
design). The generic-HTML fallback cannot read JavaScript-rendered boards — Microsoft,
DRW and similar land in `needs_review.xlsx` for a manual feed URL. `cli rescore` is
specified but not implemented; bumping `profile_version` currently invalidates the
caches without a replay command.
