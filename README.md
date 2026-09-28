# JobScraper

Watches the careers pages of the companies you care about, keeps only the
new-graduate software roles **based in Singapore** that fit your resume, and puts
them on one web page where you open them, apply, and track what happened next.

It is cheap by construction: free local rules throw away ~99% of postings before
a model ever sees one, and the survivors go to **Qwen3, an open model running on
your own GPU through [Ollama](https://ollama.com)**, in batches, as short extracts
rather than whole job descriptions. The same model reads your resume. No API key,
no login, no per-token bill.

Design and decisions: [`docs/DESIGN.md`](docs/DESIGN.md). Full specification and
build ledger: [`.claude/prds/jobscraper-v2.prd.md`](.claude/prds/jobscraper-v2.prd.md).

---

## Quick start (Windows, no Docker)

Needs Python 3.12 and, for the model steps, [Ollama](https://ollama.com) with
`ollama pull qwen3:14b` (9.3 GB; `qwen3:8b` on a smaller GPU). No API key.
(v1 is kept at the `v1-final` tag.)

```powershell
git clone https://github.com/Benjamin-Fernandez/jobscraper.git
cd jobscraper
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH = "src"

python -m jobscraper doctor      # checks config, watchlist, profile, model transport
python -m jobscraper web         # the web app: http://127.0.0.1:8765
```

Node is **not** needed to run it: the built web app is committed under
`src/jobscraper/web/static/`. (Node is only for changing the UI — see
[`web/README.md`](web/README.md).)

### First real run

1. Put your resume at **`data/resume.pdf`** (or `data/resume.docx`). It never
   leaves your machine and is git-ignored.
2. Build your profile from it — one Qwen call:
   ```powershell
   python -m jobscraper profile --refresh
   python -m jobscraper profile --show     # skills, target job titles, version
   ```
   Correct anything it got wrong in `config/profile.overrides.yaml`; that file is
   never regenerated.
3. Run a batch:
   ```powershell
   python -m jobscraper run            # the most-overdue companies
   ```
   or `.\run.ps1`, which runs a batch and then opens the web app.

## Docker

```bash
docker compose up -d --build          # web app on http://127.0.0.1:8765
docker compose run --rm app run       # one batch; any command works: doctor, status, ...
docker compose down                   # stop; the jobscraper_data volume keeps the database
```

In Docker the judge is a **local Qwen3 model served by Ollama** on your NVIDIA
GPU — no API key and no login inside the container:

```bash
docker compose --profile llm up -d --build            # app + the ollama service
docker compose exec ollama ollama pull qwen3:14b      # once: 9.3 GB into a volume
docker compose run --rm app doctor                    # judge: ollama (qwen3:14b ...) OK
```

Without `--profile llm` the app still runs; the model step is skipped and
survivors wait until a model is reachable. Details and the security notes are in `docker-compose.yml`.

Outside Docker the app talks to Ollama on `127.0.0.1:11434` (`budget.ollama_url`).

---

## How a run works

```
watchlist.yaml -> who is due? -> scrape -> free prefilter -> ~800-char extract
               -> Qwen (fit, location, years) -> code decides -> data/shortlist.json -> web app
```

- **Scheduling.** Every company is re-checked once a week (`run.cycle_days: 7`).
  Each run takes the companies that have gone longest without a check
  (never-checked first), so "loop back to the first company" is automatic. At
  295 companies and 10 per run a full sweep needs about 4.2 runs a day (set the
  batch size in the web app's Settings tab); `python -m jobscraper status` shows whether you
  are keeping up and when the queue drains.
- **Prefilter (free).** Rules in `config/rules.yaml`: drop senior/staff/lead/
  intern/non-engineering titles, keep only titles matching your resume's target
  roles, drop any location that is not explicitly Singapore (every `Remote`
  included), drop anything asking for more than 3 years, drop postings with too
  little skill overlap. A blank or vague location ("APAC", "Hybrid") is not
  guessed at — it goes to the model, which reads the description.
- **Decide (the only model step).** Qwen reports facts per posting — does it fit
  your interests, is it in Singapore, how many years it asks for — and code decides.
  Two things are enforced in code whatever it says: a role is accepted only if
  it is confirmed Singapore, and never if it asks for more than 3 years.
  A posting is never judged twice unless its description changes.
- **Shortlist.** `data/shortlist.json` is regenerated every run; your
  application status lives in the database, never in that file.

## Commands

| Command | What it does |
|---|---|
| `run [--dry-run] [--batch-size N]` | One batch. `--dry-run` fetches and reports but writes nothing and consumes nothing. |
| `status` | Due now, due this week, never checked, quarantined, run rate vs the rate a sweep needs. |
| `web` | The web app: **Inbox** (triage new roles; Not interested kept in its own section), **Applications** (by company, by stage), Runs, Companies, Profile, Settings, Developer (the background job's log). |
| `doctor` | Checks the whole setup, including whether Qwen (Ollama) is reachable. |
| `watchlist list` / `add "Name" URL` / `disable KEY` | Manage companies; edits keep your comments. |
| `profile [--show \| --refresh \| --bump]` | Build or inspect the resume-derived profile. |
| `filter test --title … --location … [--desc …]` | Dry-run the rules on a made-up posting. |
| `filter explain JOB_ID_OR_URL` | Every rule's verdict for a stored posting. |
| `titles [show]` / `titles suggest` | The job titles the title filter searches for; ask Qwen for 5 new ones, never one suggested before (the web app's Profile tab does both). |
| `companies [show]` / `companies search` | Your own list of companies (uploaded on the web app's Companies tab, one per line, most wanted first); find each one's careers site with Qwen and watch the ones found. |
| `reresolve KEY` | Forget a company's cached job-board provider so the next run rediscovers it. |
| `sync` | Reconcile `watchlist.yaml` into the database (every run does this anyway). |
| `purge [--days N] [--compact]` | Delete stored job descriptions older than `retention.description_days` (7) and compact the database; every run does this at its end. Roles in the Inbox or Applications keep theirs. |

Run each as `python -m jobscraper <command>` (with `PYTHONPATH=src`), or through
`.\run.ps1 <command>`.

## Changing what it watches

`config/watchlist.yaml` is the list. The smallest entry is two lines:

```yaml
  - name: Jane Street
    careers_url: https://www.janestreet.com/join-jane-street/open-roles/
```

Rename a company freely — its history is keyed on `key` (a slug of the name by
default), not the display name. Remove an entry and it is disabled, never
deleted, so your applications to it stay. If discovery cannot find a company's
job board, set `provider`, `slug` or `feed_url` on the entry yourself.

## Tuning the filter

Every rule in `config/rules.yaml` has `enabled:` and an `extra:` list you own:

```yaml
  - id: title_allow
    extra: ["trade support engineer"]     # a title your resume did not produce
```

Check a change before it runs for real:

```powershell
python -m jobscraper filter test --title "Trade Support Engineer" --location "Singapore"
```

Editing the rules re-checks every stored posting on the next run, for free.

## Files you own vs files the engine owns

| Yours — edit freely | Engine's — regenerated, safe to delete |
|---|---|
| `config/watchlist.yaml` | `data/shortlist.json` |
| `config/rules.yaml` (the `extra:` lists, `enabled:`) | `data/profile.derived.yaml` |
| `config/profile.overrides.yaml` | `data/jobs/` (web-app run logs) |
| `config/config.yaml` | |
| `data/resume.pdf` | |

`data/jobscraper.db` holds your application history — back it up, do not delete it.

## Configuration

`config/config.yaml` — batch size, the cycle (7 days by default; the web app's
Settings tab changes it), the model (`budget.backend: ollama | off`, Qwen3 via
Ollama), how long job descriptions are kept (`retention.description_days`), web
host/port. Environment overrides:
`JOBSCRAPER_CONFIG`, `JOBSCRAPER_DB`, `JOBSCRAPER_HOST`, `JOBSCRAPER_PORT`.
Keep the host at `127.0.0.1`: the app has no login.

## Development

```powershell
python tests/run_tests.py            # full suite; -k <text> to select
cd web; npm ci; npm test             # UI tests (Vitest)
```

CI runs both on every push and pull request, plus the Docker checks.
`tests/test_layering.py` enforces the module boundaries in `docs/DESIGN.md`.
