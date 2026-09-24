<script setup>
// Every role with a status, across all runs, grouped by status (PRD 8.5, M8-T1).
// Each row shows its app_events timeline and lets the status be changed in
// place. The status list comes from config via /api/stats, never hardcoded, so
// adding a status is a config change (M8-T2).
//
// This tab ignores the run selector on purpose: an application outlives the run
// that found it.
import { computed, onMounted, ref } from 'vue'
import { getApplications, getStats, setApplicationStatus } from '../api.js'

defineProps({
  run: { type: [Number, String], default: null },
  jobs: { type: Array, required: true },
})
const emit = defineEmits(['changed'])

const rows = ref([])
const statuses = ref([])
const loading = ref(true)
const error = ref('')
const saving = ref('')

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// "2026-09-24T08:50:05" (stored in UTC) -> "24 Sep 08:50 UTC".
function when(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/.exec(iso || '')
  if (!m) return ''
  const day = `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}`
  return m[4] ? `${day} ${m[4]}:${m[5]} UTC` : day
}

function safeUrl(url) {
  return /^https?:\/\//i.test(url || '') ? url : null
}

// Groups in config order; a status config no longer lists goes last, not missing.
const groups = computed(() => {
  const order = [...statuses.value]
  for (const r of rows.value) if (!order.includes(r.status)) order.push(r.status)
  return order
    .map(status => ({ status, rows: rows.value.filter(r => r.status === status) }))
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
    error.value = `Could not load applications: ${e.message || e}`
  } finally {
    loading.value = false
  }
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
    error.value = `Could not change ${row.company ?? row.job_id}: ${e.message || e}`
  } finally {
    saving.value = ''
  }
}

onMounted(load)
</script>

<template>
  <section class="applications">
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="loading" class="muted">Loading…</p>
    <p v-else-if="!rows.length && !error" class="muted">
      Nothing tracked yet. Mark a role applied in the Inbox and it appears here.
    </p>

    <section v-for="group in groups" :key="group.status" class="group" :data-status="group.status">
      <h2>{{ group.status }} <span class="n">{{ group.rows.length }}</span></h2>
      <table>
        <thead>
          <tr><th>Role</th><th>Status</th><th>History</th></tr>
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
.muted { color: var(--muted); }
.error { color: var(--warn); }
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
