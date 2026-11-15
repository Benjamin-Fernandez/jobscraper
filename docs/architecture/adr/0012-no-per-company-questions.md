# ADR-0012: No per-company questions on the Profile page; a per-meaning counter proposes a detail after more than 15 employers; corrections live with the application

**Status:** accepted (owner D-215, 2026-11-15); revised 2026-11-15 after the design review `docs/reviews/Q-127-profile-questions-design.md` and the Coordinator's D1-D5. **Design:** `docs/architecture/q127_profile_questions_design.md`. **Supersedes in part:**
- QD §4 and §10: question capture shown as owner-facing cards;
- LFF §6.3 "Answered for you" and the owner-fact / consent stop cards;
- ADR-0005's "the DB holds the question queue" as something the owner works through. `extra:` stays the store of the owner's answers.

## Context
Under the live `strict` filler, a required field that code could not prove an answer for became a `questions` card at its first sighting. The card was keyed by that employer's exact wording, named the company, and sat above the owner's details on the Profile page. The owner's live data: 24 open cards, all from one attempt at one employer, 18 of them `no_rule`, with the facts already in the profile.

The always-answer filler (`int/Q-121`, ADR-0011) answers those fields, but it still puts per-wording cards on the same page: "Answered for you", and owner-fact or consent stops. D-215 forbids any question tied to a company on the Profile page. It allows one exception: a question seen in more than 15 different applications that needs a new section under the owner's details.

## Decision
1. **R1.** The Profile page shows only the owner's details, under any fill policy. Per-application facts go to the application: what was sent, each answer's basis, the assumed ones, and "Use a different answer next time" live in Applications → What was sent / What was filled.
2. **Counter per meaning.** A question counts toward a proposal only when it was **required** and the details and the resume could not answer it (a strict stop, an assumed answer, or a no-field owner fact). It is grouped by **topic**:
   - a fixed key for the four no-field owner facts (A1 class);
   - the same normalised label already mapped;
   - else a provisional slug, merged by the local model's naming **after** the attempt has ended and the browser is closed, never during it.

   A topic the model maps to an existing profile field (`topics.profile_path`) is never proposed; it only shows "Needed by {n} applications" on that field while it is empty.
3. **The threshold** is a config value: `apply.topics.count_by: employer | job` (default **employer**) and `apply.topics.min_count` (default **16**, i.e. more than 15). A proposal is one field under "More about you", with no company and no wording, and only for a topic named by the model or by class (never a provisional slug); its title must hold no employer name, no `?`, and at most 60 characters. A full national ID is never proposed. The owner adds it or dismisses it. **An added field is saved as `extra.<topic>` with `labels: []` and `promoted: true`:** it reaches forms only through the model's briefing, never as an exact-label answer.
4. **Corrections** ("Use a different answer next time") are written to `extra` for the exact qualified label only:
   - an entry that already holds exactly that label is updated; a label shared with other wordings or a promoted entry is refused (409);
   - otherwise a new key is slugged from the label, never a `questions` row's key and never through the model's `same_as`, and no other entry changes;
   - refused for answers that follow the owner's details: profile, standing and default sources, and the declaration, consent, marketing, work-rights, sponsorship, self-ID and owner-fact classes (the class is stored on the audit row as `apply_answers.field_class`);
   - the default scope is the employer of that application.

   They are listed under Settings → Apply → "Answers you corrected". `strict` stays the code default until the go-live commit and then the rollback, shown as "Stop when unsure"; it shows no cards and recovers from the application's own view.
5. **A blocking fact with no field** (passport number, bank details, another ID) waits for the threshold like any other topic (Coordinator D4). Until then, each application that needs it stops before typing, and its row says why.
6. **Storage reuses** `questions` + `question_sightings` as the sightings log: a `topic` column, plus one new `topics` table for status (Release 2, schema v10; Release 1 adds only `apply_answers.field_class`, v9). Nothing is deleted: the 24 cards become counting topics at 1 employer each, and the 3 answered keep working as remembered answers.
7. **Delivery (Coordinator D1).** Release 1 (no cards, What was sent, the rebuilt Profile) is built on `int/Q-121` and reaches `personal` in one scrubbed squash with the always-answer filler: one visible go-live. `fill_policy: always` is its own last commit; owner D-216 means the first Auto-apply click after it sends for real, with no trial runs. Release 2 (the counter) follows, invisibly.

## Options considered
| Option | Why not chosen |
|---|---|
| Keep the cards behind a filter or a collapsed group | Still per-company text on the Profile page (R1), and still unbounded |
| Count per wording (today's `sig` / key) | Every employer words it differently, so a common fact is never proposed and the log only grows |
| Count with the A1 field classes only | Most such questions are `ordinary`, so classes cannot tell "notice period" from "driving licence" |
| A hand-kept table of canonical questions | Cannot know tomorrow's questions; maintenance for every new form |
| New `gap_*` tables instead of reusing `questions` | Duplicates the capture, naming and sighting machinery, and loses the existing 24 rows' history; reuse costs one column and one table |
| Count distinct job ids as the default | One employer's many roles share one form and could cross 15 alone, which is exactly the company-specific question D-215 excludes. Kept as `count_by: job` if the owner prefers |
| Give a promoted field the wordings it was seen under as labels | Tier 3 would answer every one of those wordings verbatim, so one wrong merge would put a wrong answer on many forms; with `labels: []` a wrong merge only gives an odd proposal |
| Surface a blocking no-field fact on the Profile after 3 employers | A per-company question on the page before the owner's threshold, which D-215 forbids (D4) |

## Consequences
- **Good:**
  - The Profile page is bounded by the owner's own facts.
  - Every application carries its own record and a way to correct it.
  - A common question can become a real field without code changes (QD §6.3 promotion, now built), and a wrong grouping never changes an answer.
  - Retry no longer depends on answering cards.
- **Accepted:**
  - A fact with no field that blocks applications (a passport number) stops up to 15 employers' forms before anything is proposed (D4). It is visible on each row, in the Overview "To do", in the queue's same-fact pause, and in the Coordinator's `apply topics` printout. A full national ID is never proposed, so such forms always stop.
  - Topic grouping by the local model can merge or split wrongly; it only moves a counter and a proposal's wording, never an answer.
  - The old question routes stay for one release: `GET /api/questions` returns its full old shape with nothing in it, the writers answer 410.
  - Remembered answers can carry an employer's name (scope) and wording (title); they are listed in Settings, not on the Profile page.
- **Rollback:** `fill_policy: strict` (revert one config line; no data change). Hiding the cards needs no rollback, because the cards' rows stay in the store.
