# Q-70 · UX audit of the Vue SPA (reviewer, 2026-11-07)

Read-only audit of `personal` @ 91ab3db. Skills: design-critique, accessibility-review (WCAG 2.2 AA).
Benchmarks: Linear (keyboard-first, quiet chrome), Huntr/Teal (pipeline tracker, follow-ups,
job card detail), GitHub (consistent page heads, `?` shortcut sheet).

Severity: **P1** hurts the daily loop (find, triage, apply, track) or fails WCAG AA · **P2** clear friction ·
**P3** polish. Effort: **S** < half a day · **M** about a day · **L** several days or backend work.

## 1. Baseline

- `cd web; npx vitest run` → `Tests  279 passed | 1 skipped (280)`, 17 files, 4.57 s.
- Scope read: all of `web/src` (7,466 lines) and the `web/tests` list. No browser, no server
  (the Coordinator does the visual pass). Contrast figures for G9–G12 are M18's measured values.
  They still hold because the colour tokens are unchanged (`style.css:23-43`, `107-128`).
- M18 was paused before its build, so almost none of G1–G42 landed. 1 is FIXED and 5 are CHANGED
  (partly done). The other 36 are still OPEN.
- What works and should stay as it is: the token sheet (`style.css:19-105`, one 4 px space scale,
  a 7-step type scale, 3 radii, 3 shadows, a complete dark set); TabLoading skeletons; the toast
  with pause and "Undo previous" (`toast.js:31-118`); Inbox single-key triage with an off switch
  (`Inbox.vue:261-316`); the SetupChecklist empty state; ApplicationDetails' 409/422 handling, focus
  on the error banner and the per-leaf `mergeEdits`.

## 2. M18 re-check (G1–G42)

| ID | State | Evidence (current code) |
|---|---|---|
| G1 | OPEN | `track()` moves `selectedId` before the await (`Inbox.vue:185-191`); the article is keyed `:key="selected.id"` (`:432`), so the pressed button is destroyed and focus falls to `<body>`. |
| G2 | OPEN | Every `.card-hit` is a tabbable button with no `tabindex` (`Inbox.vue:409-415`). |
| G3 | CHANGED | S/A/X/O/J/K keys, `aria-keyshortcuts` and an off switch shipped (`Inbox.vue:299-313`, `479-492`). Still missing: an undo key, a `?` sheet, Esc. |
| G4 | OPEN | "Choose runs…" is still an `<option>` (`RunSelector.vue:157`); selecting it emits `choose`, and the Inbox then navigates to `#/runs` (`Inbox.vue:252-255`). |
| G5 | OPEN | `@change="change(row, $event.target.value)"` writes on every change event (`Applications.vue:289-295`, `127-140`). |
| G6 | CHANGED | The toast now pauses on hover and focus, and keeps the previous Undo (`toast.js:38-118`, `ToastHost.vue:38-41`). Applications still has no way to remove a row: `untrackApplication` isn't imported (`Applications.vue:13`). |
| G7 | OPEN | `useJob` polls only while the tab that called it is mounted (`composables/useJob.js:4-6`, `67-70`). App.vue has no job watcher (`App.vue:11-197`). |
| G8 | OPEN | `stage = ref('all')` (`Applications.vue:32`). No Active chip (`:55-58`). |
| G9 | OPEN | Control borders still use `--border-strong` (`style.css:31`, `188`, `235`; `FieldInput.vue:413`). The status select's border is `transparent` (`Applications.vue:409`). |
| G10 | OPEN | Opacity fades: `.cards.ni .card-body` 0.65 (`Inbox.vue:586`), `.card.closed .card-body` 0.6 (`:615`), `.stage-n.zero` 0.5 (`Applications.vue:350`). |
| G11 | OPEN | The selected card uses a 35 % accent border on `--accent-soft` (`Inbox.vue:605-608`). |
| G12 | OPEN | There is no `::placeholder` rule anywhere in `style.css`. |
| G13 | OPEN | `--header-h: 3.5rem` is never changed at ≤ 640 px (`style.css:96`, `App.vue:364-369`). There is no `scroll-padding-top`. Things pinned at `top: var(--header-h)`: `WatchedCompanies.vue:349`, `Runs.vue:403`, and a new user, `ApplicationDetails.vue:428` (scroll-margin). |
| G14 | OPEN | `readNiOpen()` defaults to open (`Inbox.vue:85-86`). `neighbour()` walks every open group (`:157-161`). Caught-up needs `!untracked.length` (`:375`). |
| G15 | OPEN | `<component :is :key>` has no `<KeepAlive>` (`App.vue:259-269`). |
| G16 | OPEN | `emit('changed')` after every track (`Inbox.vue:193`) toggles `loading`, and `.split.refreshing` fades the list to 0.6 (`:386`, `:559`). |
| G17 | CHANGED | The list now scrolls in its own box (`Inbox.vue:565-567`). The sticky detail still has no max-height (`:617-621`), so its actions scroll away. |
| G18 | OPEN | `when()` prints "… UTC" and `shortDate()` takes the UTC day (`format.js:175-187`). |
| G19 | OPEN | `v-if="error"` replaces the list, and the split requires `!error` (`Inbox.vue:363-366`, `386`). |
| G20 | OPEN | The Runs tab never reads `props.error` and shows "No runs yet." (`Runs.vue:281-284`). The shell sets `error` (`App.vue:136`). |
| G21 | OPEN | `markNotInterested()` has no busy guard (`Inbox.vue:222-236`), and its button has no `:disabled` (`:475`). |
| G22 | OPEN | `<section class="why jd" aria-live="polite">` wraps the whole description (`Inbox.vue:515`). |
| G23 | OPEN | `select()` only sets `detailOpen` (`Inbox.vue:151-154`): focus doesn't move, nothing scrolls, no history entry. |
| G24 | OPEN | "{n} in Applications" (`Inbox.vue:330`) against the badge, which counts active only (`tabs.js:272`). |
| G25 | OPEN | The Found chip counts found + watched (`Companies.vue:47`), but the summary's Found counts found only (`:432`). |
| G26 | OPEN | "Clear list" still sits in the head in danger red (`Companies.vue:351`, `569`), behind `window.confirm` (`:256`). |
| G27 | OPEN | No reason is given for `aborted_unhealthy`, and the failed link's title still says "in run N" (`Runs.vue:343-351`). |
| G28 | CHANGED | A "Recent activity" sort was added (`Applications.vue:64-79`, `190-193`). There is still no age in stage and no follow-up cue (`:104-107`). |
| G29 | OPEN | The tab bar and the stage strip hide their scrollbars and give no overflow cue (`App.vue:309-316`, `Applications.vue:320-331`). |
| G30 | OPEN | No compact density or A–Z jump. A "your list" chip on every row (`WatchedCompanies.vue:270`). |
| G31 | OPEN | Run checkbox in a bare `<td>` (`Runs.vue:327-337`); title × (`TitleEditor.vue:261`); careers icon (`WatchedCompanies.vue:299`); new instance: chip × 1.4 rem (`FieldInput.vue:432-435`). |
| G32 | OPEN | `remove()` saves at once with no Undo (`TitleEditor.vue:111-116`). |
| G33 | OPEN | Only the Runs tab says a job is running (`Runs.vue:268-272`). |
| G34 | CHANGED | The no-jobs Inbox now shows SetupChecklist with buttons (`SetupChecklist.vue:75-79`). Caught-up has no next step (`Inbox.vue:375-379`). The Applications filtered-empty state has no Clear (`Applications.vue:232-235`). |
| G35 | FIXED | Runs, Profile and Settings now have `.page-head` (`Runs.vue:210-215`, `Profile.vue:202-207`, `Settings.vue:138-143`). |
| G36 | OPEN | Esc clears search only on Companies (`Companies.vue:456`). Not in the Inbox (`Inbox.vue:341`) or Applications (`Applications.vue:185`). |
| G37 | OPEN (part) | Raw counts (`Runs.vue:113-116`); "0.6 runs a day" (`Settings.vue:60`, `113`). The Profile "Re-derive" wording was kept on purpose (C-17 note, `tests/ux1.test.js:371`), so don't change it. |
| G38 | OPEN | `selected` falls back to `listed[0]` and is styled even on a phone (`Inbox.vue:104`, `406`). |
| G39 | OPEN | A row shows only the role (`Applications.vue:246-250`). `location` and `closed_at` are already in the payload (`store.py:1094-1103`). |
| G40 | OPEN | Dark mode is `prefers-color-scheme` only (`style.css:107`). |
| G41 | OPEN | No `content-visibility` on any long list (grep: 0 hits). |
| G42 | OPEN | Fixes point to `config/watchlist.yaml` (`WatchedCompanies.vue:38-42`). |

## 3. New gaps (surfaces M18 never saw, plus system polish)

**N1 · Profile → Application details: unsaved edits are lost on any navigation · P1 · S**
- Evidence: `dirty` (`ApplicationDetails.vue:49`) shows up only as a line of text (`:396`). Switching
  the Profile view unmounts the form (`Profile.vue:73-77`, `305-312`). So does a tab change
  (`App.vue:259-261`, no KeepAlive), and so does a reload. There is no `beforeunload`.
- Why it matters: this is a form of 16 groups that the auto-apply needs. Losing 10 minutes of typing
  to one click on "Inbox" breaks trust.
- Fix: keep the draft in `sessionStorage`, restore it with a banner, and add a `beforeunload` guard
  (lane D, D1).

**N2 · "Saved." hides the next edits · P2 · S**
- Evidence: `<span v-if="dirty && !note">You have unsaved changes.</span>` (`ApplicationDetails.vue:396`).
  `note` is cleared only by `load()` and `save()` (`:74`, `:158`). After one save, later edits show
  "Saved." and never the warning.
- Fix: tie both messages to `dirty` (lane D, D2).

**N3 · Save is always enabled, and there is no Discard · P3 · S**
- Evidence: `:disabled="saving"` (`ApplicationDetails.vue:398`). There is no way back to the file's
  values short of a reload.
- Fix: lane D, D3.

**N4 · On a 409, "Reload" throws away what was typed · P2 · S**
- Evidence: the conflict banner's Reload calls `load()` (`ApplicationDetails.vue:232`, `72-82`),
  although `reloadKeepingEdits()` with `mergeEdits` already exists (`:91-107`). The copy tells the
  owner to "make your change again" (`:227`).
- Fix: lane D, D4.

**N5 · The long form has no in-page navigation · P2 · M**
- Evidence: groups render one after another (`ApplicationDetails.vue:289-337`). Only the "Needed"
  list jumps to fields (`:245-255`). There is no group index and no progress per group.
- Fix (later): a sticky group index on wide screens (anchor links to `#g-<id>`) with each group's
  needed count.

**N6 · An unset yes/no field reads as "No" · P2 · S** (truthfulness, D-91)
- Evidence: the `bool` switch's text is `modelValue === true ? 'Yes' : 'No'` (`FieldInput.vue:224`).
  So null, which D-91 defines as "unknown", is shown as a "No" answer. The same happens on QuestionCard
  bool answers (`QuestionCard.vue:160-167` renders FieldInput).
- Fix: show "Not set" (lane D, D5). FieldInput is shared with QuestionCard (flagged).

**N7 · Questions that block auto-apply are invisible outside Profile → Application details · P2 · M**
- Evidence: the Profile tab has no badge (`tabs.js:276`). The count lives only in the inner view
  label (`Profile.vue:71`). Nothing in the Inbox or Applications says "3 applications are waiting on
  your answers".
- Fix (later, shell): a Profile badge for open questions plus missing fields, fetched by the shell.
  Needs a new count in `/api/stats` or an extra shell call.

**N8 · After Retry, a toast and then silence · P2 · S**
- Evidence: `retry()` shows "Started…" with no link and no progress (`QuestionsInbox.vue:146-152`).
- Fix: add a link to the job log (lane D, D6). G7/G33 then give the global progress.

**N9 · Dismissing a question is one click and can't be undone · P2 · L**
- Evidence: `dismiss()` posts at once, and its toast has no action (`QuestionsInbox.vue:114-123`).
  `api.js` has no un-dismiss call, and the button lives in QuestionCard (frozen for this work).
- Fix (later): an un-dismiss endpoint, an Undo in the toast, and a "Dismissed (n)" list.

**N10 · Loading states are inconsistent · P3 · S**
- Evidence: QuestionsInbox shows plain text (`QuestionsInbox.vue:189`), while the other tabs use
  `TabLoading`. SetupChecklist renders nothing until its 4 requests return (`SetupChecklist.vue:42`),
  so the empty Inbox is blank and then pops in.
- Fix: TabLoading in QuestionsInbox (lane D, D7). SetupChecklist comes later.

**N11 · Applications shows no auto-apply state · P2 · L**
- Evidence: rows carry only status, notes and events. The payload has no `apply_attempts` join
  (`store.py:1094-1103`). Dry-run done, stopped on a question and submitted are all invisible where
  the owner tracks applications.
- Fix (later, backend): add `last_attempt {state, mode, reason_code, at}` to `/api/applications`.
  Show it as a second pill on the row, linked to the Questions view when it stopped on a question.

**N12 · An application has no detail view · P2 · M**
- Evidence: an application row is a title link out plus a note (`Applications.vue:246-284`). The
  description, "Why it matches" and the facts exist only in the Inbox. `getPosting` is already
  available (`api.js:99`).
- Fix (later): an expandable row or a side panel that reuses the Inbox detail blocks. Better: first
  extract `JobDetail.vue` from `Inbox.vue:437-541`.

**N13 · Status and note changes reload the whole list, and errors show at the top · P3 · S**
- Evidence: `await load()` after every write (`Applications.vue:133`, `161`). The error is shown at
  `:204-207`, far from the row.
- Fix: folded into B3 (a toast near the action). An optimistic patch comes later.

**N14 · Control styles are defined three times, and the global selector misses types · P3 · S**
- Evidence: `style.css:231-249` covers number, text and search only. `FieldInput.vue:409-423` and
  `Applications.vue:392-400` re-declare border, radius and focus for email, url, date and textarea.
- Fix: extend the global selector (lane C, C6). Remove the duplicates later.

**N15 · Patterns are re-implemented per tab · P3 · M**
- Evidence: segmented controls ×4 (`Profile.vue:317-329`, `Companies.vue:313`,
  `Settings.vue:227-243`, `Applications.vue:320-344`). Confirms ×3 (`ApplicationDetails.vue:436`,
  `QuestionsInbox.vue:279`, `window.confirm` at `Companies.vue:256`). The danger button exists only
  scoped (`ApplicationDetails.vue:439`). Off-scale values: `0.7rem` and `4px` radius
  (`Inbox.vue:698-700`), weight 550 (`Applications.vue:383`).
- Fix (later): `Segmented.vue`, `InlineConfirm.vue` and a global `button.danger`.

**N16 · No global keyboard layer · P2 · M**
- Evidence: the only global key is `/` (`App.vue:153-162`). There are no go-to keys (`g i`, `g a`),
  no `?` sheet and no Ctrl+K palette. Linear and GitHub users expect all three.
- Fix (later): a shell shortcut registry that reuses the `onSlash` guard; `?` opens a dialog listing
  the shell keys plus the Inbox keys.

**N17 · Settings: notices that never clear, and arrow keys that save · P3 · S**
- Evidence: `cycleSaved` and `saved` persist (`Settings.vue:92`, `123`). The cycle radios save on
  `change` (`:157-165`), and arrow keys move the checked radio (3.2.2-like; reversible).
- Fix (later): clear the notice on the next edit; commit the cycle on Enter/blur as in B2.
  Settings.vue is also touched by Q-60.

**N18 · Heading levels are flat · P3 · S**
- Evidence: section titles are `h2`, siblings of the page `h2` (`Profile.vue:232`, `264`, `267`;
  `Settings.vue:145`, `179`; `Runs.vue:217`, `279`; `ApplicationDetails.vue:246`, `268`;
  `QuestionsInbox.vue:186`). WCAG 1.3.1 (minor).
- Fix (later): `h3` under the page `h2`. Check `tests/h1.test.js`.

**N19 · Developer is a top-level tab · P3 · S**
- Evidence: `tabs.js:279`. It adds to G29's crowding on a phone.
- Fix (later): move it behind Settings, or to the end with a quieter style.

**N20 · Write errors in the Inbox can't be dismissed · P3 · S**
- Evidence: `writeError` persists until the next action (`Inbox.vue:361`).
- Fix (later): add a close button.

## 4. Ranked table (value to find → triage → apply → track, divided by effort)

| # | ID | Title | Tab | Sev | Eff | Files touched |
|---|---|---|---|---|---|---|
| 1 | G1 | Focus after triage goes to the next card | Inbox | P1 | S | Inbox.vue |
| 2 | G2 | Roving tabindex on cards | Inbox | P1 | S | Inbox.vue |
| 3 | G5 | Status select commits only on pointer, Enter or blur, with Undo | Applications | P1 | S | StatusSelect.vue (new), Applications.vue |
| 4 | G8 | Active chip, the remembered default | Applications | P1 | S | applications.js (new), Applications.vue |
| 5 | G14 | Not interested folded; caught-up reachable | Inbox | P2 | S | Inbox.vue |
| 6 | G21 | Busy guard and cooldown on every triage action | Inbox | P2 | S | Inbox.vue |
| 7 | G16 | No fade after triage | Inbox | P2 | S | Inbox.vue |
| 8 | N1 | Unsaved application details survive navigation | Profile | P1 | S | ApplicationDetails.vue |
| 9 | G7+G33 | Shell job watcher and masthead pill | Shell | P1 | M | App.vue, useJob.js, JobPill.vue (new) |
| 10 | G9+G12 | Control-border token and placeholder colour | All | P1 | S | style.css |
| 11 | G4 | "Choose runs…" as a button | Inbox | P1 | S | RunSelector.vue |
| 12 | G13 | Phone header height and scroll padding | All | P1 | S | style.css |
| 13 | G28 | Age in stage and a "Follow up?" cue | Applications | P2 | S | applications.js, Applications.vue |
| 14 | G10+G11 | Contrast-safe quiet rows and the selected bar | Inbox, Apps | P1 | S | Inbox.vue, Applications.vue |
| 15 | G19 | A refresh error keeps the list | Inbox | P2 | S | Inbox.vue |
| 16 | N6 | Unset yes/no shows "Not set" | Profile/Questions | P2 | S | FieldInput.vue |
| 17 | N4 | 409 Reload keeps edits | Profile | P2 | S | ApplicationDetails.vue |
| 18 | N2 | "Saved." no longer hides edits | Profile | P2 | S | ApplicationDetails.vue |
| 19 | G6r | Remove from Applications (single-event rows) with Undo | Applications | P2 | S | Applications.vue |
| 20 | G15 | KeepAlive for Inbox and Applications | Shell | P2 | S | App.vue (+ hooks in A9, B10) |
| 21 | G22 | No aria-live on the description | Inbox | P2 | S | Inbox.vue |
| 22 | N8 | Retry toast links to the log | Profile | P2 | S | QuestionsInbox.vue |
| 23 | G39 | Location / closed on the application row | Applications | P3 | S | applications.js, Applications.vue |
| 24 | G23 | Phone: focus and scroll on opening a role | Inbox | P2 | S | Inbox.vue |
| 25 | G18 | Local time, not UTC | All | P2 | S | format.js, Applications/Profile tests |
| 26 | G17 | Detail max-height and sticky actions | Inbox | P2 | S | Inbox.vue |
| 27 | G24 | "already tracked" wording | Inbox | P2 | S | Inbox.vue |
| 28 | G34 | Clear filters in Applications; next step after caught-up | Apps, Inbox | P3 | S | Applications.vue, Inbox.vue |
| 29 | G36 | Esc clears search | Inbox, Apps | P3 | S | Inbox.vue, Applications.vue |
| 30 | G3r | Undo key `z` and a `?` sheet | Inbox | P2 | S | Inbox.vue |
| 31 | N3 | Save disabled when clean; Discard | Profile | P3 | S | ApplicationDetails.vue |
| 32 | N10 | Skeletons in Questions and SetupChecklist | Profile, Inbox | P3 | S | QuestionsInbox.vue, SetupChecklist.vue |
| 33 | G29 | Tab bar overflow cue | Shell | P2 | S | App.vue |
| 34 | N7 | Questions badge in the shell | Shell | P2 | M | App.vue, tabs.js, (API) |
| 35 | N12 | Application detail panel | Applications | P2 | M | JobDetail.vue (new), Inbox.vue, Applications.vue |
| 36 | N16 | Global go-to keys and a `?` sheet | Shell | P2 | M | App.vue, shortcuts.js (new) |
| 37 | N5 | Group index for the details form | Profile | P2 | M | ApplicationDetails.vue |
| 38 | G20 | Run-list error on Runs | Runs | P2 | S | Runs.vue, App.vue |
| 39 | G27 | Aborted run reason; failed-link title | Runs | P2 | S | Runs.vue |
| 40 | G32 | Undo on title remove | Profile | P2 | S | TitleEditor.vue |
| 41 | G25 | One set of counts on Your list | Companies | P2 | S | Companies.vue |
| 42 | G26 | Demote "Clear list"; inline confirm | Companies | P2 | S | Companies.vue |
| 43 | G31 | Touch targets ≥ 24 px | Runs, Companies, Profile | P2 | S | Runs.vue, TitleEditor.vue, WatchedCompanies.vue, FieldInput.vue |
| 44 | G30 | Compact density and A–Z jump | Companies | P2 | M | WatchedCompanies.vue |
| 45 | G37 | Thousands separators; Settings wording | Runs, Settings | P3 | S | Runs.vue, Settings.vue |
| 46 | G38 | No selected style on a phone list | Inbox | P3 | S | Inbox.vue |
| 47 | N17 | Settings notices clear; cycle commit | Settings | P3 | S | Settings.vue (Q-60 overlap) |
| 48 | N18 | Heading levels | several | P3 | S | Profile/Settings/Runs/ApplicationDetails/QuestionsInbox |
| 49 | N14 | Global control selector | All | P3 | S | style.css |
| 50 | N15 | Shared Segmented, InlineConfirm, danger | several | P3 | M | new components, 5 tabs |
| 51 | G40 | Theme switch | Settings | P3 | S | style.css, Settings.vue (Q-60 overlap) |
| 52 | G41 | `content-visibility` on long lists | Companies | P3 | S | WatchedCompanies.vue, Companies.vue |
| 53 | N19 | Developer tab placement | Shell | P3 | S | tabs.js |
| 54 | N20 | Dismissable write error | Inbox | P3 | S | Inbox.vue |
| 55 | N11 | Auto-apply state on application rows | Applications | P2 | L | store.py, web API, Applications.vue |
| 56 | N9 | Undo / list for dismissed questions | Profile | P2 | L | API, QuestionCard.vue, QuestionsInbox.vue |
| 57 | G42 | Fix failed companies inline | Companies | P3 | L | API, WatchedCompanies.vue |

## 5. Proposed build lanes

Rules for every lane:
- Work on your own branch from `personal`.
- No backend or API changes.
- **Don't touch `web/src/components/QuestionCard.vue`.**
- Run the full `cd web; npx vitest run` before handing off.
- Where a step needs the new `--control-border` token before lane C has merged, write
  `var(--control-border, var(--border-strong))`, so merge order doesn't matter.

**Concurrency (04_team.md §4.5, at most 3 engineer lanes):**
- Wave 1: A, B and D in parallel.
- Wave 2: C. Its C4 (KeepAlive) needs A9 and B10 merged first, or a cached Inbox keeps its
  window key listener and the keys fire on other tabs.

**File ownership (disjoint).** Shared test files are split by `describe` block, and the edit hunks
don't overlap:

| Lane | Owns |
|---|---|
| A Inbox flow | `web/src/tabs/Inbox.vue`, `web/tests/Inbox.test.js`, `web/tests/inbox-flow.test.js` (new). `web/tests/ux1.test.js`: only the blocks "Inbox: triage shortcuts" and "The job description, made readable". `web/tests/m17.test.js`: only "The Inbox badge". |
| B Applications | `web/src/tabs/Applications.vue` ⚑, `web/src/applications.js` (new), `web/src/components/StatusSelect.vue` (new), `web/tests/Applications.test.js`, `web/tests/applications-flow.test.js` (new). `web/tests/ux1.test.js`: only the blocks "Applications: notes" and "Applications: sort". |
| C Shell + tokens | `web/src/App.vue`, `web/src/style.css` ⚑, `web/src/composables/useJob.js`, `web/src/components/RunSelector.vue`, `web/src/components/JobPill.vue` (new), `web/tests/App.test.js`, `web/tests/m15.test.js`, `web/tests/shell-job.test.js` (new). |
| D Profile / forms | `web/src/components/ApplicationDetails.vue`, `web/src/components/FieldInput.vue` ⚑, `web/src/components/QuestionsInbox.vue`, `web/tests/ApplicationDetails.test.js`, `web/tests/QuestionsInbox.test.js`. |

⚑ flags:
- `Applications.vue`: int/Q-60-mail-status adds MailSuggestions above the stage strip. B keeps the
  strip markup and only edits the script, rows and CSS.
- `style.css`: Q-60 adds `--stage-assessment`. C's edits are additive token lines and new rules,
  plus one changed `border` value.
- `FieldInput.vue` is rendered by QuestionCard. D5 changes what bool answers show there; tell the
  lanes that own QuestionCard.

### Lane A · Inbox flow (G1, G2, G14, G21, G16, G10/G11, G19, G22, G23, G36, G24, plus the G15 hooks)

1. **A1 (G1).**
   - Add `const rootEl = ref(null)` on `<section class="inbox">`, and a helper
     `async function refocus() { await nextTick(); const id = selected.value?.id; if (!id) return; if (detailOpen.value && window.matchMedia('(max-width: 900px)').matches) document.getElementById('detail-title')?.focus(); else itemEls[id]?.focus() }`.
   - Give `#detail-title` the attribute `tabindex="-1"`.
   - In `track()`, `markNotInterested()`, `moveBack()` and `undo()`, capture
     `const hadFocus = document.activeElement === document.body || rootEl.value?.contains(document.activeElement) || !!document.activeElement?.closest?.('.toast')`
     before the first state change. Then call `if (hadFocus) refocus()` once `selectedId` holds its
     final value: after the await on success, and also in the catch branch.
2. **A2 (G2).**
   - On `.card-hit` add `:tabindex="selected && job.id === selected.id ? 0 : -1"`.
   - In `onListKey`, add `Home` (go to the first card) and `End` (go to the last), using the same
     select + focus as the arrows.
3. **A3 (G14).**
   - `readNiOpen()`: return `getItem(NI_KEY) === '1'`, and `false` in the catch.
   - `neighbour(job)`: walk `isDismissed(job) ? notInterested.value : visible.value` instead of
     `listed.value`.
   - Caught-up branch: change the condition to `v-else-if="!visible.length && !query.trim()"`
     (keep it after the SetupChecklist branch). Its second line becomes:
     `<p class="muted">Every new role is triaged.<template v-if="notInterested.length"> <button type="button" class="link show-ni" @click="niOpen = true">Show Not interested ({{ notInterested.length }})</button></template><template v-else> See <a href="#/applications">Applications</a>.</template></p>`.
   - Split condition: `untracked.length && (visible.length || (notInterested.length && niOpen))`.
4. **A4 (G21).**
   - Add `let lastActionAt = 0` and
     `function guard() { const t = Date.now(); if (busy.value || t - lastActionAt < 400) return false; lastActionAt = t; return true }`.
   - Make `if (!guard()) return` the first line of `track()`, `markNotInterested()` and `moveBack()`.
   - Wrap the bodies of `markNotInterested()` and `moveBack()` in
     `busy.value = true; try { … } finally { busy.value = false }`.
   - Add `:disabled="busy"` to the `.dismiss` and `.undismiss` buttons.
5. **A5 (G16).**
   - Add `const quiet = ref(false)`. Set `quiet.value = true` right before each `emit('changed')` in
     `track()` and `undo()`.
   - `watch(() => props.loading, (now, was) => { if (was && !now) quiet.value = false })`.
   - Split class: `refreshing: loading && !quiet`.
6. **A6 (G10, G11), styles only.**
   - Replace `.cards.ni .card-body, .cards.ni .mark { opacity: 0.65 }` with
     `.cards.ni .mark { opacity: 0.65 } .cards.ni .card .title { color: var(--text-2); font-weight: 500 }`.
   - Replace `.card.closed .card-body { opacity: 0.6 }` with
     `.card.closed .title { color: var(--text-2) }`.
   - `.card.selected .card-hit`: set
     `background: var(--accent-soft); border-color: transparent; box-shadow: inset 3px 0 0 var(--accent);`.
7. **A7 (G19).**
   - Take the error `<div>` out of the v-if chain (a plain `v-if="error"`). Its text becomes
     `jobs.length ? 'Could not refresh the shortlist: ' + error + '. Showing the last list loaded.' : 'Could not load the shortlist: ' + error`.
   - Start the chain at `<TabLoading v-if="firstLoad">`. The next branch becomes
     `<SetupChecklist v-else-if="!jobs.length && !error">`.
   - Drop `!error &&` from the split condition.
8. **A8 (G22).**
   - Remove `aria-live="polite"` from `.why.jd`.
   - Add inside it:
     `<p class="visually-hidden" role="status">{{ description?.state === 'error' ? 'Could not load the description.' : '' }}</p>`.
9. **A9 (G15 prep).**
   - Import `onActivated` and `onDeactivated`.
   - Add `onActivated(() => window.addEventListener('keydown', onShortcut))` and
     `onDeactivated(() => window.removeEventListener('keydown', onShortcut))`. Keep the
     mount/unmount pair; the browser drops duplicate adds.
10. **A10 (G23).**
    - In `select()`, when `open` is set and `matchMedia('(max-width: 900px)')` matches:
      `await nextTick(); window.scrollTo(0, 0); document.getElementById('detail-title')?.focus()`.
    - The Back button: `@click="detailOpen = false; nextTick(() => itemEls[selected?.id]?.focus())"`.
11. **A11 (G36, G24).**
    - On the search input: `@keydown.esc="query ? (query = '') : $event.target.blur()"`.
    - Subtitle: `{{ tracked }} already tracked` (keep the link).

Verify A:
- `cd web; npx vitest run tests/Inbox.test.js tests/inbox-flow.test.js tests/ux1.test.js tests/m17.test.js`,
  then the full suite.
- The new tests (mount with `attachTo: document.body`):
  - after a click on `.save`, `document.activeElement` is the next card's `.card-hit`;
  - only one `.card-hit` has `tabindex="0"`;
  - with localStorage empty, `.cards.ni` is absent and `.caught-up` shows when only dismissed roles
    remain;
  - two clicks on `.dismiss` within 400 ms call `dismissRole` once;
  - with `error` set and jobs present, `.split` still renders;
  - `.jd` has no `aria-live`.
- Manual on 8768: triage 5 roles by keyboard only, and focus never lands on `<body>`.

### Lane B · Applications (G8, G5, G28, G6r, G39, G10 part, G34 part, G36 part, plus the G15 hook)

1. **B1, new `web/src/applications.js`.** Pure helpers with no Vue:
   - `lastAt(row)`: move it here from `Applications.vue:69-71`.
   - `isActive(row)`: `!CLOSED_STATUSES.includes(row.status)`.
   - `daysSince(iso, now = Date.now())`: uses `utcMs`; returns `Math.floor((now - t) / 86400000)` or
     `null`.
   - `FOLLOW_UP_DAYS = 14`.
   - `needsFollowUp(row, now)`: `row.status === 'applied' && daysSince(lastAt(row), now) >= FOLLOW_UP_DAYS`.
   - `ageLabel(row, now)`: take the last event `e`; if it is missing, return `''`; else
     `${statusLabel(e.to_status)} · ${d === 0 ? 'today' : d === 1 ? '1 day' : d + ' days'}`.
   - `secondLine(row)`: `[cleanLocation(row.location), row.closed_at ? 'Posting closed' : ''].filter(Boolean).join(' · ')`.
   - `STAGE_KEY = 'jobscraper.applications.stage'`.
2. **B2 (G8).**
   - `stage = ref(readStage())`, where readStage returns the stored value, or `'active'` when there
     is none or storage throws. Add `watch(stage, v => { try { localStorage.setItem(STAGE_KEY, v) } catch {} })`.
   - `stages`: prepend `{ id: 'active', label: 'Active', n: inScope.value.filter(isActive).length }`
     before All.
   - `shown`: add the branch `stage.value === 'active' ? inScope.value.filter(isActive)`.
   - After `load()` succeeds: `if (!stages.value.some(s => s.id === stage.value)) stage.value = 'active'`.
   - CSS: `.stage.active[data-status='active']::after { background: var(--accent) }`.
3. **B3, new `web/src/components/StatusSelect.vue` (G5).**
   - Props `modelValue`, `options`, `disabled`, `label`. Emits `commit`.
   - Root `<label class="status-field">`, then a visually-hidden label span, then
     `<select class="status-select">` bound to `:value="pending ?? modelValue"` and
     `:data-status="pending ?? modelValue"`.
   - Script:
     - `let viaPointer = false`; `const pending = ref(null)`.
     - `@pointerdown`: `viaPointer = true`.
     - `@keydown`:
       - every key sets `viaPointer = false`;
       - Enter: `preventDefault(); flush()`;
       - Escape: `pending.value = null; e.target.value = props.modelValue`.
     - `@change`: `if (viaPointer) { viaPointer = false; pending.value = null; if (v !== modelValue) emit('commit', v) } else pending.value = v`.
     - `@blur`: `flush()`, where flush emits `commit` only when `pending !== null && pending !== modelValue`,
       then sets `pending = null`.
   - Move the `.status-select` CSS (`Applications.vue:405-418`) into this file. Use
     `var(--control-border, var(--border-strong))` for the border instead of `transparent` (G9).
   - In Applications.vue, replace `:287-298` with
     `<StatusSelect :model-value="row.status" :options="optionsFor(row)" :disabled="saving === row.job_id" :label="..." @commit="s => change(row, s)" />`.
4. **B4 (G5 feedback).**
   - In `change()`, keep `const before = row.status`.
   - On success:
     `showToast({ message: \`Moved to ${statusLabel(status)}: ${row.role ?? row.job_id}\`, action: { label: 'Undo', run: () => change({ ...row, status }, before) } })`.
   - Undo writes one more history event. This is accepted, the same way the server logs every change.
5. **B5 (G28).**
   - The `.updated` span shows `ageLabel(row)`, with `:title="when(lastAt(row))"`.
   - In `.role` after the title:
     `<span v-if="needsFollowUp(row)" class="pill follow-up">Follow up?</span>`.
   - CSS: `.follow-up { color: var(--warn); background: var(--warn-soft); margin-left: var(--space-2) }`.
6. **B6 (G6 rest).**
   - Import `untrackApplication`.
   - In the row's non-editing template, after `.note-edit`:
     `<button v-if="(row.events?.length ?? 0) <= 1" type="button" class="link row-remove" @click="removeRow(row)">Remove from Applications</button>`.
     Only rows with a single event qualify, so no history can be lost.
   - `removeRow`:
     `await untrackApplication(row.job_id); await load(); emit('changed'); showToast({ message: \`Removed ${row.role ?? row.job_id}\`, action: { label: 'Undo', run: async () => { await setApplicationStatus(row.job_id, row.status, { company: row.company, role: row.role, url: row.url, notes: row.notes }); await load(); emit('changed') } } })`.
   - Errors go to `error.value`, as in `change()`.
7. **B7 (G39).**
   - Under the title:
     `<p v-if="secondLine(row)" class="row-meta">{{ secondLine(row) }}</p>`.
   - CSS: `.row-meta { margin: 2px 0 0; font-size: var(--text-xs); color: var(--muted) }`.
8. **B8 (G34, G36, G10).**
   - In the filtered-empty block:
     `<p><button type="button" class="link clear-filters" @click="stage = 'all'; runFilter = 'all'; query = ''">Clear filters</button></p>`.
   - On the search input: `@keydown.esc="query ? (query = '') : $event.target.blur()"`.
   - `.stage-n.zero`: replace `opacity: 0.5` with `background: transparent`.
   - `.note-input` border: `var(--control-border, var(--border-strong))`.
9. **B9 (G15 prep).**
   - `let shownOnce = false; onActivated(() => { if (shownOnce) load(); shownOnce = true })`, so the
     list refreshes when a cached tab comes back.

Verify B:
- `cd web; npx vitest run tests/Applications.test.js tests/applications-flow.test.js tests/ux1.test.js`,
  then the full suite. Existing `select.setValue(...)` calls must first `trigger('pointerdown')`.
- The new tests:
  - `keydown` ArrowDown + `change`, with no pointerdown → `setApplicationStatus` is not called until
    `blur`;
  - pointerdown + change commits once, and the toast's Undo restores the status;
  - the default chip is Active, it excludes rejected, and the choice persists after a remount;
  - with `vi.setSystemTime`, applied 15 days ago shows `.follow-up`;
  - `.row-remove` shows only on single-event rows;
  - Clear filters resets all three filters.
- Manual: Tab to a status and press Down twice; nothing saves until Enter.

### Lane C · Shell + tokens (G7, G33, G9, G12, G13, G4, G15, G29 S, N14). Wave 2

1. **C1, `composables/useJob.js` (G7).**
   - Add the option `consume = true` to `useJob({ kind, onFinish, consume })`, and
     `const seen = consume ? seenRunning : new Set()`. Use `seen` in `accept()` and `track()`.
   - Add the module-level `const starters = new Set()` and
     `export function onJobStarted(fn) { starters.add(fn); return () => starters.delete(fn) }`.
   - In `track()`, when `started` is true: `for (const fn of starters) fn(next)`.
   - With the defaults, every existing caller behaves exactly as before.
2. **C2, App.vue (G7).**
   - `const shell = useJob({ consume: false, onFinish: j => { onChanged({ runs: j.kind === 'run' }); if (j.kind === 'run') showToast({ message: j.state === 'succeeded' ? 'Run finished. New roles are in the Inbox.' : failureText(j, 'The run stopped.'), link: { label: 'Open Runs', href: '#/runs' } }) } })`.
   - In onMounted: `shell.refresh()`, keep `const stop = onJobStarted(j => shell.track(j, { started: true }))`,
     and add a `visibilitychange` listener that calls `shell.refresh()` when the page is visible.
     Remove both in onBeforeUnmount.
   - The Runs tab's own onFinish also reloads. The double reload is harmless (`requestSeq` guards it).
3. **C3, new `components/JobPill.vue` (G33).**
   - Prop `job`. Render only when `job?.state === 'running'`:
     `<span class="job-pill" role="status"><span class="spinner" aria-hidden="true"/><a href="#/runs">{{ label }} running · {{ elapsed }}</a></span>`.
   - label: `{ run: 'Run', profile: 'Profile refresh' }[job.kind] ?? 'Job'`.
   - elapsed: `duration((now - utcMs(job.started_at)) / 1000)`, with a 15 s `setInterval` cleared on
     unmount.
   - Copy the spinner CSS from `Runs.vue:379-384`.
   - In App.vue, place `<JobPill :job="shell.job.value" />` in `.masthead-inner` after `.tabbar`, and
     hide its text at ≤ 640 px with the spinner kept.
4. **C4 (G15). Only after A9 and B9 are merged.**
   - Wrap the component:
     `<KeepAlive :include="['Inbox', 'Applications']"><component … /></KeepAlive>`.
   - SFC names come from the file names (Vue 3.5 `__name`).
5. **C5, style.css (G9, G12, G13). Additive.**
   - Add `--control-border: #878479;` in `:root` and `--control-border: #75757e;` in the dark block.
   - In the `select, input[…]` rule (`:231-238`), set `border: 1px solid var(--control-border)`.
   - Add `::placeholder { color: var(--muted); opacity: 1; }`.
   - Add `html { scroll-padding-top: calc(var(--header-h) + var(--space-2)); }`.
   - Add `@media (max-width: 640px) { :root { --header-h: 5.3rem; } }`.
6. **C6, style.css (N14). Additive.**
   - Append `textarea, input[type='email'], input[type='url'], input[type='date'], input[type='month']`
     to the selectors at `:172`, `:231`, `:239` and `:240`.
   - Add `textarea { padding: var(--space-2) var(--space-3); line-height: var(--leading); }`.
7. **C7, RunSelector.vue (G4).**
   - Root `<div class="run-selector">`; `const id = useId()`;
     `<label class="run-label" :for="id">Runs</label>`; the select gets `:id="id"`.
   - Remove the `choose` option and its branch in `onChange`.
   - After the select:
     `<button v-if="props.choosable" type="button" class="ghost choose-runs" @click="emit('choose')">Choose runs…</button>`.
   - Update `App.test.js:117` and `:349` to click `.choose-runs`.
8. **C8 (G29 S).**
   - In App.vue: `const moreRight = ref(false)` and
     `function measureTabs() { const el = tablistEl.value; if (el) moreRight.value = el.scrollLeft + el.clientWidth < el.scrollWidth - 1 }`.
   - Call it on the tablist's `@scroll`, on mount and on `resize`.
   - Class `{ 'more-right': moreRight }`, with CSS
     `.tablist.more-right { mask-image: linear-gradient(to right, #000 calc(100% - 2rem), transparent) }`.

Verify C:
- `cd web; npx vitest run tests/App.test.js tests/m15.test.js tests/shell-job.test.js`, then the full
  suite. `tests/Runs.test.js`, `tests/m16.test.js` and `tests/ui.test.js` must pass unchanged
  (useJob's defaults are unchanged).
- The new tests (with a fake `getCurrentJob`):
  - a job started via a tab's `track(..., { started: true })` shows `.job-pill`;
  - on finish, the shell calls `getShortlist` + `getStats`, and the toast says "Run finished";
  - the Runs tab's own `onFinish` still fires (`consume:false` doesn't steal it);
  - "Choose runs…" is a button, and arrow keys on the select never emit `choose`;
  - Inbox → Applications → Inbox keeps the search text.
- Manual on 8768 with a DB copy: start a dry run, switch to the Inbox, and the pill ticks. At the
  end, the toast shows and the badge updates without a reload. At 390 px, Tab to a control under
  the header and it stays visible.

### Lane D · Profile / forms (N1, N2, N3, N4, N6, N8, N10 part)

1. **D1 (N1).** In ApplicationDetails.vue:
   - `const DRAFT_KEY = 'jobscraper.applicant.draft'` and `const restored = ref(false)`.
   - `watch(draft, v => { if (!data.value) return; try { if (dirty.value) sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ etag: data.value.etag, base: data.value.profile ?? {}, draft: v })); else sessionStorage.removeItem(DRAFT_KEY) } catch {} }, { deep: true })`.
   - In `load()`, after `adopt(...)`: read and parse the key. If present:
     `draft.value = s.etag === data.value.etag ? s.draft : mergeEdits(s.base, s.draft, data.value.profile ?? {}); restored.value = true`.
   - Above "Your details":
     `<p v-if="restored && dirty" class="notice warn restored" role="status">Your unsaved changes are back. <button type="button" class="link" @click="discard">Discard them</button></p>`.
   - `beforeunload`: `const guard = e => { if (dirty.value) { e.preventDefault(); e.returnValue = '' } }`,
     added in onMounted and removed in onBeforeUnmount.
2. **D2 (N2).**
   - Change the save bar to `<span v-if="dirty" class="muted unsaved">You have unsaved changes.</span>`
     and `<p v-if="note && !dirty" …>`.
3. **D3 (N3).**
   - `discard()`: `draft.value = clone(data.value.profile ?? {}); errors.value = data.value.errors ?? []; restored.value = false; try { sessionStorage.removeItem(DRAFT_KEY) } catch {}`.
   - Save bar: `<button type="button" class="ghost discard" :disabled="saving || !dirty" @click="discard">Discard changes</button>`
     before Save.
   - Save becomes `:disabled="saving || (!dirty && data.file?.exists)"`, so a missing file can still
     be created.
4. **D4 (N4).**
   - For `conflict === 'changed'`, Reload calls `reloadKeepingEdits` (no other change). The copy
     becomes: "This file changed since you opened it, in another tab or by hand. Reload to take in
     the latest. What you typed here is kept."
   - `unreadable` still calls `load`.
5. **D5 (N6). FieldInput.vue (flagged).**
   - Bool text:
     `modelValue === true ? 'Yes' : modelValue === false ? 'No' : 'Not set'`.
   - On the span, drop `aria-hidden` when the value is unset:
     `:aria-hidden="modelValue === true || modelValue === false ? 'true' : undefined"`.
   - In the scoped rule (`:413`), set the border to `var(--control-border, var(--border-strong))`.
   - Raise the chip × target: `.chip-x { width: 1.5rem; height: 1.5rem; }` (24 px, G31).
6. **D6 (N8).**
   - Add `link: { label: 'Follow it on the Developer tab', href: '#/developer' }` to the retry toast
     (`QuestionsInbox.vue:147-151`).
7. **D7 (N10).**
   - Import `TabLoading`, and replace `QuestionsInbox.vue:189` with `<TabLoading v-if="loading" :rows="2" />`.

Verify D:
- `cd web; npx vitest run tests/ApplicationDetails.test.js tests/QuestionsInbox.test.js tests/Profile.test.js tests/applicantForm.mergeEdits.test.js`,
  then the full suite. Update the assertions at `ApplicationDetails.test.js:173`, `185`, `286`
  and `304` only if the D2/D3 semantics require it.
- The new tests:
  - edit a field, unmount, remount → the field holds the edit and `.restored` shows; Discard restores
    the file's value;
  - after a save, the next edit shows "You have unsaved changes." and hides "Saved.";
  - on a 409, Reload keeps a typed value on another leaf;
  - a `bool` with a null value renders "Not set";
  - the retry toast carries a `#/developer` link.
- Manual: type into Contact, click Inbox, come back, and the edit is restored.

## 6. Out of scope / later

- **Backend needed (L):**
  - N11: auto-apply state on application rows, which needs an `apply_attempts` join in
    `/api/applications`.
  - N9: un-dismiss a question (also needs QuestionCard, frozen).
  - G42: inline careers-URL fix.
  - N7: a Questions badge (needs a count in `/api/stats`, or a shell fetch of `questions` and
    `applicant` at boot).
- **Next wave (M):**
  - N12: application detail panel. Extract `JobDetail.vue` from `Inbox.vue:437-541` first.
  - N16: shell go-to keys and a `?` sheet.
  - N5: group index for the details form.
  - G30: Companies density and A–Z jump.
  - N15: shared Segmented, InlineConfirm and danger patterns.
- **Small, after the lanes:**
  - G18: local time. It changes `format.js` plus the assertions at `Applications.test.js:118` and
    `Profile.test.js:67`; do it after lanes B and D merge.
  - Also: G17, G20, G27, G32, G25, G26, G31 (the rest), G37 (Runs/Settings only), G38, N17 and G40
    (both overlap Q-60's Settings changes; wait for it), N18, N19, N20, G41, and G3r (undo key, `?`).
- **Not frontend:** the share of Inbox roles with no stored description (M18 note) is still a
  pipeline question.
- **Open questions for the Coordinator:**
  1. D1 keeps the unsaved applicant draft, including sensitive fields, in `sessionStorage` (this
     browser only, cleared when the tab closes). I recommend accepting it, because `data/applicant.yaml`
     on the same machine holds the same data. The alternative is to leave sensitive paths out and
     accept that those edits can be lost.
  2. B4 and B6 Undo write extra `app_events` rows (Undo is a new status change). Accept that, or
     add an "undo" endpoint later.
