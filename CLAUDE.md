# JobScraper (personal): session bootstrap

A local, single-user app that finds new-grad roles in Singapore on company careers sites, and (from M19–M22) tailors the resume per job and applies automatically. Spec: `docs/prd.md` (M19–M22); M0–M17 history: `.claude/prds/jobscraper-v2.prd.md`; tour: `docs/OVERVIEW.md`.

**Every session and every agent:** read this file and the handover note below before doing anything. Then read the instruction files your step needs (`instructions/README.md`). Don't edit code you haven't read. Grep first, then read the relevant part.

@instructions/handover.md

## Non-negotiables (details in `instructions/`)

1. **The main session is the Coordinator** (top tier). It plans, delegates, reviews and records. It doesn't write production code or tests.
2. **Enhance every prompt before acting** (`03_methods.md` §1). Every delegation uses the template (§2) and states a budget.
3. **Agents write only inside their own scope** (`04_team.md` §2, enforced by `.claude/hooks/scope_guard.py` from `.claude/scopes.json`). Cross-scope changes go through `comms/outbox/<role>.md`.
4. **Design before build.** Key areas (KA-1 auto-apply engine, KA-2 answer resolution, KA-3 accounts/vault/mailbox, KA-4 tailor truthfulness) get the full dossier; everything else the fast track (`05_workflow.md` §3). Engineers build only `READY` work.
5. **A working product first**, then real use, then improvements, then test depth. Testing profile: product first (`03_methods.md` §4).
6. **Parallel engineer lanes** (worktree + background) for independent READY work; at most **4** agents at once, **3** engineer lanes. Model tier per task: `04_team.md` §2.
7. **Git always.** The integration branch is **`personal`** (it plays the role of `main`). Branch per work item (`<role>/<queue-id>-<slug>`), commit after every verified step; only the Coordinator merges into `personal`, and it may push `personal` to origin (D-62).
8. **Evidence or it didn't happen.** "Done" = the `Verify:` command ran and its output is quoted.
9. **Record before you stop:** `02_status.md`, `06_work_queue.md`, `handover.md`, committed.
10. **Ask the owner only for:** scope changes, anything destructive to `data/`, real job submissions or account creation during development, paid services, force-pushes. Decide the rest and record it (`02_status.md` §4).
11. **Reuse and use skills.** Prior art first; load the fitting skill (`03_methods.md` §8).
12. **Never:** commit personal data (the GitHub repo is **public**: `data/`, the applicant profile, tailored resumes, screenshots, passwords); read `.env`; solve or bypass CAPTCHAs or bot checks; submit a real application or create a real account on an employer site unless the owner triggered it; touch the live app's DB or port 8765; touch `../JobScraper-Cloud` or `../JobScraper-frontend`.

## Commands (Windows; system Python 3.12, no venv)

- Run anything: `$env:PYTHONPATH="src"; python -m jobscraper <verb>` (PowerShell) or `PYTHONPATH=src python -m jobscraper <verb>` (bash).
- Python tests: `python tests/run_tests.py` (all, ~2 min) · `python tests/run_tests.py -k <needle>` (a file or test).
- Web tests: `cd web; npx vitest run` · build the SPA: `cd web; npm run build` (writes `src/jobscraper/web/static/`; **build only in the main checkout**, after merging).
- Dev web instance: copy `data/jobscraper.db` into the worktree, then `JOBSCRAPER_DB=<copy> JOBSCRAPER_PORT=8768 python -m jobscraper web` in the background; stop it by PID.
- Setup check: `python -m jobscraper doctor`.

## Gotchas

- **Ports:** 8765 = the owner's live app (launched from this folder by the desktop icon), 8766 = JobScraper-Cloud dev, 8767 = the paused M18 frontend worktree, **8768 = this work's dev instance**. Ollama on 11434 is shared.
- The live app runs from this checkout: merging into `personal` changes the owner's daily app at its next launch. Smoke-check `personal` after every merge.
- PowerShell 5.1 has no `&&`; `$?` after a pipe reports the last command. `tests/run_tests.py -k` also gates imports (deliberate; don't simplify).
- `core.autocrlf=true`: a CRLF checkout changes Vite hashes. Build the bundle only in the main checkout (lesson from M12).
- Gitignored inputs (`data/resume.pdf`, `data/profile.derived.yaml`) aren't in a fresh worktree: `.worktreeinclude` lists them; copy the DB by hand.
- Never blanket-kill `python` or `node` (the live app and Claude Code run on them). Stop servers by PID.
- `tests/test_layering.py` enforces the module boundaries (`docs/DESIGN.md`, PRD NF-04): only `store.py` has SQL, only `backends.py` talks to the model, stages don't import each other.
- Cloud port source: cloud commit `019e975` snapshots, see `docs/research/cloud_port_report.md` §0. Never copy cloud files wholesale (report §3a).
