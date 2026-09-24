# JobScraper

Watches the careers pages of the companies you care about, keeps only the
new-graduate software roles **based in Singapore** that fit your resume, and puts
them on one web page where you open them, apply, and track what happened next.

It is cheap by construction: free local rules throw away ~99% of postings before
a model ever sees one, and the survivors go to the cheapest Claude model in
batches, as ~300-token extracts rather than whole job descriptions.

Design and decisions: [`docs/DESIGN.md`](docs/DESIGN.md). Full specification and
build ledger: [`.claude/prds/jobscraper-v2.prd.md`](.claude/prds/jobscraper-v2.prd.md).

---

## Quick start (Windows, no Docker)

Needs Python 3.12 and, for the model step, [Claude Code](https://claude.com/claude-code)
signed in on this machine. No API key. (v2 lives on the `v2-rebuild` branch;
`master` still holds the v1 restore point.)

```powershell
git clone -b v2-rebuild https://github.com/Benjamin-Fernandez/jobscraper.git
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
2. Build your profile from it — one cheap model call:
   ```powershell
   python -m jobscraper profile --refresh
   python -m jobscraper profile --show     # skills, target job titles, version
   ```
   Correct anything it got wrong in `config/profile.overrides.yaml`; that file is
   never regenerated.
3. Run a batch:
   ```powershell
   python -m jobscraper run            # the 10 most-overdue companies
   ```
   or `.\run.ps1`, which runs a batch and then opens the web app.

## Docker

```bash
docker compose up -d --build          # web app on http://127.0.0.1:8765
docker compose run --rm app run       # one batch; any command works: doctor, status, ...
docker compose down                   # stop; the jobscraper_data volume keeps the database
```

The image has no `claude` program, so inside Docker the model step is skipped
and survivors wait. Judge them with the in-session review below, or run batches
from the host. Details and the security notes are in `docker-compose.yml`.

---

## How a run works

```
watchlist.yaml -> who is due? -> scrape -> free prefilter -> ~800-char extract
               -> cheap model (accept/reject) -> data/shortlist.json -> web app
```

- **Scheduling.** Every company is re-checked once per 14 days. Each run takes the
  10 companies that have gone longest without a check (never-checked first), so
  "loop back to the first company" is automatic. At 229 companies a full sweep
  needs about 1.6 runs a day; `python -m jobscraper status` shows whether you
  are keeping up and when the queue drains.
- **Prefilter (free).** Rules in `config/rules.yaml`: drop senior/staff/lead/
  intern/non-engineering titles, keep only titles matching your resume's target
  roles, drop any location that is not explicitly Singapore (every `Remote`
  included), drop anything asking for more than 3 years, drop postings with too
  little skill overlap. A blank or vague location ("APAC", "Hybrid") is not
  guessed at — it goes to the model, which reads the description.
- **Decide (the only paid step).** The model answers accept/reject per posting.
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
| `web` | The web app: **Inbox** (open, mark applied, dismiss) and **Applications** (status and history). |
| `doctor` | Checks the whole setup, including which model transport is live. |
| `watchlist list` / `add "Name" URL` / `disable KEY` | Manage companies; edits keep your comments. |
| `profile [--show \| --refresh \| --bump]` | Build or inspect the resume-derived profile. |
| `filter test --title … --location … [--desc …]` | Dry-run the rules on a made-up posting. |
| `filter explain JOB_ID_OR_URL` | Every rule's verdict for a stored posting. |
| `review --export` / `review --apply` | Judge postings in a Claude Code session instead of `claude -p` (below). |
| `reresolve KEY` | Forget a company's cached job-board provider so the next run rediscovers it. |
| `sync` | Reconcile `watchlist.yaml` into the database (every run does this anyway). |

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

## Judging inside a Claude Code session

If `claude -p` is unavailable (Docker, or you would rather watch it think):

```powershell
python -m jobscraper review --export     # writes data/review_queue.json
# ask Claude Code: "judge data/review_queue.json and write data/review_verdicts.json"
python -m jobscraper review --apply
```

It asks exactly what the automatic path asks, and its answers go through the same
Singapore / 3-year checks into the same cache — the two paths are interchangeable.

## Files you own vs files the engine owns

| Yours — edit freely | Engine's — regenerated, safe to delete |
|---|---|
| `config/watchlist.yaml` | `data/shortlist.json` |
| `config/rules.yaml` (the `extra:` lists, `enabled:`) | `data/profile.derived.yaml` |
| `config/profile.overrides.yaml` | `data/review_*.json` |
| `config/config.yaml` | |
| `data/resume.pdf` | |

`data/jobscraper.db` holds your application history — back it up, do not delete it.

## Configuration

`config/config.yaml` — batch size, 14-day cycle, model, the model transport
(`budget.backend: cli | api | off`), web host/port. Environment overrides:
`JOBSCRAPER_CONFIG`, `JOBSCRAPER_DB`, `JOBSCRAPER_HOST`, `JOBSCRAPER_PORT`.
Keep the host at `127.0.0.1`: the app has no login.

## Development

```powershell
python tests/run_tests.py            # full suite; -k <text> to select
cd web; npm ci; npm test             # UI tests (Vitest)
```

CI runs both on every push and pull request, plus the Docker checks.
`tests/test_layering.py` enforces the module boundaries in `docs/DESIGN.md`.
