# mullti_user_prd — JobScraper as a public, multi-user cloud service

**Status:** DRAFT r2 — requirements + target design, revised after an ECC architect
review (2026-09-25). Nothing here is built yet.
**Created:** 2026-09-25 · **Owner:** Benjamin
**Builds on:** the single-user v2 in `.claude/prds/jobscraper-v2.prd.md` (M0–M12:
watchlist → staleness scheduler → ATS scrape → free prefilter → Qwen facts →
code decides → shortlist → Vue web app with run control, resume upload and
companies-per-run).
**Method:** requirements skeleton from the ECC `plan-prd` skill (problem → evidence
→ users → hypothesis → metrics → scope → milestones → questions → risks); design
reviewed by the ECC `architect` agent against the v2 code. Per the owner, this
document also carries the **target design and the hosting choice**, which the skill
normally defers to `/plan` — they are §8–§12.

> **How to read this.** §1–§7 say *what* must be true and *why*. §8–§12 say how v2
> must change to get there, with costs. §13–§15 are the plan, the questions and the
> risks. Figures marked *(verified 2026-09-25)* come from the sources in §16;
> everything else is an estimate and says so.

---

## 1. Problem

Job seekers in Singapore who target specific companies must check each company's
careers site by hand, repeatedly, and read every posting to find the few that fit
their level, contract type and interests. JobScraper already does this well for one
person — 224 companies, ~33,000 postings a cycle, ~90 shortlisted roles, all
confirmed Singapore — but only for someone who can run Python, edit YAML and host a
local LLM. Everyone else keeps doing it by hand, or relies on job boards that bury
company-direct postings among agency and duplicate listings.

## 2. Evidence

- **Observed (v2, 2026-09-24).** One full cycle over 224 companies: ~21,600–33,000
  postings, a free prefilter passing <1%, a shortlist of 90 roles, 0 accepted outside
  Singapore. The mechanism works; the question is whether others want it.
- **Observed (v2).** The per-company work (scraping, reading a posting's facts) is
  identical for every user who watches that company — what makes a shared service
  cheap (§9.2).
- **Caveat (not yet measured).** v2's crawl coverage was measured from a *home* IP.
  Datacenter IPs are blocked more often by careers sites' bot protection — P0 measures
  this before anything is built (§9.6).
- **Assumption — needs validation via user interviews + a landing page with a
  waitlist:** Singapore job seekers want a company-watch tool and will pay a few
  dollars a month for more runs.
- **Assumption — needs validation via a pricing test:** willingness to pay at §11's prices.

## 3. Users

- **Primary:** job seekers **in Singapore** — final-year students and graduates
  (internship / new-grad) and early-career professionals — with a list of companies
  they want to work for and a clear idea of the roles they want. Triggered weekly or
  fortnightly, or when target companies open a hiring season.
- **Secondary (later):** university career-services offices (a cohort plan). Not MVP.
- **Not for:** recruiters and agencies (no candidate search, no bulk export), mass-apply
  automation, users under the minimum age (§12.3), users outside Singapore at launch
  (§9.8 keeps the door open).

## 4. Hypothesis

We believe **a hosted JobScraper where a user uploads a resume, picks role types,
keywords, an experience ceiling and target companies, and gets a fresh,
Singapore-verified shortlist on their own schedule** will **replace manual
careers-site checking** for **Singapore job seekers**.
We'll know we're right when **≥ 40% of users who complete onboarding open their Inbox
in at least 3 of their first 6 weeks, and ≥ 5% of active users pay** — at an
infrastructure cost that stays **below US$0.50 per active user per month**.

## 5. Success Metrics

| Metric | Target | How measured |
|---|---|---|
| Onboarding → first shortlist | ≤ 10 min, ≥ 70% of sign-ups | events `signed_up` → `first_shortlist_ready` |
| Weekly retention | ≥ 40% open Inbox in 3 of first 6 weeks | Inbox view events |
| Paid conversion | ≥ 5% of monthly active users | Stripe subscriptions ÷ MAU |
| Location precision | 100% of accepted roles in the user's chosen locations | automated check + monthly hand audit of 30 |
| Infra + LLM cost | < US$0.50 per active user per month | monthly bill ÷ MAU |
| Run success | ≥ 98% of runs reach `done` or `partial` | run state (§8.5) |
| Run latency | p95 queue-to-done ≤ 15 min | run timestamps |
| Crawl coverage from the server | ≥ 90% of companies fetch successfully | crawl log |
| Availability | ≥ 99% monthly | uptime monitor |
| Deletion | account deletion completes immediately in the live DB; backups expire within the stated window | deletion log |

## 6. Scope

### MVP — what tests the hypothesis

1. **Sign up / log in with Google** (no passwords).
2. **Onboarding:** resume (PDF/DOCX) → **role types** (internship, full-time, contract —
   any combination) → **keywords and interests** → **experience ceiling** → **target
   companies** (search the shared catalog, or add by careers URL) → **schedule**.
3. **Runs on the user's schedule** (manual, weekly, fortnightly — a chosen day/time,
   Singapore time), counted against the user's quota.
4. **The v2 funnel per user:** shared crawl → shared posting facts → per-user prefilter
   → per-user fit (Qwen) → code decides → per-user shortlist.
5. **The v2 web app, made multi-user:** Inbox, Applications, Runs, Profile, Companies,
   Settings, **Billing**.
6. **Quotas and paid tiers** (Stripe, PayNow + cards).
7. **Hosting in Singapore** at the cost in §10.
8. **Privacy for a public service:** consent, withdrawal, deletion, export, encryption,
   a privacy policy (PDPA, §12.3).

### Out of scope (MVP)

| Item | Why deferred |
|---|---|
| **Scraping LinkedIn** | Prohibited by LinkedIn's User Agreement; §9.7 gives the compliant route. |
| Auto-apply / filling application forms | Different product; abuse and ToS risk. |
| Non-Singapore locations | Launch market; the data model keeps locations per user (§9.8). |
| Email/Telegram alerts | First post-MVP item; not needed to test the hypothesis. |
| Mobile apps | The responsive web app (v2 M12) covers phones. |
| Per-user or self-hosted LLMs | Cost-prohibitive at this scale (§9.5). |
| University/cohort accounts | Secondary segment; after the hypothesis holds. |
| Republishing full job descriptions | Shortlists show a short extract + the employer's link (§12.3). |

---

## 7. Decision Register (new)

Numbered from D-19 so they sit beside v2's decisions (D-1–D-18).

| # | Decision | Rationale |
|---|---|---|
| **D-19** | **Shared catalog + per-user layers.** Companies, postings and each posting's *facts* are global; preferences, prefilter results, fit, shortlists and applications are per user. | Crawling and fact extraction are identical for every watcher of a company, so cost scales with *distinct companies*, not users. |
| **D-20** | **One shared Qwen endpoint, pay-per-token — not a model per user, not self-hosted.** | ~US$15–25/month for 200 users vs ≥ US$360/month for one always-on GPU (§9.5). Personalisation lives in the prompt and data. |
| **D-21** | **Hosted Qwen on Alibaba Cloud Model Studio's Singapore endpoint**, through a new OpenAI-compatible backend beside v2's `ollama`/`cli`/`api`; thinking disabled. A fallback provider only for non-personal prompts (§9.3). Ollama stays for development. | In-region, cheapest per token, and D-16 already chose Qwen. |
| **D-22** | **Two prompts, two steps.** A **facts** prompt with *no user data* (Singapore?, locations, yoe_min, employment type, seniority) runs once per posting version; a **fit** prompt built from *one user's* profile and interests runs per (user, posting). Code still decides (D-17). | v2's single prompt hard-codes one persona ("a new graduate software engineer … Singapore"); a public service needs the user-independent facts separated from the user-dependent fit. |
| **D-23** | **Google sign-in only (OIDC), keyed on Google `sub`, `email_verified` required; server-side sessions.** | The owner's requirement; no passwords; stable identity even if the email changes. |
| **D-24** | **No LinkedIn scraping.** Postings come from company ATS feeds (as v2) and generic `JobPosting` markup on careers pages; LinkedIn appears only as links users paste. | §9.7: no read API exists; scraping breaches LinkedIn's terms and was enforced in 2025. |
| **D-25** | **Start on one small Singapore VM** (DigitalOcean 2 GB) running Docker Compose with Postgres, one worker process, Caddy; backups encrypted off-VM. Scale out on *measured* triggers. | Cheapest viable at ≤ 200 users (§10); every piece is separable later. |
| **D-26** | **Quota is an append-only ledger**, charged atomically at run start, refunded by rule; one active run per user. | Auditable, race-free, and maps runs to cost (§8.5). |
| **D-27** | **Postgres replaces SQLite; `store.py` stays the only SQL module**; row-level security is enforced, not decorative. | v2 §8.4 designed for this swap; multi-user needs concurrency and isolation. |
| **D-28** | **Cache keys are content hashes of everything that shapes an answer.** | v2 caches decisions by `profile_version` only — editing `judge.interests` today serves stale verdicts. Multi-user must not inherit that (§8.3). |
| **D-29** | **Shared facts are protected against poisoning:** facts batches hold one company's postings only; facts from user-added companies stay private to that user until the company is reviewed. | One hostile posting or attacker page must not write `is_singapore: true` into facts every user sees (§12.2). |

---

## 8. Target design — what changes from v2

### 8.1 What stays, what changes

| v2 piece | Multi-user fate |
|---|---|
| ATS adapters, discovery, `net.py` (rate limits, robots) | **Kept**, fed by the shared catalog. **Plus** SSRF protection for user-added URLs (§12.2) and a generic schema.org `JobPosting` (JSON-LD) adapter for careers pages on no known ATS. |
| `RawJob.employment_type` (filled by Lever, Ashby, SmartRecruiters, Workable, Recruitee) — *dropped by v2's schema today* | **Persisted** as `postings.employment_type_raw`; the model is asked only when it is empty (Greenhouse, Workday, generic). |
| Staleness scheduler (per company, 14 days, stamped on attempt) | **Kept for the shared crawl**; the deadline becomes the *shortest tier window among the company's watchers*, measured from `last_success_at` (not the attempt stamp). A separate **per-user run scheduler** is new (§8.5). |
| Description hydration inside the funnel (`_hydrate`) | **Moved to the crawler** (`postings.jd_fetched_at`): user runs never make network calls. |
| Free prefilter (`rules.yaml`, rule registry) | **Kept, per user**, with rules *generated from the user's preferences*. v2's defaults are not copied: its `title_deny` rejects "intern", which an internship seeker needs. |
| Vital extract | **Kept, global** (one per posting version). |
| Decide (one prompt: fit + facts; code decides) | **Split** into a facts prompt and a fit prompt (D-22). The guard is unchanged. |
| Decision cache `(job_id, profile_version, vital_hash)` | **Re-keyed** by content hashes (D-28, §8.3). |
| Resume ingest → derived profile | **Kept, per user**; contact details stripped before the model sees the text (§12.3). |
| `shortlist.json` file | **Replaced by a query** over per-user fit (a file per user does not scale). |
| SQLite, `store.py` | **Postgres**, `store.py` still the only SQL (D-27). |
| `config.yaml` → `judge.interests`, `batch_size` … and v2's `settings` table | **Per-user preferences and settings in Postgres**; `config.yaml` keeps only system settings. |
| Vue web app (M12 tabs) | **Kept and extended** — auth, onboarding, Companies, Billing, admin (§8.7). |
| M11 background jobs (child processes, one at a time) | **Generalised** into a Postgres queue and worker (§8.4). |
| Loopback-only, no auth (R-9) | **Replaced**: public HTTPS, Google sign-in, sessions, CSRF, rate limits (§12). |
| Ollama backend | **Development only**; production uses the hosted backend (D-21). |

### 8.2 Architecture

```
                     Users (browser, Singapore)
                               │ HTTPS
                ┌──────────────▼───────────────┐
                │ Caddy: TLS, static SPA,       │     one Singapore VM (2 GB)
                │ rate limits, security headers │     Docker Compose
                └──────────────┬───────────────┘
                               │
             ┌─────────────────▼──────────────────┐
             │ API (FastAPI, stateless)           │  Google OIDC · sessions · quotas
             │ /auth /me /onboarding /runs        │  Stripe webhooks · admin
             │ /shortlist /applications /billing  │  DB role: app_api (RLS enforced)
             └────────┬───────────────────────────┘
                      │ enqueue / read / write
             ┌────────▼────────────────────────────────────────────┐
             │ Postgres                                             │
             │ shared: companies, postings, posting_facts, crawls   │
             │ per user (RLS): users, sessions, consents,           │
             │   preferences, user_companies, profiles, user_rules, │
             │   runs, run_companies, user_prefilter, user_fit,     │
             │   applications, app_events, settings, quota_ledger,  │
             │   subscriptions                                      │
             │ system: jobs (queue), stripe_events, audit_log       │
             └────────▲────────────────────────────────────────────┘
                      │ SKIP LOCKED
             ┌────────┴──────────────────────────────┐
             │ worker process — three queues:         │  DB role: app_worker
             │   crawl  · facts  · run                │  (cross-user, RLS-bypass
             └───┬───────────────┬───────────────────┘   only where needed)
                 │ HTTP          │ HTTPS
          company ATS /     Hosted Qwen — Alibaba Model Studio, Singapore endpoint
          careers pages     (fallback provider for non-personal facts prompts only)

   Off-VM: encrypted Postgres backups + WAL archive → object storage
```

The worker is one process consuming three queues at launch; each queue can become its
own process or VM without code changes (§9.8).

### 8.3 Data model

**Shared catalog (no personal data):**
- `companies` — v2's fields plus `status` (active / unresolvable / blocked / pending_review),
  `added_by` (null for curated), `crawl_deadline` (derived, §8.1).
  **Identity:** `UNIQUE (provider, board_slug)` for ATS boards, and a normalised
  careers URL for the rest — *not* `slug(name)`, or two users adding "Grab" create
  duplicates.
- `postings` — v2's `jobs` plus `employment_type_raw`, `jd_fetched_at`, `vital_hash`.
- `posting_facts` — PK `(posting_id, vital_hash, prompt_version, model)` → `is_singapore`,
  `locations[]`, `yoe_min`, `employment_type`, `seniority`, `extracted_at`,
  `visibility` (`shared` | `private:<user_id>`, D-29).
- `crawls` — per-company crawl attempts and outcomes (v2's `coverage` belongs here, not
  to user runs).

**Per user (every row carries `user_id`; RLS enforced):**
- `users` — Google `sub` (unique), email, `email_verified`, name, created_at, deleted_at.
- `sessions` — server-side sessions (id hash, user, expiry, rotated_at).
- `consents` — versioned: which privacy notice version, when, withdrawn_at.
- `preferences` — role types, interests, experience ceiling, allowed locations
  (default `[singapore]`), schedule, timezone.
- `user_companies` — watched catalog companies (+ priority).
- `profiles` — derived profile (v2 shape), resume **encrypted in Postgres** (≈ 1 MB × 200
  is trivial) with its hash.
- `user_rules` — generated rules + the user's own `extra:` entries; `rules_hash`.
- `runs` — state machine (§8.5), source (manual | schedule), `scheduled_for`, stats.
- `run_companies` — the user's company list frozen at run start.
- `user_prefilter` — PK `(user_id, posting_id, rules_hash)`.
- `user_fit` — PK `(user_id, posting_id, vital_hash, fit_input_hash)`, with
  `fit_input_hash = sha256(profile summary + skills + interests + experience ceiling +
  role types + fit prompt version + model)`; `first_shortlisted_run` (so the Inbox can
  show what is new).
- `applications` — PK `(user_id, application_id)`; `posting_id` **nullable** so a
  pasted LinkedIn link can be tracked; `app_events` carries `user_id`.
- `settings` — per-user UI settings (v2's M11 table, per user).
- `quota_ledger` — append-only: `(user_id, run_id, kind: charge|refund|grant, amount, at)`,
  `UNIQUE (run_id, kind)`.
- `subscriptions` — plan, period, status, Stripe ids.

**System:**
- `jobs` (the queue) — `kind`, `payload`, `dedupe_key` (UNIQUE where not finished),
  `run_after`, `locked_until`, `attempts`, `last_error`.
- `stripe_events` — processed webhook ids (idempotency).
- `audit_log` — sign-ins, consent changes, exports, deletions, admin actions.

**Deletion is designed in, not bolted on:** every per-user table cascades from `users`;
deleting an account removes the live data at once; backups expire it (§12.3).

### 8.4 Work model: one worker, three queues

A Postgres table-backed queue (`FOR UPDATE SKIP LOCKED`) — no Redis at this size.

| Queue | Unit of work | Enqueued when |
|---|---|---|
| **crawl** | one company: resolve ATS (shared), fetch listings, diff, persist; then fetch descriptions for new postings that pass a **global location-only screen** | the company's crawl deadline passes, or a run finds it stale |
| **facts** | one company's new/changed postings → the facts prompt (one company per batch, D-29) | a run reaches step 3 and survivors lack facts (on demand, not "whatever any user might want") |
| **run** | one step of one user run (§8.5) | schedule tick, "Run now", or a run's crawls/facts finishing |

Fairness: the run queue round-robins across users; all model calls go through one
rate-limited client with per-user token metering; scheduled runs are **staggered**
(a user choosing "Monday 09:00" is placed at a random offset within the hour) so a
popular slot does not hit the provider's rate limit at once.

### 8.5 What "a run" means now

v2's run = scrape 10 companies. Multi-user, crawling is shared, so a user's run =
*"bring my shortlist up to date"*. It is a **state machine**, re-queued between steps,
so a waiting run never holds a worker:

```
queued → awaiting_crawl → filtering → judging → done | partial | failed
```

1. **queued → awaiting_crawl:** freeze the company list (`run_companies`); enqueue crawls
   for companies past the user's tier window (measured from `last_success_at`); park the
   run until they finish or a timeout.
2. **filtering:** the user's prefilter over open postings of those companies, skipping
   any with a `user_prefilter` row for the current `rules_hash`.
3. **judging:** ensure facts for survivors (enqueue facts jobs, park, resume); then the fit
   prompt, batched per user, skipping any with a `user_fit` row for the current keys;
   code decides (D-17).
4. **done / partial / failed**, and the UI is notified.

**Quota (D-26):**
- **Charge** at `queued`, inside a transaction that locks the user's subscription row;
  refuse if the balance is zero. At most **one active run per user** (partial unique
  index on `runs(user_id) WHERE state not in (done, partial, failed)`).
- **Refund rules:** `failed` for a system reason → refund. Model provider down → the run
  pauses and resumes free. Some companies blocked or failing → `partial`, **no refund**
  (the rest of the run was delivered).
- **Scheduler dedupe:** `UNIQUE (user_id, scheduled_for)` on runs, so a restart or a double
  tick never runs or charges twice.
- **Re-judge cost:** editing the profile or interests changes `fit_input_hash`, so the next
  run re-judges that user's open survivors. That run is charged normally; free-tier edits
  are rate-limited so a user cannot trigger unlimited re-judges.

**"Choose when to run":** preferences hold *Manual*, *Weekly on {day} at {time}*,
*Fortnightly*, or *Daily (higher tiers)*, in Singapore time; a per-minute tick enqueues
due runs if quota remains.

### 8.6 The user's inputs → the v2 engine

| User input | Feeds |
|---|---|
| Resume | profile ingest (v2 M2), after stripping contact details → skills, target titles, summary |
| Role types (intern / FT / contract, multi-select) | generated rules: seniority/intern words in `title_deny` depend on the selection; a rule on `employment_type_raw` → `posting_facts.employment_type` (unknown passes to fit, as D-2) |
| Keywords / interests | `title_allow.extra` + the fit prompt's interests (v2 D-18) |
| Experience ceiling | `experience_ceiling` rule + the guard's `yoe_min` cap, per user |
| Target companies | `user_companies`; new URLs → shared discovery (SSRF-checked, pending review) |
| Locations (default Singapore) | `location_explicit` allow tokens, per user |
| Schedule | the per-user run scheduler (§8.5) |

### 8.7 Web app changes (building on M12)

- **Public pages:** landing, pricing, privacy policy, terms. Signed out users see only these.
- **Auth:** "Continue with Google"; sign-out; delete account; export my data; withdraw consent.
- **Onboarding wizard** (five steps, resumable): resume → role types → keywords & YOE →
  companies → schedule; the first run starts at the end.
- **Tabs** (M12 shell kept): Inbox · Applications · Runs · Profile · **Companies** (search
  the catalog, add by URL, crawl health) · **Billing** (plan, runs left, upgrade via
  Stripe) · Settings. Inbox shows a short extract and the employer's link, not the full
  description.
- **Admin** (owner only): users, crawl health and block rate, companies pending review,
  queue depth, LLM spend, manual quota grants.

---

## 9. Viability and the key design questions

### 9.1 Is it viable?

**Technically: yes.** Every stage exists in v2 and is measured; the new work —
multi-tenancy, auth, billing, a queue, hosting — is well-trodden.

**Economically: yes, if work stays shared.** At 200 users the service costs roughly
**US$30–45/month** (§10.3); break-even is ~10 paying users on the cheapest paid tier (§11).

**The binding constraints are operational, not financial:** careers sites blocking a
datacenter IP (unmeasured until P0), the LinkedIn requirement (§9.7), privacy duties
(§12.3), and one person operating a public service.

### 9.2 Why sharing is the whole economic case

Estimate *(assumption — validate from sign-ups)*: 200 users × ~40 companies each with
heavy overlap → ~1,000–2,000 distinct companies. Crawl cost scales with distinct
companies; fact extraction with distinct new postings; only fit grows with users, and fit
is cached per content (D-28), so steady-state runs judge only *new* postings.

### 9.3 LLM: per user or shared? → **Shared**

- A model per user buys nothing: the model is stateless; personalisation is the prompt
  and the database.
- One endpoint, one rate-limited client, per-user metering and batching. A fit prompt
  holds exactly one user's profile; a facts prompt holds no user data and one company's
  postings.
- **Thinking disabled** on every call (`enable_thinking=false`, as v2's Ollama backend
  sends `think: false`) — otherwise output tokens multiply.
- **Fallback provider:** if it is outside Singapore (e.g. DeepInfra, US), send it only
  facts prompts (no personal data), or name it in the privacy notice (§12.3).

### 9.4 Which Qwen, where → **Alibaba Model Studio, Singapore endpoint**

| Option | Price per 1M tokens (in / out) | Notes |
|---|---|---|
| Qwen Flash on Model Studio, **Singapore** endpoint | ~US$0.10–0.15 / 0.40–0.47 *(verified)* | In-region; 1M free tokens per model for 90 days |
| Qwen3-14B (open weights — what v2 validated) via DeepInfra / OpenRouter | ~US$0.10 / 0.22 *(verified)* | Outside Singapore |
| Self-hosted Qwen3-14B on a cloud GPU | ≥ ~US$360/month always-on (estimate) | Only far beyond 200 users |
| Ollama on the owner's PC | electricity | Development only |

**Quality gate — in P3, on the split pipeline, not on v2's prompt.** v2's 17/17 result
was one persona and one combined prompt. The gate is: the facts prompt on a labelled set
(Singapore / not / vague; years; employment type), and the fit prompt on small case sets
for **several personas** (new-grad engineer — v2's 17 cases; an internship seeker; a
contract seeker; a non-engineering interest profile such as operations or product).
Pass: no accepted role outside the chosen locations, and agreement with the labels at or
above v2's.

### 9.5 LLM cost estimate *(assumptions stated)*

| Step | Volume per month (200 users) | Tokens | Cost at ~US$0.14 / 0.42 |
|---|---|---|---|
| Facts (on demand, one company per batch) | ~30,000–60,000 new/changed postings reaching some user's step 3 × ~700 in / ~60 out | ~21–42M in / 2–4M out | ~US$4–8 |
| Fit, steady state | 200 users × ~4 runs × ~50 *new* survivors × ~600 in / ~80 out | ~24M in / 3M out | ~US$5 |
| Fit, onboarding + re-judges after edits | ~200 first runs × ~300 survivors + edits | ~40M in / 5M out | ~US$8 |
| Resume parsing | ~250 × ~4,000 in / ~800 out | ~1M in / 0.2M out | ~US$0.2 |
| **Total** | | | **≈ US$15–25/month** |

Self-hosting breaks even only when token spend exceeds a GPU's cost — roughly 15–25×
this — i.e. thousands of active users. Revisit at 2,000 MAU.

### 9.6 Crawling at multi-user scale

- ~1,000–2,000 companies on 1–7-day windows ≈ 150–1,000 company fetches a day — one crawl
  queue with v2's per-host rate limits handles it.
- Storage: ~33k postings for 224 companies today → ~300k postings (~2 GB) at 2,000 companies.
- **Biggest unmeasured risk: datacenter-IP blocking.** Sites behind Cloudflare/Akamai bot
  protection often block cloud IPs that a home connection passes. **P0 runs a 48-hour
  crawl of the full catalog from a US$6 Singapore droplet** and compares coverage with v2's.
  If coverage drops materially, the design needs an answer *before* P1 (slower crawling,
  conditional requests, a residential-grade egress for blocked hosts only, or dropping
  those companies).

### 9.7 LinkedIn → **not scraped; compliant alternatives only**

Findings *(verified 2026-09-25)*: LinkedIn has **no API to search or read job postings**
(its Job Posting API is for approved partners to *post*, and it is not accepting new
partners); its User Agreement prohibits scraping; LinkedIn sued Proxycurl in January 2025
and the service shut down in July 2025 under a permanent injunction.

The requirement "find LinkedIn postings from the companies' official accounts" is met
without touching LinkedIn's servers:
1. **Most already reach us.** A company's LinkedIn postings are usually syndicated from its
   own ATS, which the crawler reads. *TBD — P0 measures it:* hand-sample 50 LinkedIn
   postings from 10 target companies and count how many are in the catalog.
2. **Close the gap at the source:** find the ATS or careers feed behind the missing ones;
   add a generic schema.org `JobPosting` (JSON-LD) adapter for careers pages on no known ATS.
3. **User-supplied links:** a user can paste a LinkedIn job URL into Applications; we store
   the link and what they typed — we never fetch the page.
4. **Licensed data only after legal review** of a vendor's licence. Not in the MVP.

### 9.8 Extensibility beyond 200 users and beyond Singapore

- Stateless API → more API containers behind Caddy or a load balancer.
- Queues → split the worker into per-queue processes, then separate VMs.
- Postgres → managed Postgres (same engine, same `store.py`); a read replica for the
  catalog if needed.
- Locations are per-user preferences and facts carry `locations[]`: a new market is data
  and prompt work, not a redesign.
- The LLM backend is pluggable; self-hosting becomes config when volume justifies it.

---

## 10. Hosting — cheapest viable, in Singapore

### 10.1 Options compared *(prices verified 2026-09-25, USD/month)*

| Option | What | Monthly | Verdict |
|---|---|---|---|
| **A. One small VM** *(recommended)* | DigitalOcean SGP1 droplet, **2 GB** (US$12–18): Caddy, API, one worker process (three queues), Postgres tuned small (e.g. `shared_buffers` 256 MB); resumes encrypted in Postgres; backups + WAL archive encrypted to Cloudflare R2 (free tier) | **~US$12–18** | Cheapest viable: the LLM is remote, so the box only runs a web app, a crawler and a small database. Resize to 4 GB (US$24) with one reboot. |
| B. VM + Supabase | Supabase Pro (US$25: Postgres, Google Auth, storage, AWS Singapore) + a small droplet | ~US$37–43 | Less ops (managed backups, auth); twice the cost. The fallback if running Postgres proves burdensome. |
| C. VM + managed Postgres | droplet + DigitalOcean Managed Postgres (from ~US$15) | ~US$27–40 | The scale-out path for the database. |
| D. Serverless (Cloud Run + Neon) | scale-to-zero containers + serverless Postgres | ~US$0–30 | Free tiers mostly in US regions; long crawls and a scheduler fit poorly. |
| E. Hetzner Singapore | CPX11 (2 GB) US$20.49 / CPX21 (4 GB) US$37.49 | ~US$21–38 | No longer cheapest in Singapore after the 2026 price rise; 0.5–1 TB traffic. |

**Recommendation (D-25): Option A.** If backups must stay in Singapore rather than R2's
nearest region, use DigitalOcean Spaces SGP (US$5) instead.

**Durability:** nightly `pg_dump` alone risks up to a day of lost data (applications,
payments). Use **continuous WAL archiving** (e.g. WAL-G) to object storage plus a nightly
base backup, both encrypted before upload; a **restore drill** before launch and monthly.

**Scale-out triggers — measured, not guessed:** run-queue p95 > 15 min; sustained CPU or
RAM > 70%; disk > 70%; crawl block rate rising by IP; or a restore drill > 1 hour. The
first response is resizing the VM; the next is managed Postgres (C) and a second worker VM.

### 10.2 Deployment shape

- Docker Compose (v2 M10 already packages the app); images built in GitHub Actions and
  pulled on the VM; restart the API container behind Caddy to deploy.
- Cloudflare DNS (free); Caddy for automatic TLS.
- **Firewall trap:** Docker-published ports bypass `ufw`. Publish only Caddy's 80/443;
  keep Postgres on the internal Docker network; use the cloud firewall as well.
- Secrets in environment files readable only by the service user; nothing in git.
- Monitoring: uptime check, error tracking (free tier, with personal data scrubbed), a
  daily metrics email (runs, failures, LLM spend, crawl block rate).

### 10.3 Total monthly cost at 200 users *(estimate)*

| Item | USD/month |
|---|---|
| VM (Option A, 2 GB → 4 GB if needed) | 12–24 |
| Backups (R2 free tier, or Spaces SGP) | 0–5 |
| Qwen (hosted, §9.5) | 15–25 |
| Domain (amortised), monitoring free tiers | ~1–2 |
| Stripe fees | per payment (§11) |
| **Total** | **≈ US$30–45** (≈ US$0.15–0.25 per user) |

---

## 11. Tiers, quotas and unit economics

*(Prices are proposals — TBD, needs validation via a pricing test.)*

| Tier | Price | Runs / month | Companies | Crawl freshness | Schedules |
|---|---|---|---|---|---|
| Free | S$0 | 4 | 20 | ≤ 7 days | manual, weekly |
| Plus | S$5 / month | 16 | 60 | ≤ 3 days | + fortnightly, twice weekly |
| Pro | S$12 / month | 60 | 200 | ≤ 1 day | + daily |

- **Payments:** Stripe Checkout + Customer Portal + webhooks (signature-verified,
  idempotent via `stripe_events`). Singapore fees *(verified)*: PayNow **1.3%**, cards
  **3.4% + S$0.50** — ~13% of a S$5 card payment, so **offer PayNow and annual plans**
  (e.g. S$50/year for Plus).
- **Break-even:** ~US$40/month ≈ S$52 → ~10 Plus subscribers, or ~5 Pro.
- **Cost per run** (estimate): ~US$0.01–0.02 in LLM plus a share of crawling; quotas mainly
  bound abuse and set the upgrade path.
- **Ledger rules** (§8.5): charged at start, refunded by rule, no rollover, admin grants
  are ledger entries too.

---

## 12. Security, privacy and abuse

### 12.1 Authentication and sessions

Google OIDC authorization-code flow with PKCE, scopes `openid email profile` only;
validate the ID token; key the account on `sub` and require `email_verified`.
Server-side sessions (`sessions` table), cookie HttpOnly + Secure + SameSite=Lax, rotated
at sign-in; CSRF protection on every state-changing request (v2's cross-site write guard,
generalised from loopback to the public origin); sign-out everywhere.

### 12.2 Hardening a public service needs (v2 did not)

- **Row-level security that actually binds:** `FORCE ROW LEVEL SECURITY` on per-user tables
  (a table owner otherwise bypasses RLS); each request's transaction runs
  `SET LOCAL app.user_id`; the API connects as a role without RLS bypass; only the worker
  role may act across users. Isolation tests in CI: one user can never read or write
  another's rows through any endpoint.
- **SSRF** (users add careers URLs the server fetches): refuse private, loopback,
  link-local, cloud-metadata **and Docker-network** ranges; resolve once and connect to the
  checked IP (defeats DNS rebinding); re-check after every redirect; cap size and time.
- **Shared-fact poisoning (D-29):** one company per facts batch; user-added companies'
  facts private until reviewed; the code-decides guard still requires Singapore confirmed.
- **Uploads:** v2's rules (raw body, 5 MB cap, magic bytes) plus parsing in a **sandboxed
  subprocess** with memory and time limits; resumes are never served back as files. (An
  antivirus daemon such as ClamAV needs ~1 GB of RAM — not worth it on a 2 GB box when the
  file is only parsed, never served.)
- **Rate limits:** per user and per IP (Caddy + application); queue fairness (§8.4).
- **Logs:** never log prompts, resume text or job-description bodies; scrub personal data
  from error-tracker events.
- **Secrets:** Qwen and Stripe keys only in the processes that use them.

### 12.3 Singapore PDPA *(summary — confirm against PDPC guidance or with counsel before launch)*

- **Consent and purpose:** a notice at sign-up (versioned in `consents`) that the resume is
  processed to find matching jobs, including by a named third-party AI provider.
  **Withdrawal** of consent stops processing; the account can then be deleted.
- **Minimum age:** set one (students are the primary users) and state it in the terms.
- **Minimisation:** strip name, email and phone from resume text before any model call;
  offer to delete the raw resume after parsing.
- **Protection:** resumes encrypted at rest. *Honest limit:* the encryption key sits on the
  same VM as the data, so this protects backups and disk images, not a compromised server —
  say so internally; move the key to a KMS when scaling out.
- **Retention and deletion:** live data deleted immediately on account deletion; backups
  expire it within the stated retention window (e.g. 30 days) — published in the policy.
- **Access and correction:** export my data; edit my profile; answer access requests within
  30 days.
- **Transfers abroad (s.26):** list every overseas processor — Google (sign-in), Stripe,
  Cloudflare (DNS/R2), the error tracker, and any non-Singapore LLM fallback — with the
  safeguards relied on.
- **Breach management:** an incident plan; notify the PDPC **within 3 calendar days** of
  assessing a breach as notifiable, and affected users where required.
- **Data Protection Officer:** designate one (the owner at launch) and publish a contact.
- **Content:** show a short extract and link to the employer's posting; do not republish full
  job descriptions to many users.

---

## 13. Delivery milestones

Business outcomes, not engineering tasks — `/plan` turns each into a plan.

| # | Milestone | Outcome | Status | Plan |
|---|---|---|---|---|
| P0 | Validate the premises | Landing page + waitlist + 10 interviews; **48-hour datacenter-IP crawl test** (§9.6); LinkedIn coverage sample (§9.7); pricing test | pending | — |
| P1 | Multi-tenant core | Postgres; shared vs per-user tables with content-hash keys (D-28); user-scoped `store.py` + forced RLS; **deletion cascade and export built in**; the owner's v2 data migrated as user #1 | pending | — |
| P2 | Accounts and onboarding | Google sign-in, consents, onboarding wizard, per-user profile, preferences, companies | pending | — |
| P3 | Queue, workers, two-step judging | crawl/facts/run queues; run state machine; facts + fit prompts (D-22); **the quality gate on the split pipeline** (§9.4); one-time facts backfill for the catalog | pending | — |
| P4 | Private beta in Singapore | Option A live behind an allowlist; TLS, WAL archiving, restore drill; **SSRF, RLS and isolation tests passing**; monitoring | pending | — |
| P5 | Schedules and quotas | per-user schedules (staggered), quota ledger, refund rules | pending | — |
| P6 | Retention beta | 20–50 waitlist users for 4+ weeks; measure §5's retention before charging | pending | — |
| P7 | Billing | Stripe tiers with PayNow, customer portal, idempotent webhooks | pending | — |
| P8 | Public launch | privacy policy, terms, PDPA checklist (§12.3), minimum age; open sign-ups | pending | — |
| P9 | LinkedIn gap closure | missing ATS feeds added per the P0 sample; JSON-LD `JobPosting` adapter; paste-a-link tracking | pending | — |
| P10 | Scale-out readiness | managed Postgres, per-queue workers, a second VM — when §10.1's measured triggers fire | pending | — |

---

## 14. Open questions

- [ ] **Datacenter-IP coverage** — how much of the catalog blocks a cloud IP? *P0 test (§9.6).*
      This can change the hosting design.
- [ ] **Price points and tiers** — S$5 / S$12 are guesses. *Pricing test.*
- [ ] **Hosted Qwen quality** — does Qwen Flash on Model Studio pass the P3 gate? If not,
      Qwen3-14B via a fallback provider (outside Singapore — facts prompts only) or a larger model.
- [ ] **LinkedIn coverage gap** — how many target-company LinkedIn postings are missing from
      the catalog? *P0 hand sample.*
- [ ] **Catalog moderation** — who reviews user-added companies before their facts are shared,
      and how fast? (D-29 makes the default "private until reviewed".)
- [ ] **Freshness windows** — are 7 / 3 / 1 days right per tier?
- [ ] **Resume retention default** — delete the raw file after parsing?
- [ ] **Minimum age** — which age, and is parental consent needed below it?
- [ ] **Operator** — personal or company entity for Stripe and PDPA purposes?
- [ ] **Support promise** — channel and response time at launch.

## 15. Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-M1 | Careers sites block the server's datacenter IP | **Medium–High** | High | P0 measures it first; robots + per-host delays; conditional requests; spread crawls; alternatives decided before P1 (§9.6) |
| R-M2 | The LinkedIn requirement tempts scraping → legal exposure | Medium | High | D-24; the compliant route (§9.7); written legal basis before any data vendor |
| R-M3 | Cross-tenant data leak | Low | Very high | forced RLS, per-request `SET LOCAL`, separate DB roles, isolation tests in CI, audit log |
| R-M4 | Shared-fact poisoning by a hostile posting or user-added page | Medium | High | D-29: single-company batches, private-until-reviewed, the guard |
| R-M5 | PDPA breach or complaint | Low | High | §12.3 checklist before launch; encryption; incident plan; DPO |
| R-M6 | Hosted Qwen quality below v2's local Qwen3-14B | Medium | Medium | P3 gate on the split pipeline, several personas; fallback model; code decides |
| R-M7 | LLM rate-limit peaks at popular schedule slots | Medium | Medium | staggered schedules; one rate-limited client; runs pause and resume |
| R-M8 | Cost blow-up from cache invalidation (edits trigger mass re-judges) | Medium | Medium | content-hash keys (D-28); re-judges charged as runs; edit rate limits |
| R-M9 | Single-VM outage or data loss | Medium | High | WAL archiving + nightly base backups off-VM; monthly restore drill; measured scale-out triggers |
| R-M10 | SSRF via user-supplied careers URLs | Medium | High | §12.2: IP checks incl. Docker ranges, resolve-once, redirect re-checks, caps |
| R-M11 | Single operator: incidents, support and moderation depend on one person | High | Medium | allowlisted beta first; automated alerts; clear support promise; admin tooling |
| R-M12 | Republishing job-description content | Low | Medium | extract + link only (§12.3) |
| R-M13 | Card fees eat small payments | High | Low | PayNow and annual plans (§11) |
| R-M14 | Qwen provider price or availability changes | Low | Medium | pluggable OpenAI-compatible backend; second provider configured |
| R-M15 | Demand lower than assumed | Medium | High | P0 and the P6 retention beta come before billing |

---

## 16. Sources (checked 2026-09-25)

- Qwen pricing, Model Studio Singapore endpoint: [Alibaba Cloud Model Studio pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing), [BenchLM Qwen API pricing](https://benchlm.ai/alibaba/api-pricing), [eesel AI Qwen pricing](https://www.eesel.ai/blog/qwen-pricing)
- Qwen3-14B / 30B-A3B hosted prices: [OpenRouter Qwen3 14B](https://openrouter.ai/qwen/qwen3-14b), [OpenRouter Qwen3 30B A3B](https://openrouter.ai/qwen/qwen3-30b-a3b), [DeepInfra Qwen pricing guide](https://deepinfra.com/blog/qwen-api-pricing-2026-guide)
- LinkedIn: [Job Posting API overview (Microsoft Learn)](https://learn.microsoft.com/en-us/linkedin/talent/job-postings/api/overview?view=li-lts-2026-03), [LinkedIn API access in 2026 (Phyllo)](https://www.getphyllo.com/post/linkedin-api-access-in-2026-partner-program-approval-timeline-alternatives), [Proxycurl shutdown](https://nubela.co/blog/goodbye-proxycurl/), [LinkedIn wins case against Proxycurl](https://www.socialmediatoday.com/news/linkedin-wins-legal-case-data-scrapers-proxycurl/756101/)
- Hosting: [DigitalOcean droplet pricing](https://www.digitalocean.com/pricing/droplets), [DigitalOcean managed Postgres pricing](https://docs.digitalocean.com/products/databases/postgresql/details/pricing/), [Hetzner 2026 price adjustment](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/), [Hetzner CPX11](https://sparecores.com/server/hcloud/cpx11), [Supabase pricing](https://supabase.com/pricing), [Cloud Run pricing](https://cloud.google.com/run/pricing), [Neon pricing](https://neon.com/pricing)
- Payments: [Stripe Singapore pricing](https://stripe.com/en-sg/pricing), [Stripe local payment methods](https://stripe.com/en-sg/pricing/local-payment-methods)

---
*Status: DRAFT r2 — requirements and target design, architect-reviewed. Next step: P0
(validate the premises — above all the datacenter-IP crawl test), then
`/plan .claude/prds/mullti_user_prd.md` for P1.*
