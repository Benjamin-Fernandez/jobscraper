# The local model starts itself (Q-126, D-214)

Status: **READY TO BUILD (rev 2, after review, 2026-11-15)**. Architect. Review: `docs/reviews/Q-126-ollama-autostart-design.md` (READY WITH CHANGES; every item C1-C14 is folded, see §12). Coordinator rulings R1-R7 (to be recorded as **D-217**) are binding and visible here. ADR: `adr/0013-app-starts-local-model.md`. Extends `apply_queue_design.md` (§3.2 worker loop, §4.1 pauses, §7.2 copy) and changes none of its stops. Contract: `apply/contracts.py`, additive, no version bump (v7 on `personal`; v8 after the later merge into `int/Q-121`). Owner decision D-214: "ollama should automatically run when autoapply is selected".

**Built on `personal`, ships first and alone (R5).** Never base a Q-126 branch on `int/Q-121`. §10 says how each lane shapes its edit so the later `personal` → `int/Q-121` merge stays mechanical.

## 0. Diagnosis (personal @ 9c3982e)

**The click to the banner.** `POST /api/apply` enqueues and calls `kick()` (`web/applyqueue.py:178-219`), which starts `jobscraper apply queue --parent-pid N`. `cli.py:1321` builds `backends.build(cfg.budget)`, then `run_queue` (`apply_flow.py:1957`) runs `precheck()` before any take (`apply_flow.py:1988-1992`). Line 1916 reads `backend.available`, which calls `OllamaBackend._probe` (`backends.py:130-154`): `GET /api/tags` with a 5 s cap raises ConnectError, so the code is `unreachable`. The worker calls `pause(MODEL_UNAVAILABLE)` (`apply_flow.py:1899`) → `store.queue_pause` (`store.py:1721`) and exits 0. The Runs banner renders `QUEUE_PAUSE_TEXTS[MODEL_UNAVAILABLE]` (`contracts.py`, `routers/apply.py:314`). On this path the role was never taken, so the old hint "back at the front" was inaccurate: it simply stayed first.

Mid-attempt the same pause has three other sources, and each one returns the role (`apply_flow.py:2025`):
- the warm-up fails: `warm_up`, `apply_flow.py:1195-1205`;
- a page call fails (`transport_failed`): `apply_flow.py:1365-1372`;
- the compose call fails: `apply_flow.py:1459-1463`.

`pause_for` maps all three at `apply_flow.py:2151`.

**Why nothing tries (corrected, C10).** Nothing in `src/` or `run.ps1` ever launches a process for Ollama: that alone produced the owner's banner. The probe cache is not the cause: each worker probes once and exits at its pause, and the next worker probes again. A cached probe never recovers within a process, so after a start the same backend must `reset_probe()`; that is the only reason for the cache change. Each process still probes once, not on every call.

**Why Resume is manual.**
- The pause is stored. `queue_take` refuses while paused (`store.py:1698`), and so does `_kick` (`applyqueue.py:209`).
- Only `POST /api/apply/queue/resume` (`routers/apply.py:411`) clears the pause.
- Nothing ever re-checks the model.

**Other places a stopped Ollama reaches the owner:**
- Search run, judge step: `pipeline.py:506-512` logs "decide: skipped (…); N postings wait for a model". The run still "succeeds".
- Tailor: `cmd_tailor` prints "tailor failed" (`cli.py:645-651`). **Inside an attempt**, the tailor failure silently uploads the original resume (`apply_flow.py:856-873`): named follow-up F1 (§11), not part of this build.
- Profile re-derive: `resume_ingest.py:570-574` fails the job, and `_plan_applicant` prints `SKIP_MODEL_DOWN` (`cli.py:503-517`). The web shows "Start Ollama, then choose Re-read resume" (`ResumeRefresh.vue:157`).
- Titles suggest: `cli.py:562-580`.
- Mail sync: `mailstatus_flow.py:605-609, 665-667` adds a `model_unavailable` suggestion.
- Local AI card: the `ModelHealth` probe (`web/connections.py:466-566`) shows "Ollama isn't running … Start Ollama, then check again." (`connections.js:136-139`), and stays at attention for 24 h after a `model_unavailable` attempt (`connections.py:347-351`).
- `doctor`: `cli.py:120-126` prints "UNAVAILABLE - Ollama is not reachable … start it".

## 1. Decisions

1. **One service, `backends.ensure_model_running`.** It lives in `backends.py`, the only module allowed to call `/api/tags`. `tests/test_layering.py` passes with no edit: no new module to classify, and `web/` may already import `backends`.
2. **Who calls it.** The process that is about to use the model calls it. No web route calls it or waits on it: an HTTP request cannot hold for up to 6.5 minutes. The worker that a click or Resume starts calls it as its first act, before any take.
3. **Never stop the server.** JobScraper never stops or kills an Ollama, not even one it started. Ollama unloads the model itself after its keep-alive (5 min by default; apply passes `llm_fill.keep_alive`), so the GPU memory is freed anyway. An idle `ollama serve` holds no VRAM. A search run, the mail sync or the owner's own tools may be using the server.
4. **Start rule.** A start happens only when the port **refuses connections** three times (§2 step 1). A server that answers, however slowly, is alive: it is never restarted or killed.
5. **Library defaults are off.** Every new parameter defaults to "do not start": `ensure_model_running(autostart=…)` has no default, `run_queue(model_autostart=False)`, `pipeline.run(model_autostart=False)`. Only `cli.py` turns autostart on, and only when the process rule (§6 rule 6) and the owner's switch (§4.5) both allow it.
6. **No timed resume (R1).** A model pause lifts **only on an owner click**: Resume, or a new Inbox Auto-apply click (§4.4). No timer, tick, probe or background task ever lifts a pause.

## 2. The service (`backends.py`, WP-E1)

```python
@dataclass(frozen=True)
class ModelReady:
    code: str             # "ready" | "off" | "not_running" | "not_installed" | "start_failed"
                          # | "port_taken" | "not_answering" | "model_missing" | "load_failed"
                          # | "cancelled" (should_stop turned true; maps to no pause: the caller returns)
    started: bool = False # this call launched `ollama serve`
    detail: str = ""      # a model tag, a port number or fixed words; never a path or URL
    seconds: float = 0.0
    @property
    def ok(self) -> bool: return self.code == "ready"

def ensure_model_running(budget, *, autostart: bool, backend: Backend | None = None,
        load: bool = False, keep_alive=None, on_state=lambda s: None,
        should_stop: Callable[[], bool] = lambda: False,
        start_wait_s: float = 60.0, load_wait_s: float = 330.0,
        spawn=None, find=None, http=None, pid_alive: Callable[[int], bool] | None = None,
        clock=time.monotonic, sleep=time.sleep, lock_dir: Path | None = None) -> ModelReady
def find_ollama(budget, env=os.environ, *, cwd: Path | None = None,
        checkout: Path | None = None) -> str | None
def autostart_allowed_here(*, db_path, env=os.environ, config_given: bool = False,
        source_dir=None) -> bool
def running_from_worktree(source_dir=None) -> bool   # moved here from web/applyqueue.py (unchanged)
def autostart_switch(budget, get=None) -> bool       # settings `budget.ollama_autostart` over config, default True
OllamaBackend.reset_probe()                          # forget the cached probe and thinking flag
warm(keep_alive=None, *, timeout=None)               # Backend.warm, OllamaBackend.warm and module warm():
                                                     # `timeout` is KEYWORD-ONLY and always passed by keyword (R5)
```

**Target.** The given `OllamaBackend`'s `url` and `model_id`. Without one, the URL and model resolve exactly as `build` does (`JOBSCRAPER_OLLAMA_URL` wins). `configured_code(budget)` non-empty → `off`.

**`should_stop` (R2, C1).** Every wait loop below and the warm call poll `should_stop()` at least every 2 s. The warm runs in a daemon thread so the poll works; when `should_stop()` turns true the service returns `ModelReady("cancelled")` at once (the load request may finish in its thread; the process is about to exit). A start lock it holds is released in `finally` as usual.

**Algorithm.** `ping` = `GET /api/version`. One **try** answers one of:
- `ollama`: HTTP 200 with a JSON `version` string;
- `refused`: `httpx.ConnectError`;
- `timeout`: any `httpx.TimeoutException`;
- `other`: anything else (another status, not JSON, a protocol error).

**One ping = up to 3 tries, 1 s apart, 5 s cap each (C7).** The first `ollama` answer wins at once. Three `refused` → `refused`. Three `other` → `other`. Three `timeout`, or any other mix → `timeout`. Worst case before a decision outside a start: under 20 s.

1. `ping`. On `other` → `port_taken` (detail = port). On `timeout` → `not_answering`. Neither ever spawns.
2. On `refused`: if `autostart` is false or `_target_is_local(url, model)` is false → `not_running`. A URL with no explicit port → `not_running` (never guess a port; C12). Then `exe = find(budget)`; none found → `not_installed`. Its detail is the model tag, which the hint's pull command uses.
3. **Start lock (C8).** The lock is `lock_dir or tempfile.gettempdir()` / `jobscraper-ollama-<port>.lock`, created with `os.open(O_CREAT|O_EXCL|O_WRONLY)`. The creator writes its own PID (`os.getpid()`, one line) into it at once.
   - If we create it: `ping` again (someone may have just started it). Still `refused` → `on_state("starting")`, then `spawn([exe, "serve"], env + {"OLLAMA_HOST": host_port})`, and `started=True`. `OSError` → `start_failed` "the program wouldn't start". `host_port` is `f"{host}:{port}"`, or `f"[{host}]:{port}"` for an IPv6 host such as `::1` (C12).
   - If the file exists: read its PID. The lock is **stale at once** when the PID is unreadable after 2 s, or `pid_alive(pid)` is false (the creator was killed, for example by Cancel's `taskkill /F`). It is also stale when older than `start_wait_s + 30` s. A stale lock is deleted once and step 3 retried. A live creator's fresh lock: `on_state("starting")` and only wait.
   - While waiting, the waiter re-reads the lock on each poll. If it vanished or went stale and the port still refuses, the waiter takes the lock and spawns itself (once).
   - With `pid_alive=None` (library default) only the age rule applies; `cli.py` passes `web.jobs.pid_alive` (a lazy import in cli; `backends` never imports `web`).
   - The creator deletes the file in `finally`.
4. **Wait.** `ping` every 0.5 s, doubling to at most 2 s, until `ollama`. Inside this wait `other` and `timeout` simply continue the poll (a server that is binding may answer oddly for a second; C7). At `start_wait_s` the last answer decides: `refused` → `start_failed` "no answer after 60 seconds"; `other` → `port_taken`; `timeout` → `not_answering`.
5. **Model check.** `GET /api/tags` (5 s cap): the tag must be listed (no `:` means `:latest`, as `_probe`). Missing → `model_missing` (detail = tag). **Never `/api/pull`.**
6. `backend.reset_probe()` when a backend was given.
7. If `load`: `on_state("loading")`, then `backend.warm(keep_alive, timeout=load_wait_s)` in its thread, polling `should_stop`. `BackendError` → `load_failed` (detail = tag). 330 s sits just above Ollama's own 5-minute load limit, so Ollama's error arrives first.
8. → `ready`. When Ollama is already up, steps 1, 5 and 7 cost two small GETs plus a no-op generate.

**`find_ollama` (C3, R3).** It **never calls `shutil.which`** (on Windows it searches the current directory first). Order:
1. `budget.ollama_path` (config.yaml only, §6 rule 2). If set and it fails the rule below → `None` (fatal: never fall through to another program).
2. The default install locations. Windows: `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`, then `%ProgramFiles%\Ollama\ollama.exe`. macOS: `/Applications/Ollama.app/Contents/Resources/ollama`, `/opt/homebrew/bin/ollama`, `/usr/local/bin/ollama`. Linux: `/usr/local/bin/ollama`, `/usr/bin/ollama`.
3. Each entry of `env["PATH"]` that is an absolute directory and resolves neither to the current directory (`cwd`, default `Path.cwd()`) nor to the checkout (`checkout`, default the repository root of the running source) nor below it, joined with `ollama.exe` (Windows) or `ollama`.

Every candidate is `Path.resolve()`d first. It counts only as an existing regular file named exactly `ollama.exe` on Windows (case-insensitive) or `ollama` elsewhere. A `.cmd`/`.bat` shim and the tray app `ollama app.exe` never count. A failing candidate in (2) or (3) is skipped; the first passing one wins.

**`spawn` (the default `_spawn_detached`):**
- **Test guard first (C4b).** It raises `OSError("autostart is off here")` before anything else when `os.environ.get("JOBSCRAPER_OLLAMA_AUTOSTART") == "0"`, or when `"run_tests"` or `"pytest"` is in `sys.modules`. A real start is then impossible even if a caller passes `autostart=True`; the result is `start_failed`.
- **Windows:** it starts `[sys.executable, "-I", "-c", _LAUNCHER, exe, "serve"]` hidden (`CREATE_NO_WINDOW`, standard handles to DEVNULL) and waits up to 15 s for it to exit 0. `_LAUNCHER` is a fixed string constant. It launches `sys.argv[1:]` with `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW | CREATE_BREAKAWAY_FROM_JOB` (on `OSError`, it retries once without BREAKAWAY), DEVNULL handles and `close_fds`, then exits.
  - Why an intermediate: Cancel kills a job with `taskkill /T /F` (`web/jobs.py:290-309`), which walks parent PIDs. A server started as a grandchild whose parent has exited is outside every JobScraper tree.
  - It has its own hidden console, so closing the app's console window doesn't reach it either.
- **POSIX:** `Popen([exe, "serve"], start_new_session=True, …DEVNULL, close_fds=True)`. Its own session, so the job's `killpg` doesn't reach it.

## 3. Call sites

| Caller (file) | Starts? | Load? | On failure |
|---|---|---|---|
| **Worker, before each take.** `_Run.precheck` (`apply_flow.py`), when `acfg.fill == "llm"` and `backend` is a real `OllamaBackend`, through a new method `_Run.ensure_model(load=True)` that passes `should_stop=self.should_stop`. A fake backend keeps today's `available` rule, so pin P6 stands. | `run_queue(model_autostart=False)` default; cli sets it | yes, with `llm_fill.keep_alive`; `num_ctx` is already set by cli | `MODEL_PAUSE_BY_CODE[code]` with `detail`. `cancelled` → `precheck` returns `(APP_CLOSED, None)`. Nothing is taken, so the role stays first. |
| **Stop re-check (R2, C1).** `run_queue` calls `self.should_stop()` again **immediately after `precheck()` returns and before `queue_take`**. True → `pause(APP_CLOSED)` and break, exactly like the loop top. A worker never takes a role after the owner closed the app. | | | |
| **Worker, after an item** whose `pause_for` result is `MODEL_UNAVAILABLE`, the row `failed` and `submit_clicked_at` null (read from the store, NF-06), with a real `OllamaBackend` | same | yes | `r = self.ensure_model(load=True)`, then **re-check `should_stop()`**: true → return the role (today's note), pause `APP_CLOSED`, break. Else: `r.ok`, the job not in `self.model_retried` and `self.model_retries < 2` → add the job, `self.model_retries += 1`, `queue_return(…, note="the local AI model restarted")` (C11: exactly these words), log, **continue with no pause**. `r.ok` otherwise (the same role again, or the third such ending in this worker run, C5) → return the role, pause `MODEL_NOT_ANSWERING`. Not ready → return the role, the mapped pause with `detail`. The role is returned in every case (RETURNS_ITEM). |
| **Inbox Auto-apply click** `POST /api/apply`, and **Resume** | through the worker only | | The route lifts a model pause (§4.4) and kicks; it never calls the model or waits. The worker's first act is the pre-take call above. When a search run holds the slot, that run brings the model up for its judge step, and the worker does when it starts. |
| `apply <ids>` (`cmd_apply`), `tailor` (`cmd_tailor`), `profile` (`cmd_profile`, before ingest; `_plan_applicant` needs the model every time), `titles suggest` (`cli.py`) | yes (`_ensure_model(cfg, store, args)` helper in cli) | no (the first call loads it) | One log line, then the command goes on as today and reports its own failure. |
| Search run: decide step (`pipeline.py`) | only when postings are waiting, through a new `pipeline.run(…, model_autostart=False)` kwarg that `cmd_run` sets | no | The existing skip line, with the code's words: "decide: skipped (Ollama isn't installed); N postings wait for a model". |
| Mail sync timer, Local AI card probe, queue tick | **no, report only** | | A background timer never starts Ollama (the owner may have closed it on purpose) and never lifts a pause. |
| `doctor` | no, reports only | | It prints `autostart      on (found: default install location)` or `on, but Ollama isn't installed`, `off (Settings → Local AI)`, `off in this copy (JOBSCRAPER_DB, worktree or test)`. Never a path. |

**Retry bound (C5).** A worker run makes at most **2** automatic retries in total (`self.model_retries`, next to the per-job set `self.model_retried`). Resume or a click starts a new worker with both reset: a deliberate owner action. The `MODEL_NOT_ANSWERING` text may be loose when the server is healthy and the page call fails for a role-specific reason (an HTTP 500, a context overflow); that is harmless, and Resume gives the role one more try.

**Worker state.** `on_state` writes `apply_queue.model` (`starting`/`loading`) and `apply_queue.model_at` through `store.queue_model_state`. A `finally` clears them, and the next worker clears them at its start.

**Worker log lines:**
- `model: starting Ollama`
- `model: Ollama answered after 4 s`
- `model: loading qwen3:14b`
- `model: ready (31 s)`
- `model: <code> <detail>`
- `queue: the local AI model stopped answering; it is ready again, so job=<id> goes again (once)`

## 4. What the owner sees

**4.1 Runs → Auto-apply queue, while the model is starting.** The `GET /api/apply/queue` view gains `model: null | {state, since}` (from `store.queue_model_view()`), shown only while `slot == "apply"`. When `now` is null, the "Now applying" slot shows one row, with no Stop button (no attempt exists yet):
- **"Starting the local AI model…"** with the elapsed time;
- then **"Loading the model…"** with the line "The first load can take a minute."

Pause still works: `queue_take` refuses while paused, so a Pause pressed during the wait is honoured and nothing is taken. Closing the app works too (§3, the stop re-check). When the model is ready, the role is taken as usual. No banner appears and no Resume is needed.

**4.2 Pauses (text / hint, as written into `contracts.py`).** A model pause appears only when the app tried and could not, or may not try. Every hint ends with what to do, and the queue waits for that click. None promises that the queue goes on without one.
- `model_not_installed`: "JobScraper couldn't find Ollama on this computer, so the queue is paused. Nothing was sent." / "Install Ollama from ollama.com and download the model with “ollama pull {detail}”, then resume. If Ollama is installed somewhere else, set budget.ollama_path in config.yaml."
- `model_start_failed`: "JobScraper tried to start Ollama, but it didn't start ({detail}). The queue is paused. Nothing was sent." / "Open Ollama from the Start menu, then resume." The detail is "no answer after 60 seconds" or "the program wouldn't start".
- `model_missing`: "The AI model {detail} isn't downloaded, so the queue is paused. Nothing was sent." / "Download it in a terminal with “ollama pull {detail}” (several GB), then resume." For example: “ollama pull qwen3:14b”.
- `model_port_taken`: "Another program is using port {detail}, where Ollama should run, so the queue is paused. Nothing was sent." / "Close that program, then resume. If Ollama runs at another address, set budget.ollama_url in config.yaml."
- `model_load_failed`: "Ollama is running but couldn't load the model {detail}, so the queue is paused. Nothing was sent." / "Another program may be using the graphics card. Close it, then resume. Your roles keep their place in the queue."
- `model_not_answering`: "The local AI model is running but not answering in time, so the queue is paused. Nothing was sent." / "Another program may be using the graphics card. Close it or let it finish, then resume. Your roles keep their place in the queue."
- `model_unavailable` (changed): "The local AI model isn't running, so the queue is paused. Nothing was sent." / "Start Ollama, then resume. To have JobScraper start it for you, turn on “Start the local AI model when it is needed” in Settings → Accounts → Local AI." This pause is now stored only when nothing listens and JobScraper didn't try: the switch is off, the URL is not on this computer, `budget.enable_llm` is off, or this is a copy where autostart is off.
- Applications row, `ReasonCode.MODEL_UNAVAILABLE` hint (changed): "Try again. If the local AI model still can't start, the Auto-apply queue in Runs says why."

"then resume" matches the other queue hints ("…, then resume."). A new Auto-apply click also lifts a model pause (§4.4); the copy names only Resume, so each hint has one action.

`_pause_copy` (`routers/apply.py`) and the worker's `pause()` log line format the **hint** with `{detail}` too, inside the same try/except (W1 and E2 both; W1 lands before or with E2, never E2 alone).

**4.3 Retry.** The automatic retry (§3, row 3) shows only as the Up-next note "Back at the front: the local AI model restarted" (the panel prints `Back at the front: {{ item.note }}`, and the stored note is exactly "the local AI model restarted").

**4.4 Lifting a model pause: owner clicks only (R1).** There is no timed resume. Two clicks lift a model pause; nothing else does.
- **Resume** (`POST /api/apply/queue/resume`) lifts any pause, as today.
- **A new Inbox Auto-apply click** (`POST /api/apply`) lifts the stored pause **only** when its reason is in `MODEL_CLICK_RESUME` (all seven model pauses), the runner is enabled and its restart gate is open. In `enqueue`, after the queue rows are committed and before the kick, `start_apply` (only it: a keyword `lift_model_pause=True`; `POST /api/questions/retry` keeps today's behaviour) calls `store.queue_resume_if({r.value for r in MODEL_CLICK_RESUME}, now, keep_window=MODEL_PAUSE_VALUES)`. A pause for any other reason (owner, cancelled, bot checks, restarted, …) is never lifted by a click; Resume only, unchanged.

**Both clicks run the start-and-wait service before anything is taken.** The route clears the pause and kicks; the worker's first act is the pre-take ensure (§3 row 1), which starts and loads the model. Ready → the worker takes the head and carries on. Not ready → the worker stores the precise pause again (§4.2) and nothing was taken. While it works, the banner gives way to "Starting the local AI model…" (§4.1). Why the route does not wait itself: a request cannot hold for up to 6.5 minutes, only the process that uses the model starts it (§1.2), and a Pause pressed during the wait must win (it does: the stored pause is empty, so the owner's Pause is written and `queue_take` refuses). If the worker cannot start at once (a search run holds the slot), the unpaused queue waits for the slot as every queued role does today (D-205); the worker still ensures the model before its first take.

A click lifts the queue as it stands: every role clicked in this app session goes on, not only the new one. Roles from an earlier session never do: **across a restart D-200 holds.** The start-up hook calls `queue_pause_if_waiting(RESTARTED, now, replace=MODEL_PAUSE_VALUES)`, which turns a stored model pause with waiting roles into `restarted`; a click never lifts `restarted`. A stored model pause with no waiting roles stays; the next click then lifts it and only the new role goes.

**The streak survives (R1, review C2.1).** `resumed_at` starts the streak window (`window_start`, `apply_flow.py:2055`): it exists so that endings the owner has acknowledged with Resume (bot checks, repeated errors) stop counting. A model pause acknowledges nothing about bot checks, so **lifting a model pause never writes `resumed_at`, whichever click lifts it**. One store path serves both routes: `queue_resume_if(reasons, now, *, keep_window)` clears the three pause keys in one `BEGIN IMMEDIATE` compare-and-clear and stamps `resumed_at` only when the cleared reason is not in `keep_window`.
- Resume calls `queue_resume_if(None, now, keep_window=MODEL_PAUSE_VALUES)`: a non-model pause is cleared and stamped exactly as today; a model pause is cleared and the window kept.
- The Auto-apply click calls it with `reasons` = the click set, as above.
- `queue_resume(now)` stays as it is (other callers, existing pins).
- Effect: a pre-take model pause after one bot-check ending, then a lift, then a second bot-check ending → `bot_checks` pause, as if no model pause had happened. Keeping the window only ever pauses sooner, never later: no new loop.

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
  - `autostart_here` is `autostart_allowed_here(db_path=<the app's DB>, config_given=<the app's>)`.
  - No path goes to the browser.
- **Card state (C9).** In `_model_item`, when `facts.autostart` and `facts.installed` and `autostart_here` hold and the code is `unreachable`, the state is **neutral** (no attention count, no shell badge or banner) unless a pause in `MODEL_PAUSES` is stored; then it is `attention` with that pause's text. A recovered `model_unavailable` attempt (a later `submitted`/`ready_to_submit` attempt for the same job, or any later attempt that passed warm-up) no longer counts for `need_reason` rule (c).
- **Card line (code `unreachable`):**
  - autostart on and installed: "Ollama isn't running. JobScraper starts it when a task needs it." (neutral);
  - not installed: "Ollama isn't installed. Install it from ollama.com to use the local AI.";
  - autostart off: today's copy.
- **`ResumeRefresh.vue:157`:** "Couldn't compare with your application details: the local AI model couldn't start. See Settings → Accounts → Local AI."

## 5. Contract, config and store deltas (all additive; no schema change)

- **Contract (WP-0, done here; no version bump):**
  - `QueuePause` gains `MODEL_NOT_INSTALLED`, `MODEL_START_FAILED`, `MODEL_MISSING`, `MODEL_PORT_TAKEN`, `MODEL_LOAD_FAILED` and `MODEL_NOT_ANSWERING`, with the §4.2 texts.
  - `RETURNS_ITEM` gains the six.
  - New: `MODEL_PAUSES` (the seven model pauses), `MODEL_PAUSE_VALUES` (their plain `.value` strings, for `store.py`, which takes strings), `MODEL_CLICK_RESUME` (the pauses a new Auto-apply click may lift: all of `MODEL_PAUSES`), `MODEL_PAUSE_BY_CODE` (every non-ready `ModelReady.code` except `cancelled`).
  - Removed before it ever reached `personal`: rev 1's `MODEL_AUTO_RESUME` (no timed resume, R1). Relative to `personal` the change is purely additive.
  - Reworded: the two `MODEL_UNAVAILABLE` hints, plus the pause text "isn't answering" → "isn't running".
- **Config (`config/config.yaml`, WP-E2):** `budget.ollama_autostart: true`, and a commented `# ollama_path:` with a note: "only a file named ollama.exe; config.yaml only".
- **Store (`store.py`, WP-E1; settings rows, no SQL outside store; all new code in one block after `queue_pause_state`):**
  - `queue_model_state(state: str | None, now)` commits; None deletes both keys.
  - `queue_model_view() -> {state, since} | None`.
  - `queue_resume_if(reasons: Collection[str] | None, now, *, keep_window: Collection[str] = ()) -> str | None`: in one `BEGIN IMMEDIATE`, read the stored reason; none stored, or `reasons` given and the reason not in it → commit, return None. Else delete the three pause keys, write `resumed_at = now` **only if the reason is not in `keep_window`**, commit, return the cleared reason.
  - `queue_pause_if_waiting(reason, now, *, replace: Collection[str] = ())`: as today, but a stored pause whose reason is in `replace` is overwritten (roles must be waiting).
  - `queue_resume(now)` and `queue_pause(…)` are unchanged.

## 6. Safety rules

1. **Local URLs only.** Only `_target_is_local` targets are started: 127.0.0.1, localhost or ::1 (literal, never resolved), an explicit port, and no `-cloud`/`:cloud` tag. Anything else → `not_running`.
2. **Fixed argv.** It is exactly `[exe, "serve"]` with `shell=False`. The env adds only `OLLAMA_HOST`. `exe` must pass the §2 name and file checks.
   - `budget.ollama_path` is read from config.yaml **only**. No route writes it. Neither `with_settings` nor `autostart_switch` reads a settings-table `budget.ollama_path`; a pin checks that a stored row for it is ignored.
   - The web can change only the boolean switch.
3. **Nothing is downloaded.** A missing model is reported with its pull command and never pulled.
4. **No admin, hidden.** A plain CreateProcess as the current user: no `runas`, no service, no window.
5. **Never kills, never restarts a live server.** A start happens only on a three-try `refused`. A slow, busy or foreign listener is never touched.
6. **Own data only; tests and dev copies never start a real Ollama (C4, R3).** `autostart_allowed_here(*, db_path, env, config_given, source_dir)`:
   - `JOBSCRAPER_OLLAMA_AUTOSTART=0` → off. `=1` → allowed: the explicit override for one command line (the manual check, §9). No code and no test ever sets `1`.
   - Unset → allowed **only** when all hold: `db_path` resolves to the checkout's own `data/jobscraper.db` (both paths resolved; any other path, every `JOBSCRAPER_DB` copy and every tmp DB in a test is off); `JOBSCRAPER_CONFIG` is unset and no `--config` was given (`config_given`); `running_from_worktree(source_dir)` is false.

   Guards on top, so no single line is the only defence:
   - (a) `tests/run_tests.py` **assigns** `os.environ["JOBSCRAPER_OLLAMA_AUTOSTART"] = "0"` (not `setdefault`) before importing any test, so a `1` left in the shell is overwritten.
   - (b) `_spawn_detached` itself refuses when the variable is `0` or a test runner is loaded (§2).
   - (c) The positive "own data" condition above: a test DB is never the checkout's live DB.
   - (d) The manual check sets the variable only on the one command line, never in the shell.
   - (e) Every library default is off (§1.5); the worker calls the service only with a real `OllamaBackend`; every pin injects `spawn`, `find` and `http`.
7. **No stop is weakened.** The retry is the existing return rule (`failed`, no Submit click, read from the store), applied at most once per role and twice per worker run. Bot checks (and their streak window, §4.4), never-twice, caps and the pre-Submit scan are untouched, and a model check still comes before any take. The stop check is repeated after every model wait.

## 7. Edge cases

- **The tray app is starting at the same moment.** Our ping is `refused`, so we spawn. One of the two servers fails to bind and exits, and the API is up either way (accepted risk A1).
- **A slow first load.** The panel shows "Loading the model…". The pre-take load has no attempt deadline, and the in-attempt `warm_up` is then a no-op on `personal` (on `int/Q-121` it still sends the stable prefix: the model is loaded, the prefix is not; a cost note only).
- **The GPU is busy with another program.** Slow is not dead: `/api/version` still answers within three tries, so the server is never restarted. A timed-out page call gets one retry, then `model_not_answering`.
- **The owner closes Ollama mid-attempt.** The page call is refused, the attempt fails with no click, the server is started again and the role goes once more. A second close pauses. After the Submit click no retry is possible (NF-06).
- **The owner closes JobScraper during the model wait.** `should_stop` turns true; the service returns `cancelled`; the worker pauses `app_closed` and takes nothing. Ollama keeps running.
- **Two JobScraper processes start it at once.** The per-port lock: the second waits and never spawns. A lock left by a killed creator is stale at once (PID rule), so the next worker spawns at once instead of reporting a false `start_failed`.
- **A non-default port or `[::1]`.** `OLLAMA_HOST` comes from the URL (`[::1]:<port>` for IPv6), the lock name carries the port, and `port_taken` names it. A URL with no port is not started.
- **A start fails, the owner fixes it, then clicks Auto-apply on another role.** The click lifts the model pause; the worker ensures; the queue goes on. If it still fails, the precise pause is back and nothing was sent.

## 8. Work packages (disjoint files), lanes and order

| WP | Lane (agent) | Files (nobody else writes them) | After | May run with | Verify |
|---|---|---|---|---|---|
| WP-0 | architect | `src/jobscraper/apply/contracts.py` (done, rev 2) | | | `python tests/run_tests.py -k apply_contracts` (72/72 after T0) |
| WP-T0 | tester | `tests/run_tests.py` (the assigned guard line), `tests/test_apply_contracts_v5.py` (C6 retarget: `assert "Runs" in rt.hint and "Try again" in rt.hint`; keep the other two assertions) | WP-0 | E1 | `python tests/run_tests.py -k apply_contracts` |
| WP-E1 | engineer A | `src/jobscraper/backends.py`, `src/jobscraper/store.py` | WP-0; T0 merged before E1 | T0 | `-k backends`, `-k store`, `-k layering`, `-k apply_contracts` |
| WP-W1 | engineer B (web) | `src/jobscraper/web/applyqueue.py`, `src/jobscraper/web/routers/apply.py`, `src/jobscraper/web/connections.py`, `src/jobscraper/web/routers/connections.py` | E1 | E2, U1 | `-k web_apply`, `-k connections`, `-k apply_queue`, `-k layering`, `-k apply_contracts` |
| WP-E2 | engineer A or C | `src/jobscraper/apply_flow.py`, `src/jobscraper/cli.py`, `src/jobscraper/pipeline.py`, `config/config.yaml` | E1 | W1, U1 | `-k apply_flow` and `-k apply_e2e` (each run separately), `-k apply_queue`, `-k pipeline`, `-k cli`, `-k apply_contracts` |
| WP-U1 | frontend | `web/src/components/ApplyQueuePanel.vue`, `web/src/connections.js`, `web/src/components/ConnectionsHub.vue`, `web/src/connections_api.js`, `web/src/components/ResumeRefresh.vue` | E1 (the API shapes are fixed in §4) | W1, E2 | `cd web; npx vitest run` |
| WP-T | tester | `tests/test_q126_*.py` (new), `web/tests/connections.test.js`, `web/tests/q44-refresh.test.js` (retargets) | each lane, as it lands | all | the lane's Verify plus `-k q126` |

**Order.** WP-0 + T0 → E1 → then **W1, E2 and U1 in parallel** (three engineer lanes, the maximum; with the tester that is four agents) → merge **W1 before or with E2, never E2 alone** (E2 writes hints with `{detail}`, W1 formats them) → U1 after W1 → one bundle build in the main checkout after the merge. Every lane runs `-k apply_contracts` and may not merge on a red pin. The full suite runs on the integration tree before the merge into `personal`, plus separate `-k apply_e2e` and `-k apply_flow` runs (the full suite skips Edge tests silently).

## 9. Pins (fakes only; no test starts a process) and the manual check

**Seams:** `spawn`, `find`, `http` (a fake client that records every URL), `pid_alive`, `should_stop`, `clock`/`sleep` (fake time), `lock_dir` (tmp); `run_queue(model_ensurer=…, model_autostart=…)`; a fake `ModelHealth` and a fake runner for the tick and the routes.

**Pins:**
- **T1** Already running → `ready`, no spawn.
- **T2** Three `refused` → one spawn `[exe, "serve"]` with `OLLAMA_HOST=127.0.0.1:<port>`; ready on a later ping; states `starting`; the lock holds the creator's PID and is gone afterwards.
- **T3** No exe → `not_installed`. A configured `ollama.bat`, `cmd.exe` or `ollama app.exe`, or a relative path → `not_installed`, no spawn, no fall-through. **T3b** A planted `ollama.exe` in the cwd, one in the checkout, and a relative PATH entry are all ignored; a default install location wins over PATH; `shutil.which` is never called (patched to raise).
- **T4** autostart off, a remote URL or a cloud tag → `not_running`, no spawn. **T4b** `http://[::1]:11434` → `OLLAMA_HOST=[::1]:11434`; a URL with no port → `not_running`.
- **T5** spawn `OSError` / no answer within 60 fake seconds → `start_failed` with each detail.
- **T6** Three `other` → `port_taken`; three `timeout` → `not_answering`; a mix → `not_answering`; `refused, refused, ollama` → ready; none spawns. **T6b** During the start wait, `other` and `timeout` continue the poll; at the deadline the last answer decides (`refused` → `start_failed`, `other` → `port_taken`, `timeout` → `not_answering`).
- **T7** Tag absent → `model_missing`; no `/api/pull` is ever requested.
- **T8** Load fails → `load_failed`; `warm` receives `timeout ≤ 330` **by keyword**.
- **T9** A fresh lock whose PID is alive → no spawn, wait, then ready; a lock older than 90 s → one spawn; two threads at once → exactly one spawn. **T9b** A fresh lock whose PID is dead → one spawn immediately (no 60 s wait, no `start_failed`). **T9c** The lock vanishes during the wait while the port still refuses → the waiter spawns once.
- **T10** `reset_probe` makes a failed backend available.
- **T11** Worker, each code → the mapped pause, no attempt row, the role still first, the model state cleared; `ready` → the take proceeds; P6 still passes.
- **T11b** `should_stop` turns true during the ensure (fake clock) → the service returns `cancelled`, no `queue_take`, pause `app_closed`. **T11c** `should_stop` turns true right after a `ready` precheck → no `queue_take`, pause `app_closed`.
- **T12** Retry: the first `failed/model_unavailable` → returned with the note exactly "the local AI model restarted", no pause, a second attempt runs; the same role's second failure → `model_not_answering`, returned; a row with `submit_clicked_at` → never retried. **T12b** Retry cap: three roles in one worker run each end `failed/model_unavailable` once → two retries, the third pauses `model_not_answering` with no retry. **T12c** `should_stop` true after the post-item ensure → the role is returned, pause `app_closed`, no further take.
- **T13** **No timer lifts a pause:** a stored model pause (each of the seven), an ok `ModelHealth`, many ticks → still paused, no worker started, `resumed_at` unchanged.
- **T13b** **An Auto-apply click lifts only a model pause:** each of the seven model reasons → cleared and kicked; `owner`, `cancelled`, `bot_checks`, `repeated_errors`, `restarted`, `app_closed`, `daily_limit` → still paused, the role queued. Runner disabled or gate closed → no lift. `POST /api/questions/retry` → no lift.
- **T13c** Lifting a model pause by the click or by Resume leaves `resumed_at` unchanged; Resume on a non-model pause stamps it (unchanged behaviour). A bot-check ending, a pre-take model pause, a lift and a second bot-check ending → `bot_checks`.
- **T13d** Compare-and-clear: the stored reason changed to `owner` between the click's read and its clear → not cleared.
- **T13e** After a click lift, the worker's pre-take ensure fails → the precise pause is stored again and nothing is taken.
- **T13f** No text or hint of a pause in `MODEL_PAUSES` contains "by itself" or "continues" (no model copy promises a resume without a click). Every one of those hints contains "resume".
- **T14** At start-up a stored model pause plus waiting roles → `restarted`; a stored model pause with no roles → unchanged; a click after the restart never lifts `restarted`.
- **T15** `autostart_allowed_here`: env `0`/`1`/unset combined with a `JOBSCRAPER_DB` copy, `JOBSCRAPER_CONFIG`, `config_given` and a worktree. `budget.ollama_path` in the settings table is ignored. **T15b** Unset with a tmp DB → False; unset with `db_path` equal to a fake checkout's `data/jobscraper.db` (tmp layout, `source_dir` given) → True.
- **T15c** `_spawn_detached` raises `OSError` (so `start_failed`) when the variable is `0`, and when a test runner module is loaded, even with `autostart=True`; inside the suite `os.environ["JOBSCRAPER_OLLAMA_AUTOSTART"] == "0"` holds although a `1` was set before `run_tests.py` started (the runner assigns).
- **T16** The PUT route accepts only a bool. The GET connections body holds no path (no `\` or `:/` in the facts).
- **T17** Layering passes.
- **T18** pipeline: the service is called only when postings wait.
- **T19** Card state: `unreachable` + autostart on + installed + here + no model pause → neutral, no attention count; with a stored model pause → attention with its text; a recovered `model_unavailable` attempt does not count.
- **T20** `_pause_copy` and the worker's `pause()` log format `{detail}` in the hint; no raw braces reach the owner.
- **T21** The retargeted v5 pin (C6) and the two vitest retargets.
- **Vitest:** the two panel states, the card lines and neutral state, the switch row saving and reverting.

**Manual check (Coordinator, at the end, on the integration tree, real machine, DRY RUN, DB copy; ask the other live sessions first, because Ollama on 11434 is shared). Never port 8765, never the live DB, never a real job id:**
0. `curl http://127.0.0.1:11434/api/ps` shows no model loaded by another session. Quitting the tray app drops the shared GPU tools.
1. Quit Ollama (tray → Quit). `curl http://127.0.0.1:11434/api/version` must be refused.
2. Copy `data/jobscraper.db`. In the copy, through `Store`:
   - **`queue_clear()` first.** The copy holds the owner's real waiting roles, and a worker on the copy would take them.
   - `queue_resume`, then `set_setting("apply.mode","dry_run")`.
   - `queue_add("q126-phantom", None, "dry_run", "inbox", now)`, then `commit()`.
   - That job id has no applications row, so `queue_take` drops it **after** the pre-take check and no browser opens.
   - Before step 3, check that `queue_items()` lists only the phantom.
3. On one command line (never `$env:` in the shell): `JOBSCRAPER_DB=<copy> JOBSCRAPER_OLLAMA_AUTOSTART=1 python -m jobscraper apply queue --dry-run`.
   - Expect `model: starting Ollama` … `model: ready (…)`, then `queue: job=q126-phantom no longer To apply; skipped`, exit 0.
   - The API now answers, and `ollama.exe` runs with no console window.
4. Run step 3 again (re-add the phantom first): no new process, `ready` within 1 s.
5. Close the terminal used in step 3; the API still answers.
6. In the copy, `set_setting("budget.ollama_autostart","false")` and quit Ollama. Step 3 now gives the pause `model_unavailable` with the new text and hint.
7. Optional: a dev web instance on the copy (port 8768, `JOBSCRAPER_MAIL_SYNC=0`, `JOBSCRAPER_APPLY_QUEUE=1`, `JOBSCRAPER_OLLAMA_AUTOSTART=1` on its command line, `apply.mode` `dry_run` in the copy, its queue cleared, the phantom added, `budget.ollama_autostart` back to `true`, a stored model pause). Press **Resume**, then cancel the running worker job (the job's Cancel, which runs `taskkill /T /F`; the queue's Stop button is absent while no attempt exists) during "Starting the local AI model…", and confirm `ollama.exe` survives. Wait several minutes with Ollama answering and a new model pause stored: the banner stays (no timed resume). Stop the instance by PID.
8. Set `budget.ollama_path` to a non-existent file in a copy of config via `JOBSCRAPER_CONFIG` (with `JOBSCRAPER_OLLAMA_AUTOSTART=1` on the line) and confirm the `not_installed` pause text.

## 10. Merge note for `int/Q-121` (R5)

Q-126 ships on `personal` first. Then `personal` is merged into `int/Q-121`. Each lane shapes its edit so that merge is additive:

| Shared spot | `int/Q-121` has | Q-126 lane rule |
|---|---|---|
| `backends.warm` (`Backend.warm`, `OllamaBackend.warm`, module `warm()`) | `warm(keep_alive=None, messages=None)`, plus `PromptRefused`, `forbid`, `_guard` | E1 adds `*, timeout=None` **keyword-only** after the existing parameters and calls it only by keyword. The merged signature is `warm(keep_alive=None, messages=None, *, timeout=None)`. All new functions (`ModelReady`, `ensure_model_running`, `find_ollama`, `_spawn_detached`, `autostart_*`, `running_from_worktree`) go in **one new block at the end of the module**; `reset_probe` is a new method placed right after `available`. No reformatting of existing lines. |
| `apply_flow.py` `run_queue` pre-take block (`:1986-1994`) and post-item block (`:2020-2032`), `precheck` | `pause_for` consent/streak lines (not the model branch) | E2 puts the logic in two **new** `_Run` methods (`ensure_model`, `model_retry`) and inserts only one-line calls plus the `should_stop` re-check into `run_queue` and `precheck`. `pause_for` is not touched. New `_Run` fields are added at the end of `__init__`. The module `run_queue(...)` gains keyword arguments at the end of its signature. |
| `store.py` queue pause/resume | schema v8 elsewhere | E1 adds `queue_resume_if`, `queue_model_state`, `queue_model_view` as one block after `queue_pause_state`; `queue_pause_if_waiting` gains only the keyword `replace`; `queue_resume` and `queue_pause` are unchanged. No schema change. |
| `cli.py` `apply queue` and `cmd_doctor` | `cmd_doctor` +167 lines | E2 adds a helper `_doctor_autostart_line(cfg)` and `_ensure_model(cfg, store, args)` as new functions; `cmd_doctor` gets one call line at the end of its model section; the `apply queue` handler passes `model_autostart`, `pid_alive` and its existing stop check as new keyword arguments. |
| `web/routers/apply.py` `queue_view`, `enqueue`, `resume_queue`, `_pause_copy` | `queue_view` region (`:332-342`) | W1 computes the model state in a new helper `_model_view(store, slot)` and adds one `"model"` key to the returned dict; the click lift is a new helper `_lift_model_pause(store, runner)` called with one line in `enqueue`; `resume_queue` swaps one line (`queue_resume` → `queue_resume_if(None, …)`); `_pause_copy` changes only its hint line. |
| `apply/contracts.py` version comment, `REASON_TEXTS[MODEL_UNAVAILABLE]` | `CONTRACT_VERSION = 8`, a hunk at `:226-262` | WP-0 is done: the Q-126 comment block says "no version bump"; at the merge keep 8 and both comment blocks. |
| `config/config.yaml` | possibly new `apply.*` keys | E2 adds only `budget.ollama_autostart` and the commented `ollama_path` under `budget:`. |

## 11. Accepted risks and follow-ups (R7)

- **A1.** The tray app starting at the same moment gives two servers racing for the port; one exits and the API is up either way. The headless server has no tray icon: Task Manager (`ollama.exe`) or sign-out ends it.
- **A2.** A scheduled search run, or a CLI task, may start Ollama and load the model while the owner closed it on purpose. It is idle after keep-alive, never killed, and the Settings switch text discloses it.
- **A3.** A user-writable folder on PATH that holds a file named `ollama.exe` is trusted after the default locations (a planted file there already means code execution as the owner). The cwd and the checkout are never searched.
- **A4.** `OLLAMA_MODELS` and other env changed after JobScraper started are stale in the spawned server, which may then report `model_missing`. Restarting JobScraper fixes it.
- **A5.** `PUT /api/connections/model/autostart` has no CSRF token; the app has none anywhere, and the only effect is a boolean that lets the installed program start.
- **A6.** The `model_unavailable` hint's switch advice is wrong when the cause is a remote URL or the AI switched off in config.
- **A7.** A click that lifts a model pause lets every role clicked in this app session go on, not only the new one. They were all clicked by the owner in this session, and "Nothing was sent" held for each.
- **A8.** A PID reused within 90 s by another process makes a dead creator's lock look alive; the waiter then waits 60 s and may report `start_failed`. Rare; the next click retries.
- **Follow-up F1 (id from the Coordinator; not part of this build).** The tailor's silent fall-back to the original resume inside an attempt (`apply_flow.py:856-873`): a tailor transport failure should end the attempt `model_unavailable` instead, so the §3 retry covers it. Today it is truthful only through the audit row (`resume_source = original`).

## 12. Review fold (C1-C14) and rulings (R1-R7)

| Item | Where | How |
|---|---|---|
| C1 stop after a long wait | §2 `should_stop`, §3 rows 2-3, T11b/c, T12c | As written, extended by R2 (the re-check follows both the pre-take and the post-item ensure). |
| C2 timer auto-resume | §1.6, §4.4, §5, T13-T13f | **Changed by R1:** the review's simpler alternative, sharpened. No timer lift at all; a model pause lifts only on Resume or a new Auto-apply click; the streak window survives a model lift (`keep_window`); hints say "then resume". |
| C3 `find_ollama` | §2, T3b | As written: no `shutil.which`, default locations before PATH, cwd and checkout excluded, resolved candidates, skip vs fatal. |
| C4 test guard | §6 rule 6, T15b/c, WP-T0 | As written (assign, spawn refuses, positive own-DB condition, one-line override). |
| C5 retry cap | §3, T12b | As written: 2 per worker run. |
| C6 stale pin | WP-T0, T21 | As written; the hint text stays. |
| C7 ping rules | §2 algorithm and step 4, T6/T6b | As written; mixes are specified. |
| C8 lock PID | §2 step 3, T9b/c | Changed: the lock holds the PID only; `pid_alive` is injected (cli passes `web.jobs.pid_alive`). `process_identity` is left out to keep the seam small; PID reuse is accepted risk A8. |
| C9 card state | §4.5, T19 | As written. |
| C10 diagnosis | §0 | As written. |
| C11 note text | §3, §4.3, T12 | As written. |
| C12 `[::1]`, no port | §2 steps 2-3, T4b | As written. |
| C13 merge order | header, §8, §10 | **Changed by R5:** Q-126 on `personal` first; `personal` then merges into `int/Q-121`; keyword-only `timeout`; §10 shapes every shared edit. |
| C14 manual check | §9 steps 0, 7, 8 | As written, step 7 extended to show that no timer lifts a pause. |
| R1 / R2 / R3 / R4 / R5 / R6 / R7 | §4.4 / §3 / §2, §6 / §0, §4.3, §2, §9 / §10 / ADR-0013 / §11 | All binding; recorded as D-217. |

**Requirement map:**

| Requirement | Where |
|---|---|
| D-214 automatic start | §2, §3 |
| No manual step when the start works | §3 rows 1 and 3, §4.1 |
| A precise single pause, only after trying | §4.2 |
| No submission without a fresh click (D-200, R1) | §1.6, §4.4 |
| D-200 restart rule | §4.4 (start-up `replace`) |
| NF-06 never twice | §3 row 3, §6 rule 7 |
| NF-04 layering | §1.1, §6 rule 6, §10 |
| D-205 queue unchanged otherwise | §3, §4.4 |
| ADR | `adr/0013-app-starts-local-model.md` |
