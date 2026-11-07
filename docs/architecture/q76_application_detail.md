# Q-76: Application detail panel (N12) and auto-apply state on application rows (N11)

Fast track (`instructions/05_workflow.md` §3.2). Source: `docs/reviews/Q-70-ux-audit.md` N11 and N12. No new table and no contract change; `apply/contracts.py` is read only (`REASON_TEXTS`, `STATE_TEXTS`, `AttemptState`, `TERMINAL_STATES`).

## 1. What the owner gets

- Each application row gets a second pill with the latest auto-apply attempt, e.g. `Dry run ready` or `Needs your input`. The pill links to Profile → Application details when the attempt stopped for a question or missing details.
- Each row gets a **Details** button. It opens the posting below the row: facts, "Why it matches", matched skills, "About the job" (fetched on open), the status History, and every auto-apply attempt with its reason in words. One row is open at a time.
- The Inbox detail pane looks and works exactly as today. Its blocks move into a shared `JobDetail.vue`.

## 2. Backend (N11)

**Store** (`store.py`; the only SQL), new method:

```python
def last_attempts(self) -> dict[str, dict[str, Any]]:
    """job_id -> the newest apply_attempts row (all columns) plus `attempts` (count)."""
    # SELECT a.*, n.attempts FROM apply_attempts a
    #   JOIN (SELECT job_id, MAX(id) AS last_id, COUNT(*) AS attempts
    #           FROM apply_attempts GROUP BY job_id) n ON a.id = n.last_id
```

It uses `idx_attempts_job`. `attempts_for_job(job_id)` already exists (oldest first). No DDL.

**Router** (`web/routers/applications.py`). The web may import `apply.contracts` (test_layering CONTRACTS):

- `attempt_view(row) -> dict`, pure. It returns:
  - `{id, mode, state, kind, reason_code, text, hint, queued_at, finished_at, submit_clicked_at, resume_source}`
  - `text`/`hint` = `REASON_TEXTS[reason].text.format(detail=reason_detail)` / `.hint` for `failed`, `STATE_TEXTS[state]` for `submitted_unconfirmed` and `ready_to_submit`, otherwise `""`.
  - It never includes `job_log`, `end_url`, `tenant_host` or `resume_sha256` (not needed; keeps the payload free of paths and URLs).
  - An unknown `reason_code` (an old row) → `text = ""`, `kind = "stopped"`. It never raises.
- `kind` (what the pill shows):

| kind | when |
|---|---|
| `running` | state not terminal (queued … submitting) |
| `sent` | `submitted` |
| `unconfirmed` | `submitted_unconfirmed` |
| `dry_run` | `ready_to_submit` |
| `needs_input` | `failed` with `unanswerable_required` or `profile_incomplete` |
| `cancelled` | `failed` with `cancelled` |
| `stopped` | any other `failed` |

- `GET /api/applications`: every row gains `last_attempt: attempt_view | null` and `attempts: int` (one `store.last_attempts()` call per request; no N+1). Every row also gains `posting: {reason, matched_skills, yoe_min, decided_at, closed} | null`, taken from the shortlist entry the router already loads (`by_id`), so the detail needs no second shortlist read.
- New `GET /api/applications/{job_id}/attempts` → `[attempt_view]`, newest first (`attempts_for_job` reversed). `[]` when there are none, never 404 (an application may have none).

## 3. Frontend

**`web/src/components/JobDetail.vue`** (new; extracted from `Inbox.vue`):

- Props: `job` (the shortlist shape: `id, title, company, location, yoe_min, decided_at, closed, url, reason, matched_skills`) and `titleId` (default `'detail-title'`).
- Owns:
  - the head (CompanyMark + `h3.detail-title`), the facts list, the closed note;
  - "Why it matches", "Matched skills", "About the job", with description loading through `getPosting`, `parseDescription` / `previewBlocks`, `PREVIEW_CHARS`, and the Show more state;
  - `years()`.
- Slots: `actions` (after the closed note) and `extra` (at the end).
- The description cache moves to a module-level `Map` in new `web/src/postingCache.js` (`loadPosting(id) -> {state, text, error}`), shared by both tabs.
- It keeps every class name and id the Inbox tests use: `.detail-head`, `.detail-title`, `.facts`, `.stale-note`, `.why`, `.reason`, `.jd`, `.jd-status`, `.jd-text`, `.jd-more`, `#detail-title`. Their scoped CSS moves with them.

**Inbox.vue** keeps the outer `<article class="detail surface">`, the phone **back** button, the action bar (track, dismiss, keys), the ni-note and the did-apply prompt. They are passed in the `actions` slot.

**Applications.vue:**

- **Pill:** after `follow-up`, `<span class="pill attempt" :data-kind>`. Its label comes from new `web/src/attempts.js` `attemptLabel(kind, mode)`, and its `title` is the attempt's `text`.
- **Details:** a `link details-toggle` button with `aria-expanded` and `aria-controls`. When open, it renders `<JobDetail :job="detailJob(row)" :title-id="`app-detail-${row.job_id}`">` in a `div.app-detail` under the row.
  - `detailJob(row)` merges `row` with `row.posting`, mapping `role` → `title`.
  - The `extra` slot holds the attempts list: fetched on open with `getApplicationAttempts`; each item shows a date, a `Dry run` or `Real` label, the pill, `text` and `hint`.
  - History stays in the row as it is today.
- **Needs input:** `needs_input` links open Profile → Application details. A small new module, `web/src/profileView.js`, exports `PROFILE_VIEW_KEY = 'profile.view'` (moved out of Profile.vue's `VIEW_KEY`) and `openProfile(view)`, which sets the remembered view and then `location.hash = '#/profile'`. Profile.vue imports the key and re-reads it in `onActivated`. App.vue is not touched (it belongs to Q-75 lane I).

**Copy** (`design:ux-copy`; pills are short and say the state, not the mechanism):

| kind | Pill | Note |
|---|---|---|
| running | `Auto-apply running` | |
| sent | `Sent by auto-apply` | |
| unconfirmed | `Sent, not confirmed` | hint from STATE_TEXTS tells what to do |
| dry_run | `Dry run ready` | |
| needs_input | `Needs your input` | link text in the detail: `Answer in Application details` |
| cancelled | `Auto-apply cancelled` | |
| stopped | `Auto-apply stopped` | `text` says why |

Other strings:
- Details button: `Details` / `Hide details`.
- Attempts heading: `Auto-apply attempts`.
- Empty: `No auto-apply attempts for this role.`
- Load error: `Couldn't load the attempts: {error}.` with `Try again`.
- No posting data (left the shortlist): JobDetail shows the facts it has; "About the job" falls back to its existing "on the company site" lines.

## 4. Parallel work: Q-75 lane I is editing Inbox.vue now

The extraction is the **last** step, started only after lane I is merged into `personal` (`int/Q-75-wave3`). Rebase or branch from the new `personal`. Steps 1–4 touch no Inbox file and can start now. Expected touch points in Inbox.vue (line numbers as of personal 3c40aa8; they will move):

- script: the description block (l.124–149: `PREVIEW_CHARS`, `descriptions`, `expanded`, `loadDescription`, `description*` computeds, the `watch` on `selected.id`), `years()` (l.110–113), the imports of `getPosting`, `parseDescription`, `previewBlocks`, `CompanyMark` (if unused after);
- template: `article.detail` inner blocks l.517–533 (head, facts, closed note) and l.583–630 (why, skills, About the job);
- scoped CSS for those classes.

Lane I's likely overlaps: G18 local time (the `Found {date}` fact; keep its new formatter call when moving it), N16 shortcuts (they stay in the Inbox slot) and G3r. Rule: move lane I's merged markup as it is; restyle nothing.

## 5. Build steps (one engineer lane `eng/Q-76-app-detail`, tester after step 6)

1. `store.py`: `last_attempts()`. Verify: `python tests/run_tests.py -k test_store`.
2. `web/routers/applications.py`: `attempt_view`, `last_attempt`/`attempts`/`posting` on rows, `GET /applications/{job_id}/attempts`. Verify: `-k test_web_applications`, then `-k test_layering`.
3. `web/src/api.js` `getApplicationAttempts`; `web/src/attempts.js`; `web/src/profileView.js` (+ Profile.vue reads the key from it). Verify: `cd web; npx vitest run`.
4. `Applications.vue`: the pill and the needs-input link. Verify: vitest.
5. **After Q-75 lane I merges:** `postingCache.js` and `JobDetail.vue`; Inbox.vue uses them (§4). Verify: vitest, with every existing Inbox test unchanged and green.
6. `Applications.vue`: the Details toggle, JobDetail, the attempts list. Verify: vitest, then the full suite `python tests/run_tests.py`. Browser pass on 8768 (DB copy) at desktop width and 390px. The Coordinator rebuilds the bundle after the merge.

**Files:** `src/jobscraper/store.py`, `src/jobscraper/web/routers/applications.py`, `web/src/{api.js,attempts.js,profileView.js,postingCache.js}`, `web/src/components/JobDetail.vue`, `web/src/tabs/{Applications,Inbox,Profile}.vue`, tests. Q-44's lane V also edits `Profile.vue`, but only the Resume view, so the two touch different lines; merge Q-44 first if both are open.

**Tests:**
- D1 `last_attempts`: the newest per job and the count; jobs without attempts are absent.
- D2 `attempt_view`: each kind; the `{detail}` formatting; an unknown reason doesn't raise; no `job_log`, `end_url` or `tenant_host` in the output.
- D3 `/api/applications`: `last_attempt` is null without attempts; `posting` is null when the job left the shortlist; one `last_attempts` query per request (spy).
- D4 `/attempts`: newest first; `[]` for none; a bad id is a 422 by the path pattern.
- D5 vitest: the pill label per kind; needs-input sets the profile view and navigates; Details opens one row at a time; attempts load, empty and error states; JobDetail renders the facts, why and JD with Show more; the Inbox suite unchanged.

READY TO BUILD: yes
