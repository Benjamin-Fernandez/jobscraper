# JobScraper

Monitors 229 company career sites for new-grad software roles in Singapore that match
your resume, and drops the ones worth applying to into a tracker with clickable links.

Full design rationale: `docs/DESIGN.md`.

---

## Run it

```powershell
cd C:\Users\Admin\Documents\All_Created_Folders\Misc\Projects\JobScraper
.\run.ps1              # process the next 30 companies, then open the viewer
.\run.ps1 view         # just browse matches and tick off applications
.\run.ps1 status       # where am I in the cycle?
.\run.ps1 doctor       # check setup
.\run.ps1 -NoView      # run the batch without opening the viewer
```

Or directly:

```powershell
$env:PYTHONPATH = "src"
python -m jobscraper run
```

## How the batching works

**Each run processes exactly 30 companies, then stops.** The cursor remembers where it
got to:

| When | What runs |
|---|---|
| Monday | companies 1-30 |
| Tuesday | companies 31-60 |
| Tuesday again | companies 61-90 |
| ... | ... |
| after 8 runs | all 229 done - cycle complete |

Once the whole list is done, a **new cycle cannot start until 14 days** have passed
since that cycle's first batch. Run it early and you get told when the next cycle opens:

```
Cycle 1 is complete - all 229 companies checked. The next cycle opens in 86h
(2026-09-28 09:00 UTC). Use --force to start it now.
```

Reaching the 14-day mark part-way through the list does **not** reset the cursor - the
list is finished first, so every company gets checked once per cycle. Resetting on the
clock alone would mean companies near the end of the list were almost never checked.

`--force` starts a new cycle immediately. `--batch-size N` overrides 30 for one run.

## Marking things as applied

A run ends by opening the **viewer** - a small web page served from your own
machine at `http://127.0.0.1:8765`. Every match is a card with an **Applied**
checkbox next to the Apply button.

Tick it and, before the box even finishes turning green, the tracker on disk has
already been updated:

| Where | What gets written |
|---|---|
| `Applications` sheet, `Status` | `Applied` |
| `Applications` sheet, `Date Applied` | today's date |
| `Applied` sheet | a clean log line: date, company, tier, **role name**, score, **application link** |

Un-tick it and both are rolled back. A ticked card goes green-edged and struck
through, so what is left to do is obvious at a glance.

### What it will not overwrite

The tick only ever moves `Status` between blank / `To Apply` and `Applied`. If you
have already moved a row on yourself - `OA`, `Interview`, `Offer`, `Rejected` -
ticking the box leaves that row completely alone, and so does a `Date Applied` you
typed in by hand. `Resume Version`, `Referral`, `Notes` and `Outcome` are never
read or written at any point. This is covered by tests, not just intent.

### Why a server and not just the file

A page opened straight off disk (`file://...`) cannot write to your spreadsheet -
browsers forbid it, and there is no way around that. So the page is served over
loopback instead. It binds `127.0.0.1` only and checks the `Host` header, so
nothing outside this machine can reach it. Open the HTML file directly and the
checkboxes disable themselves with a note rather than pretending to save.

If `application_tracker.xlsx` is open in Excel, Windows holds a write lock and the
tick reports that instead of failing silently - close Excel and tick again.

## What you get

| File | What it is |
|---|---|
| `output/all_matches.html` | **What the viewer serves.** Every match so far, rebuilt from the tracker, with the Applied checkboxes. |
| `output/latest_matches.html` | Only the last run's new matches (`.\run.ps1 view --latest`). |
| `output/application_tracker.xlsx` | The running list. Append-only. |
| `output/run_tracker.xlsx` | `Runs` = one row per run. `Coverage` = one row per company per run, including every failure. |
| `output/needs_review.xlsx` | Companies that were quarantined and need a feed URL pasted in. |

### The application tracker

Columns A-N are written by the program. Columns O-T are **yours**:
`Status, Date Applied, Resume Version, Referral, Notes, Outcome`.

The program writes `Status` and `Date Applied` only when you tick **Applied** in
the viewer, and only in the safe direction described above. It never touches
`Resume Version`, `Referral`, `Notes` or `Outcome`, and never rewrites or reorders
a row you have edited - this is verified behaviour, not an intention. `Status` has a
dropdown matching your existing legend (To Apply / Applied / OA / Interview / Offer /
Rejected). The **Role** and **Apply** cells are both clickable links straight to the
posting. Score >= 70 shades green, 50-69 amber. Backups of the last 5 versions live in
`output/backups/`.

## When a site fails

Failures never stop a run. Each one is classified and the company is skipped:

- `transient` (timeout, 429, 5xx) - retried 3x with backoff inside the run
- `blocked` (403, bot-wall) - not retried
- `gone` (404) - not retried
- `schema` (200 but unparseable, or no job links found) - signals an ATS change

Three consecutive failures triggers **one automatic re-resolution attempt** (most
breakage is a company moving ATS, which this repairs silently). If that fails the
company is **quarantined**: skipped in future runs, listed in `needs_review.xlsx`, and
retried once every 4th run. One success un-quarantines it automatically.

If more than half a batch fails, the run assumes your network is at fault rather than
five sites dying at once: it quarantines nobody, rolls back the failure counters, and
exits marked `aborted_unhealthy`.

## When a careers URL is wrong

Resolving a company to an ATS is a guess: the probe tries likely slugs and keeps
whichever board answers. A slug existing does **not** mean it is yours - anyone can
register `google.recruitee.com`. So a probed board now has to prove it:

- **Aggregators are never scraped.** A `careers_url` pointing at LinkedIn, Indeed,
  Glassdoor and friends yields no slug and is never sniffed. Mathrix's URL was a
  LinkedIn company page, which once resolved it to *LinkedIn's own* Greenhouse
  board and scraped 53 of LinkedIn's postings.
- **The board must agree it is you.** Its self-reported name has to overlap the
  company name; where the ATS exposes no name, the slug itself must look like the
  company name.
- **Demo boards are rejected.** A board whose every posting is titled "Sample",
  "Test Job" or similar is somebody's abandoned trial account.

Anything that fails these falls through to `needs_review.xlsx` rather than being
silently monitored. Fix one with:

```powershell
.
un.ps1 reresolve "Mathrix" --purge        # redo discovery, drop old postings
.
un.ps1 pin "Acme" --url https://...       # point it somewhere by hand
.
un.ps1 pin "Acme" --needs-feed --note "why"
```

Some sites cannot be scraped at all: Google, Meta and Microsoft render their
careers pages entirely in JavaScript and expose no public feed, so they sit in
`needs_review.xlsx` until you supply a URL one of the adapters understands.

## The matching engine

Four stages, each cheaper than the next:

1. **Stage A - rules, free.** Title deny-list (senior/staff/intern/non-engineering),
   Singapore-only location, 5+ years reject. Deliberately conservative: it only rejects
   what is unambiguous. Vague locations (`APAC`, `All Offices`, blank) are *not*
   rejected - they go to stage 3 to be normalized.
2. **Stage B - local scoring, free.** BM25 over the JD against your resume and skill
   list, plus weighted skill overlap, title affinity, tier and category priors. 0-100.
3. **Stage C1 - extraction.** Pulls structured facts (`is_singapore`, `seniority`,
   `yoe_min`, `intake_year`, `sponsorship`, `role_family`, `tech_stack`) into the
   database. These persist and improve every future run.
4. **Stage C2/D - adjudication.** A verdict per posting, Sonnet for T1/T2 companies and
   Haiku for the rest, with a second opinion on borderline high-tier roles. Disagreement
   surfaces as `contested` rather than being silently resolved.

Stages 3-4 need a model. **Without one the pipeline still runs** on rules and local
scoring alone - you just get more noise, because vague-location and vague-title postings
cannot be resolved. Which model, and how it is reached, is the next section.

### Stages 3-4 run through Claude Code - no API key

Judging is a transport question, and `budget.backend` in `config/config.yaml` answers it:

| `backend` | How it judges | Needs |
|---|---|---|
| `cli` *(default)* | Shells out to `claude -p`, the Claude Code CLI | Claude Code signed in |
| `api` | The `anthropic` SDK | `ANTHROPIC_API_KEY` |
| `off` | Nothing - rules and local scoring only | - |

With `cli`, a run judges postings using the Claude Code subscription you are already
signed into. There is no API key and no per-token bill. Check it with:

```powershell
.\run.ps1 doctor        # judge  backend=cli / OK - cli (...\claude.CMD)
```

Each `claude -p` call carries roughly 12k prompt tokens of Claude Code's own overhead on
top of the postings, and takes 5-60s depending on batch size. A 30-company run is
normally 15-20 calls. Raise `extraction_batch` / `verdict_batch` to trade fewer, larger
calls for more; lower them if a call times out.

If the transport fails `max_consecutive_failures` times in a row (logged out, rate
limited), the judge stands down for the rest of that run and local scoring carries the
batch - it does not burn a 300-second timeout per remaining call.

### Judging inside a Claude Code session instead

`review` is the other way round: rather than the program calling Claude Code, you hand
the postings to the session you are already talking to. Useful when you want to read the
reasoning as it happens, or when the CLI is unavailable.

```powershell
python -m jobscraper review --export      # writes output/review_queue.json
#   then, to Claude Code:  "review review_queue.json and write review_verdicts.json"
python -m jobscraper review --apply       # folds the verdicts back in, re-exports
```

The queue holds only postings in the undecided band that nothing has judged yet, best
score first; `--all` widens it to the auto-accepts too, `--limit N` caps it. Verdicts
land in the same cache the automatic backends use, so the two paths never duplicate work.

Nothing is ever judged twice: extraction and verdicts are cached by
`hash(job_id + jd_text + profile_version)`.

## Tuning the matching

Everything lives in `config/profile.yaml` - skills, title patterns, locations, weights,
thresholds. It is meant to be edited by hand.

Because `ambiguous_hints` is the only escape hatch from the Singapore-only filter, a
location string that is not blank, not Singapore, and not listed there is treated as
elsewhere. That default-deny is intentional; without it, `Zug, Switzerland` and
`Aarhus, Denmark` sail straight through.

After editing, bump `profile_version` so cached verdicts are recomputed.

## Commands

| Command | What it does |
|---|---|
| `run` | Process the next 30 companies, then open the viewer |
| `view` | Serve the match page so you can tick off applications |
| `view --latest` | Same, but only the last run's matches |
| `view --port N` | Use a different port (default 8765) |
| `run --force` | Start a new cycle without waiting 14 days |
| `run --dry-run` | Everything except writing the output files |
| `status` | Cursor position, counts, quarantine list |
| `doctor` | Verify workbook, config, deps, judge transport |
| `review --export` | Queue postings for a Claude Code session to judge |
| `review --apply` | Fold `review_verdicts.json` back in and re-export |
| `resolve` | Work out each company's ATS without fetching jobs |
| `reresolve NAME` | Redo ATS discovery for one company (`--purge` drops its old postings) |
| `pin NAME --url U` | Point a company at a feed URL by hand |
| `pin NAME --needs-feed` | Park a company for review with a reason |
| `sync` | Reload the workbook into the database |
| `export` | Rewrite run_tracker and needs_review from the database |

## Layout

```
config/config.yaml     batch size, cycle days, timeouts, budget
config/profile.yaml    the matching spec  <- tune this
data/                  input workbook + SQLite database
output/                trackers, HTML view, backups
src/jobscraper/        the package (serve.py is the local viewer)
docs/DESIGN.md         architecture and rationale
```

SQLite is the source of truth; the spreadsheets are a surface. Deleting
`data/jobscraper.db` resets all history, including which postings you have already seen.
