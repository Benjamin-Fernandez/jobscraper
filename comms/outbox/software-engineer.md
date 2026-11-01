# Outbox: software-engineer

Only `software-engineer` appends here (the Coordinator may mark entries resolved). Format: `instructions/04_team.md` §5.

<!--
### YYYY-MM-DD software-engineer → <recipient role | coordinator>
TYPE: handoff | request | question | blocker | review
RE: <requirement IDs / paths>
BODY: <concise message>
STATUS: open
-->

### 2026-11-01 software-engineer → coordinator
TYPE: handoff
RE: Q-03, F-06, D-56; cloud_port_report C-10, C-12 to C-18
BODY: Branch `eng/Q-03-ui-port` (from `personal`), one commit per item, `web/src/**` only.
- C-10 toast.js + ToastHost.vue copied from cloud 6be6e46 (personal had no own lines).
- C-13 jd.js + Inbox `descriptionBlocks`/`descriptionPreview` (no v-html). The `aria-live` on the whole description (audit G22) is left as is.
- C-12 Inbox keys s/a/x/o/j/k (cloud `onShortcut` guard), "Turn off" toggle in localStorage (try/catch), `aria-keyshortcuts`. Personal `/` search focus, its `aria-keyshortcuts="/"` and `<kbd class="key-hint">` kept.
- C-14 Applications: inline notes via `setApplicationStatus(job_id, row.status, {notes})`, sort Company A-Z / Recent activity, stage-count pills. No follow-up chip.
- C-15 Companies: "Edit list" / "Type or paste names" before "Clear list", textarea saved as companies.txt via the existing upload (`PUT /api/companies/list`). WatchedCompanies, CountPicker and the view switch untouched.
- C-16 setup.js + SetupChecklist.vue wrap the empty-Inbox state.
- C-17 page heads on Runs, Profile, Settings; `.badge-slot` only with a count; `.page-head + .section-title` CSS. "Read my resume again" wording not applied (personal Profile has no such button).
- C-18 `detailText` + 413/415/422 in `describeError`, `failureText` (used in TitleEditor, Profile, Companies), JobStatus says "cancelled" when `job.reason === 'cancelled'` (needs the C-4 engine half to set `reason`), boot screen with Retry in App.vue (network error only; an ApiError still goes to the tabs), `sgtClock()` in format.js.
EVIDENCE: `cd web; npx vitest run` -> 1 failed | 179 passed (180). The failure is intended: `web/tests/m16.test.js:278` expects `.jd-text` text to equal the raw description; it is now heading/list/paragraph elements (tester to update with the h1/ux1 ports). Scratch build (`vite build --outDir <scratch> --emptyOutDir`) succeeded.
KNOWN LIMITS: not exercised in a browser.
STATUS: open
