# Prior art: reuse decisions (M19–M22)

Summary of the verdicts in the three research briefs. Each line links back to the brief that holds the evidence (URL, licence, activity, date checked 2026-11-01).

| Candidate | What it is | Licence | Verdict | Used for | Evidence |
|---|---|---|---|---|---|
| `jobscraper-cloud` @ `019e975` and later kernels | The owner's own multi-user fork | private, own | **Reuse** (port hunks, not files) | M19: C-1 to C-8, C-10, C-12 to C-18, C-22, C-23 | `cloud_port_report.md` §0–§1 |
| Resume-Matcher (srbhr) | Open-source resume ↔ JD matcher, Ollama support | Apache-2.0 | **Adapt** (scoring weights, truthfulness check, "I have this" confirmation) | KA-4 tailor | `resume_tailor_brief.md` §3 |
| O\*NET technology skills | Public skill/tool vocabulary | CC BY 4.0 | **Reuse** as part of the JD-term dictionary | KA-4 | `resume_tailor_brief.md` §3 |
| YAKE | Keyword extractor | AGPL | **Reject** (licence) | — | `resume_tailor_brief.md` §3 |
| KeyBERT | Embedding keyword extractor | MIT | **Reject** (heavy, needs embeddings) | — | `resume_tailor_brief.md` §3 |
| Jobscan, Teal, Rezi, ResumeWorded | Commercial tailoring tools | proprietary | **Learn from** (coverage UX, missing-term report) | KA-4 UI | `resume_tailor_brief.md` §3 |
| career-ops | Open-source apply assistant (Playwright) | see brief | **Learn from** (Playwright patterns, per-ATS quirks, stops before Submit) | KA-1 | `auto_apply_brief.md` §1 |
| job-apply-plugin | Browser-extension apply helper | see brief | **Learn from** (answer memory UX) | F-12 | `auto_apply_brief.md` §1 |
| AIHawk / Jobs_Applier_AI_Agent | LinkedIn-centred auto-applier | see brief | **Reject** (job-board target, anti-detection direction) | — | `auto_apply_brief.md` §1 |
| Simplify Copilot, LazyApply, JobRight | Commercial auto-fill / auto-apply | proprietary | **Learn from** (Workday `data-automation-id` selectors; failure complaints) | KA-1, KA-2 | `auto_apply_brief.md` §1 |
| Greenhouse Job Board API `?questions=true` | Public form schema per posting | public API | **Reuse** (plan before the browser opens) | F-31 | `auto_apply_brief.md` §2 |
| Playwright for Python | Browser automation (Edge channel) | Apache-2.0 | **Reuse** | F-34 | `auto_apply_brief.md` §3 |
| `keyring` | OS credential store access (Windows Credential Manager) | MIT | **Reuse** | F-35, F-36 | `auto_apply_brief.md` §4 |
| python-docx (already a dependency) | DOCX writer | MIT | **Reuse** | F-23 | `resume_tailor_brief.md` §5 |
| Word via COM (pywin32) | DOCX → PDF on this PC | proprietary app / PSF | **Reuse** (Word is installed) | F-23 PDF | `resume_tailor_brief.md` §5 |

Built from scratch, and why: the per-ATS adapters, resolver and declaration rules (no open-source project fits a local, Singapore-focused, Edge-based single user with these guards); the tailor pipeline around Resume-Matcher's ideas (its stack is a separate web app, not a library).

## Q-60 / F-50: application status from email (checked 2026-11-02)

Evidence: `mail_status_brief.md` §5. Metadata tags: **F** = fetched 2026-11-02 (GitHub API or repo page), **Sn** = search snippet only, unverified. "Last push" is the GitHub `pushed_at` value, not necessarily the last commit.

| Candidate | Link | Licence | Last push | Stars | Fit for JobScraper | Verdict |
|---|---|---|---|---|---|---|
| offerflow | https://github.com/Xiangyahaian/offerflow | MIT (F) | 2026-08-17, the same day it was created (F) | 222 (F) | High in concept: local-first, IMAP, AI extraction into a local SQLite application table (Python/FastAPI per Sn; GitHub reports CSS). Chinese README, single code drop | **Learn from** (pipeline shape, extraction fields) |
| ApplyTrail | https://github.com/rutuu/ApplyTrail | MIT (F) | not shown; 5 commits (F) | 1 (F) | Medium: Gmail API read-only, Next.js. Rules first, ambiguous → "unknown", cloud LLM only as fallback | **Learn from** (rules-first plus an "unknown" bucket; its keyword lists seeded brief §4) |
| AppTracker | https://github.com/mkhawam/AppTracker | none (F): all rights reserved | 2025-05-04 (F) | 0 (F) | Medium: IMAP, a Bayesian "is this job mail?" gate, then Ollama for the status; TypeScript, MongoDB, Discord | **Learn from** (two-stage gate). No licence, so no code reuse |
| n8n "Job Status Analyser" template | https://n8n.io/workflows/15299-automatic-workflow-to-categorise-your-job-status/ | unverified | unverified | — | Medium: Gmail API with OAuth, Ollama Llama 3.1 8B, spam prefilter, Google Sheets. A demotion needs a one-tap owner approval (Sn) | **Learn from** (approval gate before any downgrade) |
| OnlyJobs Desktop | https://sourceforge.net/projects/onlyjobs-desktop (GitHub origin unconfirmed) | MIT per SourceForge (Sn) | unverified | unverified | Medium: Electron, local Llama 3.2 3B, Gmail sync, classes applied/interview/offer/rejected (Sn) | **Learn from** (a small local model is workable) |
| Haolinc/job-tracker | https://github.com/Haolinc/job-tracker | not checked | not checked | not checked | Low: a Kanban board synced from Gmail; merges mail when company spellings differ (Sn) | **Learn from** (company-name merging) |
| ApplyPilot, apply-potato, dcmshi/job-tracker, prshanthreddy/jobapplicationtracker, Visalan-H/Echo, ThamerD/JappTracker, tomiwajin/careersync, odeliyach/CareerOS | https://github.com/ibarrajo/ApplyPilot, https://github.com/coolbrother/apply-potato, https://github.com/dcmshi/job-tracker, https://github.com/prshanthreddy/jobapplicationtracker, https://github.com/Visalan-H/Echo, https://github.com/ThamerD/JappTracker, https://github.com/odeliyach/CareerOS | not checked (JappTracker MIT per Sn) | not checked | not checked | Low: Gmail API plus cloud LLMs (Gemini, Groq, Claude) or Sheets/Notion/Mongo stacks (Sn) | **Reject** for reuse (cloud LLM or stack mismatch) |

Built from scratch, and why: none of these is a library. JobScraper already has a read-only IMAP reader (`apply/mail.py`, D-52), and a local, rules-first classifier fits principle 3 (deterministic first, LLM last) better than any of these pipelines.
