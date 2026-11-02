# 02: Status (live)

**Last updated:** 2026-11-02 by Coordinator
**States:** `TODO` · `IN PROGRESS` · `DONE` · `BLOCKED` · `AWAITING APPROVAL` · `DEFERRED`
**Priority:** P0 = MVP-critical · P1 = important · P2 = nice to have

## Now / Next (≤ 10 lines; history goes to `docs/planning/session_log.md`)

- **Now:** M20 build of the D-78 LLM form filler (design READY; lanes N + R merged, 090daf8). `int/Q-35-M` = lane M + architect COMPOSE_NEEDED/Q-45 design (3a99dce), tester adding pins there; lane R adapting R3. D-77 both done: tenant A submitted (S-5b), Kyndryl submitted 2026-11-02 (Q-41, "Applied"). Live app: Workday still `unsupported_ats` until N6a.
- **Next:** tester pins (incl. Q-46 a–c) → merge `int/Q-35-M` (vitest + bundle) → R3 review + merge → N6a (incl. Q-46 e) → N6b → M20 gate (5 Greenhouse dry runs + owner-approved Workday postings, D-83). Q-45 compose build. Q-44 refresh-from-resume. Q-47 tailor page trim.
- **Blocked on the owner:** nothing. Optional: Cantonese levels; whether a standing answer for NDA/restrictive-agreement questions should exist (Kyndryl's optional one was left blank).

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
| D-90 | Application status from email (owner, 2026-11-02; new scope F-50, queue Q-60) | Owner: "have the user's email login (with user's permission) with the application. If the user logins and connects their email (assume gmail only), when the application is running, it will go through the user's email from the last email that is read by the program, up till the current most recent email. This is to update the status of applications of the jobs applied to automatically… You should work in a separate branch." Built on branch `int/Q-60-mail-status` (worktree `.claude/worktrees/feat-Q-60`) as a key area (KA-3 mailbox + the application record): brief → design → test plan → build → review. Merges into `personal` only with the owner's go-ahead. IDs Q-60 / D-90 / F-50 chosen to avoid the concurrent session's numbering | owner, 2026-11-02 | DECIDED |
| D-91 | Q-60 stage-A outcomes (brief `docs/research/mail_status_brief.md`) | (a) Access: IMAP with a Gmail app password in Credential Manager (D-52 path), read-only (EXAMINE + BODY.PEEK, never STORE/COPY/MOVE/EXPUNGE/APPEND/SMTP), headers first, a body only past the sender/keyword gate; the transport sits behind one boundary so the Gmail API (`gmail.readonly`) can replace it if Google withdraws app passwords (documented, not built); XOAUTH2 rejected. (b) One or more Gmail accounts, each switched on by the owner in the app (the "permission"); the application mailbox (D-72) first. (c) "Automatically" (D-90): a confident, unique match to a *forward* status is applied without asking, offer and rejected included; never backwards, never over an owner change newer than the mail, anything else → a suggestion; every change shows its evidence and can be undone. (d) Never open links or load images from mail; never mark mail read; verification/security-code mail is never a status. (e) Mailboxes found by special-use flags (`\All`, `\Junk`), not hard-coded names | Coordinator, 2026-11-02 (from D-90's words + the brief) | DECIDED |
| D-92 | Q-60 rules v1 questions (researcher WP-R1) | (1) Mail from a platform of `kind: assessment` (HireVue, Codility, HackerRank…) never decides `interview`: a rule-tier `interview` verdict from such a sender is read as `assessment`, because an assessment vendor's "interview invitation" is a one-way recorded one (MS §6.4); live interviews arrive from the employer or a scheduler. Built in WP-S1 `classify` (code, a few lines), pinned by the tester. (2) Assessment-centre and superday invitations count as `interview` (people on the other side). (3) The account gate may hold the phrase "confirm your email"; only the bare word "confirm" is banned (MS §6.2) | Coordinator, 2026-11-02 | DECIDED |
| D-87 | Declaration-type questions (owner, 2026-11-02, after Kyndryl's optional restrictive-agreements question was left blank) | The owner is a new graduate with no such ties: these questions default to No / none / not applicable, never blank and never a question to the owner. (1) Restrictive agreements of any kind (non-compete, NDA/non-disclosure/confidentiality, non-solicitation, stock option or restricted stock grants, government conflict-of-interest restrictions) → No. (2) Government or military employment that excludes mandatory military service → No (a question that includes NS stays with `ns_status`). (3) Disability questions from any country → the profile's disability answer (today `us_self_id.disability_status`), program-filled (S). (4) A label matching several declaration classes whose values all agree → that answer instead of AMBIGUOUS. The values live only in data/applicant.yaml (S); design amendment + build = Q-48. Extends D-55, the owner's "affiliations are No". |
| D-86 | Q-35 lane M review F7, F8, F9 | Tightenings: F7 a fact-cited option is accepted only when the program's own `fact_value`/`fit_*` maps to it, never on the model's evidence alone; F8 `field_sig` hashes the shown value with the HMAC key used for `facts_used_hash`. F9: until a cover-letter compose WP exists (Q-45), a required composed-text field (cover letter, "why join") stops the attempt and is captured in the Questions inbox with reason `compose_needed` | Coordinator, 2026-11-02 | DECIDED |
| D-85 | Greenhouse emailed security code: how to read it (lane N question; S-4 open) | The code is the only line (trimmed) of 6–12 letters/digits after the "security code" sentence; zero or several candidates → fail closed. Not "must contain a digit": Greenhouse codes are random alphanumerics and ~24% of 8-character codes have none. Revisit when spike S-4 or a real email shows the format | Coordinator, 2026-11-02 | DECIDED |
| D-84 | Q-35 re-check MEDIUMs R1–R4 (design clarifications, built in lane M) | R1: G12 "other employers" excludes the applicant's own employers (profile experience + resume entries), so composed texts may name them. R2: the G5 second opinion also covers a Yes/No accepted because the model's option matched the program's (G2(d)). R3: every entry description, including entries the program adds, goes through the recheck. R4: the relevance check never maps the applicant's own contact/identity facts onto fields about another person (emergency contact, referee/reference, next of kin, spouse/partner, guardian) → unknown → Questions inbox. The architect folds the text into `llm_fill_design.md` at the next design touch | Coordinator, 2026-11-03 (reviewer's fixes) | DECIDED |
| D-83 | M20 gate under D-78 (Q-35 review M10, M13) | Gate count stays as the PRD/ADR-0003 say: 5 Greenhouse dry runs (BP §7 fixed to match). D-77 under D-78: before each automatic real submission the Coordinator reads the dry-run audit (`apply show`) row by row; a required value kept from the resume import is never submitted unless G3 passed; the gate's Workday submissions need fresh owner approval of the postings (the D-77 pair is used up by S-5b + Q-41) | Coordinator, 2026-11-03 | DECIDED |
| D-82 | Fixed answers stay deterministic under D-78 (Q-35 open question 2) | Declarations, D-75 work rights, consents, S facts and the owner's `extra` answers are locks the model sees as context but can't override (ADR-0003 fail-closed; ADR-0006 §3). The model still decides the source of every other field (D-78). Owner may revisit; moving locks to the model needs an ADR-0003 change | Coordinator, 2026-11-03 (architect's recommendation) | DECIDED |
| D-81 | NF-07 deviation for Workday (Q-35 open question 3) | A Workday attempt with the local 14B model takes ~5–6 min (S-5b: ~50 s for a 54-field page); accept it and raise the attempt timeout to 900 s for Workday only; revisit after the first real runs (`max_fields_per_call`, caching). Conditions (Q-35 review M11): Greenhouse stays ≤ 4 min; the 900 s deadline excludes the IMAP verification wait (F-36, ≤ 5 min); the deadline is checked between chunks so a timeout stops before typing; both ATSs measured at the gate | Coordinator, 2026-11-03 | DECIDED |
| D-80 | Second D-77 Workday application | Finish it with the S-5b spike tooling as soon as the owner fills the missing field (the owner asked for both applications to be done automatically; postings close), rather than holding it for the built engine. The M20 gate proves the built engine on the next owner-triggered applications | Coordinator, 2026-11-03 | DECIDED |
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
