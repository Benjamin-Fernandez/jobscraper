<script setup>
// Applications (M13-T3): every role you have saved or applied to, grouped by
// company - the question you ask before applying again ("what have I already
// sent Grab?"). A stage strip across the top counts each stage and filters to
// it, the way LinkedIn's and Huntr's trackers show a pipeline. Each row changes
// status in place and keeps its app_events history.
//
// The status list comes from config via /api/stats, never hardcoded, so adding
// a status is a config change (M8-T2); stages.js only says how one is written.
// The run selector here is this tab's own filter and starts on "all runs": an
// application outlives the run that found it (M12-T1).
import { computed, onMounted, ref } from 'vue'
import { describeError, getApplications, getStats, setApplicationStatus } from '../api.js'
import { plural, safeUrl, shortDate, when } from '../format.js'
import { tabEmits, tabProps } from '../shell.js'
import { statusLabel } from '../stages.js'
import { runsInRange } from '../runs.js'
import CompanyMark from '../components/CompanyMark.vue'
import Icon from '../components/Icon.vue'
import RunSelector from '../components/RunSelector.vue'
import TabLoading from '../components/TabLoading.vue'

const props = defineProps(tabProps)
const emit = defineEmits(tabEmits)

const rows = ref([])
const statuses = ref([])
const loading = ref(true)
const error = ref('')
const saving = ref('')
const runFilter = ref('all')
const stage = ref('all')
const query = ref('')

const UNKNOWN = 'Unknown company'
const companyOf = row => row.company || UNKNOWN

// The run and search filters; the stage filter comes after, so the strip's
// counts always describe what the other filters leave.
const inScope = computed(() => {
  const q = query.value.trim().toLowerCase()
  const inRuns = runsInRange(props.runs, runFilter.value)   // null = every run
  return rows.value.filter(r =>
    (!inRuns || inRuns.has(r.run_no))
    && (!q || [r.company, r.role].some(v => (v || '').toLowerCase().includes(q))))
})

// Stages in config order; a status config no longer lists goes last, not missing.
const order = computed(() => {
  const list = [...statuses.value]
  for (const r of rows.value) if (!list.includes(r.status)) list.push(r.status)
  return list
})

const stages = computed(() => [
  { id: 'all', label: 'All', n: inScope.value.length },
  ...order.value.map(s => ({ id: s, label: statusLabel(s), n: inScope.value.filter(r => r.status === s).length })),
])

const shown = computed(() => (stage.value === 'all'
  ? inScope.value
  : inScope.value.filter(r => r.status === stage.value)))

// Companies A-Z; inside one, roles by stage (config order), then title.
const groups = computed(() => {
  const by = new Map()
  for (const r of shown.value) {
    const key = companyOf(r)
    if (!by.has(key)) by.set(key, [])
    by.get(key).push(r)
  }
  const rank = s => order.value.indexOf(s)
  return [...by.entries()]
    .sort(([a], [b]) => a.localeCompare(b, undefined, { sensitivity: 'base' }))
    .map(([company, list]) => ({
      company,
      rows: list.sort((x, y) => rank(x.status) - rank(y.status)
        || String(x.role || '').localeCompare(String(y.role || ''))),
    }))
})

const companyCount = computed(() => new Set(shown.value.map(companyOf)).size)

// A row's own status stays selectable even if config dropped it.
function optionsFor(row) {
  return statuses.value.includes(row.status) ? statuses.value : [...statuses.value, row.status]
}

function lastChange(row) {
  const e = row.events?.at(-1)
  return e ? `${statusLabel(e.to_status)} ${shortDate(e.at)}` : ''
}

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

async function change(row, status) {
  if (status === row.status) return
  saving.value = row.job_id
  error.value = ''
  try {
    await setApplicationStatus(row.job_id, status)
    await load()
    emit('changed')
  } catch (e) {
    error.value = `Could not change ${row.company ?? row.job_id}: ${describeError(e)}`
  } finally {
    saving.value = ''
  }
}

onMounted(load)
</script>

<template>
  <section class="applications" :aria-busy="loading ? 'true' : 'false'">
    <header class="page-head">
      <div>
        <h2 class="page-title">Applications</h2>
        <p v-if="!loading && rows.length" class="page-sub count">
          {{ plural(shown.length, 'application') }} at {{ plural(companyCount, 'company', 'companies') }}
        </p>
      </div>
      <div class="page-controls">
        <label class="search">
          <Icon name="search" />
          <span class="visually-hidden">Search applications</span>
          <input v-model="query" type="search" placeholder="Search company or role">
        </label>
        <RunSelector
          :runs="runs"
          :model-value="runFilter"
          :choosable="false"
          @update:model-value="v => { runFilter = v }"
        />
      </div>
    </header>

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
      <div class="stages" role="group" aria-label="Filter by stage">
        <button
          v-for="s in stages"
          :key="s.id"
          type="button"
          class="stage"
          :class="{ active: stage === s.id }"
          :data-status="s.id"
          :aria-pressed="stage === s.id ? 'true' : 'false'"
          @click="stage = s.id"
        >
          <span class="stage-label">{{ s.label }}</span>
          <span class="stage-n num" :class="{ zero: !s.n }">{{ s.n }}</span>
        </button>
      </div>

      <div v-if="!shown.length" class="empty">
        <p class="empty-title">Nothing here.</p>
        <p class="muted">No application matches this stage, run and search.</p>
      </div>

      <div class="groups">
        <section v-for="group in groups" :key="group.company" class="company-group surface" :data-company="group.company">
          <header class="group-head">
            <CompanyMark :name="group.company" size="sm" />
            <h3 class="group-name">{{ group.company }}</h3>
            <span class="group-n">{{ plural(group.rows.length, 'role') }}</span>
          </header>
          <ul class="app-rows">
            <li v-for="row in group.rows" :key="row.job_id" class="app-row" :data-job="row.job_id" :data-status="row.status">
              <div class="role">
                <a v-if="safeUrl(row.url)" class="role-title" :href="safeUrl(row.url)" target="_blank" rel="noopener noreferrer">
                  {{ row.role ?? row.job_id }}<Icon name="external" :size="13" />
                </a>
                <span v-else class="role-title">{{ row.role ?? row.job_id }}</span>
                <p v-if="row.notes" class="notes">{{ row.notes }}</p>
              </div>
              <span class="updated">{{ lastChange(row) }}</span>
              <label class="status-field">
                <span class="visually-hidden">Status of {{ row.company ?? row.job_id }} · {{ row.role ?? '' }}</span>
                <select
                  class="status-select"
                  :data-status="row.status"
                  :value="row.status"
                  :disabled="saving === row.job_id"
                  @change="change(row, $event.target.value)"
                >
                  <option v-for="s in optionsFor(row)" :key="s" :value="s">{{ statusLabel(s) }}</option>
                </select>
              </label>
              <details v-if="row.events && row.events.length > 1" class="history">
                <summary>History <span class="num">{{ row.events.length }}</span></summary>
                <ol class="timeline">
                  <li v-for="e in row.events" :key="e.id">
                    <span class="to pill" :data-status="e.to_status">{{ statusLabel(e.to_status) }}</span>
                    <span class="at">{{ when(e.at) }}</span>
                  </li>
                </ol>
              </details>
            </li>
          </ul>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.page-controls .search { width: 16rem; max-width: 100%; }

/* The pipeline strip: one segment per stage, each a filter with its count. */
.stages {
  display: flex;
  gap: var(--space-1);
  padding: var(--space-1);
  margin-bottom: var(--space-4);
  overflow-x: auto;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  scrollbar-width: none;
}
.stages::-webkit-scrollbar { display: none; }
.stage {
  flex: 1 0 auto;
  justify-content: space-between;
  gap: var(--space-3);
  min-height: 2.5rem;
  padding: 0 var(--space-3);
  background: transparent;
  border: 1px solid transparent;
  box-shadow: none;
  color: var(--text-2);
}
.stage:hover:not(:disabled) { background: var(--surface); }
.stage.active { background: var(--surface); border-color: var(--border); box-shadow: var(--shadow); color: var(--text); font-weight: 650; }
.stage-n { font-size: var(--text-xs); color: var(--muted); }
.stage-n.zero { opacity: 0.5; }
/* Each stage's own colour, as a bar under the active segment. */
.stage { position: relative; }
.stage::after {
  content: ''; position: absolute; left: var(--space-3); right: var(--space-3); bottom: 4px;
  height: 2px; border-radius: 2px; background: transparent;
}
.stage.active[data-status='to_apply']::after { background: var(--stage-saved); }
.stage.active[data-status='applied']::after { background: var(--stage-applied); }
.stage.active[data-status='interviewing']::after { background: var(--stage-interview); }
.stage.active[data-status='offer']::after { background: var(--stage-offer); }
.stage.active[data-status='rejected']::after { background: var(--stage-rejected); }
.stage.active[data-status='withdrawn']::after { background: var(--stage-closed); }

.groups { display: grid; gap: var(--space-3); }
.company-group { padding: var(--space-2) var(--space-4) var(--space-1); }
.group-head { display: flex; align-items: center; gap: var(--space-3); padding: var(--space-2) 0; }
.group-name { margin: 0; font-size: var(--text-md); font-weight: 650; }
.group-n { color: var(--muted); font-size: var(--text-sm); }

.app-rows { list-style: none; margin: 0; padding: 0; }
.app-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto 10.5rem;
  grid-template-areas: 'role updated status' 'history history history';
  align-items: center;
  gap: 0 var(--space-4);
  padding: var(--space-3) 0;
  border-top: 1px solid var(--border);
}
.role { grid-area: role; min-width: 0; }
.role-title {
  display: inline-flex; align-items: center; gap: var(--space-1);
  font-weight: 550; color: var(--text); text-decoration: none; overflow-wrap: anywhere;
}
a.role-title:hover { color: var(--accent); text-decoration: underline; }
a.role-title .icon { color: var(--muted); }
.notes { margin: 2px 0 0; color: var(--muted); font-size: var(--text-sm); }
.updated { grid-area: updated; color: var(--muted); font-size: var(--text-xs); white-space: nowrap; }
.status-field { grid-area: status; }

/* The status control wears its stage colour. */
.status-select {
  width: 100%;
  font-weight: 600;
  border-color: transparent;
  color: var(--stage-closed);
  background-color: var(--stage-closed-soft);
}
.status-select[data-status='to_apply'] { color: var(--stage-saved); background-color: var(--stage-saved-soft); }
.status-select[data-status='applied'] { color: var(--stage-applied); background-color: var(--stage-applied-soft); }
.status-select[data-status='interviewing'] { color: var(--stage-interview); background-color: var(--stage-interview-soft); }
.status-select[data-status='offer'] { color: var(--stage-offer); background-color: var(--stage-offer-soft); }
.status-select[data-status='rejected'] { color: var(--stage-rejected); background-color: var(--stage-rejected-soft); }
.status-select option { color: var(--text); background: var(--surface); }

.history { grid-area: history; margin-top: var(--space-2); font-size: var(--text-sm); }
.history summary { cursor: pointer; color: var(--muted); width: max-content; }
.history summary .num { font-size: var(--text-xs); }
.timeline { list-style: none; margin: var(--space-2) 0 0; padding: 0 0 0 var(--space-3); border-left: 2px solid var(--border); }
.timeline li { display: flex; align-items: center; gap: var(--space-3); padding: 2px 0; }
.at { color: var(--muted); font-family: var(--mono); font-size: var(--text-xs); white-space: nowrap; }

@media (max-width: 640px) {
  .page-controls, .page-controls .search { width: 100%; }
  .app-row {
    grid-template-columns: minmax(0, 1fr) 9rem;
    grid-template-areas: 'role status' 'updated updated' 'history history';
    gap: var(--space-1) var(--space-3);
  }
}
</style>
