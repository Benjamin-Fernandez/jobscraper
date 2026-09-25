# mullti_user_prd — JobScraper as a public, multi-user cloud service

**Status:** DRAFT — requirements + target design. Nothing here is built yet.
**Created:** 2026-09-25 · **Owner:** Benjamin
**Builds on:** the single-user v2 in `.claude/prds/jobscraper-v2.prd.md` (M0–M12:
watchlist → staleness scheduler → ATS scrape → free prefilter → Qwen facts →
code decides → shortlist → Vue web app with run control, resume upload and
companies-per-run).
**Method:** requirements skeleton from the ECC `plan-prd` skill (problem →
evidence → users → hypothesis → metrics → scope → milestones → questions →
risks). Per the owner, this document also carries the **target design and the
hosting choice**, which the skill normally defers to `/plan` — they are §8–§12.

> **How to read this.** §1–§7 say *what* must be true and *why*. §8–§12 say how the
> current v2 must change to get there, with costs. §13–§15 are the plan, the
> questions and the risks. Figures marked *(verified 2026-09-25)* come from the
> sources in §16; everything else is an estimate and says so.

---

## 1. Problem

Job seekers in Singapore who target specific companies must check each company's
careers site by hand, repeatedly, and read every posting to find the few that fit
their level, contract type and interests. JobScraper already does this well for
one person — 224 companies, ~33,000 postings a cycle, ~90 shortlisted roles, all
confirmed Singapore — but only for someone who can run Python, edit YAML and host
a local LLM. Everyone else keeps doing it by hand, or relies on job boards that
bury company-direct postings among agency and duplicate listings.

## 2. Evidence

- **Observed (v2, 2026-09-24).** One full cycle over 224 companies: ~21,600–33,000
  postings, a free prefilter passing <1%, and a shortlist of 90 roles with 0 accepted
  outside Singapore. The mechanism works; the question is whether others want it.
- **Observed (v2).** The per-company work (scraping, and the model reading a posting's
  facts) is identical for every user who watches that company — the property that
  makes a shared service cheap (§9.2).
- **Assumption — needs validation via user interviews + a landing page with a
  waitlist:** that Singapore job seekers (students and early-career first) want a
  company-watch tool and will pay a few dollars a month for more runs.
- **Assumption — needs validation via a pricing test:** willingness to pay at the
  tier prices in §11.

## 3. Users

- **Primary:** job seekers **in Singapore** — final-year students and graduates
  (internship / new-grad), and early-career professionals — who have a list of
  companies they want to work for and a clear idea of the roles they want.
  Triggered weekly/fortnightly, or when their target companies open a hiring season.
- **Secondary (later):** career-services offices at Singapore universities (a
  cohort plan). Out of scope for the MVP.
- **Not for:** recruiters and agencies (no candidate search, no bulk data export),
  mass-apply automation, users outside Singapore at launch (§9.8 keeps the door open).

## 4. Hypothesis

We believe **a hosted JobScraper where a user uploads a resume, picks role types,
keywords, an experience ceiling and their target companies, and gets a fresh,
Singapore-verified shortlist on their own schedule** will **replace manual
careers-site checking** for **Singapore job seekers**.
We'll know we're right when **≥ 40% of users who complete onboarding open their
Inbox in at least 3 of their first 6 weeks, and ≥ 5% of active users pay** —
at an infrastructure cost that stays **below US$0.50 per active user per month**.

## 5. Success Metrics

| Metric | Target | How measured |
|---|---|---|
| Onboarding → first shortlist | ≤ 10 min, ≥ 70% of sign-ups | event log: `signed_up` → `first_shortlist_ready` |
| Weekly retention | ≥ 40% open Inbox in 3 of first 6 weeks | Inbox view events |
| Paid conversion | ≥ 5% of monthly active users | Stripe subscriptions ÷ MAU |
| Location precision | 100% of accepted roles in the user's chosen locations (Singapore at launch) | automated check + monthly hand audit of 30 |
| Infra + LLM cost | < US$0.50 per active user per month | monthly bill ÷ MAU |
| Run success | ≥ 98% of scheduled runs finish | `runs.status` |
| Availability | ≥ 99% monthly | uptime monitor |
| Data requests | account deletion completes ≤ 7 days (target: immediate) | deletion log |

## 6. Scope

### MVP — what tests the hypothesis

1. **Sign up / log in with Google** (no passwords).
2. **Onboarding:** upload resume (PDF/DOCX) → choose **role types** (internship,
   full-time, contract — any combination) → **keywords and interests** (the
   `judge.interests` list, per user) → **experience ceiling** (years) → **target
   companies** (search the shared catalog or add by careers URL) → **schedule**.
3. **Runs on the user's schedule** (manual, weekly, fortnightly — at a chosen day/time
   in Singapore time), counted against the user's quota.
4. **The v2 funnel per user:** shared scrape → shared posting facts → per-user
   prefilter → per-user fit judgment by Qwen → per-user shortlist.
5. **The v2 web app, made multi-user:** Inbox, Applications, Runs, Profile,
   Companies, Settings, **Billing**.
6. **Quotas and paid tiers** (Stripe, PayNow + cards).
7. **Hosting in Singapore** at the cost in §10.
8. **Privacy basics for a public service:** consent, deletion, export, encryption of
   resumes at rest, a privacy policy (PDPA, §12.3).

### Out of scope (MVP)

| Item | Why deferred |
|---|---|
| **Scraping LinkedIn** | Prohibited by LinkedIn's User Agreement; see §9.7 for the compliant alternative. |
| Auto-apply / filling application forms | Different product; high abuse and ToS risk. |
| Non-Singapore locations | Launch market; the data model keeps location per user (§9.8). |
| Email/Telegram alerts | Valuable, but not needed to test the hypothesis; first post-MVP item. |
| Mobile apps | The responsive web app (M12) covers phones. |
| Per-user self-hosted LLMs | Cost-prohibitive at this scale (§9.5). |
| University/cohort accounts | Secondary segment; after the hypothesis holds. |

---

## 7. Decision Register (new)

Numbered from D-19 so they sit beside the v2 decisions (D-1–D-18).

| # | Decision | Rationale |
|---|---|---|
| **D-19** | **Split the data into a shared catalog and per-user layers.** Companies, postings and each posting's *facts* are global; preferences, decisions, shortlists and applications are per user. | Scraping and fact extraction are identical for every user who watches a company. Sharing them makes cost scale with *distinct companies*, not users. |
| **D-20** | **One shared Qwen endpoint, pay-per-token, not a model per user.** | ~US$15/month for 200 users vs ≥ US$360/month for one always-on GPU (§9.5). Per-user isolation is achieved in the prompt and data, not the model. |
| **D-21** | **Hosted Qwen on Alibaba Cloud Model Studio's Singapore endpoint, behind the existing pluggable backend**, with an OpenAI-compatible fallback provider. Ollama stays for local development. | In-region (latency, PDPA posture), cheapest per token, and D-16 already chose Qwen. |
| **D-22** | **Two-step judging: global facts once per posting, per-user fit once per (user, posting).** Code still decides (D-17). | Facts (Singapore?, years, employment type, seniority) do not depend on the user, so they are paid for once. Only fit is per user. |
| **D-23** | **Google sign-in only (OIDC), server-side sessions.** | The owner's requirement; no password storage; Google provides verified email. |
| **D-24** | **No LinkedIn scraping.** Company postings come from their ATS (as v2); LinkedIn is used only via links the *user* provides. | §9.7: no read API exists; scraping breaches LinkedIn's terms and was enforced in 2025. |
| **D-25** | **Start on one Singapore VM with Docker Compose + Postgres; managed pieces only where they remove real risk** (backups, object storage). | Cheapest viable (§10) at ≤ 200 users; the design keeps each piece separable for scale-out. |
| **D-26** | **Quota = runs per month, enforced server-side; a failed run is refunded.** | Matches the owner's model and maps directly to LLM + crawl cost. |
| **D-27** | **Postgres replaces SQLite; `store.py` stays the only SQL module.** | v2 §8.4 designed for exactly this swap; multi-user concurrency needs it. |

---

## 8. Target design — what changes from v2

### 8.1 What stays, what changes

| v2 piece | Multi-user fate |
|---|---|
| ATS adapters, discovery, `net.py` (rate limits, robots) | **Kept.** Now fed by the shared catalog; gains SSRF protection for user-supplied URLs (§12.2). |
| Staleness scheduler (per-company, 14 days) | **Kept for the shared crawl**, re-tuned (freshness per company driven by how many users watch it). A second, **per-user run scheduler** is new (§8.5). |
| Free prefilter (`rules.yaml`, rule registry) | **Kept, per user.** System default rules + each user's rules generated from their preferences (role types, keywords, YOE, locations). |
| Vital extract | **Kept, global** (one per posting). |
| Decide: Qwen reports facts, code decides (D-17) | **Split** into global facts + per-user fit (D-22). The guard is unchanged. |
| Resume ingest → derived profile | **Kept, per user.** Resume in object storage, encrypted. |
| `shortlist.json` file | **Replaced by a query** over per-user decisions (a file per user does not scale). |
| SQLite, `store.py` | **Postgres**, `store.py` still the only SQL (D-27). |
| `config.yaml` → `judge.interests`, `batch_size` … | **Per-user settings in the database**; `config.yaml` keeps only system settings. |
| Vue web app (M12 tabs) | **Kept and extended**: auth, onboarding wizard, Companies and Billing tabs, admin screen. |
| Web ↔ run isolation (M11: runs as child processes) | **Generalised** into a job queue with workers (§8.4). |
| Loopback-only, no auth (R-9) | **Replaced**: public HTTPS, Google sign-in, sessions, CSRF, rate limits (§12). |
| Ollama backend | **Dev only**; production uses the hosted Qwen backend (D-21). |

### 8.2 Architecture

```
                    Users (browser, Singapore)
                              │ HTTPS
                  ┌───────────▼────────────┐
                  │ Caddy (TLS, gzip, static SPA, rate limit)   one Singapore VM
                  └───────────┬────────────┘                   (Docker Compose)
                              │
            ┌─────────────────▼──────────────────┐
            │  API  (FastAPI, stateless)         │  Google OIDC · sessions · quotas
            │  /auth /me /onboarding /runs       │  Stripe webhooks · admin
            │  /shortlist /applications /billing │
            └──────┬───────────────────┬─────────┘
                   │ enqueue           │ read/write
            ┌──────▼──────┐     ┌──────▼────────────────────────────┐
            │  Job queue  │     │  Postgres                          │
            │ (Postgres,  │◄───►│  shared: companies, postings,      │
            │ SKIP LOCKED)│     │          posting_facts, crawls     │
            └──────┬──────┘     │  per user: users, preferences,     │
                   │            │  user_companies, profiles, runs,   │
       ┌───────────┼──────────┐ │  prefilter, fit, applications,     │
       ▼           ▼          ▼ │  subscriptions, usage              │
  ┌─────────┐ ┌─────────┐ ┌─────────┐ └──────────────────────────────┘
  │ crawler │ │ facts   │ │ user-run│         Object storage (S3-compatible)
  │ worker  │ │ worker  │ │ worker  │         resumes (encrypted), backups
  └────┬────┘ └────┬────┘ └────┬────┘
       │ HTTP      │           │
  company ATS      └────┬──────┘
  (Greenhouse,          ▼
   Workday, …)   Hosted Qwen (Alibaba Model Studio, Singapore endpoint)
                 fallback: OpenAI-compatible provider (e.g. DeepInfra Qwen3-14B)
```

Every box is a container on one VM at launch; each can move to its own machine
without code changes (§9.8).

### 8.3 Data model (shared vs per user)

**Shared catalog (no user data):**
- `companies` — v2's table plus `watchers` (count of users watching), `added_by`
  (null for seeded), `status` (active / unresolvable / blocked).
- `postings` — v2's `jobs`, unchanged in meaning (company, title, location, URL,
  description, vital extract, first/last seen, closed).
- `posting_facts` — **new:** `(posting_id, vital_hash, model) → is_singapore /
  locations[], yoe_min, employment_type (intern | full_time | contract | unknown),
  seniority, extracted_at`. Paid for once per posting per description version.
- `crawls` — per-company crawl attempts (v2's `coverage`, global).

**Per user (every row carries `user_id`; every query is scoped by it):**
- `users` — Google `sub`, email, name, created_at, locale, deleted_at.
- `preferences` — role types, keywords/interests list, experience ceiling, allowed
  locations (default `[singapore]`), schedule, timezone (`Asia/Singapore`).
- `user_companies` — which catalog companies the user watches (+ priority).
- `profiles` — derived profile (v2 shape: skills, target titles, summary, version),
  resume object key, resume hash.
- `user_rules` — generated prefilter rules + the user's own `extra:` entries.
- `runs` — per-user run records (requested_at, source: manual | schedule, status,
  stats, quota_charged).
- `user_prefilter`, `user_fit` — v2's `prefilter` / `decisions`, keyed per user.
- `applications`, `app_events` — v2's, per user.
- `subscriptions`, `usage` — plan, period, runs used, Stripe ids.
- `audit_log` — sign-ins, deletions, exports, admin actions.

**Isolation rule (normative):** the API layer never builds a query without the
session's `user_id`; `store.py` exposes only user-scoped methods for per-user
tables, and a test asserts that every per-user method takes `user_id`. Postgres
row-level security is a second line of defence (§12.2).

### 8.4 Work model: queue + three workers

A Postgres table-backed queue (`FOR UPDATE SKIP LOCKED`) — no Redis at this size.

| Worker | Unit of work | Trigger |
|---|---|---|
| **crawler** | one company: resolve ATS (shared), fetch, diff, persist postings | company is stale — freshness target shortens with more watchers (e.g. 1 watcher: 7 days; ≥ 5: 2 days); or a user run finds its companies stale |
| **facts** | a batch of new/changed postings that pass *any* user's cheap title/location screen → Qwen facts | new postings after a crawl |
| **user-run** | one user run: prefilter the user's companies' open postings → fit for survivors (Qwen, batched per user) → the user's shortlist | the user's schedule, or "Run now" |

Fairness: the user-run worker round-robins across users so one heavy user cannot
starve others; Qwen calls go through one rate-limited client with per-user token
metering (for quota and abuse checks).

### 8.5 What "a run" means now

v2's run = scrape 10 companies. Multi-user, **scraping is decoupled and shared**, so a
user's run = *"bring my shortlist up to date"*:
1. Ensure the user's companies were crawled within their tier's freshness window
   (enqueue crawls for stale ones; the run waits for them, up to a timeout).
2. Run the user's prefilter over open postings from those companies not yet judged
   for this user's current profile + rules.
3. Ensure facts exist for survivors (shared), then judge fit (per user), code decides.
4. Update the shortlist and notify the UI.

One run is charged when step 1 starts; refunded if the run fails for a system reason.

**The owner's "choose when to run":** a schedule in preferences — *Manual only*,
*Weekly on {day} at {time}*, *Fortnightly*, or *Daily (higher tiers)* — in Singapore
time. A per-minute scheduler tick enqueues due user runs if quota remains.

### 8.6 The user's inputs → the v2 engine

| User input (onboarding) | Feeds |
|---|---|
| Resume | profile ingest (v2 M2) → skills, target titles, summary |
| Role types (intern / FT / contract, multi-select) | a new prefilter rule on `posting_facts.employment_type` (unknown → passes to fit, D-2 style) |
| Keywords / interests | `title_allow.extra` + the fit prompt's interests (v2 D-18) |
| Experience ceiling (years) | v2's `experience_ceiling` + the guard's `yoe_min` cap (per user, not fixed at 3) |
| Target companies | `user_companies`; new URLs → shared discovery |
| Locations (default Singapore) | `location_explicit` allow tokens per user |
| Schedule | the per-user run scheduler (§8.5) |

### 8.7 Web app changes (building on M12)

- **Public pages:** landing, pricing, privacy policy, terms. Signed-out users see only these.
- **Auth:** "Continue with Google"; session cookie (HttpOnly, Secure, SameSite=Lax);
  sign-out; delete account; export my data.
- **Onboarding wizard** (five steps, resumable): resume → role types → keywords & YOE →
  companies → schedule. The first run starts at the end.
- **Tabs** (M12 shell kept): Inbox · Applications · Runs · Profile · **Companies**
  (search catalog, add by URL, remove, see crawl health) · **Billing** (plan, runs
  left this month, upgrade/downgrade via Stripe) · Settings.
- **Admin** (owner only): users, crawl health, failing companies, queue depth, LLM
  spend, manual quota grants.

---

## 9. Viability and the key design questions

### 9.1 Is it viable?

**Technically: yes.** Every stage exists in v2 and is measured. The new work is
multi-tenancy, auth, billing, a queue and hosting — well-trodden ground.

**Economically: yes, if costs stay shared.** At 200 users the whole service runs for
roughly **US$45–75/month** (§10.3). Break-even needs ~**10–15 paying users** on the
cheapest paid tier (§11). The binding constraint is not money but **operational
risk**: scraping at scale (sites blocking the server), LinkedIn (§9.7) and privacy
duties (§12.3).

### 9.2 Why sharing is the whole economic case

Users' company lists overlap heavily (the seeded catalog is 229 companies). Estimate
*(assumption — validate from real sign-ups)*: 200 users × 40 companies each, ~1,000–2,000
distinct companies. Crawl cost scales with **distinct companies**, and fact extraction
with **distinct new postings** — neither with users. Only the per-user fit step grows
with users, and it is the cheapest step (short prompts, batched).

### 9.3 LLM: per user or shared? → **Shared**

- A model per user buys nothing: the model is stateless; personalisation is the
  profile and interests in the prompt, and the user's data in the database.
- One shared endpoint, one client in the workers, per-user token metering and
  per-user batching. Prompts include only that user's profile and that batch's
  postings — never another user's data.

### 9.4 Which Qwen, where → **Alibaba Model Studio (Singapore endpoint)**

| Option | Price per 1M tokens (in / out) | Notes |
|---|---|---|
| Qwen Flash on Alibaba Model Studio, **Singapore** endpoint | ~US$0.10–0.15 / 0.40–0.47 *(verified 2026-09-25)* | In-region; cheapest proprietary Qwen; 1M free tokens per model for 90 days |
| Qwen3-14B (open weights — the model v2 validated) via DeepInfra / OpenRouter | ~US$0.10 / 0.22 *(verified)* | Same model family v2 measured; hosted outside Singapore |
| Self-hosted Qwen3-14B on a cloud GPU | ≥ ~US$360/month always-on (estimate: ~US$0.50/GPU-hour) | Only worth it far beyond 200 users |
| Ollama on the owner's PC (today) | electricity | Development only — not reachable or reliable for a public service |

**Decision (D-21):** Model Studio Singapore as primary; DeepInfra Qwen3-14B as the
fallback, both through an OpenAI-compatible backend added beside v2's `ollama` /
`cli` / `api` backends. **Gate before launch:** re-run v2's measurement set (the
17 disputed cases + the 30-role audit) on the chosen hosted model; it must match
Qwen3-14B's 17/17 and 0 non-Singapore accepts.

### 9.5 LLM cost estimate *(assumptions stated)*

| Step | Volume per month (200 users) | Tokens | Cost at ~US$0.14 / 0.42 |
|---|---|---|---|
| Global facts | ~20,000 new/changed postings that pass *some* user's cheap screen × ~700 in / ~60 out | ~14M in / 1.2M out | ~US$2.5 |
| Per-user fit | 200 users × 4 runs × ~100 postings × ~600 in / ~80 out | ~48M in / 6.4M out | ~US$9.4 |
| Resume parsing | ~250 parses × ~4,000 in / ~800 out | ~1M in / 0.2M out | ~US$0.2 |
| **Total** | | | **≈ US$12–15/month** |

Self-hosting breaks even only when monthly token spend exceeds a GPU's cost —
roughly **25× today's estimate**, i.e. thousands of active users. Revisit at 2,000 MAU.

### 9.6 Scraping at multi-user scale

- ~1,000–2,000 companies on a 2–7-day freshness cycle ≈ 150–1,000 company fetches a
  day: one crawler worker with v2's per-host rate limit handles it.
- Storage: v2 holds ~33k postings for 224 companies; at 2,000 companies expect
  ~300k postings and ~2 GB — small for Postgres.
- **Blocking risk:** one server IP polling many sites. Mitigations: v2's robots
  compliance and per-host delays, conditional requests, spreading crawls across the
  day, and a documented contact user agent. TBD — needs validation via the first
  month of crawl-failure metrics.

### 9.7 LinkedIn → **not scraped; compliant alternatives only**

Findings *(verified 2026-09-25)*:
- LinkedIn has **no API to search or read job postings**; its Job Posting API is for
  approved partners to *post* jobs, and it is not accepting new partners.
- LinkedIn's User Agreement prohibits scraping; LinkedIn sued Proxycurl in January
  2025, and the service shut down in July 2025 under a permanent injunction.

So the requirement "find LinkedIn postings from the companies' official accounts"
is met **without touching LinkedIn's servers**:
1. **Most of those postings already reach us.** A company's LinkedIn postings are
   usually syndicated from its own ATS (Greenhouse, Workday, Lever …), which the
   crawler already reads. **TBD — needs validation:** sample 50 LinkedIn postings
   from 10 target companies by hand and count how many appear in our catalog.
2. **Find the missing ATS feeds.** For companies whose LinkedIn postings are not in
   our catalog, find the ATS or careers feed behind them (manually or via discovery)
   and add it to the catalog.
3. **User-supplied links.** A user can paste a LinkedIn job URL into Applications to
   track it; we store the link and what the user typed — we do not fetch the page.
4. **Licensed data, only after legal review:** a data vendor whose licence covers
   this use. Gate: written legal basis before any contract. Not in the MVP.

### 9.8 Extensibility beyond 200 users and beyond Singapore

- Stateless API → add API containers behind Caddy or a load balancer.
- Workers are queue consumers → add worker VMs; no code change.
- Postgres → managed Postgres (same engine, same `store.py`) when backups/HA matter
  more than cost; read replica for the catalog if needed.
- Locations are per-user preferences, and posting facts carry `locations[]`, so a new
  market is data and prompt work, not a redesign.
- The LLM backend is pluggable; self-hosting becomes a config change when volume
  justifies it (§9.5).

---

## 10. Hosting — cheapest viable, in Singapore

### 10.1 Options compared *(prices verified 2026-09-25, USD/month)*

| Option | What | Monthly | Pros | Cons |
|---|---|---|---|---|
| **A. One VM, all-in** *(recommended)* | DigitalOcean SGP1 Basic 2 vCPU / 4 GB (US$24) — Caddy, API, 3 workers, Postgres in Docker Compose; DigitalOcean Spaces or Cloudflare R2 for resumes + nightly backups | **~US$30–35** | Cheapest reliable option; everything in Singapore; one box to reason about | You run Postgres: backups, upgrades, restore drills are yours |
| **B. VM + Supabase** | Supabase Pro (US$25: Postgres, Google Auth, 100 GB storage, AWS Singapore) + a US$12 2 GB droplet for API + workers | **~US$40–45** | Managed backups and auth; less ops | Two vendors; Supabase compute tiers cost more as the DB grows |
| C. VM + managed Postgres | Droplet (US$12–24) + DigitalOcean Managed Postgres (from ~US$15) | ~US$30–45 | Managed backups/HA path | Slightly more than A for the same capacity |
| D. Serverless (Cloud Run + Neon) | Scale-to-zero containers + serverless Postgres | ~US$0–30 | Near-zero at idle | Free tiers mostly in US regions; long crawls fit poorly; cold starts |
| E. Hetzner Singapore | CPX11 (2 GB) US$20.49 / CPX21 (4 GB) US$37.49 | ~US$25–45 | — | No longer cheapest in Singapore after the 2026 price rise; 0.5–1 TB traffic |

**Recommendation (D-25): Option A at launch**, with backups to object storage from
day one and a written restore drill. Move Postgres to a managed service (C or B)
when any of these holds: > 500 users, paying revenue > US$200/month, or a restore
drill takes longer than an hour.

### 10.2 Deployment shape

- Docker Compose (v2's M10 already packages the app); images built in GitHub Actions
  and pulled on the VM; zero-downtime deploys by restarting the API container
  behind Caddy.
- Domain + DNS on Cloudflare (free), Caddy for automatic TLS.
- Secrets in environment files readable only by the service user; nothing in git.
- Monitoring: an uptime check, error tracking (free tier), and a daily metrics email
  (runs, failures, LLM spend, crawl failures).

### 10.3 Total monthly cost at 200 users *(estimate)*

| Item | USD/month |
|---|---|
| VM (Option A) | 24 |
| Object storage + backups | 5 |
| Qwen (hosted) | 12–15 |
| Domain (amortised), monitoring free tiers | ~1–2 |
| Stripe fees | per payment (§11) |
| **Total infra + LLM** | **≈ US$45–50** (≈ US$0.25 per user) |

---

## 11. Tiers, quotas and unit economics

*(Prices are proposals — TBD, needs validation via a pricing test.)*

| Tier | Price | Runs / month | Companies | Freshness | Schedule |
|---|---|---|---|---|---|
| Free | S$0 | 4 | 20 | crawled ≤ 7 days | manual, weekly |
| Plus | S$5 / month | 16 | 60 | ≤ 3 days | + fortnightly, twice weekly |
| Pro | S$12 / month | 60 | 200 | ≤ 1 day | + daily |

- **Payments:** Stripe Checkout + Customer Portal + webhooks. Singapore fees
  *(verified)*: PayNow **1.3%**, cards **3.4% + S$0.50**. On a S$5 card payment the
  fee is ~13% — so **offer PayNow and annual plans** (e.g. S$50/year for Plus).
- **Break-even:** ~US$50/month ≈ S$65 → ~13 Plus subscribers, or ~6 Pro.
- **Cost per run** (estimate): ~US$0.01–0.02 in LLM + a share of crawling. Runs are
  cheap, so quotas mainly bound worst-case abuse and set the upgrade path.
- **Quota rules:** one run is charged when it starts; refunded if it fails for a system
  reason; unused runs do not roll over; admins can grant runs.

---

## 12. Security, privacy and abuse

### 12.1 Authentication and sessions

Google OIDC (authorization-code flow, `openid email profile` scopes only), validated
ID token, server-side session in Postgres, cookie HttpOnly + Secure + SameSite=Lax,
CSRF protection on state-changing requests (v2's cross-site write guard, generalised
from loopback to the public origin), session rotation on sign-in, sign-out
everywhere.

### 12.2 Hardening that a public service needs and v2 did not

- **Tenant isolation:** user-scoped `store.py` methods (§8.3) + Postgres row-level
  security + tests that one user can never read another's rows.
- **SSRF:** users can add careers URLs, which the server then fetches. The crawler
  must refuse private, loopback, link-local and cloud-metadata addresses, re-check
  after redirects, and cap response size and time.
- **Rate limits:** per user and per IP on the API (Caddy + application limits);
  queue fairness (§8.4).
- **Uploads:** v2's rules (size cap, magic-byte check, raw body) plus malware
  scanning of resumes (TBD — needs a tool choice), and storage outside the web root.
- **Secrets & keys:** the Qwen and Stripe keys only in the workers/API that need them.
- **Stripe webhooks:** signature verification; idempotent handling.

### 12.3 Singapore PDPA *(summary — confirm with PDPC guidance or counsel before launch)*

- **Consent and purpose:** a clear notice at sign-up that the resume is processed to
  find matching jobs, including by a third-party AI model (the Qwen provider, named).
- **Protection:** resumes encrypted at rest; access limited to the user and the
  processing workers; audit log of admin access.
- **Retention:** keep the derived profile; offer to delete the raw resume after
  parsing; delete everything within the stated period after account deletion.
- **Access and correction:** export my data; edit my profile.
- **Breach notification:** a written incident plan — notifiable breaches go to the
  PDPC, and affected users where required, within the statutory time limits.
- **Data Protection Officer:** designate one (the owner at launch) and publish a contact.
- **Transfer:** keep data in Singapore where possible (VM, storage and the Qwen
  endpoint all offer Singapore regions).

---

## 13. Delivery milestones

Business outcomes, not engineering tasks — `/plan` turns each into a plan.

| # | Milestone | Outcome | Status | Plan |
|---|---|---|---|---|
| P0 | Validate demand | Landing page + waitlist + 10 user interviews; LinkedIn coverage sample (§9.7); hosted-Qwen quality gate (§9.4) | pending | — |
| P1 | Multi-tenant core | Postgres, shared catalog vs per-user tables, user-scoped store, isolation tests; v2 behaviour unchanged for one user | pending | — |
| P2 | Accounts and onboarding | Google sign-in, onboarding wizard, per-user profile, preferences and companies | pending | — |
| P3 | Queue and workers | crawler / facts / user-run workers; runs on demand; two-step judging (D-22) | pending | — |
| P4 | Hosted in Singapore | Option A live on a domain with TLS, backups, monitoring, restore drill passed | pending | — |
| P5 | Schedules and quotas | Per-user schedules, run quota enforcement and refunds | pending | — |
| P6 | Billing | Stripe tiers with PayNow, customer portal, webhooks | pending | — |
| P7 | Public launch | Privacy policy, terms, PDPA checklist done; first 50 users from the waitlist | pending | — |
| P8 | LinkedIn gap closure | Missing ATS feeds added per the §9.7 sample; paste-a-link tracking | pending | — |
| P9 | Scale-out readiness | Managed Postgres, second worker VM, alerting — when §10.1's triggers fire | pending | — |

---

## 14. Open questions

- [ ] **Price points and tiers** — S$5/S$12 are guesses. *Pricing test on the landing page.*
- [ ] **Hosted Qwen quality** — does Qwen Flash on Model Studio match Qwen3-14B on v2's
  measurement set? If not, Qwen3-14B via DeepInfra (outside Singapore) or a larger Flash.
- [ ] **LinkedIn coverage gap** — how many target-company LinkedIn postings are missing
  from the ATS catalog? *Hand sample (§9.7).*
- [ ] **Shared-catalog abuse** — who can add a company to the shared catalog, and how are
  junk or hostile URLs kept out? (Proposal: added companies are private to the user
  until resolved, then shared.)
- [ ] **Freshness vs cost** — are 7/3/1-day freshness windows right per tier?
- [ ] **Resume retention** — delete the raw file after parsing by default?
- [ ] **Operator** — personal or company entity for Stripe and PDPA purposes?
- [ ] **Support load** — what is promised (email, response time) at launch?

## 15. Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-M1 | Careers sites block the server's IP as crawl volume grows | Medium | High | robots + per-host delays (v2), spread crawls, conditional requests, crawl-failure alerts; later a second egress IP |
| R-M2 | LinkedIn requirement tempts scraping → legal exposure | Medium | High | D-24; the compliant route in §9.7; written legal basis before any data vendor |
| R-M3 | Cross-tenant data leak | Low | Very high | user-scoped store API, row-level security, isolation tests in CI, audit log |
| R-M4 | PDPA breach or complaint | Low | High | §12.3 checklist before launch; encryption; incident plan; DPO |
| R-M5 | Hosted Qwen quality lower than local Qwen3-14B | Medium | Medium | pre-launch quality gate (§9.4); fallback provider; code-decides guard (D-17) |
| R-M6 | Single-VM outage or data loss | Medium | High | nightly off-VM backups, tested restore, managed Postgres trigger (§10.1) |
| R-M7 | Card fees eat small payments | High | Low | PayNow and annual plans (§11) |
| R-M8 | SSRF via user-supplied careers URLs | Medium | High | §12.2 URL/IP validation, redirect re-checks, size/time caps |
| R-M9 | Qwen provider price or availability changes | Low | Medium | pluggable OpenAI-compatible backend; second provider configured |
| R-M10 | Demand is lower than assumed | Medium | High | P0 validates before P1–P7 are built |

---

## 16. Sources (checked 2026-09-25)

- Qwen pricing, Model Studio Singapore endpoint: [Alibaba Cloud Model Studio pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing), [BenchLM Qwen API pricing](https://benchlm.ai/alibaba/api-pricing), [eesel AI Qwen pricing](https://www.eesel.ai/blog/qwen-pricing)
- Qwen3-14B / 30B-A3B hosted prices: [OpenRouter Qwen3 14B](https://openrouter.ai/qwen/qwen3-14b), [OpenRouter Qwen3 30B A3B](https://openrouter.ai/qwen/qwen3-30b-a3b), [DeepInfra Qwen pricing guide](https://deepinfra.com/blog/qwen-api-pricing-2026-guide)
- LinkedIn: [Job Posting API overview (Microsoft Learn)](https://learn.microsoft.com/en-us/linkedin/talent/job-postings/api/overview?view=li-lts-2026-03), [LinkedIn API access in 2026 (Phyllo)](https://www.getphyllo.com/post/linkedin-api-access-in-2026-partner-program-approval-timeline-alternatives), [Proxycurl shutdown](https://nubela.co/blog/goodbye-proxycurl/), [LinkedIn wins case against Proxycurl](https://www.socialmediatoday.com/news/linkedin-wins-legal-case-data-scrapers-proxycurl/756101/)
- Hosting: [DigitalOcean droplet pricing](https://www.digitalocean.com/pricing/droplets), [DigitalOcean managed Postgres pricing](https://docs.digitalocean.com/products/databases/postgresql/details/pricing/), [Hetzner 2026 price adjustment](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/), [Hetzner CPX11](https://sparecores.com/server/hcloud/cpx11), [Supabase pricing](https://supabase.com/pricing), [Cloud Run pricing](https://cloud.google.com/run/pricing), [Neon pricing](https://neon.com/pricing)
- Payments: [Stripe Singapore pricing](https://stripe.com/en-sg/pricing), [Stripe local payment methods](https://stripe.com/en-sg/pricing/local-payment-methods)

---
*Status: DRAFT — requirements and target design. Next step: P0 (validate demand), then
`/plan .claude/prds/mullti_user_prd.md` for P1.*
