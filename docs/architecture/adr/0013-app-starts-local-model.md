# ADR-0013: The app may start one local program, `ollama serve`

**Status:** Accepted (Coordinator rulings D-217 on owner decision D-214) · **Date:** 2026-11-15 · **Deciders:** Coordinator, owner (D-214) · **Design:** `../ollama_autostart_design.md` (rev 2) · **Review:** `../../reviews/Q-126-ollama-autostart-design.md`

## Context
Every model user in JobScraper (the auto-apply worker, tailor, profile re-derive, titles suggest, the search run's judge step) speaks HTTP to a local Ollama, and nothing ever launches it. When Ollama is closed, an Inbox Auto-apply click ends in a stored `model_unavailable` pause that only Resume clears, and the owner has to start Ollama by hand. D-214: "ollama should automatically run when autoapply is selected". Until now JobScraper has never started a program other than its own Python workers and the apply Edge window. The constraints: the repository is public, and the mode is `auto`, so any resumed queue sends real applications. D-200 and NF-06 say no submission without a fresh click and never twice. One GPU and one Ollama on 11434 are shared with other sessions and tools. Tests, dev copies and worktrees must never start a real process. NF-04: only `backends.py` talks to the model.

## Decision
JobScraper may start exactly one program: the installed Ollama server.
- **What runs.** Exactly `[exe, "serve"]`, `shell=False`, the environment plus `OLLAMA_HOST` only. `exe` is a resolved, existing regular file named exactly `ollama.exe` (Windows) or `ollama`. It is found in `budget.ollama_path` (config.yaml only; never the settings table, never a route), then the default install locations, then absolute PATH entries other than the current directory and the checkout. Never `shutil.which`.
- **When.** Only when the process about to use the model finds a local URL (literal `127.0.0.1`, `localhost` or `::1`, an explicit port, no cloud tag) whose port refuses connections three times. A per-port lock file holding the creator's PID makes sure that two JobScraper processes start it once.
- **How.** Hidden, as the current user, detached so that no JobScraper tree-kill (Cancel's `taskkill /T /F`) or console close reaches it. Windows uses an intermediate launcher that exits; POSIX uses a new session.
- **Never.** It never kills, stops or restarts a server, ours or another's; never starts on a slow or foreign listener; never pulls (downloads) a model; never runs from a web route or a background timer.
- **Not here.** It never starts in tests, dev copies or worktrees. `tests/run_tests.py` assigns `JOBSCRAPER_OLLAMA_AUTOSTART=0`. The spawn function itself refuses under that value or a loaded test runner. With the variable unset, autostart needs the checkout's own `data/jobscraper.db`, no `JOBSCRAPER_CONFIG` or `--config`, and no worktree. `=1` exists only for one manual-check command line.
- **The owner's switch.** Settings → Accounts → Local AI, "Start the local AI model when it is needed" (default on). It is the only value the web can change.
- **A pause lifts only on an owner click.** When the start or load fails, the queue stores one precise pause (not installed, didn't start, model not downloaded, port taken, couldn't load, not answering) that says what to do. Only Resume or a new Inbox Auto-apply click lifts it, and even then only after the worker brings the model up before any take. Lifting a model pause never resets the bot-check streak.

## Options considered
**How the queue goes on after a model failure**
- A. **A timer lifts a model pause once the Local AI probe is ok** (rev 1). The queue recovers with no click. Rejected (review C2, ruling R1): the live app runs for days, so "this session" is no bound. A model that becomes ready at 3 a.m. would send queued real applications unattended (against D-200's fresh click). The lift would also reset the bot-check streak and could loop when two health tests disagree. Bounding it (age, rate, checked-after) adds four rules to a safety path for little gain.
- B. **The owner's click lifts it, after a start-and-wait** (chosen). D-214's case "Ollama closed → click → it starts" needs no pause at all: the worker starts the model before its first take. A pause remains only when the app tried and could not, and the owner's next Resume or Auto-apply click is the fresh consent.

**Who runs the server**
- 1. **A Windows service, or a scheduled task at sign-in** that keeps Ollama running. No start logic in JobScraper. Rejected: it needs admin rights or OS configuration the app must not perform, it holds the shared GPU server up even when the owner closed it on purpose, it is Windows-only, and it moves a safety-relevant behaviour outside the code and the tests.
- 2. **Ask the owner each time** (a dialog "Start Ollama?"). Rejected: D-214 asks for no manual step. The click on Auto-apply is already the owner's intent, and a second prompt would come from a background worker with no UI.
- 3. **Start `ollama serve` on demand from `backends.py`** (chosen). One function in the only module that talks to the model, injected seams for every pin, and no new process kinds besides this one.

## Consequences
- The owner's click works with Ollama closed; failures are precise and actionable, and "Nothing was sent" stays true.
- A started server outlives JobScraper. It is idle after keep-alive and holds no VRAM. The owner ends it in Task Manager or by signing out, because the headless server has no tray icon (accepted risk A1).
- A search run or a CLI task may start Ollama while the owner closed it on purpose. The switch text discloses this (A2).
- A file named `ollama.exe` in a user-writable PATH folder is trusted after the default locations. The cwd and the checkout are never searched (A3).
- New test duty: every pin injects `spawn`, `find` and `http`; a guard pin proves the spawn refuses inside the suite.
- To revisit: a remote or cloud Ollama stays out of scope. The tailor's silent fall-back to the original resume is follow-up F1.

## Action items
1. [ ] WP-T0: assigned guard in `tests/run_tests.py`; v5 pin retarget.
2. [ ] WP-E1: `backends.ensure_model_running`, `find_ollama`, `_spawn_detached`, `autostart_allowed_here`; store `queue_resume_if(keep_window)`, model state.
3. [ ] WP-W1 / WP-E2 / WP-U1 per design §8; one bundle build.
4. [ ] The Coordinator's manual check (design §9) on a dry-run DB copy, with the shared Ollama coordinated.
5. [ ] Record D-217 (rulings R1-R7) and file follow-up F1.
