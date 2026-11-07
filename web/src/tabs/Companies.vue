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
//
// The tab has two views: Watched companies - every company a run checks, A-Z
// and searchable, with why any of them failed (WatchedCompanies.vue) - and
// Your list. The view last used is remembered in this browser.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import {
  ApiError, LIST_TYPES, clearCompanyList, describeError, failureText, getCompanyHealth,
  getCompanyList, startCompanySearch, uploadCompanyList,
} from '../api.js'
import { useJob } from '../composables/useJob.js'
import { takeCompanyFilter } from '../companyFilter.js'
import { tabEmits, tabProps } from '../shell.js'
import CompanyMark from '../components/CompanyMark.vue'
import Icon from '../components/Icon.vue'
import TabLoading from '../components/TabLoading.vue'
import WatchedCompanies from '../components/WatchedCompanies.vue'

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
const listQuery = ref('')
const listSort = ref('order')          // 'order' (yours) | 'az'

// ---- which view: Watched companies or Your list ----
const VIEW_KEY = 'jobscraper.companies.view'
const wantedState = takeCompanyFilter()   // "N failed" on the Runs tab
function rememberedView() {
  try {
    return window.localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'watched'
  } catch {
    return 'watched'
  }
}
const view = ref(wantedState ? 'watched' : rememberedView())
watch(view, v => {
  try { window.localStorage.setItem(VIEW_KEY, v) } catch { /* private window */ }
})

const { job, running, refresh, track } = useJob({
  kind: 'companies',
  onFinish: finished => {
    loadList()
    loadHealth()
    emit('changed', {})
    if (finished.state === 'succeeded') note.value = 'The search has finished.'
    else problem.value = failureText(finished, 'The company search stopped early - its log is on the Developer tab.')
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
  const q = listQuery.value.trim().toLowerCase()
  const rows = items.value.filter(i => f.has(i.status)
    && (!q || [i.name, i.detail, i.careers_url].some(v => String(v || '').toLowerCase().includes(q))))
  if (listSort.value === 'az') {
    return [...rows].sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: 'base' }))
  }
  return rows
})

const capLine = computed(() => {
  const n = data.value?.searched ?? 0
  const plan = data.value?.plan ?? 'local'
  const cap = data.value?.max_companies ?? null
  if (cap === null) return `${n} ${n === 1 ? 'company' : 'companies'} counted · no limit on the ${plan} plan`
  return `${n} of ${cap} companies used on the ${plan} plan`
})

// Every watched company - watchlist and your list - and whether its careers
// site could be scanned (M17). The CSV behind the link is the same list.
const health = ref(null)
const healthError = ref('')
const failedWatched = computed(() => health.value?.counts?.failed ?? 0)
async function loadHealth() {
  try {
    health.value = await getCompanyHealth()
    healthError.value = ''
  } catch (e) {
    healthError.value = describeError(e)
  }
}

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

// Store a list file and search its new names. `source` names it in the note.
// True once the list is stored (whether or not the search could start).
async function take(file, source = file?.name) {
  problem.value = ''
  note.value = ''
  if (!file) return false
  const why = refusal(file)
  if (why) {
    problem.value = why
    return false
  }
  uploading.value = true
  try {
    const saved = await uploadCompanyList(file)
    data.value = saved
    const u = saved.upload ?? {}
    const parts = [`Read ${u.read} ${u.read === 1 ? 'company' : 'companies'} from ${source}`]
    if (u.kept) parts.push(`${u.kept} searched before`)
    if (u.capped) parts.push('only the first 2,000 lines were read')
    note.value = parts.join(' · ') + '.'
  } catch (e) {
    problem.value = serverRefusal(e)
    return false
  } finally {
    uploading.value = false
  }
  emit('changed', {})
  if (waiting.value.length) await search()
  return true
}

// ---- type or paste names (UX-1): no file needed ----
// The editor starts from the current list, in order, so adding, removing and
// reordering are all just editing. Saving sends it as a TXT list through the
// same upload, so companies searched before keep their result.

const editing = ref(false)
const draft = ref('')
const draftEl = ref(null)
const draftNames = computed(() => draft.value.split(/\r?\n/).map(l => l.trim()).filter(Boolean))

async function editList() {
  draft.value = items.value.map(i => i.name).join('\n')
  problem.value = ''
  editing.value = true
  await nextTick()
  draftEl.value?.focus()
}

async function saveTyped() {
  if (!draftNames.value.length) {
    problem.value = 'Write at least one company name, one per line.'
    return
  }
  const file = new File([`${draftNames.value.join('\n')}\n`], 'companies.txt', { type: 'text/plain' })
  if (await take(file, 'your list')) editing.value = false
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

// Clearing is rare and cannot be undone, so it sits quietly beside the downloads
// and asks in place (Q-75 G26); Keep is focused first, Esc backs out.
const confirmingClear = ref(false)
const keepEl = ref(null)
const clearEl = ref(null)
async function askClear() {
  confirmingClear.value = true
  await nextTick()
  keepEl.value?.focus()
}
async function keepList() {
  confirmingClear.value = false
  await nextTick()
  clearEl.value?.focus()
}

async function clear() {
  confirmingClear.value = false
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

onMounted(() => Promise.all([loadList(), loadHealth(), refresh()]))
</script>

<template>
  <section class="companies-tab">
    <header class="page-head">
      <div>
        <h2 class="page-title">Companies</h2>
        <p v-if="view === 'watched'" class="page-sub">Every company a run checks, A–Z, and whether its careers site could be read.</p>
        <p v-else class="page-sub">Your own list, most wanted first. Every company found is watched from the next run, in your order.</p>
      </div>
      <div class="views" role="group" aria-label="Companies view">
        <button
          type="button"
          class="view-tab view-watched"
          :class="{ active: view === 'watched' }"
          :aria-pressed="view === 'watched' ? 'true' : 'false'"
          @click="view = 'watched'"
        >
          Watched companies
          <span v-if="health" class="num view-n">{{ health.total }}</span>
          <span v-if="failedWatched" class="num view-failed" :title="`${failedWatched} failed the last fetch`">{{ failedWatched }} failed</span>
        </button>
        <button
          type="button"
          class="view-tab view-list"
          :class="{ active: view === 'list' }"
          :aria-pressed="view === 'list' ? 'true' : 'false'"
          @click="view = 'list'"
        >
          Your list
          <span v-if="data" class="num view-n">{{ items.length }}</span>
        </button>
      </div>
    </header>

    <WatchedCompanies
      v-if="view === 'watched'"
      :health="health"
      :error="healthError"
      :initial-state="wantedState || 'all'"
      @retry="loadHealth"
    />

    <template v-else>
      <div v-if="items.length || !editing" class="list-controls">
        <button v-if="items.length && waiting.length && !searching" type="button" class="primary search-now" :disabled="busy" @click="search">
          <Icon name="search" /> Search now
        </button>
        <button v-if="!editing" type="button" class="edit-list" :disabled="busy" @click="editList">
          {{ items.length ? 'Edit list' : 'Type or paste names' }}
        </button>
      </div>

      <form v-if="editing" class="list-editor surface" novalidate @submit.prevent="saveTyped">
        <label for="list-text" class="list-editor-label">Your companies, one per line, most wanted first</label>
        <textarea
          id="list-text"
          ref="draftEl"
          v-model="draft"
          class="list-text"
          rows="10"
          spellcheck="false"
          autocomplete="off"
          aria-describedby="list-text-hint"
          placeholder="Grab&#10;Shopee&#10;GovTech"
        />
        <p id="list-text-hint" class="muted list-editor-hint">
          Add, remove or reorder names. New names are searched when you save; companies searched before keep their result.
        </p>
        <div class="list-editor-actions">
          <button type="submit" class="primary save-list" :disabled="busy">
            {{ uploading ? 'Saving…' : 'Save list' }}
          </button>
          <button type="button" class="cancel-list" :disabled="uploading" @click="editing = false">Cancel</button>
          <span class="muted num list-editor-count">{{ draftNames.length }} {{ draftNames.length === 1 ? 'company' : 'companies' }}</span>
        </div>
      </form>

      <label
        v-else
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
      <div v-else-if="!items.length && !editing" class="empty">
        <Icon name="layers" :size="28" />
        <p class="empty-title">No list yet.</p>
        <p class="muted">Type the companies you want to work for, or drop a file with one per line above.</p>
        <p><button type="button" class="link" :disabled="busy" @click="editList">Type or paste names</button></p>
      </div>
      <!-- While the editor is open it is the empty state. -->
      <template v-else-if="!items.length" />


      <template v-else>
        <div class="summary surface">
          <dl class="stats">
            <div>
              <dt>Found</dt>
              <dd class="num found-n">{{ found.length }}</dd>
              <dd v-if="count('watched')" class="sub muted watched-n">{{ count('watched') }} already watched</dd>
            </div>
            <div><dt>Failed</dt><dd class="num failed-n">{{ failed.length }}</dd></div>
            <div><dt>Waiting</dt><dd class="num waiting-n">{{ waiting.length }}</dd></div>
          </dl>
          <p class="cap muted">{{ capLine }}. Failed searches do not count.</p>
          <div class="downloads">
            <button type="button" class="dl-found" :disabled="!found.length" @click="downloadFound">Download found (.txt)</button>
            <button type="button" class="dl-failed" :disabled="!failed.length" @click="downloadFailed">Download failed (.txt)</button>
            <button type="button" class="dl-report" @click="downloadReport">Full report (.csv)</button>
            <span v-if="confirmingClear" class="clear-ask" role="group" aria-label="Clear your list" @keydown.esc="keepList">
              <span class="clear-q">Clear your list? The companies it added stop being watched.</span>
              <button type="button" class="confirm-clear" :disabled="busy" @click="clear">Yes, clear it</button>
              <button ref="keepEl" type="button" class="keep-list" @click="keepList">Keep it</button>
            </span>
            <button v-else ref="clearEl" type="button" class="ghost clear" :disabled="busy" @click="askClear">Clear list</button>
          </div>
        </div>

        <div class="list-toolbar">
          <label class="search grow">
            <Icon name="search" />
            <span class="visually-hidden">Search your list</span>
            <input
              v-model="listQuery"
              type="search"
              class="list-search"
              placeholder="Search your list…"
              autocomplete="off"
              aria-keyshortcuts="/"
              @keydown.esc="listQuery = ''"
            >
            <kbd class="key-hint" aria-hidden="true">/</kbd>
          </label>
          <label>
            <span class="visually-hidden">Order</span>
            <select v-model="listSort" class="list-sort">
              <option value="order">Your order</option>
              <option value="az">Name A–Z</option>
            </select>
          </label>
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
          <li v-if="!filtered.length" class="row none muted">
            {{ listQuery.trim() ? `No company in your list matches “${listQuery.trim()}”.` : 'Nothing here.' }}
          </li>
        </ol>
      </template>
    </template>
  </section>
</template>

<style scoped>
/* The segments wrap onto a second line when the column is narrower than both
   (Q-71: at 390px they were 389px in a 341px column and widened the page). Both
   stay in view, so the selected one is always visible. */
.views {
  display: inline-flex; flex-wrap: wrap; gap: 2px; padding: 2px;
  max-width: 100%; min-width: 0;
  background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius);
}
.view-tab {
  border: 1px solid transparent; background: transparent; box-shadow: none; color: var(--text-2);
  border-radius: calc(var(--radius) - 2px);
  max-width: 100%; white-space: normal; text-align: left;
}
.view-tab:hover:not(:disabled) { background: var(--surface); color: var(--text); }
.view-tab.active, .view-tab.active:hover:not(:disabled) {
  background: var(--surface); border-color: var(--border-strong); box-shadow: var(--shadow-sm);
  color: var(--text); font-weight: 650;
}
.view-n { color: var(--muted); font-size: var(--text-xs); }
.view-failed {
  font-size: var(--text-xs); font-weight: 600; color: var(--danger); background: var(--danger-soft);
  padding: 0 var(--space-2); border-radius: 999px;
}
.list-controls { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--space-2); margin-bottom: var(--space-3); }
.list-toolbar { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-bottom: var(--space-2); }
.grow { flex: 1 1 16rem; }

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
.drop + .empty, .drop ~ .skeleton { margin-top: var(--space-4); }
.list-editor ~ .skeleton { margin-top: var(--space-4); }

/* Type or paste names (UX-1). */
.list-editor { display: grid; gap: var(--space-2); padding: var(--space-4); }
.list-editor-label { font-weight: 600; font-size: var(--text-sm); }
.list-text {
  width: 100%; min-height: 12rem; resize: vertical; padding: var(--space-2) var(--space-3);
  font: inherit; font-size: var(--text-sm); line-height: 1.6; color: var(--text);
  background: var(--surface); border: 1px solid var(--border-strong); border-radius: var(--radius);
  transition: border-color 0.12s, box-shadow 0.12s;
}
.list-text:focus-visible {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent);
}
.list-editor-hint { margin: 0; font-size: var(--text-sm); }
.list-editor-actions { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.list-editor-count { font-size: var(--text-sm); margin-left: auto; }
/* Quiet until asked: the irreversible choice is red only inside its own question. */
.clear { margin-left: auto; }
.clear-ask { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); margin-left: auto; font-size: var(--text-sm); }
.confirm-clear { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 45%, var(--border-strong)); }
.search-now { display: inline-flex; align-items: center; gap: var(--space-1); }

.summary { margin: var(--space-4) 0 var(--space-3); padding: var(--space-4); display: grid; gap: var(--space-3); }
.stats { display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-6); margin: 0; }
.stats dt { font-size: var(--text-xs); color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; }
.stats dd { margin: 0; font-size: var(--text-xl); font-weight: 600; }
.stats .sub { font-size: var(--text-xs); font-weight: 400; }
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
  /* Off-screen rows are skipped by layout and paint (Q-75 G41). */
  content-visibility: auto; contain-intrinsic-size: auto 3.25rem;
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
