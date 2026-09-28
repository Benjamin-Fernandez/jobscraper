# mullti_user_prd — JobScraper as a public, multi-user cloud service

**Status:** DRAFT r3 — requirements + target design. r2 (2026-09-25) took in an ECC
architect review; r3 (2026-09-28) closes logic gaps found in a second review (listed in
§17) and adds free / student hosting (§10.4). Nothing here is built yet.
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
| Onboarding → first shortlist | first results ≤ 10 min when every chosen company is already in the catalog (new companies need a crawl first; the UI shows progress), ≥ 70% of sign-ups | events `signed_up` → `first_results_shown` |
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
9. **An email digest after a scheduled run that found new roles** (D-30). Without it a
   scheduled product is silent: runs finish while the user is away, and the retention
   metric depends on them remembering to look.

### Out of scope (MVP)

| Item | Why deferred |
|---|---|
| **Scraping LinkedIn** | Prohibited by LinkedIn's User Agreement; §9.7 gives the compliant route. |
| Auto-apply / filling application forms | Different product; abuse and ToS risk. |
| Non-Singapore locations | Launch market; the data model keeps locations per user (§9.8). |
| Instant / Telegram / push alerts | The per-run email digest (MVP item 9) is enough to test the hypothesis. |
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
| **D-25** | **One small Singapore VM** running Docker Compose with Postgres, one worker process, Caddy; backups encrypted off-VM. **Phased:** build and non-commercial beta on a **free tier** (Oracle Cloud Always Free in Singapore, or Azure for Students — §10.4); before charging anyone (P7), be on a host whose terms allow commercial use (Oracle if its terms allow, else a DigitalOcean 2 GB droplet). Scale out on *measured* triggers. | Cheapest viable at ≤ 200 users (§10); student credits forbid commercial use and the DigitalOcean student credit ended 2026-08-01, so the free phase must end at billing; every piece is separable later. |
| **D-26** | **Quota is an append-only ledger**, charged atomically at run start, refunded by rule; one active run per user. | Auditable, race-free, and maps runs to cost (§8.5). |
| **D-27** | **Postgres replaces SQLite; `store.py` stays the only SQL module**; row-level security is enforced, not decorative. | v2 §8.4 designed for this swap; multi-user needs concurrency and isolation. |
| **D-28** | **Cache keys are content hashes of everything that shapes an answer.** | v2 caches decisions by `profile_version` only — editing `judge.interests` today serves stale verdicts. Multi-user must not inherit that (§8.3). |
| **D-29** | **Shared facts are protected against poisoning:** facts batches hold one company's postings only; facts from user-added companies stay private to that user until the company is reviewed. | One hostile posting or attacker page must not write `is_singapore: true` into facts every user sees (§12.2). |
| **D-30** | **Email digest in the MVP:** after a scheduled run with ≥ 1 new shortlisted role, one email (count + top titles + link to the Inbox; no job-description text). One-click unsubscribe. | A scheduled run nobody hears about tests nothing (§6 item 9). |
| **D-31** | **A board is identified by its normalised endpoint — (provider, tenant, site) — not (provider, slug).** Several catalog companies may share one board with an `entity_filter` (department / legal entity). | Seen in v2 on 2026-09-27: Rakuten Asia and Rakuten Viki are two sites on one Workday tenant (`rakuten`), and "Grab Financial Group" resolves to Grab's own SmartRecruiters board. `UNIQUE(provider, board_slug)` would merge the first pair and duplicate-scrape the second. |
| **D-32** | **A run that finds nothing to do is not charged.** If no watched company is past its window and no posting changed, the run ends as `nothing_new` with a refund, and "Run now" shows when fresh data can next exist. | Otherwise a user pays a run for re-reading an unchanged catalog — the quota would bill for nothing. |
| **D-33** | **Large boards are fetched with a location facet, not truncated.** Workday, SmartRecruiters and others are queried for the locations some user allows; the 600-posting cap applies after the facet. | v2 caps every board at 600 postings (`MAX_JOBS`); on 2026-09-27 Visa, AIA, Manulife, PwC, Kyndryl, DXC, HPE and Deutsche Bank all hit it, so Singapore roles past the cap are silently missed. |
| **D-34** | **Platform spend guard:** a daily token budget across all users; at 80% alert the owner, at 100% pause new judging (runs park as `awaiting_llm`, resume free next day). | Per-user quotas bound one user; nothing bounded the sum — a bug, a mass re-judge or abuse could burn a month's LLM budget in a day. |

---

## 8. Target design — what changes from v2

### 8.1 What stays, what changes

| v2 piece | Multi-user fate |
|---|---|
| ATS adapters, discovery, `net.py` (rate limits, robots) | **Kept**, fed by the shared catalog. **Plus** SSRF protection for user-added URLs (§12.2) and a generic schema.org `JobPosting` (JSON-LD) adapter for careers pages on no known ATS. |
| `RawJob.employment_type` (filled by Lever, Ashby, SmartRecruiters, Workable, Recruitee) — *dropped by v2's schema today* | **Persisted** as `postings.employment_type_raw`; the model is asked only when it is empty (Greenhouse, Workday, generic). |
| Staleness scheduler (per company, 7 days since 2026-09-27, stamped on attempt) | **Kept for the shared crawl**; the deadline becomes the *shortest tier window among the company's watchers*, measured from `last_success_at` (not the attempt stamp). A separate **per-user run scheduler** is new (§8.5). |
| Adapters' 600-posting cap (`MAX_JOBS`) | **Location-faceted fetch** for large boards (D-33); the cap stays as a safety limit after the facet. |
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
  `added_by` (null for curated), `crawl_deadline` (derived, §8.1), `board_id`,
  `entity_filter` (nullable: department / legal-entity match within a shared board).
  **Identity (D-31):** a separate `boards` table keyed `UNIQUE (provider, tenant, site)`
  — the normalised feed endpoint — and a normalised careers URL for the rest; *not*
  `slug(name)` (two users adding "Grab" would duplicate it) and *not* `(provider, slug)`
  (Rakuten Asia and Rakuten Viki share tenant `rakuten`). A board is crawled once however
  many companies point at it.
- `postings` — v2's `jobs` plus `employment_type_raw`, `jd_fetched_at`, `vital_hash`,
  `closed_at`. **Retention:** closed postings are kept 90 days (so an Inbox or an
  application can still show them), then purged unless an application references them.
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
- `user_posting_state` — PK `(user_id, posting_id)`: `new | seen | dismissed | applied`,
  `dismissed_reason` (optional). Without it the Inbox only grows: nothing records "I've
  looked at this" or "not for me", and a dismissed role would reappear after a re-judge.
- `applications` — PK `(user_id, application_id)`; `posting_id` **nullable** so a
  pasted LinkedIn link can be tracked; a **snapshot** (title, company, location, URL,
  captured at apply time) so the record survives the posting closing or being purged;
  `app_events` carries `user_id`.
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
deleting an account removes the live data at once; backups expire it (§12.3). Shared rows
the user touched: companies they added that are still `pending_review` with no other
watcher are deleted, reviewed ones keep the company and null `added_by`; facts with
`visibility = private:<user>` are deleted.

### 8.4 Work model: one worker, three queues

A Postgres table-backed queue (`FOR UPDATE SKIP LOCKED`) — no Redis at this size.

| Queue | Unit of work | Enqueued when |
|---|---|---|
| **crawl** | one **board** (D-31): resolve ATS (shared), fetch listings (location-faceted, D-33), diff, persist; then fetch descriptions for new postings that pass a **global location-only screen** — the *union of every user's allowed locations*, not a hard-coded Singapore, or a user who allows "Remote" would get postings with no description | the board's crawl deadline passes, or a run finds it stale |
| **facts** | one company's new/changed postings → the facts prompt (one company per batch, D-29) | a run reaches step 3 and survivors lack facts (on demand, not "whatever any user might want") |
| **run** | one step of one user run (§8.5) | schedule tick, "Run now", or a run's crawls/facts finishing |

Fairness: the run queue round-robins across users; all model calls go through one
rate-limited client with per-user token metering and the platform spend guard (D-34);
scheduled runs are **staggered** (a user choosing "Monday 09:00" is placed at a random
offset within the hour) so a popular slot does not hit the provider's rate limit at once.

**Crawl budget:** the crawl queue has a daily ceiling (e.g. 3,000 board fetches). Tier
freshness windows are targets, not promises: past the ceiling the stalest boards go
first and the Companies tab shows each board's real age. A few Pro users each watching
200 niche companies at a 1-day window must not be able to starve everyone else.

### 8.5 What "a run" means now

v2's run = scrape 10 companies. Multi-user, crawling is shared, so a user's run =
*"bring my shortlist up to date"*. It is a **state machine**, re-queued between steps,
so a waiting run never holds a worker:

```
queued → awaiting_crawl → filtering → judging → done | partial | failed | nothing_new
                                         ↘ awaiting_llm (spend guard / provider down) ↗
```

1. **queued → awaiting_crawl:** freeze the company list (`run_companies`); enqueue crawls
   for companies past the user's tier window (measured from `last_success_at`); park the
   run until they finish or a timeout.
2. **filtering:** the user's prefilter over open postings of those companies, skipping
   any with a `user_prefilter` row for the current `rules_hash`.
3. **judging:** ensure facts for survivors (enqueue facts jobs, park, resume); then the fit
   prompt, batched per user, skipping any with a `user_fit` row for the current keys;
   code decides (D-17).
4. **done / partial / failed / nothing_new**; the UI is notified, and a scheduled run with
   new shortlisted roles sends the digest (D-30).

**Results appear as they are ready.** A first run can be large (40 companies, ~300
survivors, facts for most of them), so judging works in batches and each finished batch
is visible in the Inbox at once; the run's progress shows "12 of 40 companies, 80 of 300
roles judged". The onboarding metric (§5) counts *first results shown*, not run end.

**Quota (D-26):**
- **Charge** at `queued`, inside a transaction that locks the user's subscription row;
  refuse if the balance is zero. At most **one active run per user** (partial unique
  index on `runs(user_id) WHERE state not in (done, partial, failed)`).
- **Refund rules:** `failed` for a system reason → refund. Model provider down or the
  spend guard tripped → `awaiting_llm`, resumes free. Some companies blocked or failing →
  `partial`, **no refund** (the rest of the run was delivered). Nothing to do →
  `nothing_new`, refunded (D-32).
- **Quota period:** Free resets on the 1st of the month (SGT); paid tiers reset on the
  subscription's billing date. No rollover.
- **Plan changes:** an upgrade applies at once and grants the difference in runs for the
  rest of the period (a `grant` ledger entry); a downgrade applies at the period end. A
  failed payment keeps the paid tier through Stripe's retry window, then drops to Free at
  the period end — watched companies beyond the Free limit are paused, not deleted.
- **A scheduled run with no quota left** is not started: it is recorded as
  `skipped_no_quota` (still unique on `(user_id, scheduled_for)`) and the user gets one
  email per period, not one per skipped run.
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
| Role types (intern / FT / contract, multi-select) | generated rules: seniority/intern words in `title_deny` depend on the selection; a rule on employment type (unknown passes to fit, as D-2). **Precedence:** an internship signal in the title or the facts beats the ATS field — ATSs routinely label a 6-month internship "Full-time" (the *schedule*), so `employment_type_raw = Full-time` + title "Intern" = internship. Graduate programmes count as full-time; part-time and temporary map to contract. |
| Keywords / interests | `title_allow.extra` + the fit prompt's interests (v2 D-18) |
| Experience ceiling | `experience_ceiling` rule + the guard's `yoe_min` cap, per user |
| Target companies | `user_companies`; new URLs → shared discovery (SSRF-checked, pending review) |
| Locations (default Singapore) | `location_explicit` allow tokens, per user; and the **guard** — v2's "Singapore confirmed" becomes "`posting_facts.locations` ∩ the user's allowed locations is non-empty", so the facts prompt must return locations, not only `is_singapore` |
| Schedule | the per-user run scheduler (§8.5) |

### 8.7 Web app changes (building on M12)

- **Public pages:** landing, pricing, privacy policy, terms. Signed out users see only these.
- **Auth:** "Continue with Google"; sign-out; delete account; export my data; withdraw consent.
- **Onboarding wizard** (five steps, resumable): resume → role types → keywords & YOE →
  companies → schedule; the first run starts at the end.
- **Tabs** (M12 shell kept): Inbox · Applications · Runs · Profile · **Companies** (search
  the catalog, add by URL, crawl health) · **Billing** (plan, runs left, upgrade via
  Stripe) · Settings. Inbox shows a short extract and the employer's link, not the full
  description; each card can be **dismissed** ("not for me", optional reason) and new cards
  are marked until seen (`user_posting_state`).
- **"Why wasn't this shown?"** A user can paste a posting URL, or open a *Filtered out*
  list, and see which rule or check rejected it (v2's `filter explain`, per user), with a
  one-click "add this title to my keywords". A public user cannot read YAML; without this
  a too-strict rule is invisible and trust erodes.
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
  crawl of the full catalog from a free Singapore VM** (Oracle Always Free or Azure for
  Students, §10.4 — the same IP range the beta will use) and compares coverage with v2's.
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

**Recommendation (D-25), phased:**
1. **Build, P0 test and non-commercial beta (P0–P6): free** — Oracle Cloud Always Free in
   Singapore (§10.4), which fits the whole Option-A stack at US$0.
2. **From billing (P7): Option A on a host whose terms allow commercial use** — stay on
   Oracle if its agreement permits it, else a DigitalOcean 2 GB SGP droplet (US$12–18).
   The move is a Compose deployment plus a Postgres restore — rehearsed by the restore
   drill anyway.

If backups must stay in Singapore rather than R2's nearest region, use DigitalOcean
Spaces SGP (US$5) or Oracle Object Storage (20 GB free) instead.

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

During the free phase (§10.4) the VM and backups cost US$0, so the beta costs roughly the
LLM bill alone — ≈ US$5–15/month for 20–50 beta users, less while Model Studio's free
token allowance lasts.

### 10.4 Free and student hosting *(checked 2026-09-28)*

The owner is a student, so the student offers were checked. **None of them can host the
paid service**: every student credit is for learning and non-commercial use, and the
biggest one (DigitalOcean) is gone. What they *can* do is make P0–P6 free.

| Offer | What you get | Singapore? | Commercial use? | Verdict |
|---|---|---|---|---|
| **Azure for Students** | US$100 credit for 12 months, no card; 12 months of 750 h/month each of B1s, B2pts v2 and B2ats v2 VMs (**1 GB RAM each**); 750 h/month of PostgreSQL Flexible Server B1ms (2 GB RAM, 32 GB storage + 32 GB backup); always-free Container Apps, Functions, App Service F1 (1 h CPU/day) | Southeast Asia region exists; free-size VM availability there is not guaranteed — confirm in the portal | **No** — the offer terms limit credits to "education, non-commercial research" and development; the subscription is disabled when the credit runs out. Renewal: the offer terms say one subscription per student, the marketing page says it renews yearly — treat renewal as unconfirmed | **Usable for the free beta, not for launch.** Split: API + worker + Caddy on a 1 GB B2ats v2, Postgres on the free B1ms Flexible Server. 1 GB is tight — the worker must run one queue at a time. |
| **Oracle Cloud Always Free** (not a student offer; free for anyone) | Ampere A1 **2 OCPU + 12 GB RAM** (halved from 4/24 without notice on 2026-06-15), 2 AMD micro VMs, 200 GB block storage, 20 GB object storage, **10 TB/month egress**, all in the home region | **Yes** — `ap-singapore-1` can be the home region | Not confirmed — check the Oracle Cloud Services Agreement before P7 | **Best free fit**: the whole Option-A stack on one 12 GB VM at US$0. Upgrade the account to Pay-As-You-Go (card needed, still US$0 within the limits): PAYG accounts are exempt from idle-instance reclamation (A1 VMs under 20% CPU, network and memory for 7 days — which describes this workload). Risk: Oracle changes the free limits without notice (R-M16). |
| **GitHub Student Developer Pack — DigitalOcean** | *Was* US$200 for 1 year | — | — | **Ended**: DigitalOcean left the pack; every credit expired 2026-08-01. |
| **GitHub Student Developer Pack — Heroku** | US$13/month credit for 24 months | **No** — Common Runtime is US/EU only | Student credit | Not suitable: overseas hosting of resumes adds a PDPA s.26 transfer and ~200 ms latency. |
| **GitHub Student Developer Pack — others** | Azure (same offer as above), MongoDB Atlas US$50, Datadog Pro 2 years, Sentry, New Relic, a free `.tech` / `.me` domain | — | — | Useful around the edges: **a free domain for the beta** and free monitoring/error tracking. |
| AWS Free plan (any new account) | US$100–200 credits, expires after **6 months** | Yes (`ap-southeast-1`) | Yes | Too short-lived to matter. |
| Google Cloud | US$300 for 90 days; always-free e2-micro is **US regions only** | Credits yes, free VM no | Yes | Too short-lived; the free VM is in the wrong country. |

**Decision:** Oracle Always Free (PAYG-upgraded) in Singapore for P0–P6, with Azure for
Students as the fallback if Oracle has no A1 capacity or rejects the sign-up; move to a
commercial-use host before P7 (D-25). Model Studio's free token allowance (1M tokens per
model for 90 days) covers the P3 quality gate.

---

## 11. Tiers, quotas and unit economics

*(Prices are proposals — TBD, needs validation via a pricing test.)*

| Tier | Price | Runs / month | Companies | Crawl freshness | Schedules |
|---|---|---|---|---|---|
| Free | S$0 | 5 | 20 | ≤ 7 days | manual, weekly |
| Plus | S$5 / month | 16 | 60 | ≤ 3 days | + fortnightly, twice weekly |
| Pro | S$12 / month | 60 | 200 | ≤ 1 day | + daily |

- **Free is 5 runs, not 4:** a weekly schedule fires 5 times in a 5-week month, so 4 runs
  would make every such month's last scheduled run fail for want of quota.
- **Payments:** Stripe Checkout + Customer Portal + webhooks (signature-verified,
  idempotent via `stripe_events`). Singapore fees *(verified)*: PayNow **1.3%**, cards
  **3.4% + S$0.50** — ~13% of a S$5 card payment. **PayNow cannot auto-renew**: it is a
  one-off, customer-initiated payment, usable for a subscription only as a manually paid
  invoice. So: **monthly plans auto-renew on cards; PayNow is for annual plans and prepaid
  run packs** (e.g. Plus S$50/year, paid by invoice), which also keeps the fee share low.
- **Break-even:** ~US$40/month ≈ S$52 → ~10 Plus subscribers, or ~5 Pro.
- **Cost per run** (estimate): ~US$0.01–0.02 in LLM plus a share of crawling; quotas mainly
  bound abuse and set the upgrade path.
- **Ledger rules** (§8.5): charged at start, refunded by rule, no rollover, admin grants
  are ledger entries too.

---

## 12. Security, privacy and abuse

### 12.1 Authentication and sessions

Google OIDC authorization-code flow with PKCE, scopes `openid email profile` only;
validate the ID token; key the account on `sub` and require `email_verified`. Publish the
OAuth consent screen to *In production* before the beta opens beyond a handful of people
(in *Testing* only listed test users, at most 100, can sign in); `openid email profile`
are non-sensitive scopes and need no Google security review, though showing a logo
needs brand verification.
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
- **Rate limits:** per user and per IP (Caddy + application); queue fairness (§8.4);
  company additions capped per user per day (each one triggers discovery crawls).
- **Free-tier multi-accounting:** Google accounts are free, so one person can hold many
  Free accounts. Each costs little (fit on ~20 companies), so the defence is proportionate:
  the platform spend guard (D-34), per-IP sign-up limits, and review if one IP holds more
  than a few accounts — not identity checks.
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

### 12.4 Scraping careers sites as a service *(new in r3)*

v2 is one person reading public careers pages for their own job search. A service that
crawls hundreds of employers' boards and serves the results to paying users is a
different legal and ethical position, and the PRD addressed only LinkedIn's. Before P7:
- **Terms review:** public ATS job-board APIs (Greenhouse, Lever, Ashby) are published for
  embedding and are the safest; Workday's `/wday/cxs/` JSON is an *internal, undocumented*
  endpoint of each employer's site — check the employers' and Workday's terms, and prefer
  the published `JobPosting` markup where it exists.
- **Keep honouring robots.txt**, identify the crawler in its User-Agent with a contact URL,
  and keep v2's per-host rate limits.
- **Employer opt-out:** a published contact and a `companies.status = opted_out` that stops
  crawling within 48 hours.
- **Link, don't host:** the extract-and-link rule above.

---

## 13. Delivery milestones

Business outcomes, not engineering tasks — `/plan` turns each into a plan.

| # | Milestone | Outcome | Status | Plan |
|---|---|---|---|---|
| P0 | Validate the premises | Landing page + waitlist + 10 interviews; free Oracle (or Azure for Students) Singapore VM set up; **48-hour datacenter-IP crawl test** from it (§9.6); LinkedIn coverage sample (§9.7); pricing test; **location-faceted fetch for large boards** (D-33 — also a v2 fix) | pending | — |
| P1 | Multi-tenant core | Postgres; `boards` separate from companies (D-31); shared vs per-user tables with content-hash keys (D-28); `user_posting_state`; user-scoped `store.py` + forced RLS; **deletion cascade and export built in**; the owner's v2 data migrated as user #1 | pending | — |
| P2 | Accounts and onboarding | Google sign-in, consents, onboarding wizard, per-user profile, preferences, companies | pending | — |
| P3 | Queue, workers, two-step judging | crawl/facts/run queues; run state machine; facts + fit prompts (D-22); **the quality gate on the split pipeline** (§9.4); one-time facts backfill for the catalog | pending | — |
| P4 | Private beta in Singapore | Option A live **on the free tier** (§10.4) behind an allowlist; OAuth consent screen published; TLS, WAL archiving, restore drill; **SSRF, RLS and isolation tests passing**; spend guard (D-34); monitoring | pending | — |
| P5 | Schedules, quotas, digest | per-user schedules (staggered), quota ledger, refund / period / plan-change rules (§8.5), email digest (D-30) | pending | — |
| P6 | Retention beta | 20–50 waitlist users for 4+ weeks; measure §5's retention before charging | pending | — |
| P7 | Billing | **move to a commercial-use host first** (D-25); scraping terms review (§12.4); Stripe: cards for monthly, PayNow invoices for annual / run packs, customer portal, idempotent webhooks | pending | — |
| P8 | Public launch | privacy policy, terms, PDPA checklist (§12.3), employer opt-out (§12.4), minimum age; open sign-ups | pending | — |
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
- [ ] **Oracle Always Free for a paid service** — does the Oracle Cloud Services Agreement
      allow commercial use of Always Free resources? Decides whether P7 needs a move (§10.4).
- [ ] **Azure for Students fallback** — are the free VM sizes available in Southeast Asia,
      and does the offer renew each year (the offer terms and the marketing page disagree)?
- [ ] **Workday and other internal job endpoints** — do the terms allow a commercial
      service to use them, or must those employers be read from `JobPosting` markup (§12.4)?

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
| R-M16 | A free or student offer changes or ends mid-beta (Oracle halved Always Free without notice on 2026-06-15; DigitalOcean ended its student credit, retroactively, on 2026-08-01) | Medium | Medium | Compose + restore drill keep the move to a paid host to hours; backups off the free host; never depend on a free tier past P6 |
| R-M17 | Employers or ATS vendors object to commercial crawling | Medium | High | §12.4: terms review before P7, robots, identified crawler, opt-out within 48 h, extract-and-link only |
| R-M18 | Large boards silently truncated (v2's 600-posting cap) | **High** (observed) | Medium | D-33 location-faceted fetch; alert when a board returns exactly the cap |
| R-M19 | Free-tier abuse through many Google accounts | Low | Low | spend guard (D-34), per-IP sign-up limits (§12.2) |

---

## 16. Sources (checked 2026-09-25)

- Qwen pricing, Model Studio Singapore endpoint: [Alibaba Cloud Model Studio pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing), [BenchLM Qwen API pricing](https://benchlm.ai/alibaba/api-pricing), [eesel AI Qwen pricing](https://www.eesel.ai/blog/qwen-pricing)
- Qwen3-14B / 30B-A3B hosted prices: [OpenRouter Qwen3 14B](https://openrouter.ai/qwen/qwen3-14b), [OpenRouter Qwen3 30B A3B](https://openrouter.ai/qwen/qwen3-30b-a3b), [DeepInfra Qwen pricing guide](https://deepinfra.com/blog/qwen-api-pricing-2026-guide)
- LinkedIn: [Job Posting API overview (Microsoft Learn)](https://learn.microsoft.com/en-us/linkedin/talent/job-postings/api/overview?view=li-lts-2026-03), [LinkedIn API access in 2026 (Phyllo)](https://www.getphyllo.com/post/linkedin-api-access-in-2026-partner-program-approval-timeline-alternatives), [Proxycurl shutdown](https://nubela.co/blog/goodbye-proxycurl/), [LinkedIn wins case against Proxycurl](https://www.socialmediatoday.com/news/linkedin-wins-legal-case-data-scrapers-proxycurl/756101/)
- Hosting: [DigitalOcean droplet pricing](https://www.digitalocean.com/pricing/droplets), [DigitalOcean managed Postgres pricing](https://docs.digitalocean.com/products/databases/postgresql/details/pricing/), [Hetzner 2026 price adjustment](https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/), [Hetzner CPX11](https://sparecores.com/server/hcloud/cpx11), [Supabase pricing](https://supabase.com/pricing), [Cloud Run pricing](https://cloud.google.com/run/pricing), [Neon pricing](https://neon.com/pricing)
- Payments: [Stripe Singapore pricing](https://stripe.com/en-sg/pricing), [Stripe local payment methods](https://stripe.com/en-sg/pricing/local-payment-methods), [Stripe PayNow](https://stripe.com/payment-method/paynow), [PayNow is one-off only (MemberPress / Stripe)](https://memberpress.com/docs/enable-paynow-with-stripe-and-memberpress/) *(checked 2026-09-28)*
- Free / student hosting *(checked 2026-09-28)*: [Azure for Students](https://azure.microsoft.com/en-us/free/students), [Azure for Students offer terms](https://azure.microsoft.com/en-us/pricing/offers/ms-azr-0170p), [Azure free services](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/create-free-services), [GitHub Student Developer Pack](https://education.github.com/pack), [Heroku for GitHub students](https://www.heroku.com/github-students/), [DigitalOcean student credit ended](https://aistudentdiscount.com/digitalocean-github-student-developer-pack-credits/), [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm), [Oracle halves A1 free limits (InfoQ)](https://www.infoq.com/news/2026/07/oracle-cloud-free-tier-limits/), [Oracle PAYG avoids idle reclamation](https://blog.51sec.org/2023/02/oracle-cloud-cleaning-up-idle-compute.html), [AWS Free plan](https://aws.amazon.com/about-aws/whats-new/2025/07/aws-free-tier-credits-month-free-plan/), [Google Cloud free features](https://docs.cloud.google.com/free/docs/free-cloud-features)

## 17. r3 review — logic gaps closed

| # | Gap in r2 | Fix |
|---|---|---|
| 1 | Board identity `(provider, slug)` merges Rakuten Asia / Rakuten Viki (one Workday tenant) and double-crawls Grab / Grab Financial (one board) | D-31, `boards` table, `entity_filter` |
| 2 | Large boards truncated at 600 postings — observed on 8 companies | D-33, R-M18 |
| 3 | A run with nothing new was still charged | D-32, `nothing_new` state |
| 4 | Free = 4 runs but a weekly schedule fires 5 times in some months | Free = 5 (§11) |
| 5 | Quota period, upgrades, downgrades, failed payments and quota-exhausted schedules undefined | §8.5 quota rules |
| 6 | Scheduled runs finish silently (alerts were out of scope) | D-30 email digest in MVP |
| 7 | No way to mark a role seen or not-for-me; Inbox only grows | `user_posting_state`, dismiss (§8.3, §8.7) |
| 8 | Applications broke when a posting closed or was purged; no posting retention | application snapshot, 90-day closed-posting retention |
| 9 | Users could not see why a role was filtered out | "Why wasn't this shown?" (§8.7) |
| 10 | Global description screen hard-coded to Singapore; guard used `is_singapore` only | union of allowed locations; guard on `locations ∩ allowed` (§8.4, §8.6) |
| 11 | ATS "Full-time" on internships would misfile interns | employment-type precedence (§8.6) |
| 12 | Nothing bounded total LLM spend | D-34 spend guard, `awaiting_llm` |
| 13 | Nothing bounded total crawling (Pro × 200 companies × daily) | crawl budget (§8.4) |
| 14 | "First shortlist ≤ 10 min" unreachable for companies not yet crawled | progressive results; metric redefined (§5, §8.5) |
| 15 | PayNow assumed to work for monthly subscriptions — it cannot auto-renew | cards monthly; PayNow for annual / packs (§11) |
| 16 | Commercial crawling of employers' sites not assessed (only LinkedIn was) | §12.4, R-M17 |
| 17 | Account deletion left user-added companies and private facts undefined | §8.3 deletion rules |
| 18 | Free-tier multi-accounting; per-user company-add rate | §12.2 |
| 19 | Hosting assumed a paid droplet from day one; DigitalOcean student credit no longer exists | §10.4 free phase, D-25 phased |

---
*Status: DRAFT r3 — requirements and target design, architect-reviewed (r2) and
logic-reviewed (r3). Next step: P0 — set up the free Singapore VM (§10.4) and run the
datacenter-IP crawl test from it — then `/plan .claude/prds/mullti_user_prd.md` for P1.*
