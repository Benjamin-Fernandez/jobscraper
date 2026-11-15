# Review: Q-126 "the app starts the local model itself" (code, before merge into `personal`)

Reviewer, 2026-11-15. Branch `rev/Q-126-code` off `int/Q-126` (86767e7). Reviewed: `git diff personal..HEAD -- src/ config/ web/src/` (16 files, +1,378/-81) against `docs/architecture/ollama_autostart_design.md` rev 2, `docs/reviews/Q-126-ollama-autostart-design.md` (C1-C14), ADR-0013, D-200, D-203, D-205, D-214, D-217, and the four lanes' and the tester's outbox entries. Read-only checks run with `JOBSCRAPER_OLLAMA_AUTOSTART=0`: `-k q126` 100/100, `-k layering` 13/13, `-k apply_queue` 47/47, `-k apply_flow` 149/149. Throwaway snippets drove `find_ollama`, `autostart_allowed_here`, `_target_is_local` and a refused `_spawn_detached` with temp dirs only. Not run: `-k apply_e2e`, the full suite, vitest, anything that starts Ollama or the web app. No process was started and `data/`, the live DB and ports 11434/8765 were not touched.

## Verdict: READY WITH CHANGES

No HIGH finding. The safety core holds: no path can send an application twice or without the owner's click because of this change, nothing but the installed Ollama is started, nothing is started in tests, dev copies or worktrees, and a search run, the tailor and the web start behave as on `personal` when Ollama is missing. Two MEDIUM items must be fixed before the merge because each is a regression on the owner's side and each is a one-line change: M1 (a CLI verb now always fails) and M2 (the new `cmd_web` environment write leaks into the single-process test suite, and the full suite has never been run on this branch). The rest is LOW.

## Findings

### M1 (MEDIUM) `applicant refresh-resume` is broken: `args` is undefined

- **Where:** `src/jobscraper/cli.py:918`, inside `_applicant_refresh(cfg, save)` (def at :907). The new line `_ensure_model(cfg, None, args)` uses `args`, which is not a parameter and not a module name (AST check: the only undefined name in `cli.py`).
- **Trigger:** the owner (or anyone) runs `python -m jobscraper applicant refresh-resume`.
- **Effect:** `NameError` is caught by the function's own `except Exception` (:927-928) and prints "applicant: the resume could not be read (NameError)", exit 1. A working verb now never works, with a message that blames the resume. Not the web path (the Profile page runs `profile --refresh --plan-applicant`, which is `cmd_profile` and is fine), and no test covers the verb (`-k q126` and `-k cli` are green).
- **Fix:** pass what the helper needs: `_applicant_refresh(cfg, save, args)` from :864 and `_ensure_model(cfg, None, args)`, or call `_ensure_model` in the caller (`cmd_applicant`, where `args` exists) before `_applicant_refresh`. Tester: one pin that runs the verb on a temp config with `_ensure_model` patched.

### M2 (MEDIUM) `cmd_web` writes `JOBSCRAPER_CONFIG` into the process and a test never undoes it; the full suite was never run

- **Where:** `src/jobscraper/cli.py:376` (`os.environ["JOBSCRAPER_CONFIG"] = str(args.config)`), and `tests/test_mail_d157_pins.py:144-171` (`test_mail_d157c_...` calls `cli.main(["--config", path, "web"])` and restores only `JOBSCRAPER_DB` and `JOBSCRAPER_MAIL_SYNC`).
- **Trigger:** the single-process full suite (`python tests/run_tests.py`). I reproduced it: after calling that test function, `JOBSCRAPER_CONFIG` is still `...\Temp\d157c_<x>\config.yaml`.
- **Effect:** every later test that calls `load_config()` with no path reads that temp config, and the dev DB/path rules in later files see `JOBSCRAPER_CONFIG` set. Tests become order-dependent; a later failure is blamed on the wrong change. The engineer's own handoff says the full suite was stopped at 35 of 129 files, so this has not been seen. (Production is unaffected: the live app has no `--config`.)
- **Fix:** tester: restore `JOBSCRAPER_CONFIG` in that test's `finally` (add it to `old`), and grep the other `cli.main([... "--config" ..., "web"])` callers (`tests/test_apply_queue_cli.py` already restores it). Then run the full suite on the integration tree (see the conditions).

### L1 (LOW) The PATH fallback accepts any file named `ollama.exe` in any absolute PATH directory outside the cwd and the checkout

- **Where:** `backends.py:562-624` (`find_ollama`, steps 2-3). Verified by snippet: a planted `ollama.exe` in an arbitrary absolute PATH dir is returned when no default install exists; the cwd, a relative entry, an entry under the checkout, a non-absolute `ollama_path` and a configured file not named `ollama.exe` all return None.
- **What "only a file named ollama.exe counts" really checks:** the resolved path's file name (case-insensitive on Windows) and `is_file()`. No signature or publisher check. A symlink is resolved first, so a link to another program fails on its target's name.
- **Effect:** someone who can write into a PATH directory could get that file started by JobScraper, but the same person could already hijack any PATH lookup, and the default install locations are tried first. This matches the design (§2, C3, R3); accepted. Cheap hardening if wanted: drop the PATH step and keep defaults plus `ollama_path`.

### L2 (LOW) The child inherits the app's whole environment

- **Where:** `backends.py:872` (`env = dict(os.environ)` plus `OLLAMA_HOST`). Same as the design ("the env adds only `OLLAMA_HOST`"). The app keeps its secrets in the keyring, not in the environment (grep of `os.environ` shows none), so nothing JobScraper-specific leaks; whatever the owner's session holds is passed to Ollama, a trusted local program of the same user. Accepted.

### L3 (LOW) The owner's switch is read once per worker and once per CLI command

- **Where:** `cli.py:1431` (`model_autostart=_model_autostart(...)` at worker start). Turning the switch off in Settings while a worker runs does not stop that worker from starting Ollama before its next take. It cannot start anything it could not have started at launch, and the worker is short-lived. Accepted; one line in the Settings description would do.

### L4 (LOW) Bare `profile` may start Ollama although nothing needs deriving

- **Where:** `cli.py:557` (`not args.show` is true for bare `profile`, which re-derives only if the resume changed). With Ollama stopped, a no-op `profile` starts it. Harmless, wasteful. Could be narrowed to `args.refresh or plan_applicant or <resume changed>`.

### L5 (LOW) A stale "starting the model" row can show while a manual `apply` job holds the slot

- **Where:** `web/routers/apply.py:_model_view` (shown when `slot == "apply"`). A worker killed during a model wait (`taskkill /T` on Cancel) leaves `apply_queue.model` set; the next *queue* worker clears it, but a single manual `jobscraper apply <id>` job (also kind `apply`) would show it until then. Display only. Fix: also clear the row in `cmd_apply`, or have `_model_view` ignore a `since` older than ~7 minutes (the longest legal wait is 60 + 330 s).

### L6 (LOW) The retry can repeat early, reversible steps of one application

- A mid-attempt `model_unavailable` (page 3 of a Workday-style flow) is retried once, from the start, with no owner click. The Submit click has not happened (NF-06), so nothing is sent twice, but a second pass may touch an employer draft or sign in again. This is the design's accepted row 3 (§3, risk R-retry) and the same condition as the existing manual return-and-Resume.

### L7 (LOW) Fail-safe silence when the owner's DB is not `data/jobscraper.db`

- `autostart_allowed_here` is true only when `cfg.db_path` equals the checkout's `data/jobscraper.db`. A `paths.db` override in `config.yaml` makes autostart silently off and the card says "Not in this copy of JobScraper". Safe direction; the default config has the default path.

## What I tried that held

**1(a) Never twice.** The retry is set in exactly one place, `apply_flow.py:2146`, guarded by `model_retry_wanted` (:1989): `why is MODEL_UNAVAILABLE`, a real `OllamaBackend`, row state `failed`, `submit_clicked_at is None`, all read from the store. `submit_clicked_at` is committed before the click (`apply_flow.py:13, 835`) and a row never ends `failed` after the click (D-69), so a role whose attempt clicked Submit cannot be retried. The retry is capped at 1 per job and 2 per worker run (:2003-2030); a repeat or a third gives `model_not_answering` and the role is returned. A crash between the attempt's end and `queue_return`: the role was already deleted from the queue by `queue_take`, so it is lost from the queue, not resent; the owner sees a failed attempt. Fails closed. The counters are per worker process, so the owner's next click gets a new budget of 2: owner-bound.

**1(b) Nothing lifts a pause without the owner.** `queue_resume_if` and `queue_resume` have exactly two callers: `routers/apply.py:252` (the Inbox click) and `:467` (Resume). The start-up hook only writes `restarted`. No timer, tick, GET, connections probe or Questions retry (`lift_model_pause=False`) reaches them. The runner tick (`applyqueue.py:_loop`) only calls `kick`, which refuses while a pause is stored. After the worker stores its own model pause it breaks out and exits; nothing restarts it.

**1(c) The click lifts only a model pause.** `MODEL_CLICK_RESUME` = the seven `MODEL_PAUSES` (`contracts.py`), one compare-and-clear inside `BEGIN IMMEDIATE` (`store.py:1824`), so a pause that changed to `owner` meanwhile is kept. `profile_incomplete`, `daily_limit`, `browser_unavailable`, `restarted`, `app_closed`, `cancelled`, `bot_checks` and the rest are not in the set. A runner that is off or whose gate is closed lifts nothing (`routers/apply.py:248`); the gate opens only after the start-up hook committed, so roles from an earlier session (stored model pause + waiting roles becomes `restarted`, `store.py:1738`) still wait for Resume. A stored model pause with no waiting roles stays, and the click then lifts it for the role just clicked. `resumed_at` is not written for a model pause, so the bot-check streak survives.

**2. Stop wins.** `should_stop` is polled inside every wait of the service (each ping try, the wait loop, the load thread's join every ~0.5 s), and `run_queue` re-checks it right after `precheck` and before `queue_take` (`apply_flow.py:2111`); `model_retry` re-checks after its own ensure (:2017-2022) and returns the role with `app_closed`. An owner Pause during the wait is also safe: `queue_take` returns nothing while a pause is stored (`store.py:1698`), and the worker's own pause is "first reason wins". The CLI run by hand has no `should_stop`; Ctrl+C is a `BaseException`, passes the service's `except Exception`, clears the state in `finally`, and pauses `cancelled`.

**3. The launcher.** Argv is `[exe, "serve"]`, `shell=False` on both paths (`backends.py:641-690`); the Windows launcher text is a fixed string run with `python -I -c`. `find_ollama` never calls `shutil.which`; the cwd, relative PATH entries, the checkout and anything below it are skipped (snippet). `budget.ollama_path` is read only from `cfg.budget`; nothing in `src/` reads a settings row for it (grep: the only settings key read is `budget.ollama_autostart`), no route writes it, and `web/` does not call `ensure_model_running`. URLs: `localhost`, `127.0.0.1`, `::1` start; `0.0.0.0`, `127.1`, `localhost.` and `http://localhost:11434@evil.com` (hostname `evil.com`) are not local (snippet); `http://evil@127.0.0.1:11434` is local and httpx connects to the same host, so there is no mismatch; no explicit port means no start. `-cloud`/`:cloud` tags never start. Tests, dev copies, worktrees: `tests/run_tests.py:52` assigns `JOBSCRAPER_OLLAMA_AUTOSTART=0`; `_spawn_detached` refuses on `0`, on `run_tests`/`pytest` in `sys.modules` or in `argv[0]` (even with `=1`), and, with the variable unset, unless the DB is the checkout's own, `JOBSCRAPER_CONFIG` is unset and the code is not in a worktree (snippet: refused with `=0`; unset live/copy/config cases as designed). `=1` overrides everything except the test-runner check; nothing in `src/` or the launch scripts sets it. The lock is a per-port `O_EXCL` file holding the creator's PID with an age cap of 90 s, so PID reuse is bounded and two workers produce one spawn (a missing temp folder goes on without a lock; a second `ollama serve` would then only fail on the port). No `api/pull`, no kill, no stop anywhere in `backends.py`.

**4. Failure behaviour.** With Ollama not installed the service returns `not_installed` after three refused pings (about 2 s of sleeps). In a search run that only changes the existing skip line (`pipeline._bring_model_up` never raises, runs only when postings wait and the probe fails); the tailor/profile verbs print one line and go on; the web start runs no autostart code. The 60 s start wait and the 330 s load wait are in worker or job processes, never on a request thread; the GET path does only `Path.resolve` and a settings read, and the probe's `find_ollama` runs in the existing probe thread.

**5. Layering and contract.** `-k layering` 13/13. Only `backends.py` talks to the model; the store has the only SQL and no schema change (no `SCHEMA`/`CREATE`/`ALTER` in the diff; new data is two settings keys, `apply_queue.model` and `.model_at`); `web/` imports `backends` and `web.applyqueue` only; contract additions are new enum members, new constants and reworded copy.

**6. Web and screens.** `PUT /api/connections/model/autostart` takes only a real boolean (`type(...) is bool`, 422 otherwise, nothing changed), writes one settings row, sits behind the global `CrossSiteWriteGuard`, and returns booleans only (ADR-0009 holds). `detail` is a model tag, a port or a fixed phrase (`ModelReady` code paths in `backends.py`), never a path or URL; it passes `redact` before storing. The Vue shows pause text with `{{ }}` interpolation (no `v-html` in either component); the one place the server's `message` is displayed goes through the same interpolation. No client timer calls resume (the only timer is the elapsed-seconds ticker).

**7. `config/config.yaml`.** The diff is +8 lines: `budget.ollama_autostart: true` and a commented `# ollama_path:`. `apply.mode` and `apply.fill` are untouched.

## Departures the lanes listed

- E2 (1) separate `should_stop` re-check: acceptable (same effect, and it also covers a `None` precheck). E2 (2) `detail or None`: acceptable.
- E1 1 (`queue_resume_if(None)` with nothing paused writes nothing): acceptable, W1 keeps `queue_resume` for that case (`routers/apply.py:467`). E1 2 (`reset_probe` before the model check): acceptable. E1 3 (no lock when the temp folder is unwritable): acceptable (L-level; a second spawn only fails on the port). E1 4, 5, 5b, 6: acceptable and as designed.
- W1 (a) `running_from_worktree` imported from `backends`, `_REPO_ROOT` kept for the pin: acceptable. W1 (b) `config_given` not visible to the web: closed by `cmd_web` setting `JOBSCRAPER_CONFIG` (M2 is the test side of that). W1 (c), (d): acceptable.
- U1 (a) a stored pause beats the starting row: acceptable and better than the design (keeps Resume). U1 (b) `lifted` not shown: acceptable. U1 (c) `Profile.vue:98` still matches the backend log line: acceptable, the line is unchanged. U1 (d): acceptable. Note U1's stale vitest pin (`web/tests/q44-refresh.test.js` 370-372) must be retargeted and vitest run before the bundle is built.

## Gaps the tester listed as not pinned

None blocks. T18 (the pipeline starts the service only when postings wait): I read `_bring_model_up` (`pipeline.py:589-629`): it counts postings without a cached decision from this model and without three parse failures, and returns before any service call when none wait or the backend already answers; a mistake costs a start, not a send. The recovered-attempt rule of T19 changes only how long a card shows attention. T13d at route level: the route makes one `queue_resume_if` call and the compare-and-clear is pinned at store level. T13e (a failed ensure after a lift stores the pause again): read in `precheck` (`apply_flow.py:1927-1933`), the not-ready result returns the mapped pause before `queue_take`. The `--config` check is covered by M2's environment write (and a pin exists per the engineer); the leak in M2 is the thing to fix.

## Accepted risks

- A retried role may repeat reversible pre-Submit steps (L6). A model start takes up to 60 s plus a 330 s load before a role is taken; the owner sees "Starting the local AI model...". An Ollama started by JobScraper stays running after the app closes (by design, never killed). The switch is a boolean the web can change; the program location is not.

## Conditions for the merge

1. Fix M1 (the `args` NameError) and M2 (restore `JOBSCRAPER_CONFIG` in `test_mail_d157c`); each with a pin or a re-run.
2. Run on the integration tree, each ALONE and with `JOBSCRAPER_OLLAMA_AUTOSTART=0`: the full suite (`python tests/run_tests.py`), `-k apply_e2e`, `-k apply_flow`, and `cd web; npx vitest run` (retarget the `q44-refresh` pin first). The full suite has not been run on this branch.
3. Build the bundle only in the main checkout after the merge (CLAUDE.md), then smoke `personal`.

## Coordinator's manual check on a dry-run DB copy

On one command line only (never in the shell): `JOBSCRAPER_DB=<copy> JOBSCRAPER_OLLAMA_AUTOSTART=1 JOBSCRAPER_MAIL_SYNC=0 JOBSCRAPER_APPLY_QUEUE=0 JOBSCRAPER_PORT=8768 python -m jobscraper web`, with `apply.mode` set to `dry_run` in the copy's settings table first. Close Ollama (tray and `ollama serve`), then check in order: (1) Settings → Accounts → Local AI shows the switch and a neutral "starts when a task needs it" card; (2) `PUT` the switch off then on and watch the card; (3) click Auto-apply on one role of the copy with `apply.mode` `dry_run` and watch Runs show "Starting the local AI model..." then "Loading the model...", then the role filling in dry run, never a send; (4) close Ollama again, click again: the queue pauses with a model reason and the click after fixing the cause lifts only that pause; (5) rename the program path in `budget.ollama_path` to a wrong file and confirm `model_not_installed`; (6) `python -m jobscraper doctor` prints `autostart` with no path. Never use the live DB, port 8765 or a real job id with `auto` mode; Ollama is the shared one on 11434, so ask the other live session first.
