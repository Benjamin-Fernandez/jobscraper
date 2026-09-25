# web/ — the JobScraper UI

Vue 3 + Vite (PRD D-3, section 8.5, M12). One page with tabs across the top -
Inbox, Applications, Runs, Profile, Settings. The active tab lives in the URL
hash (`#/runs`), so refresh, back/forward and bookmarks work; arrow keys move
between tabs. The run selector (in Inbox and Applications) swaps the data in
place.

Styling: every colour, size and space is a token in `src/style.css` (light and
dark), and components use only those tokens.

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
automatically, so nothing else changes (PRD M7-T4). The tab gets the URL
`#/<id>` and a place in the tab bar with no other edit.

The component declares the shell's contract from `src/shell.js`:

```js
import { tabEmits, tabProps } from '../shell.js'
defineProps(tabProps)   // run, runs, jobs, loading, error
defineEmits(tabEmits)   // changed, select-run
```

A registry entry may add `badge: ({ jobs, stats, runs, run }) => number | null`
and `badgeLabel` to show a count on the tab.
