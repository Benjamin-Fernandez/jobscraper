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
