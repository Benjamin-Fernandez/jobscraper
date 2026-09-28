<script setup>
// Your own list of companies (M16). Drop a TXT or DOCX file - one company per
// line, most wanted first - and the tab stores it (PUT /api/companies/list)
// and starts the company search as a background job: Qwen suggests each
// careers site, discovery proves there is a job board behind it, and every
// company found is watched from then on, scraped in your order.
//
// The list below keeps your order and says, for each company, what the search
// did: found (and where), already watched, failed (and why), or still waiting.
// Found and failed names download as TXT - the failed list is ready to fix and
// upload again. The plan caps how many companies a list adds; a failed search
// does not count toward it.
import { computed, onMounted, ref, watch } from 'vue'
import {
  ApiError, LIST_TYPES, clearCompanyList, describeError, getCompanyList,
  startCompanySearch, uploadCompanyList,
} from '../api.js'
import { useJob } from '../composables/useJob.js'
import { tabEmits, tabProps } from '../shell.js'
import CompanyMark from '../components/CompanyMark.vue'
import Icon from '../components/Icon.vue'
import TabLoading from '../components/TabLoading.vue'

defineProps(tabProps)
const emit = defineEmits(tabEmits)

const MAX_BYTES = 1024 * 1024
const ACCEPT = ['.txt', '.docx', ...Object.values(LIST_TYPES)].join(',')

const STATUS = {
  found: { label: 'Found', pill: 'ok' },
  watched: { label: 'Already watched', pill: 'applied' },
  failed: { label: 'Failed', pill: 'failed' },
  pending: { label: 'Waiting', pill: 'pending' },
  searching: { label: 'Searching…', pill: 'running' },
  over_limit: { label: 'Over plan limit', pill: 'dry_run' },
}
const WAITING = new Set(['pending', 'searching', 'over_limit'])
const FILTERS = [
  { id: 'all', label: 'All', has: () => true },
  { id: 'found', label: 'Found', has: s => s === 'found' || s === 'watched' },
  { id: 'failed', label: 'Failed', has: s => s === 'failed' },
  { id: 'waiting', label: 'Waiting', has: s => WAITING.has(s) },
]

const data = ref(null)
const loadError = ref('')
const loading = ref(true)
const dragging = ref(false)
const uploading = ref(false)
const starting = ref(false)
const clearing = ref(false)
const problem = ref('')
const note = ref('')
const filter = ref('all')

const { job, running, refresh, track } = useJob({
  kind: 'companies',
  onFinish: finished => {
    loadList()
    emit('changed', {})
    if (finished.state === 'succeeded') note.value = 'The search has finished.'
    else problem.value = 'The company search stopped early - its log is on the Developer tab.'
  },
})

const searching = computed(() => running.value && job.value?.kind === 'companies')
const otherJob = computed(() => running.value && job.value?.kind !== 'companies')
const busy = computed(() => uploading.value || starting.value || clearing.value || running.value)

const items = computed(() => data.value?.items ?? [])
const count = s => items.value.filter(i => i.status === s).length
const found = computed(() => items.value.filter(i => i.status === 'found' || i.status === 'watched'))
const failed = computed(() => items.value.filter(i => i.status === 'failed'))
const waiting = computed(() => items.value.filter(i => WAITING.has(i.status)))
const filterCount = f => items.value.filter(i => f.has(i.status)).length
const filtered = computed(() => {
  const f = FILTERS.find(x => x.id === filter.value) ?? FILTERS[0]
  return items.value.filter(i => f.has(i.status))
})

const capLine = computed(() => {
  const n = data.value?.searched ?? 0
  const plan = data.value?.plan ?? 'local'
  const cap = data.value?.max_companies ?? null
  if (cap === null) return `${n} ${n === 1 ? 'company' : 'companies'} counted · no limit on the ${plan} plan`
  return `${n} of ${cap} companies used on the ${plan} plan`
})

async function loadList() {
  try {
    data.value = await getCompanyList()
    loadError.value = ''
  } catch (e) {
    loadError.value = describeError(e)
  } finally {
    loading.value = false
  }
}

// Each poll of the running search also re-reads the list, so rows turn from
// Waiting to Found or Failed as the search reaches them.
watch(job, () => { if (searching.value) loadList() })

function extension(name) {
  return (/\.([a-z0-9]+)$/i.exec(name || '')?.[1] || '').toLowerCase()
}

function refusal(file) {
  if (!(extension(file.name) in LIST_TYPES)) {
    return `${file.name} is not a TXT or DOCX file. Put one company on each line and save it as either.`
  }
  if (file.size === 0) return `${file.name} is empty.`
  if (file.size > MAX_BYTES) return `${file.name} is larger than 1 MB.`
  return ''
}

function serverRefusal(e) {
  if (e instanceof ApiError && e.status === 413) return 'The server refused the file: it is larger than 1 MB.'
  if (e instanceof ApiError && e.status === 415) return `The server could not read the file: ${e.detail || 'not a TXT or DOCX file'}.`
  if (e instanceof ApiError && e.status === 422) return 'No company names were found in the file. Put one company on each line.'
  return `Could not upload the list: ${describeError(e)}`
}

async function search() {
  problem.value = ''
  starting.value = true
  try {
    track(await startCompanySearch(), { started: true })
    loadList()
  } catch (e) {
    problem.value = e instanceof ApiError && e.status === 409
      ? 'Another job is running. Press Search now when it has finished.'
      : `Could not start the search: ${describeError(e)}`
    refresh()
  } finally {
    starting.value = false
  }
}

async function take(file) {
  problem.value = ''
  note.value = ''
  if (!file) return
  const why = refusal(file)
  if (why) {
    problem.value = why
    return
  }
  uploading.value = true
  try {
    const saved = await uploadCompanyList(file)
    data.value = saved
    const u = saved.upload ?? {}
    const parts = [`Read ${u.read} ${u.read === 1 ? 'company' : 'companies'} from ${file.name}`]
    if (u.kept) parts.push(`${u.kept} searched before`)
    if (u.capped) parts.push('only the first 2,000 lines were read')
    note.value = parts.join(' · ') + '.'
  } catch (e) {
    problem.value = serverRefusal(e)
    return
  } finally {
    uploading.value = false
  }
  emit('changed', {})
  if (waiting.value.length) await search()
}

function onPick(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  take(file)
}

function onDrop(event) {
  dragging.value = false
  if (busy.value) return
  take(event.dataTransfer?.files?.[0])
}

async function clear() {
  if (!window.confirm('Clear your list? The companies it added stop being watched.')) return
  problem.value = ''
  note.value = ''
  clearing.value = true
  try {
    data.value = await clearCompanyList()
    emit('changed', {})
  } catch (e) {
    problem.value = `Could not clear the list: ${describeError(e)}`
  } finally {
    clearing.value = false
  }
}

// ---- downloads: built here from the list, nothing is fetched ----

function save(name, text, type = 'text/plain') {
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

const lines = rows => rows.map(r => r.name).join('\r\n') + '\r\n'
function csvCell(v) {
  const s = v === null || v === undefined ? '' : String(v)
  const safe = /^[=+\-@\t\r]/.test(s) ? `'${s}` : s        // never a formula in Excel
  return /[",\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe
}

function downloadFound() { save('companies-found.txt', lines(found.value)) }
function downloadFailed() { save('companies-failed.txt', lines(failed.value)) }
function downloadReport() {
  const head = ['rank', 'company', 'status', 'careers_url', 'open_roles', 'detail']
  const rows = items.value.map(r => [r.position, r.name, STATUS[r.status]?.label ?? r.status,
    r.careers_url, r.postings, r.detail].map(csvCell).join(','))
  save('companies-report.csv', '﻿' + [head.join(','), ...rows].join('\r\n') + '\r\n', 'text/csv')
}

onMounted(() => Promise.all([loadList(), refresh()]))
</script>

<template>
  <section class="companies-tab">
    <header class="page-head">
      <div>
        <h2 class="page-title">Companies</h2>
        <p class="page-sub">Your own list, most wanted first. Every company found is watched from the next run, in your order.</p>
      </div>
      <div v-if="items.length" class="page-controls">
        <button v-if="waiting.length && !searching" type="button" class="primary search-now" :disabled="busy" @click="search">
          <Icon name="search" /> Search now
        </button>
        <button type="button" class="clear" :disabled="busy" @click="clear">Clear list</button>
      </div>
    </header>

    <label
      class="drop"
      :class="{ dragging, disabled: busy, compact: items.length }"
      @dragenter.prevent="dragging = !busy"
      @dragover.prevent="dragging = !busy"
      @dragleave.prevent="dragging = false"
      @drop.prevent="onDrop"
    >
      <input
        class="visually-hidden file"
        type="file"
        :accept="ACCEPT"
        :disabled="busy"
        aria-describedby="list-hint"
        @change="onPick"
      >
      <span class="drop-title">
        {{ uploading ? 'Uploading…' : items.length ? 'Drop a new list to replace this one' : 'Drop your list of companies here, or choose a file' }}
      </span>
      <span id="list-hint" class="muted">
        TXT or DOCX, one company per line, in your order of preference. Companies searched before keep their result.
      </span>
    </label>

    <p v-if="problem" class="notice error" role="alert">{{ problem }}</p>
    <p v-if="note" class="notice ok" role="status">{{ note }}</p>
    <p v-if="searching" class="notice warn searching" role="status">
      Searching {{ waiting.length }} {{ waiting.length === 1 ? 'company' : 'companies' }}… Qwen suggests each careers site and each one is checked for a job board.
      <a href="#/developer">Follow the log</a>
    </p>
    <p v-else-if="otherJob && waiting.length" class="notice warn" role="status">
      Another job is running; search the list when it has finished.
    </p>

    <TabLoading v-if="loading" :rows="3" />
    <div v-else-if="loadError" class="notice error" role="alert">
      <p>Could not load your list: {{ loadError }}</p>
      <button type="button" @click="loadList">Try again</button>
    </div>
    <div v-else-if="!items.length" class="empty">
      <Icon name="layers" :size="28" />
      <p class="empty-title">No list yet.</p>
      <p class="muted">Write the companies you want to work for, one per line, and drop the file above.</p>
    </div>

    <template v-else>
      <div class="summary surface">
        <dl class="stats">
          <div><dt>Found</dt><dd class="num found-n">{{ count('found') }}</dd></div>
          <div><dt>Already watched</dt><dd class="num watched-n">{{ count('watched') }}</dd></div>
          <div><dt>Failed</dt><dd class="num failed-n">{{ failed.length }}</dd></div>
          <div><dt>Waiting</dt><dd class="num waiting-n">{{ waiting.length }}</dd></div>
        </dl>
        <p class="cap muted">{{ capLine }}. Failed searches do not count.</p>
        <div class="downloads">
          <button type="button" class="dl-found" :disabled="!found.length" @click="downloadFound">Download found (.txt)</button>
          <button type="button" class="dl-failed" :disabled="!failed.length" @click="downloadFailed">Download failed (.txt)</button>
          <button type="button" class="dl-report" @click="downloadReport">Full report (.csv)</button>
        </div>
      </div>

      <div class="filters" role="group" aria-label="Show">
        <button
          v-for="f in FILTERS"
          :key="f.id"
          type="button"
          class="filter"
          :class="{ active: filter === f.id }"
          :aria-pressed="filter === f.id ? 'true' : 'false'"
          @click="filter = f.id"
        >
          {{ f.label }} <span class="num">{{ filterCount(f) }}</span>
        </button>
      </div>

      <ol class="list surface">
        <li v-for="c in filtered" :key="c.position" class="row" :data-status="c.status">
          <span class="rank num" :title="`Your #${c.position}`">{{ c.position }}</span>
          <CompanyMark :name="c.name" size="sm" />
          <div class="what">
            <span class="name">{{ c.name }}</span>
            <span v-if="c.detail" class="detail muted">{{ c.detail }}</span>
          </div>
          <a
            v-if="c.careers_url"
            class="site"
            :href="c.careers_url"
            target="_blank"
            rel="noopener noreferrer"
            :aria-label="`${c.name} careers site`"
          ><Icon name="external" /> Careers</a>
          <span v-else />
          <span class="pill status" :data-status="STATUS[c.status]?.pill ?? c.status">{{ STATUS[c.status]?.label ?? c.status }}</span>
        </li>
        <li v-if="!filtered.length" class="row none muted">Nothing here.</li>
      </ol>
    </template>
  </section>
</template>

<style scoped>
.drop {
  display: grid; gap: var(--space-1); justify-items: center; text-align: center;
  padding: var(--space-6) var(--space-4);
  border: 2px dashed var(--border-strong); border-radius: var(--radius-lg);
  background: var(--surface); cursor: pointer;
  transition: border-color 0.12s, background-color 0.12s;
}
.drop.compact { padding: var(--space-4); }
.drop:hover { border-color: var(--accent); }
.drop:focus-within { outline: 2px solid var(--focus); outline-offset: 2px; }
.drop.dragging { border-color: var(--accent); background: var(--accent-soft); }
.drop.disabled { opacity: 0.6; cursor: not-allowed; }
.drop.disabled:hover { border-color: var(--border-strong); }
.drop-title { font-weight: 600; }
.drop .muted { font-size: var(--text-sm); }
.notice { margin-top: var(--space-3); }
.clear { color: var(--danger); }
.search-now { display: inline-flex; align-items: center; gap: var(--space-1); }

.summary { margin: var(--space-4) 0 var(--space-3); padding: var(--space-4); display: grid; gap: var(--space-3); }
.stats { display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-6); margin: 0; }
.stats dt { font-size: var(--text-xs); color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.stats dd { margin: 0; font-size: var(--text-xl); font-weight: 600; }
.found-n { color: var(--ok); }
.failed-n { color: var(--danger); }
.cap { margin: 0; font-size: var(--text-sm); }
.downloads { display: flex; flex-wrap: wrap; gap: var(--space-2); }

.filters { display: flex; flex-wrap: wrap; gap: var(--space-1); margin-bottom: var(--space-2); }
.filter { border-radius: 999px; font-size: var(--text-sm); }
.filter .num { color: var(--muted); margin-left: var(--space-1); }
.filter.active { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); }
.filter.active .num { color: inherit; }

.list { list-style: none; margin: 0; padding: 0; }
.row {
  display: grid; grid-template-columns: 2.25rem auto minmax(0, 1fr) auto auto; align-items: center;
  gap: var(--space-3); padding: var(--space-2) var(--space-4); border-top: 1px solid var(--border);
}
.row:first-child { border-top: 0; }
.row.none { display: block; text-align: center; padding: var(--space-4); }
.rank { color: var(--muted); font-size: var(--text-sm); text-align: right; }
.what { display: grid; min-width: 0; }
.name { font-weight: 600; overflow-wrap: anywhere; }
.detail { font-size: var(--text-sm); }
.site { display: inline-flex; align-items: center; gap: var(--space-1); font-size: var(--text-sm); white-space: nowrap; }
.pill[data-status='pending'] { color: var(--muted); background: var(--surface-2); }

@media (max-width: 640px) {
  .row { grid-template-columns: 1.75rem auto minmax(0, 1fr); }
  .site, .status { grid-column: 3; justify-self: start; }
}
</style>
