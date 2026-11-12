<script setup>
// Every company JobScraper watches - the watchlist and your own list - in one
// searchable A-Z directory, and whether its careers site could be read (M17's
// /api/companies/health). Failed companies say why in words and, opened, what
// the error was and what you can do about it; the Failed view groups them by
// cause. The CSV download is the same list.
//
// A long list can be read at a glance (Q-75 G30): "Compact" drops each row to
// one line (the choice is remembered in this browser), and above 20 companies
// an A-Z strip jumps to a letter. Off-screen rows are not laid out
// (content-visibility, G41), so a thousand companies scroll smoothly.
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { COMPANY_EXPORT_URL } from '../api.js'
import { DENSITY_EVENT, densityCompact, setDensityCompact } from '../density.js'
import { ago, plural } from '../format.js'
import CompanyMark from './CompanyMark.vue'
import Icon from './Icon.vue'
import TabLoading from './TabLoading.vue'

const props = defineProps({
  health: { type: Object, default: null },
  error: { type: String, default: '' },
  // 'all' | 'ok' | 'failed' | 'not_scanned' - where the view starts.
  initialState: { type: String, default: 'all' },
})
const emit = defineEmits(['retry'])

const STATES = [
  { id: 'all', label: 'All' },
  { id: 'ok', label: 'Can be scanned' },
  { id: 'failed', label: 'Failed' },
  { id: 'not_scanned', label: 'Not scanned yet' },
]
const STATE_PILL = {
  ok: { label: 'OK', pill: 'ok' },
  failed: { label: 'Failed', pill: 'failed' },
  not_scanned: { label: 'Not scanned yet', pill: 'pending' },
}

// Why a scan failed (the server's `kind`), in a few words, and what to do.
const CAUSES = {
  blocked: {
    label: 'Blocks automated access',
    fix: 'The company\'s site refuses automated readers. Check its careers page yourself, or find the job board it uses (Greenhouse, Lever, Workday…) and set that in config/watchlist.yaml.',
  },
  gone: {
    label: 'Careers page gone',
    fix: 'The careers address no longer exists - the company probably moved it. Find the new page and update careers_url in config/watchlist.yaml.',
  },
  schema: {
    label: 'No readable job listings',
    fix: 'The page loads, but no jobs could be read from it (often a site built entirely in JavaScript). Add a feed_url for its job board in config/watchlist.yaml.',
  },
  transient: {
    label: 'Temporary error',
    fix: 'A timeout, a busy server or a network blip. Nothing to do - it is tried again on the next scan.',
  },
  other: {
    label: 'Unexpected error',
    fix: 'Something unusual went wrong; the error below says what. If it keeps happening, check the company\'s entry in config/watchlist.yaml.',
  },
}
// Before the server sent `kind` (older installs): read it from the reason.
function causeOf(row) {
  if (row.kind && CAUSES[row.kind]) return row.kind
  const r = row.reason || ''
  if (/blocks/.test(r)) return 'blocked'
  if (/no longer exists/.test(r)) return 'gone'
  if (/no job listings/.test(r)) return 'schema'
  if (/temporary/.test(r)) return 'transient'
  return 'other'
}
const isPaused = row => row.paused ?? /paused/.test(row.reason || '')

// The hiring system behind a careers site, as people know it.
const BOARDS = {
  generic_html: 'Own careers page', greenhouse: 'Greenhouse', lever: 'Lever', ashby: 'Ashby',
  smartrecruiters: 'SmartRecruiters', workable: 'Workable', recruitee: 'Recruitee', workday: 'Workday',
}
const boardName = b => BOARDS[b] ?? b

const SORTS = {
  az: { label: 'Name A–Z', fn: (a, b) => byName(a, b) },
  za: { label: 'Name Z–A', fn: (a, b) => byName(b, a) },
  roles: { label: 'Most open roles', fn: (a, b) => (b.open_roles ?? -1) - (a.open_roles ?? -1) || byName(a, b) },
  recent: { label: 'Last scanned', fn: (a, b) => String(b.last_scan || '').localeCompare(String(a.last_scan || '')) || byName(a, b) },
}
const byName = (a, b) => String(a.company).localeCompare(String(b.company), undefined, { sensitivity: 'base' })

const query = ref('')
const state = ref(STATES.some(s => s.id === props.initialState) ? props.initialState : 'all')
const cause = ref('all')
const source = ref('all')
const sort = ref('az')
const searchEl = ref(null)
const openAll = ref(false)             // every failure's detail open at once

// ---- density (G30): remembered in this browser (density.js) ----
// The button here and the Settings -> Preferences switch write the same key and tell
// each other through a window event, so whichever is open follows the other.
const compact = ref(densityCompact())
function toggleDensity() {
  setDensityCompact(!compact.value)
  compact.value = densityCompact()
}
function onDensity(e) {
  compact.value = typeof e.detail?.on === 'boolean' ? e.detail.on : densityCompact()
}
window.addEventListener(DENSITY_EVENT, onDensity)
onBeforeUnmount(() => window.removeEventListener(DENSITY_EVENT, onDensity))

watch(state, () => { cause.value = 'all' })

const items = computed(() => props.health?.items ?? [])
const counts = computed(() => {
  const c = { all: items.value.length, ok: 0, failed: 0, not_scanned: 0 }
  for (const i of items.value) c[i.state] = (c[i.state] ?? 0) + 1
  return c
})
const hasYourList = computed(() => items.value.some(i => i.source === 'your list'))
// The "your list" chip says which rows came from it; it says nothing when every
// row did, or when the Source filter already picked them (G30).
const showSource = computed(() => source.value === 'all'
  && hasYourList.value && items.value.some(i => i.source !== 'your list'))

const q = computed(() => query.value.trim().toLowerCase())
function matches(row) {
  if (!q.value) return true
  return [row.company, row.job_board, boardName(row.job_board), row.reason, row.careers_url]
    .some(v => String(v || '').toLowerCase().includes(q.value))
}

// Everything but the state and cause filters: what the chips count.
const base = computed(() => items.value.filter(r =>
  matches(r) && (source.value === 'all' || r.source === source.value)))

const failedHere = computed(() => base.value.filter(r => r.state === 'failed'))
const causes = computed(() => {
  const n = {}
  for (const r of failedHere.value) {
    const k = causeOf(r)
    n[k] = (n[k] ?? 0) + 1
  }
  return Object.keys(CAUSES).filter(k => n[k]).map(k => ({ id: k, n: n[k], ...CAUSES[k] }))
})

const shown = computed(() => base.value
  .filter(r => state.value === 'all' || r.state === state.value)
  .filter(r => state.value !== 'failed' || cause.value === 'all' || causeOf(r) === cause.value)
  .sort(SORTS[sort.value].fn))

// A-Z: a letter heading wherever the first letter changes.
const lettered = computed(() => sort.value === 'az' || sort.value === 'za')
function letterOf(row) {
  const c = String(row.company || '').trim().charAt(0).toUpperCase()
  return /[A-Z]/.test(c) ? c : '#'
}
const rows = computed(() => {
  const out = []
  let last = null
  for (const r of shown.value) {
    if (lettered.value) {
      const l = letterOf(r)
      if (l !== last) out.push({ letter: l, key: `letter-${l}` })
      last = l
    }
    out.push({ row: r, key: `co-${r.company}` })
  }
  return out
})

// ---- A-Z jump (G30): only when the list is long enough to need it ----
const JUMP_FROM = 20
const jumpLetters = computed(() => (!lettered.value || shown.value.length <= JUMP_FROM
  ? []
  : rows.value.filter(r => r.letter).map(r => r.letter)))
const listEl = ref(null)
async function jumpTo(letter) {
  await nextTick()
  const el = listEl.value?.querySelector(`[data-letter="${letter}"]`)
  if (!el) return
  el.scrollIntoView?.({ block: 'start' })
  el.focus?.({ preventScroll: true })
}

function clearFilters() {
  query.value = ''
  state.value = 'all'
  cause.value = 'all'
  source.value = 'all'
  searchEl.value?.focus()
}

const safe = url => (/^https?:\/\//i.test(url || '') ? url : null)
</script>

<template>
  <div class="watched">
    <TabLoading v-if="!health && !error" :rows="4" />
    <div v-else-if="!health" class="notice error" role="alert">
      <p>Could not read the watched companies: {{ error }}</p>
      <button type="button" @click="emit('retry')">Try again</button>
    </div>

    <template v-else>
      <!-- The numbers double as the filter: click one to see those companies. -->
      <div class="tiles" role="group" aria-label="Show companies">
        <button
          v-for="s in STATES.filter(x => x.id !== 'not_scanned' || counts.not_scanned)"
          :key="s.id"
          type="button"
          class="tile"
          :class="[`tile-${s.id}`, { active: state === s.id }]"
          :aria-pressed="state === s.id ? 'true' : 'false'"
          :data-state="s.id"
          @click="state = s.id"
        >
          <span class="tile-n num">{{ counts[s.id] }}</span>
          <span class="tile-label">{{ s.id === 'all' ? 'Watched' : s.label }}</span>
        </button>
      </div>

      <div class="toolbar">
        <label class="search grow">
          <Icon name="search" />
          <span class="visually-hidden">Search companies</span>
          <input
            ref="searchEl"
            v-model="query"
            type="search"
            class="company-search"
            placeholder="Search by company, job board or reason…"
            autocomplete="off"
            aria-keyshortcuts="/"
            @keydown.esc="query = ''"
          >
          <kbd class="key-hint" aria-hidden="true">/</kbd>
        </label>
        <label v-if="hasYourList" class="inline">
          <span class="visually-hidden">Source</span>
          <select v-model="source" class="source">
            <option value="all">Watchlist and your list</option>
            <option value="watchlist">Watchlist only</option>
            <option value="your list">Your list only</option>
          </select>
        </label>
        <label class="inline">
          <span class="visually-hidden">Sort</span>
          <select v-model="sort" class="sort">
            <option v-for="(s, id) in SORTS" :key="id" :value="id">{{ s.label }}</option>
          </select>
        </label>
        <button
          type="button"
          class="density"
          :class="{ active: compact }"
          :aria-pressed="compact ? 'true' : 'false'"
          @click="toggleDensity"
        >Compact rows</button>
        <a class="button health-csv" :href="COMPANY_EXPORT_URL" download>
          Download all (.csv)
        </a>
      </div>

      <!-- Failed: the causes, each with what to do, and a filter of its own. -->
      <section v-if="state === 'failed' && causes.length" class="causes" aria-label="Why they failed">
        <button
          type="button"
          class="cause"
          :class="{ active: cause === 'all' }"
          :aria-pressed="cause === 'all' ? 'true' : 'false'"
          @click="cause = 'all'"
        >
          <span class="cause-label">Every cause</span>
          <span class="num cause-n">{{ failedHere.length }}</span>
        </button>
        <button
          v-for="c in causes"
          :key="c.id"
          type="button"
          class="cause"
          :class="{ active: cause === c.id }"
          :aria-pressed="cause === c.id ? 'true' : 'false'"
          :data-cause="c.id"
          @click="cause = c.id"
        >
          <span class="cause-label">{{ c.label }}</span>
          <span class="num cause-n">{{ c.n }}</span>
        </button>
      </section>
      <p v-if="state === 'failed' && cause !== 'all'" class="cause-fix" role="note">
        <strong>What you can do:</strong> {{ CAUSES[cause].fix }}
      </p>

      <p class="result-line muted" aria-live="polite">
        {{ plural(shown.length, 'company', 'companies') }}<template v-if="q"> matching “{{ query.trim() }}”</template>
        <template v-if="q || state !== 'all' || source !== 'all'">
          · <button type="button" class="link" @click="clearFilters">Clear filters</button>
        </template>
        <template v-if="shown.some(r => r.state === 'failed')">
          · <button type="button" class="link open-all" @click="openAll = !openAll">
            {{ openAll ? 'Hide all details' : 'Show all details' }}
          </button>
        </template>
      </p>

      <nav v-if="jumpLetters.length" class="jump" aria-label="Jump to a letter">
        <button v-for="l in jumpLetters" :key="l" type="button" class="jump-letter" :aria-label="`Jump to ${l}`" @click="jumpTo(l)">{{ l }}</button>
      </nav>

      <ul v-if="shown.length" ref="listEl" class="dir surface" :class="{ compact }">
        <template v-for="item in rows" :key="item.key">
          <li v-if="item.letter" class="letter" :data-letter="item.letter" tabindex="-1">{{ item.letter }}</li>
          <li v-else class="co" :data-state="item.row.state">
            <CompanyMark :name="item.row.company" size="sm" />
            <div class="co-main">
              <div class="co-top">
                <span class="co-name">{{ item.row.company }}</span>
                <span v-if="showSource && item.row.source === 'your list'" class="chip">your list</span>
              </div>
              <p class="co-meta muted">
                <span v-if="item.row.job_board">{{ boardName(item.row.job_board) }}</span>
                <span v-if="item.row.state === 'ok' && item.row.open_roles !== null && item.row.open_roles !== undefined">
                  {{ plural(item.row.open_roles, 'open role') }}
                </span>
                <span v-if="item.row.last_scan" :title="`${item.row.last_scan} UTC`">checked {{ ago(item.row.last_scan.replace(' ', 'T')) }}</span>
              </p>
              <details v-if="item.row.state === 'failed'" class="why" :open="openAll">
                <summary>
                  <span class="why-text">{{ CAUSES[causeOf(item.row)].label }}</span>
                  <span v-if="isPaused(item.row)" class="paused">paused, retried later</span>
                </summary>
                <dl class="why-detail">
                  <div><dt>Why</dt><dd class="reason">{{ item.row.reason }}</dd></div>
                  <div v-if="item.row.error"><dt>Error</dt><dd class="mono err">{{ item.row.error }}</dd></div>
                  <div><dt>Failures in a row</dt><dd class="num">{{ item.row.failures_in_a_row }}</dd></div>
                  <div><dt>Last worked</dt><dd>{{ item.row.last_success ? `${item.row.last_success} UTC` : 'never' }}</dd></div>
                  <div><dt>What you can do</dt><dd>{{ CAUSES[causeOf(item.row)].fix }}</dd></div>
                </dl>
              </details>
            </div>
            <a
              v-if="safe(item.row.careers_url)"
              class="site"
              :href="item.row.careers_url"
              target="_blank"
              rel="noopener noreferrer"
              :aria-label="`${item.row.company} careers site`"
            ><Icon name="external" /><span class="site-text">Careers</span></a>
            <span v-else />
            <span class="pill co-state" :data-status="STATE_PILL[item.row.state]?.pill">{{ STATE_PILL[item.row.state]?.label ?? item.row.state }}</span>
          </li>
        </template>
      </ul>
      <div v-else class="empty none">
        <Icon name="search" :size="24" />
        <p class="empty-title">No companies match.</p>
        <p class="muted">Try another spelling, or <button type="button" class="link" @click="clearFilters">clear the filters</button>.</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(8.5rem, 1fr)); gap: var(--space-2); margin-bottom: var(--space-4); }
.tile {
  display: grid; justify-items: start; gap: 0; min-height: 0; height: auto;
  padding: var(--space-3) var(--space-4); text-align: left;
  border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface);
  box-shadow: var(--shadow-sm); white-space: normal;
}
.tile:hover:not(:disabled) { border-color: var(--border-strong); background: var(--surface); }
.tile.active { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.tile-n { font-size: var(--text-xl); font-weight: 650; line-height: 1.3; }
.tile-label { font-size: var(--text-xs); color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.tile-ok .tile-n { color: var(--ok); }
.tile-failed .tile-n { color: var(--danger); }

.toolbar { display: flex; flex-wrap: wrap; gap: var(--space-2); align-items: center; margin-bottom: var(--space-3); }
.grow { flex: 1 1 16rem; }
.inline { display: inline-flex; }

.causes { display: flex; flex-wrap: wrap; gap: var(--space-1); margin-bottom: var(--space-2); }
.cause { border-radius: 999px; font-size: var(--text-sm); gap: var(--space-2); }
.cause-n { color: var(--muted); }
.cause.active { background: var(--danger-soft); border-color: var(--danger); color: var(--danger); }
.cause.active .cause-n { color: inherit; }
.cause-fix {
  margin: 0 0 var(--space-3); padding: var(--space-3) var(--space-4); font-size: var(--text-sm);
  background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius);
}

.result-line { margin: 0 0 var(--space-2); font-size: var(--text-sm); }

/* clip, not hidden: hidden would make the list the letters' sticky container. */
.dir { list-style: none; margin: 0; padding: 0; overflow: clip; }
.letter {
  position: sticky; top: var(--header-h); z-index: 1;
  padding: var(--space-1) var(--space-4); background: var(--surface-2);
  border-top: 1px solid var(--border); border-bottom: 1px solid var(--border);
  font-family: var(--font-display); font-size: var(--text-xs); font-weight: 700; color: var(--muted);
}
.letter:first-child { border-top: 0; }
.co {
  display: grid; grid-template-columns: auto minmax(0, 1fr) auto auto; align-items: start;
  gap: var(--space-3); padding: var(--space-3) var(--space-4); border-top: 1px solid var(--border);
  /* Off-screen rows are skipped by layout and paint (G41); `auto` remembers the real height once seen. */
  content-visibility: auto; contain-intrinsic-size: auto 4.25rem;
}
.letter { scroll-margin-top: var(--header-h); }
.letter:focus { outline: none; }
.letter:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }

/* Compact (G30): name, board and counts on one line. */
.compact .co { padding: var(--space-1) var(--space-4); align-items: center; contain-intrinsic-size: auto 2.25rem; }
.compact .co > .mark { display: none; }
.compact .co { grid-template-columns: minmax(0, 1fr) auto auto; }
.compact .co-main { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0 var(--space-3); }
.compact .co-meta { gap: 0 var(--space-3); }
.compact .why { flex: 1 1 100%; }
.compact .co-state, .compact .site { margin-top: 0; }

.density.active { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); }
.jump { display: flex; flex-wrap: wrap; gap: 2px; margin: 0 0 var(--space-2); }
.jump-letter {
  min-height: 1.5rem; min-width: 1.5rem; padding: 0 var(--space-1);
  font-size: var(--text-xs); font-weight: 650; box-shadow: none; background: transparent;
  border-color: transparent; color: var(--accent);
}
.jump-letter:hover:not(:disabled) { background: var(--accent-soft); color: var(--accent); }
.letter + .co { border-top: 0; }
.co > .mark { margin-top: 2px; }
.co-main { min-width: 0; }
.co-top { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.co-name { font-weight: 600; overflow-wrap: anywhere; }
.co-meta { display: flex; flex-wrap: wrap; gap: 0 var(--space-3); margin: 0; font-size: var(--text-sm); }
.co-meta span { white-space: nowrap; }
.co-state, .site { margin-top: 2px; }
.site {
  display: inline-flex; align-items: center; justify-content: center; gap: var(--space-1);
  min-width: 1.5rem; min-height: 1.5rem; font-size: var(--text-sm); white-space: nowrap;
}
.pill[data-status='pending'] { color: var(--muted); background: var(--surface-2); }

.why { margin-top: var(--space-1); font-size: var(--text-sm); }
.why summary {
  display: inline-flex; flex-wrap: wrap; align-items: center; gap: var(--space-2);
  cursor: pointer; color: var(--danger); font-weight: 500; list-style: none;
}
.why summary::-webkit-details-marker { display: none; }
.why summary::before { content: '▸'; font-size: 0.8em; transition: transform 0.12s; }
.why[open] summary::before { transform: rotate(90deg); }
.why summary:hover .why-text { text-decoration: underline; }
.paused { font-size: var(--text-xs); color: var(--warn); background: var(--warn-soft); padding: 0 var(--space-2); border-radius: 999px; font-weight: 600; }
.why-detail {
  display: grid; gap: var(--space-2); margin: var(--space-2) 0 0; padding: var(--space-3);
  background: var(--surface-2); border-radius: var(--radius);
}
.why-detail div { display: grid; grid-template-columns: 9rem minmax(0, 1fr); gap: var(--space-2); }
.why-detail dt { color: var(--muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: 0.05em; padding-top: 2px; }
.why-detail dd { margin: 0; overflow-wrap: anywhere; }
.err { font-size: var(--text-xs); }

.none { padding: var(--space-6) var(--space-4); }

@media (max-width: 640px) {
  .co { grid-template-columns: auto minmax(0, 1fr) auto; }
  .site { grid-column: 2; grid-row: 2; justify-self: start; }
  .compact .site { grid-column: auto; grid-row: auto; justify-self: auto; }
  .site-text { display: none; }
  .why-detail div { grid-template-columns: 1fr; gap: 0; }
}
</style>
