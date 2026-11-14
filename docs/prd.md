# JobScraper (personal): PRD r2 — cloud port, ATS resume tailor, auto-apply

**Status:** APPROVED r1 (2026-11-01; the owner delegated approval to the Coordinator: "ensure a full proper plan is created and approve it if acceptable"); r2 2026-11-02 · **Owner:** Benjamin · **Created:** 2026-11-01
**Changelog:** r2 (2026-11-02, planner, Q-09): folds in D-65 (answer memory = resolver tier 3; "I have this" → `data/applicant.yaml` `attested_skills`; reason codes `cancelled`, `mail_not_set_up`; `vault.py` in the foundation; `apply_flow` → `tailor_flow` edge; `app_events.by`) and D-67 (spike S-2: the LLM bullet and summary rewrite move to M22, `tailor.llm` off by default).
**Covers milestones:** M19 (cloud port), M20 (walking skeleton), M21 (MVP), M22 (breadth). M0–M17 are specified and recorded in `.claude/prds/jobscraper-v2.prd.md`, which stays the reference for the existing pipeline. M18 (frontend audit, worktree `../JobScraper-frontend`) is paused and not part of this PRD.

## 0. How to use this document (for agents)

- This file is the **source of truth for what to build** in M19–M22. Live status is in `instructions/02_status.md`, not here.
- Requirement IDs (`F-nn`, `NF-nn`) are referenced by designs, work packages, tests and status ticks. Never renumber; strike a dropped one through with the reason.
- Decision IDs in this PRD start at **D-50**, so they never collide with D-1…D-18 in the v2 PRD (or D-19…D-42 in the cloud repo).
- A work package is done only when its `Verify:` command passes. Don't trust a status flag; re-run the command.
- If a requirement is wrong or impossible, don't improvise. Raise a `question` in your outbox; the Coordinator takes it to the owner.
- Research behind this PRD: `docs/research/cloud_port_report.md`, `docs/research/resume_tailor_brief.md`, `docs/research/auto_apply_brief.md`. Read the section a requirement cites, not the whole file.

## 1. Problem

The owner finds roles with JobScraper, then applies by hand on each employer's careers site. Two costs remain:

1. **Every application is typed again.** The same details (name, contact, education, citizenship, race, notice period, salary, a dozen "no" declarations) go into a different form at each employer. Workday-style sites also need a new account and password per employer, plus an email verification.
2. **One resume for every job.** Recruiters search the ATS (applicant tracking system: the employer's hiring software) by the job description's own words. A resume that says "k8s" when the posting says "Kubernetes" ranks lower, and tailoring by hand for each role is slow.

Separately, the cloud fork (`jobscraper-cloud`) has fixed several engine problems that still affect the personal app: postings that flicker closed, roles missed past a 600-posting cap, fragile judging, runs that stay "running" after a cancel.

## 2. Users and needs

One user: the owner, a new-graduate computer engineer in Singapore, who runs JobScraper on their own Windows 11 PC (Edge as the default browser, local Ollama with Qwen3-14B on an RTX 5080). Their needs:

- "Apply to this role for me" from the Inbox, end to end, with no typing.
- A resume adapted to each role's wording, that passes ATS parsing and keyword search, without lying.
- One place to keep the details applications ask for, answered once.
- To know exactly what was sent to each employer, and why an application failed.

## 3. Goals and success metrics

| # | Goal | Metric (measured at the M21 gate) |
|---|---|---|
| G1 | Applications go out without typing | ≥ 70% of auto-apply attempts on Greenhouse, Lever and Ashby postings end `submitted` with a detected confirmation; ≥ 50% on Workday |
| G2 | Failures are honest | 100% of failed attempts carry a reason code, the step, and a screenshot; 0 duplicate submissions to the same posting |
| G3 | Tailored resumes cover the JD's words truthfully | JD keyword coverage rises on ≥ 90% of tailored resumes; 0 fabricated employers, titles, dates, degrees, numbers or tools (deterministic validator, golden cases A–C) |
| G4 | The engine stops losing roles | No posting is closed by one bad fetch (C-1); capped Workday and SmartRecruiters boards return their Singapore roles (C-2) |
| G5 | Nothing personal reaches the public repo | `git check-ignore` passes for every new personal-data path; a test asserts it |

**Non-goals:** a multi-user service (that is `jobscraper-cloud`); applying through LinkedIn, Indeed or any job board; beating anti-bot controls.

## 4. Scope

### 4.1 MVP (M19–M21)
- **Cloud port (M19):** engine fixes C-1 to C-8, C-22, C-23 and UI/UX items C-10, C-12 to C-18 from `docs/research/cloud_port_report.md` §1.
- **Applicant profile (M20–M21):** every detail applications ask, edited in the Profile tab, stored locally.
- **ATS resume tailor (M20–M21):** per job; a truthful, keyword-aligned DOCX (and PDF through Word) from a clean ATS template; temporary storage.
- **Auto-apply (M20–M21):** fully automatic for Greenhouse, Lever, Ashby and Workday, including Workday account creation, a password vault, and email verification through IMAP; batch apply from the Inbox; an audit of every answer.

### 4.2 Later (M22)
- Workable, SmartRecruiters and Recruitee adapters; a generic LLM-assisted adapter for custom pages, SAP SuccessFactors, Oracle and iCIMS (fill-and-submit with the same guards).
- Answer memory: correcting an answer in the audit view teaches the resolver.
- Cloud items C-9 (partial), C-19 (Settings chip editors), C-20 (line endings + CI bundle check), C-21 (measurement tools), C-24 (one job at a time, CLI included).
- Passwords written to the Default Edge profile directly, if spike S-1's sync route fails (via a browser extension).

### 4.3 Out of scope
- **Solving, bypassing or outsourcing CAPTCHAs**, stealth or fingerprint-spoofing plugins, rotating IPs. A CAPTCHA ends the attempt (F-27).
- Writing into Edge's password database (`Login Data`) directly. It is protected by Edge's app-bound encryption, and getting around that is malware technique (auto-apply brief §4.1).
- Job boards (LinkedIn Easy Apply, Indeed, JobStreet, MyCareersFuture) as application targets.
- A cloud LLM. Everything runs on local Qwen3 via Ollama.
- Inventing experience: no skill, employer, title, date, degree or number that isn't in the owner's resume or profile, in the resume or in any answer.
- Password-reset flows, two-factor sign-in on employer sites, and phone/SMS verification (these end the attempt with a reason).
- Porting anything multi-user from the cloud repo (auth, Postgres, quotas, deploy): report §2.

## 5. Requirements

Priority: P0 = the milestone can't ship without it, P1 = important, P2 = nice to have.

### 5.1 Cloud port (M19). Design: `docs/research/cloud_port_report.md` §1 (the report is the fast-track design)

**F-01 (P0) Postings close only on evidence (C-1).**
- WHEN a board fetch succeeds and a known posting is missing THE SYSTEM SHALL increment its `missed_runs`, and SHALL close it only when `missed_runs` reaches 2.
- IF a fetch returns zero postings or exactly the cap THEN THE SYSTEM SHALL close nothing for that company and SHALL log the reason.

**F-02 (P0) Capped boards are faceted to Singapore (C-2).**
- WHEN a Workday board reports more postings than the cap THE SYSTEM SHALL re-query it with its Singapore location facet; WHEN querying SmartRecruiters THE SYSTEM SHALL pass `country=sg`.
- IF a board is still capped after faceting THEN THE SYSTEM SHALL flag it in the coverage row and the run log.

**F-03 (P0) Robust judging (C-3).**
- THE SYSTEM SHALL send postings to the model as short ids `p1..pN`, restricted by an Ollama JSON schema.
- IF a batch answer is unreadable or truncated THEN THE SYSTEM SHALL halve the batch and retry; IF one posting fails alone 3 times THEN THE SYSTEM SHALL park it in `decision_failures` and stop sending it.
- IF 3 consecutive model calls return nothing THEN THE SYSTEM SHALL stop the run as an outage.
- IF the model accepts a posting without naming an allowed location THEN THE SYSTEM SHALL not accept it.
- Personal's own judge prompt, `judge.interests` and `rules.yaml` lists SHALL be kept (report §3a).

**F-04 (P0) Cancelled and crashed runs say so (C-4, C-5).**
- WHEN a run is cancelled or raises THE SYSTEM SHALL mark it `failed` with `stats.reason` ("cancelled" or the error text) before exiting.
- WHEN the web app finds a job record whose PID now belongs to another process THE SYSTEM SHALL treat the job as finished.

**F-05 (P1) Scheduling, logging, block reasons (C-6, C-7, C-8).**
- THE SYSTEM SHALL treat a company as due within a grace of min(12 h, 10% of the cycle), and SHALL stamp a batch with the run's start time.
- WHEN an API request fails with a 500 THE SYSTEM SHALL answer `{detail, request_id}` and log the traceback with that id; `GET /api/healthz` SHALL report the DB's health.
- WHEN a board answers with a Cloudflare, Akamai, captcha or rate-limit page THE SYSTEM SHALL record the failure as `BLOCKED` with that signature, not as a schema error.

**F-06 (P1) UI/UX ports (C-10, C-12 to C-18).**
- The Undo toast pauses on hover or focus and offers "Undo previous" (C-10).
- Inbox triage keys `s` `a` `x` `o` `j` `k`, ignored while typing, switchable off, alongside the existing `/` search (C-12, D-56).
- Job descriptions render headings, lists and paragraphs (never `v-html`) (C-13).
- Applications: inline notes; sort by company or recent activity (C-14). No follow-up chip.
- Companies: type or paste the list (C-15). An empty Inbox shows a getting-started checklist (C-16). Page heads on Runs, Profile and Settings; no empty badge slot (C-17). Plain-language errors and a boot screen with Retry (C-18).
- Personal's own UI work (the `/` search key, CountPicker, the Watched companies view, editable batch size and cycle) SHALL be kept (report §3a).

**F-07 (P2) Hardening (C-22, C-23).** Application URLs must be http(s); the company-list DOCX is checked for zip bombs; the filter CLI test no longer depends on the real profile.

### 5.2 Applicant profile

**F-10 (P0) One local applicant profile.**
- THE SYSTEM SHALL store the applicant profile in `data/applicant.yaml` (gitignored), validated against the schema in `docs/architecture/apply_design.md` (fields from auto-apply brief §6.2: identity, contact, Singapore status, race, NS, US self-ID, availability, pay, education, experience, skills, languages, links, documents, consents, declarations).
- WHEN the profile is first created THE SYSTEM SHALL pre-fill education, experience, skills and links from the resume, and SHALL mark those fields "from resume, check".
- THE SYSTEM SHALL hold the owner's standing declarations (D-55): not a politically exposed person, no audit or independence conflicts, no shareholdings or financial interests in employers, no relatives at employers, no criminal record, no bankruptcy, no regulatory or disciplinary history, no non-compete. Each one can be changed in the profile.

**F-11 (P0) Edit the profile in the Profile tab.**
- WHEN the owner opens Profile THE SYSTEM SHALL show an "Application details" form, grouped as in F-10, with a completeness meter that counts the fields auto-apply needs.
- WHEN the owner saves THE SYSTEM SHALL validate it (e.g. postal code is 6 digits, email has the right format, salary is a positive whole number) and SHALL name each invalid field.
- IF a field auto-apply needs is empty THEN THE SYSTEM SHALL list it before any auto-apply starts.

**F-12 (P1) Answer memory.** WHEN the owner corrects an answer in an application's audit view and ticks "Remember for this question" THE SYSTEM SHALL store the normalised question label with the answer and SHALL use it ahead of the LLM next time (resolver tier 3, after profile rules: F-32's order; D-65).

### 5.3 ATS resume tailor (key area KA-4). Design: `docs/architecture/tailor_design.md`, from `docs/research/resume_tailor_brief.md` §4–§5

**F-20 (P0) Master resume.**
- WHEN the resume changes THE SYSTEM SHALL parse it once into a structured master (contact, sections, entries, bullets with ids), and SHALL accept the parse only if every text leaf occurs in the extracted resume text (after whitespace normalisation).
- The master SHALL be cached by resume hash in `data/master_resume.json` (gitignored).

**F-21 (P0) Keyword map and coverage.**
- WHEN tailoring for a job THE SYSTEM SHALL extract the JD's terms (deterministic dictionary + a JSON-schema LLM call whose terms are kept only if they occur in the JD), mark each `required` or `preferred`, and classify each against the master as `present_exact`, `present_variant` or `missing`.
- THE SYSTEM SHALL compute "JD keyword coverage" (required weight 2, preferred 1) before and after tailoring, counting a term only in the JD's own spelling. It SHALL never be called an "ATS score".

**F-22 (P0) Truthful rewrite.**
- THE SYSTEM SHALL swap variant spellings to the JD's spelling (deterministic, alias list `config/aliases.yaml`) and reorder bullets and skills by relevance (M20–M21).
- LLM rewrite: M22, off by default (D-67). WHERE `tailor.llm` is on THE SYSTEM SHALL also rewrite bullets per entry and the summary with the LLM (JSON schema, temperature 0.25), after the validator gaps found by spike S-2 are closed.
- Employers, titles, dates, degrees and institutions SHALL never be sent to the model for rewriting and SHALL be copied verbatim.
- IF a rewritten bullet adds or drops a number, adds a tool or skill that is not in the master or attested, or loses its id THEN THE SYSTEM SHALL keep the original bullet and record why.
- Missing terms SHALL be reported, never added. WHEN the owner clicks "I have this" on a missing term THE SYSTEM SHALL save it in `data/applicant.yaml` under `attested_skills` (D-65; not the owner's protected `config/profile.overrides.yaml`) and use it from then on.

**F-23 (P0) Parse-safe output.**
- THE SYSTEM SHALL render a single-column DOCX from one ATS template (standard headings, no tables, text boxes, headers or footers) with the owner's page count as a ceiling. WHERE Microsoft Word is installed THE SYSTEM SHALL also produce a PDF through Word.
- WHEN a file is produced THE SYSTEM SHALL re-read it with the app's own text extractor and SHALL fail the tailoring if any heading, employer or date doesn't round-trip.
- Files SHALL be named `<First>_<Last>_Resume.docx|pdf`.

**F-24 (P0) Temporary storage (D-59).**
- THE SYSTEM SHALL write tailored files under `data/tailored/<job_id>/` (gitignored) and a row in a `tailored` table.
- THE SYSTEM SHALL delete draft files 7 days after creation (during the existing `purge`), and SHALL delete a **sent** file 30 days after its application reaches a closed status. The row (scores, missing terms, SHA-256) is kept.
- THE SYSTEM SHALL never write resume text to job logs; only counts and ids.

**F-25 (P0) Tailor from the UI.**
- WHEN the owner clicks "Tailor resume" on an Inbox or Applications role THE SYSTEM SHALL start a background `tailor` job and then show coverage before and after, the missing terms (with "I have this"), a side-by-side diff of changed bullets, and download links.
- Auto-apply SHALL tailor automatically when no current tailored file exists for the job (D-58).

### 5.4 Auto-apply (key areas KA-1, KA-2, KA-3). Design: `docs/architecture/apply_design.md`, from `docs/research/auto_apply_brief.md` §2–§8

**F-30 (P0) Start an application.**
- WHEN the owner clicks "Auto-apply" on a role in the Inbox ~~, or "Auto-apply to selected" on several,~~ (not built: the Inbox has no multi-select; the API takes up to 20 ids, `apply_queue_design.md` §1) THE SYSTEM SHALL add the role to the auto-apply queue and answer at once, and one background worker SHALL apply to the queued roles one at a time, in order, while the owner keeps adding roles. Runs → "Auto-apply queue" SHALL show the role being applied to, the roles waiting and the recently finished ones, with Pause, Resume, Clear and Remove (D-205).
- The owner's click is the only trigger: a search run, the shortlist and app start-up SHALL never start an attempt; "Try again" in Applications and "Retry" under Questions from applications count as fresh clicks. WHEN the app restarts with roles waiting THE SYSTEM SHALL keep them and SHALL pause the queue until the owner presses Resume (D-200, D-205).
- IF the role is already `applied` in Applications, or a twin of it is (M17 same-URL rule), or an attempt for it already reached `submitted` or `submitted_unconfirmed`, or it is already queued or being applied to THEN THE SYSTEM SHALL refuse it and say why (D-205).
- IF a required profile field is missing THEN THE SYSTEM SHALL refuse to start and list the fields (F-11).
- THE SYSTEM SHALL enforce the caps set in Settings → Apply, counted by Submit clicks on the Singapore calendar day, with 0 meaning no limit; the owner's values are no daily limit and at most 10 a day per employer. One attempt is in flight at a time (D-204).

**F-31 (P0) Detect the ATS and plan.**
- WHEN an attempt starts THE SYSTEM SHALL identify the ATS from the watchlist provider, then from the apply URL's patterns, and SHALL pick its adapter.
- WHERE the ATS publishes a form schema (Greenhouse `?questions=true`) THE SYSTEM SHALL build the full answer plan before the browser opens. Otherwise the adapter SHALL read the form from the page.
- IF no adapter matches THEN THE SYSTEM SHALL end the attempt as `unsupported_ats` (until M22's generic adapter).

**F-32 (P0) Resolve every answer (KA-2).** In this order, the first tier that answers wins:
1. the adapter's field map (name, email, phone, resume upload…);
2. a profile rule: the normalised question label matched against `config/questions.yaml` (synonyms → profile keys), with the profile value mapped onto an offered option;
3. answer memory (F-12);
4. a declaration rule (F-33);
5. the local LLM, given the label, the offered options, a minimal profile extract and the JD. It returns an option index, a value or `UNKNOWN`, through a JSON schema.
- THE SYSTEM SHALL fill a tier-5 answer only if it is one of the offered options or, for free text, passes the grounding check: every number, date, employer and skill in it occurs in the profile, master resume or JD.
- Free-text questions ("Why this company?", cover letter) SHALL be written by the LLM from the JD and the master resume, within the grounding check and the field's length limit.
- IF a **required** field ends `UNKNOWN` or fails grounding THEN THE SYSTEM SHALL end the attempt as `unanswerable_required` and name the question. An optional field is left blank.
- Every answer SHALL record its tier, source, confidence and, for tier 5, the model and prompt hash.

**F-33 (P0) Declarations.**
- WHEN a question is classified as a declaration (PEP, audit or independence conflict, shareholding, relatives, criminal record, bankruptcy, regulatory, non-compete, health) THE SYSTEM SHALL answer from the profile's standing declarations (F-10): "No" by default.
- `prior_employment_at_company` SHALL be deduced: "Yes" if the employer matches any entry in the profile's experience (internships included), otherwise "No". `previously_applied` SHALL come from JobScraper's Applications and attempts.
- Work authorisation, sponsorship, citizenship or PR, race, NS and US self-ID SHALL come from the profile, using "decline to self-identify" where the profile says so.

**F-34 (P0) Drive the browser (KA-1).**
- THE SYSTEM SHALL control Microsoft Edge through Playwright (`channel="msedge"`) with a persistent browser profile owned by JobScraper (`%LOCALAPPDATA%\JobScraper\apply-profile`), headed by default (D-53).
- THE SYSTEM SHALL fill fields the way a person's input would (type into inputs, choose from dropdowns, upload files), wait for the page to settle after each step, and work through multi-step wizards with the adapter's step map.
- THE SYSTEM SHALL upload the tailored resume (F-25), or the original resume if tailoring failed.
- THE SYSTEM SHALL save a screenshot of every step and of the final page under `data/apply/<attempt_id>/` (gitignored).

**F-35 (P0) Accounts and passwords (KA-3).**
- WHEN a site needs an account and the vault has none for that site THE SYSTEM SHALL create one with the profile's email and a generated password (20 characters, upper, lower, digit and symbol, adjusted by the adapter's password rules), and SHALL store it in Windows Credential Manager (service `jobscraper:<ats>:<tenant-host>`) **before** submitting the sign-up form.
- WHEN the vault has an account for the site THE SYSTEM SHALL sign in with it. IF sign-in fails THEN THE SYSTEM SHALL end the attempt as `login_failed` and SHALL not reset the password.
- The database SHALL record only that an account exists (ATS, tenant, email, created, verified), never the password.
- Into Edge: WHERE spike S-1 confirms Edge password sync works from the JobScraper profile THE SYSTEM SHALL save each new password in that profile so it syncs to the owner's Default profile. Otherwise Settings → Accounts SHALL offer "Export new passwords for Edge" (a CSV in Edge's import format, deleted after a confirmed import) and "Copy password" per account.

**F-36 (P0) Email verification through IMAP (D-52).**
- WHERE IMAP is configured (host, username, app password in Credential Manager) THE SYSTEM SHALL, when a site asks for email verification or a one-time code, read the mailbox read-only for messages that arrived after the attempt started, from the ATS's or employer's sender domain, and SHALL open the verification link or enter the code, waiting up to 5 minutes.
- IF no matching message arrives in time THEN THE SYSTEM SHALL end the attempt as `email_verification_timeout`.
- THE SYSTEM SHALL never delete, move or send mail, and SHALL open only links on the ATS's or employer's domain.

**F-37 (P0) Submit and confirm (D-51).**
- WHERE `apply.mode` is `auto` THE SYSTEM SHALL click the final Submit once the pre-Submit scan passes, with no further confirmation (the owner's Auto-apply click is the consent), then SHALL wait for the adapter's confirmation signal (confirmation URL, "thank you" text, or a status in the candidate portal). The owner's install runs `auto`; a fresh install defaults to `dry_run` (D-203).
- WHEN confirmation is detected THE SYSTEM SHALL set the attempt to `submitted`, set the role to `applied` in Applications (with an event "Applied by JobScraper"), and mark the tailored file `sent`. Until then the role SHALL show as queued or being applied to, never as applied (D-207).
- IF Submit was clicked but no confirmation appears within 60 s THEN THE SYSTEM SHALL set `submitted_unconfirmed`, SHALL never resubmit it automatically, and SHALL ask the owner to check.
- WHERE `apply.mode` is `dry_run` THE SYSTEM SHALL do everything except click Submit, and SHALL end `ready_to_submit`, leaving the filled form open for 10 minutes.

**F-38 (P0) Fail properly.**
- IF the attempt meets a CAPTCHA or bot challenge (reCAPTCHA, hCaptcha, Cloudflare Turnstile iframes or interstitials), an SMS or 2FA step, a closed posting, a page the adapter doesn't recognise, a validation error it can't fix in one retry, or an unexpected exception THEN THE SYSTEM SHALL stop all input, record the reason code, the step, the URL, a screenshot and the page HTML, and SHALL not submit.
- On `captcha`, the window SHALL stay open for `apply.captcha_wait_s` seconds (default 0) so the owner may finish it by hand; the attempt still ends `failed: captcha` unless confirmation is then detected.
- Failed attempts SHALL show in the role's panel with a one-line reason and "Open the posting" so the owner can apply by hand.

**F-39 (P0) Audit: what I told this employer.**
- THE SYSTEM SHALL store one row per field filled (verbatim label, field type, offered options, value, tier, confidence, rule or prompt id) for every attempt, kept as long as the application.
- WHEN the owner opens an application THE SYSTEM SHALL show "What I told this employer": the answers, the resume file sent, the screenshots, and the outcome.

**F-40 (P1) Apply settings.** Settings → Apply SHALL show each value and edit it in place, saved on change: mode (Automatic submit | Dry run; switching to Automatic submit asks once), applications a day and per employer (0 = no limit), show the browser window, the human-check wait (0–600 s) and write cover letters. These values SHALL be stored in the settings table and SHALL win over `config/config.yaml` from the next apply job (Q-111, Q-116). Settings → Accounts SHALL hold the connected accounts (email updates, the application mailbox, the apply browser, the local AI, the employer accounts list) and SHALL never send a stored password to the browser: ~~Copy password~~ dropped (ADR-0009); Export for Edge stays on the command line (`accounts export-edge`); entering the mailbox and employer passwords from the web is Q-103 (Q-100 Wave 2) (D-191, D-203, D-204).

**F-41 (P1, M22) More ATSs.** Adapters for Workable, SmartRecruiters and Recruitee; a generic adapter (LLM labels the page's fields, same resolver and guards) for custom pages, SuccessFactors, Oracle and iCIMS.

### 5.5 Non-functional

| ID | Requirement (measurable) | Pri |
|---|---|---|
| NF-01 | Privacy: `data/applicant.yaml`, `data/master_resume.json`, `data/tailored/`, `data/apply/` and the apply browser profile are never committed; a test runs `git check-ignore` on each | P0 |
| NF-02 | Secrets: passwords, the IMAP app password and mail-status account passwords live only in Windows Credential Manager; never in SQLite, YAML, logs, screenshots' file names, or LLM prompts | P0 |
| NF-03 | Local only: no cloud LLM; the web app still binds to 127.0.0.1 and answers only loopback Host headers | P0 |
| NF-04 | Layering: `tailor/` and `apply/` are stage packages; `apply_flow.py` is the orchestrator; `mailstatus/` is a stage package, `mailstatus_flow.py` is its orchestrator, and `imapread.py` is the foundation module that speaks IMAP; `web/` may not import it; only `store.py` has SQL and only `backends.py` talks to the model; `tests/test_layering.py` enforces it | P0 |
| NF-05 | Pace: one attempt at a time; actions at human pace (no artificial jitter for evasion); caps per D-61 | P0 |
| NF-06 | Idempotency: a posting is never submitted twice by the app (attempt state + Applications + twins) | P0 |
| NF-07 | Time: tailoring finishes in ≤ 90 s per job on the owner's PC; an auto-apply attempt (no account) in ≤ 4 min | P1 |
| NF-08 | The live app (port 8765, `data/jobscraper.db`) is never used for development; dev instances use a copied DB on port 8768 | P0 |
| NF-09 | Logs: the Developer tab shows the apply job's step-by-step log (no personal values, no passwords) | P1 |

### 5.6 Application status from email (key area KA-3). Design: `docs/architecture/mail_status_design.md` (MS), from `docs/research/mail_status_brief.md`; ADR `docs/architecture/adr/0007-mail-status-imap.md`

With the owner's opt-in per mailbox, JobScraper reads Gmail over IMAP, read-only, and updates tracked applications from employers' emails. Every change keeps a short quote from the email as evidence and can be undone. Owner request: D-150 (queue Q-60); design decisions D-151..D-154, D-156. A new status, `assessment` (tests, coding challenges, one-way video), sits between `applied` and `interviewing`. Section numbers in the table (§7, §14) refer to MS.

| ID | Requirement |
|---|---|
| F-50a | WHEN the owner gives a Gmail address and app password in Settings or with `mail accounts add`, and ticks the consent box, THE SYSTEM SHALL test a read-only login first. Only if the login succeeds SHALL it store the password in Credential Manager (`jobscraper:imap:imap.gmail.com`, user = address) and record the account with the consent time and consent-text version. IF the login fails THE SYSTEM SHALL store nothing and SHALL say why in plain words. |
| F-50b | WHERE the application mailbox (`apply.mail`, D-72) is set up THE SYSTEM SHALL offer it first, as "Use this mailbox", without asking for its password again. |
| F-50c | THE SYSTEM SHALL read a mailbox only while its switch is on. WHEN the owner disconnects it THE SYSTEM SHALL delete its cursor, its processed-message log, its open suggestions and its account row, and its vault entry too unless email verification (`apply.mail`) also uses it. |
| F-50d | WHILE the web app runs THE SYSTEM SHALL sync every mailbox that is switched on, at start-up and every `mail_status.interval_min` minutes, without taking the JobManager slot. A sync SHALL process every message after the cursor up to the newest, in UID order, in the mailboxes Gmail flags `\All` and `\Junk`. |
| F-50e | WHEN the app starts after being closed THE SYSTEM SHALL continue from the stored cursor. No message SHALL be skipped, and none SHALL be processed twice: X-GM-MSGID dedupes across mailboxes, Spam moves and UIDVALIDITY changes. |
| F-50f | WHEN a mailbox has no cursor yet THE SYSTEM SHALL start from the earliest open application's date minus 1 day, but no earlier than `first_sync_max_days` (180) before now. |
| F-50g | THE SYSTEM SHALL open mailboxes only with EXAMINE and fetch only with BODY.PEEK or header items. It SHALL never send STORE, COPY, MOVE, EXPUNGE, APPEND or SMTP, never mark mail read, never open a link from mail and never load remote content. |
| F-50h | THE SYSTEM SHALL fetch a message body only after the header gate passes: the sender is a hiring platform or a tracked employer, or the message is in a thread already matched to an application, and it is not bulk mail or job-board mail. |
| F-50i | THE SYSTEM SHALL never treat the owner's own sent mail, auto-replies, verification, security-code, account or password mail (D-85), job alerts, talent-community newsletters, job-board mail or recruiter outreach as a status. |
| F-50j | THE SYSTEM SHALL match a message to an application only through the signals in MS §7. WHEN several applications fit THE SYSTEM SHALL not choose one: it SHALL leave a suggestion listing them. |
| F-50k | THE SYSTEM SHALL classify with the deterministic phrase rules in `config/mail_rules.yaml` first. Only for gated, matched messages the rules can't decide SHALL it ask the local model. The model SHALL choose one fixed category, or `unknown`, and give a quote that code checks appears in the message. |
| F-50l | WHEN a confident, unique match points to a *forward* status THE SYSTEM SHALL apply it automatically, offer and rejected included, with `app_events.by = 'mail'` and an evidence row. It SHALL never move a status backwards and never override an owner change newer than the email. A forward move that isn't confident or unique SHALL become a suggestion. |
| F-50m | WHEN the owner clicks Undo on an email-made change that is still the application's latest event THE SYSTEM SHALL restore the previous status and its `applied_at`. The same message SHALL never apply again. |
| F-50n | WHEN the owner accepts a suggestion THE SYSTEM SHALL apply it, if the application's status hasn't changed since the suggestion was made. WHEN the owner dismisses it THE SYSTEM SHALL close it. |
| F-50o | THE SYSTEM SHALL show, per mailbox, when it was last checked, the result counts, the folders it reads, and any failure in plain words. It SHALL offer "Check now" and the CLI verb `mail sync`. |
| F-50p | IF Gmail refuses the login THEN THE SYSTEM SHALL pause that mailbox, SHALL not retry on the timer, and SHALL say how to fix it. IF the network is down or Gmail throttles THEN THE SYSTEM SHALL back off and try again later. |
| F-50q | IF All Mail is hidden from IMAP THEN THE SYSTEM SHALL read INBOX and Spam instead and SHALL say so. IF the model is unavailable or busy THEN THE SYSTEM SHALL keep using the rules and SHALL retry the undecided messages later. |
| F-50r | THE SYSTEM SHALL log only counts, codes, account ids and platform domains: never an address, display name, subject, body, quote or password. It SHALL store no bodies or links, and SHALL store a subject (≤ 120 characters) and a quote (≤ 200 characters) only on evidence rows. |
| F-50s | THE SYSTEM SHALL store a message's outcome and the cursor advance in the same transaction. |
| F-50t | THE SYSTEM SHALL take sender platforms, gates and phrases from `config/mail_rules.yaml`, so that a new sender or phrase needs no code change (MS §14). |

## 6. Key areas (these get the full design dossier)

| Area | Why it is key | Requirements |
|---|---|---|
| **KA-1 Auto-apply engine** (browser driver, adapters, attempt state machine, submit and confirmation) | Invisible failure modes (a half-filled submission, a double submission), terms-of-service and bot-control exposure, and everything else plugs into it | F-30, F-31, F-34, F-37, F-38, NF-05, NF-06 |
| **KA-2 Answer resolution and declarations** | Wrong answers are legal attestations to an employer; an LLM is involved; mistakes are invisible without the audit | F-32, F-33, F-39, F-12 |
| **KA-3 Accounts, vault and mailbox** | Credentials, mailbox access, and account creation on third-party sites; reading the owner's Gmail to update applications (F-50) | F-35, F-36, F-50, NF-02 |
| **KA-4 Resume tailor truthfulness** | A fabricated claim on a resume is costly and invisible; LLM rewriting | F-20 to F-24 |

All other parts (the cloud port, the profile form, settings, UI panels) use the fast track (`instructions/05_workflow.md` §3.2). The cloud port's design is `docs/research/cloud_port_report.md`.

## 7. Design overview

### 7.1 Current state (retrofit)

Python 3.12 (system interpreter, no venv), FastAPI + Vue 3 SPA (built bundle committed under `src/jobscraper/web/static/`), SQLite (`data/jobscraper.db`, `store.py` is the only SQL), Qwen3-14B through Ollama (`backends.py`). Layers: CLI → orchestrators (`pipeline.py`, `company_search.py`) → stages (`scheduler`, `scrape/`, `filter`, `decide`, `profile/`) → foundation (`store`, `config`, `net`, `backends`, `models`, `watchlist`). The web server starts slow work as background CLI jobs (`web/jobs.py`, kinds `run`, `profile`, `titles`, `companies`), one at a time. Full tour: `docs/OVERVIEW.md`; architecture: `docs/DESIGN.md`.

### 7.2 What is added

```
web (Profile: Application details · Inbox: Tailor / Auto-apply · Applications: What I told this employer · Settings: Apply, Accounts)
   │ HTTP /api  (routers: applicant.py, tailor.py, apply.py)
   ▼
CLI verbs: tailor <job_id> · apply <job_id>… [--dry-run] · applicant check     ← background job kinds "tailor", "apply"
   ▼
orchestrators: tailor_flow.py (master → keywords → rewrite → validate → render)
               apply_flow.py  (queue → detect → tailor → plan → resolve → browser/adapter → submit → record)
   ▼
stages:  tailor/ (master, jd_terms, mapping, rewrite, validate, render)
         apply/  (detect, plan, resolve, declarations, classify, browser, mail, ats/{greenhouse, lever, ashby, workday, …})
   ▼
foundation: store.py (+ tables tailored, apply_attempts, apply_answers, ats_accounts, answer_memory; column app_events.by)
            backends.py (+ JSON-schema `format` and temperature per call) · applicant.py (profile schema + load/save) · vault.py (Credential Manager) · config
```

- **Contracts** (written by the architect before any lane builds): `src/jobscraper/apply/contracts.py` (FormField, FormPlan, Answer, AttemptState, ReasonCode, AtsAdapter protocol) and `src/jobscraper/tailor/contracts.py` (MasterResume, Bullet, JdTerm, TailorResult).
- **Attempt state machine:** `queued → tailoring → planning → opening → [signing_in | signing_up → verifying_email] → filling(step n) → submitting → submitted | submitted_unconfirmed | ready_to_submit (dry run) | failed(reason)`.
- **Reason codes:** `captcha`, `bot_challenge`, `sms_or_2fa`, `login_failed`, `email_verification_timeout`, `mail_not_set_up`, `unanswerable_required`, `validation_error`, `page_unrecognised`, `posting_closed`, `unsupported_ats`, `cap_reached`, `duplicate`, `profile_incomplete`, `cancelled`, `error` (`cancelled` and `mail_not_set_up` added by D-65).
- **Layering notes (D-65):** `vault.py` sits in the foundation, not in `apply/`, because the web app needs it directly (Copy password, the IMAP password, the Edge export) and web/ may not import a stage. `apply_flow` may import `tailor_flow`: the one allowed orchestrator-to-orchestrator edge (for `tailor_for_apply`). `tests/test_layering.py` encodes both.
- **Layering notes (F-50, MS §2):** `mailstatus/` is a stage package, `mailstatus_flow.py` is its orchestrator, and `imapread.py` is the foundation module that speaks IMAP; `web/` may not import it. `apply/mail.py` uses `imapread.py` too. The web app's timer (`web/mailsync.py`) starts `python -m jobscraper mail sync` as a separate process instead of reading mail itself. `mailstatus_flow` adds no orchestrator-to-orchestrator edge.
- **New dependencies:** `playwright` (drives the installed Edge; no browser download), `keyring` (Windows Credential Manager), `pywin32` (Word → PDF, optional). IMAP uses the standard library.
- **Config:** `config/config.yaml` gains an `apply:` block (mode, caps, headed, captcha wait, profile dir) and a `tailor:` block (temperature, page ceiling, retention days). `config/questions.yaml` (question synonyms → profile keys) and `config/aliases.yaml` (term variants) are public, generic data. Personal values live only in `data/`.

## 8. Milestones

| Milestone | Delivers | Gate (checkable) | Requirements |
|---|---|---|---|
| **M19 Cloud port** (runs in parallel with M20 design) | Engine fixes and UI/UX items from the cloud fork | `python tests/run_tests.py` and `cd web; npx vitest run` pass; one real run on a copied DB (port 8768) closes no posting on an empty fetch and finds Singapore roles on a capped Workday board | F-01 to F-07 |
| **M20 Walking skeleton** | `python -m jobscraper apply <job_id> --dry-run` on one real Greenhouse posting: a hand-filled `data/applicant.yaml`, a deterministic tailored DOCX (variant swaps only), the plan from the Greenhouse schema, resolver tiers 1–5, Edge filled through Playwright, the resume uploaded, stopping at `ready_to_submit` with screenshots and audit rows | On 5 real Greenhouse postings the owner picks: every attempt ends `ready_to_submit` or a correct reason code, and the owner reads the audit and finds no wrong answer; then one real submission, triggered by the owner, ends `submitted` and the role shows as applied. For the owner's own clicks the dry runs no longer come first: `apply.mode` is `auto` (D-203) | F-10, F-20, F-21, F-22 (swaps), F-23, F-31, F-32, F-33, F-34, F-37, F-38, F-39 |
| **M21 MVP** | Profile form, tailor UI (scores, missing terms, diff, downloads) with TTL and the LLM JD-term extraction (the LLM rewrite is M22, D-67); Lever, Ashby and Workday adapters; vault, account creation, IMAP verification; batch apply, caps, audit view, settings | 10 real applications submitted automatically across at least 3 ATSs including Workday, with G1/G2 met; tailoring golden cases A–C pass; NF-01 test passes | F-11, F-22 to F-25, F-30, F-35 to F-37, F-40, NF-01 to NF-09 |
| **M22 Breadth** | More ATSs, generic adapter, answer memory, the LLM bullet and summary rewrite with a hardened validator (D-67), deferred cloud items | Per item | F-12, F-22 (LLM rewrite), F-41, C-9, C-19 to C-21, C-24 |

## 9. Risks and premises to validate

| # | Risk or premise | Impact | How we validate it | By when |
|---|---|---|---|---|
| R-1 | Playwright can drive Edge 156 headed on a dedicated persistent profile, and Edge's password manager and sync work in it (Playwright adds `--disable-sync` and a basic password store by default) | Without sync, passwords reach the Default Edge profile only through a CSV import | **Spike S-1** (1 h): launch, sign in by hand once, save a password on a test site, check it appears in the Default profile | Before M20 build |
| R-2 | Qwen3-14B rewrites bullets within the rules at temperature 0.25 in ≤ 90 s | Weak tailoring, or the validator rejects most rewrites | **Spike S-2**: golden cases A–C plus 3 real JDs; count validator rejections and time | Done 2026-11-02: no coverage gain over the swaps, validator gaps; see D-67 |
| R-3 | Greenhouse forms fill reliably (react-select dropdowns, file upload, reCAPTCHA stays invisible at human pace) | The walking skeleton stalls | **Spike S-3**: dry-run fill on 2 real Greenhouse postings, no submit | Before M20 build |
| R-4 | Gmail IMAP with an app password works for the owner's address (needs 2-Step Verification on) | No automatic verification; Workday attempts end `email_verification_timeout` | **Spike S-4** after the owner creates the app password (owner task) | Before the M21 Workday work |
| R-5 | Fully automatic submission sends a wrong answer (about 4% of 30-field forms are fully right at 90% per-field accuracy, auto-apply brief §1.2) | A wrong attestation or a poor application under the owner's name | The resolver prefers deterministic tiers; grounding check; `unanswerable_required` fails closed; ~~M20's gate reviews 5 dry runs before `auto` is switched on~~ (superseded for the owner's own clicks: `auto` is on and the first real submissions are also the filler's first live runs; Submit only after the pre-Submit scan passes); full audit (D-203) | M20 gate |
| R-6 | Workday's site terms forbid third-party apps without consent; ATS bot controls may flag or drop automated applications | Locked accounts, silently dropped applications | Owner's informed choice (D-54); human pace, caps, no evasion; the attempt fails on any challenge | Recorded at kickoff |
| R-7 | Merging M19's UI ports makes the paused M18 audit partly stale | M18 rework | M18 resumes from the new `personal`; its audit gaps are re-checked first (report §3b) | When M18 resumes |
| R-8 | Changing `personal` changes the app the owner uses every day | A broken daily app | Work in worktrees; dev DB copies on port 8768; smoke check on `personal` after each merge; the owner relaunches the app to pick up changes | Always |

## 10. Decisions, open questions and assumptions

| # | Decision | Options and recommendation | Decided by and date | Status |
|---|---|---|---|---|
| D-50 | Where the work lives | Personal app, branch `personal` (owner's request) | owner, 2026-11-01 | DECIDED |
| D-51 | Who clicks Submit | Fully automatic; fail properly on CAPTCHA or unknown errors; unknown questions answered by grounded deduction (owner). Research recommended a human Submit (auto-apply brief §7); mitigations in R-5 | owner, 2026-11-01 | DECIDED |
| D-52 | Email verification | IMAP with an app password stored in Credential Manager, read-only (owner) | owner, 2026-11-01 | DECIDED |
| D-53 | Browser route | Playwright + a dedicated Edge profile, headed (Chromium 136+ ignores remote debugging on the default profile; brief §3). An Edge extension is revisited in M22 only if S-1's sync route fails | Coordinator, 2026-11-01 | DECIDED |
| D-54 | Workday | Included, fully automatic, per the owner's choice of full automation. Its site terms forbid unapproved third-party apps (brief §7); the owner accepts that risk for their own applications. Caps apply | Coordinator, from D-51; 2026-11-01 | DECIDED (owner may revisit) |
| D-55 | Standing declarations | All "No" (the owner has no PEP status, audit or independence conflicts, stakes in any company, etc.), stored in the profile; prior employment and previous applications are deduced from data, not answered "No" blindly | owner + Coordinator, 2026-11-01 | DECIDED |
| D-56 | Triage keys | Cloud's map (`s` `a` `x` `o` `j` `k`) plus personal's `/` search; M18's audit map is superseded | Coordinator, 2026-11-01 | DECIDED |
| D-57 | Account creation | Automatic, without a per-employer confirmation (follows D-51) | Coordinator, from D-51 | DECIDED |
| D-58 | Tailored resume use | Automatic: no review gate before use; the validator is the guard; the diff is always viewable | Coordinator, from D-51 | DECIDED |
| D-59 | Tailor retention | Drafts 7 days; a sent file until its application closes + 30 days; rows kept | Coordinator, 2026-11-01 | DECIDED |
| D-60 | Tailor output | A clean ATS template; DOCX always, PDF through Word (installed); keep the original page count; temperature 0.25; target-title headline on; alias list editable | Coordinator, 2026-11-01 | DECIDED |
| D-61 | Caps | 10 submissions a day, 2 per employer a day, one in flight; editable in Settings | Coordinator, 2026-11-01 | DECIDED |
| D-62 | Team and process | Standard team (coordinator, researcher, architect, planner, software-engineer, tester, reviewer), no security reviewer; product-first testing; the Coordinator merges into `personal` and may push | owner, 2026-11-01 | DECIDED |
| D-63 | Cloud UI ports vs paused M18 | Port the UI items to `personal` now (M19); M18 rebases onto the result when resumed. Skip C-11 (M18 already has a better version) | Coordinator, 2026-11-01 | DECIDED |
| D-65 | Design-time PRD fixes (architect, Q-04) | Answer memory is resolver tier 3; "I have this" skills go to `data/applicant.yaml` `attested_skills`; golden case B: Excel is an exact match; reason codes `cancelled`, `mail_not_set_up`; `vault.py` in the foundation; `apply_flow` may import `tailor_flow`; `app_events.by` column | Coordinator, 2026-11-02 | DECIDED |
| D-67 | Tailor LLM rewrite after spike S-2 | The per-entry LLM rewrite added no coverage over the deterministic swaps (54/54 runs) and the validator has gaps (verb/seniority upgrades, number words, unknown tools). `tailor.llm: false` by default; M21 ships deterministic swaps, reordering, render, storage/TTL and UI (plus LLM JD-term extraction); the LLM bullet and summary rewrite and the validator fixes move to M22 | Coordinator, 2026-11-02 | DECIDED |

**Open questions:** none blocking. The owner will be asked for, as owner tasks: the email address to apply with and the profile values (M20); a Gmail app password (M21, S-4); one manual sign-in to the Microsoft account in the JobScraper Edge profile if S-1 shows sync works.

**Assumptions taken instead of asking:**
- Applications use one email address (the owner's), not plus-addressed variants.
- Expected salary is a single monthly SGD figure from the profile.
- The NRIC is not stored unless the owner adds it; a form that requires it ends `unanswerable_required`.
- Headed Edge is the default, so the owner can see what happens; headless is a setting.
- "Stored temporarily" (tailored resume) is satisfied by D-59.

## 11. Glossary

- **ATS (applicant tracking system):** the employer's hiring software that hosts the application form and stores applicants (Greenhouse, Lever, Ashby, Workday…).
- **Tenant:** one employer's instance of an ATS, e.g. `dbs.wd3.myworkdayjobs.com`. Workday accounts are per tenant.
- **JD:** job description.
- **Coverage:** the weighted share of the JD's terms that appear, in the JD's spelling, in the resume.
- **Declaration / attestation:** a yes/no statement about yourself that the employer may rely on (PEP, conflicts, criminal record).
- **PEP (politically exposed person):** someone with a prominent public role, or their family or close associates; banks must ask.
- **EEO / self-ID:** US equal-employment questions (gender, race/ethnicity, veteran, disability), often shown by global ATSs.
- **Playwright:** a library that controls a real browser from code.
- **Credential Manager:** the Windows store for passwords, encrypted per Windows user.
- **IMAP / app password:** the protocol for reading a mailbox; a Gmail app password is a separate 16-character password for one app.
- **Dry run:** an attempt that fills everything but doesn't click Submit.
- **Grounding check:** a code check that every fact in a generated answer exists in the owner's data or the JD.

## 12. Sources

- `docs/research/cloud_port_report.md` (2026-11-01): cloud repo diff, port candidates, risks.
- `docs/research/resume_tailor_brief.md` (2026-11-01): ATS screening facts, prior art (Resume-Matcher, Apache-2.0), method, golden cases.
- `docs/research/auto_apply_brief.md` (2026-11-01): prior art, per-ATS flows, browser and password routes, Singapore questions, terms of service, architecture.
