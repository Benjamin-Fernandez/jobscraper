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
//
// Email updates (Q-60, F-50l-n): suggestions an email raised sit above the stage
// strip (MailSuggestions, hidden when there are none), and an event an email
// made wears a "From email" badge in History (MailEvidence) with its quote and
// Undo. Either action reloads the rows and the suggestions.
import { computed, onActivated, onMounted, ref, watch } from 'vue'
import { describeError, getApplications, getStats, setApplicationStatus, untrackApplication } from '../api.js'
import { ageLabel, isActive, lastAt, needsFollowUp, secondLine, STAGE_KEY } from '../applications.js'
import { plural, safeUrl, shortDate, when } from '../format.js'
import { tabEmits, tabProps } from '../shell.js'
import { statusLabel } from '../stages.js'
import { showToast } from '../toast.js'
import { runsInRange } from '../runs.js'
import CompanyMark from '../components/CompanyMark.vue'
import Icon from '../components/Icon.vue'
import MailEvidence from '../components/MailEvidence.vue'
import MailSuggestions from '../components/MailSuggestions.vue'
import RunSelector from '../components/RunSelector.vue'
import StatusSelect from '../components/StatusSelect.vue'
import TabLoading from '../components/TabLoading.vue'

const props = defineProps(tabProps)
const emit = defineEmits(tabEmits)

const rows = ref([])
const statuses = ref([])
const loading = ref(true)
const error = ref('')
const saving = ref('')
const runFilter = ref('all')
// The stage chip is remembered; a first visit lands on Active, so rejected and
// withdrawn roles do not crowd the list you act on (Q-70 B2, G8).
function readStage() {
  try { return window.localStorage.getItem(STAGE_KEY) || 'active' } catch { return 'active' }
}
const stage = ref(readStage())
watch(stage, v => { try { window.localStorage.setItem(STAGE_KEY, v) } catch { /* private mode */ } })
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
  { id: 'active', label: 'Active', n: inScope.value.filter(isActive).length },
  { id: 'all', label: 'All', n: inScope.value.length },
  ...order.value.map(s => ({ id: s, label: statusLabel(s), n: inScope.value.filter(r => r.status === s).length })),
])

const shown = computed(() => {
  if (stage.value === 'all') return inScope.value
  if (stage.value === 'active') return inScope.value.filter(isActive)
  return inScope.value.filter(r => r.status === stage.value)
})

// Company A-Z groups a company's roles together; Recent activity lists every
// application on its own, the latest change first.
const sort = ref('company')

// Companies A-Z; inside one, roles by stage (config order), then title.
const groups = computed(() => {
  if (sort.value === 'recent') {
    return [...shown.value]
      .sort((a, b) => String(lastAt(b)).localeCompare(String(lastAt(a))))
      .map(r => ({ company: companyOf(r), key: r.application_id ?? r.job_id, rows: [r] }))
  }
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
      key: company,
      rows: list.sort((x, y) => rank(x.status) - rank(y.status)
        || String(x.role || '').localeCompare(String(y.role || ''))),
    }))
})

const companyCount = computed(() => new Set(shown.value.map(companyOf)).size)

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
    // A remembered stage that config no longer lists falls back to Active.
    if (!stages.value.some(s => s.id === stage.value)) stage.value = 'active'
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
    // Undo is one more change, so it writes one more history event (D-101).
    showToast({
      message: `Moved to ${statusLabel(status)}: ${row.role ?? row.job_id}`,
      action: { label: 'Undo', run: () => change({ ...row, status }, before) },
    })
    // A suggestion about this application may no longer apply (superseded).
    suggestions.value?.load()
  } catch (e) {
    error.value = `Could not change ${row.company ?? row.job_id}: ${describeError(e)}`
  } finally {
    saving.value = ''
  }
}

// Only a row with a single event can be removed, so no history is lost; Undo
// puts it back as it was (Q-70 B6, G6).
async function removeRow(row) {
  error.value = ''
  try {
    await untrackApplication(row.job_id)
    await load()
    emit('changed')
    showToast({
      message: `Removed ${row.role ?? row.job_id}`,
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
    error.value = `Could not remove ${row.company ?? row.job_id}: ${describeError(e)}`
  }
}

// ---- notes: the same POST with the row's own status, so the history gets no
// new event; an empty note clears it ----

const noteFor = ref('')          // job id whose note is open for editing
const noteDraft = ref('')
const savingNote = ref(false)

function editNote(row) {
  noteFor.value = row.job_id
  noteDraft.value = row.notes || ''
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

onMounted(load)
// A cached tab coming back shows what changed meanwhile (Q-70 B9).
let shownOnce = false
onActivated(() => { if (shownOnce) load(); shownOnce = true })
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
          <input v-model="query" type="search" placeholder="Search company or role" aria-keyshortcuts="/" @keydown.esc="query ? (query = '') : $event.target.blur()">
          <kbd class="key-hint" aria-hidden="true">/</kbd>
        </label>
        <label>
          <span class="visually-hidden">Sort</span>
          <select v-model="sort" class="app-sort">
            <option value="company">Company A–Z</option>
            <option value="recent">Recent activity</option>
          </select>
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
      <MailSuggestions ref="suggestions" @changed="afterMail" />

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
        <p><button type="button" class="link clear-filters" @click="stage = 'all'; runFilter = 'all'; query = ''">Clear filters</button></p>
      </div>

      <div class="groups">
        <section v-for="group in groups" :key="group.key" class="company-group surface" :data-company="group.company">
          <header class="group-head">
            <CompanyMark :name="group.company" size="sm" />
            <h3 class="group-name">{{ group.company }}</h3>
            <span v-if="sort !== 'recent'" class="group-n">{{ plural(group.rows.length, 'role') }}</span>
          </header>
          <ul class="app-rows">
            <li v-for="row in group.rows" :key="row.application_id ?? row.job_id" class="app-row" :data-job="row.job_id" :data-status="row.status">
              <div class="role">
                <a v-if="safeUrl(row.url)" class="role-title" :href="safeUrl(row.url)" target="_blank" rel="noopener noreferrer">
                  {{ row.role ?? row.job_id }}<Icon name="external" :size="13" />
                </a>
                <span v-else class="role-title">{{ row.role ?? row.job_id }}</span>
                <span v-if="needsFollowUp(row)" class="pill follow-up">Follow up?</span>
                <p v-if="secondLine(row)" class="row-meta">{{ secondLine(row) }}</p>
                <form
                  v-if="noteFor === row.job_id"
                  class="note-form"
                  @submit.prevent="saveNote(row)"
                  @keydown.esc="noteFor = ''"
                >
                  <label class="visually-hidden" :for="`note-${row.job_id}`">Note on {{ row.company ?? row.job_id }} · {{ row.role ?? '' }}</label>
                  <textarea
                    :id="`note-${row.job_id}`"
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
                <template v-else>
                  <p v-if="row.notes" class="notes">{{ row.notes }}</p>
                  <button
                    type="button"
                    class="link note-edit"
                    :disabled="savingNote"
                    :aria-label="`${row.notes ? 'Edit note' : 'Add note'} on ${row.company ?? row.job_id} · ${row.role ?? ''}`"
                    @click="editNote(row)"
                  >
                    {{ row.notes ? 'Edit note' : 'Add note' }}
                  </button>
                  <button
                    v-if="(row.events?.length ?? 0) <= 1"
                    type="button"
                    class="link row-remove"
                    @click="removeRow(row)"
                  >
                    Remove from Applications
                  </button>
                </template>
              </div>
              <span class="updated" :title="when(lastAt(row))">{{ ageLabel(row) }}</span>
              <StatusSelect
                :model-value="row.status"
                :options="optionsFor(row)"
                :disabled="saving === row.job_id"
                :label="`Status of ${row.company ?? row.job_id} · ${row.role ?? ''}`"
                @commit="s => change(row, s)"
              />
              <details v-if="row.events && row.events.length > 1" class="history">
                <summary>History <span class="num">{{ row.events.length }}</span></summary>
                <ol class="timeline">
                  <li v-for="e in row.events" :key="e.id" :data-by="e.by ?? null">
                    <span class="to pill" :data-status="e.to_status">{{ statusLabel(e.to_status) }}</span>
                    <span class="at">{{ when(e.at) }}</span>
                    <MailEvidence v-if="e.by === 'mail' && e.mail" :event="e" @undone="afterMail" @stale="afterMail" />
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
  justify-content: center;
  gap: var(--space-2);
  min-height: 2.5rem;
  padding: 0 var(--space-3);
  background: transparent;
  border: 1px solid transparent;
  box-shadow: none;
  color: var(--text-2);
}
.stage:hover:not(:disabled) { background: var(--surface); }
.stage.active { background: var(--surface); border-color: var(--border); box-shadow: var(--shadow); color: var(--text); font-weight: 650; }
.stage-n {
  min-width: 1.6em; padding: 0 0.35em; border-radius: 999px; text-align: center;
  font-size: var(--text-xs); line-height: 1.6; color: var(--muted); background: var(--surface-3);
}
.stage.active .stage-n { color: var(--text-2); }
.stage-n.zero { background: transparent; }
/* Each stage's own colour, as a bar under the active segment. */
.stage { position: relative; }
.stage::after {
  content: ''; position: absolute; left: var(--space-3); right: var(--space-3); bottom: 4px;
  height: 2px; border-radius: 2px; background: transparent;
}
.stage.active[data-status='active']::after { background: var(--accent); }
.stage.active[data-status='to_apply']::after { background: var(--stage-saved); }
.stage.active[data-status='applied']::after { background: var(--stage-applied); }
.stage.active[data-status='assessment']::after { background: var(--stage-assessment); }
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
.notes { margin: 2px 0 0; color: var(--text-2); font-size: var(--text-sm); white-space: pre-line; text-wrap: pretty; }
/* Its own line under the title and note, never beside the title. */
.note-edit { display: flex; width: max-content; margin-top: 2px; font-size: var(--text-xs); color: var(--muted); text-decoration: none; }
.note-edit:hover:not(:disabled) { color: var(--accent); text-decoration: underline; }
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
.updated { grid-area: updated; color: var(--muted); font-size: var(--text-xs); white-space: nowrap; }
/* StatusSelect renders its own label root; place it in the row's status area. */
.app-row > :deep(.status-field) { grid-area: status; }
.follow-up { color: var(--warn); background: var(--warn-soft); margin-left: var(--space-2); }
.row-meta { margin: 2px 0 0; font-size: var(--text-xs); color: var(--muted); }
.row-remove { display: flex; width: max-content; margin-top: 2px; font-size: var(--text-xs); color: var(--muted); text-decoration: none; }
.row-remove:hover:not(:disabled) { color: var(--accent); text-decoration: underline; }

.history { grid-area: history; margin-top: var(--space-2); font-size: var(--text-sm); }
.history summary { cursor: pointer; color: var(--muted); width: max-content; }
.history summary .num { font-size: var(--text-xs); }
.timeline { list-style: none; margin: var(--space-2) 0 0; padding: 0 0 0 var(--space-3); border-left: 2px solid var(--border); }
.timeline li { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-3); padding: 2px 0; }
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
