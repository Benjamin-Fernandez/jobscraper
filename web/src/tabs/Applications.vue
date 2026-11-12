<script setup>
// Applications (M13-T3, Q-118 section 3): every role you have saved or applied to,
// grouped by company - the question you ask before applying again ("what have I
// already sent Grab?"). A strip of stage tabs across the top - All, Active, Applied,
// Interviewing, Offer, Rejected (D-207) - counts each and filters to it; the open tab
// is in the URL (`#/applications/<stage>`). Each row (ApplicationRow) moves through
// its status pill ("Move to…") or by dragging it onto a tab, and keeps its app_events
// history.
//
// D-207: `to_apply`, `assessment` and `withdrawn` have no tab and are not move
// targets, but they stay in the data: a `to_apply` row (saved, or being auto-applied
// to) shows under All and Active, an `assessment` row under Interviewing and a
// `withdrawn` row under Rejected, each with its own word on its pill (`stageOf`).
// Nothing here rewrites a row's status on its own; a role reads Applied only when its
// status is applied.
//
// The run selector here is this tab's own filter and starts on "all runs": an
// application outlives the run that found it (M12-T1).
//
// Email updates (Q-60, F-50l-n): suggestions an email raised sit above the stage
// strip (MailSuggestions, hidden when there are none), and an event an email
// made wears a "From email" badge in History (MailEvidence) with its quote and
// Undo. Either action reloads the rows and the suggestions.
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { describeError, getApplicationAttempts, getApplications, getStats, setApplicationStatus, untrackApplication } from '../api.js'
import { IN_PROGRESS_REMOVE, attemptLabel, modeLabel } from '../attempts.js'
import {
  STAGE_KEY, inFlight, inStage, isActive, lastAt, pinRank, rememberedStage, stageCounts,
} from '../applications.js'
import { openProfile } from '../profileView.js'
import { exactTime, plural, when } from '../format.js'
import { useHashItem, useView } from '../route.js'
import { tabEmits, tabProps } from '../shell.js'
import { MOVE_TARGETS, STAGE_TABS, stageOf, stageTabLabel, statusLabel } from '../stages.js'
import { showToast } from '../toast.js'
import { runsInRange } from '../runs.js'
import ApplicationRow from '../components/ApplicationRow.vue'
import CompanyMark from '../components/CompanyMark.vue'
import Icon from '../components/Icon.vue'
import JobDetail from '../components/JobDetail.vue'
import MailEvidence from '../components/MailEvidence.vue'
import MailSuggestions from '../components/MailSuggestions.vue'
import RunSelector from '../components/RunSelector.vue'
import TabLoading from '../components/TabLoading.vue'
import Segmented from '../ui/Segmented.vue'

const props = defineProps(tabProps)
const emit = defineEmits(tabEmits)

const rows = ref([])
const statuses = ref([])
const loading = ref(true)
const error = ref('')
const saving = ref('')
const runFilter = ref('all')
const root = ref(null)

// ---- the open tab: in the hash, and remembered ----
// `#/applications/<stage>` opens that tab; a bare `#/applications` opens the one
// picked last (localStorage, mapped by `rememberedStage` so an old `to_apply`,
// `assessment` or `withdrawn` value lands on the tab that holds it now), and All on a
// first visit. An unknown stage in the hash opens All (design section 7).
function readStage() {
  try { return rememberedStage(window.localStorage.getItem(STAGE_KEY)) } catch { return 'all' }
}
function unknownStageInHash() {
  const m = /^#\/applications\/([\w-]+)/.exec(window.location.hash || '')
  return Boolean(m && !STAGE_TABS.includes(m[1]))
}
let remembered = unknownStageInHash() ? 'all' : readStage()
const stage = useView('applications', STAGE_TABS, remembered)
watch(stage, v => {
  remembered = v
  try { window.localStorage.setItem(STAGE_KEY, v) } catch { /* private mode */ }
}, { immediate: true })
// useView sends a bare `#/applications` (the nav bar's link) back to the tab that was
// remembered when this page mounted; while the page stays alive, keep the latest one.
function onHash() {
  if (/^#\/applications\/?$/.test(window.location.hash || '') && stage.value !== remembered) {
    stage.value = remembered
  }
}
window.addEventListener('hashchange', onHash)
onBeforeUnmount(() => window.removeEventListener('hashchange', onHash))

const query = ref('')

const UNKNOWN = 'Unknown company'
const companyOf = row => row.company || UNKNOWN
const roleOf = row => row.role ?? row.job_id

// The run and search filters; the stage filter comes after, so the strip's
// counts always describe what the other filters leave.
const inScope = computed(() => {
  const q = query.value.trim().toLowerCase()
  const inRuns = runsInRange(props.runs, runFilter.value)   // null = every run
  return rows.value.filter(r =>
    (!inRuns || inRuns.has(r.run_no))
    && (!q || [r.company, r.role].some(v => (v || '').toLowerCase().includes(q))))
})

// Stages in config order (the order of roles inside a company); a status config no
// longer lists goes last, not missing.
const order = computed(() => {
  const list = [...statuses.value]
  for (const r of rows.value) if (!list.includes(r.status)) list.push(r.status)
  return list
})

const stages = computed(() => {
  const n = stageCounts(inScope.value)
  return STAGE_TABS.map(id => ({ id, label: stageTabLabel(id), n: n[id] }))
})

const shown = computed(() => inScope.value.filter(r => inStage(r, stage.value)))

// The page sub-title counts the whole data set, before any filter.
const companyCount = computed(() => new Set(rows.value.map(companyOf)).size)
const activeCount = computed(() => rows.value.filter(isActive).length)

// By company groups a company's roles together; Recent lists every application on
// its own, the latest change first.
const sort = ref('company')
const SORTS = [{ value: 'company', label: 'By company' }, { value: 'recent', label: 'Recent' }]

// Rows JobScraper is applying to or that wait in the queue lead All and Active
// (running, then by queue position); elsewhere they sort as any other row.
const pins = computed(() => stage.value === 'all' || stage.value === 'active')
function pinOrder(a, b) {
  if (!pins.value) return 0
  const x = pinRank(a) || Infinity
  const y = pinRank(b) || Infinity
  return x === y ? 0 : x < y ? -1 : 1
}

// Companies A-Z (a company with a pinned row first); inside one, pinned rows, then
// roles by stage (config order), then title. Recent: one list, no company headers.
const groups = computed(() => {
  if (sort.value === 'recent') {
    const list = [...shown.value]
      .sort((a, b) => pinOrder(a, b) || String(lastAt(b)).localeCompare(String(lastAt(a))))
    return list.length ? [{ company: '', key: 'recent', rows: list }] : []
  }
  const by = new Map()
  for (const r of shown.value) {
    const key = companyOf(r)
    if (!by.has(key)) by.set(key, [])
    by.get(key).push(r)
  }
  const rank = s => order.value.indexOf(s)
  const lead = list => (pins.value ? Math.min(...list.map(r => pinRank(r) || Infinity)) : Infinity)
  return [...by.entries()]
    .map(([company, list]) => ({
      company,
      key: company,
      rows: list.sort((x, y) => pinOrder(x, y) || rank(x.status) - rank(y.status)
        || String(x.role || '').localeCompare(String(y.role || ''))),
    }))
    .map(g => ({ ...g, lead: lead(g.rows) }))
    .sort((a, b) => (a.lead === b.lead ? 0 : a.lead < b.lead ? -1 : 1)
      || a.company.localeCompare(b.company, undefined, { sensitivity: 'base' }))
})

async function load() {
  error.value = ''
  try {
    const [apps, stats] = await Promise.all([getApplications(), getStats()])
    rows.value = apps
    statuses.value = stats.statuses
  } catch (e) {
    error.value = `Could not load applications: ${describeError(e)}`
  } finally {
    loading.value = false
  }
}

function retry() {
  loading.value = true
  load()
}

function showAll() {
  stage.value = 'all'
  runFilter.value = 'all'
  query.value = ''
}

// ---- rows by id (focus after a move, the hash item) ----

const rowRefs = {}
const stageBtns = {}

// After a move the row's pill gets focus back; when the row left this tab, the tab
// itself does (there is no pill to return to).
async function refocus(jobId) {
  await nextTick()
  const r = rowRefs[jobId]
  if (r && shown.value.some(x => x.job_id === jobId)) r.focusMove()
  else stageBtns[stage.value]?.focus()
}

// `#/applications/<stage>/<job_id>` (Runs' "Open in Applications") scrolls to and
// focuses that row once the rows are in.
const hashItem = useHashItem('applications')
async function revealHashItem() {
  const id = hashItem.value
  if (!id || loading.value) return
  await nextTick()
  const r = rowRefs[id]
  const el = r?.el?.()
  if (!el) return
  el.scrollIntoView?.({ block: 'center' })
  r.focus()
}
watch([hashItem, loading], revealHashItem)

// ---- the live region: one polite sentence at a time ----

const announcement = ref('')
function announce(text) {
  // Cleared first so the same sentence twice is still read out.
  announcement.value = ''
  nextTick(() => { announcement.value = text })
}

// ---- email updates ----

const suggestions = ref(null)

// A suggestion was accepted or an email-made change undone: the status moved.
async function afterMail() {
  await load()
  emit('changed')
  await suggestions.value?.load()
}

async function change(row, status) {
  if (status === row.status) return
  const before = row.status
  saving.value = row.job_id
  error.value = ''
  try {
    await setApplicationStatus(row.job_id, status)
    await load()
    emit('changed')
    announce(`${roleOf(row)} at ${companyOf(row)} moved from ${statusLabel(before)} to ${statusLabel(status)}.`)
    // Undo is one more change, so it writes one more history event (D-101); it
    // restores the old status even when that one has no tab (to_apply, assessment,
    // withdrawn).
    showToast({
      message: `Moved to ${statusLabel(status)}: ${roleOf(row)}`,
      action: { label: 'Undo', run: () => change({ ...row, status }, before) },
    })
    // A suggestion about this application may no longer apply (superseded).
    suggestions.value?.load()
  } catch (e) {
    error.value = `Could not change ${row.company ?? row.job_id}: ${describeError(e)}`
  } finally {
    saving.value = ''
  }
  refocus(row.job_id)
}

// ---- drag a row onto a stage tab (pointer, wider than a phone) ----
// Native HTML5 drag and drop. The dragged row is kept here, not only in
// dataTransfer (a browser hides its data until the drop, and a test stub may not
// carry it). The four move targets accept a drop, except the row's own stage; All
// and Active never do. Esc cancels natively ("Drop cancelled.").

const DRAG_TYPE = 'text/x-jobscraper-job'
const dragged = ref(null)
const overTab = ref('')
let dropped = false

const dragEnabled = ref(true)
onMounted(() => {
  try {
    const mq = window.matchMedia?.('(max-width: 640px), (pointer: coarse)')
    dragEnabled.value = !mq?.matches
  } catch { /* no matchMedia: keep the default */ }
})

function accepts(tab, row = dragged.value) {
  return Boolean(row) && MOVE_TARGETS.includes(tab) && stageOf(row.status) !== tab
}
function dropState(tab) {
  if (!dragged.value) return undefined
  if (!accepts(tab)) return 'no'
  return overTab.value === tab ? 'over' : 'ok'
}

function onDragStart(row, event) {
  dragged.value = row
  dropped = false
  const dt = event?.dataTransfer
  if (dt) {
    try { dt.setData(DRAG_TYPE, row.job_id) } catch { /* a stub without setData */ }
    try { dt.effectAllowed = 'move' } catch { /* read-only in a stub */ }
  }
  announce(`Dragging ${roleOf(row)}. Drop it on a stage tab.`)
}
function onDragEnd() {
  if (dragged.value && !dropped) announce('Drop cancelled.')
  dragged.value = null
  overTab.value = ''
}
function draggedRow(event) {
  if (dragged.value) return dragged.value
  let id = ''
  try { id = event?.dataTransfer?.getData?.(DRAG_TYPE) || '' } catch { /* no data */ }
  return id ? rows.value.find(r => r.job_id === id) ?? null : null
}
function setEffect(event, effect) {
  try { if (event?.dataTransfer) event.dataTransfer.dropEffect = effect } catch { /* stub */ }
}
function onDragOver(tab, event) {
  if (!dragged.value) return
  if (!accepts(tab)) { setEffect(event, 'none'); return }
  event?.preventDefault?.()
  setEffect(event, 'move')
  overTab.value = tab
}
function onDragLeave(tab) {
  if (overTab.value === tab) overTab.value = ''
}
function onDrop(tab, event) {
  event?.preventDefault?.()
  const row = draggedRow(event)
  const ok = accepts(tab, row)
  dropped = true
  dragged.value = null
  overTab.value = ''
  if (ok) change(row, tab)
}

// Removing asks first, under the row (Q-100 A13): "Remove {company} from
// Applications? Its notes go too." [Remove] [Keep]. Focus goes to Keep, the safe
// answer, and back to the row's "⋯" menu when the owner keeps the row.
const removeAsk = ref('')           // job id whose removal is being confirmed
const keepBtns = {}
async function askRemove(row) {
  removeAsk.value = row.job_id
  await nextTick()
  keepBtns[row.job_id]?.focus()
}
async function keepRow(row) {
  removeAsk.value = ''
  await nextTick()
  rowRefs[row.job_id]?.focusMore()
}
function confirmRemove(row) {
  removeAsk.value = ''
  return removeRow(row)
}

// Only a row with a single event can be removed, so no history is lost; Undo
// puts it back as it was (Q-70 B6, G6). A role JobScraper is applying to answers
// 409 `in_progress` (the queue backend): the server's own words are shown.
async function removeRow(row) {
  error.value = ''
  try {
    await untrackApplication(row.job_id)
    await load()
    emit('changed')
    showToast({
      message: `Removed ${roleOf(row)}`,
      action: {
        label: 'Undo',
        run: async () => {
          try {
            await setApplicationStatus(row.job_id, row.status,
              { company: row.company, role: row.role, url: row.url, notes: row.notes })
            await load()
            emit('changed')
          } catch (e) {
            error.value = `Could not restore ${row.company ?? row.job_id}: ${describeError(e)}`
          }
        },
      },
    })
  } catch (e) {
    const said = e?.status === 409 && e?.body?.text
      ? [e.body.text, e.body.hint].filter(Boolean).join(' ')
      : e?.status === 409 ? IN_PROGRESS_REMOVE : describeError(e)
    error.value = `Could not remove ${row.company ?? row.job_id}: ${said}`
  }
}

// ---- notes: the same POST with the row's own status, so the history gets no
// new event; an empty note clears it ----

const noteFor = ref('')          // job id whose note is open for editing
const noteDraft = ref('')
const savingNote = ref(false)
const noteInputs = {}

async function editNote(row) {
  noteFor.value = row.job_id
  noteDraft.value = row.notes || ''
  await nextTick()
  noteInputs[row.job_id]?.focus()
}

async function saveNote(row) {
  savingNote.value = true
  error.value = ''
  try {
    await setApplicationStatus(row.job_id, row.status, { notes: noteDraft.value.trim() })
    // Close this row's editor only - never one opened since.
    if (noteFor.value === row.job_id) noteFor.value = ''
    await load()
  } catch (e) {
    error.value = `Could not save the note for ${row.company ?? row.job_id}: ${describeError(e)}`
  } finally {
    savingNote.value = false
  }
}

// ---- the posting under a row (Q-76 N12): one open at a time ----

const openId = ref(null)           // job id whose detail is open
const attempts = ref({})           // job id -> { state: 'loading' | 'ok' | 'error', items, error }

// The shortlist's shape for JobDetail: the row's own fields, filled out by the
// posting data the server found for it (null once the role left the shortlist).
function detailJob(row) {
  return {
    ...row,
    ...(row.posting ?? {}),
    id: row.job_id,
    title: row.role ?? row.job_id,
    closed: row.posting?.closed ?? Boolean(row.closed_at),
  }
}

async function loadAttempts(id) {
  attempts.value = { ...attempts.value, [id]: { state: 'loading', items: [] } }
  try {
    const items = await getApplicationAttempts(id)
    attempts.value = { ...attempts.value, [id]: { state: 'ok', items } }
  } catch (e) {
    attempts.value = { ...attempts.value, [id]: { state: 'error', items: [], error: describeError(e) } }
  }
}

function toggleDetail(row) {
  if (openId.value === row.job_id) { openId.value = null; return }
  openId.value = row.job_id
  loadAttempts(row.job_id)
}

onMounted(load)
// A cached tab coming back shows what changed meanwhile (Q-70 B9).
let shownOnce = false
onActivated(() => { if (shownOnce) load(); shownOnce = true })

// ---- follow the auto-apply queue (Q-120 U3) ----
// The Inbox, Runs and a row's "Try again" announce `jobscraper:apply-queue`; the rows
// reload then, and every 10 s while one is queued or being applied to (no polling
// otherwise). A quiet reload: no error banner, and it waits while a save or a drag is
// under way or the first load has not finished. Off while the tab is cached or hidden.
const QUEUE_EVENT = 'jobscraper:apply-queue'
const POLL_MS = 10000
let active = true
let following = false
let poll = null

async function refreshQuiet() {
  if (!active || following || loading.value || saving.value || dragged.value) return
  following = true
  try {
    const [apps, stats] = await Promise.all([getApplications(), getStats()])
    rows.value = apps
    statuses.value = stats.statuses
  } catch { /* keep what is shown; the next tick tries again */ } finally {
    following = false
  }
}

function syncPoll() {
  const live = active && rows.value.some(inFlight)
  if (live && poll === null) {
    poll = setInterval(() => { if (!document.hidden) refreshQuiet() }, POLL_MS)
  } else if (!live && poll !== null) {
    clearInterval(poll)
    poll = null
  }
}
watch(rows, syncPoll, { immediate: true })

const onQueueEvent = () => refreshQuiet()
onMounted(() => window.addEventListener(QUEUE_EVENT, onQueueEvent))
onActivated(() => { active = true; syncPoll() })
onDeactivated(() => { active = false; syncPoll() })
onBeforeUnmount(() => {
  window.removeEventListener(QUEUE_EVENT, onQueueEvent)
  active = false
  syncPoll()
})
</script>

<template>
  <section ref="root" class="applications" :aria-busy="loading ? 'true' : 'false'">
    <header class="page-head">
      <div>
        <h2 class="page-title">Applications</h2>
        <p v-if="!loading && rows.length" class="page-sub count">
          {{ activeCount }} active · {{ rows.length }} tracked at {{ plural(companyCount, 'company', 'companies') }}
        </p>
      </div>
      <div class="page-controls">
        <label class="search">
          <Icon name="search" />
          <span class="visually-hidden">Search applications</span>
          <input v-model="query" type="search" placeholder="Search company or role" aria-keyshortcuts="/" @keydown.esc="query ? (query = '') : $event.target.blur()">
          <kbd class="key-hint" aria-hidden="true">/</kbd>
        </label>
        <Segmented v-model="sort" class="app-sort" label="Sort" :options="SORTS" />
        <RunSelector
          :runs="runs"
          :model-value="runFilter"
          :choosable="false"
          @update:model-value="v => { runFilter = v }"
        />
      </div>
    </header>

    <!-- One polite live region for the tab: drag start, the move, a cancelled drop. -->
    <p class="visually-hidden app-live" aria-live="polite">{{ announcement }}</p>

    <div v-if="error" class="notice error" role="alert">
      <p>{{ error }}</p>
      <button type="button" @click="retry">Try again</button>
    </div>
    <TabLoading v-if="loading" :rows="3" />
    <div v-else-if="!rows.length && !error" class="empty">
      <Icon name="layers" :size="28" />
      <p class="empty-title">Nothing tracked yet.</p>
      <p class="muted">Save a role or mark it applied in the <a href="#/inbox">Inbox</a> and it appears here.</p>
    </div>

    <template v-else-if="rows.length">
      <MailSuggestions ref="suggestions" @changed="afterMail" />

      <div class="stages" :class="{ 'is-dragging': dragged }" role="group" aria-label="Filter by stage">
        <button
          v-for="s in stages"
          :key="s.id"
          :ref="el => { stageBtns[s.id] = el }"
          type="button"
          class="stage"
          :class="{ active: stage === s.id, 'ui-drop': dragged }"
          :data-status="s.id"
          :data-drop="dropState(s.id)"
          :aria-pressed="stage === s.id ? 'true' : 'false'"
          @click="stage = s.id"
          @dragenter="onDragOver(s.id, $event)"
          @dragover="onDragOver(s.id, $event)"
          @dragleave="onDragLeave(s.id)"
          @drop="onDrop(s.id, $event)"
        >
          <span class="stage-label">{{ s.label }}</span>
          <span class="stage-n num" :class="{ zero: !s.n }">{{ s.n }}</span>
        </button>
      </div>

      <div v-if="!shown.length" class="empty">
        <p class="empty-title">Nothing here.</p>
        <p class="muted">No application matches this stage, run and search.</p>
        <p><button type="button" class="clear-filters" @click="showAll">Show all</button></p>
      </div>

      <div class="groups">
        <section
          v-for="group in groups"
          :key="group.key"
          class="company-group ui-card"
          :data-company="group.company || null"
        >
          <header v-if="sort !== 'recent'" class="group-head">
            <CompanyMark :name="group.company" size="sm" />
            <h3 class="group-name">{{ group.company }}</h3>
            <span class="group-sep" aria-hidden="true">·</span>
            <span class="group-n">{{ plural(group.rows.length, 'role') }}</span>
          </header>
          <ul class="app-rows">
            <ApplicationRow
              v-for="row in group.rows"
              :key="row.application_id ?? row.job_id"
              :ref="el => { if (el) rowRefs[row.job_id] = el; else delete rowRefs[row.job_id] }"
              :row="row"
              :show-company="sort === 'recent'"
              :saving="saving === row.job_id"
              :details-open="openId === row.job_id"
              :drag-enabled="dragEnabled"
              :dragging="dragged?.job_id === row.job_id"
              @move="s => change(row, s)"
              @remove="askRemove(row)"
              @note="editNote(row)"
              @details="toggleDetail(row)"
              @drag-start="e => onDragStart(row, e)"
              @drag-end="onDragEnd"
            >
              <form
                v-if="noteFor === row.job_id"
                class="note-form"
                @submit.prevent="saveNote(row)"
                @keydown.esc="noteFor = ''"
              >
                <label class="visually-hidden" :for="`note-${row.job_id}`">Note on {{ row.company ?? row.job_id }} · {{ row.role ?? '' }}</label>
                <textarea
                  :id="`note-${row.job_id}`"
                  :ref="el => { noteInputs[row.job_id] = el }"
                  v-model="noteDraft"
                  class="note-input"
                  rows="3"
                  maxlength="4000"
                  placeholder="Recruiter, referral, interview dates…"
                />
                <div class="note-actions">
                  <button type="submit" class="primary note-save" :disabled="savingNote">
                    {{ savingNote ? 'Saving…' : 'Save note' }}
                  </button>
                  <button type="button" class="ghost note-cancel" :disabled="savingNote" @click="noteFor = ''">Cancel</button>
                </div>
              </form>
              <p v-else-if="row.notes" class="notes">{{ row.notes }}</p>
              <span v-if="removeAsk === row.job_id" class="remove-ask" role="group" :aria-labelledby="`remove-q-${row.job_id}`">
                <span :id="`remove-q-${row.job_id}`" class="remove-q">
                  Remove {{ row.company ?? row.job_id }} from Applications? Its notes go too.
                </span>
                <button type="button" class="link remove-yes" @click="confirmRemove(row)">Remove</button>
                <button
                  :ref="el => { keepBtns[row.job_id] = el }"
                  type="button"
                  class="link remove-keep"
                  @click="keepRow(row)"
                >Keep</button>
              </span>
              <details v-if="row.events && row.events.length > 1" class="history">
                <summary>History <span class="num">{{ row.events.length }}</span></summary>
                <ol class="timeline">
                  <li v-for="e in row.events" :key="e.id" :data-by="e.by ?? null">
                    <span class="to pill" :data-status="e.to_status">{{ statusLabel(e.to_status) }}</span>
                    <span class="at" :title="exactTime(e.at)">{{ when(e.at) }}</span>
                    <MailEvidence v-if="e.by === 'mail' && e.mail" :event="e" @undone="afterMail" @stale="afterMail" />
                  </li>
                </ol>
              </details>
              <div
                v-if="openId === row.job_id"
                :id="`app-panel-${row.job_id}`"
                class="app-detail"
                role="region"
                :aria-labelledby="`app-detail-${row.job_id}`"
              >
                <JobDetail :job="detailJob(row)" :title-id="`app-detail-${row.job_id}`">
                  <template #extra>
                    <section class="attempts" aria-labelledby="attempts-heading">
                      <h4 id="attempts-heading">Auto-apply attempts</h4>
                      <p v-if="!attempts[row.job_id] || attempts[row.job_id].state === 'loading'" class="muted attempts-status">Loading…</p>
                      <div v-else-if="attempts[row.job_id].state === 'error'" class="notice error attempts-error" role="alert">
                        <p>Couldn't load the attempts: {{ attempts[row.job_id].error }}.</p>
                        <button type="button" @click="loadAttempts(row.job_id)">Try again</button>
                      </div>
                      <p v-else-if="!attempts[row.job_id].items.length" class="muted attempts-status">No auto-apply attempts for this role.</p>
                      <ul v-else class="attempt-list">
                        <li v-for="a in attempts[row.job_id].items" :key="a.id" class="attempt-item" :data-kind="a.kind">
                          <div class="attempt-head">
                            <span class="at" :title="exactTime(a.queued_at)">{{ when(a.queued_at) }}</span>
                            <span class="attempt-mode">{{ modeLabel(a.mode) }}</span>
                            <span class="pill attempt" :data-kind="a.kind">{{ attemptLabel(a.kind, a.mode) }}</span>
                          </div>
                          <p v-if="a.text" class="attempt-text">{{ a.text }}</p>
                          <p v-if="a.hint" class="attempt-hint muted">{{ a.hint }}</p>
                          <button v-if="a.kind === 'needs_input'" type="button" class="link attempt-answer" @click="openProfile('details')">
                            Answer in Application details
                          </button>
                        </li>
                      </ul>
                    </section>
                  </template>
                </JobDetail>
              </div>
            </ApplicationRow>
          </ul>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.page-controls .search { width: 16rem; max-width: 100%; }

/* The stage tabs: underline tabs, each a filter with its count and, while a row is
   dragged, a drop target (.ui-drop[data-drop]). */
.stages {
  display: flex;
  gap: var(--space-1);
  margin-bottom: var(--space-4);
  overflow-x: auto;
  border-bottom: 1px solid var(--border);
  scrollbar-width: none;
}
.stages::-webkit-scrollbar { display: none; }
.stage {
  flex: 0 0 auto;
  gap: var(--space-2);
  min-height: 2.5rem;
  padding: 0 var(--space-3);
  background: transparent;
  border: 0;
  border-bottom: 2px solid transparent;
  border-radius: var(--radius-sm) var(--radius-sm) 0 0;
  box-shadow: none;
  color: var(--text-2);
}
.stage:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
.stage.active { border-bottom-color: var(--accent); color: var(--text); font-weight: var(--weight-semibold); }
.stage-n {
  min-width: 1.6em; padding: 0 0.35em; border-radius: var(--radius-pill); text-align: center;
  font-size: var(--text-xs); line-height: 1.6; color: var(--muted); background: var(--surface-2);
}
.stage.active .stage-n { color: var(--text-2); background: var(--surface-3); }
.stage-n.zero { background: transparent; }

.groups { display: grid; gap: var(--space-3); }
/* A card per company; its rows run to the card's edges. */
.company-group { padding: 0; }
.group-head {
  display: flex; align-items: center; gap: var(--space-2);
  padding: var(--space-3) var(--space-4);
  border-bottom: 1px solid var(--border);
}
.group-head :deep(.mark) { margin-right: var(--space-1); }
.group-name { margin: 0; font-size: var(--text-md); font-weight: var(--weight-bold); line-height: var(--leading-tight); }
.group-sep, .group-n { color: var(--muted); font-size: var(--text-sm); }

.app-rows { list-style: none; margin: 0; padding: 0; }

/* Under a row: the note, its editor, the remove question, history and the posting. */
.notes { margin: var(--space-1) 0 0; color: var(--text-2); font-size: var(--text-sm); white-space: pre-line; text-wrap: pretty; }
.note-form { display: grid; gap: var(--space-2); margin-top: var(--space-2); max-width: 40rem; }
.note-input {
  width: 100%; resize: vertical; padding: var(--space-2) var(--space-3);
  font: inherit; font-size: var(--text-sm); color: var(--text);
  background: var(--surface); border: 1px solid var(--control-border, var(--border-strong)); border-radius: var(--radius);
}
.note-input:focus-visible {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent);
}
.note-actions { display: flex; gap: var(--space-2); }
.remove-ask { display: flex; flex-wrap: wrap; align-items: center; gap: 0 var(--space-2); margin-top: var(--space-1); font-size: var(--text-xs); }
.remove-q { color: var(--text-2); }
.remove-ask .remove-yes, .remove-ask .remove-keep { display: inline-flex; align-items: center; min-height: 2rem; padding: 0 var(--space-1); font-size: var(--text-xs); font-weight: 600; }
.remove-ask .remove-yes { color: var(--danger); }

/* The posting under its row, as wide as the row; min-width 0 so a long word wraps. */
.app-detail {
  min-width: 0;
  margin-top: var(--space-3);
  padding: var(--space-4);
  background: var(--surface-2);
  border-radius: var(--radius);
}
.app-detail :deep(.detail-title) { font-size: var(--text-lg); overflow-wrap: anywhere; }
/* JobDetail's scoped heading style does not reach slot content, so this repeats it. */
.attempts { margin-top: var(--space-5); padding-top: var(--space-4); border-top: 1px solid var(--border); }
.attempts h4 { margin: 0 0 var(--space-2); font-size: var(--text-sm); font-weight: var(--weight-bold); color: var(--text-2); }
.attempts-status { margin: 0; font-size: var(--text-sm); }
.attempts-error { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-2); }
.attempts-error p { min-width: 0; margin: 0; overflow-wrap: anywhere; }
.attempt-list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-3); }
.attempt-item { min-width: 0; font-size: var(--text-sm); }
.attempt-head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-3); }
.attempt-mode { color: var(--text-2); font-weight: 600; }
.attempt { color: var(--text-2); background: var(--surface-3); }
.attempt[data-kind='sent'] { color: var(--ok); background: var(--ok-soft); }
.attempt[data-kind='dry_run'], .attempt[data-kind='unconfirmed'], .attempt[data-kind='needs_input'] { color: var(--warn); background: var(--warn-soft); }
.attempt[data-kind='stopped'] { color: var(--danger); background: var(--danger-soft); }
.attempt-text, .attempt-hint { margin: 2px 0 0; overflow-wrap: anywhere; text-wrap: pretty; }
.attempt-answer { margin-top: 2px; font-size: var(--text-sm); }

.history { margin-top: var(--space-2); font-size: var(--text-sm); }
.history summary { cursor: pointer; color: var(--muted); width: max-content; }
.history summary .num { font-size: var(--text-xs); }
.timeline { list-style: none; margin: var(--space-2) 0 0; padding: 0 0 0 var(--space-3); border-left: 2px solid var(--border); }
.timeline li { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-3); padding: 2px 0; }
.at { color: var(--muted); font-size: var(--text-xs); white-space: nowrap; }

@media (max-width: 640px) {
  .page-controls, .page-controls .search { width: 100%; }
  .stages { scroll-snap-type: x proximity; }
  .stage { min-height: var(--touch-min); scroll-snap-align: start; }
  .group-head { padding: var(--space-3); }
  .remove-ask .remove-yes, .remove-ask .remove-keep { min-height: var(--touch-min); }
  .history summary { min-height: var(--touch-min); display: flex; align-items: center; }
}
</style>
