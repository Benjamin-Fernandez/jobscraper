# Q-118 design: UI polish wave (Overview, Applications, Runs, Companies, Profile)

Architect, 2026-11-12. Fast track. Inputs: `docs/research/ui_polish_brief.md` (cited as B§x), `q116_settings_design.md` §3/§5/§6 (the row/rail look these tabs now share), `apply_queue_design.md` (Q-120, cited as AQ§x, draft), the five 1440px screenshots and the code. Status: **READY** after the Coordinator's review; Foundation (§1) also goes to the shell's owner.

## 0. Decisions and owner items
Fixed by the Coordinator (not reopened): D-206 (no kit, no new dependency; hand-built primitives, B§1.5; body font with tabular numerals), the stage strip, native DnD + "Move to…", the queue surfaces (AQ§7). Mine: **every new global class is prefixed `ui-`** (`.badge`, `.card`, `.check` and `.table` already exist in App.vue, Inbox.vue, FieldInput.vue and Runs.vue, so unprefixed names would collide); menus render **inline, never teleported** (tests find them with `wrapper.find`); **no backend work package** (every number comes from an existing endpoint or from Q-120's).

| Owner item | Change | § |
|---|---|---|
| 1 Profile: no resume title; skills and titles look better | File-name line and the big drop zone are gone once a resume exists; a compact "From your resume" header with Replace / Re-read; Skills and Job titles become two side-by-side chip cards; the duplicate bullet list of titles goes | 6 |
| 2 Companies: drop "Watchlist and your list"; show the list against what can be scanned and what was scanned | The source select, the two-view toggle and the three number tiles go; a funnel sentence plus a segmented bar whose legend is the filter; one sortable table | 5 |
| 3 Runs: count control and checkboxes look cheap | `.ui-segmented` count control ("All" without a squeezed number, Custom reveals the field), the start button carries the count, Dry run is a switch, a styled real checkbox, a bulk bar only when something is selected, badges instead of lower-case pills | 4 |
| 4 Applications: All first; remove Saved/Withdrawn/Assessment; DnD onto tabs; auto-apply shows at once | Tabs All · Active · Applied · Interviewing · Offer · Rejected; one-row list with a status pill that opens "Move to"; drag a row onto a tab; queue chips on `to_apply` rows; "Applied automatically" badge | 3 |
| 5 Overview: response rate line looks cheap; empty space; clickable pipeline | KPI row (response rate is a KPI card); 12-column grid (To do + Pipeline left, Last run + Past 7 days right); pipeline segments link to `#/applications/<stage>` | 2 |
| 6 A framework for a professional look | D-206: a stronger token set + 7 small primitives (§1); Reka UI stays the recorded later pilot | 1, 11 |

## 1. Foundation (`web/src/style.css`, `web/src/ui/`, `stages.js`, `Icon.vue`; lane L0)
**Untouched:** every protected token and class named by the shell's owner keeps its name; `button` white-space, the 390px bottom-bar spacing, `.state-chip`, `.notice`, `.empty`, `.pill[data-status]`, `.tag`, `button.link` (still used in sentences and in Settings), `.section-title` (still used elsewhere; these five tabs stop using it for card headings).
**Value changes (protected names, new values):**
- `.num` and `input[type='number']`: `font-family: inherit; font-variant-numeric: tabular-nums lining-nums;` (`.mono` keeps `--mono`). This is the main "MD file" fix (B§0.1).
- `.surface`: shadow `--shadow-sm` (lighter cards; `--shadow` stays for raised cards).
- `.chip`: `line-height: 1.6; padding: 2px var(--space-2); border-radius: var(--radius-pill); font-size: var(--text-sm)` at ≥ 641px (`--text-xs` stays below).
**New tokens (light and dark use existing colour tokens only, so no new colour pair):** `--text-3xl: 2rem` (KPI values) · `--weight-medium: 500`, `--weight-semibold: 600`, `--weight-bold: 650` · `--leading-tight: 1.25` · `--radius-pill: 999px` · `--shadow-md: 0 4px 16px rgba(23,23,26,.10), 0 1px 3px rgba(23,23,26,.06)` (menus; dark: `0 6px 20px rgba(0,0,0,.45)`, in both dark blocks) · `--row-h: 2.75rem`, `--row-h-compact: 2.25rem` · `--motion: 120ms`, `--ease-out: cubic-bezier(.2,0,0,1)` · `--stage-withdrawn: var(--stage-closed)`, `--stage-withdrawn-soft: var(--stage-closed-soft)`.
**Elevation scale:** 0 = page (`--bg`) · 1 = card (`.surface`/`.ui-card`: `--surface`, `1px --border`, `--shadow-sm`) · 2 = sticky bar (`.ui-bulkbar`: `--shadow`) · 3 = menu/toast (`--shadow-md`/`--shadow-lg`). Never nest a card in a card: sub-areas inside a card use `--surface-2` with no border.
**Typography:** page title `--text-2xl` 650 (as now); card title `--text-md` `--weight-bold`, sentence case (replaces the all-caps 11px labels on these tabs); body `--text-sm`; captions `--text-xs` `--muted`; KPI values `--text-3xl` `--weight-semibold` `.num`.
**Rhythm and width:** sections `--space-6` apart; card padding `--space-4` (≤ 640px `--space-3`); card head to body `--space-3`; rows `--space-3 --space-4`. Content uses the full `--page-w` through `.ui-grid`.
**Links vs buttons:** an action is a `button` (`.primary`, default, `.ghost`); navigation to another place is `a.button` or `a.text-link`; `button.link` only inside a sentence. No underlined stand-alone action. `.text-link`: `--accent`, no underline, underline on hover and `:focus-visible`.

**Global classes (new):**
| Class | Use, DOM |
|---|---|
| `.ui-card` + `.ui-card-head` / `.ui-card-title` / `.ui-count` / `.ui-card-actions` | A card: `section.ui-card > header.ui-card-head > h3.ui-card-title + span.ui-count.num + div.ui-card-actions`. `.ui-count` = muted number pill (`--surface-2`, `--radius-pill`) |
| `.ui-grid` + `.span-4/5/6/7/8/12` | 12-column grid, gap `--space-5`; ≤ 900px every span is 12 |
| `.ui-list` / `.ui-list-row` | Rows inside a card, the SettingRow look: grid `minmax(0,1fr) auto`, min-height 3.5rem, rows split by `1px --border`; `.ui-list-row-title` (600) over `.ui-list-row-desc` (`--muted`) |
| `.ui-badge[data-tone=ok/info/warn/danger/neutral]` + optional leading `Icon` | Status words: `--text-xs` 600, `--radius-pill`, fg/bg = `--ok/--ok-soft`, `--accent/--accent-soft`, `--warn/--warn-soft`, `--danger/--danger-soft`, `--text-2/--surface-2`. Words always carry the meaning |
| `.ui-table` (+ `.col-num`, `.col-select`, `.col-action`, `[data-stack]`) | Data table: `th` `--text-xs` 600 `--muted` sentence case, bottom border `--border-strong`; rows `--row-h` (`.is-compact`: `--row-h-compact`); `tbody tr:hover` `--surface-2`; `tr[aria-selected='true']` `--accent-soft`; `.col-num` right-aligned `.num`; empty cells stay empty (B§2.3.2). `[data-stack]` at ≤ 640px: `thead` visually hidden, each `tr` a 2-line grid, `td[data-label]::before { content: attr(data-label) " " }` |
| `.ui-check` | Styled checkbox that keeps a real input: `label.ui-check > input[type=checkbox] + span.ui-check-box[aria-hidden] + span(label text or .visually-hidden)`. The input is `opacity:0; position:absolute; inset:0` over a 2rem (≤ 640px `--touch-min`) hit area; the box is 1.1rem, `1.5px --control-border`, checked `--accent` fill with a check drawn by `::after` borders in `--accent-text`; `:indeterminate` a bar; focus ring on the box via `input:focus-visible + .ui-check-box`; disabled 0.45 opacity |
| `.ui-select` | `span.ui-select > select`: `appearance:none`, padding-right 2rem, a chevron drawn by `::after` borders in `currentColor` (no literal colour, no SVG data URI) |
| `.ui-segmented` / `.ui-segmented > button` | Pill track `--surface-2`, 2px inset; segments transparent, body font, `.num` for numbers; selected (`[aria-pressed=true]`, `[aria-checked=true]` or `[aria-selected=true]`): `--surface`, `--shadow-sm`, `--text`, 600. Each segment ≥ `--control-h` tall, `--touch-min` at ≤ 640px |
| `.chip.is-removable` + `.chip-remove` · `.chip.is-suggested` · `button.chip.is-filter[aria-pressed]` | Removable chip with an × button (24px look, 44px hit area at ≤ 640px via `::after`); dashed suggested chip with a leading +; filter chip with a count |
| `.ui-bulkbar` | Sticky bar `bottom: calc(var(--bottom-nav-h) + env(safe-area-inset-bottom) + var(--space-3))`, `.surface` + `--shadow`, flex row: text left, buttons right |
| `.ui-drop[data-drop=ok/no/over]` | Drop-target states: `ok` dashed `2px --accent` outline; `over` `--accent-soft` fill; `no` opacity .5 |
| `.ui-skeleton` | Loading bar `--surface-3`, pulse animation off under reduced motion; rows match the real row height |
| `.text-link` | See the link rule above |

**Components (new, `web/src/ui/`):**
| Component | Props / emits / slots | DOM and ARIA |
|---|---|---|
| `Segmented.vue` | `modelValue`, `options:[{value,label,ariaLabel?,disabled?,title?}]`, `label` (group name) / `update:modelValue` | `div.ui-segmented[role=radiogroup][aria-label]` > `button[role=radio][aria-checked]`, roving tabindex, arrows/Home/End move and select |
| `Switch.vue` | `modelValue`, `label`, `description?`, `disabled`, `busy` / `update:modelValue` | The Q-116 switch row look: `button[role=switch][aria-checked]` named by the label, described by the description, visible "On"/"Off" text, `aria-busy` while busy |
| `MenuButton.vue` | `items:[{id,label,checked?,disabled?,danger?,hint?}]`, `label` (accessible name), `kind: 'menu'/'radio'`, `align: 'start'/'end'`, `triggerClass`, `disabled`, `disabledReason` / `select(id)` / slot `trigger` (visible content) | `button[aria-haspopup=menu][aria-expanded][aria-controls]` + inline `ul.ui-menu[role=menu]` (absolute, `--shadow-md`, flips up when it would pass the viewport bottom, guarded for jsdom) > `li[role=none] > button[role=menuitem or menuitemradio][aria-checked]`; an optional `p.ui-menu-heading` labels the menu |
| `MoveMenu.vue` | `status`, `targets` (default `MOVE_TARGETS`), `name` (e.g. "SRE at Flowdesk"), `disabled`, `disabledReason` / `move(status)` | MenuButton `kind=radio`; trigger = `.pill[data-status]` + chevron, text = `statusLabel(status)`; name "Move {name}, now {Stage}"; heading "Move to"; the current stage is checked and disabled |
| `KpiCard.vue` | `label`, `value` (number, string or null), `caption?`, `hint?`, `href?` | `a.ui-kpi` when `href`, else `div.ui-kpi`: `span.ui-kpi-label`, `span.ui-kpi-value.num`, `span.ui-kpi-caption`; `hint` = `title` + visually hidden text; value null = caption only |
| `ProgressSegments.vue` | `segments:[{id,label,n,tone,href?}]`, `mode: 'link'/'filter'`, `modelValue` (filter), `label`, `allLabel?` / `update:modelValue` | Bar `div.ui-progress[aria-hidden]` of spans (`flex-grow: n`, ≥ 6px when n > 0, gap 2px, tone colour from stage or tone tokens, zero hidden); legend `ul.ui-progress-legend[aria-label]` of `a` (link mode) or `button[aria-pressed]` (filter; with an optional leading "All" item), each swatch + label + `.num` count; zero items stay, muted |
| `SortHeader.vue` | `label`, `column`, `sort:{key,dir}`, `numeric?` / `sort(column)` | `th[scope=col][aria-sort]` > `button.ui-th-sort` (label + chevron that flips; hidden until sorted) |
**Shared rules (`stages.js`, L0):** `STAGE_TABS = ['all','active','applied','interviewing','offer','rejected']`; `MOVE_TARGETS = ['applied','interviewing','offer','rejected']`; `stageOf(status)`: `assessment → 'interviewing'`, `withdrawn → 'rejected'`, `to_apply → null` (Active and All only), the four targets map to themselves, any other config status `→ null`. `CLOSED_STATUSES` unchanged (`rejected`, `withdrawn`). `LABELS.to_apply` becomes **"To apply"** (the queue design's word, AQ§7.1; it covers saved and queued). The `.pill[data-status]` rules stay; `withdrawn` keeps the closed grey; `assessment` keeps its teal on the row pill. **Icon.vue** gains `grip` (six dots), `more` (three dots), `info` (circle + i) and `alert` (triangle), 24-unit grid, Lucide-style paths copied with the ISC note in the file header (B§1.3).

## 2. Overview (`tabs/Overview.vue`, `overview.js`; lane LA)
```
1440                                                                         390
Overview                                                                     Overview
Where your search stands, and what to do next.                               Where your search stands, …
<SetupChecklist :runs :runs-known with-apply />  (unchanged, only when shown) <SetupChecklist …/>
┌New roles─────┐┌Active applications┐┌Interviews─────┐┌Response rate──┐     ┌New roles──┐┌Active─────┐
│ 101          ││ 34                ││ 3             ││ 72%           │     │ 101       ││ 34        │
│ in your Inbox││ Not rejected or w…││ No offers yet ││ 81 of 113 hea…│     └───────────┘└───────────┘
└──────────────┘└───────────────────┘└───────────────┘└───────────────┘     ┌Interviews─┐┌Response───┐ (2×2)
┌To do (span-8)──────────────────────────────────┐┌Last run (span-4)──────┐ ┌To do────────────────────┐
│ Triage 101 new roles               [Open Inbox] ││ ✓ Success · 1 min ago │ │ Triage 101 new roles    │
│ Save the ones worth applying to; mark the rest… ││ 0 new roles · 10 comp…│ │ Save the ones… [Open In…]│
│ Follow up on 30 applications           [Review] ││            [Open Runs]│ │ Follow up on 30 … [Rev…]│
│   GovTech · Software Engineer, Core…   48 days  │└───────────────────────┘ └─────────────────────────┘
│   GovTech · Platform Infrastructure…   48 days  │┌Past 7 days────────────┐ ┌Pipeline 113 tracked─────┐
│   and 27 more                                    ││ 0 new roles  0 to apply│ │███████░░░░░░░░░░░▒▒▒▒▒▒│
└─────────────────────────────────────────────────┘│ 1 applied    1 other   │ │Applied 31 › Interv. 3 ›│
┌Pipeline  113 tracked (span-8)──────────────────┐└───────────────────────┘ │Offer 0 ›   Rejected 79 ›│
│ ██████████████████████▒▒░  ░░░░░░░░░░░░░░░░░░░ │                          └─────────────────────────┘
│ ■ Applied 31 › ■ Interviewing 3 › ■ Offer 0 ›   ■ Rejected 79 › (1 withdrawn)   Last run, Past 7 days
└─────────────────────────────────────────────────┘                          stack below
```
- **KPI row** (`div.ui-grid` of four `KpiCard`, span-3; ≤ 640px a 2×2 grid): "New roles" = `newRoleCount(jobs)`, caption "in your Inbox", `href="#/inbox"` · "Active applications" = rows with `isActive`, caption "Not rejected or withdrawn", `#/applications/active` · "Interviews" = interviewing + assessment rows, caption "{n} offers" / "1 offer" / "No offers yet", `#/applications/interviewing` · "Response rate" = `responseRate()` (unchanged rule), value "{rate}%", caption "{heard} of {applied} heard back", hint "An interview, offer or rejection after you applied counts as a reply."; with no sent application: value null, caption "No applications sent yet." No link. All from `GET /api/applications`, `/api/stats` and the shell's `jobs`.
- **To do** (`ui-card` + `ui-list`, span-8): one `ui-list-row` per `nextUp()` item, in its order; the first row's button is `.primary`, the rest default. Copy: questions "{n} questions waiting for your answer" / desc as today / [Answer questions]; inbox "Triage {n} new roles" / "Save the ones worth applying to; mark the rest Not interested." / [Open Inbox]; follow-up "Follow up on {n} applications" / "Applied 14 or more days ago, with no reply recorded." / [Review] → `#/applications/applied`, with up to 3 sub-rows "{Company} · {Role}" + "{n} days" (right, `.num`) and "and {k} more" as plain text; run rows as today. None: the row "You're all caught up." / "Nothing needs you right now. The next run brings new roles to your Inbox." Questions error: the existing warn notice inside the card, with [Try again].
- **Pipeline** (`ui-card`, span-8, title "Pipeline", `.ui-count` "{total} tracked"): `ProgressSegments mode=link`, segments Applied, Interviewing (incl. assessment), Offer, then Rejected (incl. withdrawn) set apart by a gap and muted; `href` `#/applications/<stage>`; legend text "Applied 31", a "›" `aria-hidden`; when withdrawn > 0 the Rejected item adds "(1 withdrawn)". Empty: "Nothing tracked yet. Save a role in the Inbox and it shows up here."
- **Last run** (span-4 card): `lastRunState()`; `.ui-badge` (Success ok / Failed danger / Aborted warn) + "{ago}"; "{n} new roles · {c} companies checked" (`accepted`, `stats.companies_due`); `failReason` when failed; [Open Runs] (`a.button.ghost`). No run: "No runs yet." + [Open Runs]. While a run is going: badge info "Running" + "Follow it on the Runs tab." (replaces today's page-sub lines).
- **Past 7 days** (span-4 card): a `dl` 2×2 of small stats, value `--text-lg` `.num`: "New roles found", "To apply", "Applied", "Other updates" (`pastWeek()`; the `week.saved` key stays, its label changes); zero values muted. All zero: "A quiet week: nothing found or changed in the past 7 days."
- **overview.js:** `DEFAULT_STAGES` → `['applied','interviewing','offer']`; `pipeline()` returns `{ segments:[{id,label,n}] (via stageOf), toApply, withdrawn, assessment, rejected, total }`; `openStages()` and `responseRate()` unchanged (the reply rule still reads config order); new `kpis(rows, jobs)`. Loading: four `.ui-skeleton` KPI cards + two card skeletons.

## 3. Applications (`tabs/Applications.vue`, new `components/ApplicationRow.vue`, `applications.js`, `RunSelector.vue`; lane LB)
```
1440                                                                                         390
Applications                       [⌕ Search company or role  /] [By company│Recent] Runs [All runs ⌄] Applications
34 active · 113 tracked at 20 companies                                                      [⌕ Search…        ]
[All 113] [Active 34] [Applied 31] [Interviewing 3] [Offer 0] [Rejected 79]   ← drop targets   [By company│Recent][Runs⌄]
(MailSuggestions, unchanged)                                                                  [All][Active][Applied][Int›  (scrolls)
┌──────────────────────────────────────────────────────────────────────────────────────────┐ ┌───────────────────────────┐
│ [GT] GovTech · 7 roles                                                                   │ │[GT] GovTech · 7 roles     │
│ ⠿ Software Engineer, Core Engineering Products ↗                  [◌ Applying… Filling the│ │Software Engineer, Core… ↗ │
│   Singapore                                                         form]  [To apply ⌄] ⋯│ │◌ Queued · 3rd             │
│ ⠿ Platform Infrastructure Engineer, AISO ↗  [Follow up?]   Applied · 48 days [Applied ⌄] ⋯│ │[To apply ⌄]            ⋯ │
│ ⠿ Data Engineer ↗  ● Needs your answers [Answer in Profile] [Try again]     [To apply ⌄] ⋯│ ├───────────────────────────┤
│ ⠿ Backend Engineer ↗  [✓ Applied automatically]            Applied · today  [Applied ⌄] ⋯│ │Platform Infrastructure… ↗ │
└──────────────────────────────────────────────────────────────────────────────────────────┘ │Applied · 48 days · Follow…│
                                                                                              │[Applied ⌄]             ⋯ │
```
- **Stage strip:** `STAGE_TABS` in that order, labels "All", "Active", "Applied", "Interviewing", "Offer", "Rejected" with `.num` counts (Interviewing counts assessment rows, Rejected counts withdrawn). Same DOM as today (`div.stages[role=group][aria-label="Filter by stage"]` > `button.stage[aria-pressed][data-status]`), restyled as underline tabs: active = 2px `--accent` bottom border + `--text`; ≤ 640px it scrolls sideways (`overflow-x:auto`, `scroll-snap`), each tab `--touch-min`. Filter: All = every row; Active = `isActive`; a stage = rows with `stageOf(status) === stage`. Unknown config statuses show under All and Active only.
- **Stage in the URL:** `useView('applications', STAGE_TABS, remembered)`; remembered = `localStorage[STAGE_KEY]` mapped through `stageOf` (old `to_apply` → `active`, `assessment` → `interviewing`, `withdrawn` → `rejected`), else **`all`** on a first visit (All now leads the strip; assumption A1). A tab click writes `#/applications/<stage>` by `replaceState` (useView) and the key. A row id in the hash (`#/applications/<stage>/<job_id>`, `useHashItem('applications')`) scrolls to and focuses that row (used by Runs' "Open in Applications"); job ids that don't match `[\w-]+(:[\w-]+)?` link to the stage only.
- **Row** (`ApplicationRow.vue`, props `row`, `showCompany`, `saving`; emits `move`, `remove`, `note`, `details`): grid `auto minmax(0,1fr) auto auto auto` = grip · title block · `.app-state` · age (`ageLabel`, `.num`, `title` = exact time) · MoveMenu · ⋯ MenuButton. Title block: role (external `a`, as today) + `Follow up?` pill; second line `secondLine(row)`, plus "{Company}" first when sorted by Recent (then `CompanyMark size=sm` leads the row). By company: one `.ui-card` per company with a header "[mark] {Company} · {n} roles"; Recent: one card, no headers.
- **`.app-state` slot (queue states; shared with Q-120 U3):** `to_apply` rows show one chip from `row.last_attempt` / `row.queue` via `StateChip` (as-is): no attempt "To apply" (neutral) · `queued` (U3) "Queued · {ordinal}" (neutral) · `running` "Applying…" (checking) + the step word when AQ provides it · `needs_input` "Needs your answers" (attention) + `a.button.ghost` "Answer in Profile" (`openProfile('details')`) · `stopped` "Stopped: {text}" (attention, text clipped to 60 chars, full in `title`) + `a.button.ghost` "Open the posting" · `dry_run` "Dry run ready" (checking) · `unconfirmed` "Sent, not confirmed" (attention). After them U3 adds `button` "Try again" (AQ§7.1). Status `applied` with `last_attempt.kind === 'sent'`: `.ui-badge[data-tone=ok]` with `check` icon "Applied automatically". Rows that are queued or running are pinned to the top of Active and All (running, then queued by position) and are **not draggable**; their MoveMenu is disabled with the reason "JobScraper is applying to this role. Stop it in Runs first."
- **Move to:** `MoveMenu` replaces `StatusSelect` (deleted). Targets Applied, Interviewing, Offer, Rejected; a `to_apply`, `assessment` or `withdrawn` row shows its own word on the pill ("To apply", "Assessment", "Withdrawn") with no target checked. Choosing commits at once through the existing `change(row, status)`: the existing toast "Moved to {Stage}: {role}" with Undo (Undo restores the old status, even `to_apply`/`assessment`/`withdrawn`); live region (one `p.visually-hidden[aria-live=polite]` per tab) "{Role} at {Company} moved from {Old} to {New}."; focus returns to the pill.
- **Drag and drop (≥ 641px, pointer):** each row `draggable="true"` except pinned rows; the grip (`Icon grip`, `--muted`, visible on row hover/focus) is the visual cue, the whole row drags. `dragstart` sets `dataTransfer.setData('text/x-jobscraper-job', job_id)`, `effectAllowed='move'`, keeps the row in a module variable (jsdom-safe), adds `.is-dragging` (opacity .5) and announces "Dragging {Role}. Drop it on a stage tab." The four target tabs get `.ui-drop[data-drop=ok]`, the row's own stage, All and Active `data-drop=no`; `dragover` on a target `preventDefault` + `over`; `drop` → `change(row, stage)`; `dragend` clears. Esc cancels natively. Touch and keyboard use Move to (B§2.4.2; Atlassian: no arrow-key dragging).
- **⋯ menu** ("More actions for {Role} at {Company}"): "Add note"/"Edit note", "Show details"/"Hide details", "Open the posting" (if `safeUrl`), "Remove from Applications" (only when ≤ 1 event; opens today's in-row confirm "Remove {Company} from Applications? Its notes go too." [Remove] [Keep]). The note form, History `<details>` and the detail panel stay under the row as today.
- **Header:** sort becomes `Segmented` "By company" / "Recent" (label "Sort"); `RunSelector` wraps its select in `.ui-select` (DOM otherwise unchanged; Inbox uses it too). Page sub: "{active} active · {total} tracked at {c} companies" (whole data set, before filters).
- Empty and error states keep today's copy; "Nothing here." adds [Show all] (sets stage All, clears run and search).

## 4. Runs (`tabs/Runs.vue`, `components/CountPicker.vue`, `runs.js`; lane LC)
```
1440                                                                   390
Runs                                                                   Runs
A run checks your companies' job boards and puts the roles … Inbox.    A run checks …
┌Auto-apply queue (ApplyQueuePanel, span-7)─┐┌Start a run (span-5)────┐┌Auto-apply queue──────────┐
│ Now applying  GovTech · Data Engineer     ││ Companies this run     ││ Now applying …           │
│ ◌ Filling the form · 2 min  [Stop this ap…]││[30│50│100│200│All│Custom]│└──────────────────────────┘
│ Up next (2)              [Pause queue] [⋯]││ 100 of 433 companies ·  │┌Start a run───────────────┐
│ 1. Flowdesk · SRE   added 2 min ago Remove││ about 9 min. Only compa…││[30│50│100│200]           │
│ Recently finished                         ││ Dry run            Off ○││[All│Custom]  (wraps)     │
│ Grab · Analyst  ✓ Sent  12:04  Open in A… ││ [Check 100 companies]   ││ …  [Check 100 companies] │
└───────────────────────────────────────────┘└────────────────────────┘└──────────────────────────┘
┌Run history  Last run 1 min ago · 0 matches──────────────────────────────────────────┐┌Run history───────────────┐
│ ☐  Run  Date     Companies  Postings  Matches  Took    Failed  Status               ││☐ Run 29 · 30 Oct  ✓Success│
│ ☐  31   12 Nov          10       273        0  13 min      11  ✓ Success            ││  257 companies · 40,503 … │
│ ☑  29   30 Oct         257    40,503       32  19 min      28  ✓ Success            ││  32 matches · 19 min · 28 │
└─────────────────────────────────────────────────────────────────────────────────────┘└──────────────────────────┘
          [ 1 run selected · 32 matches          Clear selection   [Show in Inbox] ]  ← .ui-bulkbar, only when ≥ 1
```
- **Top area:** `div.runs-top` = an optional queue slot, then the Start card. CSS: one column; at ≥ 1100px `.runs-top:has(> .runs-queue)` becomes `minmax(0,7fr) minmax(0,5fr)` (queue left, start right); without the panel the Start card spans the row with its controls in two columns (picker left, switch and button right), so no hole. ≤ 1099px: queue, then Start, then history. LC leaves the comment `<!-- Q-120 U2: <ApplyQueuePanel class="runs-queue ui-card" /> mounts here -->` as the first child of `.runs-top`.
- **Panel styling contract (for Q-120 U2):** root `section.ui-card.runs-queue`, head `.ui-card-head` > `h3.ui-card-title` "Auto-apply queue" + `.ui-count` (waiting) + `.ui-card-actions` (Pause / Resume / Clear queue as default buttons; "Stop this application" default, never `.primary`). Now applying = a `.ui-list-row` with `StateChip state="checking"` (state word) and elapsed `.num`. Paused banner = `.notice.warn[role=status]` inside the card. Up next and Recently finished = `ol.ui-list` / `ul.ui-list` with `h4.ui-card-title`-styled sub-headings; "Dry run" = `.ui-badge[data-tone=neutral]`; outcome chips = `.ui-badge` (sent ok, dry_run info, needs_input warn, stopped danger, cancelled neutral); "Remove" = `button.ghost`; "Open in Applications" = `a.text-link` to `#/applications/all/<job_id>` (§3).
- **Start card** (`form.start.ui-card`, title "Start a run"): `CountPicker` with new prop `custom: 'field'|'segment'` (default `'field'`, Settings unchanged in behaviour); Runs passes `'segment'`: presets 30, 50, 100, 200, "All" (`aria-label` "All {max} companies"; no number inside the segment), "Custom". Custom (or a value that is not a preset or max) shows a labelled field below: "Number of companies" (`input.custom`, `.num`, width 8rem). CountPicker keeps `.presets`, `button.preset[aria-pressed][data-preset]`, `input.custom` and its emits; its CSS moves to `.ui-segmented` (mono gone; the look changes in Settings too, see request R2). Hint (`#run-batch-hint`): "{n} of {max} companies · about {estimate}. Only companies that are due are checked." / empty value: "Uses your saved setting: {batch} of {max} companies." / errors as today. `Switch` "Dry run" with description "Fetch and report; save nothing." Primary button: empty → "Start run"; n → "Check {n} companies"; max → "Check all {max} companies"; dry run → "Start dry run ({n} companies)"; busy → "Starting…". The Cancel button and the running notice (`.notice.warn` with spinner, "{busy} in progress · {elapsed} so far." + `a.text-link` "Follow its log on the Developer tab") sit in the card footer. Q-120 U2 adds the "Run after this application" label via `startLabel` (a computed LC introduces).
- **Run history** (`ui-card`, title "Run history", head text "Last run {ago} · {matches}" + `a.text-link` "See them in the Inbox" when > 0; `id="choose-runs"`, `tabindex=-1` on the card, the Inbox's "Choose runs…" focus target): `table.history.ui-table[data-stack]`. Columns: select (`.ui-check`, label "Select run {n}", disabled with `title` "This run found 0 matches" when `accepted` is 0; faint until row hover, focus or a first selection) · Run · Date · Companies · Postings · Matches (number only, `.col-num`) · Took · Failed (`button.ghost.failed-link` `.num`, danger text when `failedTone` is hard; same label) · Status (`.ui-badge` + icon, word from new `runStatusTitle()`: "Success", "Failed", "Aborted", "Dry run", "Running"). Unknown values render an empty cell (`count()`/`runTook` return ''). Header checkbox "Select every run with matches" (`indeterminate` when some). Shift-click selects the range between the last clicked and this row (enabled rows only). `tr[aria-selected]` mirrors the selection.
- **Bulk bar** (`.ui-bulkbar[role=region][aria-label="Selected runs"]`, only when ≥ 1): "{n} runs selected · {matches}" + `button.ghost.clear-picked` "Clear selection" + `button.primary.show-picked` "Show in Inbox". The always-visible "Choose runs" card goes. Loading: three `.ui-skeleton` rows in the table.

## 5. Companies (`tabs/Companies.vue`, `components/WatchedCompanies.vue`, new `companyRows.js`, `companyFilter.js`; lane LD)
```
1440                                                                      390
Companies          [Edit list] [Upload list] [Search now] [⋯ More]       Companies              [⋯ More]
Your list, and which of its companies JobScraper can read.               Your list, and which …
559 in your list → 433 watched → 394 readable → 120 checked this cycle   [Edit list] [Upload list]
████████████████▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▒▒░░░░░░░░░░░░                          559 in your list → 433 watched →
(All 559) ■ Checked this cycle 120 ■ Due for a check 274 ■ Failed 39      394 readable → 120 checked …
■ No job board found 126  ■ Waiting 0 (hidden when 0)                     ████████▓▓▓▓▓▓▓▒░░░
[⌕ Search by company, job board or reason…  /]  [Compact rows]           (All 559)(Checked 120)
┌Company ▲──────────────┬Job board───┬Open roles┬Last checked┬Status──────────────┬────┐ (Due 274)(Failed 39)…
│[1] 1Password          │Ashby       │       90 │13 days ago │✓ Checked           │ ↗  │ [⌕ Search…         ]
│[AI] Aberdeen (abrdn)  │Workday     │       22 │18 days ago │◌ Due for a check   │ ↗  │ ┌1Password    ✓ Checked┐
│[AD] Acme Robotics     │            │          │            │! No job board found│    │ │Ashby · 90 roles · 13…│
│                       │            │          │            │ no careers site fou│    │ └──────────────────────┘
└───────────────────────┴────────────┴──────────┴────────────┴────────────────────┴────┘
```
- **Data (no new endpoint):** `GET /api/companies/list` (`items[].status/name/provider/postings/detail/searched_at`, cap fields), `GET /api/companies/health` (`items[].state/last_scan/open_roles/job_board/kind/reason/careers_url`), `GET /api/settings` (`cycle_days`). `companyRows.js` (pure): `partition(health, list, cycleDays, now)` → buckets `checked` (state ok and `last_scan` within `cycle_days`), `due` (ok, older), `failed`, `never` (`not_scanned`), `not_found` (list status `failed`), `waiting` (list `pending/searching/over_limit`); `rows()` maps both shapes to `{key, company, board, openRoles, lastChecked, bucket, reason, kind, url}`. Health rows are taken whole; only `not_found` and `waiting` come from the list, so no company is counted twice and no name join is needed. If settings fail, `checked` and `due` merge into "Readable".
- **Funnel sentence** (`p.funnel`, `.num` numbers, arrows `aria-hidden`): "{list} in your list → {watched} watched → {readable} readable → {checked} checked this cycle" (list = list items; watched = `health.total`; readable = health `ok`; checked = `checked` bucket). No list: it starts at "{watched} watched". Below it, `ProgressSegments mode=filter` (label "Show companies", `allLabel` "All"), segments in this order: "Checked this cycle" (ok), "Due for a check" (info), "Failed" (danger), "Never checked" (neutral, only when > 0), "No job board found" (warn), "Waiting for search" (neutral, only when > 0). The legend is the filter and replaces the three tiles, the view toggle and the source select (B§2.2.1/2.2.2 merged into one control: a departure, so the counts and the filter can't disagree).
- **Table** (`WatchedCompanies.vue` becomes the table; props `health`, `list`, `cycleDays`, `error`, `initialState`; keeps search, `Compact rows` density sync with Settings, the cause chips and the "What you can do" note in the Failed view, the CSV link): `table.ui-table[data-stack]` with `SortHeader` on Company (default ascending), Open roles, Last checked; columns Company (`CompanyMark sm` + name) · Job board (`boardName`) · Open roles (`.col-num`, empty when unknown) · Last checked (`ago(last_scan or searched_at)`, `title` exact) · Status (`.ui-badge`: "Checked" ok, "Due for a check" info, "Failed" danger with the reason as a second line, "Never checked" neutral, "No job board found" warn with `detail` as second line, "Waiting" / "Searching…" / "Over plan limit" neutral) · `.col-action` `a.button.ghost` with `external` icon, `aria-label` "Careers page for {company}" (none without a URL). The A–Z strip and the sort select go (B§2.2.4). Result line: "{n} companies" + [Clear filters] (`button.ghost`).
- **List actions** (page head): "Edit list" (opens today's editor, unchanged), "Upload list" (the hidden file input behind a `label.button`, TXT or DOCX; a drop anywhere on the tab shows the overlay "Drop to replace your list"), "Search now" (`.primary`, only with waiting names), `MenuButton` "More" (`more` icon): "Download found (.txt)", "Download not found (.txt)", "Full report (.csv)", "All watched companies (.csv)", "Clear list…" (danger; opens today's in-place confirm "Clear your list? The companies it added stop being watched." [Clear list] [Keep list]). Cap line moves into the page sub when a cap exists: "… {n} of {cap} companies used on the {plan} plan."
- **First run (no list, no health rows):** today's drop zone + "Type or paste names" stay as the empty state. Runs' "N failed" keeps `requestCompanyFilter('failed')`, mapped to the Failed segment. The view key `jobscraper.companies.view` is no longer read.

## 6. Profile (`tabs/Profile.vue`, `components/TitleEditor.vue`; lane LE)
```
1440                                                                    390
Profile                              [Resume and titles│Application details] Profile
Your resume, and the job titles each run searches for.                  [Resume and titles│Application…]
┌From your resume · read 2 Nov──────────────[Replace resume] [Re-read]┐┌From your resume · read 2 Nov──┐
│ Experience  Less than a year     Graduation  2026                    ││[Replace resume] [Re-read]     │
│ Benjamin … is a software engineer with a strong background in AI… (3 ││Experience Less than a year    │
│ lines) [Show more]                                                   ││Summary (3 lines) [Show more]  │
└──────────────────────────────────────────────────────────────────────┘└───────────────────────────────┘
┌Skills 52 (span-6)─────────────────┐┌Job titles to search for 11 (span-6)┐┌Skills 52──────────────────────┐
│ (python)(typescript)(javascript)… ││ A posting is kept when its title … ││(python)(typescript)…          │
│ (12 shown)        [Show all 52]   ││ (software engineer ×)(full stack ×)││[Show all 52]                  │
│ Interests  (fintech)(ai)          ││ [Add a job title, e.g. data…][Add] │└───────────────────────────────┘
│ From your resume. Re-read it to … ││ Recommended titles [Recommend titl…]│┌Job titles to search for 11───┐
└───────────────────────────────────┘│ (+ backend engineer)(+ ml ops …)    ││(software engineer ×)…        │
<ResumeRefresh/> (unchanged)          └────────────────────────────────────┘└──────────────────────────────┘
```
- **Header card** (only when `profile.present`): title "From your resume", caption "read {when(parsed_at)}" (`title` exact). Actions: `label.button` "Replace resume" (the existing hidden file input; PDF or DOCX, 5 MB) and `button` "Re-read resume" (`refreshOnly`, today's "Re-derive profile from the stored resume", renamed). The card is also the drop target (`.ui-drop[data-drop=over]` while a file is over it; overlay text "Drop to replace your resume"). Facts as a `dl` row: "Experience" / "Graduation". Summary clamped to 3 lines with `button.ghost` "Show more"/"Show less" (`aria-expanded`). The file name, the "52 skills" and "11 job titles" lines and the titles `<ul>` are removed. Fine print stays muted at the bottom: "Profile version {v} · read by {parsed_by}". Upload notes, errors, "Reading your resume…" and the log `<details>` sit under the card, as today. No resume yet: today's drop zone and "No profile yet." stay.
- **Skills card** (span-6, `.ui-count` = skills length): `ul.chips.skills` of `.chip` (body font); first 12, then `button.ghost.more-skills` "Show all {n}" / "Show fewer" (`aria-expanded`). Interests as a sub-group ("Interests" `h4`) with chips or "None set. They live in config.yaml under judge.interests." Footer caption "From your resume. Re-read it to update them." Skills are read-only (no endpoint edits them; assumption A3; grouping by category: §11).
- **Job titles card** = `TitleEditor` restyled as a `.ui-card` (span-6): head "Job titles to search for" + `.ui-count` (`countLabel`); desc as today; chips `.chip.is-removable` (× = `.chip-remove`, `aria-label` "Remove {title}"); add field + [Add]; "Reset to the titles from your resume" = `button.ghost`; "Recommended titles" sub-section with `button.chip.is-suggested` "+ {title}" items (today's `.te-suggestion` buttons, classes kept) and [Recommend titles] default (not `.primary`, so the card has no competing primary). Behaviour and copy otherwise unchanged.
- Hash views (`#/profile/resume`, `#/profile/details`, `useView`) and the tablist are unchanged; the tablist gets `.ui-segmented`.

## 7. Routes
| Hash | Before | After |
|---|---|---|
| `#/applications` | remembered stage, first visit Active | remembered stage (mapped by `stageOf`), first visit **All**; hash left alone |
| `#/applications/<stage>` (all, active, applied, interviewing, offer, rejected) | not a route (landed on the tab) | that stage; unknown → `all`, canonical `replaceState` (useView rule) |
| `#/applications/<stage>/<job_id>` | n/a | that stage, row scrolled into view and focused |
| `#/companies`, `#/runs`, `#/overview`, `#/profile[/resume|/details]` | unchanged | unchanged |
No edit to `route.js`, `tabs.js` or `App.vue`: `parseHash` already reads `#/applications/applied` as the Applications tab.

## 8. Accessibility (per new primitive)
- **Segmented:** radiogroup, roving tabindex, arrows select (they also commit: the Applications sort is not risky); selected also shown by weight and shadow, not colour alone. CountPicker keeps its `aria-pressed` buttons (tests).
- **Switch:** `role=switch`, visible On/Off text, named by its label; 44px row at ≤ 640px.
- **MenuButton / MoveMenu:** WAI-ARIA menu button: Enter, Space or ArrowDown open and focus the checked or first item; ArrowUp opens on the last; Up/Down/Home/End move; a letter jumps; Enter/Space select; Esc closes and focuses the trigger; Tab closes; outside click closes. Disabled trigger keeps focus and exposes the reason through `aria-describedby`. Items ≥ 2.25rem (≥ 44px at ≤ 640px).
- **DnD:** never the only path (Move to); announcements in one polite live region: drag start, "{Role} at {Company} moved from {Old} to {New}.", "Drop cancelled." Drop targets are tabs that remain plain buttons for keyboard users.
- **KpiCard:** a link whose name is "{label}: {value}, {caption}"; hint as visually hidden text.
- **ProgressSegments:** the bar is `aria-hidden`; the legend carries every number; link mode `a` named "{label}, {n}"; filter mode `aria-pressed`. Segment colours pass 3:1 against `--surface` in both themes (stage and tone tokens already do).
- **SortHeader:** `aria-sort` on the `th` (ascending, descending, none on the others); the button names the column.
- **`.ui-check`:** a real `input[type=checkbox]` (setValue, `:checked`, label still work); focus ring on the drawn box; 44px hit area at ≤ 640px; header checkbox exposes `indeterminate`.
- **Bulk bar:** `role=region` with a label; appears without stealing focus; "Clear selection" returns focus to the first row checkbox.
- All: tokens only (no literal colours), both themes, `prefers-reduced-motion` stops the skeleton pulse, menu fade and chevron rotation.

## 9. Files and build plan (worktrees, branch per lane, `eng/Q-118-<lane>`)
| Lane | Files (disjoint) | Waits for |
|---|---|---|
| **L0** foundation | `web/src/style.css`, `web/src/ui/{Segmented,Switch,MenuButton,MoveMenu,KpiCard,ProgressSegments,SortHeader}.vue` (new), `web/src/stages.js`, `web/src/components/Icon.vue` | review of §1 by the shell's owner |
| **LA** Overview | `tabs/Overview.vue`, `overview.js` | L0 merged |
| **LB** Applications | `tabs/Applications.vue`, `components/ApplicationRow.vue` (new), `applications.js`, `components/RunSelector.vue`, `components/StatusSelect.vue` (deleted) | L0 |
| **LC** Runs | `tabs/Runs.vue`, `components/CountPicker.vue`, `runs.js` | L0 |
| **LD** Companies | `tabs/Companies.vue`, `components/WatchedCompanies.vue`, `companyRows.js` (new), `companyFilter.js` | L0 |
| **LE** Profile | `tabs/Profile.vue`, `components/TitleEditor.vue` | L0 |
Steps: (1) L0, Verify `cd web; npx vitest run` (all green: L0 changes no DOM in existing components) and a visual check of Settings in both themes on the dev instance (8768). (2) LA, LB, LC in parallel (max 3 engineer lanes), then LD, LE; each: Verify `cd web; npx vitest run` with that lane's retargeted tests + the new pins green, and a 1440/390 screenshot pair on 8768. (3) One bundle build in the main checkout after the last merge (message the live sessions first).
**With Q-120 (AQ§9):** LC merges **before** U2 (U2 then adds the one mount line in the `.runs-top` slot and the `startLabel` branch); LB merges **before** U3 (U3 then edits `attempts.js` and `ApplicationRow.vue`'s `.app-state` slot, not `Applications.vue`; please update AQ§9's U3 file list). U1 (Inbox, JobPill, api.js) touches none of these files. Until W1 ships, nothing is faked: the queue slot is empty (the Start card spans the row), `queued` never appears (rows show what `last_attempt` says today), "Try again" is absent, and the "Open in Applications" deep link is unused.
**Backend work packages:** none.

## 10. Tests (tester; existing files to retarget per lane, then lean new pins in `web/tests/q118-*.test.js`)
- **L0** `q118-ui.test.js`: MenuButton keyboard (open, move, Esc returns focus); MoveMenu emits `move` and marks the current stage; Segmented arrows; Switch `aria-checked`; ProgressSegments link hrefs and `aria-pressed`; `stageOf` and `STAGE_TABS` order; `statusLabel('to_apply') === 'To apply'`.
- **LA** retarget `Overview.test.js`, `overview.helpers.test.js` (pipeline shape, DEFAULT_STAGES, "To apply" week label), `q100-shell.test.js` and `App.test.js` only if they read Overview text. Pins: KPI values and hrefs; pipeline links `#/applications/applied|interviewing|offer|rejected`; assessment counted in Interviewing, withdrawn in Rejected; SetupChecklist still mounted with `with-apply`.
- **LB** retarget `Applications.test.js`, `applications-flow.test.js` (STAGE_KEY default), `q76-detail.test.js` (attempt pill moves into `.app-state`), `ux1.test.js` and `q100-setup.test.js` (Applications parts; Remove now via the ⋯ menu). Pins: strip order All…Rejected with no Saved/Assessment/Withdrawn button; `#/applications/offer` opens Offer; Move to commits, toasts with Undo, announces old→new and refocuses the pill; DnD (`dragstart` + `drop` on the Interviewing tab with a stub `dataTransfer`) commits once; running/queued rows not draggable; "Applied automatically" badge on `sent`.
- **LC** retarget `Runs.test.js`, `q75-pages.test.js`, `ui.test.js` (CountPicker, Runs), `ux1.test.js` (Runs); keep `q116-settings.test.js` and `m15.test.js` green untouched. Pins: Custom reveals the field; button text "Check {n} companies"; bulk bar absent at 0, "{n} runs selected" at 1; shift-click range; header checkbox indeterminate; empty cells instead of "—".
- **LD** retarget `m16.test.js`, `m17.test.js`, `q75-pages.test.js`, `ui.test.js`, `ux1.test.js` (Companies parts), `q116-settings.test.js` (density sync only). Pins: no source select and no view toggle; funnel sentence numbers; each legend filter shows its bucket; `partition()` unit cases (cycle edge, settings failure, no double count); sort by Open roles.
- **LE** retarget `Profile.test.js`, `q44-refresh.test.js`, `ux1.test.js`, `q100-setup.test.js` (Profile parts), `m15/m16/m17.test.js` (TitleEditor classes kept, so likely untouched). Pins: no file-name line once present; drop zone only with no profile; "Show all {n}" toggles; no titles `<ul>` in the resume card.
Shared test files (ux1, q75-pages, ui, m16, m17, q100-setup) are edited by one tester, lane by lane in merge order.

## 11. Later / out of scope
Board (kanban) view of Applications · Reka UI pilot (B§1.4) if hand-built menus prove costly · skills grouped by category (the profile has no category field) and editable skills (no endpoint) · Overview auto-apply widget · Inter web font (B§1.3, optional) · "Your order" column in the companies table (the editor and the CSV keep the order).

## 12. Assumptions (none blocking) and requests
A1 Applications opens on **All** at a first visit (All now leads the strip); the remembered stage still wins. A2 the `to_apply` word becomes "To apply" everywhere (`statusLabel`), matching AQ§7; the Inbox Save button keeps "Save". A3 skills stay read-only. A4 "Checked this cycle" = a successful check within `cycle_days` (client-side; the pipeline's own due rule may differ by hours). A5 `CountPicker`'s restyle shows in Settings → Search too (same DOM and behaviour).
Requests (outbox): R1 shell owner: review §1; optionally restyle `SetupChecklist` with `.ui-card` (no prop change). R2 shell owner: accept the CountPicker look change in Settings. R3 Q-120: U3 edits `ApplicationRow.vue`; U2 uses the §4 panel class contract.
