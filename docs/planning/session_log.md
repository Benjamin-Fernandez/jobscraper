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
