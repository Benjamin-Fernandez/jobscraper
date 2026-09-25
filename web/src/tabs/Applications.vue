<script setup>
// Every role with a status, grouped by status (PRD 8.5, M8-T1). Each row shows
// its app_events timeline and lets the status be changed in place. The status
// list comes from config via /api/stats, never hardcoded, so adding a status is
// a config change (M8-T2).
//
// The run selector here is this tab's own filter and starts on "all runs": an
// application outlives the run that found it, so picking a run in the Inbox
// must not hide applications from other runs (M12-T1).
import { computed, onMounted, ref } from 'vue'
import { describeError, getApplications, getStats, setApplicationStatus } from '../api.js'
import { plural, safeUrl, when } from '../format.js'
import { tabEmits, tabProps } from '../shell.js'
import RunSelector from '../components/RunSelector.vue'
import TabLoading from '../components/TabLoading.vue'

defineProps(tabProps)
const emit = defineEmits(tabEmits)

const rows = ref([])
const statuses = ref([])
const loading = ref(true)
const error = ref('')
const saving = ref('')
const runFilter = ref('all')

const shown = computed(() => (runFilter.value === 'all'
  ? rows.value
  : rows.value.filter(r => r.run_no === runFilter.value)))

// Groups in config order; a status config no longer lists goes last, not missing.
const groups = computed(() => {
  const order = [...statuses.value]
  for (const r of shown.value) if (!order.includes(r.status)) order.push(r.status)
  return order
    .map(status => ({ status, rows: shown.value.filter(r => r.status === status) }))
    .filter(g => g.rows.length)
})

// A row's own status stays selectable even if config dropped it.
function optionsFor(row) {
  return statuses.value.includes(row.status) ? statuses.value : [...statuses.value, row.status]
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
    <div class="toolbar">
      <RunSelector :runs="runs" :model-value="runFilter" @update:model-value="v => { runFilter = v }" />
      <p v-if="!loading && rows.length" class="count">{{ plural(shown.length, 'application') }}</p>
    </div>

    <div v-if="error" class="notice error" role="alert">
      <p>{{ error }}</p>
      <button type="button" @click="retry">Try again</button>
    </div>
    <TabLoading v-if="loading" :rows="3" />
    <div v-else-if="!rows.length && !error" class="empty">
      <p class="empty-title">Nothing tracked yet.</p>
      <p class="muted">Mark a role applied in the Inbox and it appears here.</p>
    </div>
    <div v-else-if="!shown.length && !error" class="empty">
      <p class="empty-title">No applications from this run.</p>
    </div>

    <section v-for="group in groups" :key="group.status" class="group" :data-status="group.status">
      <h2>{{ group.status }} <span class="n">{{ group.rows.length }}</span></h2>
      <table>
        <thead>
          <tr><th scope="col">Role</th><th scope="col">Status</th><th scope="col">History</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in group.rows" :key="row.job_id" :data-job="row.job_id">
            <td class="role">
              <a v-if="safeUrl(row.url)" :href="safeUrl(row.url)" target="_blank" rel="noopener noreferrer">
                {{ row.company ?? '?' }} · {{ row.role ?? row.job_id }}
              </a>
              <span v-else>{{ row.company ?? '?' }} · {{ row.role ?? row.job_id }}</span>
              <div v-if="row.notes" class="notes">{{ row.notes }}</div>
            </td>
            <td>
              <select
                :aria-label="`Status of ${row.company ?? row.job_id}`"
                :value="row.status"
                :disabled="saving === row.job_id"
                @change="change(row, $event.target.value)"
              >
                <option v-for="s in optionsFor(row)" :key="s" :value="s">{{ s }}</option>
              </select>
            </td>
            <td>
              <ol class="timeline">
                <li v-for="e in row.events" :key="e.id">
                  <span class="to">{{ e.to_status }}</span>
                  <span class="at">{{ when(e.at) }}</span>
                </li>
              </ol>
            </td>
          </tr>
        </tbody>
      </table>
    </section>
  </section>
</template>

<style scoped>
.toolbar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.5rem 1rem; margin-bottom: 0.75rem; }
.count { color: var(--muted); margin: 0; }
.group { margin-bottom: 1.5rem; }
h2 { font-size: 0.95rem; text-transform: capitalize; margin: 0 0 0.4rem; }
.n { color: var(--muted); font-weight: 400; }
table { width: 100%; border-collapse: collapse; }
th { text-align: left; font-weight: 500; color: var(--muted); font-size: 0.8rem; border-bottom: 1px solid var(--border); padding: 0.3rem 0.4rem; }
td { vertical-align: top; border-bottom: 1px solid var(--border); padding: 0.5rem 0.4rem; }
.role a { text-decoration: none; }
.notes { color: var(--muted); font-size: 0.85rem; }
.timeline { list-style: none; margin: 0; padding: 0; font-size: 0.85rem; }
.timeline li { display: flex; gap: 0.5rem; }
.at { color: var(--muted); }
@media (max-width: 600px) {
  thead { display: none; }
  tr, td { display: block; border: none; padding: 0.2rem 0; }
  tr { border-bottom: 1px solid var(--border); padding: 0.5rem 0; }
}
</style>
