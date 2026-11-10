# Q-87 Recommended companies: design

**Status: READY TO BUILD** (architect, 2026-11-10). Owner request 2026-11-10: "a section to recommend companies based on the type of companies the user has input (assuming there are at least 30 to extract)". Decisions D-113..D-116. Fast-track item (not a key area), P2.

Reuses M16 `company_search.py` (ask Qwen with null-not-guess, prove with `scrape/discovery.py`, read the board once), the `JobManager` child-process jobs, and `watchlist.all_entries` + `store.sync_watchlist` for "becomes watched".

## 1. Inputs (D-113)

- **The user's set** = every row of `companies` (enabled) that has `last_success_at IS NOT NULL`. That is watchlist.yaml plus the uploaded list plus earlier added recommendations: everything the user chose and that we could read.
- **Gate:** `scanned = count(enabled AND last_success_at NOT NULL)`; ready when `scanned >= 30` (`RECS_MIN_SCANNED = 30`, a module constant). Below the gate, nothing is generated; the API returns `{ready: false, scanned, needed: 30, more: 30 - scanned}` and the UI says how many more are needed. The refresh endpoint refuses with 409 below the gate; the CLI exits 2 with the same sentence.
- **Weights** (deterministic, from stored data, no model): per company `weight = 3 * applied + 1 * accepted`, where `applied` = rows in `applications` for its jobs (any status) and `accepted` = its jobs with an `accept` decision for the current profile version. Ties break by `last_success_at` (newest first), then name. The **sample** is the top 60 names by weight. With no applications or accepts at all, the sample is the 60 most recently read companies (the set is then unweighted; still valid).
- **Target titles** (`profile/titles` user titles, else the derived profile's `target_titles`) are used only **deterministically**, after proof: a candidate's `title_matches` = its postings whose title contains a target title (casefold substring, same normalisation as the prefilter's `title_allow`). They never go to the model (privacy rule, §6).

## 2. Generation (D-114)

Two kinds of model call, both via `backends.build(cfg.budget)` and `backend.complete(system, user, max_tokens)` (only `backends.py` talks to the model):

1. **Summarise** (1 call, `max_tokens=1500`): the 60 sample names -> up to 6 sectors, each with up to 4 example names taken **from the input**. Prompt: "Group these companies into at most 6 sectors (e.g. fintech, semiconductors, e-commerce). Use only names from the list as examples. If you do not know a company, leave it out. Reply with ONLY `{"sectors": [{"sector": "...", "examples": ["..."]}]}`."
   Deterministic check: an example not in the sample (case-insensitive) is dropped; a sector with no example left is dropped. 0 sectors -> state `model_unusable` (§6).
2. **Propose** (1 call per sector, at most 6, `max_tokens=2000`): "Name up to 12 companies similar to {examples} in {sector} that have an office in Singapore and hire fresh graduates. Do not repeat these: {examples}. If you are not sure a company exists or has a Singapore office, leave it out. For the website and careers page answer null rather than guess; never invent a domain. Reply with ONLY `{"companies": [{"name": "...", "website": "https://..." or null, "careers_url": "https://..." or null}]}`." The lead URL is `company_search._http(careers_url) or _http(website)`, exactly as `lookup_sites`.
   Parsing reuses `company_search._json`; a call that fails or parses to nothing yields no candidates for that sector (counted `ask_failed`).

**Exclusion (deterministic, before any network):** `norm_key(name)` = `slugify(name)` with trailing legal tokens removed (`pte, ltd, limited, inc, llc, corp, corporation, co, plc, group, holdings, sa, ag, gmbh, bv`). A candidate is dropped (counted `excluded`) when its norm key or `slugify` matches any of: every `companies` row (enabled or not, so quarantined and **unscannable** (D-111: quarantined, `probation_due_run IS NULL`) companies are excluded); every `company_list` row (any status, so a failed search is not retried here); every `company_recs` row (shown, added, dismissed, or unproven within 30 days). Duplicates across sectors keep the first. **After proof** a second check drops a candidate whose `(provider, slug)` equals a watched company's (catches "Facebook" vs "Meta").

**Deterministic seed: none** (D-114). There is no public directory of ATS boards to enumerate (guessing slugs is crawling), and `companies` stores no sector; the model's sector grouping is the only sector source. Revisit if a curated seed file is ever wanted.

**Bounds:** at most 72 candidates; prove at most `RECS_MAX_CHECKS = 40` in sector order (interleaved round-robin so one sector cannot use them all); stop early once `RECS_MAX_SHOWN = 20` are proven.

## 3. Verification (D-115)

Every candidate goes through **the same proof as M16**: refactor `company_search._search_one` into a public

```python
def prove(name: str, lead: Optional[str], client: HttpClient, resolve: Callable,
          fetch: Optional[Callable], locations: Sequence[str] = ()) -> dict[str, Any]
```

returning the existing result dict (`status` found|failed, `company_key`, `careers_url`, `provider`, `slug`, `feed_url`, `postings`, `detail`) plus `sg_postings` (postings whose `location` casefold contains any of `cfg.scrape_locations`; `None` when no posting has a location, e.g. many `generic_html` pages) and `titles` (the posting titles, used for `title_matches`, not stored). `_search_one` keeps its "already watched" check and then calls `prove`; M16 behaviour is unchanged (pinned).

- **Shown only if** `status == found` and `postings >= 1`. Found with 0 open roles, failed, or a duplicate board -> `unproven` with the detail; never shown, kept 30 days so a refresh does not re-check it.
- **Robots and bot checks:** the `HttpClient` is built as in `search()` (`respect_robots` from `run`, the configured UA, `rate_limit_delay`, `max_retries=1`). Discovery's existing public ATS API probes are unchanged. A `blocked` fetch is `unproven` ("the site blocked automated reading"); no retry with another UA, no browser, never a CAPTCHA.
- Workday and SmartRecruiters boards are read with the Singapore facet (D-33), so for them `sg_postings == postings`; the card says so plainly by showing only "N open roles in Singapore".

## 4. Storage and API (D-116)

**Table** (DDL for `store.py`; the engineer adds it to the schema script):

```sql
CREATE TABLE IF NOT EXISTS company_recs (
    key TEXT PRIMARY KEY,                -- norm_key(name)
    name TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('shown', 'added', 'dismissed', 'unproven')),
    sector TEXT, like_names TEXT,        -- like_names: JSON list (<= 3) from the user's set
    careers_url TEXT, provider TEXT, slug TEXT, feed_url TEXT,
    postings INTEGER, sg_postings INTEGER, title_matches INTEGER,
    detail TEXT,                         -- proof result or why unproven
    company_key TEXT,                    -- companies.key once added
    proposed_at TEXT NOT NULL, checked_at TEXT, decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_company_recs_state ON company_recs(state);
```

**Cache:** a refresh deletes `shown` rows older than 14 days and `unproven` rows older than 30 days, then adds new ones; `dismissed` and `added` rows are permanent (they are the exclusion memory). A shown card's counts are as of `checked_at` ("checked 3 days ago").
**Progress/status:** settings key `company_recs.status`, JSON `{state: running|done|model_down|model_unusable|failed, phase: gather|summarise|propose|prove|done, done, total, current, started_at, finished_at, counts: {asked, excluded, checked, proven, unproven, ask_failed}}`, written with `store.set_setting` after every candidate (as M16 writes per row). If Q-85's progress sidecar (D-112) is generic for all job kinds when this is built, the CLI also reports through it; the UI reads the settings key either way.

**Add path:** an `added` row becomes a watched company through `watchlist.all_entries`, which gains a third source after the uploaded list: `recommended_entries(store.company_recs(states=("added",)), taken)` (notes "recommended"), then `store.sync_watchlist(...)` at once, exactly like a `found` list row. It is scanned at the next run (never-scraped companies are due first). Not appended to `company_list`: `replace_company_list` would drop it on the next upload.
**Plan cap:** `Plan.max_companies` counts `found`+`watched` list rows **plus** `added` recs; an add over the cap is refused (409). The owner's `local` plan has no cap.

**Endpoints** (web imports only store, watchlist, config; never the orchestrator):

| Method, path | Does | Returns |
|---|---|---|
| `GET /api/companies/recommended` | `control.recommended_view(cfg, store)` | `{gate: {ready, scanned, needed, more}, status: <settings JSON or null>, items: [Rec], cap: {max, used}}`; items = `shown`, ranked `sg_postings` desc (null last), `title_matches` desc, `postings` desc |
| `POST /api/jobs/recommend` | `JobManager.start("recommend", {})`, argv `companies recommend` | 202 job record; 409 below gate ("needs 30 scanned companies"), 409 JobBusy |
| `POST /api/companies/recommended/{key}/add` | state -> added, `company_key = slugify(name)`, `decided_at`, sync watchlist | 200 `{item, watched: true}`; 404 unknown/not shown; 409 over cap; idempotent on `added` |
| `POST /api/companies/recommended/{key}/dismiss` | state -> dismissed | 200 `{item}`; 404; idempotent |

`Rec` JSON: `{key, name, sector, like_names, provider, careers_url, postings, sg_postings, title_matches, checked_at}`.

## 5. UI (lane V)

Companies tab gains a third view in its view switch, **"Recommended"** (remembered like the others), rendered by a new `web/src/components/RecommendedCompanies.vue`. Header "Recommended for you" + **Refresh** button (`useJob`, disabled while any job runs).

- **Card:** `CompanyMark` + name; reason line **"Like Grab, Sea: fintech, Singapore"** (built in the UI from `like_names[:2]` and `sector`; no free model text is shown); board line **"Greenhouse board"** / **"Careers page"** (`generic_html`); counts line: `sg_postings > 0` -> **"12 open roles, 3 in Singapore"**; `0` -> **"12 open roles, none in Singapore right now"**; `null` -> **"12 open roles"**; Workday/SmartRecruiters -> **"3 open roles in Singapore"**; plus **"2 match your titles"** when `title_matches > 0`; "Checked 3 days ago" muted. Buttons **Add to watched** (primary) and **Not interested** (quiet). After Add: card shows "Added. It will be scanned in the next run." then leaves the list; after Not interested it leaves with a toast "Hidden. We won't suggest it again." (no Undo in v1).
- **Below gate:** "Recommendations start once 30 of your companies have been scanned. You have 22 so far, so 8 more to go. Add companies under Your list, then run a scan." Refresh hidden.
- **Ready, never refreshed:** "Find companies like the ones you watch. We ask Qwen for similar firms with a Singapore office, then check each has a job board we can read." + Refresh.
- **Running:** progress line from `status`: "Grouping your companies…" (summarise), "Asking Qwen for similar companies…" (propose), "Checking job boards: 14 of 40 (Stripe)" (prove), with a bar; poll GET every 2 s while the job runs (as the list view does).
- **Done, nothing new:** "No new companies to recommend right now. We checked 34 suggestions; none had a job board we could read. Try again in a few weeks."
- **Model down:** "Couldn't get new recommendations: Qwen isn't running. Start Ollama, then refresh. Earlier recommendations are still below."
- **Over cap (409):** "Your plan watches up to N companies. Remove one to add this."
- **390px:** cards one column; the two buttons share a row at 50% each, min 44px tall; the reason and counts lines wrap, never truncate the counts; the view switch scrolls horizontally if three labels do not fit.

## 6. Contracts, layering, failures, privacy

New orchestrator `src/jobscraper/company_recs.py` (CLI-only import, like `company_search`):

```python
RECS_MIN_SCANNED = 30; RECS_MAX_CHECKS = 40; RECS_MAX_SHOWN = 20
def norm_key(name: str) -> str
def gate(store: Store) -> dict[str, int | bool]                  # {ready, scanned, needed, more}
def sample(store: Store, limit: int = 60) -> list[str]           # weighted, §1
def summarise(backend: Any, names: list[str]) -> list[dict]      # [{sector, examples}], checked
def propose(backend: Any, sector: str, examples: list[str]) -> list[dict]   # [{name, lead}]
def recommend(cfg: Config, store: Store, *, backend: Any = None,
              client: Optional[HttpClient] = None, resolve: Callable = discovery.resolve,
              fetch: Optional[Callable] = None, say: Callable[[str], Any] = print) -> dict[str, int]
```

Store methods (only `store.py` has SQL): `scanned_company_count() -> int`; `company_signal_weights(profile_version: int) -> dict[int, int]` (company_id -> weight); `company_recs(states: Sequence[str] = ()) -> list[dict]`; `upsert_company_rec(key: str, **fields) -> None`; `set_company_rec_state(key: str, state: str, now: str) -> Optional[dict]`; `purge_company_recs(now: str, shown_days: int = 14, unproven_days: int = 30) -> int`. Watchlist: `recommended_entries(rows, taken) -> list[WatchlistEntry]`. Control: `recommended_view(cfg, store) -> dict`. CLI: `companies recommend` (exit 0 done, 2 below gate, 3 model down/unusable, 1 other). jobs.py: `KINDS += ("recommend",)`, argv `["companies", "recommend"]`.

**Layering:** `test_layering.py` adds `company_recs` to `ORCHESTRATOR` and the edge `("company_recs", "company_search")` to `ORCHESTRATOR_EDGES` (reuse `prove`, `_json`, `_http`, no copy). Web may not import either.

**Failure modes:** backend unavailable or every call raising `BackendError` before any candidate -> `model_down`, exit 3, shown rows untouched. Summarise yields 0 valid sectors -> `model_unusable` ("Qwen's answer couldn't be used. Try refresh again."), exit 3. A propose call failing -> that sector skipped, `ask_failed` counted. Discovery/board errors -> `unproven` silently, counted in `counts.unproven`, never shown. Cancel (JobManager CTRL_BREAK) -> `status.state = failed`, `"cancelled"`; rows written so far stay.

**Privacy:** the model sees only company names (the user's sample and its own suggestions) and sector labels. No titles, profile, resume, email or application data. Recommendations live only in the local DB (`data/`, never committed); fixtures use invented company names.

## 7. Build steps and test plan

Lanes have disjoint files; V builds against the §4 JSON with a mocked api.

**Lane P (software-engineer, sonnet), branch `engineer/Q-87-recs-python`:**
1. `store.py`: DDL + the six methods. `watchlist.py`: `recommended_entries`, `all_entries` third source.
2. `company_search.py`: extract `prove` (+ `locations`, `sg_postings`, `titles`); `_search_one` calls it.
3. `company_recs.py` (§6), `cli.py` `companies recommend`.
4. `web/jobs.py` kind; `web/routers/companies.py` 3 routes + `web/routers/jobs.py` `POST /jobs/recommend`; `web/control.py` `recommended_view`.
Verify: `python tests/run_tests.py -k company` (existing M16 pins stay green) then `python tests/run_tests.py -k layering` after lane T's layering edit.

**Lane V (software-engineer, sonnet), branch `engineer/Q-87-recs-vue`:** `web/src/api.js` (`getRecommended`, `startRecommend`, `addRecommended`, `dismissRecommended`), `components/RecommendedCompanies.vue`, `tabs/Companies.vue` view switch. Verify: `cd web; npx vitest run`.

**Lane T (tester):** `tests/test_company_recs.py`, `test_layering.py` edit, `web/src/components/RecommendedCompanies.test.js`. Verify: `python tests/run_tests.py -k company_recs` and `cd web; npx vitest run RecommendedCompanies`.

**Pins** (fake backend with scripted JSON replies, fake `resolve`/`fetch`, temp store; no network, no Ollama):
1. Gate: 29 scanned -> `ready false, more 1`, CLI exit 2, refresh route 409; 30 -> ready. Disabled or never-succeeded companies do not count.
2. Sample weights: applied 3 / accepted 1 ordering; no signals -> recency order; limit 60.
3. Summarise drops examples not in the sample and empty sectors; 0 sectors -> `model_unusable`, exit 3.
4. Exclusion by norm key ("Grab Holdings Pte Ltd" vs watched "Grab"), unscannable company (quarantined, probation NULL), list `failed` row, dismissed and recent unproven recs; never sent to `resolve`.
5. Post-proof duplicate board `(provider, slug)` -> unproven.
6. Shown only when found with postings >= 1; 0 roles and failed -> unproven, counted; caps 40 checks / 20 shown; round-robin across sectors.
7. `sg_postings`: location match, `None` when no locations; `title_matches` from target titles; ranking order in `recommended_view`.
8. Model down (backend `available=False`) -> `model_down`, exit 3, existing shown rows untouched; one propose `BackendError` -> sector skipped.
9. Add -> `added`, watched via `all_entries`, survives `replace_company_list`; over cap 409; idempotent. Dismiss -> excluded next refresh.
10. Purge windows 14/30 days; dismissed/added never purged.
11. M16 regression: `search()` results unchanged after the `prove` refactor.
12. Privacy: the fake backend records prompts; assert no target title or profile text appears in any prompt.
13. Vitest: gate copy with numbers, never-refreshed, running progress per phase, model-down, empty-done, card count variants (sg >0 / 0 / null / Workday), Add/Not interested remove the card, 409 cap message, 390px buttons layout class.

## Alternatives rejected

- Web search or company databases (Crunchbase, LinkedIn): paid or scraping against terms; the app stays local and free.
- Deterministic seed from ATS boards: no public board directory; slug guessing at scale is crawling.
- Embedding similarity over job descriptions: we have no descriptions for unwatched companies, so nothing to compare.
- Showing unproven model suggestions marked "unverified": the owner asked for real boards, and Qwen invents plausible names.
- Appending adds to `company_list`: a re-upload of the list would silently unwatch them.
- Running the generation in a web thread: web may not import orchestrators, and a model call must not block the web app.
- One settings JSON blob for all recs: per-candidate progress writes and dismissal lookups want rows; a table is simpler.
- Sending target titles to the model for better fit: owner rule is names and sectors only; titles are applied deterministically after proof instead.
