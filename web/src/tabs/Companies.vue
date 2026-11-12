<script setup>
// Your own list of companies (M16) set against the companies JobScraper can read
// (M17), in one table (Q-118 LD). Drop a TXT or DOCX file - one company per line, most
// wanted first - or type the names, and the tab stores the list (PUT /api/companies/list)
// and starts the company search as a background job: Qwen suggests each careers site,
// discovery proves there is a job board behind it, and every company found is watched
// from then on, scraped in your order.
//
// The page head holds the list's actions (Edit list, Upload list, Search now, More:
// downloads and Clear list). Below it WatchedCompanies.vue draws the funnel
//   N in your list -> N watched -> N readable -> N checked this cycle
// and ONE table: every watched company, then the names of your list that were not found
// or are still waiting, each with its outcome. Found and failed names download as TXT -
// the not-found list is ready to fix and upload again. The plan caps how many companies
// a list adds; a failed search does not count toward it.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import {
  ApiError, COMPANY_EXPORT_URL, LIST_TYPES, clearCompanyList, describeError, failureText,
  getCompanyHealth, getCompanyList, getSettings, startCompanySearch, uploadCompanyList,
} from '../api.js'
import { useJob } from '../composables/useJob.js'
import { takeCompanyFilter } from '../companyFilter.js'
import { tabEmits, tabProps } from '../shell.js'
import Icon from '../components/Icon.vue'
import WatchedCompanies from '../components/WatchedCompanies.vue'
import MenuButton from '../ui/MenuButton.vue'

defineProps(tabProps)
const emit = defineEmits(tabEmits)

const MAX_BYTES = 1024 * 1024
const ACCEPT = ['.txt', '.docx', ...Object.values(LIST_TYPES)].join(',')

// The words of the downloadable report, one per search status.
const STATUS_LABEL = {
  found: 'Found',
  watched: 'Already watched',
  failed: 'No job board found',
  pending: 'Waiting',
  searching: 'Searching…',
  over_limit: 'Over plan limit',
}
const WAITING = new Set(['pending', 'searching', 'over_limit'])

const data = ref(null)
const loadError = ref('')
const loading = ref(true)
const dragging = ref(false)
const uploading = ref(false)
const starting = ref(false)
const clearing = ref(false)
const problem = ref('')
const note = ref('')
const fileEl = ref(null)
const moreEl = ref(null)

const wantedState = takeCompanyFilter()   // "N failed" on the Runs tab

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
const found = computed(() => items.value.filter(i => i.status === 'found' || i.status === 'watched'))
const failed = computed(() => items.value.filter(i => i.status === 'failed'))
const waiting = computed(() => items.value.filter(i => WAITING.has(i.status)))

// "Your list, and which of its companies JobScraper can read." The plan's cap, when it
// has one, goes on the end; a failed search does not count toward it.
const sub = computed(() => {
  const base = 'Your list, and which of its companies JobScraper can read.'
  const cap = data.value?.max_companies ?? null
  if (cap === null) return base
  const n = data.value?.searched ?? 0
  return `${base} ${n} of ${cap} companies used on the ${data.value?.plan ?? 'local'} plan.`
})

// Every watched company - watchlist and your list - and whether its careers
// site could be scanned (M17). The CSV behind the menu item is the same list.
const health = ref(null)
const healthError = ref('')
async function loadHealth() {
  try {
    health.value = await getCompanyHealth()
    healthError.value = ''
  } catch (e) {
    healthError.value = describeError(e)
  }
}

// "Checked this cycle" needs the cycle length. If the settings do not load, the table
// says "Readable" instead of splitting checked from due.
const cycleDays = ref(null)
async function loadCycle() {
  try {
    const n = Number((await getSettings())?.cycle_days)
    cycleDays.value = n > 0 ? n : null
  } catch {
    cycleDays.value = null
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
  loadHealth()                          // names dropped from the list are no longer watched
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

// A file dropped anywhere on the tab replaces the list; while it is over the tab an
// overlay says so. The depth counter keeps the overlay steady while the pointer
// crosses the tab's children (each one fires its own enter and leave).
let dragDepth = 0
const carriesFiles = e => !e.dataTransfer?.types || Array.from(e.dataTransfer.types).includes('Files')
function onDragEnter(e) {
  if (!carriesFiles(e)) return
  e.preventDefault()
  dragDepth += 1
  dragging.value = !busy.value
}
function onDragOver(e) {
  if (!carriesFiles(e)) return
  e.preventDefault()
  dragging.value = !busy.value
}
function onDragLeave() {
  dragDepth = Math.max(0, dragDepth - 1)
  if (!dragDepth) dragging.value = false
}
function onDrop(e) {
  if (!carriesFiles(e)) return
  e.preventDefault()
  dragDepth = 0
  dragging.value = false
  if (busy.value) return
  take(e.dataTransfer?.files?.[0])
}

// Clearing is rare and cannot be undone, so it sits in the More menu and asks in place
// (Q-75 G26); Keep is focused first, Esc backs out and focus returns to More.
const confirmingClear = ref(false)
const keepEl = ref(null)
async function askClear() {
  confirmingClear.value = true
  await nextTick()
  keepEl.value?.focus()
}
async function keepList() {
  confirmingClear.value = false
  await nextTick()
  moreEl.value?.focus()
}

async function clear() {
  confirmingClear.value = false
  problem.value = ''
  note.value = ''
  clearing.value = true
  try {
    data.value = await clearCompanyList()
    emit('changed', {})
    loadHealth()
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
function downloadNotFound() { save('companies-failed.txt', lines(failed.value)) }
function downloadReport() {
  const head = ['rank', 'company', 'status', 'careers_url', 'open_roles', 'detail']
  const rows = items.value.map(r => [r.position, r.name, STATUS_LABEL[r.status] ?? r.status,
    r.careers_url, r.postings, r.detail].map(csvCell).join(','))
  save('companies-report.csv', '﻿' + [head.join(','), ...rows].join('\r\n') + '\r\n', 'text/csv')
}
// The server's CSV of every watched company: a plain download of the same address.
function downloadWatched() {
  const a = document.createElement('a')
  a.href = COMPANY_EXPORT_URL
  a.download = ''
  document.body.appendChild(a)
  a.click()
  a.remove()
}

const moreItems = computed(() => [
  { id: 'found', label: 'Download found (.txt)', disabled: !found.value.length },
  { id: 'notfound', label: 'Download not found (.txt)', disabled: !failed.value.length },
  { id: 'report', label: 'Full report (.csv)', disabled: !items.value.length },
  { id: 'watched', label: 'All watched companies (.csv)' },
  { id: 'clear', label: 'Clear list…', danger: true, disabled: busy.value || !items.value.length },
])
function onMore(id) {
  if (id === 'found') downloadFound()
  else if (id === 'notfound') downloadNotFound()
  else if (id === 'report') downloadReport()
  else if (id === 'watched') downloadWatched()
  else if (id === 'clear') askClear()
}

// Nothing watched and nothing listed: the first-run page (a drop zone and the editor).
const firstRun = computed(() => !loading.value && !loadError.value && !items.value.length
  && health.value && !health.value.total && !editing.value)

onMounted(() => Promise.all([loadList(), loadHealth(), loadCycle(), refresh()]))
</script>

<template>
  <section
    class="companies-tab"
    @dragenter="onDragEnter"
    @dragover="onDragOver"
    @dragleave="onDragLeave"
    @drop="onDrop"
  >
    <header class="page-head">
      <div>
        <h2 class="page-title">Companies</h2>
        <p class="page-sub">{{ sub }}</p>
      </div>
      <div class="page-controls">
        <button v-if="!editing" type="button" class="edit-list" :disabled="busy" @click="editList">
          {{ items.length ? 'Edit list' : 'Type or paste names' }}
        </button>
        <button type="button" class="upload-list" :disabled="busy" @click="fileEl?.click()">
          {{ uploading ? 'Uploading…' : 'Upload list' }}
        </button>
        <button v-if="items.length && waiting.length && !searching" type="button" class="primary search-now" :disabled="busy" @click="search">
          <Icon name="search" /> Search now
        </button>
        <MenuButton
          ref="moreEl"
          :items="moreItems"
          label="More list actions"
          align="end"
          trigger-class="ghost more-actions"
          @select="onMore"
        >
          <template #trigger><Icon name="more" /> More</template>
        </MenuButton>
        <input
          ref="fileEl"
          class="visually-hidden file"
          type="file"
          tabindex="-1"
          :accept="ACCEPT"
          :disabled="busy"
          aria-label="Choose a TXT or DOCX file of companies"
          @change="onPick"
        >
      </div>
    </header>

    <!-- Clearing cannot be undone: asked in place. -->
    <div v-if="confirmingClear" class="notice warn clear-ask" role="group" aria-labelledby="clear-q" @keydown.esc="keepList">
      <span id="clear-q" class="clear-q">Clear your list? The companies it added stop being watched.</span>
      <span class="clear-buttons">
        <button type="button" class="confirm-clear" :disabled="busy" @click="clear">Clear list</button>
        <button ref="keepEl" type="button" class="keep-list" @click="keepList">Keep list</button>
      </span>
    </div>

    <form v-if="editing" class="list-editor ui-card" novalidate @submit.prevent="saveTyped">
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

    <p v-if="problem" class="notice error" role="alert">{{ problem }}</p>
    <p v-if="note" class="notice ok" role="status">{{ note }}</p>
    <p v-if="searching" class="notice warn searching" role="status">
      Searching {{ waiting.length }} {{ waiting.length === 1 ? 'company' : 'companies' }}… Qwen suggests each careers site and each one is checked for a job board.
      <a href="#/developer">Follow the log</a>
    </p>
    <p v-else-if="otherJob && waiting.length" class="notice warn" role="status">
      Another job is running; search the list when it has finished.
    </p>
    <div v-if="loadError" class="notice error" role="alert">
      <p>Could not load your list: {{ loadError }}</p>
      <button type="button" @click="loadList">Try again</button>
    </div>

    <!-- First run: no list and nothing watched. -->
    <template v-if="firstRun">
      <button
        type="button"
        class="drop"
        :class="{ dragging }"
        :disabled="busy"
        aria-describedby="list-hint"
        @click="fileEl?.click()"
      >
        <span class="drop-title">{{ uploading ? 'Uploading…' : 'Drop your list of companies here, or choose a file' }}</span>
        <span id="list-hint" class="muted">
          TXT or DOCX, one company per line, in your order of preference. Companies searched before keep their result.
        </span>
      </button>
      <div class="empty">
        <Icon name="layers" :size="28" />
        <p class="empty-title">No list yet.</p>
        <p class="muted">Type the companies you want to work for, or drop a file with one per line above.</p>
        <p><button type="button" class="link" :disabled="busy" @click="editList">Type or paste names</button></p>
      </div>
    </template>
    <WatchedCompanies
      v-else
      :health="health"
      :list="data"
      :cycle-days="cycleDays"
      :error="healthError"
      :initial-state="wantedState || 'all'"
      @retry="loadHealth"
    />

    <!-- A file dragged over the tab: a drop anywhere replaces the list. -->
    <div v-if="dragging" class="drop-overlay ui-drop" data-drop="over" role="presentation">
      <span class="drop-overlay-text">Drop to replace your list</span>
    </div>
  </section>
</template>

<style scoped>
.companies-tab { position: relative; }
.page-controls { align-items: center; }
.notice { margin-bottom: var(--space-3); }
.notice p { margin: 0; }

.clear-ask { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-2) var(--space-4); }
.clear-buttons { display: inline-flex; flex-wrap: wrap; gap: var(--space-2); }
.confirm-clear { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 45%, var(--border-strong)); }
.search-now { display: inline-flex; align-items: center; gap: var(--space-1); }

/* The first-run drop zone is one big button that opens the file picker. */
.drop {
  display: grid; gap: var(--space-1); justify-items: center; text-align: center; width: 100%;
  height: auto; padding: var(--space-6) var(--space-4); white-space: normal;
  border: 2px dashed var(--border-strong); border-radius: var(--radius-lg);
  background: var(--surface); box-shadow: none;
}
.drop:hover:not(:disabled) { border-color: var(--accent); background: var(--surface); }
.drop.dragging { border-color: var(--accent); background: var(--accent-soft); }
.drop-title { font-weight: var(--weight-semibold); }
.drop .muted { font-size: var(--text-sm); font-weight: 400; }
.drop + .empty { margin-top: var(--space-4); }

/* Type or paste names (UX-1). */
.list-editor { display: grid; gap: var(--space-2); margin-bottom: var(--space-4); }
.list-editor-label { font-weight: var(--weight-semibold); font-size: var(--text-sm); }
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

/* The overlay covers the tab and lets every drag event through to the section. */
.drop-overlay {
  position: absolute; inset: 0; z-index: 4; display: grid; place-items: center;
  pointer-events: none; border-radius: var(--radius-lg);
}
.drop-overlay-text {
  padding: var(--space-3) var(--space-5); font-weight: var(--weight-semibold);
  color: var(--accent); background: var(--surface); border-radius: var(--radius-pill); box-shadow: var(--shadow-md);
}

@media (max-width: 640px) {
  .page-controls { width: 100%; }
}
</style>
