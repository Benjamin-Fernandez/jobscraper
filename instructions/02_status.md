# 02: Status (live)

**Last updated:** 2026-11-01 by Coordinator
**States:** `TODO` · `IN PROGRESS` · `DONE` · `BLOCKED` · `AWAITING APPROVAL` · `DEFERRED`
**Priority:** P0 = MVP-critical · P1 = important · P2 = nice to have

## Now / Next (≤ 10 lines; history goes to `docs/planning/session_log.md`)

- **Now:** kickoff done (PRD r1 approved under the owner's delegation). M19 port lanes, the browser spike (S-1 + S-3) and the auto-apply design (KA-1 to KA-3) start in parallel.
- **Next:** tailor design (KA-4) and spike S-2; test plans and build plans for M20; then the M20 walking skeleton build.
- **Blocked on the owner:** nothing yet. Coming: the applicant profile values and the email to apply with (M20); a Gmail app password (M21).

## 1. Milestones

| Milestone | Goal | Gate (checkable) | Status |
|---|---|---|---|
| M19 Cloud port | Engine fixes + UI/UX items from jobscraper-cloud | Both suites pass; a real run on a copied DB shows C-1/C-2 behaviour | TODO |
| M20 Walking skeleton | `apply <job_id> --dry-run` on Greenhouse, deterministic tailored DOCX, audit | 5 owner-picked Greenhouse postings end `ready_to_submit` or a correct reason; the owner finds no wrong answer; one owner-triggered real submission ends `submitted` | TODO |
| M21 MVP | Profile form, full tailor, Lever/Ashby/Workday, vault, IMAP, batch apply | 10 real automatic submissions across ≥ 3 ATSs incl. Workday; G1/G2; golden cases A–C; NF-01 test | TODO |
| M22 Breadth | More ATSs, generic adapter, answer memory, deferred cloud items | Per item | TODO |

## 2. Requirement status (definitions in `docs/prd.md` §5)

| ID | Requirement (short) | Pri | Status | Notes |
|---|---|---|---|---|
| F-01 | Postings close only on evidence (C-1) | P0 | TODO | M19 engine lane |
| F-02 | Capped boards faceted to Singapore (C-2) | P0 | TODO | M19 engine lane |
| F-03 | Robust judging (C-3) | P0 | TODO | M19 engine lane |
| F-04 | Cancelled/crashed runs say so (C-4, C-5) | P0 | TODO | M19 engine lane |
| F-05 | Grace, logging, block reasons (C-6–C-8) | P1 | TODO | M19 engine lane |
| F-06 | UI/UX ports (C-10, C-12–C-18) | P1 | TODO | M19 UI lane |
| F-07 | Hardening (C-22, C-23) | P2 | TODO | M19 |
| F-10 | Applicant profile (data/applicant.yaml) | P0 | TODO | M20 |
| F-11 | Profile form in the Profile tab | P0 | TODO | M21 |
| F-12 | Answer memory | P1 | TODO | M22 |
| F-20 | Master resume | P0 | TODO | M20 |
| F-21 | Keyword map and coverage | P0 | TODO | M20 |
| F-22 | Truthful rewrite | P0 | TODO | swaps M20, LLM M21 |
| F-23 | Parse-safe DOCX/PDF | P0 | TODO | M20 |
| F-24 | Temporary storage | P0 | TODO | M21 |
| F-25 | Tailor from the UI | P0 | TODO | M21 |
| F-30 | Start an application, duplicates, caps | P0 | TODO | M20 CLI, M21 UI |
| F-31 | Detect ATS and plan | P0 | TODO | M20 |
| F-32 | Resolve every answer | P0 | TODO | M20 |
| F-33 | Declarations | P0 | TODO | M20 |
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
| D-65 | Design-time PRD fixes (architect, Q-04) | Answer memory is resolver tier 3 (F-32 order wins over F-12's "tier 2"); "I have this" skills go to `data/applicant.yaml` `attested_skills`, not the protected overrides file; golden case B: Excel is an exact match; new reason codes `cancelled`, `mail_not_set_up`; `vault.py` in foundation; `apply_flow` may import `tailor_flow`; `app_events.by` column. Planner folds these into the PRD (Q-09) | Coordinator, 2026-11-02 | DECIDED |
| D-64 | Cancelling a run | 30 s grace for runs (5 s other jobs); after a hard kill the web app marks the run row failed "cancelled (killed)" | Coordinator, 2026-11-02 | DECIDED |
| D-63 | Cloud UI ports vs M18 | Port to `personal` now; M18 rebases later; skip C-11 | Coordinator | DECIDED |

## 5. Known issues and verification items

| # | Item | Trust level | Status |
|---|---|---|---|
| K-1 | Research briefs: claims marked K or "unverified" in each brief's last section | assumption | open; spikes S-1 to S-4 settle the design-critical ones |
| K-2 | 62 of 257 Inbox roles had no stored JD on 2026-10-23 (45 Greenhouse); tailoring needs the JD | verified then, not re-checked | open; the apply flow fetches the JD when missing (design) |
