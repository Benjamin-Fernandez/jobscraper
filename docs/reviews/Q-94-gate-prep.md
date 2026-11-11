# Review: Q-94 gate prep (branch `eng/Q-94-gate-prep`, `git diff 44fb107..HEAD`)

Reviewer, 2026-11-10. KA-2 answer resolution (WP-A04) plus small KA-1 changes. No CRITICAL or HIGH finding in the diff itself.

**Verdict: MERGE WITH FOLLOW-UPS.** WP-A04 meets the spec and is fail-closed for every country the resolver can name. Two gaps are listed below (F1 MEDIUM, new with the broader synonyms; F2 pre-existing in an untouched row, HIGH in effect). Neither blocks this merge. Fix both before the M20 gate (D-83).

## Verification (last lines quoted)
- `-k q94` -> `14/14 passed  (-k 'q94')`
- `-k apply_resolve` -> `46/46 passed  (-k 'apply_resolve')`
- `-k questions` -> `72/72 passed  (-k 'questions')`
- `-k locks` -> `5/5 passed  (-k 'locks')`
- `-k layering` -> `13/13 passed  (-k 'layering')`
- Probes (scripts in the session scratchpad, not committed): the real `config/questions.yaml`, the real resolver, each label asked as a Yes/No dropdown. Two profiles: P1 = authorised `{SG: true, default: false}`, sponsorship `{SG: false, default: true}` (any SG leak shows as the opposite answer); and the tester's sample profile (`{SG: true, US: false}`, sponsorship `{SG: false}`, so other countries get the standing answer).

## 1. WP-A04 probes (label -> row, country, answer, source -> right?)
P1 unless stated. "default" = the map's `default` key.

| Label | Row | Country | Answer | Source | Right? |
|---|---|---|---|---|---|
| authorised to work in the United Kingdom | authorised | GB | No | .default | yes |
| authorized to work in the US / the U.S. | authorised | US | No | .default | yes (sample: .US = No) |
| legally authorised to work in Canada | authorised | CA | No | .default | yes |
| Are you a Singapore Citizen or PR? | residency `#sg_citizen_or_pr` (not a work-rights row) | SG | Yes | residency_status | yes, untouched row |
| authorised to work in the EU | authorised | EU | No | .default | yes |
| authorised to work anywhere in Asia | authorised | none named, job SG | Yes | .SG | **no** (F1) |
| ...in the country where this job is located / in this country / right to work in the location of this role | authorised | job SG | Yes | .SG | yes (spec 8.2 step 2) |
| ...in the US or Singapore | authorised | SG+US | stop | `work rights differ: SG, US` | yes (fail-closed, no model) |
| ...in Singapore or the United Kingdom | authorised | SG+GB | stop | conflict | yes (sample profile: both Yes, so it answers Yes) |
| ARE YOU AUTHORIZED TO WORK IN THE US? | authorised | US + job SG | stop | conflict | yes (Q-30 F4 / D-76) |
| AUTHORISED TO WORK IN SINGAPORE? | authorised | SG | Yes | .SG | yes |
| ...in India (not Singapore) | authorised | IN+SG | stop | conflict | yes (safe) |
| Will you need sponsorship, now or in the future, to work without restrictions? | none: `exclude: [without]` removes the sponsorship row, no authorised synonym matches | n/a | falls to tier 3/5 | model sees `work_rights` | yes, fail-closed (the old SG row answered "No" here) |
| Can you work in the US without sponsorship? | authorised, `a and not s` | US | No | .default | yes |
| Can you work in Singapore without sponsorship? | authorised | SG | Yes | .SG | yes |
| Are you able to work in the UK without visa sponsorship? | authorised | GB | No | .default | yes |
| WILL YOU REQUIRE SPONSORSHIP TO WORK IN THE US? | sponsorship | US + job SG | stop | conflict | yes |
| Will you require sponsorship to work in Canada / Hong Kong; require a work permit to work in Germany | sponsorship | CA / HK / DE | Yes | .default | yes |
| Do you require an employment pass to work in Singapore | sponsorship | SG | No | .SG | yes |
| authorised to work in Spain / Mexico / South Africa | authorised | none named, job SG | Yes | .SG | **no** (F1) |
| authorised to work worldwide / in Southeast Asia / in APAC | authorised | none named, job SG | Yes | .SG | **no** (F1) |
| require sponsorship to work in Poland | sponsorship | none named, job SG | No | .SG | **no** (F1) |
| authorised to work in the United Arab Emirates | authorised | AE | No | .default | yes |
| authorised to work in North America | authorised | US (via the "america" alias) | No | .default | right by accident |

**Synonym check.** The kept phrases ("authorised to work in singapore", "authorized to work in the united states", ...) cannot force SG on a label naming another country. A synonym only picks the row, never the country: the country is read from the label by `resolve.label_countries` (`resolve.py:125`) and applied in `_tier2_country_bool` (`resolve.py:968`). A label naming the UK and Singapore gets both codes, so it stops or answers consistently. The kept country phrases only help the row win a score tie and are harmless.

**`exclude: [without]`.** It fires at any label length (`Rule.score`, `resolve.py:229`). The sponsorship row never claims a "without" label; the authorised row owns "without sponsorship / visa sponsorship / requiring sponsorship".

## 2. Consumers of the old keys
- Locks L4: `locks.py:178-184` takes the `country_bool` branch first (`_tier2_country_bool`). OK. `WORK_RIGHTS_PREFIXES` / `_work_rights_bool` (`locks.py:46,151-188`) are now reached only by the fixture rules (`tests/fixtures/apply/questions.sample.yaml:5,10`). Harmless dead path in production (F4).
- `resolve.py` loader and `COUNTRY_BOOL_KEYS` (`:63`): the real file loads and `-k apply_resolve` passes.
- **facts.py fallback (`facts.py:454-461`).** `rule_match` now returns None for `.<CC>` paths, so `_profile_fit` takes the `work_right` value and `_kind` returns "bool". I called `facts.fact_value("profile:singapore_status.authorised_to_work.SG|US|default", ...)` and the sponsorship paths against both the OLD (`44fb107`) and the NEW rules file. The six results were identical (Yes, No, No, Yes, No, Yes). No regression. (Pre-existing and unchanged: a cited `.SG` ref answers a UK label with the SG value, because the fact path ignores the label's country. The guard layer has to catch that. Not part of this diff.)
- `applicant.REQUIRED_PATHS` (`applicant.py:121`) already uses the map keys. OK.
- `tests/test_apply_questions.py` "cfl" US-or-Canada case: passes (`-k questions`).

## 3. Re-pointed excludes tests
They guard everything they guarded, and more. The two synthetic `Rule.score` tests are untouched, so the Q-29 mechanism (a one-token exclude acts on a long label) is still pinned. The three real-file tests were replaced, not weakened: for each of 11 countries they now assert the selected row, `label_countries == {code}`, source `.<code>`, and the answer from that country's key while SG says the opposite, with a stub backend that must not be called. "UK is never answered from SG" is kept through the `.standing` / `.default` source assertions. They also assert the rows carry no country excludes and the sponsorship row excludes only `without`. No weakening found.

## 4. Q-43 (`applicant.py:696-701,759-760`)
- Only a string that, lower-cased, trimmed and space-collapsed, equals present/current/now/ongoing/to date becomes None. A real date, a date object, a null, an empty string and a missing key are untouched (a missing key is not created). Idempotent. Applies to experience and education.
- Experience downstream is correct: `experience_months` treats an empty end as now (`:2204-2206`); `current_employment` (`declarations.py:75`) and the CURRENT_COMPANY canonical (`resolve.py:847`) read a blank end as current; `facts._block_from_entry` renders "present". Tailor dates come from the resume parser (`tailor_flow.py:474`), not from `normalise`, so they are unaffected.
- Education: "Present" now becomes empty. Before, it was a validation error and counted as filled; now `_filled("education")` (`:1251`) reports the entry as lacking an end. Still blocked, with a different message; `graduation_year` ignores it either way (F3, LOW).

## 5. F11
Pure refactor. `L1_KEPT_NOTE` text is unchanged and now defined once in `locks.py:39` (`pagefill.py:58` aliases it). `FACT_SOURCES` is defined once in `guards.py:59` (`pagefill.py:74` aliases it) and replaces three inline triples in `guards.py`. `pagefill` already imported `guards` and `locks` (`pagefill.py:48,50`), so there is no new import edge, and `-k layering` is 13/13. No other copy of the string or triple remains in `src/`. The tester's identity pins cover it.

## Findings

**F1 (MEDIUM, new with the broader synonyms): a country or region the resolver cannot name is answered with the SINGAPORE right.**
`resolve.py:68-96` has 24 countries plus 4 alias groups; `work_rights_countries` (`resolve.py:956-966`) then falls to `ctx.job_country` (SG). The new generic synonyms ("authorised to work", "eligible to work", "right to work") now select the row for any such label, where the old rows (narrow, country-suffixed) left it to the model. Failing labels: "Are you authorised to work in Spain?" (also Mexico, South Africa), "...worldwide", "...in Southeast Asia", "...in APAC", "Will you require sponsorship to work in Poland?" -> SG value, source `.SG`. With the sample profile the answer equals the standing one, so it hurts when the owner sets a `default` different from SG; "worldwide" / "Asia" is wrong whatever the profile says. This follows the spec (8.2 step 2: no country named -> the job's country), so the spec wins and nothing blocks. Roles are Singapore roles, so exposure is small. Suggested fix (architect amends 8.2, then engineer): when the label has an "in <word>" work-location tail that names no recognised country, region or "this / the country / location / where" phrase, stop with note `work rights: country not recognised` (never the model, same as `conflict`). At minimum add region words (asia, apac, emea, worldwide, globally, anywhere, north america) as a stop list and extend `COUNTRIES` (ES, MX, PL, ZA, SE, IT, ...).

**F2 (HIGH in effect, PRE-EXISTING, outside this diff; does not block Q-94): "Are you a US citizen or permanent resident?" and "Are you a Canadian citizen or permanent resident?" answer Yes.**
`config/questions.yaml:194-225`: the `sg_citizen_or_pr` yes_if row lists bare "citizen or permanent resident", "citizen or pr", "citizen pr" and so on with no Singapore requirement and no other-country exclude. The same result on `44fb107` confirms it predates this change. The residency row is out of D-75 scope (QD 8.2 last paragraph), so I only record it. Fix as a Q-95 data change: add the other countries and demonyms (united states, us, usa, american, canadian, canada, uk, british, ...) to that row's exclude, or drop the unguarded bare synonyms. Worth doing before the gate: a wrong Yes to a US-citizenship question is a false statement on an application.

**F3 (LOW):** an education `end` typed "Present" is now an empty end, so the Profile reports a missing education end instead of an invalid date (same fail-closed effect).

**F4 (LOW):** `locks._work_rights_bool` / `WORK_RIGHTS_PREFIXES` are dead in production; remove them with the fixture later.

**F5 (LOW):** D-178 is cited in `llm_fill_design.md:455` but I found no D-178 entry in `docs/` or `instructions/` other than the handover's "next D-178" note; record it in `02_status.md` section 4.

## Other checks
- No personal data or secrets in the diff (added lines scanned for emails, names, passwords; the new fixture is synthetic). No CAPTCHA or bot-check change. No SQL or model-call layering change.
- No submit-path code touched, so no double-submission risk. The D-178 line matches the code (`CallLog` is created per `fill_page`, `pagefill.py:128`).
- Disagreement with the spec: none that I would overrule. F1 is a spec gap, not a deviation.
