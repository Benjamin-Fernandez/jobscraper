# Q-116 design: one Settings page (category rail + rows)

Status: READY TO BUILD (reviewed by the Q-100 session 2026-11-12: approve with 3 minor findings, folded in). Fast track (UI only, no new backend). Builds on Q-100 (`q100_ui_design.md` §1, §4.3, §4.4) and Q-111 (`GET/PUT /api/apply/settings`). Owner, 2026-11-12: "more intuitive, maybe something similar to LinkedIn … settings all over the place". Bound by D-200 (nothing is applied to unless the owner clicks), D-203 (in auto mode the click fills and submits, no second confirm), D-204 (no daily limit, 10 per employer).

## 1. Problems with today's page
- The section picker is a small segmented control in the top-right corner, away from the content; it reads like a filter, not navigation.
- A 40rem column hugs the left edge (≈60% of a 1440px window is empty), and three visual styles coexist: hub cards, an Apply `dl`, segmented boxes.
- Four save models: Cycle saves on click, Companies per run needs its own Save, Apply has a page-level Save, Theme applies instantly.
- Settings live elsewhere with no pointer from Settings: the shortcuts switch at the foot of the Inbox action bar, list density in Companies, job titles and interests in Profile.
- The current value is not visible at a glance: Apply shows prose ("10 applications a day · 2 per employer · browser window shown"); the caps form predates D-204 (1–50, no "no limit"); five apply options are config-only today.

## 2. Information architecture
Four categories, in this order: **Accounts**, **Apply**, **Search**, **Preferences** (today's Appearance, renamed because it now holds the keyboard row too; §4 maps the old hash). `#/settings` opens Accounts on desktop. Row ids (in backticks) are the hash item (§4) and the DOM id `setting-<id>`. Control: *edit* = row opens in place, *switch* = toggles on the row, *link* = goes elsewhere.

**Accounts**: Q-100's `ConnectionsHub` embedded unchanged (its own "Connected accounts" heading and cards). No rows of ours.

**Apply**. Intro line above the groups (§5). Source of every edit/switch row: `GET /api/apply/settings`; saves `PUT /api/apply/settings` with the one changed key. Hidden when the GET answers 404/405 (Mode then falls back to `GET /api/apply/status` `mode`, read-only).

| Group | Row label (`id`) | Description line | Value shown | Control | Saves to | v1 |
|---|---|---|---|---|---|---|
| How applying works | Mode (`mode`) | What happens when you click Auto-apply on a role. | Dry run / Automatic submit | edit: 2 radios; Automatic asks first | `mode` | v1 |
| | Show the browser window (`browser-window`) | Watch each application in its own Edge window. | On / Off | switch | `headed` | v1 |
| | Human-check wait (`human-check-wait`) | How long JobScraper waits for you at a human check. It never solves one. | Stops at once / Up to 2 min | edit: presets + number | `captcha_wait_s` (0..600) | v1 |
| Limits | Applications a day (`daily-cap`) | The most applications JobScraper submits in one day. | No daily limit / 25 a day | edit: presets + number | `daily_cap` (0..500, 0 = none) | v1 |
| | Per employer (`per-employer-cap`) | The most applications to one employer in one day. | No limit / 10 a day | edit: presets + number | `per_employer_daily_cap` (0..100) | v1 |
| Writing | Write cover letters (`cover-letters`) | Writes one from your resume when a form requires it. Off: you're asked instead. | On / Off | switch | `compose_enabled` | v1 |
| Before you apply | Application mailbox (`mailbox`) | Reads the codes some sites email you during an application. | StateChip of the `apply-mailbox` item | link "Manage in Accounts" | links to `#/settings/accounts/apply-mailbox` | v1 |
| | Application details (`details`) | Contact details, work rights and the answers forms ask for. | Complete / 3 to fill in | link "Edit in Profile" | links to `#/profile/details` | v1 |
| | Resume (`resume`) | The resume JobScraper reads, tailors and uploads. | (none) | link "Edit in Profile" | links to `#/profile/resume` | v1 |
| (later) | Let the local AI read private fields | — | — | — | `apply.model_sees_sensitive` | Later §9 |

**Search**. Source: `GET /api/settings`; saves `PUT /api/settings`.

| Group | Row label (`id`) | Description line | Value shown | Control | Saves to | v1 |
|---|---|---|---|---|---|---|
| Schedule | Cycle (`cycle`) | How often every company is checked again. | Daily / Weekly / Fortnightly / Monthly (`cycleLabel`) | edit: radios from `cycle_day_options` | `cycle_days` | v1 |
| | Companies per run (`batch-size`) | How many watchlist companies one run checks. | 50 companies | edit: `CountPicker` (presets + All + number) | `batch_size` (1..enabled) | v1 |
| What to look for | Job titles (`titles`) | The roles JobScraper searches for. | (none) | link "Edit in Profile" | links to `#/profile/resume` | v1 |
| | Kinds of role (`interests`) | The kinds of work you're open to. Set in config.yaml for now. | (none) | link "View in Profile" | links to `#/profile/resume` | v1 link; edit Later |
| | Companies to watch (`companies`) | The careers sites JobScraper checks. | (none) | link "Manage in Companies" | links to `#/companies` | v1 |
| (later) | Keep job descriptions for | — | — | — | `retention.description_days` | Later |

**Preferences** (this browser only).

| Group | Row label (`id`) | Description line | Value shown | Control | Saves to | v1 |
|---|---|---|---|---|---|---|
| Display | Colour theme (`theme`) | Light, dark, or match your device. | Light / Dark / System | edit: 3 radios | `theme.js` `setTheme` (`jobscraper.theme`) | v1 |
| | Compact company list (`density`) | Shows each company on one line in Companies. | On / Off | switch | new `density.js` (`jobscraper.companies.density`) | v1 |
| Keyboard | Keyboard shortcuts (`shortcuts`) | Single-key actions in the Inbox and g + a letter to switch tabs. / and ? always work. | On / Off | switch | `shortcuts.js` `setShortcutsEnabled` (`jobscraper.inbox.shortcuts`) | v1 |

**Deliberately out:** the Developer tab (a job log, not a setting); `budget.*` AI settings (the hub's Local AI card states them and how to fix them); `apply.fill`, `mail_status.enabled` (MailCard switches each mailbox). **Duplicates kept:** the Inbox "Turn off" link and the Companies "Compact rows" button stay where they act (in-context; WCAG 2.1.4 wants the off switch near the keys); both read the same key, and the Settings row and the in-place control follow each other through a window event.

## 3. Layout and components
- **Page:** header "Settings" + subtitle, then a two-pane grid `15rem minmax(0, 44rem)`, gap `var(--space-6)`, full width of `main`. 641–900px: rail `12rem`. ≤640px: one pane (phone screens below).
- **Rail (`SettingsRail.vue`):** vertical list, sticky (`top: var(--space-4)`); each entry = `Icon` (Accounts `key`, Apply `send`, Search `search` (exists), Preferences `sliders`; the three new shapes are added to `Icon.vue`'s `ICONS`, 24-unit grid: `key` = circle (8,15) r4 + path `M11 12l8.5-8.5M16 7l2.5 2.5M14 9l2 2`; `send` = paths `M4 12 20 4l-4 16-4-7z`, `M12 13 20 4`; `sliders` = path `M4 7h9M17 7h3M4 17h3M11 17h9` + circles (15,7) r2 and (9,17) r2) + name + badge. Current entry: `--surface` background, `--border-strong` left bar 3px, weight 650. **Badges:** Accounts = `attentionCount` (as today: dot + number + visually hidden "need attention"); Apply = the number of distinct missing detail labels from `GET /api/applicant` (visually hidden "details to fill in"); none when 0 or the load failed.
- **Group (`SettingsGroup.vue`):** `h4` title, then a `surface` card; rows separated by `1px var(--border)`.
- **Row (`SettingRow.vue`):** grid `minmax(0,1fr) auto`, min-height 3.5rem, padding `var(--space-3) var(--space-4)`. Left: label (600, `--text-sm`) over the description (`--muted`, `--text-sm`, wraps). Right: value (`--text-2`) then the affordance: chevron `›` (rotates 90° when open) for edit; a switch track with On/Off text for switch; "Manage in …" text + `›` for link. The whole row is the hit target (`button` or `a`). Read-only (`writable` not `true`): no chevron, no switch, value as text, description gains " Set in config.yaml."
- **Edit interaction: expand in place, one open at a time.** Opening a row closes the other; the editor sits under the row inside the card. Chosen over LinkedIn's sub-page because there are only 3–9 rows per category, each editor is one control, an in-place editor keeps the row's context and needs no extra history level, and at 390px it simply grows downward. **Commit rules (one rule for the page):** a radio click or Space saves at once; an arrow key moves without saving, Enter or focus leaving the editor saves, Esc reverts (Q-75 N17, now for every radio row); a number saves on Enter or when focus leaves the editor, if valid and changed; a preset button saves at once; Esc reverts and closes, focus back on the row. An invalid number never sends; its error shows under the field; opening another row drops that draft. A switch saves on toggle. No page-level Save anywhere.
- **Risky change:** choosing Automatic submit shows the in-row confirm (§5); nothing is sent until "Switch to automatic submit"; "Keep dry run" or Esc puts Dry run back and sends nothing. Switching to Dry run never asks.
- **Saving states:** while a save is in flight the row has `aria-busy="true"` and its control is disabled; on success the value updates and "Saved" (with ✓) shows beside it for 3 s; on failure the old value stays and the error shows under the row (`role="alert"`) until the next edit. Switches are not optimistic. Apply 404/405 on PUT: the Apply rows turn read-only (Q-100 rule).

```
Desktop 1440                                                     Phone 390, screen 1      Phone 390, screen 2
Settings                                                          Settings                 ‹ Settings
Accounts, applying, search and preferences.                       Accounts, applying, …    Apply
┌───────────────────┐  Apply                                      ┌──────────────────────┐ To apply, open a role in the
│ ⚿ Accounts    ● 1 │  To apply, open a role in the Inbox and     │ ⚿ Accounts     ● 1 › │ Inbox and choose Auto-apply.
│▌➤ Apply       ● 3 │  choose Auto-apply.            [Open Inbox] │ ➤ Apply        ● 3 › │ [Open Inbox]
│ ⌕ Search          │  How applying works                         │ ⌕ Search           › │ How applying works
│ ≡ Preferences     │  ┌────────────────────────────────────────┐ │ ≡ Preferences      › │ ┌──────────────────────┐
└───────────────────┘  │ Mode              Automatic submit   ⌄ │ └──────────────────────┘ │ Mode                 │
                       │ What happens when you click Auto-apply │                          │ What happens when …  │
                       │  ( ) Dry run  (•) Automatic submit     │                          │ Automatic submit   › │
                       ├────────────────────────────────────────┤                          ├──────────────────────┤
                       │ Show the browser window      On  [ ●]  │                          │ Show the browser     │
                       │ Watch each application in its own …    │                          │ window     On  [ ●]  │
                       ├────────────────────────────────────────┤                          └──────────────────────┘
                       │ Human-check wait      Up to 2 min    › │
                       └────────────────────────────────────────┘
```
- **Phone (≤640px, `matchMedia('(max-width: 640px)')`, guarded for jsdom):** with no view in the hash the page shows the category list (`nav`, rows 48px, badges, `›`); choosing one sets `location.hash = '#/settings/<id>'` (a push, so the phone's Back returns to the list); the category screen starts with a back link `‹ Settings` (`href="#/settings"`), then the category title. Value moves under the description when the row is narrower than 22rem (container query on the card).

## 4. Routes
| Hash | Desktop | Phone |
|---|---|---|
| `#/settings` | Accounts (hash left alone, as `useView` does today) | the category list |
| `#/settings/accounts[/<item>]` | Accounts; the hub scrolls to and focuses the card (unchanged, D-197) | same, as its own screen |
| `#/settings/apply`, `/search`, `/preferences` | that category | that category screen |
| `#/settings/<category>/<row-id>` (ids in §2) | the category with that row open, scrolled into view, its row button focused; unknown row id = top | same |
| `#/settings/appearance[/…]` | rewritten with `replaceState` to `#/settings/preferences` before `useView` runs (and in a `hashchange` listener registered before `useView`'s) | same |
| `#/settings/<unknown>` | `#/settings/accounts`, canonical (today's `useView` rule) | same |
Rail clicks keep `useView`'s `replaceState`. No edit to `route.js` or `App.vue`: the shell's mode chip (`#/settings/apply`), banner (`#/settings/accounts/<id>`) and `onHub` logic keep working. (`onHub` also hides the banner on the phone category list; accepted, the list shows the same badge.) Row ids are read with `useHashItem('settings')`, acted on only by the panel whose category is in the hash. `ConnectionsHub` is mounted only while Accounts is shown (`v-if`, never `v-show` or an inner keep-alive): the hub calls `useHashItem('settings')` without checking the view, so a mounted hub would act on another category's row id.

## 5. Copy (final; sentence case; labels and value texts are in the §2 tables)
- Page: title "Settings"; subtitle "Accounts, applying, search and preferences." Categories: "Accounts", "Apply", "Search", "Preferences". Rail label (screen reader): "Settings categories". Back link: "Settings" (with `‹`, `aria-label="Back to Settings"`).
- Group titles: "How applying works", "Limits", "Writing", "Before you apply", "Schedule", "What to look for", "Display", "Keyboard".
- Apply intro: "To apply, open a role in the Inbox and choose Auto-apply. JobScraper never applies to a role you didn't click." [Open Inbox]. When `busy`: "An application is running now. Changes apply to the next one."
- Why that is true (checked in code, 2026-11-12): a running application keeps the mode it started with. The apply job reads its mode once when it starts (`jobscraper apply` computes the effective mode, `cli.py` `cmd_apply`: `_effective_apply` then `dry_run = … acfg.mode != "auto"`; `apply_flow._Run.__init__` holds `self.dry_run`/`self.mode` for the whole job), so switching to Dry run never stops a submission that is already under way.
- Mode editor: "Dry run" / "Fills each form and leaves it open for you. Nothing is submitted." · "Automatic submit" / "When you click Auto-apply, JobScraper fills the form and submits it once its final check passes."
- Confirm (in the row, `role="group"`): title "Submit applications automatically?"; body "From now on, clicking Auto-apply on a role fills the form and submits it once its final check passes. There's no second confirmation."; buttons "Switch to automatic submit" (primary) / "Keep dry run".
- Human-check wait editor: presets "Stop at once" (0), "1 min", "2 min", "5 min"; field "Seconds to wait"; helper for 0: "JobScraper stops and leaves the page to you. It never solves a human check." for n > 0: "JobScraper waits up to {n} s for you to finish a human check in the window. It never solves one." Value: 0 "Stops at once"; n "Up to {n} s", or "Up to {m} min" when n is a whole number of minutes.
- Daily cap editor: presets "No limit" (0), 10, 25, 50; field "Applications a day"; helper "0 means no limit. Up to 500." Per employer: presets "No limit", 2, 5, 10; field "Per employer a day"; helper "0 means no limit. Up to 100." Values: daily 0 "No daily limit", n "{n} a day"; per employer 0 "No limit", n "{n} a day".
- Number errors (under the field): "Enter a whole number." · "Enter a number from {lo} to {hi}."
- Cycle editor (kept from today, A15): the hint "Every company is checked again every {n} days. At {k} companies per run that is {runs}." and "The config default is {weekly}." Pending arrow choice: "{Monthly} is selected but not saved. Press Enter to save, or Esc to keep {weekly}."
- Companies per run editor (kept, A10): cadence hint "A full {n}-day sweep takes {runs} at this size ({r} runs to cover {c} companies)."; range "Between 1 and {max}. The config default is {d}. A run started with its own count (Runs tab) uses that instead."; none enabled: "No companies yet. Add some in Companies, or start a run to load your watchlist."; validation as today ("Enter how many companies a run should take.", "Enter a whole number.", "A run needs at least 1 company.", "At most {max} - that is every enabled company.").
- Saved: visible "Saved"; announced "Saved: {row label}, {value}." (Search rows add " The next run uses it.").
- Save errors (under the row): 422 "Couldn't save: {message from `errors[].message` for this field, else `detail`}." · network/other "Couldn't save: {describeError}. Your previous setting is kept." · Apply 404/405 "Couldn't save: this server doesn't accept changes yet." (Q-100 wording).
- Load errors: Search "Couldn't load search settings: {reason}." [Try again]. Apply sources that fail are hidden (never faked); Accounts errors are the hub's own.
- Read-only suffix: " Set in config.yaml." Links: "Manage in Accounts", "Edit in Profile", "View in Profile", "Manage in Companies".

## 6. Accessibility
- Desktop rail: `role="tablist"`, `aria-orientation="vertical"`, `aria-label="Settings categories"`; entries `role="tab"`, roving `tabindex`, ArrowUp/ArrowDown (and Left/Right, kept from today), Home, End move and focus; content `role="tabpanel"` `aria-labelledby`. Icons `aria-hidden`. Phone list: `nav aria-label="Settings categories"` > `ul` of links.
- Focus: a rail click or arrow keeps focus on the tab. Phone drill-in moves focus to the category title (`h3 tabindex="-1"`; for Accounts the hub's `.hub-title`); Back returns focus to the list entry just left. Row open: focus to the checked radio or the number field; close (Esc, re-click): focus to the row button; a hash row id focuses the row button.
- Rows: edit rows are `button aria-expanded aria-controls="setting-<id>-editor"`, name = label + value (`aria-labelledby`), `aria-describedby` = description; the editor is `role="group"` labelled by the row label. Switches: `button role="switch" aria-checked`, same naming. Link rows: `a` named "{label}, {link text}". Saved text in a `role="status"` span per row; errors `role="alert"`.
- Targets: every row, switch, preset and list entry ≥ 44px tall at ≤640px (`--touch-min`). Switch state is shown as text (On/Off), never colour alone; focus ring `2px var(--focus)`. Only theme tokens (no literal colours), so light and dark both work; chevron rotation off under `prefers-reduced-motion`.

## 7. Files and build steps
New: `web/src/components/SettingsRail.vue`, `SettingsGroup.vue`, `SettingRow.vue`, `SearchSettings.vue`, `PreferencesSettings.vue`; `web/src/settingsRows.js` (the `useRows()` composable: `open`, `busy`, `saved`, `error` per row id, `flash(id)`, `fail(id, msg)`; formatters `capLabel`, `waitLabel`; the shared copy of §5 except Apply's); `web/src/density.js` (`DENSITY_KEY`, `densityCompact()`, `setDensityCompact(on)` dispatching `jobscraper:density`); `web/src/applyData.js` (`loadApplyData() -> {status, settings, summary}`, each null on failure, plus `missingLabels(summary)`). Rewritten: `Settings.vue` (page shell, routes, data, rail, phone screens; the Search and Appearance markup moves out to the two new panels), `ApplySettings.vue` (rows; props `connections`, `apply` = the `loadApplyData` answer; emits `saved(nextSettings)`; no own loading, no Save button). Edited: `WatchedCompanies.vue` (read `density.js`, listen to `jobscraper:density`; its button calls `setDensityCompact`), `Icon.vue` (three shapes, §3). Not edited: `route.js`, `App.vue`, `Inbox.vue`, `connections.js`, the hub and its cards.
**SettingRow contract** (both lanes use it): props `id, label, description, value, kind ('edit'|'switch'|'link'|'static'), checked, href, linkText, open, busy, saved, error, readOnly`; slots `value` (e.g. StateChip) and default (the editor); emits `toggle` (edit open/close) and `change(bool)` (switch).

Lane 1 (`eng/Q-116-L1-shell`): `Settings.vue`, `SettingsRail.vue`, `SettingsGroup.vue`, `SettingRow.vue`, `settingsRows.js`, `applyData.js`, `SearchSettings.vue`, `PreferencesSettings.vue`, `density.js`, `WatchedCompanies.vue`, `Icon.vue`.
1. `SettingRow.vue`, `SettingsGroup.vue`, `settingsRows.js`, `applyData.js` per the contracts; commit first (lane 2 branches from this commit). Verify: `cd web; npx vitest run` green (no test touches them yet).
2. `Settings.vue` shell: rail (+ icons), phone list/back, `appearance` alias, one `getConnections` + one `loadApplyData` on mount and `onActivated`, Accounts badge + Apply badge, hub embedded under `v-if` (mounted only while Accounts is shown, §4), `<ApplySettings :connections :apply @saved>`; on `saved(next)` it replaces `apply.settings` and re-reads `getApplyStatus` (mode, busy). Verify: dev instance on 8770 (DB copy, `JOBSCRAPER_MAIL_SYNC=0`): every hash of §4 lands as stated at 1440 and 390.
3. `SearchSettings.vue` (cycle + companies per run moved from `Settings.vue`, commit rules of §3) and `PreferencesSettings.vue` (theme, density, shortcuts; re-read stored values in `onActivated`; listen to `jobscraper:shortcuts` and `jobscraper:density`); `density.js` + `WatchedCompanies.vue`. Verify: vitest green except the retargets listed in §8; a cycle change and a batch-size change save on 8770.

Lane 2 (`eng/Q-116-L2-apply`, from lane 1 step 1): `ApplySettings.vue` only.
4. `ApplySettings.vue` as rows with the §2 table, ranges 0..500 / 0..100 / 0..600, PUT one key per save, the in-row confirm, read-only unless `writable === true`, no probe PUT, rows hidden on 404. Verify: on 8771 with a DB copy (the PUT writes settings rows in that copy only; never the live DB or 8765), switch Mode to Dry run and back (confirm shown), set Applications a day to No limit; `GET /api/apply/settings` reflects each; no application is started.
**Bundle:** after both lanes merge into `personal` and vitest is green there: message the other live sessions (ListAgents), then `cd web; npm run build` in the main checkout only; commit the bundle; smoke `#/settings/apply` on a dev instance with a DB copy (never 8765).

## 8. Tests (lean, tester; new file `web/tests/q116-settings.test.js`)
- Routes: `#/settings` desktop → Accounts; phone (mocked `matchMedia`) → list, drill-in, back; `#/settings/appearance` → `#/settings/preferences`; `#/settings/apply/daily-cap` opens that row; unknown view → accounts.
- Round trip: open Applications a day, pick "No limit" → one `PUT {daily_cap: 0}`, value "No daily limit", "Saved"; a 422 with `errors[{field:'daily_cap'}]` → the message under the row, old value kept; an invalid number sends nothing.
- Auto switch: choosing Automatic submit sends nothing until confirmed; Keep dry run sends nothing; confirming sends `{mode:'auto'}`.
- Q-100 pins kept: one `/api/connections` fetch shared with Apply; no PUT on load; read-only without `writable: true`; mailbox row chip + link; Accounts badge; shortcuts row and Inbox stay in sync.
- Hash ids: no Settings row id (§2) equals a hub item id (`gmail:N`, `apply-mailbox`, `edge`, `model`, `employer-accounts`); and the hub is not mounted outside Accounts.
- Backend (Python, `-k web_`): a foreign-Origin `PUT /api/apply/settings` gets 403 and writes nothing (CrossSiteWriteGuard), like Q-100's pin for `POST /api/connections/model/check`.
- Retarget: `q100-settings.test.js` (four views → rail and Preferences; ApplySettings now takes `apply`; Save button gone; caps ranges; confirm copy), `Settings.test.js` and `ui.test.js` (Companies per run: Enter/blur/preset instead of Save), `m15.test.js` and `q75-pages.test.js` (cycle and theme now inside a row that opens first; notice texts §5), `ux1.test.js` (page title unchanged, check it still passes). `q100-shell.test.js` and `route.test.js` should pass unchanged.

## 9. Later (not in v1)
- Let the local AI read private profile fields (`apply.model_sees_sensitive`): add the key to Q-111's GET/PUT; a privacy switch (D-201), so a KA-2 review of the copy first.
- Edit kinds of role (`judge.interests`): a list key in `GET/PUT /api/settings` (settings table) that the judge reads over config.
- Resume tailoring on/off (`tailor.enabled`), job-description retention (`retention.description_days`), email check interval (`mail_status.interval_min`, the timer must restart): each a new key in `GET/PUT /api/settings` (or a mail route) read by its stage over config. Then a "Data and privacy" category for the first, second and fourth.

## 10. Open questions
None blocking. Assumptions: "Preferences" replaces "Appearance" (old hash kept); density moves in and the in-place controls stay; the Apply badge counts missing details.

## 11. Kept from Q-100 (agreed: Q-116 owns `Settings.vue` and `ApplySettings.vue`)
1. Hashes `#/settings/accounts|apply|search|appearance` and `#/settings/accounts/<item-id>` deep links (scroll + focus the card, `useView`/`useHashItem`, D-197): §4; `appearance` is an alias now.
2. The Accounts attention count (`attentionCount`) and the shell banner's links: rail badge (§3); `App.vue` untouched.
3. One `/api/connections` fetch shared by the hub and Apply: `Settings.vue` holds it (§7 step 2).
4. "Application mailbox: {state} · Manage in Accounts" row (MAJOR-6, `apply/contracts.py:175`): Apply → Before you apply.
5. Editable only when `writable: true`, never a probe PUT; a 404 source hides its rows: §2, §7 step 4.
6. Human checks: JobScraper waits for you and never solves one: Human-check wait row and §5.
7. A10/A12/A15 copy of Search and Appearance: kept in §5 (subtitle updated for the rename; the "plan (local)" line stays dropped).
8. 44px targets at ≤640px; at 390px a category list that drills in, not a rail: §3, §6.
9. No secret in any response or in the page (ADR-0009): no row reads or shows a password; the hub is unchanged.
**Departures from Q-100, with reasons:** the view tabs become a vertical rail (Q-104 (e), owner's LinkedIn direction); "Appearance" → "Preferences" (it now holds the keyboard row); the mode value reads "Automatic submit" and the confirm copy follows D-203 (Q-100's "Automatic" hid that the click submits; `COPY.modeAuto` in `connections.js` is left as is for its other users); caps 0 = no limit with Q-111 ranges (D-204) replace 1–50; the page-level Save goes (save on change); Q-100's "Ready to apply" row becomes the intro line + the Application details row.
