# Q-121 unlock review A: corpus of 12 made-up Singapore new-grad application forms

Made-up employers only. Each `NN_*.txt` is one form; the probe `../Q-121-unlock-A-probes/run_corpus.py` reads them.

Line format (`|` separated): `key|TYPE|R or O|label|options (; separated)|class|truthful answer|help text`
- `@form name | style | employer | posting title` first line; `@page Title` starts a page (a Workday-style form is several pages, each one `fill_page_always` call).
- `@use macro` expands a block from `_macros.txt` (name, phone, links, school, job entries: the parts every system asks the same way).
- class (what a competent model names): ord, dec:<which>, wr (work right), sp (sponsorship), priv, ret, mkt, cert, ack, sid:<which>, of:<which>, oth (other person).
- answer: the TRUE answer for the sample applicant (`tests/fixtures/apply/applicant.sample.yaml`: a Singapore citizen, National Service completed, 4.20/5.00 CAP, no current salary, no referees); `~` = a competent model has nothing to say (optional field); checkboxes `true` / `false`.
- Authored from what Workday, Greenhouse, Lever and SuccessFactors / Taleo forms ask of Singapore new-graduate applicants. Wordings are the author's recollection, not scraped.
