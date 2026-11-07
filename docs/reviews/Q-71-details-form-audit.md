# Q-71 · Profile → Your details: gap audit

Reviewer, 2026-11-07. Base: `int/Q-70-ux` 5d0f266 (worktree `.claude/worktrees/int-Q-70-ux`), plus the salary fix on `eng/Q-71-details` 027f45f.
Owner's words: "needs large fixing", "I can't even enter my desired salary". The Coordinator's browser walkthrough (B1–B10, desktop 1512px) is folded in; each B-item was checked against the code and has a Q71 ID below.

## 1. Method

- Read: `web/src/components/FieldInput.vue` (456 l), `web/src/components/ApplicationDetails.vue` (511 l), `web/src/applicantForm.js`, `web/src/tabs/Profile.vue` (views, resume upload), `web/src/style.css` tokens, `src/jobscraper/applicant.py` (REQUIRED/RECOMMENDED_PATHS l.80–98, ENUMS/BOOLS l.139–200, `normalise` l.400, `save` l.558, `validate` l.604–798, `_filled`/`completeness` l.918–964, FORM l.967–1223), `src/jobscraper/web/routers/applicant.py`, `src/jobscraper/web/control.py` `profile_view`, `config/applicant.example.yaml`, `config/questions.yaml` (all `- key:` rows), `apply/resolve.py` COUNTRIES l.69.
- Each kind traced: UI emit (FieldInput `set`) → `setAt(draft)` → `PUT /api/applicant {profile, etag}` → `applicant.save` = `normalise` → `validate` → YAML. Each traced from (a) missing key, (b) null, (c) template placeholder (0, ''), (d) a valid value: enter, change, clear, save.
- WCAG 2.1 AA checked at code level (design:accessibility-review). Not rendered: contrast is checked from the tokens only (`--muted` #5d5c64 on #fff ≈ 6.6:1, passes).
- Not re-reported: Q-70 lane D N1–N10 (draft in sessionStorage, save states, Discard, 409 reload, bool "Not set", skeleton). None of them looked broken.

## 2. Correctness defects (can't enter / silently lost)

**Q71-01 · CRITICAL · Expected salary renders no inputs when unset** (already known). `FieldInput.vue:318` `v-if="salary"`; FORM gives `nullable=False` (`applicant.py:1097`), so there is no "I don't have one" box either. Starting from (a) or (b) you can't enter anything. The fix on `eng/Q-71-details` 027f45f (`shownSalary` defaults, `v-if="!noSalary"`) is correct: the first edit writes `{amount, currency:'SGD', period:'monthly'}`, and the server accepts it (`validate` l.705–716). Pin: vitest, FieldInput kind salary with `nullable:false` and modelValue null/undefined renders Amount; typing 4500 emits `{amount:4500, currency:'SGD', period:'monthly'}`. Lane F must branch from 027f45f.

**Q71-02 · HIGH · Country boxes cut a typed name to 2 letters and save it (B1).** `FieldInput.vue:177–189`: kind `country` is a text box with `maxlength="2"` and `onUpper`. Typing "Singapore" keeps "SI" (Slovenia). The server checks only the shape, `ISO2_RE` (`applicant.py:646–648` contact.country, `:658–660` nationality), so "SI" saves. Failure scenario (this is very likely how the preview file got "SI"): `contact.country = SI`, so (1) the SG postal-code rule is skipped (`:651`); (2) `resolve.country_names('SI')` is `()` (`resolve.py:648`, the table has 24 countries), so every "Country" question fails closed and auto-apply stops on each form; (3) a "do you have the right to work where you live" question reads the map for SI and falls back to `default` (`resolve.py:907`). The same text box is used for the country rows of Right to work and Needs sponsorship (`FieldInput.vue:376–387`). A row that isn't `^[A-Z]{2}$` ("U") is left out of the map by `mapOf` (`:114–118`): it stays on screen with a red border and no message, and is gone after reload. That is silent loss.
Fix (G): add `COUNTRY_NAMES: dict[str, str]` to `applicant.py`, covering every ISO 3166-1 alpha-2 code with its English short name (static data, foundation layer, no import). `validate`: contact.country, nationality and every non-`default` key of the two maps must be in it, else the message "is not a country code. Pick a country from the list". `_item_json` for kind `country` emits `options` `[{value:'SG', label:'Singapore (SG)'}, ...]`: SG first, then by name. Emit the same list as `country_options` for `country_bool_map`.
Fix (F): kind `country` becomes a native `<select>` (type-ahead works: typing "Sing" jumps there) over `options`, with the existing `unlisted` fallback, `autocomplete="country"`, and a blank "Choose…" that emits null. Map rows use the same select instead of the code box. A row with no country yet shows "Choose a country" as an inline error, not a silent drop. Optional soft check (F): Country ≠ SG while the phone code is +65 shows the warning "Your country is {name} but your phone code is +65. Is that right?" (warning only, it never blocks).
Pins: py, `validate({'contact':{'country':'XX'}})` errors and 'SI' passes; form_json has country options, SG first. vitest: country renders a select, picking "Singapore (SG)" emits 'SG'; a map row without a country shows the message.
Owner action: once this is fixed, the owner must check their own Country and Nationality (the preview showed SI).

**Q71-03 · HIGH · A failed save gives no way to find what failed.** `ApplicationDetails.vue:289–294`: on a 422 the banner says only "Some details need fixing. They're marked below." It lists only the `unplaced` errors. The page is about 7900px tall and the PUT is all-or-nothing (`routers/applicant.py:148–152`), so one bad field anywhere blocks saving the salary, and the owner has to scroll to find a red border.
Fix (F): an error summary in the banner, one `<li>` per error with the field label (`labelOf(e.path)`; for an entry sub-field, "School 1 · Degree"), the message, and a "Go to" link button that calls `fillIn(e.path)`. `fillIn` must focus the sub-field itself: for `education[0].end` use `subId`, not the first input of the item. Copy: heading "{n} details need fixing before you can save"; each line "{Label}: {message}". Keep `role="alert"` and the focus on the banner. Pin: vitest, a 422 with errors at `contact.email` and `education[0].degree` gives two links, and clicking the second focuses `#f-education-in-0-degree`.

**Q71-04 · MEDIUM · An added but blank entry blocks every save.** `addEntry` (`FieldInput.vue:90–96`) creates `{institution:'', degree:'', …}`. `validate` requires institution and degree (`applicant.py:767–773`), so clicking Add school, changing your mind and pressing Save is a 422 for the whole profile. Fix (F, `ApplicationDetails.save`): before the PUT, drop the entries of `education`, `experience` and `languages` whose every sub value is empty ('' / null) and that have no `from_resume` key. Only the payload is pruned; the draft keeps its rows until the save succeeds. Pin: vitest, add an entry, save, and the PUT body has none.

**Q71-05 · MEDIUM · Amounts with commas or decimals are lost or refused.** Salary amount and every `int` field are `type="number"` (`FieldInput.vue:192–202, 321–331`). In Firefox, "4,500" gives `value === ''`, so null is emitted: the box shows 4,500 but saves nothing and "Needed" stays. Chrome silently blocks the comma key. "4500.50" saves as a float and the server refuses it with "must be a positive whole number". Fix (F): render salary amount and `int` as `type="text" inputmode="numeric"`. On input, strip `[\s,]` and a leading `$`/`S$`. If the rest is `^\d+$`, emit a Number. Otherwise emit the raw text, so the server's message shows and the value is never silently null. Empty input emits null. Pin: vitest, typing "4,500" emits 4500 and "45k" emits "45k" (a string, so a server error follows).

**Q71-06 · MEDIUM · "Needed" stays on after filling a salary, education or a list.** `filledHere` (`ApplicationDetails.vue:161–165`) returns false for every GROUPED kind and for lists, so the badge stays until the next save. The owner types a salary, still sees "Needed", and concludes the input is broken. Fix (F): mirror `applicant._filled` (`applicant.py:918–926`). Salary is filled when `amount` is an integer > 0. `education` is filled when an entry has institution, degree and end. Entries and lists are filled when they hold at least one item. Pin: vitest, typing an amount removes the Needed tag before saving.

**Q71-07 · MEDIUM · The "From your resume, please check" tag never clears.** `setEntry` (`FieldInput.vue:87–89`) spreads the entry and keeps `from_resume: true`, so the tag stays after the owner corrects the entry. Q-44 ("Refresh from resume") will overwrite entries marked `from_resume: true`, so an edited entry would be overwritten later. Fix (F): `setEntry` sets `from_resume: false` when the entry had the key. Pin: vitest, editing a sub-field of a `from_resume` entry emits `from_resume:false`.

**Q71-08 · MEDIUM · Required consents set to No count as filled.** `_filled` (`applicant.py:926`) treats `False` as filled for `consents.privacy_consent` and `consents.certify_true`. Auto-apply starts, then stops at the consent or terms box (`docs/architecture/apply_design.md:837`: Workday sign-up raises `UNANSWERABLE_REQUIRED "account terms"`). That is fail-closed, but it is wasted runs and the reason is never named. Fix (G): those two count as filled only when `is True`; `missing_for_apply` lists them, and the UI label reads "Must be Yes for auto-apply". Pin: py, `missing_for_apply` with `privacy_consent: false` includes it.

**Q71-09 · MEDIUM · An earliest start date in the past is accepted and sent.** The template's `2026-01-05` is already past. `validate` (`applicant.py:742–745`) checks only the format, and resolve fills it as typed. Fix (F, warning only): under the date, if the value is earlier than today (SGT) show "This date has passed. Employers will read it as your start date." Pin: vitest.

**Q71-10 · LOW · A yes/no switch can't go back to "Not set".** The `bool` switch (`FieldInput.vue:214–225`) cycles true/false only. This matters once eng/Q-48 lands `declarations.willing_to_sign_nda`, where null means "ask me" (D-91). Covered by Q71-12's radios plus a "Clear" link for those items.

**Q71-11 · LOW · Focus after "Add" lands nowhere.** `FieldInput.vue:95` focuses `subId(entries.value.length, …)`. After the emit and `nextTick` the length already includes the new entry, so the id is one too far and the focus is lost (WCAG 2.4.3). Fix: `length - 1`. The same pattern on map rows (`:141`) is correct. Pin: vitest, after Add the new entry's first input is `document.activeElement`.

Checked and correct: text, email, phone_cc and digits round-trip as strings (clear = ''). date and month clear to null and the server's `_canon_date` canonicalises them. An enum value the list doesn't offer stays visible (`unlisted`). Chips de-duplicate, and blur adds them. list_url errors land on `links.other[i]` and show under the item. `json_safe` and `with_version` keep unknown keys. The template's `notice_period_days: 0` counts as filled, which is plausible for a new graduate.

## 3. Fields the form can't edit

- **Every key in `config/applicant.example.yaml` has a FORM item**, except `version` (written by the server) and `education[]/experience[].from_resume` (a flag).
- **Every key in `config/questions.yaml` is covered** (37 keys). `computed.experience_years` and `computed.graduation_year` are derived from experience and education.
- **On another branch:** `declarations.government_employment` and `declarations.willing_to_sign_nda` (D-87/D-91) are in FORM on `eng/Q-48-declarations` (`applicant.py:1222–1227` there), not on int/Q-70-ux. Lane F's yes/no control (Q71-12) must keep null visible as "Not set" for them.
- **Asked by professional forms (Workday, Greenhouse, LinkedIn) but in no file:** middle name, references (name, relation, contact), certifications and licences, projects and awards, a salary range (min–max), a work-arrangement preference (on-site, hybrid, remote), phone type. None of them blocks a current Greenhouse application; they're listed in §7 for the backlog. The one with real value is a minimum salary: some SG Workday forms ask for a range.
- **Not filled from the resume (B7):** nothing in `src/` writes `from_resume` or copies resume data into applicant.yaml. Resume ingest writes `data/profile.derived.yaml` (summary, skills, years, graduation, titles) and has no experience entries. So Experience and Skills stay empty after an upload; Education was entered earlier by hand. The smallest step is **Q71-15**. Experience needs the AI parse of Q-44 (BACKLOG).

## 4. UX gaps compared with professional forms

**Q71-12 · MEDIUM · Yes/no questions show as a switch reading "No" (B2).** `bool` is one checkbox whose side text is the current value (`FieldInput.vue:214–225`). For "Have you ever been convicted…?" a switch reads as a setting, not an answer. Workday and Greenhouse use Yes/No radios. Fix (G): `_item_json` emits `control: "yes_no"` for bool items whose path starts with `declarations.` or equals `availability.willing_to_relocate`, set in a `YES_NO_CONTROL` set rather than on the FORM lines, to avoid conflicts with Q-48. Consents keep the switch (their labels are statements). Fix (F): `ApplicationDetails` passes `kind = item.control === 'yes_no' ? 'yes_no' : item.kind` and treats it as GROUPED (span label + `labelledby`). The existing `yes_no` radios (`:226–229`) render with neither checked while the value is null and show the text "Not set" beside them. Add a "Clear" link button only for items marked `nullable_bool` (the D-91 NDA item, once merged). Pin: vitest, a declarations bool renders a radiogroup named by its label.

**Q71-13 · MEDIUM · No way around a 7900px page (B4).** There is no section nav, no per-section status and no "next missing". The top box (`ApplicationDetails.vue:297–307`) has "Fill in" per row only. Fix (F):
1. At ≥ 1100px, a sticky left rail `<nav aria-label="Sections">`: one link per group to `#g-{id}`, each showing a tag "{n} needed" or "{n} to fix" or a check mark. Mark the current section with `aria-current="true"` (IntersectionObserver).
2. Below 1100px, the same links as a horizontal chip row under "Your details".
3. In the sticky save bar, a "Next needed ({n})" button that focuses the next needed item after the focused or last-visible field, wrapping around; hide it at n = 0.
4. Each group header shows the same tag as the rail.
Pin: vitest, the rail lists every group and the Next needed button cycles through needed items in order.

**Q71-14 · MEDIUM · Fields that don't apply are always shown (B5).** Fix (G): a `SHOW_WHEN` dict in `applicant.py`, emitted by `_item_json` as `show_when: {path, values}`:
- `singapore_status.race_other` when race ∈ [other]
- `declarations.holdings` when shareholding_in_company ∈ [true]
- `declarations.relatives_employers` when relatives_at_company ∈ [true]
- `singapore_status.ord_date` when ns_status ∈ [completed, serving]

Fix (F): hide an item (`v-if`) only when the condition is false **and** its value is empty **and** it has no error. A non-empty hidden list would still answer "Yes" through declarations matching, so stale data stays visible. Hidden values are never wiped. Pins: py, form_json carries show_when; vitest, race = Indian hides "Race, if other", while race = Indian with race_other set keeps it shown.

**Q71-15 · MEDIUM · Skills are empty after a resume upload (B7).** Fix (F only, no API change): the existing `GET /api/profile` (`api.js:173`, `control.profile_view`) already returns the derived `skills`. Under Skills, when the derived list has entries missing from `skills` (case-insensitive), show "Your resume lists {n} skills that aren't here." with a button "Add them". It appends them in title case for all-lowercase tokens, with a short exception list ("SQL", "AWS", "C++", "Node.js"; else keep as is), into the draft (not saved). Under an empty Experience, show "Experience isn't filled from your resume yet. Add your jobs here." Pin: vitest with a mocked getProfile.

**Q71-16 · MEDIUM · Files are raw path boxes (B6).** `documents.resume` and `documents.transcript` are `text` (`applicant.py:1158–1162`). The Needed row "Resume file" → "Fill in" focuses a path box, which is the wrong action. Fix (G): `applicant_view` adds `documents_status: {resume: {name, size, modified} | null, transcript: {…} | null}`, using `applicant.resume_file` and an `is_file` check for transcript; it returns the file name only, never the full path. Fix (F): the Files group shows "Using resume.pdf, uploaded 7 Nov 2026, 15:31" or "No resume yet" with a button "Upload in Resume and titles". The button emits `go-view` and Profile.vue switches to `resume`. The path box moves under a "Use a different file" disclosure. Transcript gets "Found" or "Not found" beside its box. The Needed row for `documents.resume` gets the same upload button instead of "Fill in". Pins: py, view includes documents_status; vitest, clicking the button emits go-view.

**Q71-17 · MEDIUM · No browser autofill; fails WCAG 1.3.5.** `autocomplete="off"` is hard-coded (`FieldInput.vue:171, 184`). Fix (G): an `AUTOCOMPLETE` dict emitted per item:
- identity: given-name, family-name, nickname, bday
- contact: email, tel-country-code, tel-national, address-line1, address-line2, postal-code, address-level2, country
- links: url for linkedin, github, portfolio
- backup_email: `off`

Fix (F): add an `autocomplete` prop to FieldInput, defaulting to `off`. Pin: vitest, the contact.email input has `autocomplete="email"`.

**Q71-18 · MEDIUM · Errors appear only after Save.** Professional forms check a field when you leave it. Fix (G): `POST /api/applicant/check {profile}` → `{errors}`. It runs `validate(normalise(p))`, writes nothing, needs no etag or lock, and lives in the same router. Fix (F): on blur of a changed field, debounced 400ms, call check and show only the errors for paths the owner has touched, under the field. Cheap normalisers on blur: url without a scheme gets `https://`; phone code "65" becomes "+65"; email is trimmed. Pins: py, check returns errors and doesn't write (the file's mtime is unchanged); vitest, blur shows "must be an email address" under Email.

**Q71-19 · MEDIUM · Single narrow column on desktop (B9).** `.group` is a one-column grid (`ApplicationDetails.vue:480`) and inputs cap at 28rem. Fix (F): at ≥ 900px, `.group` becomes `grid-template-columns: repeat(2, minmax(0, 1fr))`. Items of kinds entries, salary, country_bool_map, list_text, list_url, fixed, yes_no (questions), multiline and every item in the declarations and consents groups get `grid-column: 1 / -1`. Pairs then sit side by side: first + last name, phone code + number, postal code + city, residency + work pass. Inputs inside a cell use `width: 100%`. One column below 900px. Pin: vitest class check, entries items get the `wide` class.

**Q71-20 · LOW · "Private: never sent to the AI" on nearly every field (B3).** It appears on the group (`:347`) and on each item (`:366`). Fix (F): when every item in the group is sensitive, show the group tag only. In a mixed group (Contact), the header says "Private: never sent to the AI, except City and Country", built from the non-sensitive labels, and items get no tag. Keep the visually-hidden text "Private" in each sensitive field's `describedby` hint so screen readers still hear it. Pin: vitest, us_self_id shows exactly one "Private" tag.

**Q71-21 · LOW · Repeated headings and weak entry controls (B8).** Group "Education" is followed by the item label "Education" (FORM `:1102–1103`, likewise Experience). Fix (F): when an item is the only one in its group and its label equals the group title, render the label visually hidden. Entry cards: put Remove in the legend row, right-aligned, as a small `ghost` button with the text "Remove". The Add button's visible text is "Add school", "Add job" or "Add language" (`entry_label`, lower-cased after "Add"). Pin: vitest.

**Q71-22 · LOW · Copy (B10 and others; design:ux-copy).**
- `pay.months_per_year` help → "13 if you get the AWS (Annual Wage Supplement, a 13th-month bonus)."
- `singapore_status.religion` help "Or leave it as decline." → "Type your religion, or “decline” to not say." (a text box shows the raw word).
- EEO labels from `_enum_opts` defaults: "Hispanic latino" → "Hispanic or Latino"; "Two or more" → "Two or more races"; "Native american" → "American Indian or Alaska Native"; "Pacific islander" → "Native Hawaiian or Pacific Islander"; "Black" → "Black or African American"; "Not a veteran" stays; disability "No"/"Yes" → "No, I don't have a disability" / "Yes, I have a disability".

Fix (G): label dicts in FORM. Pin: py, form_json labels.

**Q71-23 · LOW · Required fields aren't marked until they're missing.** `required` reaches the UI (`_item_json` l.1204) but nothing shows it. Fix (F): a small "Required for auto-apply" text tag on required items when filled; the existing "Needed" tag replaces it when empty. Pin: vitest.

**Q71-24 · LOW · The save bar overflows at 390px.** `.save-bar` (`ApplicationDetails.vue:502–508`) has no `flex-wrap`: the text, Discard, Save and (after Q71-13) Next needed don't fit in 358px. Fix (F): `flex-wrap: wrap`; below 640px the "You have unsaved changes." text takes its own row. Pin: none (CSS); check in the browser.

## 5. Ranked table (owner value: blocks applying > data loss > confusion > polish, then effort)

| Rank | ID | Sev | What | Lane | Effort |
|---|---|---|---|---|---|
| 1 | Q71-01 | CRITICAL | Expected salary inputs missing when unset | eng/Q-71 (in progress) | S |
| 2 | Q71-02 | HIGH | Country boxes cut typed names to codes ("SI"); map rows dropped silently | G + F | M |
| 3 | Q71-03 | HIGH | No error summary with links: one bad field blocks saving | F | S |
| 4 | Q71-04 | MEDIUM | Blank added entry blocks every save | F | S |
| 5 | Q71-05 | MEDIUM | "4,500" saves null; decimals refused | F | S |
| 6 | Q71-06 | MEDIUM | "Needed" sticks after filling salary or education | F | S |
| 7 | Q71-08 | MEDIUM | Consents set to No count as filled | G | S |
| 8 | Q71-13 | MEDIUM | Section rail, per-section status, Next needed | F | M |
| 9 | Q71-12 | MEDIUM | Yes/No radios for declaration questions | G + F | S |
| 10 | Q71-16 | MEDIUM | Files: show the resume in use, upload button | G + F | M |
| 11 | Q71-15 | MEDIUM | "Add {n} skills from your resume" | F | S |
| 12 | Q71-14 | MEDIUM | show_when for conditional fields | G + F | S |
| 13 | Q71-07 | MEDIUM | from_resume tag never clears (Q-44 overwrite risk) | F | S |
| 14 | Q71-18 | MEDIUM | Check on blur (`POST /api/applicant/check`) + URL/+cc normalisers | G + F | M |
| 15 | Q71-17 | MEDIUM | autocomplete tokens (WCAG 1.3.5) | G + F | S |
| 16 | Q71-09 | MEDIUM | Start date in the past: warning | F | S |
| 17 | Q71-19 | MEDIUM | 2-column layout at ≥ 900px | F | S |
| 18 | Q71-20 | LOW | Private badge once per section | F | S |
| 19 | Q71-21 | LOW | Repeated headings; entry Add/Remove | F | S |
| 20 | Q71-22 | LOW | Copy: AWS, religion, EEO labels | G | S |
| 21 | Q71-23 | LOW | "Required for auto-apply" marker | F | S |
| 22 | Q71-10 | LOW | bool can't return to Not set (D-91) | F (with Q71-12) | S |
| 23 | Q71-11 | LOW | Focus after Add entry lost | F | S |
| 24 | Q71-24 | LOW | Save bar wraps at 390px | F | S |

Counts: CRITICAL 1 (known, in progress), HIGH 2, MEDIUM 14, LOW 7. Only Q71-01..03 block.

## 6. Lanes (disjoint files)

**Lane G · backend** · branch `eng/Q-71-G-schema` off int/Q-70-ux · files: `src/jobscraper/applicant.py`, `src/jobscraper/web/routers/applicant.py`, `tests/test_applicant_form.py`, `tests/test_web_applicant.py` (new tests may go in `tests/test_applicant_q71.py`). Contract additions to the item JSON are additive and optional, so lane F must still work while they're absent.
1. G1 (Q71-02): `COUNTRY_NAMES` (all ISO 3166-1 alpha-2 codes; static dict; no new dependency); validate contact.country, nationality and map keys against it; country `options` in `_item_json` and `country_options` on country_bool_map items. Check the existing tests that save made-up codes.
2. G2 (Q71-12, Q71-14, Q71-17): `YES_NO_CONTROL`, `SHOW_WHEN`, `AUTOCOMPLETE` dicts → `control`, `show_when`, `autocomplete` in `_item_json`. Keep them out of the FORM tuples (eng/Q-48 edits the declarations group: minimise the merge conflict).
3. G3 (Q71-08): `_filled` requires True for the two required consents.
4. G4 (Q71-16): `documents_status` in `applicant_view` (name, size, modified ISO; never an absolute path).
5. G5 (Q71-18): `POST /api/applicant/check` (no write, no lock).
6. G6 (Q71-22): label and help copy.

Verify: `python tests/run_tests.py -k applicant` and `-k layering`, then the full suite once.

**Lane F · frontend** · branch `eng/Q-71-F-form` off `eng/Q-71-details` 027f45f (it carries the salary fix) · files: `web/src/components/FieldInput.vue`, `web/src/components/ApplicationDetails.vue`, `web/src/applicantForm.js`, `web/src/tabs/Profile.vue` (go-view only), `web/tests/FieldInput.test.js`, `web/tests/ApplicationDetails.test.js`. Not `QuestionCard.vue`, but it also renders FieldInput: re-run its tests, because kind country becomes a select over `options` (QuestionCard passes `gapField.options`, which G1 fills).
- **F-only, start now:** Q71-03, -04, -05, -06, -07, -09, -11, -13, -15, -19, -20, -21, -23, -24.
- **After G merges into int (or rebase onto G):** Q71-02 (country select), -12 (+ -10), -14, -16, -17, -18.
- **Fallbacks while G is absent:** country without options keeps the text box but drops `maxlength` and shows the hint "2-letter code, e.g. SG for Singapore". Missing `control`, `show_when` or `autocomplete` keeps today's behaviour.

Verify: `cd web; npx vitest run`. Then a browser check on 8768 with a DB copy and a **test** applicant file, never the owner's: enter an expected salary from null, type "Singapore" into Country, add and abandon a school, save with a bad email and follow the summary link, and check the layout at 390px.

**Order:** Q71-01 merges first. G and F run in parallel; G merges before F's second half. The Coordinator merges int/Q-70-ux → personal after both, rebuilds the bundle in the main checkout, and asks the owner to check Country and Nationality (Q71-02).

## 7. Out of scope (backlog candidates)

- Q-44 Refresh from resume (experience, education and skills from the AI parse).
- New schema fields: middle name, references, certifications, projects, salary minimum, work-arrangement preference, phone type.
- Extending `resolve.COUNTRIES` (24 countries) to the full list: an answer for a country outside the table still fails closed, which is correct.
- The QuestionsInbox layout above the form.
- The Q-48 declarations merge.
- Housekeeping: `instructions/06_work_queue.md` has two rows with ID **Q-71** (l.60 mail follow-ups, l.61 this form). The Coordinator should renumber one.
