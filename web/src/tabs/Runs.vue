<script setup>
// Start a run, watch it, cancel it, and see every run so far (M12-T2). The run
// itself is the CLI in a child process on the server (M11-T3); this tab only
// asks for it and reads its log. When a run ends, the shell reloads the run list
// and the shortlist, so the Inbox shows what the run found.
//
// The run history is also the "Choose runs…" picker (M15): select any runs and
// show their roles together in the Inbox. A run that accepted nothing says
// "0" matches and has nothing to select. Q-118 LC: the start card (a segmented
// count control, a Dry run switch, a button that carries the count), a history
// table with a styled checkbox column and Shift-click ranges, and a bulk bar
// that appears only while something is selected.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError, cancelJob, describeError, getSettings, startRun } from '../api.js'
import { useJob } from '../composables/useJob.js'
import { requestCompanyFilter } from '../companyFilter.js'
import { ago, duration, plural, shortDate, utcMs, when } from '../format.js'
import {
  asList, matchLabel, num, runStatusIcon, runStatusLabel, runStatusNote, runStatusTitle, runStatusTone,
  takePickerRequest,
} from '../runs.js'
import { tabEmits, tabProps } from '../shell.js'
import ApplyQueuePanel from '../components/ApplyQueuePanel.vue'
import CountPicker from '../components/CountPicker.vue'
import Icon from '../components/Icon.vue'
import Switch from '../ui/Switch.vue'

const props = defineProps(tabProps)
const emit = defineEmits(tabEmits)

const settings = ref(null)
const settingsError = ref('')
const batch = ref('')
const dryRun = ref(false)
const starting = ref(false)
const cancelling = ref(false)
const actionError = ref('')

const { job, error: jobError, running, refresh, track } = useJob({
  kind: 'run',
  onFinish: () => emit('changed', { runs: true }),
})

const ORPHANED = 'This job cannot be cancelled from here: it was started before the web app last '
  + 'restarted, so the web app no longer controls it. It shows as running until it ends. To stop '
  + 'it sooner, end its "python -m jobscraper" process on this machine.'

// 0 before the first sync: then the server, not this form, says what is wrong.
const max = computed(() => settings.value?.enabled_companies ?? null)

// Empty is allowed: the server then uses the saved setting (M11).
const batchError = computed(() => {
  const n = batch.value
  if (n === '' || n === null) return ''
  if (!Number.isInteger(n) || n < 1) return 'Enter a whole number, 1 or more.'
  if (max.value && n > max.value) return `At most ${num(max.value)} - that is every enabled company.`
  return ''
})

// ---- the auto-apply queue (Q-120 U2) ----
// The panel polls the queue and tells us who holds the job slot, so there is no second
// poller here. While the auto-apply worker holds it, a search run can still be asked for:
// the server defers it until the current application finishes ("Run after this
// application"). An older server has no queue, reports 'free', and nothing changes.
const queueSlot = ref('free')
const queueRunPending = ref(false)
const deferred = ref(false)
const applyHolds = computed(() => queueSlot.value === 'apply')
const DEFERRED = 'The search run starts when the current application finishes.'
const APPLY_BUSY = 'Auto-apply is busy (it may be keeping a dry-run form open). Pause the queue in Runs to free it.'
const deferredShown = computed(() => queueRunPending.value || (deferred.value && applyHolds.value))

function onQueueStatus(status) {
  queueSlot.value = status?.slot ?? 'free'
  queueRunPending.value = Boolean(status?.runPending)
}
watch(applyHolds, on => { if (!on) deferred.value = false })

// The job is "in the way" of a new run unless it is the apply worker, which defers it.
const busyKind = computed(() => (running.value ? job.value.kind : null))
const blocked = computed(() => running.value && !applyHolds.value)
const BUSY = { run: 'A run', profile: 'A profile refresh', titles: 'A title recommendation', companies: 'A company search' }
const busyLabel = computed(() => BUSY[busyKind.value] ?? 'A job')
const canStart = computed(() => !blocked.value && !starting.value && !batchError.value && !queueRunPending.value)

async function loadSettings() {
  try {
    settings.value = await getSettings()
    if (batch.value === '') batch.value = settings.value.batch_size
  } catch (e) {
    settingsError.value = describeError(e)
  }
}

async function start() {
  if (!canStart.value) return
  actionError.value = ''
  starting.value = true
  try {
    const started = await startRun({
      batch_size: batch.value === '' ? undefined : batch.value,
      dry_run: dryRun.value,
    })
    if (started?.deferred) {
      // 202 {deferred: true}: the auto-apply worker holds the slot, so no run has
      // started and nothing is tracked as a run. The panel shows the pending run.
      deferred.value = true
      window.dispatchEvent(new Event('jobscraper:apply-queue'))
      return
    }
    track(started, { started: true })
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      actionError.value = applyHolds.value || job.value?.kind === 'apply'
        ? APPLY_BUSY
        : 'A job is already running. Wait for it to finish, or cancel it.'
      refresh()
    } else {
      actionError.value = `Could not start the run: ${describeError(e)}`
    }
  } finally {
    starting.value = false
  }
}

async function cancel() {
  actionError.value = ''
  cancelling.value = true
  try {
    track(await cancelJob())
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      // 409 means the server has no job it can stop. If the job still reports
      // running, the web app was restarted under it and no longer owns it (M11).
      await refresh()
      actionError.value = running.value ? ORPHANED : 'Nothing is running any more.'
    } else {
      actionError.value = `Could not cancel: ${describeError(e)}`
      refresh()
    }
  } finally {
    cancelling.value = false
  }
}

// Once the job that blocked a start has ended, its message is stale.
watch(() => job.value?.state, (now, before) => {
  if (before === 'running' && now !== 'running') actionError.value = ''
})

// An unknown figure is an empty cell, not a dash (Q-118 B2.3.2).
function count(run, field, statsKey) {
  const v = run[field] ?? run.stats?.[statsKey]
  return v === null || v === undefined ? '' : num(v)
}

const runDate = run => shortDate(run.finished_at || run.started_at) || ''

function seconds(run) {
  const a = utcMs(run.started_at); const b = utcMs(run.finished_at)
  return a === null || b === null || b < a ? null : (b - a) / 1000
}
const runTook = run => duration(seconds(run)) || ''

// ---- how long a run takes: the pace of the last few real runs ----
// Seconds per company over up to five recent successful runs that fetched
// something. Runs differ (the AI reads more on some), so it is "about".
const pace = computed(() => {
  let secs = 0; let companies = 0; let used = 0
  for (const r of props.runs) {
    const due = Number(r.stats?.companies_due) || 0
    const took = seconds(r)
    if (r.status !== 'ok' || !due || took === null) continue
    secs += took; companies += due
    if (++used === 5) break
  }
  return companies ? secs / companies : null
})
const estimate = computed(() => {
  const n = batch.value
  if (!pace.value || batchError.value || !Number.isInteger(n)) return ''
  return duration(Math.max(60, n * pace.value))
})

// The start button says how many companies it will check; while the auto-apply
// worker holds the slot it says the run waits for the current application (Q-120 U2).
const startLabel = computed(() => {
  if (starting.value) return 'Starting…'
  if (applyHolds.value) return 'Run after this application'
  const n = batch.value
  if (!Number.isInteger(n) || n < 1 || batchError.value) return dryRun.value ? 'Start dry run' : 'Start run'
  const companies = plural(n, 'company', 'companies')
  if (dryRun.value) return `Start dry run (${companies})`
  return max.value && n === max.value ? `Check all ${companies}` : `Check ${companies}`
})

// While a job runs: how long it has been going, ticking once a second.
const now = ref(Date.now())
let clock = null
watch(running, on => {
  clearInterval(clock)
  if (on) {
    now.value = Date.now()
    clock = setInterval(() => { now.value = Date.now() }, 1000)
  }
}, { immediate: true })
onBeforeUnmount(() => clearInterval(clock))
const elapsed = computed(() => {
  const t = utcMs(job.value?.started_at)
  return running.value && t !== null ? duration(Math.max(0, (now.value - t) / 1000)) : ''
})

const lastRun = computed(() => props.runs.find(r => r.finished_at) ?? null)

// The failed count is red only when the run itself broke.
const HARD = ['failed', 'aborted_unhealthy']
const failedTone = r => (HARD.includes(r.status) ? 'hard' : 'partial')
// The Companies tab lists who fails now, not who failed in that run: say so.
const failedText = r =>
  `${plural(Number(r.stats.companies_failed), 'company', 'companies')} could not be read in this run. The Companies tab lists the ones that fail now.`

// "N failed" in the history: the Companies tab's Failed list says which and why.
function showFailed() {
  requestCompanyFilter('failed')
  window.location.hash = '#/companies'
}

// ---- the picker (M15) ----
const picked = ref(new Set(asList(props.run)))
watch(() => props.run, v => { picked.value = new Set(asList(v)) })

const pickedMatches = computed(() => props.runs
  .filter(r => picked.value.has(r.run_no))
  .reduce((n, r) => n + (Number(r.accepted) || 0), 0))

// A run with nothing accepted has nothing to show, so it cannot be selected.
const selectable = computed(() => props.runs.filter(r => Number(r.accepted) > 0).map(r => r.run_no))
const selectedCount = computed(() => selectable.value.filter(n => picked.value.has(n)).length)
const allSelected = computed(() => selectable.value.length > 0 && selectedCount.value === selectable.value.length)
const someSelected = computed(() => selectedCount.value > 0 && !allSelected.value)

// Shift-click selects the rows between the last one clicked and this one (rows
// that can be selected only). `click` comes before `change`, so the click
// records the key and the change uses it; setValue() in a test is a bare change.
const lastPicked = ref(null)
let shiftHeld = false
const noteShift = event => { shiftHeld = event.shiftKey === true }
function onPick(event, run) {
  const on = event.target.checked
  const next = new Set(picked.value)
  const range = shiftHeld && lastPicked.value !== null && lastPicked.value !== run.run_no
  shiftHeld = false
  if (range) {
    const order = props.runs.map(r => r.run_no)
    const a = order.indexOf(lastPicked.value)
    const b = order.indexOf(run.run_no)
    const [lo, hi] = a < 0 || a > b ? [b, a < 0 ? b : a] : [a, b]
    for (const r of props.runs.slice(lo, hi + 1)) {
      if (!Number(r.accepted)) continue
      if (on) next.add(r.run_no)
      else next.delete(r.run_no)
    }
  } else if (on) next.add(run.run_no)
  else next.delete(run.run_no)
  picked.value = next
  lastPicked.value = run.run_no
}

function togglePage() {
  const next = new Set(picked.value)
  for (const n of selectable.value) {
    if (allSelected.value) next.delete(n)
    else next.add(n)
  }
  picked.value = next
}

const tableEl = ref(null)
// Clearing leaves the keyboard where the list is, not on a button that just vanished.
async function clearPicked() {
  picked.value = new Set()
  lastPicked.value = null
  await nextTick()
  tableEl.value?.querySelector('tbody input[type="checkbox"]:not(:disabled)')?.focus()
}

// Newest first, whatever order they were selected in.
function showPicked() {
  const list = props.runs.map(r => r.run_no).filter(n => picked.value.has(n))
  if (!list.length) return
  emit('select-run', list)
  window.location.hash = '#/inbox'
}

const pickerEl = ref(null)

onMounted(async () => {
  // Sent here by "Choose runs…": go straight to the history.
  if (takePickerRequest()) {
    await nextTick()
    pickerEl.value?.scrollIntoView?.({ block: 'start' })
    pickerEl.value?.focus?.({ preventScroll: true })
  }
  await Promise.all([loadSettings(), refresh()])
})
</script>

<template>
  <section class="runs">
    <header class="page-head">
      <div>
        <h2 class="page-title">Runs</h2>
        <p class="page-sub">A run checks your companies' job boards and puts the roles that fit you in your Inbox.</p>
      </div>
    </header>

    <div class="runs-top">
      <!-- The auto-apply queue (Q-120 U2). It renders nothing on a server without the queue. -->
      <ApplyQueuePanel class="runs-queue ui-card" @status="onQueueStatus" @changed="refresh" />
      <form class="start ui-card" novalidate @submit.prevent="start">
        <header class="ui-card-head">
          <h3 class="ui-card-title">Start a run</h3>
        </header>

        <div class="start-body">
          <div class="start-count">
            <p class="field-label">Companies this run</p>
            <CountPicker
              v-model="batch"
              input-id="run-batch"
              label="Companies this run"
              custom="segment"
              custom-label="Number of companies"
              :max="max"
              :placeholder="settings ? String(settings.batch_size) : 'default'"
              :invalid="Boolean(batchError)"
              describedby="run-batch-hint"
              :disabled="blocked"
            />
            <p id="run-batch-hint" class="hint" :class="{ invalid: batchError }">
              <template v-if="batchError">{{ batchError }}</template>
              <template v-else-if="settings && !settings.enabled_companies">
                No companies are enabled yet - sync the watchlist first.
              </template>
              <template v-else-if="settings && Number.isInteger(batch)">
                {{ num(batch) }} of {{ num(settings.enabled_companies) }} companies<template v-if="estimate"> · about {{ estimate }}</template>.
                Only companies that are due are checked.
              </template>
              <template v-else-if="settings">
                Uses your saved setting: {{ num(settings.batch_size) }} of {{ num(settings.enabled_companies) }} companies.
              </template>
              <template v-else>Leave empty to use the saved setting.</template>
            </p>
          </div>

          <div class="start-go">
            <Switch
              v-model="dryRun"
              label="Dry run"
              description="Fetch and report; save nothing."
              :disabled="blocked"
            />
            <button type="submit" class="primary start-run" :disabled="!canStart">{{ startLabel }}</button>
          </div>
        </div>

        <!-- The job's log lives on the Developer tab (M16); here, one line. -->
        <footer v-if="settingsError || actionError || deferredShown || blocked || (jobError && !job)" class="start-foot">
          <p v-if="settingsError" class="notice error" role="alert">Could not read the saved setting: {{ settingsError }}</p>
          <p v-if="actionError" class="notice error" role="alert">{{ actionError }}</p>
          <p v-if="deferredShown" class="notice ok run-deferred" role="status">{{ DEFERRED }}</p>
          <div v-if="blocked" class="busy-row">
            <p class="notice warn run-busy" role="status">
              <span class="spinner" aria-hidden="true" />
              <span>
                {{ busyLabel }} in progress<template v-if="elapsed"> · {{ elapsed }} so far</template>.
                <a class="text-link" href="#/developer">Follow its log on the Developer tab</a>.
              </span>
            </p>
            <button type="button" class="cancel" :disabled="cancelling" @click="cancel">
              {{ cancelling ? 'Cancelling…' : busyKind === 'run' ? 'Cancel run' : `Cancel ${busyLabel.toLowerCase().replace(/^an? /, '')}` }}
            </button>
          </div>
          <p v-else-if="jobError && !job" class="notice error" role="alert">Could not read the current job: {{ jobError }}</p>
        </footer>
      </form>
    </div>

    <section
      id="choose-runs"
      ref="pickerEl"
      class="history-card ui-card"
      tabindex="-1"
      aria-labelledby="runs-history-title"
    >
      <header class="ui-card-head">
        <h3 id="runs-history-title" class="ui-card-title">Run history</h3>
        <div v-if="lastRun" class="ui-card-actions last-run">
          <span class="muted">
            Last run {{ ago(lastRun.finished_at, now) }}<template v-if="lastRun.status && lastRun.status !== 'ok'">, {{ runStatusLabel(lastRun.status) }}</template>
            · {{ matchLabel(lastRun.accepted) }}
          </span>
          <a v-if="lastRun.accepted" class="text-link" href="#/inbox">See them in the Inbox</a>
        </div>
      </header>
      <p v-if="lastRun && runStatusNote(lastRun.status)" class="muted run-note">{{ runStatusNote(lastRun.status) }}</p>

      <div v-if="loading && !runs.length" class="history-skeleton" role="status" aria-busy="true">
        <span class="visually-hidden">Loading…</span>
        <span v-for="n in 3" :key="n" class="ui-skeleton" aria-hidden="true" />
      </div>
      <!-- A failed load is not "no runs yet" (Q-75 G20); Try again reloads the list. -->
      <div v-else-if="!runs.length && runsError" class="notice error runs-error" role="alert">
        <p>Could not load your run history: {{ runsError }}</p>
        <button type="button" @click="emit('changed', { runs: true })">Try again</button>
      </div>
      <div v-else-if="!runs.length" class="empty">
        <p class="empty-title">No runs yet.</p>
        <p class="muted">Start one above; it appears here when it finishes.</p>
      </div>
      <div v-else class="table-wrap">
        <table ref="tableEl" class="history ui-table" :class="{ 'has-picked': picked.size > 0 }" data-stack>
          <thead>
            <tr>
              <th scope="col" class="col-select">
                <label class="ui-check">
                  <input
                    type="checkbox"
                    :checked="allSelected"
                    :indeterminate="someSelected"
                    :disabled="!selectable.length"
                    @change="togglePage"
                  >
                  <span class="ui-check-box" aria-hidden="true" />
                  <span class="visually-hidden">Select every run with matches</span>
                </label>
              </th>
              <th scope="col">Run</th>
              <th scope="col">Date</th>
              <th scope="col" class="col-num">Companies</th>
              <th scope="col" class="col-num">Postings</th>
              <th scope="col" class="col-num">Matches</th>
              <th scope="col" class="col-num">Took</th>
              <th scope="col" class="col-num">Failed</th>
              <th scope="col" class="col-action">Status</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="r in runs"
              :key="r.run_no"
              :data-run="r.run_no"
              :class="{ picked: picked.has(r.run_no) }"
              :aria-selected="picked.has(r.run_no) ? 'true' : 'false'"
            >
              <td class="col-select">
                <label class="ui-check" :title="r.accepted ? undefined : 'This run found 0 matches'">
                  <input
                    type="checkbox"
                    :checked="picked.has(r.run_no)"
                    :disabled="!r.accepted"
                    :title="r.accepted ? undefined : 'This run found 0 matches'"
                    @click="noteShift"
                    @change="onPick($event, r)"
                  >
                  <span class="ui-check-box" aria-hidden="true" />
                  <span class="visually-hidden">Select run {{ r.run_no }}</span>
                </label>
              </td>
              <td class="run-cell">{{ r.run_no }}</td>
              <td data-label="Date" :class="{ 'is-empty': !runDate(r) }" :title="when(r.finished_at || r.started_at)">{{ runDate(r) }}</td>
              <td data-label="Companies" class="col-num" :class="{ 'is-empty': !count(r, 'companies', 'companies_due') }">{{ count(r, 'companies', 'companies_due') }}</td>
              <td data-label="Postings" class="col-num" :class="{ 'is-empty': !count(r, 'postings', 'postings_seen') }">{{ count(r, 'postings', 'postings_seen') }}</td>
              <td data-label="Matches" class="col-num matches">{{ num(Number(r.accepted) || 0) }}</td>
              <td data-label="Took" class="col-num took" :class="{ 'is-empty': !runTook(r) }">{{ runTook(r) }}</td>
              <td data-label="Failed" class="col-num failed" :class="{ 'is-empty': r.stats?.companies_failed == null }">
                <button
                  v-if="Number(r.stats?.companies_failed) > 0"
                  type="button"
                  :class="['ghost', 'failed-link', failedTone(r)]"
                  :title="failedText(r)"
                  :aria-label="failedText(r)"
                  @click="showFailed"
                >{{ num(r.stats.companies_failed) }}</button>
                <template v-else-if="r.stats?.companies_failed != null">{{ num(r.stats.companies_failed) }}</template>
              </td>
              <td class="col-action status">
                <span
                  v-if="runStatusTitle(r.status)"
                  class="ui-badge"
                  :data-tone="runStatusTone(r.status)"
                  :title="runStatusNote(r.status) || undefined"
                >
                  <Icon v-if="runStatusIcon(r.status)" :name="runStatusIcon(r.status)" :size="12" />
                  {{ runStatusTitle(r.status) }}
                </span>
                <span v-if="runStatusNote(r.status)" class="visually-hidden">. {{ runStatusNote(r.status) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Only while something is selected; it does not take focus when it appears. -->
    <div v-if="picked.size" class="ui-bulkbar" role="region" aria-label="Selected runs">
      <p class="bulk-text">
        <strong>{{ plural(picked.size, 'run') }} selected</strong>
        <span class="muted"> · {{ matchLabel(pickedMatches) }}</span>
      </p>
      <div class="bulk-actions">
        <button type="button" class="ghost clear-picked" @click="clearPicked">Clear selection</button>
        <button type="button" class="primary show-picked" @click="showPicked">Show in Inbox</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* ---- the top area: an optional queue panel (Q-120 U2) beside the start card ---- */
.runs-top {
  display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-5);
  align-items: start; margin-bottom: var(--space-5);
}
@media (min-width: 1100px) {
  .runs-top:has(> .runs-queue) { grid-template-columns: minmax(0, 7fr) minmax(0, 5fr); }
}

/* ---- start card ---- */
.start-body { display: grid; gap: var(--space-4); }
/* No queue panel: the card spans the row, the count control left, the switch and button right. */
@media (min-width: 800px) {
  .runs-top:not(:has(> .runs-queue)) .start-body {
    grid-template-columns: minmax(0, 3fr) minmax(0, 2fr);
    column-gap: var(--space-7); align-items: start;
  }
}
.field-label { margin: 0 0 var(--space-2); font-size: var(--text-sm); font-weight: var(--weight-semibold); }
.hint { margin: var(--space-3) 0 0; font-size: var(--text-sm); color: var(--muted); }
.hint.invalid { color: var(--danger); }
.start-go { display: grid; gap: var(--space-3); align-content: start; }
.start-go :deep(.ui-switch) { padding-inline: 0; border-radius: 0; }
.start-go :deep(.ui-switch:hover:not(:disabled)) { background: transparent; }
.start-run { width: 100%; min-height: 2.75rem; }
.start-foot { display: grid; gap: var(--space-3); margin-top: var(--space-4); padding-top: var(--space-4); border-top: 1px solid var(--border); }
.start-foot .notice { margin: 0; }
.busy-row { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-3); }
.busy-row .notice { flex: 1 1 18rem; }
.cancel { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 45%, var(--border-strong)); }
.run-busy { display: flex; align-items: flex-start; gap: var(--space-2); }
.spinner {
  width: 0.9rem; height: 0.9rem; flex: none; margin-top: 0.2rem; border-radius: 50%;
  border: 2px solid currentColor; border-right-color: transparent;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* ---- history card ---- */
.history-card:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
.last-run { font-size: var(--text-sm); gap: var(--space-1) var(--space-3); }
.run-note { margin: calc(-1 * var(--space-1)) 0 var(--space-3); font-size: var(--text-sm); }
.history-skeleton .ui-skeleton { height: var(--row-h); margin-bottom: var(--space-2); }
.history-card .empty { border: 0; background: var(--surface-2); }
/* The table runs to the card's edges; its first and last cells keep the card's padding. */
.table-wrap { margin-inline: calc(-1 * var(--space-4)); overflow-x: auto; }
.history th:first-child, .history td:first-child { padding-left: var(--space-3); }
.history th:last-child, .history td:last-child { padding-right: var(--space-4); }
.history td { white-space: nowrap; }
.history .run-cell { font-weight: var(--weight-semibold); font-variant-numeric: tabular-nums lining-nums; }
/* The checkboxes stay quiet until the pointer is on the row, the keyboard is in it, or a
   first run is selected (touch has no hover, so they stay as they are there). */
@media (hover: hover) {
  .history:not(.has-picked) tbody tr:not(:hover):not(:focus-within) .ui-check:has(> input:not(:disabled)) { opacity: 0.4; }
}
/* A run that broke is red; a good run with a few unreadable companies is not
   an outage, so its count is quiet (Q-70 E4, G27). */
.failed-link {
  position: relative; min-width: 1.75rem; min-height: 1.75rem; padding: 0 var(--space-2);
  margin-right: calc(-1 * var(--space-2)); font-variant-numeric: tabular-nums lining-nums;
}
.failed-link.hard, .failed-link.hard:hover:not(:disabled) { color: var(--danger); }
.failed-link.partial { color: var(--muted); text-decoration: underline dotted; text-underline-offset: 3px; }
.failed-link.partial:hover:not(:disabled) { color: var(--text); }

/* ---- bulk bar ---- */
.bulk-text { margin: 0; font-size: var(--text-sm); }

/* ---- phone: the foundation stacks each row; this orders it and keeps 44px targets ---- */
@media (max-width: 640px) {
  .table-wrap { overflow: visible; }
  .history th:first-child, .history td:first-child, .history th:last-child, .history td:last-child { padding: 0; }
  .history tr { padding-block: var(--space-2); }
  .history .run-cell { flex: 1 1 0; }
  .history .run-cell::before { content: 'Run '; font-weight: var(--weight-medium); color: var(--muted); }
  .history td.status { order: 1; margin-left: auto; }
  .history td[data-label] { order: 2; }
  .history td.is-empty { display: none; }
  .failed-link::after {
    content: ''; position: absolute; left: 50%; top: 50%;
    width: max(100%, var(--touch-min)); height: var(--touch-min); transform: translate(-50%, -50%);
  }
  .bulk-actions button { min-height: var(--touch-min); }
}
</style>
