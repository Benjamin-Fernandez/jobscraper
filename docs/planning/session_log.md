# Session log (append-only; newest at the bottom)

One entry per session. Older handover notes end up here, so `handover.md` stays short.

### 2026-11-01: session 1 (kickoff, retrofit)
- **Done:** project kickoff in retrofit mode on branch `personal`. Three research briefs (cloud port report, ATS resume tailor, auto-apply) in `docs/research/`. PRD r1 `docs/prd.md` (M19–M22) approved by the Coordinator under the owner's delegation. Harness scaffolded (CLAUDE.md, instructions/, agents, hooks, scopes, outboxes); hooks probed.
- **Decisions:** D-01, D-02, D-50 to D-63 (`instructions/02_status.md` §4). Owner: Standard team without a security reviewer; fully automatic submission that fails properly; IMAP for verification; merge and push allowed.
- **Next:** Q-01 to Q-04 in parallel.

## 2026-11-02 (session 1, continued)
- M19 merged and pushed (cab10af, bundle e6b33d7): 410/410 Python, 220+1 web; D-66 abort guard, TD-01.
- M20 dossier merged: test plans (Q-08), build plans (Q-09), tailor patch + D-68/D-69 (Q-19), seeds (Q-20).
- Owner: Workday is the biggest problem → D-70 (Workday-first M20, MyGreenhouse autofill, tailored resume always replaces autofilled; real accounts + auto-submit allowed at 2 Workday employers). Q-22 design delta merged (contracts v3).
- Lane T (tailor) and lane P (profile + resolver) merged; Q-21 oracles + guards; suite 469/469.
- Owner gave the application email (kept out of the repo; Coordinator memory). Stored IMAP secret is not an app password; MyGreenhouse sign-in landed outside the JobScraper profile.
- Owner stopped the session: lanes B, V, tester paused with work committed on their branches (see handover).

## 2026-11-02/03 · session 2 (continued, paused by the owner)
- Merged + pushed: int/Q-30 (D-74 Profile form + F-13 questions, D-75, tier-3 memory; review APPROVE WITH FIXES), Q-36 lenient profile (D-79), Q-39 review fixes F2/F6/F7 + `data/*.tmp` gitignore (Q-42 defect pin), S-5b spike (LLM-driven Workday: tenant A submitted + confirmed, tenant B fail-closed on a required field), Q-35 D-78 design (ADR-0006, contracts v5) + amendment + re-check READY, tester T0/T1/T3/T2-core/T4-lane-N, lanes N + R with review fixes (920/920).
- Decisions D-79 (lenient profile), D-80 (finish tenant B with spike tooling), D-81 (NF-07 Workday deviation + conditions), D-82 (locks stay deterministic), D-83 (gate count 5 GH dry runs; audit read row by row; fresh owner approval for gate postings), D-84 (re-check R1–R4), D-85 (Greenhouse code pattern), D-86 (lane M F7/F8 tightenings, F9 interim compose_needed).
- Owner: new resume; profile re-derived and applicant.yaml experience/skills rebuilt on request; address_line2 filled.
- Open at pause: lane M (b79df03) and R3 (adc8f08) unmerged; Q-41, Q-44, Q-45 queued.

## 2026-11-02 · session 3 (resumed, paused by the owner)
- Q-41 done: tenant B Workday application filled to Review by the S-5b tooling, read row by row by the Coordinator, submitted once, "Applied" (merged 59967d7). Owner gave job locations (Singapore ×3) and kept the tailored PDF and AWS.
- Owner rules: D-87 declaration-type questions → No; D-91 free from restrictive covenants, willing to sign NDAs. Coordinator decisions D-88 (military/NS labels sensitive), D-89 (government wording beats prior/current employment), D-90/D-90a (declaration frame gates after the WP-Q48 review), K-3 (possible flaky filter test).
- Q-46 defects (location from home city, ungrounded skills, cited-fact relevance, disability source, Workday Next wait) pinned and fixed by lane M; lane M hierarchical how-heard fit (e2414c5).
- Q-48 designed (architect), built (WP-Q48), reviewed: needs fixes (frame-blind classification). Fix round was running at the pause (8393f98, not verified).
- R3 reviewed (merge after fixes); lane R fixed F1–F6, F8, F9 (2add8ee); re-review was stopped at the pause.
- int/Q-35-M 3aadc13: lane M + WP-Q48 (first build) + tester pins; 1007/1024, the 17 = WP-Q48 fix-round pins. Nothing new merged into personal from the build this session (only Q-41 and records).
