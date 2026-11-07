# Q-44 + Q-73: Refresh application details from the resume, and a readable resume summary

Fast track (`instructions/05_workflow.md` §3.2). It generalises `apply_design.md` §5.5 (`applicant init`, never built) into a repeatable refresh. KA-4 rules: copy facts, invent nothing.

## 1. What the owner gets

1. The owner uploads a resume. The profile job runs as today and then also prepares **proposals** from the new resume.
2. The Resume view shows a summary card (Q-73) and, below it, **"Update your application details"**: a list of changes with checkboxes, each showing the before and after. The owner ticks, then chooses **Save {n} changes**.
3. Only entries that came from a resume (`from_resume: true`) or are still the template placeholders can change. Entries the owner added or edited (Q71-07 sets `from_resume: false`) are never changed: they show as "Kept: you edited this".
4. CLI: `python -m jobscraper applicant refresh-resume` prints the same plan. `--yes` saves the changes that are ticked by default.

## 2. Components and layering

| Piece | Module (layer) | Role |
|---|---|---|
| `profile_proposals(cfg, backend) -> dict` | `tailor_flow.py` (orchestrator) | Loads the master resume (`_load_master`, made public as `ensure_master`; a model parse only when the cache is stale). Maps its entries to plain dicts (§3.1). Filters the derived skills (§3.3). |
| `parse_resume_dates`, `skill_label`, `refresh_plan`, `apply_refresh`, `load_proposals`, `save_proposals` | `applicant.py` (foundation, pure dicts) | Merge and apply (§3.2). No tailor import. |
| `cmd_profile --plan-applicant`, `cmd_applicant refresh-resume` | `cli.py` | Writes the proposals file. Prints or saves the plan. |
| `GET/POST /api/applicant/refresh` | `web/routers/applicant.py` | Reads the proposals file, computes the plan fresh, saves with the etag guard. |
| Summary card, refresh panel | `web/src/tabs/Profile.vue`, new `web/src/components/ResumeRefresh.vue` | UI (§5). |

**Proposals file:** `data/applicant.refresh.json` (gitignored with `data/`; the path is derived beside `cfg.applicant_path`, so no config key). Shape:

`{resume_hash, source_name, created_at, experience:[entry], education:[entry], skills:[label], not_on_resume:[label]}`

The file holds resume-side facts only. The plan is computed against the current `applicant.yaml` on every GET, so it is never stale after a form edit.

## 3. Algorithms (all deterministic; the only model step is the existing master parse)

### 3.1 Proposal entries (`tailor_flow.profile_proposals`)

- Only `SectionKind.EXPERIENCE` and `SectionKind.EDUCATION` count. Projects, leadership and awards are never mapped.
- **Experience:**
  - `employer` = `organisation` and `title` = `title`, both verbatim.
  - `location` = `entry.location` verbatim, else `""`. Never `contact.location`, never a guess (Q-46a lesson).
  - `description` = the first bullet, verbatim (≤ 500 chars; cut at the last space before 500, nothing added).
  - `start`/`end` from `parse_resume_dates(entry.dates)`.
- **Education:**
  - `institution` = `organisation` and `degree` = `title`, both verbatim. `start`/`end` as for experience.
  - `major`, `minor`, `grade*` = `""`. The subtitle is not parsed, so no grade or major is guessed. The verbatim `subtitle` goes to the change's `note` ("Resume says: …") so the owner can copy it.
- Every proposal carries `from_resume: true` and `dates_text` (the verbatim dates, plan display only; never saved).
- **Never touched:** `languages` (no levels are invented), `links`, `attested_skills`, and everything else in the file.

### 3.2 `parse_resume_dates(text) -> (start, end, ok)`

- Accepted tokens:
  - `Mon YYYY` or `Month YYYY` → `YYYY-MM`
  - `MM/YYYY` → `YYYY-MM`
  - `YYYY-MM` → `YYYY-MM`
  - `Present` / `Current` / `Now` / `Ongoing` → `end = None`
- Separators: `–`, `—`, `-`, `to`.
- A single token: with `Expected`/`Exp.` before it, it is the `end` only; otherwise it is both `start` and `end`.
- Not accepted:
  - A year with no month ("2021 – 2025"): no month is invented.
  - Anything else.
- When `ok = False`, both values are `None` and the change gets the note `Dates not understood ("<verbatim>"). Add them after saving.`
- An entry with no `start` adds nothing to `computed_facts` (§5.1), so an unread range is never taken as "present".

### 3.3 Skills

- A derived skill (`profile.derived.yaml` `skills`) is proposed only if it appears in the resume text (`tailor_flow.master_text`, else `resume_ingest.extract_text`) as a whole word, case-insensitively. The derive prompt may imply skills (resume_ingest l.198); those go to `not_on_resume` and are never added (KA-4, Q-46b).
- `skill_label` is the Python twin of `applicantForm.js skillLabel`, and the same test cases pin both.
- The plan **adds** missing skills (case-insensitive) and never removes one. Exception: when `skills` is exactly the template's placeholder list, the plan offers to replace it.

### 3.4 `refresh_plan(profile, proposals, template) -> Plan` (pure)

- **Replaceable entry:** `from_resume is True`, or its identifying pair equals the template's placeholder (`employer`+`title` / `institution`+`degree` read from `config/applicant.example.yaml`). Anything else is owner-owned, including entries with no `from_resume` key, which is what the form adds.
- **Match key:** `_key(org) + "|" + _key(title)`, where `_key` = lowercase, punctuation to spaces, whitespace collapsed (a private helper in `applicant.py`; foundation may not import `apply/plan.norm_label`). If no exact match exists, a match on `org` alone counts when it is unique on both sides (a promotion, a renamed degree).
- **Ops per list** (`experience`, `education`):
  - `update`: a replaceable entry matched to a proposal whose values differ. The new entry is the proposal. A field the proposal cannot fill (unread dates, `""`) keeps the old value only when the old entry was `from_resume: true`, never from a placeholder. Default ticked.
  - `add`: a proposal with no match. Default ticked, except when its dates are not understood.
  - `remove`: a replaceable entry with no match ("No longer on your resume", or "Example entry from the template"). Default ticked.
  - `kept`: an owner-owned entry that a proposal matches. Info only: the proposal is dropped.
- **Order:** existing entries keep their positions. An added entry goes just before the first kept or updated entry that follows it in resume order; if there is none, it goes at the end.
- **Change id:** `"<list>:<op>:<match key>"` (stable across GETs). `skills:add` and `skills:replace` are one change each.
- **`apply_refresh(profile, proposals, accept_ids, template) -> dict`:** recomputes the plan, applies only the accepted ids and returns the new profile. The caller validates and saves (`applicant.save`: atomic, D-74 comment backup, etag).

### 3.5 Degradation

| Case | Behaviour |
|---|---|
| Model down while the master is stale | The profile job still succeeds. Log: `application details check skipped: the AI model isn't running`. No proposals file. Card: §5 "unavailable" copy. |
| No `applicant.yaml` | GET returns `{state: "no_profile"}`. The panel is hidden (Application details shows "Start from the template"). |
| Proposals for an older resume (`resume_hash` ≠ current file) | GET returns `{state: "stale"}`. The panel says to re-read the resume. |
| Etag mismatch on POST | 409. UI: "Your details changed in another window. Reload to see the latest." |
| Saving yields validation errors | 422 with `errors` (should not happen; pinned). |
| Unknown accept id | Ignored and reported in `ignored` (pinned). |

## 4. API

- `GET /api/applicant/refresh` →
  - `{state: "ready", source_name, created_at, changes: [{id, list, op, index, before, after, note, default}], skills: {add: [..], not_on_resume: [..]}}`
  - or `{state: "none" | "stale" | "no_profile"}`
  - `before`/`after` are entry dicts (no `dates_text` in `after`). They are shown in the UI only and never logged.
- `POST /api/applicant/refresh` with `{etag, accept: [id]}` → the `GET /api/applicant` payload plus `{saved: n, ignored: [id]}`.
- `GET /api/profile` gains `years_experience: int|null` and `graduation: str|null` (read from the derived file, as today).

## 5. UI and copy (`design:ux-copy`)

**Q-73 summary card** (Resume view, it replaces the "Current profile" facts row):

- Title: `What we read from your resume`.
- Lines:
  - `{source_name} · read {date}` (file name only; no folders anywhere in the default view)
  - `Experience: {n} years` (`Less than a year` for 0)
  - `Graduation: {year}`
  - `{n} skills` (the first 12 as chips, then `and {k} more`)
  - `{t} job titles`
- After a successful job: `Resume read: {n} skills, {t} job titles.`
- The job log moves under a collapsed `<details><summary>Details</summary>` (JobStatus unchanged inside). On failure it opens by default, and the error sentence stays above it.
- `cmd_profile` prints paths relative to the project root (`data/profile.derived.yaml`), so even Details shows no absolute path.

**Refresh panel** (`ResumeRefresh.vue`):

- Heading: `Update your application details`.
- Intro: `Your resume has changes your application details don't. Pick what to update. Entries you edited yourself are never changed.`
- Row labels: `Add`, `Update`, `Remove: no longer on your resume`, `Remove: example from the template`, `Kept: you edited this`.
- Each row shows `employer · title · start – end` (before → after for updates).
- Skills row: `Add {n} skills from your resume: …`. Under Details: `Not on your resume, so not added: …`.
- Buttons: `Save {n} changes` (primary) and `Not now` (hides the panel until the next resume).
- Empty: `Your application details match your resume.`
- Stale: `This was checked against an older resume. Choose "Re-derive profile from the stored resume" to check again.`
- Unavailable: `Couldn't compare with your application details: the AI model isn't running. Start Ollama, then choose "Re-derive profile from the stored resume".`
- After a save: `Saved {n} changes. Check them in Application details.` (a link to that view).

## 6. Build steps (two lanes: P = Python 1–6, V = Vue 7–8 against the §4 contract)

1. `applicant.py`: `parse_resume_dates`, `skill_label` (+ shared cases). Verify: `python tests/run_tests.py -k test_applicant`.
2. `applicant.py`: `refresh_plan`, `apply_refresh`, `load_proposals` / `save_proposals` (atomic), plus a template reader. Verify: `-k test_applicant_refresh`.
3. `tailor_flow.py`: `ensure_master` (public `_load_master`), `profile_proposals`. Verify: `-k test_tailor_flow`.
4. `cli.py`: `profile --plan-applicant` (catches every exception and logs the skip line, so the profile job still succeeds), `applicant refresh-resume [--yes]`, relative paths in `cmd_profile`. `web/jobs.py`: the profile kind argv `["profile", "--refresh", "--plan-applicant"]`. Verify: `-k test_cli`.
5. `web/control.py profile_view`: `years_experience`, `graduation`. Verify: `-k test_web`.
6. `web/routers/applicant.py`: GET/POST `/applicant/refresh`. Verify: `-k test_web_applicant`, then the full suite `python tests/run_tests.py`.
7. `web/src/api.js` (`getResumeRefresh`, `saveResumeRefresh`), `ResumeRefresh.vue`, `Profile.vue` (summary card, Details collapse, panel). Verify: `cd web; npx vitest run`.
8. `applicantForm.js`: `skillLabel` cases shared with step 1 (fixture `tests/fixtures/skill_labels.json`, read by both suites). Verify: vitest plus `-k skill_label`.

**Files:** `src/jobscraper/{applicant,tailor_flow,cli}.py`, `src/jobscraper/web/{control,jobs}.py`, `src/jobscraper/web/routers/applicant.py`, `web/src/{api.js,applicantForm.js}`, `web/src/tabs/Profile.vue`, `web/src/components/ResumeRefresh.vue`, `tests/fixtures/skill_labels.json`, tests. No store or contracts change. No overlap with Q-75 lanes I/J.

**Tests:**
- R1 dates: each accepted form; `Present` gives `end None`; a year-only range and junk give `ok False`; `Expected May 2026` gives the end only.
- R2 an owner entry (no key, or `from_resume: false` and not a placeholder) is never changed, even when a proposal matches it (`kept`).
- R3 a placeholder entry is removed or replaced; a `from_resume: true` entry is updated; unread dates keep the old value only from a `from_resume: true` entry.
- R4 the location is never filled from `contact.*`; `languages` / `links` / `attested_skills` are byte-identical after apply.
- R5 skills: add-only, case-insensitive; implied skills land in `not_on_resume`; the template list is replaced.
- R6 change ids are stable; only accepted ids are applied; unknown ids are reported. R7 the order rule; an added entry has `from_resume: true` and no `dates_text`.
- R8 web: the GET states (ready / none / stale / no_profile); POST 409 on a stale etag; the saved file validates.
- R9 cli: the plan step fails (fake backend down) but the profile job exits 0 with the skip line; no absolute path in `cmd_profile` output.
- R10 vitest: summary card (no "/" or "\\" path in the default view), Details collapsed on success and open on failure, the panel ticks the defaults, the Save count, Not now.

READY TO BUILD: yes
