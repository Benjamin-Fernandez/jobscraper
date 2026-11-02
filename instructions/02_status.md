# 02: Status (live)

**Last updated:** 2026-11-02 by Coordinator
**States:** `TODO` · `IN PROGRESS` · `DONE` · `BLOCKED` · `AWAITING APPROVAL` · `DEFERRED`
**Priority:** P0 = MVP-critical · P1 = important · P2 = nice to have

## Now / Next (≤ 10 lines; history goes to `docs/planning/session_log.md`)

- **Now:** M20 build. Merged and pushed: lanes T, P, V part 1, B; int/Q-30 (D-74 Profile form + F-13 questions, D-75 work rights, tier-3 memory; review APPROVE WITH FIXES), 752/752 Python, web 253+1. Running: spike S-5b (LLM-driven Workday at the 2 D-77 employers), Q-38 tester (int/Q-36 oracles), Q-39 engineer (review F2/F6/F7).
- **Next:** merge int/Q-36 (owner profile → errors 0) and Q-39; S-5b report → Q-35 D-78 redesign (folds in review F1/F3/F4); then V2 accounts, V4–V7, WP-Q1b (after F1), WP-F1 fixtures; M20 gate.
- **Blocked on the owner:** nothing.

## 1. Milestones

| Milestone | Goal | Gate (checkable) | Status |
|---|---|---|---|
| M19 Cloud port | Engine fixes + UI/UX items from jobscraper-cloud | Both suites pass; a real run on a copied DB shows C-1/C-2 behaviour | DONE 2026-11-02 (cab10af: 410/410 Python, 220+1 skip web; real 6-company run on a DB copy; dev web 8768 healthz ok) |
| M20 Walking skeleton (re-scoped D-70) | Workday end to end (account, verification, wizard, submit) + Greenhouse with MyGreenhouse autofill + deterministic tailored resume + audit | Real automatic submissions at the 2 owner-approved Workday employers end `submitted`; Greenhouse dry runs end `ready_to_submit`; `apply show` audit has no wrong answer | IN PROGRESS |
| M21 MVP | Profile form, full tailor, Lever/Ashby/Workday, vault, IMAP, batch apply | 10 real automatic submissions across ≥ 3 ATSs incl. Workday; G1/G2; golden cases A–C; NF-01 test | TODO |
| M22 Breadth | More ATSs, generic adapter, answer memory, deferred cloud items | Per item | TODO |

## 2. Requirement status (definitions in `docs/prd.md` §5)

| ID | Requirement (short) | Pri | Status | Notes |
|---|---|---|---|---|
| F-01 | Postings close only on evidence (C-1) | P0 | DONE | M19 engine lane |
| F-02 | Capped boards faceted to Singapore (C-2) | P0 | DONE | M19 engine lane |
| F-03 | Robust judging (C-3) | P0 | DONE | M19 engine lane |
| F-04 | Cancelled/crashed runs say so (C-4, C-5) | P0 | DONE | M19 engine lane |
| F-05 | Grace, logging, block reasons (C-6–C-8) | P1 | DONE | M19 engine lane |
| F-06 | UI/UX ports (C-10, C-12–C-18) | P1 | DONE | M19 UI lane |
| F-07 | Hardening (C-22, C-23) | P2 | DONE | M19 |
| F-10 | Applicant profile (data/applicant.yaml) | P0 | DONE | M20 lane P merged |
| F-11 | Profile form in the Profile tab | P0 | TODO | M20 (D-74) |
| F-12 | Answer memory | P0 | TODO | M20 (D-74) |
| F-13 | Questions to answer: unanswered application questions become profile fields in the web app | P0 | TODO | M20 (D-74) |
| F-20 | Master resume | P0 | DONE | M20 lane T merged |
| F-21 | Keyword map and coverage | P0 | DONE | M20 lane T merged |
| F-22 | Truthful rewrite | P0 | TODO | swaps M20, LLM M21 |
| F-23 | Parse-safe DOCX/PDF | P0 | DONE | M20 lane T merged |
| F-24 | Temporary storage | P0 | TODO | M21 |
| F-25 | Tailor from the UI | P0 | TODO | M21 |
| F-30 | Start an application, duplicates, caps | P0 | TODO | M20 CLI, M21 UI |
| F-31 | Detect ATS and plan | P0 | TODO | M20 |
| F-32 | Resolve every answer | P0 | DONE | M20 lane P merged |
| F-33 | Declarations | P0 | DONE | M20 lane P merged |
| F-34 | Drive the browser | P0 | TODO | M20 |
| F-35 | Accounts and passwords | P0 | TODO | M21 |
| F-36 | Email verification (IMAP) | P0 | TODO | M21 |
| F-37 | Submit and confirm | P0 | TODO | M20 |
| F-38 | Fail properly | P0 | TODO | M20 |
| F-39 | Audit: what I told this employer | P0 | TODO | rows M20, view M21 |
| F-40 | Apply settings | P1 | TODO | M21 |
| F-41 | More ATSs, generic adapter | P1 | TODO | M22 |
| NF-01–NF-09 | Privacy, secrets, local, layering, pace, idempotency, time, dev isolation, logs | P0/P1 | TODO | |

## 3. Completed

| Date | Item | By | Evidence |
|---|---|---|---|
| 2026-11-01 | Research: cloud port report, tailor brief, auto-apply brief | researcher ×3 | `docs/research/*.md` |
| 2026-11-01 | PRD r1 | Coordinator | `docs/prd.md` |

## 4. Decision register

Decided items aren't reopened. If facts change, raise a new decision that references the old one. D-50 onward are this PRD's decisions (`docs/prd.md` §10 has the full text).

| # | Decision | Options and recommendation | Decided by and date | Status |
|---|---|---|---|---|
| D-01 | Autonomy level | The Coordinator decides routine matters, merges into `personal` and may push; asks for scope, destructive, paid, real submissions during development | owner, 2026-11-01 | DECIDED |
| D-02 | Testing profile | Product first | owner ("prioritising a working model first"), 2026-11-01 | DECIDED |
| D-50 | Where the work lives | Personal app, branch `personal` | owner, 2026-11-01 | DECIDED |
| D-51 | Submit | Fully automatic; fail properly; grounded deduction for unknown questions | owner, 2026-11-01 | DECIDED |
| D-52 | Email verification | IMAP, app password in Credential Manager | owner, 2026-11-01 | DECIDED |
| D-53 | Browser route | Playwright + dedicated Edge profile, headed | Coordinator, 2026-11-01 | DECIDED |
| D-54 | Workday | Included, automatic; terms risk noted | Coordinator from D-51 | DECIDED |
| D-55 | Standing declarations | "No", in the profile; prior employment/applications deduced from data | owner + Coordinator | DECIDED |
| D-56 | Triage keys | Cloud map + `/` | Coordinator | DECIDED |
| D-57 | Account creation | Automatic | Coordinator from D-51 | DECIDED |
| D-58 | Tailored resume use | Automatic, validator-guarded, diff viewable | Coordinator from D-51 | DECIDED |
| D-59 | Tailor retention | Drafts 7 d; sent until closed + 30 d | Coordinator | DECIDED |
| D-60 | Tailor output | Clean template; DOCX + PDF via Word; page ceiling; temp 0.25 | Coordinator | DECIDED |
| D-61 | Caps | 10/day, 2/employer/day, 1 in flight | Coordinator | DECIDED |
| D-62 | Team and git | Standard team, no security reviewer; merge and push allowed | owner | DECIDED |
| D-79 | Lenient profile reading (Q-36, Coordinator per D-78) | `normalise` on load/validate/save: enums any case/spacing + synonyms, quoted yes/no/true/false → bool (supersedes QD §8.1 strictness for these words), "prefer not to say" → decline, dates from YAML dates / "Mar 2020" / "03/2020" / DD/MM/YYYY (SG order); ambiguous forms still rejected. Entry dates (education/experience) keep a full day when given (D-68 A-4 computed_facts) | Coordinator, 2026-11-03 | DECIDED |
| D-78 | LLM-driven form filling (owner, 2026-11-03) | Owner: "Calls should be made to the LLM to do the filling up of the forms. It should not be manual entry as manual entry hardcoded is vulnerable to systems changing… the LLM should be the one filling the information up, deciding whether the information comes from applicant.yaml / resume"; "if there are options to 'import from resume', it should always choose that". The local model fills every field from a generic page read (label, type, options) using applicant.yaml + resume text + saved answers; adapters keep only navigation; resume-import options are always taken (reverses D-70's Workday rule), then the model checks every field. Guard rails stay: standing answers (D-55, D-75) as facts, grounding, unknown required → stop + Questions inbox, CAPTCHA stop, caps, NF-06. Profile validation becomes lenient (case, YAML booleans, synonyms). Spike S-5b (real Workday at Kyndryl + PayPal, D-77) is the first prototype; architect redesign Q-35 | owner, 2026-11-03 | DECIDED |
| D-77 | Workday test go-ahead (owner, direct, 2026-11-03) | Owner: "You will create the account for me, fill up the information and submit all automatically. I will manually check the email to see if you have submitted." Spike S-5 re-runs at Kyndryl (DevOps Engineer) + PayPal (Software Engineer) (GlobalFoundries dropped: applications moved to Eightfold): real accounts, IMAP verification, full wizard, automatic Submit, but only when every required answer comes from the profile/resolver (an unknown required answer stops that employer, never guessed). Starts after the owner fills `data/applicant.yaml` | owner, 2026-11-03 | DECIDED |
| D-76 | Q-30 tester questions | Bare all-caps `US` in the verbatim label = United States (lowercase `us` = pronoun); D-75 `conflict` wins over `no_option_fits`; a choice question's first answer may be employer-scoped only (base picks empty allowed); adopt the tester's assumed call shapes (assign_key, parse_naming, naming_user_prompt, upsert_question). QD text amended later (architect/planner batch) | Coordinator, 2026-11-03 | DECIDED |
| D-75 | Work rights always assumed (owner, 2026-11-03) | Every work-authorisation question = Yes and every sponsorship question = No for any country unless the profile says otherwise per country (`authorised_to_work`/`requires_sponsorship` gain a `default`); the model's grounding facts include it. Residency/citizenship and work-pass type still come from the profile. Folded into Q-30 | owner, 2026-11-03 | DECIDED |
| D-74 | Profile in the web app + dynamic fields (owner, 2026-11-03) | Profile → Application details form (WP-W1, W5) moves into M20. New F-13: questions an application can't answer are captured and shown in the Profile tab as new fields; the owner's answer is stored locally and reused by the resolver (answer memory, F-12 brought forward); waiting attempts can be retried. The model may only name/group questions, never answer them there. Design Q-30 | owner, 2026-11-03 | DECIDED |
| D-73 | Lane V points | Foundation modules may import `apply.contracts`/`tailor.contracts` only (layering rule, Q-28); accept engineer choices: emailed code = next non-blank line; `[Gmail]/Spam` unquoted; `mail set-password --host/--user` also save to the settings table; `mail test --backup` without a backup mailbox tests the main one and says so | Coordinator, 2026-11-03 | DECIDED |
| D-72 | Application mailbox | Owner switched the application Gmail account (address kept out of the repo); no backup email (`contact.backup_email` empty; the D-70 backup path stays in code but is inert); old Credential Manager entry deleted | owner, 2026-11-03 | DECIDED |
| D-71 | Lane P open points | Accept the engineer's stricter choices (fixed-mapping fields never reach tiers 2/4/5; checkbox/email/phone/date/URL/typeahead never reach the model; required cover letter may); `backup_email` added to the template (architect to fold into §5.4); `ResolveContext.job_title` additive field → architect (Q-27) | Coordinator, 2026-11-02 | DECIDED |
| D-70 | Workday first; MyGreenhouse autofill | Owner 2026-11-02: Workday is the biggest problem and must work; Greenhouse uses "Autofill with MyGreenhouse" (owner signs in once in the JobScraper Edge profile) then fills the empty fields; the tailored resume always replaces an autofilled one. Lane V (vault, accounts, IMAP, Workday wizard) moves from M21 into M20; spike S-5 = real Workday flow at 2 employers with the owner's email (owner allowed real accounts AND automatic submission there); a backup email is used when the primary is already registered | owner, 2026-11-02 | DECIDED |
| D-69 | Tester's testability items | Clicked Submit ends only submitted/submitted_unconfirmed (NF-06); apostrophes kept in labels; `current_employee_at_company` deduced; validator counts standalone numbers only; tester's assumed signatures adopted; fixture paths per tests/fixtures | Coordinator, 2026-11-02 | DECIDED |
| D-68 | Planner gaps A-1..A-5 | A-1 resolver gets the alias dictionary for grounding; A-2 apply_flow passes resume text (extract_text or tailor master) in the resolver context; A-3 CLI `apply show`; A-4 experience months = merged intervals, internships count, whole months; A-5 `tailor.llm_terms` (default on, M21) separate from `tailor.llm` (off, M22) | Coordinator, 2026-11-02 | DECIDED |
| D-67 | Tailor LLM layer | Spike S-2: LLM bullet rewrite added 0 coverage over deterministic swaps (54/54 runs), ~6 s/resume, validator gaps found. `tailor.llm: false` by default; M21 tailor is deterministic (swaps, reordering, render, storage, UI); LLM bullet + summary rewrite and validator fixes move to M22 | Coordinator, 2026-11-02 | DECIDED |
| D-66 | Local-network-fault guard | Count only regular due companies; probation failures never abort a batch (pre-existing flaw found in the M19 check: 6 ok + 11 probation failures aborted run #30 on a DB copy) | Coordinator, 2026-11-02 | DECIDED |
| D-65 | Design-time PRD fixes (architect, Q-04) | Answer memory is resolver tier 3 (F-32 order wins over F-12's "tier 2"); "I have this" skills go to `data/applicant.yaml` `attested_skills`, not the protected overrides file; golden case B: Excel is an exact match; new reason codes `cancelled`, `mail_not_set_up`; `vault.py` in foundation; `apply_flow` may import `tailor_flow`; `app_events.by` column. Planner folds these into the PRD (Q-09) | Coordinator, 2026-11-02 | DECIDED |
| D-64 | Cancelling a run | 30 s grace for runs (5 s other jobs); after a hard kill the web app marks the run row failed "cancelled (killed)" | Coordinator, 2026-11-02 | DECIDED |
| D-63 | Cloud UI ports vs M18 | Port to `personal` now; M18 rebases later; skip C-11 | Coordinator | DECIDED |

## 5. Known issues and verification items

| # | Item | Trust level | Status |
|---|---|---|---|
| K-1 | Research briefs: claims marked K or "unverified" in each brief's last section | assumption | open; spikes S-1 to S-4 settle the design-critical ones |
| K-2 | 62 of 257 Inbox roles had no stored JD on 2026-10-23 (45 Greenhouse); tailoring needs the JD | verified then, not re-checked | open; the apply flow fetches the JD when missing (design) |
