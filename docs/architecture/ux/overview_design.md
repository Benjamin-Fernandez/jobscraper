# Overview tab: lean design (Q-70 wave 2, D-102)

Fast track (`instructions/05_workflow.md` §3.2). Frontend only: no backend or API change, no new npm
dependency, `QuestionCard.vue` untouched. Skills used: design-critique (hierarchy, states), ux-copy (every string below).

## 1. Purpose and decisions

The owner opens the app and needs two answers within seconds: what needs me now, and how is the
search going. Today that takes four tabs (Inbox badge, Applications, Profile → Application details, Runs).

| # | Decision | Why |
|---|---|---|
| O1 | New tab `overview`, **first** in `TABS`, so it is also the default route (`tabFromHash` falls back to `ids[0]`) and the brand link target. **No `App.vue` change**: the shell never names a tab (M7-T4). | A home page is only useful if it is where you land. Deep links (`#/inbox`, `#/runs`, …) keep working unchanged. |
| O2 | No badge on the Overview tab. | Its counts repeat the Inbox and Applications badges. |
| O3 | Pipeline = **current** count per open stage (stat tiles in vocabulary order) plus a closed count; no conversion chart. | Readable at a glance with < 50 rows; a funnel chart adds little and would need the dataviz pass. |
| O4 | "This week" = the rolling **past 7 days** (UTC stamps via `utcMs`), not a calendar week. | No locale or time-zone edge cases (format.js keeps UTC; G18 is later). |
| O5 | A run is "stale" after `STALE_RUN_DAYS = 7`. The card's button starts a run with the saved batch size (same call as Runs). | The run cycle is configurable; 7 days is the widest common cycle (open question 1). |
| O6 | The Questions card deep-links to Profile → Application details by writing `localStorage['profile.view'] = 'details'` (the key `Profile.vue:53` already reads on mount), then `location.hash = '#/profile'`. | Reuses existing behaviour; no Profile.vue edit. |
| O7 | The follow-up card lists up to 3 roles inline and links to `#/applications` with no filter. | Applications' stage is read once at setup; under KeepAlive (C4) a stored-stage hint would be ignored. |
| O8 | The Overview fetches its own data on every mount (it is not in the KeepAlive list). | Always fresh; four small GETs. |

## 2. Data (existing APIs only)

On mount, in parallel with `Promise.allSettled`, so one failure blanks only its own section:

| Call | Shape used | Feeds |
|---|---|---|
| `getApplications()` | `[{job_id, status, company, role, updated_at, applied_at, events:[{from_status, to_status, at}]}]`, events oldest first | pipeline, response rate, follow-ups, past 7 days |
| `getStats()` | `{statuses:[…ordered], by_status:{…}}` | stage order (never hardcoded, M8-T2) |
| `getQuestions('open')` | `{groups:[…], waiting:[{job_id, company, title, open}], ready:[…], busy}` | Questions card |
| `getCurrentJob()` | `{id, kind, state, started_at}` or null | "a run is in progress" line; hides the Start button |

From the shell props (`tabProps`): `jobs` → `newRoleCount(jobs)` (`badges.js`, the same number as the
Inbox badge); `runs` (newest first: `run_no, started_at, finished_at, status, accepted`) → last run, roles
found. `getApplicant` is not needed: open question groups are what blocks auto-apply.

## 3. Pure helpers: new `web/src/overview.js` (no Vue)

Imports: `utcMs` (format.js), `statusLabel`, `CLOSED_STATUSES` (stages.js), `needsFollowUp`, `lastAt`,
`daysSince` (applications.js, lane B step B1: `lastAt(row) -> iso|null`; `daysSince(iso, now = Date.now()) -> int|null`;
`needsFollowUp(row, now = Date.now()) -> boolean`, true when `status === 'applied'` and `daysSince(lastAt(row), now) >= 14`).

Constants: `DAY_MS = 86400000`, `WINDOW_DAYS = 7`, `STALE_RUN_DAYS = 7`, `FOLLOW_UP_SHOWN = 3`,
`HARD_RUN_FAILURES = ['failed', 'aborted_unhealthy']`, `PROFILE_VIEW_KEY = 'profile.view'`.

1. `openStages(statuses = [], rows = [])` → `string[]`. `statuses` without CLOSED_STATUSES, in order; then any
   open status found on a row but not in the vocabulary, appended in first-seen order. Empty `statuses` falls back to
   `['to_apply', 'applied', 'interviewing', 'offer']`.
2. `pipeline(rows, statuses)` → `{ stages: [{status, label, n}], closed: {n, rejected, withdrawn}, total }`.
   `n` counts `row.status`. Zero-count stages stay (the flow reads left to right). `total = rows.length`.
3. `responseRate(rows, statuses)` → `{ applied, heard, rate }`; `rate` is an integer percent, or `null` when `applied === 0`.
   - `later` = open stages after `'applied'` in `openStages` order (e.g. interviewing, offer, Q-60's assessment).
     If `'applied'` is not in the vocabulary, return `{applied: 0, heard: 0, rate: null}`.
   - A row counts as **applied** when its status or any event's `to_status` is `'applied'` or in `later`.
   - It counts as **heard** when it is applied and (status or any `to_status` is in `later`, or it was rejected
     after it was applied: a `'rejected'` event after the first applied-or-later event, or status `'rejected'`
     with an applied event before). Withdrawn is the owner's choice, not a reply. Rejected from Saved is not applied.
4. `pastWeek(rows, runs, now = Date.now())` → `{ found, saved, applied, moved }`. Events with `utcMs(at) >= now - 7*DAY_MS`:
   `saved` = `to_status === 'to_apply'`, `applied` = `to_status === 'applied'`, `moved` = every other event.
   `found` = sum of `Number(accepted) || 0` over runs with `finished_at` in the window and `status !== 'dry_run'`.
   Unreadable stamps are skipped. Undo events count (D-101: an undo is a status change).
5. `followUps(rows, now = Date.now())` → `[{job_id, company, role, days}]`: `needsFollowUp` rows, `days = daysSince(lastAt(row), now)`,
   longest wait first, ties by `job_id`.
6. `lastRunState(runs, now = Date.now())` → `{ state, run, days }`. `run` = the first run with `finished_at` and
   `status !== 'dry_run'` (same pick as `Runs.vue:164`, minus dry runs). `state`: `'none'` (no such run), `'failed'`
   (`HARD_RUN_FAILURES` includes its status), `'stale'` (`days >= STALE_RUN_DAYS`), else `'fresh'`. `days` = whole days, or null.
7. `nextUp({ newRoles, questions, waiting, followUps, run, jobRunning })` → ordered `[{id, n?}]`, only items with work:
   `'questions'` (questions > 0) → `'inbox'` (newRoles > 0) → `'follow-up'` (followUps.length > 0) → `'run'`
   (`run.state` is `'stale'` or `'failed'` and `!jobRunning`). `'none'` gives no card (the setup checklist covers it). `[]` = caught up.

Edge cases every helper handles: `rows`/`runs` null or missing → treated as `[]`; a row with no `events` → `[]`;
statuses unknown to `statusLabel` still get a label (it title-cases them).

## 4. Component: new `web/src/tabs/Overview.vue`

`defineProps(tabProps); defineEmits(tabEmits)`. State: `apps`, `stats`, `questions`, `job` (refs, null until loaded),
`errors` (`{apps, questions}` strings), `firstLoad` (true until the first settle), `starting`, `startError`.
`now = Date.now()` read once per load (no ticking clock). `load()` runs on mount; the Try again buttons call it.

Template, top to bottom (`<section class="overview" aria-labelledby="overview-title">`):

1. `<header class="page-head">`: `<h2 id="overview-title" class="page-title">Overview</h2>`,
   `<p class="page-sub">Where your search stands, and what to do next.</p>`. Below it, one quiet status line
   `<p class="run-line muted">`:
   - job running: "A run is in progress. Follow it on the <a href="#/runs">Runs tab</a>."
   - else last run: "Last run {ago(finished_at, now)}: {plural(accepted, 'new role')}." (`ago`, `plural` from format.js)
   - no run: nothing.
2. `firstLoad` → `<TabLoading :rows="3" />` and nothing else.
3. `runs.length === 0` → `<SetupChecklist :runs="runs" />` (its own heading and steps). The sections below still render
   (they show their empty states), so the page never goes blank once setup is done.
4. **Next up** `<section aria-labelledby="next-title">`, `<h2 id="next-title" class="section-title">Next up</h2>`,
   then `<ul class="next-cards">`, one `<li class="next-card surface" :data-kind="id">` per `nextUp` item; each card is
   `<h3 class="next-title">`, one `<p class="next-body muted">`, and one CTA (`a.button` or `button`):

| id | Title (h3) | Body | CTA |
|---|---|---|---|
| questions | "{plural(n, 'question')} waiting for your answer" | waiting > 0: "Auto-apply is paused on {plural(w, 'application')} until you answer." else "Answer once; every later form reuses it." | `button.primary` "Answer questions" → O6 |
| inbox | "{plural(n, 'new role')} to triage" | "Save the ones worth applying to; mark the rest Not interested." | `a.button` "Open Inbox" `#/inbox` |
| follow-up | "{plural(n, 'application')} to follow up" | "Applied 14 or more days ago, with no reply recorded." then `<ul class="follow-list">` of up to 3: "{company} · {role} · {days} days" (+ "and {k} more" when k > 0) | `a.button` "Open Applications" `#/applications` |
| run (stale) | "Your last run was {days} days ago" | "New postings may be waiting. A run checks the companies that are due." | `button.primary` "Start a run" (busy: "Starting…", disabled) |
| run (failed) | "Your last run {runStatusLabel(status)}" ("failed" / "aborted") | "See what happened on the Runs tab." | `a.button` "Open Runs" `#/runs` |

   - The first card's CTA is `primary`; the others `ghost`, so exactly one primary action shows.
   - Caught up (`[]`, runs exist): `<div class="empty">` with `<p class="empty-title">You're all caught up.</p>` and
     `<p class="muted">Nothing needs you right now. The next run brings new roles to your Inbox.</p>`.
   - Questions failed to load: the card is skipped and a `notice warn` reads "Could not check for open questions: {error}."
     with `button.link` "Try again".
   - Start a run: `startRun({})` (saved batch size), then `useJob({ kind: 'run' }).track(started, { started: true })`, so
     lane C's shell pill and finish toast take over. Success → `showToast({ message: 'Run started. New roles land in the Inbox when it finishes.', link: { label: 'Open Runs', href: '#/runs' } })`
     and the run card hides (`job` set to the started job). 409 → `startError` "A job is already running. Follow it on the Runs tab."
     Other → "Could not start the run: {describeError(e)}". `startError` shows in `<p class="notice error" role="alert">` inside the card.
5. **Pipeline** `<section aria-labelledby="pipe-title">`, `<h2 id="pipe-title" class="section-title">Pipeline</h2>`:
   - `<ol class="stage-tiles" aria-label="Open applications by stage, in order">`; each
     `<li class="stage-tile" :data-status="status"><span class="tile-n">{n}</span> <span class="tile-label">{label}</span></li>`,
     separated by `<span class="flow" aria-hidden="true">→</span>`. Then a separate tile `li.stage-tile.closed`: n = `closed.n`,
     label "Closed", `title` "Rejected {r} · Withdrawn {w}", plus visually-hidden " (rejected {r}, withdrawn {w})".
   - Response line `<p class="response">`: rate null → "No applications sent yet." else
     "**{rate}%** response rate · {heard} of {plural(applied, 'application')} heard back", with
     `<span class="muted">` "An interview, offer or rejection after you applied counts as a reply."
   - `total === 0` → instead of tiles: "Nothing tracked yet. Save a role in the Inbox and it shows up here."
   - Applications failed → `notice error`: "Could not load your applications: {error}" + `button` "Try again" (Pipeline and Past 7 days both).
   - The whole section is an `a`-free summary; one trailing link "Open Applications" (`#/applications`, class `link`).
6. **Past 7 days** `<section aria-labelledby="week-title">`, `<h2 id="week-title" class="section-title">Past 7 days</h2>`:
   `<dl class="week-tiles">` with four `<div>` pairs, `<dt>` label then `<dd class="tile-n">` count: "New roles found",
   "Saved", "Applied", "Other updates". All four zero → `<p class="muted">A quiet week: nothing found or changed in the past 7 days.</p>`.

## 5. Layout and tokens

- Desktop (> 900 px): Next up as `display: grid; grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr)); gap: var(--space-4)`.
  Pipeline and Past 7 days side by side under it: `.overview-lower { display: grid; grid-template-columns: 3fr 2fr; gap: var(--space-5) }`.
- ≤ 900 px: `.overview-lower` one column. ≤ 640 px: next cards one column, CTA `justify-self: start`;
  stage tiles `flex-wrap: wrap` two per row (`flex: 1 1 40%`), `.flow` hidden; week tiles a 2 × 2 grid.
- Cards: `.surface`, `padding: var(--space-4)`, `border-radius: var(--radius-lg)`, `border-left: 3px solid`:
  questions and stale run `var(--warn)`, failed run `var(--danger)`, inbox and follow-up `var(--accent)`.
- Tiles: `.tile-n { font-family: var(--mono); font-variant-numeric: tabular-nums; font-size: var(--text-2xl); font-weight: 650; color: var(--text) }`,
  `.tile-label { font-size: var(--text-sm); color: var(--muted) }`; stage tiles get `border-top: 3px solid` from
  `[data-status=to_apply] var(--stage-saved)`, `applied var(--stage-applied)`, `interviewing var(--stage-interview)`,
  `offer var(--stage-offer)`, `assessment var(--stage-assessment, var(--stage-closed))`, default and `.closed` `var(--stage-closed)`.
- Spacing only from `--space-*`, text from `--text-*`. No new colour or token; all CSS scoped in Overview.vue.

## 6. Accessibility

- One `h2` page title; each section is a `<section>` labelled by its own `h2`; cards use `h3` (under the shell's `h1`).
- Counts are real text inside lists (`ol`/`dl`), so a screen reader hears "3 Applied", "New roles found 12"; the arrows and
  stage colours are decoration (`aria-hidden`, never the only cue).
- No `aria-live` on the counts (they don't change while viewed). Loading is TabLoading's `role="status"`; errors use
  `role="alert"`; the start result is a toast (ToastHost already announces).
- Focus is not moved on mount. CTAs are real links/buttons ≥ 24 px tall (`--control-h`); the Closed tile's breakdown is
  in visually-hidden text, not only in `title`.

## 7. Extra: calmer "failed N" on the Runs table (`web/src/tabs/Runs.vue`)

Today `.failed-link` is always `var(--danger)`, so a successful run with 28 unreadable companies looks like an outage.
(Covers the failed-link part of G27; the aborted-reason part stays later.)
- Script: `import { plural } from '../format.js'` (add to the existing import); `const HARD = ['failed', 'aborted_unhealthy']`;
  `const failedTone = r => (HARD.includes(r.status) ? 'hard' : 'partial')`;
  ``const failedText = r => `${plural(Number(r.stats.companies_failed), 'company', 'companies')} could not be read. See which on the Companies tab.` ``.
- Template `:344-350`: `:class="['link', 'failed-link', failedTone(r)]"`, `:title="failedText(r)"`, `:aria-label="failedText(r)"`. Click unchanged.
- CSS `:385-386`: `.failed-link { font-family: var(--mono) }`, `.failed-link.hard, .failed-link.hard:hover:not(:disabled) { color: var(--danger) }`,
  `.failed-link.partial { color: var(--muted); text-decoration: underline dotted }`, `.failed-link.partial:hover:not(:disabled) { color: var(--text) }`.

## 8. Build steps (one lane, after lanes B and C merge into int)

Files: `web/src/overview.js` (new), `web/src/tabs/Overview.vue` (new), `web/src/tabs.js`, `web/src/tabs/Runs.vue`,
`web/tests/overview.test.js` (new), `web/tests/Overview.test.js` (new), `web/tests/Runs.test.js` (new describe only),
plus the test hunks in step 5 (`App.test.js` is lane C's, `Applications.test.js` lane B's: apply after they merge).
Disjoint from A (Inbox.vue), B (Applications.vue, applications.js, StatusSelect.vue), C (App.vue, style.css, useJob.js,
RunSelector.vue, JobPill.vue), D (ApplicationDetails, FieldInput, QuestionsInbox). `App.vue` is **not** edited.

1. `overview.js` per §3, with `overview.test.js` first (pure, `now` injected).
2. `Overview.vue` per §4–§6, importing `TabLoading`, `SetupChecklist`, `showToast` (`../toast.js`), `useJob`, the api calls, format/runs helpers.
3. `tabs.js`: one additive hunk, the first entry of `TABS`:
   `{ id: 'overview', label: 'Overview', component: () => import('./tabs/Overview.vue') },` (and a one-line comment: the home page, default route).
4. `Runs.vue` per §7.
5. Tests that assume an empty hash opens the Inbox:
   - `App.test.js`: `beforeEach` `setHash('')` → `setHash('#/inbox')`; `:60, :143, :159, :175` then run on the Inbox unchanged.
     `:69` expects `['Overview', 'Inbox', 'Applications', 'Runs', 'Companies', 'Profile', 'Settings', 'Developer']` (`slice(0, 8)`).
     `:184-194` become "an empty hash opens the Overview and the URL says #/overview" (`setHash('')`, wait for `.overview`)
     and "an unknown hash falls back to the Overview". `:242-245` expect `'overview'`. `:253`: `i === 0` → `t.id === 'inbox'`.
     `:268` ArrowLeft from inbox → `'overview'`, then one more ArrowLeft → `LAST`; `:281` Home → `'overview'`; `:283` stays on `'overview'` (key 'a' from there).
   - `Applications.test.js:174`: `setHash('')` → `setHash('#/inbox')`.
   - Unchanged, verified: `ui.test.js` (`#/inbox`), `Runs.test.js:254` (`#/runs`), `extensibility.test.js` (explicit hashes), `ux1.test.js:357` (badges only).

Verify: `cd web; npx vitest run tests/overview.test.js tests/Overview.test.js tests/Runs.test.js tests/App.test.js tests/Applications.test.js`,
then the full `npx vitest run`. New test names:
- overview.test.js: "openStages keeps config order and appends unknown open statuses"; "pipeline counts closed apart";
  "responseRate counts interview, offer and rejection after applying, not withdrawn or rejected from Saved";
  "responseRate is null with no applications"; "pastWeek uses a rolling 7 days and skips dry runs";
  "followUps lists applied 14+ days, longest first"; "lastRunState is none, fresh, stale or failed";
  "nextUp orders questions, inbox, follow-up, run and hides the run card while a job runs".
- Overview.test.js (fakeApi, `vi.setSystemTime`): "shows TabLoading until data settles"; "renders a card per pending item and only one primary CTA";
  "caught up when nothing is pending"; "Answer questions stores profile.view=details and opens #/profile";
  "Start a run posts jobs/run once and shows the toast; 409 shows the already-running text";
  "an applications error keeps Next up and offers Try again"; "no runs shows the setup checklist".
- Runs.test.js, describe "failed N tone": "a successful run's failed count is muted with a title"; "a failed or aborted run's count stays red".

Manual on 8768 (DB copy): open `/` → lands on `#/overview`; counts match the Inbox badge and the Applications chips;
Answer questions opens Profile on Application details; at 390 px the page is one column with no sideways scroll;
on Runs, run 29 (success, 28 failed) shows a muted 28 with the tooltip, an aborted run's count is red.

## 9. Later (needs a backend change or another lane)

- A deep link to the Applications "Follow up" rows (needs Applications.vue to re-read a hint on `onActivated`; lane B file).
- Use the configured run cycle for staleness instead of `STALE_RUN_DAYS` (needs `getSettings`, or cycle in `/api/runs`).
- Auto-apply attempt counts on the Overview (N11: `apply_attempts` join).

## Open questions

1. Stale threshold: 7 days fixed, or the configured cycle (one extra `getSettings()` call, no API change)? Default: 7.
2. Should Overview stay the default route, or land on the Inbox when it has new roles? Default: always Overview.

READY TO BUILD: yes
