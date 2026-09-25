<script setup>
// Start a run, watch it, cancel it, and see every run so far (M12-T2). The run
// itself is the CLI in a child process on the server (M11-T3); this tab only
// asks for it and reads its log. When a run ends, the shell reloads the run list
// and the shortlist, so the Inbox shows what the run found.
import { computed, onMounted, ref, watch } from 'vue'
import { ApiError, cancelJob, describeError, getSettings, startRun } from '../api.js'
import { useJob } from '../composables/useJob.js'
import { shortDate } from '../format.js'
import { tabEmits, tabProps } from '../shell.js'
import JobStatus from '../components/JobStatus.vue'
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
const ready = ref(false)

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

onMounted(async () => {
  await Promise.all([loadSettings(), refresh()])
  ready.value = true
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
          {{ cancelling ? 'Cancelling…' : busyKind === 'profile' ? 'Cancel profile refresh' : 'Cancel run' }}
        </button>
      </div>
    </form>

    <p v-if="settingsError" class="notice error" role="alert">Could not read the saved setting: {{ settingsError }}</p>
    <p v-if="actionError" class="notice error" role="alert">{{ actionError }}</p>

    <h2 class="section-title">Current job</h2>
    <div class="current">
      <TabLoading v-if="!ready" :rows="1" />
      <p v-else-if="jobError && !job" class="notice error" role="alert">Could not read the current job: {{ jobError }}</p>
      <JobStatus v-else :job="job" title="Run log" />
    </div>

    <h2 class="section-title">Run history</h2>
    <TabLoading v-if="loading && !runs.length" :rows="2" />
    <div v-else-if="!runs.length" class="empty">
      <p class="empty-title">No runs yet.</p>
      <p class="muted">Start one above; it appears here when it finishes.</p>
    </div>
    <div v-else class="table-wrap">
      <table class="history">
        <thead>
          <tr>
            <th scope="col">Run</th>
            <th scope="col">Date</th>
            <th scope="col" class="num">Companies</th>
            <th scope="col" class="num">Postings</th>
            <th scope="col" class="num">Accepted</th>
            <th scope="col">Status</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in runs" :key="r.run_no" :data-run="r.run_no">
            <td>{{ r.run_no }}</td>
            <td>{{ runDate(r) }}</td>
            <td class="num">{{ count(r, 'companies', 'companies_due') }}</td>
            <td class="num">{{ count(r, 'postings', 'postings_seen') }}</td>
            <td class="num">{{ r.accepted ?? '—' }}</td>
            <td><span class="pill" :data-status="r.status">{{ r.status ?? '—' }}</span></td>
          </tr>
        </tbody>
      </table>
    </div>
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
</style>
