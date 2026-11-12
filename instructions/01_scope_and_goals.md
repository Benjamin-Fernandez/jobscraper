# 01: Scope and goals (the project's constitution)

**Changes to this file need the owner's approval.** Record each change as a decision in `02_status.md` §4.

## 1. Vision

JobScraper is the owner's personal job-search machine: it watches ~300 employers' careers sites, shortlists new-grad roles in Singapore that fit them, and, from M20, **tailors the resume to each role and applies on the employer's site automatically**, so a role in the Inbox becomes a submitted application without typing. It runs only on the owner's PC.

## 2. Users

One user, the owner: a new-grad computer engineer (NTU) in Singapore, comfortable with software, not with ATS internals. The app is not multi-user; the multi-user product lives in the separate `jobscraper-cloud` repo and never merges with this one.

## 3. Primary deliverable and success criteria

The deliverable: from the Inbox, "Auto-apply" submits a truthful, tailored application on Greenhouse, Lever, Ashby and Workday sites and records exactly what was sent. Success (PRD §3): ≥ 70% of attempts on the single-page ATSs (≥ 50% on Workday) end submitted with a confirmation; 100% of failures carry a reason and a screenshot; 0 duplicate submissions; every answer sent is recorded with its basis (profile, resume, a standing default, or marked as an assumption, D-208); nothing personal in git.

## 4. Constraints

- Windows 11, system Python 3.12, Microsoft Edge 156 (the owner's default browser), Word installed, Ollama with Qwen3-14B on an RTX 5080. **No cloud LLM, no paid services.**
- The GitHub repo `Benjamin-Fernandez/jobscraper` is **public**: all personal data stays in gitignored `data/`, and secrets in Windows Credential Manager.
- The live app (port 8765, `data/jobscraper.db`) runs from this checkout and must keep working after every merge.
- Respect employers' bot controls: CAPTCHAs and challenges end an attempt; no evasion. Human-paced, capped volume (D-61).

## 5. Principles (non-negotiable design rules)

1. **The model fills the form from the owner's own facts (owner, 2026-11-12, D-208; replaces "truthful by construction, fail closed").** The local model reads the whole applicant profile and the resume, nothing in them is treated as private, and it answers every field of an application by deriving sensibly from them; a required field is never left unanswered. Declaration-type questions (politically exposed person, relationships, conflicts, criminal record and the like) default to No. An answer the profile and resume do not cover is the model's best sensible answer and is recorded as an assumption for the owner to review. Code still decides what only code knows: which file is uploaded, the account identity and passwords (never shown to the model), never applying twice, and stopping at bot checks.
2. **Fail properly.** An attempt that can't finish stops input, records a reason code, the step and a screenshot, and never submits half an application or submits twice.
3. **The model answers; code handles the mechanics (D-208; replaces "deterministic first, LLM last").** Wording matches and rules are hints to the model, never a reason to leave a field empty.
4. **Keep the layering:** stages don't import each other; orchestrators wire them; only `store.py` has SQL; only `backends.py` talks to the model.
5. **Everything auditable:** every answer sent is stored with its source and shown in "What I told this employer".
6. **Personal data never leaves the machine** and never enters git.

## 6. Out of scope

CAPTCHA solving or bot-check evasion; writing into Edge's password database directly; job boards (LinkedIn, Indeed, JobStreet, MyCareersFuture) as targets; cloud LLMs; inventing experience; password resets, 2FA or SMS verification on employer sites; anything multi-user from the cloud repo. (PRD §4.3.)
