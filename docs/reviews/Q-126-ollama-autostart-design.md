# Review: Q-126 "the app starts the local model itself" (design, before build)

Reviewer, 2026-11-15. Branch `rev/Q-126-design` off `arch/Q-126-ollama-autostart` (175af9e). Reviewed: `docs/architecture/ollama_autostart_design.md` (276 lines) and the WP-0 diff of `src/jobscraper/apply/contracts.py`, against the code on that branch, `apply_queue_design.md`, `docs/reviews/Q-120-apply-queue-code.md`, D-200, D-205, D-214, NF-04, NF-06. Read-only checks run: `-k apply_contracts` 71/72 (one failing pin, see C6), `-k layering` 13/13. No process was started; Ollama, the live DB and `data/` were not touched.

## Verdict: READY WITH CHANGES

The core is sound and I would let it be built: one service in `backends.py`; a start only when the port refuses connections; a fixed `[exe, "serve"]` argv with no shell; the executable never taken from the settings table; no pull, no kill, no restart of a live server; the pre-take check ahead of every take; the one automatic retry limited to a `failed` row with `submit_clicked_at` null. Two items are HIGH (C1, C2) and must be in the text before the engineer starts. Neither needs a second design round; each is a paragraph.

The two HIGH items:
- **C1:** a worker that waits up to 6.5 minutes for the model can then take a role although the app that started it has closed.
- **C2:** the timer auto-resume goes beyond D-214 and can start real submissions hours later with no click. It also erases the bot-check streak.

## Required changes

Each has a severity, a place in the design, and text that can be pasted.

### C1 (HIGH) §3 row 1 and §2 step 4/7: re-check "stop" after a long model wait

**Evidence.**
- In `run_queue` (`apply_flow.py:1957-2010`) the order is: `should_stop()` at the loop top (:1971), `precheck()` (:1989), then `queue_take` (:1996).
- `queue_take` re-reads only the pause and yield flags (`store.py:1698`). It never reads `should_stop`.
- Today `precheck` costs microseconds. With §3 it can block for `start_wait_s` (60) plus `load_wait_s` (330): up to 390 s.

**Failure scenario.** The owner clicks Auto-apply with Ollama closed. The worker starts Ollama and begins the 5-minute load. The owner closes JobScraper, and `_parent_gone` turns true. The load finishes, `precheck` returns None, and `queue_take` hands out the head. The worker applies, in `auto` mode, to a role from an app the owner closed. The worker is a child of `web`, and `taskkill /T` only runs on Cancel. NF-06 does not stop this: it is the first and only attempt.

**Paste into §3, after row 1:**
> `ensure_model_running` takes `should_stop: Callable[[], bool] = lambda: False`; its wait loops and the warm call poll it every 2 s (the warm runs in a worker thread so the poll works) and return `ModelReady("cancelled")` when it is true. `run_queue` calls `self.should_stop()` again immediately after `precheck()` returns and before `queue_take`; true → `pause(APP_CLOSED)` and break, exactly like the loop top. The same re-check follows the post-item ensure of row 2 before `queue_return`/`continue`. Pin T11b: a fake clock where `should_stop` turns true during the ensure → no `queue_take`, pause `app_closed`.

Add `"cancelled"` to the `ModelReady.code` comment in §2. It maps to no pause: the caller returns.

### C2 (HIGH) §4.4 and the contract: bound the auto-resume

**Evidence.**
- D-214 says "carries on" within the ask; a pause appears "only when the app tried and could not". It does not say the queue restarts by itself hours later.
- D-200 and PRD line 158: no submission "without a fresh click". Roles waiting after a restart need Resume.
- The design's boundary is "within one app session". But the live app is left running for days (desktop icon), so "session" is not a bound.

**Failure scenario.** The owner queues six roles in the evening, and Ollama fails to start (`start_failed`). The pause is stored and the owner goes to bed. At 3 a.m. the scheduled search run or the owner's other tool starts Ollama. The probe reports ok, the 5-second tick lifts the pause, and six real applications go out unattended. The owner expected a pause that waits for them.

**Three further defects in the same mechanism:**
1. `queue_resume_if` "also sets `resumed_at`" (§5). `queue_resume` stamps the streak window start (`store.py:1756-1766`, `window_start` at `apply_flow.py:2055`). An auto-lift between two CAPTCHA endings therefore hides the first one from the `bot_checks` rule (`pause_for`, 2 in a row). A machine action must not reset the streak that protects against bot checks.
2. `model_port_taken` is auto-liftable, but the probe's "ok" (`GET /api/tags` lists the model) and the ensure's `port_taken` (`/api/version` not 200-JSON-with-`version`) are different tests. If they ever disagree, the loop is: lift → spawn a worker (~seconds) → `port_taken` → pause → 5 s later lift, forever. That is the retry loop the brief forbids.
3. `model_not_installed` and `model_missing` need minutes to hours of owner work (a multi-GB pull). A pause that "continues by itself" for those will usually be hours old, which is the C2 scenario.

**Paste into §4.4 (replacing the lifting paragraph):**
> The tick may lift a stored model pause only when ALL hold: (1) its reason is in `MODEL_AUTO_RESUME`, now **{MODEL_UNAVAILABLE, MODEL_START_FAILED, MODEL_PORT_TAKEN}**; (2) the pause is **at most 30 minutes old** (`since`, store clock); an older one waits for Resume, like `restarted`; (3) `model_health.snapshot()` is ok AND was checked after the pause was stored (`checked_at >= since`); (4) this runner has lifted fewer than **2 pauses in the last hour** (in-memory list; a third waits for the owner). The lift is `store.queue_resume_if(reasons, now, stamp_resumed_at=False)`: it clears the three pause keys only, **never writes `resumed_at`**, and is one `BEGIN IMMEDIATE` compare-and-clear. `model_not_installed`, `model_missing`, `model_load_failed`, `model_not_answering` are never lifted by the tick; Resume lifts them.
>
> The simpler alternative, which I would also accept, is to delete the tick lift and keep Resume as the only way (D-214 does not ask for more). If so, every "The queue continues by itself …" hint ends "then press Resume".

**Contract (WP-0), paste to match:**
- `MODEL_AUTO_RESUME = frozenset({MODEL_UNAVAILABLE, MODEL_START_FAILED, MODEL_PORT_TAKEN})`.
- `MODEL_NOT_INSTALLED` hint: "…then download the model with “ollama pull {detail}”, then press Resume."
- `MODEL_MISSING` hint: "Download it in a terminal with “ollama pull {detail}” (several GB), then press Resume."
- `MODEL_UNAVAILABLE`, `MODEL_START_FAILED` and `MODEL_PORT_TAKEN` hints keep "The queue continues by itself once it answers." and add "(within half an hour; after that, press Resume)".

Pins to add:
- T13b: a pause 31 minutes old is not lifted.
- T13c: a lift leaves `resumed_at` unchanged.
- T13d: a third lift in an hour is refused.
- T13e: a probe whose `checked_at` is older than `since` does not lift.

### C3 (MEDIUM) §2 `find_ollama`: do not use `shutil.which`; known locations first

**Evidence.**
- Python 3.12 `shutil.which("ollama")` on Windows searches the current directory first (it consults `NeedCurrentDirectoryForExePathW`).
- The web app and its workers run with the checkout as cwd (`run.ps1:20` `Set-Location $PSScriptRoot`).
- The design says candidates must be "absolute", but `which` can return `.\ollama.exe`, and the text does not say whether a rejected candidate falls through to the next source.
- The design also gives PATH priority over the default install directory.

**Failure scenario.** A file named `ollama.exe` that is in the repo folder (a public repo, a download extracted there) or in an earlier user-writable PATH folder is started with the owner's rights, by a button the owner pressed for a different reason.

**Paste into §2 (replace the order list):**
> `find_ollama` order: (1) `budget.ollama_path`; (2) the default install locations (the Windows, macOS and Linux lists); (3) each entry of `env["PATH"]` that is an absolute directory and is not the current directory or the checkout, joined with `ollama.exe`/`ollama`. It never calls `shutil.which`. Every candidate is `Path.resolve()`d first and must satisfy the existing name and regular-file rule; a failing candidate is skipped (not fatal) for (2) and (3), and fatal only for (1). Pin T3b: a planted `ollama.exe` in the cwd and a relative PATH entry are both ignored.

### C4 (MEDIUM) §6 rule 6 and §9: make the test guard not depend on one env line

**Evidence.**
- "Every library default is off" holds for the service (`autostart: bool` has no default), but the CLI layer turns it **on** by default (`autostart_switch` default True, `autostart_allowed_here` true from a main checkout with no env).
- Many tests call `cli.main` or `cmd_*` (`test_cli.py`, `test_apply_cli.py`, `test_apply_queue_cli.py`, `test_profile.py`, `test_q44_refresh.py`).
- The only guard against a real start from them is `os.environ` set in `tests/run_tests.py`. `setdefault` would be defeated by a shell variable left at `=1` after the §9 manual check.
- A test run directly (`python tests/test_x.py`) or by another runner bypasses it.

**Failure scenario.** The Coordinator ran the manual check with `$env:JOBSCRAPER_OLLAMA_AUTOSTART=1` in the same PowerShell, then runs the suite in the main checkout. A test that reaches `cmd_tailor` with a real `OllamaBackend` and a stopped Ollama starts a real server.

**Paste into §6 rule 6:**
> (a) `tests/run_tests.py` **assigns** `os.environ["JOBSCRAPER_OLLAMA_AUTOSTART"] = "0"` (no `setdefault`) before importing any test. (b) `_spawn_detached` itself refuses (`OSError`, so `start_failed`) when that variable is `"0"` or when `"run_tests"`/`"pytest"` is in `sys.modules`, so a real start cannot happen even if a caller passes `autostart=True`. (c) `autostart_allowed_here` has a positive condition for the unset case: the effective DB is the checkout's own `data/jobscraper.db` (resolve both paths); any other DB path, including every tmp DB in tests, is "off". (d) The manual check sets the variable only on the one command line (`JOBSCRAPER_OLLAMA_AUTOSTART=1 python …`), never in the shell.

Pin T15b: with `JOBSCRAPER_OLLAMA_AUTOSTART` unset and a tmp DB, the answer is False.

### C5 (MEDIUM) §3 row 2 and §6 rule 7: cap automatic retries per worker run

**Evidence.** `model_retried` is per job id, so each role gets its own retry. Retries are bounded per role, not per worker. Each cycle can cost up to 60 + 330 s of waiting plus a whole attempt. Resume starts a new worker with an empty set, which is a deliberate owner action and fine.

**Failure scenario.** The model is flaky (VRAM pressure from another tool). Roles A, B and C each fail once and succeed on retry. That is progress, but nothing tells the owner the model has been restarted three times, and each time the other tool's work on the shared server is disturbed.

**Paste into §3 row 2:**
> A worker run makes at most **2** automatic retries in total (`self.model_retries`, a counter next to the per-job set). A third `model_unavailable` ending, for any role, pauses `MODEL_NOT_ANSWERING` without a retry. The second failure of the same role after `ready` is a pause `MODEL_NOT_ANSWERING` as designed. Note for the hint of that pause: the server may be healthy and the page call failing for a role-specific reason (HTTP 500, context overflow); the text "not answering in time" is then loose but harmless, and Resume gives the role one more try.

### C6 (MEDIUM) §5, §10 pins: the failing contract pin, and the architect's claim "no test pins these strings"

**Evidence.** `python tests/run_tests.py -k apply_contracts` gives `71/72 passed`:
> FAIL test_apply_contracts_v5::test_model_unavailable_has_owner_copy_that_says_nothing_was_sent … `assert "doctor" in rt.hint`

The hand-over's "existing tests pin none of these strings (grep)" is therefore wrong for one pin. It is the pin that should change, not the new hint. The hint's job is now to point at the page that says why. "doctor" is a CLI command the owner no longer needs in the daily path. For a CLI `apply` run (no queue), the text "Try again" is still right, and `doctor` stays in the CLI's own output.

**Paste into WP-T:** retarget the assertion in `tests/test_apply_contracts_v5.py:40` to `assert "Runs" in rt.hint and "Try again" in rt.hint`. Keep the two other assertions (`nothing was sent`, no braces). Also retarget `web/tests/connections.test.js:148` and `web/tests/q44-refresh.test.js:371` as the design says. Add that the engineer's lanes run `-k apply_contracts` and may not merge on a red pin.

### C7 (MEDIUM) §3 row 1 / §4.1: the ping rules for "slow" and "other"

**Evidence.** `ping` has a 3 s cap and a single reply decides. `timeout` → `not_answering` and `other` → `port_taken` are both stored pauses (`MODEL_NOT_ANSWERING` is not liftable). On a machine whose GPU and CPU are shared, one slow `GET /api/version` is enough. During the start wait, a half-open socket or one 503 while Ollama binds (`RemoteProtocolError`, `ReadError`) is also `other` and would store `port_taken` for a server that is a second away from ready (§2 step 4 says "`other` while waiting → `port_taken`").

**Paste into §2 algorithm step 1 and 4:**
> `ping` makes up to 3 tries 1 s apart with a 5 s cap each, and reports `refused` only when all three are `refused`. `timeout` and `other` are decided only when all three agree (a mix is `not_answering`). Inside the start wait (step 4) `other` and `timeout` simply continue the poll; at the deadline the last answer decides: `refused` → `start_failed`, `other` → `port_taken`, `timeout` → `not_answering`. The total worst case before a decision stays below 20 s outside a start.

### C8 (MEDIUM) §2 step 3 (lock): a lock left by a killed creator makes the waiter report a false failure

**Evidence.** Cancel kills the worker with `taskkill /F` (`jobs.py:290-309`), so the `finally` that deletes the lock never runs. The lock stays "fresh" for `start_wait_s + 30` = 90 s. A new worker sees a young lock and "only waits" for `start_wait_s` = 60 s, then pauses `start_failed`, though nobody was starting anything. The pause is auto-liftable, so it heals, but it is a false "JobScraper tried to start Ollama but it didn't start".

**Paste into §2 step 3:**
> The lock file holds the creator's PID and `process_identity` (reuse `web.jobs.process_identity` through a callable passed in, so `backends` imports nothing from web). A waiter that finds the lock younger than 90 s but whose creator is gone (`pid_alive` false or identity differs) treats it as stale at once. During the wait the waiter re-checks the lock each poll; if it vanished or went stale and the port still refuses, it takes the lock and spawns itself (once). Pin T9b: a lock whose PID is dead → one spawn immediately.

### C9 (MEDIUM) §4.5 Local AI card: the state must agree with the neutral line

**Evidence.** `_model_item` returns `attention` when the probe fails and `need` is true (`web/connections.py:409-410`). `need_reason` (c) holds for 24 h after any attempt that ended `model_unavailable` (`connections.py:347-351`), and (a)/(b) hold while an apply job runs. With autostart these are exactly the moments the app is starting the model. The design makes the **line** neutral, but the **state** would stay `attention`, so the shell badge, the banner and the "Auto-apply on" chip would still alert.

**Paste into §4.5:**
> In `_model_item`, when `facts.autostart` and `facts.installed` and `autostart_here` hold and the code is `unreachable`, the state is `neutral` (not `attention`) unless a pause in `MODEL_PAUSES` is stored, in which case it is `attention` with that pause's text. A recovered `model_unavailable` attempt (a later `submitted`/`ready_to_submit` attempt for the same job, or any later attempt that passed warm-up) no longer counts for rule (c). Vitest: unreachable + autostart on + installed + no stored pause → no attention count.

### C10 (LOW) §0: correct the diagnosis text

The probe cache is not what keeps a worker blind. A worker makes one probe per process and exits at its pause (`apply_flow.py:2025-2031`, `cli.py:1321-1335`); a new worker re-probes. The Q-120 review (`docs/reviews/Q-120-apply-queue-code.md`, row 5) records the opposite flaw: a cached **True** hides a model that died between roles. What actually produced the owner's banner is that nothing launches Ollama. `reset_probe` is still right: it makes the post-start `available` truthful and drops the thinking flag. Paste into §0 "Why nothing tries": replace the last sentence with "A cached probe never recovers within a process, so after a start the same backend must `reset_probe()`; that is the only reason for the cache change. Each process still probes once, not on every call."

### C11 (LOW) Up-next note text

`ApplyQueuePanel.vue:485` prints `Back at the front: {{ item.note }}`, with `note` stored as `'returned: <reason>'` (`store.py:415`). §3 row 2 stores `returned: model restarted`, so the owner reads "Back at the front: returned: model restarted"; §4.3 promises "the local AI model restarted". Paste: store the note as exactly `the local AI model restarted` for this path. That is safe: nothing parses the prefix (grep: only `apply_flow.py:1891,2029` write it). Pin T12 asserts the stored text.

### C12 (LOW) `OLLAMA_HOST` for the URL forms

`urlparse(...).hostname` for `http://[::1]:11434` is `::1`, so `OLLAMA_HOST=::1:11434` is wrong. Paste into §2 step 3: build the value as `f"[{host}]:{port}"` for an IPv6 host. A URL with no explicit port → `not_running`, no spawn (do not guess 80). Pin T4b.

### C13 (LOW) Merge order and int/Q-121 (§8, last paragraph)

Replace the paragraph with the order in "Merge order" below.

### C14 (LOW) Manual check (§9)

Add:
- (0) Before quitting Ollama, `curl http://127.0.0.1:11434/api/ps` must show no model loaded by another session. Quitting the tray app drops the shared GPU tools.
- (7) Optional: run step 3 as a web-started worker on a dev copy (`JOBSCRAPER_APPLY_QUEUE=1`, port 8768, mode `dry_run`, the copy's queue cleared), press Cancel during "Starting the local AI model…", and confirm `ollama.exe` survives. That is the one behaviour the intermediate launcher exists for, and no pin covers it.
- (8) Set `budget.ollama_path` to a non-existent file in a copy of config via `JOBSCRAPER_CONFIG` and confirm the `not_installed` pause text.

## Answers to the twelve questions

**1. Diagnosis.** The cited lines are right (`backends.py:130-154`; `apply_flow.py:1916`, `1899`, `2025`, `2151`; `store.py:1698`, `1721`; `applyqueue.py:209`; `routers/apply.py:411`; `cli.py:1321`; `pipeline.py:506-512`). The conclusion is half right (C10). Removal of the cache is done correctly: `reset_probe()` is called only inside an ensure (§2 step 6), not on every `available`. After an ensure the next `available` re-asks once.

**2. Launcher.**
- *What can run:* only a regular file named `ollama.exe` (case-insensitive) on Windows, `ollama` elsewhere, with argv exactly `[exe, "serve"]`, `shell=False`. On Windows it runs through a fixed `_LAUNCHER` constant with `-I -c`, with `exe` passed as an argument, not interpolated.
- *Can the web change it?* `ollama_path` is config.yaml only, enforced **by absence** today: there is no generic settings write (`PUT /settings` and `/apply/settings` take fixed keys; `web/` never writes config.yaml, and no code overlays `budget.*` from the settings table). That is adequate but only stated; T15 pins the ignoring of a stored row, which is the right enforcement. The only web-writable value is the boolean.
- *Name check enough?* No: see C3 (cwd-first `which`, PATH order, relative results).
- *Shell?* No.
- *Local URL?* `_target_is_local` compares the literal host to `{localhost, 127.0.0.1, ::1}` and rejects `-cloud`/`:cloud` tags. It does not resolve names, so `0.0.0.0`, a LAN IP and any other name are "remote" and never started. That is the right, conservative direction. The `OLLAMA_HOST` form needs C12.

**3. Lock and port.**
- *Two JobScraper processes:* handled by `O_EXCL`; the loser waits.
- *Stale lock:* age-only; see C8.
- *Tray app starting at the same time:* accepted LOW; one of the two servers fails to bind and the API is up either way.
- *Port taken:* detected by what the port answers (`/api/version` 200 JSON with `version`), not by a connect test. Sound, but one reply decides (C7).

**4. Slow vs dead.** Design: only `refused` spawns; `timeout` and `other` never do; nothing is killed. So a busy server is never restarted or killed. The defect is the other direction: one slow ping stores a pause (C7). Timeouts fit: the pre-take wait (60 + 330 s) runs outside any attempt deadline (`_Run.context()` sets the deadline per attempt, after the take), and the post-failure wait is also before the next take. `OllamaBackend.timeout` is 600 s, so `warm(timeout=330)` must be passed through in the same call (it is: §2 step 7). The cost is C1: nothing in the queue's own timers bounds a 390 s wait.

**5. The automatic retry (never twice).**
- *Can `model_unavailable` have clicked Submit?* No. `fail()` is the only writer of `failed` and runs only when `at.clicked` is false (`apply_flow.py:1013-1019`). `claim_click` commits `submit_clicked_at` before the click (`:829-846`). After the click every error goes to `unconfirmed()`, state `submitted_unconfirmed`, not `failed`. The pre-Submit scan precedes `submit()`. The design's extra store read (`submit_clicked_at is None`) is correct, and the row must still be `failed` (the existing return condition at `:2025-2028`). All five conditions hold with no new risk.
- *States it can be in:* a half-filled form in the apply Edge window (the page is closed in `attempt()`'s `finally`), a Workday account possibly created, a verification mail possibly requested, a resume possibly uploaded to a draft. All of these are exactly what the existing return plus Resume already produces. The retry restarts `body()` from the top, as a manual Resume does, so no new state class appears. The same mechanisms (sign-in with the vault entry, "already registered", the duplicate guard) apply.
- *Loop?* Per role, no (once). Per worker, bounded only by role count (C5). Per owner, Resume gives another single retry.
- One wording point: `TRANSPORT_FAILURE_MARKERS` and `_transport_cause` also yield "timed out", so a merely slow model ends the attempt `model_unavailable`. The retry then also covers "slow", with the 420 s cost. This is consistent with §7.

**6. Auto-resume.** See C2. The tick lift is more than D-214 asks. D-214's "carries on" is met by the pre-take start plus the one retry. The restart rule (§4.4's `queue_pause_if_waiting(…, replace=MODEL_PAUSES)`) is implementable and correct in itself: a stored model pause with waiting roles becomes `restarted`. A model pause with no waiting roles stays stored, and the next click is a fresh one. It does not interact badly with `_gate_closed`: the tick lift sits behind `kick()`'s gate check. "Within one app session" is not the right boundary (days); the pause's age is. What the owner sees before applications start again: today, nothing (no banner change; the banner just vanishes). With the C2 bound the owner sees the stored pause for at most 30 minutes of auto-lift; after that, a banner that waits.

**7. Other model users.**
- *Calling from each:* the CLI verbs that need the model (`apply`, `tailor`, `profile`, `titles suggest`) and the worker: right. Mail timer, card probe and tick report only: right.
- *Search run:* acceptable as written, because the decide step already loads the model when Ollama is up, and the new thing is only that an idle server starts. A scheduled (Task Scheduler / `run.ps1`) run at night would start Ollama and load the model for the judge; it never stops it. The shared GPU is not harmed (an idle `ollama serve` holds no VRAM; the model unloads after keep-alive). Accepted risk A2. D-214 literally says "when an application is asked for"; the Coordinator's Q-126 row adds "the other model users", so this is inside the scope the owner approved at the queue level. Keep the Settings switch text ("a search run or a resume task needs it") as the disclosure.
- *Tailor silently uploads the original resume:* the design only records it (§0) and neither fixes nor excuses it. It is existing behaviour (`apply_flow.py:856-873`, `resume()` logs "resume: original (…)" and records `resume_source = original`), and it is truthful to the owner only through the audit row. With the pre-take ensure the window narrows but remains: the model can die between the pre-take check and `resume()`; then the tailor falls back, and `warm_up` may find the model back and carry on with the untailored resume. Not a safety issue (the original is the owner's real resume, never a made-up one). Out of scope for Q-126, but file a follow-up (suggested id left to the Coordinator): "a tailor transport failure inside an attempt ends the attempt `model_unavailable` instead of falling back", with the design's retry then covering it.

**8. Off-switches.**
- *Dev copies / worktrees / `--config`:* off by the rule in §6.6; the worktree rule is the existing `running_from_worktree`. Gaps: a plain copy with no `.git` and no env counts as live; port is not part of the rule (`apply_queue_wanted` has it). C4(c) closes both with a positive DB condition.
- *Tests:* one env line plus defaults (C4).
- *Library defaults:* true for `ensure_model_running` (`autostart` is required, no default), `pipeline.run(model_autostart=False)` and `run_queue(model_autostart=…)` (the design must say its default is False; it does only for `pipeline`). Add that to §3.
- *What could start a real Ollama by accident:* a test or script that calls a `cmd_*` helper with a real `OllamaBackend` from the main checkout; a stale `=1` in the Coordinator's shell; a dev web instance in the main checkout on another port with no `JOBSCRAPER_DB`. All three are closed by C4.

**9. Owner-visible strings.** Truthful in each case I traced:
- "Nothing was sent" holds for every new text: all are pre-take or `failed` with no click (§5).
- The removed "The role it was on is back at the front" was false for a pre-take pause; correctly removed.
- "Your roles keep their place in the queue" is true: pre-take nothing was taken; post-item the role is returned in every branch.
- "tried to start Ollama, but it didn't start ({detail})" is false after a stale lock (C8).
- Style matches the other `QUEUE_PAUSE_TEXTS` (curly quotes around commands, the "Nothing was sent." tail).
- One action each? `model_unavailable` names two alternatives ("Start Ollama … Or turn on …"). The switch advice is wrong when the cause is a remote URL or `enable_llm: false` (both map to `MODEL_UNAVAILABLE`); LOW, accepted. `model_not_installed` names two sequential steps and says nothing for an install outside the default folders: LOW, suggest adding "If it is installed somewhere else, set budget.ollama_path in config.yaml." `model_port_taken` offers two alternatives. Acceptable.
- The Applications `ReasonCode.MODEL_UNAVAILABLE` hint "Try again…" is right for the queue path (C6).

**10. Contract additions.**
- *Additive:* yes. `QUEUE_PAUSE_TEXTS` has an entry for each new member (the `test_apply_contracts_v7` totality test passes). The Vue code does not map pause reasons: the server sends `text` and `hint` (`routers/apply.py:314-323`), and the panel only special-cases `disabled` (`ApplyQueuePanel.vue:192`). An unknown reason from a newer build already falls back to "paused" (`_pause_copy`). No exact-list pin exists for `QueuePause` or `RETURNS_ITEM` (grep: v7 only checks `hasattr`).
- *The one red pin:* C6; change the pin.
- *`{detail}` in hints:* `_pause_copy` formats only `text` (`routers/apply.py:318-323`), and `_Run.pause()` also (`apply_flow.py:1899-1906`). W1 and E2 must format hints, and a `{detail}` hint that reaches an old formatter shows raw braces, so W1 must land **before or with** E2 (it is harmless earlier: no stored pause carries a `{detail}` hint until E2 writes one).
- *Version:* the design says "still v7". `int/Q-121` has `CONTRACT_VERSION = 8`, so after the rebase the WP-0 comment must say "additive, no version bump (v8 at that point)".

**11. Work packages and the manual check.**
- *Complete?* The list covers the files. Two additions: the `{detail}` hint formatting rule is a W1 + E2 contract (state it in both rows), and the `Probe.installed` field belongs to E1 (backends) but its consumer is W1: the order E1 → W1 holds.
- *Disjoint?* Yes: no file appears in two rows.
- *Order:* "merge E2 together with W1" is stricter than needed; "W1 first or together, never E2 alone" is the real rule.
- *int/Q-121:* see Merge order.

**12. Simpler?** I would stake the review on one simplification only: delete the timer lift in §4.4 and keep Resume (the alternative in C2). D-214's example is "Ollama closed → click → it starts", which §3 row 1 already covers with no pause. Everything else carries its weight: the retry is what makes a mid-attempt close invisible, and the intermediate launcher is needed so the Cancel button does not kill the model (the design shows the tree-kill code, `jobs.py:290-309`).

## Merge order with `int/Q-121` (my recommendation)

**Land `int/Q-121` first (squash + scrub, as already planned), then rebase `arch/Q-126` WP-0 and start the Q-126 build lanes on the new `personal`.** Reasons:
- Q-126 is a design plus 85 lines of contract so far; nothing else is built, so rebasing it costs little. `int/Q-121` is large (8 source files, about 1700 inserted lines) and its squash needs the manual name scrub plus a deny-list scan, which should not be redone after a second merge.
- Hard conflicts if both are built in parallel:
  - **`backends.py`:** `int/Q-121` changed `Backend.warm`, `OllamaBackend.warm` and the module `warm()` to `warm(keep_alive, messages=None)` and added `PromptRefused`, `forbid` and `_guard`. Q-126 adds `OllamaBackend.warm(keep_alive, timeout)`. The merged signature must be `warm(keep_alive=None, messages=None, *, timeout=None)`. Tell the E1 engineer to make `timeout` keyword-only and to call it by keyword. One consequence: on `int/Q-121` the in-attempt `warm_up` sends the stable prefix, so §7's "the in-attempt `warm_up` is then a no-op" is only half true (the model is loaded; the prefix is not). That is a cost note, not a defect.
  - **`contracts.py`:** the version comment block (both append) and `REASON_TEXTS` next to `MODEL_UNAVAILABLE` (Q-121 hunk at :226-262); `CONTRACT_VERSION` is 8 there.
  - **`apply_flow.py`:** `run_queue`'s post-item block and `precheck` (Q-126) vs `pause_for` (Q-121 changes only the consent/streak lines, not the model branch). Expect textual conflicts only.
  - **`store.py`:** schema 8 vs the new `queue_*` functions: separate regions.
  - **`cli.py`:** both edit `cmd_doctor` (Q-121 +167 lines): the autostart line is adjacent.
  - **`web/routers/apply.py`:** Q-121 touches `queue_view` (:332-342 region); Q-126 adds `model` to the same view.
- **Do not base any Q-126 branch on `int/Q-121`:** its history holds the deny-listed name (handover). Build on the post-squash `personal` tip.

If the owner insists on starting E1 now, base it on `personal` and use the keyword-only `timeout`; expect the five textual conflicts above on the rebase.

Within Q-126: WP-0 → E1 → W1 → E2 → U1 → one bundle build (E2 and W1 together is fine).

## Accepted risks

- **A1.** The tray app starting at the same moment gives two servers racing for the port; one exits and the API is up either way. The headless server has no tray icon: Task Manager or sign-out ends it (design §7).
- **A2.** A scheduled search run, or the card, may start Ollama and load the model while the owner has closed it on purpose. It is idle after keep-alive, never killed, and covered by the Settings switch.
- **A3.** A user-writable folder earlier on PATH that holds a file named `ollama.exe` is trusted after C3 (a planted file there already means code execution as the owner).
- **A4.** `OLLAMA_MODELS` and other env changed after JobScraper started are stale in the spawned server (design §7).
- **A5.** `PUT /api/connections/model/autostart` has no CSRF token; the app has none anywhere, and the only effect is a boolean that lets the installed program start.
- **A6.** The tailor's silent fall back to the original resume is unchanged (follow-up above).
- **A7.** `model_unavailable` hint advice ("turn on the switch") is wrong when the cause is a remote URL or the AI switched off in config.

## What I checked and found sound

- **Layering.** `ensure_model_running`, `find_ollama`, `_spawn_detached` and `reset_probe` sit in `backends.py`, the only module allowed to call the model; `web/` and `apply_flow.py` already import `backends`; `-k layering` is 13/13 on the contract-only branch. The SQL for the new store functions is in `store.py`.
- **Never twice (NF-06).** The retry reads the store row, not memory (`apply_flow.py:2025-2028`); `claim_click` is untouched; `apply_duplicate` (`store.py:1502-1530`) refuses any job with a clicked or submitted attempt; a retry's second `failed/model_unavailable` row cannot be mistaken for a click.
- **No stop weakened.** Bot checks, caps, the pre-Submit scan and the duplicate guard are in `attempt()`/`guards()` and are untouched. A model pause still precedes every take (`queue_take` re-reads the pause, `store.py:1698`).
- **Exact argv and no shell.** The web can set one boolean; the URL, tag and path come from config.yaml/env.
- **Never kills.** There is no kill or stop code path in the helper; the tree-kill of Cancel does not reach the grandchild server (`jobs.py:290-309`, `web` jobs use `CREATE_NEW_PROCESS_GROUP`).
- **No download.** `/api/pull` is not called anywhere in the design, and T7 pins that.
- **Contract totality.** The new pauses all have text; the unknown-reason fallback exists; `MODEL_PAUSE_BY_CODE` covers every non-ready `ModelReady.code` listed in §2.
- **Manual check design.** `queue_clear()` first, the phantom queue row dropped by `queue_take` after the pre-take check (`store.py:1708-1711`), `--dry-run`, a copy of the DB, and the explicit "ask the other sessions" are all correct. The check never starts a browser.
- **Owner copy.** "Nothing was sent" is justified in every place it appears, and the removal of "back at the front" from the pre-take pause is right.
