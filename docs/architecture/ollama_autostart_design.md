# The local model starts itself (Q-126, D-214)

Status: design, 2026-11-15, architect. Not reviewed. Extends `apply_queue_design.md` (§3.2 worker loop, §4.1 pauses, §7.2 copy). It changes none of that design's stops. Contract: `apply/contracts.py`, still v7, additive (written with this design as WP-0, §5). Owner decision D-214: "ollama should automatically run when autoapply is selected".

## 0. Diagnosis (personal @ 9c3982e)

**The click to the banner.** `POST /api/apply` enqueues and calls `kick()` (`web/applyqueue.py:178-219`), which starts `jobscraper apply queue --parent-pid N`. `cli.py:1321` builds `backends.build(cfg.budget)`, then `run_queue` (`apply_flow.py:1957`) runs `precheck()` before any take (`apply_flow.py:1988-1992`). Line 1916 reads `backend.available`, which calls `OllamaBackend._probe` (`backends.py:130-154`): `GET /api/tags` with a 5 s cap raises ConnectError, so the code is `unreachable`. That failure is **cached for the life of the process** (`_probed`, `backends.py:132`). The worker then calls `pause(MODEL_UNAVAILABLE)` (`apply_flow.py:1899`) → `store.queue_pause` (`store.py:1721`) and exits 0. The Runs banner renders `QUEUE_PAUSE_TEXTS[MODEL_UNAVAILABLE]` (`contracts.py:291`, `routers/apply.py:314`). On this path the role was never taken, so "back at the front" was inaccurate: it simply stayed first.

Mid-attempt the same pause has three other sources, and each one returns the role (`apply_flow.py:2025`):
- the warm-up fails: `warm_up`, `apply_flow.py:1195-1205`;
- a page call fails (`transport_failed`): `apply_flow.py:1365-1372`;
- the compose call fails: `apply_flow.py:1459-1463`.

`pause_for` maps all three at `apply_flow.py:2151`.

**Why nothing tries.** Nothing in `src/` or `run.ps1` ever launches a process for Ollama. `backends.py` only speaks HTTP to it, and a stale cached probe would hide even an Ollama started by hand.

**Why Resume is manual.**
- The pause is stored. `queue_take` refuses while paused (`store.py:1698`), and so does `_kick` (`applyqueue.py:209`).
- Only `POST /api/apply/queue/resume` (`routers/apply.py:411`) clears the pause.
- Nothing ever re-checks the model.

**Other places a stopped Ollama reaches the owner:**
- Search run, judge step: `pipeline.py:506-512` logs "decide: skipped (…); N postings wait for a model". The run still "succeeds".
- Tailor: `cmd_tailor` prints "tailor failed" (`cli.py:645-651`). **Inside an attempt**, the tailor failure silently uploads the original resume (`apply_flow.py:856-873`).
- Profile re-derive: `resume_ingest.py:570-574` fails the job, and `_plan_applicant` prints `SKIP_MODEL_DOWN` (`cli.py:503-517`). The web shows "Start Ollama, then choose Re-read resume" (`ResumeRefresh.vue:157`).
- Titles suggest: `cli.py:562-580`.
- Mail sync: `mailstatus_flow.py:605-609, 665-667` adds a `model_unavailable` suggestion.
- Local AI card: the `ModelHealth` probe (`web/connections.py:466-566`) shows "Ollama isn't running … Start Ollama, then check again." (`connections.js:136-139`), and stays at attention for 24 h after a `model_unavailable` attempt (`connections.py:347-351`).
- `doctor`: `cli.py:120-126` prints "UNAVAILABLE - Ollama is not reachable … start it".

## 1. Decisions

1. **One service, `backends.ensure_model_running`.** It lives in `backends.py`, the only module allowed to call `/api/tags`. That keeps `tests/test_layering.py` passing with no edit: no new module to classify, and `web/` may already import `backends`.
2. **Who calls it.** The process that is about to use the model calls it. The Inbox click never calls it and never waits. The worker the click starts calls it within a second.
3. **Never stop the server.** JobScraper never stops or kills an Ollama, not even one it started. Ollama unloads the model itself after its keep-alive (5 min by default; apply passes `llm_fill.keep_alive`), so the GPU memory is freed anyway. An idle `ollama serve` holds no VRAM. A search run, the mail sync or the owner's own tools may be using the server. And stopping it would need PID tracking and kill logic this helper deliberately doesn't have.
4. **Start rule.** A start happens only when the port **refuses connections** (nothing is listening there). A server that answers, however slowly, is alive: it is never restarted or killed.
5. **Library defaults are off.** Every new parameter defaults to "do not start". Only `cli.py` turns autostart on, and only when the process rule (§6 rule 6) and the owner's switch (§4.5) both allow it.

## 2. The service (`backends.py`, WP-E1)

```python
@dataclass(frozen=True)
class ModelReady:
    code: str             # "ready" | "off" | "not_running" | "not_installed" | "start_failed"
                          # | "port_taken" | "not_answering" | "model_missing" | "load_failed"
    started: bool = False # this call launched `ollama serve`
    detail: str = ""      # a model tag, a port number or fixed words; never a path or URL
    seconds: float = 0.0
    @property
    def ok(self) -> bool: return self.code == "ready"

def ensure_model_running(budget, *, autostart: bool, backend: Backend | None = None,
        load: bool = False, keep_alive=None, on_state=lambda s: None,
        start_wait_s: float = 60.0, load_wait_s: float = 330.0,
        spawn=None, find=None, http=None, clock=time.monotonic, sleep=time.sleep,
        lock_dir: Path | None = None) -> ModelReady
def find_ollama(budget, env=os.environ) -> str | None
def autostart_allowed_here(env=os.environ, *, config_path=None, source_dir=None) -> bool
def autostart_switch(budget, get=None) -> bool   # settings `budget.ollama_autostart` over config, default True
OllamaBackend.reset_probe()                       # forget the cached probe and thinking flag
OllamaBackend.warm(keep_alive=None, timeout=None) # additive: timeout caps the load request
```

**Target.** The target is the given `OllamaBackend`'s `url` and `model_id`. Without one, the URL and model resolve exactly as `build` does (`JOBSCRAPER_OLLAMA_URL` wins). `configured_code(budget)` non-empty → `off`.

**Algorithm.** `ping` = `GET /api/version`, 3 s cap. It answers one of:
- `ollama`: HTTP 200 with a JSON `version` string;
- `refused`: `httpx.ConnectError`;
- `timeout`: any `httpx.TimeoutException`;
- `other`: anything else (another status, not JSON, a protocol error).

1. `ping`. On `other` → `port_taken` (detail = port). On `timeout` → `not_answering`. Neither ever spawns.
2. On `refused`: if `autostart` is false or `_target_is_local(url, model)` is false → `not_running`. Then `exe = find(budget)`; none found → `not_installed`. Its detail is the model tag, which the hint's pull command uses.
3. **Start lock.** The lock is `lock_dir or tempfile.gettempdir()` / `jobscraper-ollama-<port>.lock`, created with `os.open(O_CREAT|O_EXCL|O_WRONLY)`.
   - If we create it: `ping` again (someone may have just started it). Still `refused` → `on_state("starting")`, then `spawn([exe, "serve"], env + {"OLLAMA_HOST": "<host>:<port>"})`, and `started=True`. `OSError` → `start_failed` "the program wouldn't start".
   - If the file exists and is younger than `start_wait_s + 30` s, another JobScraper is starting Ollama: `on_state("starting")` and only wait. An older file is stale: delete it once and retry step 3.
   - The creator deletes the file in `finally`.
4. **Wait.** `ping` every 0.5 s, doubling to at most 2 s, until `ollama`, or until `start_wait_s` → `start_failed` "no answer after 60 seconds". `other` while waiting → `port_taken`.
5. **Model check.** `GET /api/tags` (5 s cap): the tag must be listed (no `:` means `:latest`, as `_probe`). Missing → `model_missing` (detail = tag). **Never `/api/pull`.**
6. `backend.reset_probe()` when a backend was given.
7. If `load`: `on_state("loading")`, then `backend.warm(keep_alive, timeout=load_wait_s)`. `BackendError` → `load_failed` (detail = tag). 330 s sits just above Ollama's own 5-minute load limit, so Ollama's error arrives first.
8. → `ready`. When Ollama is already up, steps 1, 5 and 7 cost two small GETs plus a no-op generate.

**`find_ollama` checks, in this order:**
1. `budget.ollama_path` (config.yaml only, §6);
2. `shutil.which("ollama")`;
3. On Windows: `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`, then `%ProgramFiles%\Ollama\ollama.exe`. On macOS: `/Applications/Ollama.app/Contents/Resources/ollama`, `/opt/homebrew/bin/ollama`, `/usr/local/bin/ollama`. On Linux: `/usr/local/bin/ollama`, `/usr/bin/ollama`.

A candidate counts only if it is an absolute path to an existing regular file named exactly `ollama.exe` on Windows (case-insensitive) or `ollama` elsewhere. A `.cmd`/`.bat` shim and the tray app `ollama app.exe` never count. An invalid configured path means "not found"; the search never falls through to another program.

**`spawn` (the default `_spawn_detached`):**
- **Windows:** it starts `[sys.executable, "-I", "-c", _LAUNCHER, exe, "serve"]` hidden (`CREATE_NO_WINDOW`, standard handles to DEVNULL) and waits up to 15 s for it to exit 0. `_LAUNCHER` is a fixed string constant. It launches `sys.argv[1:]` with `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB` (on `OSError`, it retries once without BREAKAWAY), DEVNULL handles and `close_fds`, then exits.
  - Why an intermediate: Cancel kills a job with `taskkill /T /F` (`web/jobs.py:290-309`), which walks parent PIDs. A server started as a grandchild whose parent has exited is outside every JobScraper tree.
  - It has its own hidden console, so closing the app's console window doesn't reach it either.
- **POSIX:** it starts `Popen([exe, "serve"], start_new_session=True, …DEVNULL, close_fds=True)`. Its own session, so the job's `killpg` doesn't reach it.

## 3. Call sites

| Caller (file) | Starts? | Load? | On failure |
|---|---|---|---|
| **Worker, before each take.** `_Run.precheck` (`apply_flow.py`), when `acfg.fill == "llm"` and `backend` is a real `OllamaBackend`. A fake backend keeps today's `available` rule, so pin P6 stands. | `run_queue(model_autostart=…)` | yes, with `llm_fill.keep_alive`; `num_ctx` is already set by cli | `MODEL_PAUSE_BY_CODE[code]` with `detail`. Nothing is taken, so the role stays first. |
| **Worker, after an item** whose `pause_for` result is `MODEL_UNAVAILABLE`, the row `failed` and `submit_clicked_at` null (read from the store, NF-06) | same | yes | `ready` and the job not yet in `self.model_retried`: add it, `queue_return(…, note "returned: model restarted")`, log, **continue with no pause**. `ready` but already retried: pause `MODEL_NOT_ANSWERING`. Not ready: the mapped pause. The role is returned in every case (RETURNS_ITEM). |
| **Inbox click** `POST /api/apply`, and **Resume** | through the worker only | | The routes never call the model or wait. The kick starts the worker, and its first act is the pre-take call above. When a search run holds the slot, that run brings the model up for its judge step, and the worker brings it up when it starts. |
| `apply <ids>` (`cmd_apply`), `tailor` (`cmd_tailor`), `profile` (`cmd_profile`, before ingest; `_plan_applicant` needs the model every time), `titles suggest` (`cli.py`) | yes (`_ensure_model(cfg, store, args)` helper in cli) | no (the first call loads it) | One log line, then the command goes on as today and reports its own failure. |
| Search run: decide step (`pipeline.py`) | only when postings are waiting, through a new `pipeline.run(…, model_autostart=False)` kwarg that `cmd_run` sets | no | The existing skip line, with the code's words: "decide: skipped (Ollama isn't installed); N postings wait for a model". |
| Mail sync timer, Local AI card probe, queue tick | **no, report only** | | A background timer must never start Ollama: the owner may have closed it on purpose. |
| `doctor` | no, reports only | | It prints `autostart      on (found: default install location)` or `on, but Ollama isn't installed`, `off (Settings → Local AI)`, `off in this copy (JOBSCRAPER_DB, worktree or test)`. Never a path. |

**Worker state.** `on_state` writes `apply_queue.model` (`starting`/`loading`) and `apply_queue.model_at`. A `finally` clears them, and the next worker clears them at its start.

**Worker log lines:**
- `model: starting Ollama`
- `model: Ollama answered after 4 s`
- `model: loading qwen3:14b`
- `model: ready (31 s)`
- `model: <code> <detail>`
- `queue: the local AI model stopped answering; it is ready again, so job=<id> goes again (once)`

## 4. What the owner sees

**4.1 Runs → Auto-apply queue, while the model is starting.** The `GET /api/apply/queue` view gains `model: null | {state, since}`, shown only while `slot == "apply"`. When `now` is null, the "Now applying" slot shows one row, with no pause and no Stop button:
- **"Starting the local AI model…"** with the elapsed time;
- then **"Loading the model…"** with the line "The first load can take a minute."

Pause still works: the worker checks it before its take. When the model is ready, the role is taken as usual. No banner appears and no Resume is needed.

**4.2 Pauses (text / hint, as written into `contracts.py`):**
- `model_not_installed`: "JobScraper couldn't find Ollama on this computer, so the queue is paused. Nothing was sent." / "Install Ollama from ollama.com, then download the model with “ollama pull {detail}”. The queue continues by itself once the model answers."
- `model_start_failed`: "JobScraper tried to start Ollama, but it didn't start ({detail}). The queue is paused. Nothing was sent." / "Open Ollama from the Start menu. The queue continues by itself once it answers." The detail is "no answer after 60 seconds" or "the program wouldn't start".
- `model_missing`: "The AI model {detail} isn't downloaded, so the queue is paused. Nothing was sent." / "Download it in a terminal with “ollama pull {detail}” (several GB). The queue continues by itself when it's ready." For example: “ollama pull qwen3:14b”.
- `model_port_taken`: "Another program is using port {detail}, where Ollama should run, so the queue is paused. Nothing was sent." / "Close that program, or set budget.ollama_url in config.yaml to Ollama's address. The queue continues by itself once Ollama answers."
- `model_load_failed`: "Ollama is running but couldn't load the model {detail}, so the queue is paused. Nothing was sent." / "Another program may be using the graphics card. Close it, then resume. Your roles keep their place in the queue."
- `model_not_answering`: "The local AI model is running but not answering in time, so the queue is paused. Nothing was sent." / "Another program may be using the graphics card. Close it or let it finish, then resume. Your roles keep their place in the queue."
- `model_unavailable` (changed): "The local AI model isn't running, so the queue is paused. Nothing was sent." / "Start Ollama and the queue continues by itself. Or turn on “Start the local AI model when it is needed” in Settings → Accounts → Local AI." This pause is now stored only when nothing listens and JobScraper didn't try: the switch is off, the URL is not on this computer, or `budget.enable_llm` is off.
- Applications row, `ReasonCode.MODEL_UNAVAILABLE` hint (changed): "Try again. If the local AI model still can't start, the Auto-apply queue in Runs says why."

`_pause_copy` (`routers/apply.py`) and the worker's `pause()` log line now format the **hint** with `{detail}` too, inside the same try/except.

**4.3 Retry.** The automatic retry (§3, row 2) shows only as the Up-next note "Back at the front: the local AI model restarted".

**4.4 Resuming by itself.** On each 5 s tick, after its gate and `enabled` checks, `ApplyQueueRunner._kick` lifts the pause when all of these hold:
- the stored pause reason is in `MODEL_AUTO_RESUME`;
- `app.state.model_health.snapshot()` is `ok` (Ollama answers and the model is pulled; the probe is non-blocking and runs every 15 s while failing).

It lifts it with `store.queue_resume_if(MODEL_AUTO_RESUME, now)`, a compare-and-clear in one `BEGIN IMMEDIATE` (an owner or cancel pause that replaced it is never lifted), then starts the worker.

That covers every model pause stored in the current app session. The owner's current pause, stored by the old build, becomes `restarted` at the upgrade restart: one Resume, then the worker starts Ollama itself. **Across a restart D-200 holds:** the start-up hook, `queue_pause_if_waiting(RESTARTED, now, replace=MODEL_PAUSES)`, turns a stored model pause into `restarted`. Roles from the last session therefore need one Resume, and from there the worker starts Ollama itself. `model_load_failed` and `model_not_answering` never lift by themselves, because a server that answers proves nothing for those causes and the lift would loop.

**4.5 Settings → Accounts → Local AI card.**
- **The switch.** A switch row sits under the card's status line, above "Check again":
  - label "Start the local AI model when it is needed";
  - description "JobScraper starts Ollama and loads the model when auto-apply, a search run or a resume task needs it. It never downloads a model.";
  - value On / Off.
  - It uses the existing settings mechanism: the settings-table key `budget.ollama_autostart` (`"true"`/`"false"`) over config.yaml over the code default **true**.
  - It saves on toggle through the new `PUT /api/connections/model/autostart {enabled: bool}`. That returns 200 `{enabled, default}`, or 422 `{detail:"invalid", errors:[{field:"enabled", message:"Start the local AI model must be true or false"}]}`.
  - Saving and errors follow the q116 §3/§5 rules: no optimistic flip, "Saved", "Couldn't save: …".
  - When `facts.autostart_here` is false, the row is read-only and its description gains " Not in this copy of JobScraper."
- **Card facts (additive).** `autostart`, `autostart_here`, `installed`.
  - `installed` comes from a new `Probe.installed: bool | None = None`, which `backends.probe` fills with `find_ollama(budget) is not None` for a local Ollama. It is filled in the `ModelHealth` probe thread, never in the GET.
  - `autostart_here` is `autostart_allowed_here(os.environ, config_path=<the app's>)`.
  - No path goes to the browser.
- **Card line (code `unreachable`):**
  - autostart on and installed: "Ollama isn't running. JobScraper starts it when a task needs it." (neutral);
  - not installed: "Ollama isn't installed. Install it from ollama.com to use the local AI.";
  - autostart off: today's copy.
- **`ResumeRefresh.vue:157`:** "Couldn't compare with your application details: the local AI model couldn't start. See Settings → Accounts → Local AI."

## 5. Contract, config and store deltas (all additive; no schema change)

- **Contract (WP-0, done here; still v7):**
  - `QueuePause` gains `MODEL_NOT_INSTALLED`, `MODEL_START_FAILED`, `MODEL_MISSING`, `MODEL_PORT_TAKEN`, `MODEL_LOAD_FAILED` and `MODEL_NOT_ANSWERING`, with the §4.2 texts.
  - `RETURNS_ITEM` gains the six.
  - New: `MODEL_PAUSES`, `MODEL_AUTO_RESUME`, `MODEL_PAUSE_BY_CODE`.
  - Reworded: the two `MODEL_UNAVAILABLE` hints, plus the pause text "isn't answering" → "isn't running".
- **Config (`config/config.yaml`, WP-E2):** `budget.ollama_autostart: true`, and a commented `# ollama_path:` with a note: "only a file named ollama.exe; config.yaml only".
- **Store (`store.py`, WP-E1; settings rows, no SQL outside store):**
  - `queue_model_state(state: str | None, now)` commits; None deletes both keys.
  - `queue_model_view() -> {state, since} | None`.
  - `queue_resume_if(reasons, now) -> bool` is a compare-and-clear that also sets `resumed_at`.
  - `queue_pause_if_waiting(reason, now, *, replace=frozenset())` overwrites a stored pause whose reason is in `replace`.

## 6. Safety rules

1. **Local URLs only.** Only `_target_is_local` targets are started: 127.0.0.1, localhost or ::1, and no `-cloud`/`:cloud` tag. Anything else → `not_running`.
2. **Fixed argv.** It is exactly `[exe, "serve"]` with `shell=False`. The env adds only `OLLAMA_HOST`. `exe` must pass the §2 name and file checks.
   - `budget.ollama_path` is read from config.yaml **only**. No route writes it. Neither `with_settings` nor `autostart_switch` reads a settings-table `budget.ollama_path`; a pin checks that a stored row for it is ignored.
   - The web can change only the boolean switch.
3. **Nothing is downloaded.** A missing model is reported with its pull command and never pulled.
4. **No admin, hidden.** A plain CreateProcess as the current user: no `runas`, no service, no window.
5. **Never kills, never restarts a live server.** A start happens only on `refused`. A slow, busy or foreign listener is never touched.
6. **Dev copies and tests never start a real Ollama.** `autostart_allowed_here` gives:
   - `JOBSCRAPER_OLLAMA_AUTOSTART=0` → off, `=1` → allowed;
   - unset → off when `JOBSCRAPER_DB` or `JOBSCRAPER_CONFIG` is set, when `--config` is given, or when the code runs from a git worktree. The worktree rule moves to `backends.running_from_worktree`, and `web/applyqueue.py` delegates to it.

   Tests have three guards on top: `tests/run_tests.py` sets `JOBSCRAPER_OLLAMA_AUTOSTART=0` before any import; every library default is off (§1.5); the worker calls the service only with a real `OllamaBackend`. Every pin injects `spawn`, `find` and `http`.
7. **No stop is weakened.** The one retry is the existing return rule (`failed`, no Submit click, read from the store), applied once automatically. Bot checks, never-twice, caps and the pre-Submit scan are untouched, and a model pause still comes before any take.

## 7. Edge cases

- **The tray app is starting at the same moment.** Our ping is `refused`, so we spawn. One of the two servers fails to bind and exits, and the API is up either way. Accepted LOW: our headless server has no tray icon. The owner stops it in Task Manager (`ollama.exe`) or by signing out.
- **A slow first load.** The panel shows "Loading the model…". The pre-take load has no attempt deadline, and the in-attempt `warm_up` is then a no-op.
- **The GPU is busy with another program.** Slow is not dead: `/api/version` still answers, so the server is never restarted. A timed-out page call gets one retry, then `model_not_answering`.
- **The owner closes Ollama mid-attempt.** The page call is refused, the attempt fails with no click, the server is started again and the role goes once more. A second close pauses. After the Submit click no retry is possible (NF-06).
- **Two JobScraper processes start it at once.** The per-port lock: the second waits and never spawns.
- **A non-default port.** `OLLAMA_HOST` comes from the URL, the lock name carries the port, and `port_taken` names it.
- **Accepted LOW: `OLLAMA_MODELS` changed after JobScraper started.** The inherited environment is stale, so the server may report `model_missing`. Restarting JobScraper fixes it.

## 8. Work packages (disjoint files)

| WP | Lane | Files | After | Verify |
|---|---|---|---|---|
| WP-0 | architect | `apply/contracts.py` (done) | | `-k apply_contracts` |
| WP-E1 | engineer | `backends.py`, `store.py` | WP-0 | `-k backends`, `-k store`, `-k layering` |
| WP-E2 | engineer | `apply_flow.py`, `cli.py`, `pipeline.py`, `config/config.yaml` | E1 | `-k apply_flow`, `-k apply_queue`, `-k apply_e2e` (separately), `-k pipeline`, `-k cli` |
| WP-W1 | web engineer | `web/applyqueue.py`, `web/routers/apply.py`, `web/connections.py`, `web/routers/connections.py` | E1 | `-k web_apply`, `-k connections`, `-k apply_queue`, `-k layering` |
| WP-U1 | frontend | `web/src/components/ApplyQueuePanel.vue`, `web/src/connections.js`, `web/src/components/ConnectionsHub.vue`, `web/src/connections_api.js`, `web/src/components/ResumeRefresh.vue` | W1 | `cd web; npx vitest run` |
| WP-T | tester | `tests/run_tests.py` (env line), `tests/test_q126_*.py` (new), retargeted pins (`web/tests/connections.test.js:148`, `q44-refresh.test.js:371`) | each lane | as above |

**Merge order:** WP-0 → E1 → E2 and W1 together (E2 produces hints with `{detail}`, and W1 formats them) → U1 → one bundle build in the main checkout. `int/Q-121` also touches `apply_flow.py` and `contracts.py`. Whichever lands second rebases; the contract lines are additive, so expect only textual conflicts.

## 9. Pins (fakes only; no test starts a process) and the manual check

**Seams:** `spawn`, `find`, `http` (a fake client that records every URL), `clock`/`sleep` (fake time), `lock_dir` (tmp); `run_queue(model_ensurer=…, model_autostart=…)`; a fake `ModelHealth` for the tick.

**Pins:**
- **T1** Already running → `ready`, no spawn.
- **T2** `refused` → one spawn `[exe, "serve"]` with `OLLAMA_HOST=127.0.0.1:<port>`; ready on the 3rd ping; states `starting`.
- **T3** No exe → `not_installed`. A configured `ollama.bat`, `cmd.exe` or `ollama app.exe`, or a relative path → `not_installed`, no spawn.
- **T4** autostart off, a remote URL or a cloud tag → `not_running`, no spawn.
- **T5** spawn `OSError` / no answer within 60 fake seconds → `start_failed` with each detail.
- **T6** `other` → `port_taken`; `timeout` → `not_answering`; neither spawns.
- **T7** Tag absent → `model_missing`; no `/api/pull` is ever requested.
- **T8** Load fails → `load_failed`; warm gets `timeout ≤ 330`.
- **T9** A fresh lock → no spawn, then ready; a stale lock → one spawn; two threads at once → exactly one spawn.
- **T10** `reset_probe` makes a failed backend available.
- **T11** Worker, each code → the mapped pause, no attempt row, the role still first, the model state cleared; `ready` → the take proceeds; P6 still passes.
- **T12** Retry: the first `failed/model_unavailable` → returned with the note, no pause, a second attempt runs; the second failure → `model_not_answering`; a row with `submit_clicked_at` → never retried.
- **T13** Auto-resume lifts the five reasons only when the probe is ok. It never lifts owner, cancelled, load_failed or not_answering; it fails the compare-and-clear when the reason changed.
- **T14** At start-up a stored model pause plus waiting roles → `restarted`.
- **T15** `autostart_allowed_here`: env `0`/`1`/unset combined with `JOBSCRAPER_DB`, `JOBSCRAPER_CONFIG`, `--config` and a worktree. `budget.ollama_path` in the settings table is ignored.
- **T16** The PUT route accepts only a bool. The GET connections body holds no path (no `\` or `:/` in the facts).
- **T17** Layering passes.
- **T18** pipeline: the service is called only when postings wait.
- **Vitest:** the two panel states, the card lines, the switch row saving and reverting.

**Manual check (Coordinator, real machine, DRY RUN, DB copy; ask the other live sessions first, because Ollama on 11434 is shared):**
1. Quit Ollama (tray → Quit). `curl http://127.0.0.1:11434/api/version` must be refused.
2. Copy `data/jobscraper.db`. In the copy, through `Store`:
   - **`queue_clear()` first.** The copy holds the owner's real waiting roles, and a worker on the copy would take them.
   - `queue_resume`, then `set_setting("apply.mode","dry_run")`.
   - `queue_add("q126-phantom", None, "dry_run", "inbox", now)`, then `commit()`.
   - That job id has no applications row, so `queue_take` drops it **after** the pre-take check and no browser opens.
   - Before step 3, check that `queue_items()` lists only the phantom.
3. `JOBSCRAPER_DB=<copy> JOBSCRAPER_OLLAMA_AUTOSTART=1 python -m jobscraper apply queue --dry-run`.
   - Expect the log lines `model: starting Ollama` … `model: ready (…)`, then `queue: job=q126-phantom no longer To apply; skipped`, exit 0.
   - The API now answers, and `ollama.exe` runs with no console window.
4. Run step 3 again: no new process, `ready` within 1 s.
5. Close the terminal used in step 3; the API still answers.
6. In the copy, `set_setting("budget.ollama_autostart","false")` and quit Ollama. Step 3 now gives the pause `model_unavailable` with the new text.

**Requirement map:**

| Requirement | Where |
|---|---|
| D-214 automatic start | §2, §3 |
| No manual step | §3 row 2, §4.4 |
| A precise single pause | §4.2 |
| D-200 restart rule | §4.4 |
| NF-06 | §3 row 2, §6 rule 7 |
| NF-04 layering | §1.1, §6 rule 6 |
| D-205 queue unchanged otherwise | §3 |

**Open (Coordinator):**
- (a) Confirm that D-200 also covers model pauses across a restart (§4.4); the alternative is auto-resume across restarts too.
- (b) File this as ADR-0012, or accept it as an additive amendment of ADR-0010. My recommendation: an ADR, because the app now launches a program.
