# 01: Scope and goals (the project's constitution)

**Changes to this file need the owner's approval.** Record each change as a decision in `02_status.md` §4.

## 1. Vision

JobScraper is the owner's personal job-search machine: it watches ~300 employers' careers sites, shortlists new-grad roles in Singapore that fit them, and, from M20, **tailors the resume to each role and applies on the employer's site automatically**, so a role in the Inbox becomes a submitted application without typing. It runs only on the owner's PC.

## 2. Users

One user, the owner: a new-grad computer engineer (NTU) in Singapore, comfortable with software, not with ATS internals. The app is not multi-user; the multi-user product lives in the separate `jobscraper-cloud` repo and never merges with this one.

## 3. Primary deliverable and success criteria

The deliverable: from the Inbox, "Auto-apply" submits a truthful, tailored application on Greenhouse, Lever, Ashby and Workday sites and records exactly what was sent. Success (PRD §3): ≥ 70% of attempts on the single-page ATSs (≥ 50% on Workday) end submitted with a confirmation; 100% of failures carry a reason and a screenshot; 0 duplicate submissions; 0 fabricated claims; nothing personal in git.

## 4. Constraints

- Windows 11, system Python 3.12, Microsoft Edge 156 (the owner's default browser), Word installed, Ollama with Qwen3-14B on an RTX 5080. **No cloud LLM, no paid services.**
- The GitHub repo `Benjamin-Fernandez/jobscraper` is **public**: all personal data stays in gitignored `data/`, and secrets in Windows Credential Manager.
- The live app (port 8765, `data/jobscraper.db`) runs from this checkout and must keep working after every merge.
- Respect employers' bot controls: CAPTCHAs and challenges end an attempt; no evasion. Human-paced, capped volume (D-61).

## 5. Principles (non-negotiable design rules)

1. **Truthful by construction.** Code decides facts; the LLM only rewords and chooses among offered options, and every generated fact must trace back to the owner's resume, profile or the JD (grounding check). When unsure, fail closed.
2. **Fail properly.** An attempt that can't finish stops input, records a reason code, the step and a screenshot, and never submits half an application or submits twice.
3. **Deterministic first, LLM last** in answer resolution (field map → profile rule → memory → declarations → LLM).
4. **Keep the layering:** stages don't import each other; orchestrators wire them; only `store.py` has SQL; only `backends.py` talks to the model.
5. **Everything auditable:** every answer sent is stored with its source and shown in "What I told this employer".
6. **Personal data never leaves the machine** and never enters git.

## 6. Out of scope

CAPTCHA solving or bot-check evasion; writing into Edge's password database directly; job boards (LinkedIn, Indeed, JobStreet, MyCareersFuture) as targets; cloud LLMs; inventing experience; password resets, 2FA or SMS verification on employer sites; anything multi-user from the cloud repo. (PRD §4.3.)
