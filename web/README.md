# web/ — the JobScraper UI

Vue 3 + Vite (PRD D-3, section 8.5). One page; the run selector swaps the data
in place, and everything else is a tab.

## You do not need node to *run* the app

The build output lives in `src/jobscraper/web/static/` and **is committed**, so
this works from a plain Python checkout:

```powershell
$env:PYTHONPATH = "src"
python -m jobscraper web          # http://127.0.0.1:8765
```

Host and port come from `web.host` / `web.port` in `config/config.yaml`, or from
the `JOBSCRAPER_HOST` / `JOBSCRAPER_PORT` environment variables. Keep the host at
`127.0.0.1`: the app has no authentication.

## Changing the UI

Needs Node 22+ and npm.

```powershell
cd web
npm install          # once
npm test             # Vitest + Vue Test Utils, tests in web/tests/
npm run build        # rewrites src/jobscraper/web/static/
```

**Commit the rebuilt `src/jobscraper/web/static/` together with the source
change.** Otherwise a Python-only checkout serves the old UI.

For hot reload, run `python -m jobscraper web` in one terminal and `npm run dev`
in another, then open the URL Vite prints. The dev server forwards `/api` to
`127.0.0.1:8765`.

## Adding a tab

One line in `src/tabs.js`, one component in `src/tabs/`, and, if it needs data,
one router module in `src/jobscraper/web/routers/`. Routers are discovered
automatically, so nothing else changes (PRD M7-T4).
