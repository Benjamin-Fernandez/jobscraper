# UI polish brief: framework choice and five screen patterns (Q-118, stage A)

Researcher, 2026-11-12. All web sources were accessed on 2026-11-12 (IDs in §4). Tags: **[F]** fact from the cited source, **[F-repo]** read in this repo or the owner's screenshots, **[F-s]** seen only in a search snippet (earlier brief), **[I]** inference, **[O]** opinion, **[U]** unverified (listed in §5). Budget: 30 of 30 web calls used.
Prior art reused, not repeated: `docs/research/ux_accounts_brief.md` (job-tool benchmark: sources U2, U3, U9 below come from its §7), `docs/reviews/Q-100-ui-audit.md` (A15 density/hierarchy), `docs/architecture/q116_settings_design.md` (row/rail pattern; new screens should reuse its row, chevron, switch and "Saved" rules).

## 0 Why it "looks like an MD file" (diagnosis from the five 1440px screenshots) [F-repo]
1. **Numbers are monospace.** `.num` and number inputs use `--mono` (`web/src/style.css:325`, `:367`), so 433, 31 and 40,503 read as code. Skill chips use the same mono look.
2. **Lists are bullets and links are underlined blue text.** Profile job titles are a `<ul>` of 11 bullets; actions ("Open Applications", "and 40 more", "Show all details", "Careers") are underlined links rather than buttons or chips.
3. **No hierarchy between cards.** Every block is the same white box with a 1px border; all-caps 11px section labels ("PIPELINE", "RUN HISTORY") are the only headings; Overview leaves the right half empty.
4. **Native controls are unstyled.** Raw checkboxes in Runs, the large blue native `<select>` for status on every Applications row, and native sort selects.
5. **Fixable without a framework:** items 1 to 3 are CSS and markup [I]. A library helps only with item 4 and with the behaviour of new controls (chips input, menus, toasts) [I].

## 1 Part 1: framework decision

### 1.1 Facts per option (sizes are npm *unpacked* sizes: a ceiling on disk, not bundle weight)
| Option | Latest version, date | Licence | Size (unpacked) and deps | Health (GitHub, 2026-11-12) | Src |
|---|---|---|---|---|---|
| PrimeVue (styled or unstyled/pass-through) | 5.0.5, 2026-11-11 | **"SEE LICENSE IN LICENSE.md": commercial dual licence.** Free "Community License" only for orgs under $1M revenue, <5 developers, <10 employees, <$3M funding (individuals qualify); **annual renewal and a licence key**; a missing or expired key "may cause a license notice to display"; no extracting source | 9.45 MB, 8 deps incl. `@primeui/license-manager`; `sideEffects: ["*.vue"]` | Old repo `primefaces/primevue` (MIT) last push 2026-09-24; npm now points to `primevue-nextchapter`, which the public GitHub search does not return | N1, N2, N3, G1, G2 |
| Naive UI | 2.45.3, 2026-08-27 | MIT | 51.9 MB; 18 deps incl. `css-render` (CSS-in-JS), `date-fns`, `lodash`, `highlight.js`; `sideEffects: false` | 18,609 stars, 712 open issues, push 2026-10-26 | N4, N5, G1 |
| Element Plus | 2.14.8, 2026-11-06 | MIT | 44.8 MB; deps incl. `dayjs`, `lodash`, `@vueuse/core`, `@floating-ui/dom`, icons; global `theme-chalk` CSS is a side effect | 27,848 stars, **1,177 open issues**, push 2026-11-12 | N4, N6, G1 |
| Vuetify (now **v4**, not 3) | 4.3.3, 2026-11-09 | MIT (npm; GitHub reports NOASSERTION) | **78.4 MB**; dep `@vuetify/v0`; peer `vite-plugin-vuetify`; side effects `*.sass, *.scss, *.css, *.vue` | 41,037 stars, 326 issues, push 2026-11-11 | N4, N7, G1 |
| shadcn-vue (copy-in components on Reka UI + Tailwind) | CLI 2.9.0, 2026-10-28 | MIT | no runtime package of its own; adds `reka-ui` plus Tailwind 4.3.5 (2026-11-06, MIT) [Tailwind dependency: U] | 10,805 stars, 143 issues, push 2026-11-03 | N8, N10, G1 |
| **Reka UI** (ex Radix Vue), headless | 2.11.0, 2026-10-05 | MIT | 9.18 MB / 3,081 files; 9 deps (`@floating-ui/vue`, `@vueuse/core`, `@tanstack/vue-virtual`, `@internationalized/*`, `aria-hidden`, `defu`, `ohash`); peer `vue >= 3.4`; **`sideEffects: false`** | 6,951 stars, 228 issues, push 2026-11-12 | N8, N9, G1, W1 |
| Headless UI for Vue | **1.7.23, 2024-09-09** (React got 2.2.10 on 2026-04-07) | MIT | 0.60 MB; 1 dep | repo 28,824 stars, push 2026-04-13; Vue build not released for 26 months | N8, N11, G1 |
| Ark UI (Vue) | 5.40.0, 2026-10-29 | MIT | 5.17 MB; **69 deps** (68 `@zag-js/*` at 1.47.0); peer `vue >= 3.5`; `sideEffects: false` | 5,464 stars, **9 open issues**, push 2026-11-12 | N8, N12, G1 |
| No library (strengthen tokens) | n/a | n/a | 0 KB added | own code | F-repo |

Reka UI's own claims [F, W1]: components "come unstyled"; it handles "aria attributes, keyboard navigation, and focus management"; styling with "any CSS solution (vanilla CSS…)"; teams can "integrate them progressively"; unused components "won't add to your bundle size thanks to tree-shaking"; an `asChild` prop exists.

### 1.2 Scores (1 = poor, 5 = best) [O, reasons tagged]
| Option | a. Incremental adoption | b. DOM / test churn | c. Look and our tokens | d. Weight for ~8 components | e. A11y of needed parts | f. Health and licence | Sum |
|---|---|---|---|---|---|---|---|
| PrimeVue 5 styled | 2: its theme layer styles every component [U] | 2: own markup and class names | 3: themeable via its preset, not our tokens directly [U] | 3 | 4 [U] | **1: commercial key, annual renewal, public repo ships the bundle** | 15 |
| PrimeVue unstyled + pass-through | 3 | 2 | 3: we write every style anyway | 3 | 4 [U] | 1 (same licence) | 16 |
| Naive UI | 2: CSS-in-JS injects styles at runtime; theme through a JS overrides object [I from `css-render` dep] | 2 | 3: Naive's look, tokens mapped by hand | 2: heavy deps | 3 [U] | 4 | 16 |
| Element Plus | 2: global theme CSS | 2 | 2: distinct "admin" look | 2 | 3 [U] | 3: 1,177 open issues | 14 |
| Vuetify 4 | 1: Material look, Sass, app wrapper expected [U] | 1 | 2 | 1: largest package | 4 [U] | 4 | 13 |
| shadcn-vue | 2: brings Tailwind and its base reset, which would restyle the existing app [U] | 3: we own the copied source | 5: best-looking defaults | 4 | 4 (Reka inside) | 4 | 22 |
| **Reka UI alone** | **5: per component, no global CSS, styles via our classes** [F, W1] | 3: new DOM for checkbox/select/menus [U] | 4: unstyled, so our tokens are the only source of truth | 4: tree-shaken, `sideEffects: false` [F] | 4: WAI-ARIA patterns [F, W1]; no data table, no DnD | 4: MIT, active | **24** |
| Headless UI Vue | 4 | 3 | 4 | 5 | 3: small set, no number field, tags input or toast [U] | **2: no Vue release since 2024-09-09** [F] | 21 |
| Ark UI | 4 | 3 | 4 | 3: 69 deps, tree-shaken [F] | 4 [U] | 5: MIT, 9 open issues | 23 |
| No library | 5 | **5: no DOM change unless we choose** | 3: only as good as our CSS | 5 | 3: we own every ARIA pattern | 5 | 23 |

### 1.3 Supporting pieces
| Piece | Facts | Verdict |
|---|---|---|
| Drag and drop | **Native HTML5 DnD**: 0 KB. **vue-draggable-plus** 0.6.1, 2026-01-11, MIT, wraps SortableJS 1.15.7 (2026-02-11, MIT); repo last push 2026-03-13 [F, N13, G2]. **@formkit/drag-and-drop** 0.7.0, 2026-11-07, MIT, 1,952 stars, 5 issues [F, N13, G2]. **@atlaskit/pragmatic-drag-and-drop** 4.0.0, 2026-09-24, Apache-2.0, 12,796 stars [F, N13, G2]. Sizes not fetched [U]. Atlassian's guidance: "Always provide alternatives to dragging" via a button that opens an inline menu of outcomes; it advises **against** arrow-key dragging; announce "the name of the item being moved, as well as its old and new position" in a live region; return focus to the trigger [F, W2] | **Native DnD** for "drop a row on a stage tab" (one drop target type, no sorting) plus a **"Move to…" menu** as the keyboard path (Reka DropdownMenu). Adopt @formkit/drag-and-drop only if sortable lists or a board arrive later [O] |
| Icons | The app's `Icon.vue` has about 20 hand-drawn icons [F-repo]. Lucide's Vue package is now **`@lucide/vue` 1.72.0, 2026-11-11, ISC**; `lucide-vue-next` did not appear in npm search [F, N14]; repo 25,715 stars [F, G1] | Keep `Icon.vue`; copy the few Lucide paths needed into it (ISC: keep the notice) [O]. Adding `@lucide/vue` is fine later if per-icon imports tree-shake [U] |
| Typeface | `@fontsource-variable/inter` 5.3.0, 2026-07-19, **OFL-1.1** [F, N15]; `inter-latin-wght-normal.woff2` = **48,256 bytes**, latin-ext 85,068, opsz axis 72,920 [F, N16]. Vite bundles imported woff2 into `static/`, so it works offline [I] | Optional. **The mono-number look is fixed without a new font:** set `.num` to the body font with `font-variant-numeric: tabular-nums` [I]. Inter (latin, one variable file, ~48 KB) is worth it only if the owner wants a less "Windows" feel [O]. Whether Segoe UI Variable has a `tnum` feature is [U]; Inter does [U] |
| Utility CSS | Tailwind 4.3.5, 2026-11-06, MIT, 98,583 stars [F, N10, G2]; UnoCSS 66.12.0, 2026-10-26, MIT [F, N14]; Open Props: MIT, 5,571 stars, push 2026-10-11, npm version not fetched [F, G2; U] | **Reject all three now.** 572 lines of tokens already do the job; a utility layer means a second styling system and (Tailwind) a base reset [U] over 4,100 lines of scoped CSS [O]. Open Props is worth reading for its shadow and easing scales, then copy values into `style.css` (learn) [O] |

### 1.4 Recommendation: Reka UI, headless, per component, on top of a token "polish pass"
Why [I]: highest score on (a) and (c), MIT and active (f), and it never ships a look that competes with `style.css`, so the Settings row/rail pattern (Q-116) stays the visual base. It covers the behaviour that is costly to hand-write (tags input, menus, number field, toast, dialog focus) while tables, chips, badges and the funnel stay plain CSS.
**Risks for the ~1,000 DOM tests** [I unless tagged]: (1) Reka Checkbox renders a `button role="checkbox"`, not `input[type=checkbox]`, so tests using `setValue(true)` or `input[type=checkbox]` break [U]; (2) Select, DropdownMenu, Dialog and Toast teleport into `document.body`, so `wrapper.find` misses them unless tests mount with `attachTo` or stub Teleport [U]; (3) floating positioning may need `ResizeObserver` and pointer-event shims in jsdom [U]; (4) text, roles and accessible names stay ours, so role/text queries mostly survive; class queries survive only if we pass our class names through [I]. Mitigation: one component at a time, the tester updates that screen's tests in the same lane, `asChild` where it keeps our element [F, W1].
**First three steps:** (1) Polish pass with no dependency: body-font tabular numerals, `.chip`, `.badge`, `.table`, `.segmented`, `.kpi` primitives and an elevation scale in `style.css`; buttons instead of underlined action links; stop at the Overview screen and let the owner react. (2) Add `reka-ui`; wrap it in thin app components (`ui/Segmented.vue` on ToggleGroup, `ui/NumberField.vue`, `ui/TagInput.vue` on TagsInput, `ui/MoveMenu.vue` on DropdownMenu, `ui/Toast.vue`) styled only by tokens and `data-state` attributes; pilot on Runs; record the gzip delta of `npm run build` before and after. (3) Roll out screen by screen: Applications (stage tabs, Move to menu, native DnD, toast with Undo), Profile (TagsInput), Companies (table, filter chips), Overview (pure CSS).
**Do NOT:** rewrite the app or all tests at once; add Tailwind, a styled kit, or any library global CSS or reset; load fonts or icons from a CDN; adopt PrimeVue 5 (licence key, annual renewal) [F, N3]; swap every checkbox and select globally in one change; rename visible labels, roles or classes that tests use without the tester in the lane; touch Settings (Q-116 just shipped).

### 1.5 Fallback: no library, strengthen the token system
Use it if the Reka pilot breaks more than about one screen's tests or adds more than ~40 KB gzip [O threshold]. **Steps:** (1) the same polish pass; (2) hand-build Segmented (`role="radiogroup"`), Chip/TagInput (input plus removable buttons), MoveMenu (menu button pattern), Toast region (`role="status"`) and table styles; (3) native DnD plus the Move to menu. **Do NOT:** grow our own date pickers, comboboxes or virtual lists; at that point switch to Reka (or Ark UI, the next-best headless option) instead [O].

## 2 Part 2: patterns for the five screens (each line is buildable; sources in §4)

### 2.1 Profile (parsed resume)
1. Lead with what was read, not the file: header "From your resume · read 2 Nov" with Replace / Re-read buttons in one compact Q-116-style row; drop "resume.pdf" and the big dashed drop zone once a resume exists (keep the drop zone for first run) [F-repo; O]. Simplify's profile is organised by sections (Profile, Personal Info, Job Preferences), not by file [F, U2].
2. Two cards side by side at ≥ 900px, stacked at 390px: **Skills (52)** and **Target job titles (11)**, each with a count in the header and chips in the body font, not mono [O].
3. Chips are editable in place with a TagsInput: Enter adds, × or Backspace removes, each chip a 44px target on touch; titles become chips, not bullets [O].
4. Show the first 12 skills, then a **button** "Show all 52" (`aria-expanded`), never an underlined "and 40 more" link [O]. Group skills under small headings (Languages, Frameworks, Tools, Other) only if the term table can supply the category [I].
5. A re-read **proposes** additions as dashed "suggested" chips with Accept / Dismiss; it never silently replaces edits. Simplify: re-parsing adds entries and the user reviews suggestions first [F, U2].

### 2.2 Companies (import of ~560 names)
1. One **segmented progress bar** under the title, read left to right: In your list 559 → Found 433 → Readable automatically 394 → Checked this cycle n → Failed 39. Each legend item is a filter button (`aria-pressed`) with its count, replacing the three big number boxes [O; counts F-repo].
2. **Status filter chips** above the table: All · Readable · Not checked this cycle · Failed · Not found, each with a count; the "Watchlist and your list" select goes [O].
3. A real **table** instead of 70px card rows: Company · Job board · Open roles (right-aligned, tabular) · Last checked · Status badge · "Careers ↗" as the last-column row action. Primer: right-align numbers; row actions go in the last column, several actions go in a dropdown; one column sorted by default [F, W4, W5].
4. **Compact density by default** for 433 rows (Primer offers Condensed / Normal / Spacious) and sortable column headers replace the A–Z letter strip [F, W4; O].
5. **Failed view groups by reason** ("Careers page not found 12 · Blocked by the site 8 · Timed out 5") with the reason as a second line under the badge, so "why" is one glance away [O; Q-100 A15].

### 2.3 Runs (start a run, run history)
1. Start card: a **segmented control** "30 · 50 · 100 · 200 · All 433 · Custom"; Custom reveals the number field; the primary button carries the count ("Check 100 companies") and the time estimate sits under it; Dry run becomes a Q-116 switch row with On/Off text, not a raw checkbox [O; F-repo].
2. History table: numbers right-aligned in body-font tabular numerals; **no "–" placeholders**: Primer warns that placeholder characters in empty cells create "a weird experience" for screen readers, so leave the cell empty [F, W5]; status badge = icon + word.
3. Selection like Linear: X selects the focused row, Shift-click selects a range [F, W3]; the checkbox column has a 44px hit area and stays faint until hover, focus or a first selection [O]. A plain row click opens the run's details, so selection never happens by accident [O].
4. **Bulk-action bar appears only when ≥ 1 run is selected** ("2 runs selected · Show their roles in Inbox · Clear"), sticky at the bottom of the table; it replaces today's always-visible "Choose runs" card with its disabled button [O; F-repo].
5. Loading: skeleton rows that match the real columns so row height doesn't jump [F, W5].

### 2.4 Applications (tracker)
1. **Stage tabs with counts** (All, Active, Applied, Interviewing, Offer, Rejected); Saved, Assessment and Withdrawn go into a "More" menu or a filter so the bar fits 390px [O]. Careerflow uses Saved, Applied, Interview, Offer [F, U19 via ux brief].
2. **Drag a row onto a stage tab**: while dragging, tabs show a drop outline; on drop, a toast "Moved 'SRE · Flowdesk' to Interviewing · Undo". The keyboard path is a "Move to…" menu button on each row named after the item; announce old and new stage in a live region; focus returns to the trigger [F, W2]. Replace the large native status `<select>` on every row with a compact status pill that opens that menu [O; F-repo].
3. **List, not kanban, by default**: long titles, 34 active rows and a 390px phone suit a list [I]. Linear keeps board and list as two layouts of one view with shared ordering and "Show empty groups" off [F, W3]; Huntr is board-first with stage columns [F-s, U9]. Offer a board toggle later (ux brief pattern 19).
4. **Auto-submitted applications**: while running, the row shows an "Applying…" badge with the current step ("Filling page 2 of 4") and cannot be dragged; pin it to the top of Active. When done: "Applied automatically" source badge that opens the fill audit (ux brief patterns 17, 18); a dry run ends as "Ready for you to review" [O].
5. One row per application (company avatar and name inside the row) instead of company group cards; Add note / Details / Remove go behind a "⋯" menu (Primer: several row actions → dropdown) [F, W4]; keep the "Follow up?" badge [O].

### 2.5 Overview (dashboard)
1. **KPI row of four cards**: New roles to triage (101), Active applications (34), Interviews (3), **Response rate 72%** with "81 of 113 heard back" as its caption and the definition in a tooltip. Response rate belongs here, not as a sentence under the pipeline [O; F-repo].
2. **Clickable pipeline**: one horizontal segmented bar (Saved → Applied → Assessment → Interviewing → Offer, Closed set apart and muted); each segment is a link to Applications filtered to that stage (`#/applications/<stage>`) [O]. Zero stages stay visible but muted.
3. **Fill the dead space with a 12-column grid**: left 8 columns = "To do" list (Triage 101 roles → Open Inbox; Follow up 30 → Open list) and the pipeline; right 4 columns = "Last run" and "Past 7 days" (one card with four inline stats, not four big boxes of zeros) [O; F-repo].
4. Surface problems on Home only when they exist: Stripe's Home shows analytics and "surfaces important notifications, like unresolved disputes" [F, W6]; ours = a "Needs attention" strip (Gmail, 39 failed companies, local model down) linking to the fix [O].
5. Stripe lets the owner add or remove Home widgets [F, W6]; not needed for one user, so a fixed layout is fine [O].

## 3 Reuse verdicts (github-gem-seeker pass)
Reka UI: **reuse** (dependency). Ark UI: **learn** (second choice). shadcn-vue: **learn** (copy visual ideas such as spacing, borders and badge styles into our tokens; do not install Tailwind). Open Props: **learn** (shadow and easing values). PrimeVue 5: **reject** (licence). Naive UI, Element Plus, Vuetify 4: **reject** (global look, weight). Headless UI Vue: **reject** (stalled Vue release). @formkit/drag-and-drop: **learn** (if sorting is ever needed). `@lucide/vue`: **adapt** (copy paths, ISC notice).

## 4 Sources (all accessed 2026-11-12)
N1 https://registry.npmjs.org/-/v1/search?text=primevue&size=2 · N2 https://registry.npmjs.org/primevue/latest · N3 https://unpkg.com/primevue@5.0.5/LICENSE.md · N4 https://registry.npmjs.org/-/v1/search?text=naive-ui%20element-plus%20vuetify&size=20 · N5 https://registry.npmjs.org/naive-ui/latest · N6 https://registry.npmjs.org/element-plus/latest · N7 https://registry.npmjs.org/vuetify/latest · N8 https://registry.npmjs.org/-/v1/search?text=reka-ui%20shadcn-vue%20headlessui%20ark-ui&size=25 · N9 https://registry.npmjs.org/reka-ui/latest · N10 https://registry.npmjs.org/-/v1/search?text=tailwindcss%20open-props%20inter%20lucide-vue-next&size=30 · N11 https://registry.npmjs.org/@headlessui/vue/latest · N12 https://registry.npmjs.org/@ark-ui/vue/latest · N13 https://registry.npmjs.org/-/v1/search?text=vue-draggable-plus%20formkit%20drag-and-drop&size=25 · N14 https://registry.npmjs.org/-/v1/search?text=lucide-vue-next%20open-props%20unocss&size=25 · N15 = N10 · N16 https://data.jsdelivr.com/v1/packages/npm/@fontsource-variable/inter@5.3.0?structure=flat
G1 https://api.github.com/search/repositories?q=repo:primefaces/primevue+repo:tusen-ai/naive-ui+repo:element-plus/element-plus+repo:vuetifyjs/vuetify+repo:unovue/reka-ui+repo:unovue/shadcn-vue+repo:tailwindlabs/headlessui+repo:chakra-ui/ark+repo:lucide-icons/lucide · G2 same API for Alfred-Skyblue/vue-draggable-plus, formkit/drag-and-drop, atlassian/pragmatic-drag-and-drop, SortableJS/Sortable, fontsource/font-files, rsms/inter (OFL-1.1), tailwindlabs/tailwindcss, unocss/unocss, argyleink/open-props, primefaces/primevue-nextchapter (not returned)
W1 https://reka-ui.com/docs/overview/introduction · W2 https://atlassian.design/components/pragmatic-drag-and-drop/accessibility-guidelines · W3 https://linear.app/docs/board-layout · W4 https://primer.style/product/components/data-table/ · W5 https://primer.style/product/components/data-table/guidelines/ · W6 https://docs.stripe.com/dashboard/basics
From `ux_accounts_brief.md` §7 (accessed 2026-11-11): U2 https://help.simplify.jobs/articles/8396475-editing-your-profile-after-onboarding · U9 https://help.huntr.co/en/articles/13413245-the-job-board (snippet only) · U19 https://help.careerflow.ai/en/articles/10723830-getting-started-with-careerflow-ai

## 5 Unverified or inferred
- Bundle weight (gzip) for the handful of components of any library: not measured; unpacked sizes only. Measure with `npm run build` in the pilot.
- Reka component coverage (Checkbox, ToggleGroup, Tabs, NumberField, TagsInput, DropdownMenu, Dialog, Toast) is from memory; W1 names no components. Its Checkbox markup, Teleport behaviour and jsdom needs (test risks 1 to 3) are unverified.
- PrimeVue: pass-through / unstyled mode details, accessibility quality, theme behaviour; whether PrimeVue 4.x (MIT) is still maintained; whether `primevue-nextchapter` is private.
- Naive UI runtime style injection (inferred from the `css-render` dependency); Vuetify's app-wrapper requirement; Element Plus and Ark UI accessibility quality.
- shadcn-vue's requirement for Tailwind and the effect of Tailwind's base reset on existing CSS.
- Sizes of the DnD libraries, Open Props and `@lucide/vue`; Open Props' npm version and date; whether `lucide-vue-next` is deprecated (it only did not appear in search) and whether `@lucide/vue` tree-shakes per icon.
- Whether Inter and Segoe UI Variable expose `tnum`; whether jsdom implements `DataTransfer` for native DnD tests.
- Huntr board details (snippet only, from the earlier brief). No source was fetched for segmented progress bars, hover-revealed checkbox columns or KPI-card layouts; those observations are opinion.
- Linear does not state outright that dragging a card changes its status (W3); assumed from the layout.
