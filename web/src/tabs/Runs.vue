<script setup>
// Start a run, watch it, cancel it, and see every run so far (M12-T2). The run
// itself is the CLI in a child process on the server (M11-T3); this tab only
// asks for it and reads its log. When a run ends, the shell reloads the run list
// and the shortlist, so the Inbox shows what the run found.
//
// The run history is also the "Choose runs…" picker (M15): tick any runs and
// show their roles together in the Inbox. A run that accepted nothing says
// "0 matches" and has nothing to tick.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { ApiError, cancelJob, describeError, getSettings, startRun } from '../api.js'
import { useJob } from '../composables/useJob.js'
import { plural, shortDate } from '../format.js'
import { asList, matchLabel, runStatusLabel, takePickerRequest } from '../runs.js'
import { tabEmits, tabProps } from '../shell.js'
import TabLoading from '../components/TabLoading.vue'

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
  if (max.value && n > max.value) return `At most ${max.value} - that is every enabled company.`
  return ''
})

const busyKind = computed(() => (running.value ? job.value.kind : null))
const BUSY = { run: 'A run', profile: 'A profile refresh', titles: 'A title recommendation', companies: 'A company search' }
const busyLabel = computed(() => BUSY[busyKind.value] ?? 'A job')
const canStart = computed(() => !running.value && !starting.value && !batchError.value)

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
    track(started, { started: true })
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      actionError.value = 'A job is already running. Wait for it to finish, or cancel it.'
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

function count(run, field, statsKey) {
  const v = run[field] ?? run.stats?.[statsKey]
  return v === null || v === undefined ? '—' : v
}

function runDate(run) {
  return shortDate(run.finished_at || run.started_at) || '—'
}

// ---- the picker (M15) ----
const picked = ref(new Set(asList(props.run)))
watch(() => props.run, v => { picked.value = new Set(asList(v)) })

const pickedMatches = computed(() => props.runs
  .filter(r => picked.value.has(r.run_no))
  .reduce((n, r) => n + (Number(r.accepted) || 0), 0))

function toggle(run) {
  const next = new Set(picked.value)
  if (next.has(run.run_no)) next.delete(run.run_no)
  else next.add(run.run_no)
  picked.value = next
}

// Newest first, whatever order they were ticked in.
function showPicked() {
  const list = props.runs.map(r => r.run_no).filter(n => picked.value.has(n))
  if (!list.length) return
  emit('select-run', list)
  window.location.hash = '#/inbox'
}

const pickerEl = ref(null)

onMounted(async () => {
  // Sent here by "Choose runs…": go straight to the picker.
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
    <h2 class="section-title">Start a run</h2>
    <form class="start" novalidate @submit.prevent="start">
      <div class="field">
        <label for="run-batch">Companies this run</label>
        <input
          id="run-batch"
          v-model.number="batch"
          type="number"
          inputmode="numeric"
          min="1"
          :max="max ?? undefined"
          :placeholder="settings ? String(settings.batch_size) : 'default'"
          :aria-invalid="batchError ? 'true' : 'false'"
          aria-describedby="run-batch-hint"
          :disabled="running"
        >
        <p id="run-batch-hint" class="hint" :class="{ invalid: batchError }">
          <template v-if="batchError">{{ batchError }}</template>
          <template v-else-if="settings && !settings.enabled_companies">
            No companies are enabled yet - sync the watchlist first.
          </template>
          <template v-else-if="settings">
            Saved setting: {{ settings.batch_size }} of {{ settings.enabled_companies }} enabled companies.
          </template>
          <template v-else>Leave empty to use the saved setting.</template>
        </p>
      </div>
      <label class="check">
        <input v-model="dryRun" type="checkbox" :disabled="running">
        Dry run <span class="muted">- fetch and report, save nothing</span>
      </label>
      <div class="buttons">
        <button type="submit" class="primary start-run" :disabled="!canStart">
          {{ starting ? 'Starting…' : dryRun ? 'Start dry run' : 'Start run' }}
        </button>
        <button
          v-if="running"
          type="button"
          class="cancel"
          :disabled="cancelling"
          @click="cancel"
        >
          {{ cancelling ? 'Cancelling…' : busyKind === 'run' ? 'Cancel run' : `Cancel ${busyLabel.toLowerCase().replace(/^an? /, '')}` }}
        </button>
      </div>
    </form>

    <p v-if="settingsError" class="notice error" role="alert">Could not read the saved setting: {{ settingsError }}</p>
    <p v-if="actionError" class="notice error" role="alert">{{ actionError }}</p>

    <!-- The job's log lives on the Developer tab (M16); here, one line. -->
    <p v-if="running" class="notice warn run-busy" role="status">
      {{ busyLabel }} in progress. <a href="#/developer">Follow its log on the Developer tab</a>.
    </p>
    <p v-else-if="jobError && !job" class="notice error" role="alert">Could not read the current job: {{ jobError }}</p>

    <h2 class="section-title">Run history</h2>
    <TabLoading v-if="loading && !runs.length" :rows="2" />
    <div v-else-if="!runs.length" class="empty">
      <p class="empty-title">No runs yet.</p>
      <p class="muted">Start one above; it appears here when it finishes.</p>
    </div>
    <template v-else>
      <div
        id="choose-runs"
        ref="pickerEl"
        class="picker surface"
        role="group"
        aria-label="Choose runs to show in the Inbox"
        tabindex="-1"
      >
        <p class="picker-text">
          <strong>Choose runs</strong> - tick any runs to see their roles together in the Inbox.
          <span class="picker-count">
            {{ picked.size ? `${plural(picked.size, 'run')} ticked · ${matchLabel(pickedMatches)}` : 'Nothing ticked.' }}
          </span>
        </p>
        <div class="picker-actions">
          <button v-if="picked.size" type="button" class="ghost clear-picked" @click="picked = new Set()">Clear</button>
          <button type="button" class="primary show-picked" :disabled="!picked.size" @click="showPicked">Show in Inbox</button>
        </div>
      </div>
      <div class="table-wrap">
        <table class="history">
          <thead>
            <tr>
              <th scope="col" class="pick"><span class="visually-hidden">Show in the Inbox</span></th>
              <th scope="col">Run</th>
              <th scope="col">Date</th>
              <th scope="col" class="num">Companies</th>
              <th scope="col" class="num">Postings</th>
              <th scope="col">Matches</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="r in runs"
              :key="r.run_no"
              :data-run="r.run_no"
              :class="{ picked: picked.has(r.run_no) }"
            >
              <td class="pick">
                <input
                  type="checkbox"
                  :checked="picked.has(r.run_no)"
                  :disabled="!r.accepted"
                  :title="r.accepted ? undefined : 'Nothing to show - this run found 0 matches'"
                  :aria-label="`Show run ${r.run_no} in the Inbox`"
                  @change="toggle(r)"
                >
              </td>
              <td>{{ r.run_no }}</td>
              <td>{{ runDate(r) }}</td>
              <td class="num">{{ count(r, 'companies', 'companies_due') }}</td>
              <td class="num">{{ count(r, 'postings', 'postings_seen') }}</td>
              <td class="matches">{{ matchLabel(r.accepted) }}</td>
              <td><span class="pill" :data-status="r.status">{{ runStatusLabel(r.status) }}</span></td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<style scoped>
.start {
  display: grid; gap: var(--space-4); max-width: 34rem;
  padding: var(--space-4); background: var(--surface);
  border: 1px solid var(--border); border-radius: var(--radius-lg); box-shadow: var(--shadow);
}
.field label { display: block; font-weight: 600; font-size: var(--text-sm); margin-bottom: var(--space-1); }
.field input { width: 8rem; }
.hint { margin: var(--space-1) 0 0; font-size: var(--text-sm); color: var(--muted); }
.hint.invalid { color: var(--danger); }
.check { display: flex; align-items: center; gap: var(--space-2); font-size: var(--text-sm); cursor: pointer; }
.buttons { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.cancel { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 45%, var(--border-strong)); }
.notice { margin-top: var(--space-4); max-width: 34rem; }
.table-wrap { overflow-x: auto; border-top: 1px solid var(--border); }
.history { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
.history th {
  text-align: left; font-weight: 500; color: var(--muted); font-size: var(--text-xs);
  text-transform: uppercase; letter-spacing: 0.06em;
  border-bottom: 1px solid var(--border); padding: var(--space-2);
}
.history td { border-bottom: 1px solid var(--border); padding: var(--space-2); white-space: nowrap; }
.history th { font-family: var(--font); }
.history td:first-child, .history td.num { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.history .num { text-align: right; }
.history .pick { width: 2.5rem; text-align: center; }
/* A 0-match run looks like every other row; its box just cannot be ticked. */
.history .pick input:disabled { opacity: 1; cursor: not-allowed; }
.history tr.picked td { background: var(--accent-soft); }
.picker {
  position: sticky; top: calc(var(--header-h) + var(--space-2)); z-index: 2;
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: var(--space-2) var(--space-4); padding: var(--space-3) var(--space-4); margin-bottom: var(--space-3);
}
.picker-text { margin: 0; font-size: var(--text-sm); }
.picker-count { display: block; color: var(--muted); }
.picker-actions { display: flex; gap: var(--space-2); }
</style>
