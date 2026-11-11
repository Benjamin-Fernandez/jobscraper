<script setup>
// The cycle (M15): how often every company is checked again. The choices are
// the plan's (`cycle_day_options`), so a future tier changes what is offered
// here without a code change; picking one saves it at once.
//
// Companies per run (M12-T4): how many watchlist companies one run takes. Both
// are stored settings on the server, not config edits (config/ is read-only in
// Docker - M11), and every run uses them.
//
// The hint does the cadence arithmetic the user would otherwise do by hand: at
// this size, how many runs a day it takes to sweep every company once per cycle.
//
// Cycle by keyboard (Q-75 N17): an arrow key moves the radio but does not save;
// Enter or leaving the group does, Escape drops it (the status select's rule,
// Q-70 B3). A click or Space saves at once. Notices clear on the next edit.
//
// Appearance (Q-75 G40): Light, Dark or System, kept in this browser (theme.js).
//
// Email (Q-60, F-50): the Gmail mailboxes JobScraper reads for application
// updates. MailCard loads and saves its own data (GET /api/mail), so a server
// without those routes still shows the rest of this tab.
//
// Four views (Q-100 design section 1), picked like Profile's and kept in the hash
// (`#/settings/<view>[/<item>]`): Accounts (the Connected accounts hub, the default),
// Apply, Search (the cycle and companies per run) and Appearance. The hub's data -
// GET /api/connections - is loaded here, because the Accounts tab carries the
// attention count and Apply shows the mailbox row from the same answer. A missing
// or failed answer never reads as "all good": no count, and the hub says so.
import { computed, onMounted, ref } from 'vue'
import { ApiError, describeError, getSettings, saveSettings } from '../api.js'
import { attentionCount } from '../connections.js'
import { getConnections } from '../connections_api.js'
import { plural } from '../format.js'
import { useView } from '../route.js'
import { cycleLabel, num, runsPerDayLabel } from '../runs.js'
import { tabEmits, tabProps } from '../shell.js'
import { THEMES, setTheme, storedTheme } from '../theme.js'
import ApplySettings from '../components/ApplySettings.vue'
import ConnectionsHub from '../components/ConnectionsHub.vue'
import CountPicker from '../components/CountPicker.vue'
import TabLoading from '../components/TabLoading.vue'

defineProps(tabProps)
defineEmits(tabEmits)

// ---- views (Q-100) ----
const VIEWS = [
  { id: 'accounts', label: 'Accounts' },
  { id: 'apply', label: 'Apply' },
  { id: 'search', label: 'Search' },
  { id: 'appearance', label: 'Appearance' },
]
const view = useView('settings', VIEWS, 'accounts')

function onViewKey(e, i) {
  const next = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: VIEWS.length - 1 }[e.key]
  if (next === undefined) return
  e.preventDefault()
  const v = VIEWS[(next + VIEWS.length) % VIEWS.length]
  view.value = v.id
  document.getElementById(`settings-tab-${v.id}`)?.focus()
}

// ---- connections (the hub's data) ----
const connections = ref(null)
const connLoading = ref(true)
const connFailed = ref(false)
let previous = null            // the last good answer: a single blip is not yet a problem
const attention = ref(0)

async function loadConnections() {
  try {
    const next = await getConnections()
    if (next === null) throw new Error('absent')
    attention.value = attentionCount(next, previous)
    previous = next
    connections.value = next
    connFailed.value = false
  } catch {
    // Keep the last good answer on screen, but count nothing from a failed load.
    attention.value = 0
    connFailed.value = true
  } finally {
    connLoading.value = false
  }
}

const settings = ref(null)
const loadError = ref('')
const loading = ref(true)
const draft = ref('')
const saving = ref(false)
const saveError = ref('')
const saved = ref('')

const max = computed(() => settings.value?.enabled_companies ?? 0)
// Before the first sync no company is enabled and the server refuses every
// value. The form then does not guess an upper bound: the server says why.
const noneEnabled = computed(() => Boolean(settings.value) && max.value < 1)

const invalid = computed(() => {
  const n = draft.value
  if (n === '' || n === null) return 'Enter how many companies a run should take.'
  if (!Number.isInteger(n)) return 'Enter a whole number.'
  if (n < 1) return 'A run needs at least 1 company.'
  if (!noneEnabled.value && n > max.value) return `At most ${num(max.value)} - that is every enabled company.`
  return ''
})

const unchanged = computed(() => draft.value === settings.value?.batch_size)

function oneDecimal(x) {
  return Math.round(x * 10) / 10
}

// The server's figure for the saved size; the same arithmetic for a draft.
const cadence = computed(() => {
  const s = settings.value
  if (!s || invalid.value) return ''
  if (noneEnabled.value) return 'No companies yet. Add some in Companies, or start a run to load your watchlist.'
  const runsPerCycle = Math.ceil(s.enabled_companies / draft.value)
  const perDay = unchanged.value && s.runs_per_day_needed !== undefined
    ? s.runs_per_day_needed
    : oneDecimal(runsPerCycle / s.cycle_days)
  return `A full ${s.cycle_days}-day sweep takes ${runsPerDayLabel(perDay)} at this size `
    + `(${plural(runsPerCycle, 'run')} to cover ${plural(s.enabled_companies, 'company', 'companies')}).`
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    settings.value = await getSettings()
    draft.value = settings.value.batch_size
  } catch (e) {
    loadError.value = describeError(e)
  } finally {
    loading.value = false
  }
}

// The server's 422 in words: a plain message, or FastAPI's list of field errors.
function reason(detail) {
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && detail.length) return detail.map(d => d?.msg ?? String(d)).join('; ')
  return 'out of range'
}

async function save() {
  if (invalid.value || unchanged.value || saving.value) return
  saving.value = true
  saveError.value = ''
  saved.value = ''
  try {
    settings.value = await saveSettings({ batch_size: draft.value })
    draft.value = settings.value.batch_size
    saved.value = `Saved: ${plural(settings.value.batch_size, 'company', 'companies')} per run.`
  } catch (e) {
    saveError.value = e instanceof ApiError && e.status === 422
      ? `The server did not accept ${draft.value}: ${reason(e.detail)}`
      : `Could not save: ${describeError(e)}`
  } finally {
    saving.value = false
  }
}

// ---- the cycle (M15) ----
const savingCycle = ref(false)
const cycleError = ref('')
const cycleSaved = ref('')

const cycleHint = computed(() => {
  const s = settings.value
  if (!s) return ''
  const every = `Every company is checked again ${s.cycle_days === 1 ? 'every day' : `every ${plural(s.cycle_days, 'day')}`}.`
  if (!s.enabled_companies) return every
  return `${every} At ${plural(s.batch_size, 'company', 'companies')} per run that is `
    + `${runsPerDayLabel(s.runs_per_day_needed)}.`
})

const cyclePending = ref(null)           // an arrow-key choice waiting for Enter or blur
let arrowed = false
const shownCycle = computed(() => cyclePending.value ?? settings.value?.cycle_days)

function onCycleKey(e) {
  if (e.key === 'Enter') {
    e.preventDefault()
    commitCycle()
  } else if (e.key === 'Escape') {
    cyclePending.value = null
    arrowed = false
  } else {
    arrowed = e.key.startsWith('Arrow')
  }
}

function onCycleChange(days) {
  cycleSaved.value = ''
  cycleError.value = ''
  if (arrowed) {
    arrowed = false
    cyclePending.value = days === settings.value.cycle_days ? null : days
  } else {
    cyclePending.value = null
    chooseCycle(days)
  }
}

function commitCycle() {
  const days = cyclePending.value
  cyclePending.value = null
  if (days !== null) chooseCycle(days)
}

function onCycleFocusout(e) {
  if (!e.currentTarget.contains(e.relatedTarget)) commitCycle()
}

async function chooseCycle(days) {
  if (!settings.value || days === settings.value.cycle_days || savingCycle.value) return
  savingCycle.value = true
  cycleError.value = ''
  cycleSaved.value = ''
  try {
    settings.value = await saveSettings({ cycle_days: days })
    cycleSaved.value = `Saved: ${cycleLabel(days).toLowerCase()}. The next run uses it.`
  } catch (e) {
    cycleError.value = e instanceof ApiError && e.status === 422
      ? `The server did not accept that cycle: ${reason(e.detail)}`
      : `Could not save: ${describeError(e)}`
  } finally {
    savingCycle.value = false
  }
}

// ---- appearance (G40) ----
const theme = ref(storedTheme())
function chooseTheme(id) {
  theme.value = id
  setTheme(id)
}

onMounted(() => {
  load()
  loadConnections()
})
</script>

<template>
  <section class="settings">
    <header class="page-head">
      <div>
        <h2 class="page-title">Settings</h2>
        <p class="page-sub">Accounts, applying, search and appearance.</p>
      </div>
      <div class="views" role="tablist" aria-label="Settings sections">
        <button
          v-for="(v, i) in VIEWS"
          :id="`settings-tab-${v.id}`"
          :key="v.id"
          type="button"
          role="tab"
          class="view-tab"
          :class="[`view-${v.id}`, { active: view === v.id }]"
          :aria-selected="view === v.id ? 'true' : 'false'"
          :aria-controls="`settings-panel-${v.id}`"
          :tabindex="view === v.id ? 0 : -1"
          @click="view = v.id"
          @keydown="onViewKey($event, i)"
        >
          {{ v.label }}
          <span v-if="v.id === 'accounts' && attention > 0" class="view-badge">
            <span aria-hidden="true">{{ attention }}</span>
            <span class="visually-hidden">{{ attention }} need attention</span>
          </span>
        </button>
      </div>
    </header>

    <div
      v-if="view === 'accounts'"
      id="settings-panel-accounts"
      role="tabpanel"
      aria-labelledby="settings-tab-accounts"
    >
      <ConnectionsHub :connections="connections" :loading="connLoading" :failed="connFailed" @reload="loadConnections" />
    </div>

    <div
      v-else-if="view === 'apply'"
      id="settings-panel-apply"
      role="tabpanel"
      aria-labelledby="settings-tab-apply"
    >
      <ApplySettings :connections="connections" />
    </div>

    <div
      v-else-if="view === 'search'"
      id="settings-panel-search"
      role="tabpanel"
      aria-labelledby="settings-tab-search"
    >
    <h3 class="section-title">Cycle</h3>
    <TabLoading v-if="loading" :rows="1" />
    <div v-else-if="settings" class="panel-box cycle">
      <p id="cycle-label" class="question">How often every company is checked again</p>
      <div
        class="cycle-options"
        role="radiogroup"
        aria-labelledby="cycle-label"
        @keydown="onCycleKey"
        @pointerdown="arrowed = false"
        @focusout="onCycleFocusout"
      >
        <label
          v-for="d in settings.cycle_day_options"
          :key="d"
          class="cycle-option"
          :class="{ active: d === shownCycle }"
          :data-days="d"
        >
          <input
            type="radio"
            name="cycle"
            class="visually-hidden"
            :value="d"
            :checked="d === shownCycle"
            :disabled="savingCycle"
            @change="onCycleChange(d)"
          >
          <span class="cycle-name">{{ cycleLabel(d) }}</span>
          <span class="cycle-days">{{ plural(d, 'day') }}</span>
        </label>
      </div>
      <p v-if="cyclePending !== null" class="hint cycle-pending" role="status">
        {{ cycleLabel(cyclePending) }} is selected but not saved. Press Enter to save, or Esc to keep {{ cycleLabel(settings.cycle_days).toLowerCase() }}.
      </p>
      <p class="hint cycle-hint">{{ cycleHint }}</p>
      <p class="muted small">
        The config default is {{ cycleLabel(settings.cycle_days_default).toLowerCase() }}.
      </p>
    </div>
    <p v-if="cycleError" class="notice error" role="alert">{{ cycleError }}</p>
    <p v-if="cycleSaved" class="notice ok cycle-saved" role="status">{{ cycleSaved }}</p>

    <h3 class="section-title">Companies per run</h3>
    <TabLoading v-if="loading" :rows="1" />
    <div v-else-if="loadError" class="notice error" role="alert">
      <p>Could not load settings: {{ loadError }}</p>
      <button type="button" @click="load">Try again</button>
    </div>
    <form v-else class="batch" novalidate @submit.prevent="save">
      <label for="batch-size">How many watchlist companies one run fetches</label>
      <div class="row">
        <CountPicker
          v-model="draft"
          input-id="batch-size"
          label="Companies per run"
          :max="noneEnabled ? null : max"
          :invalid="Boolean(invalid)"
          describedby="batch-size-hint"
          @update:model-value="saved = ''; saveError = ''"
        />
        <button type="submit" class="primary save" :disabled="Boolean(invalid) || unchanged || saving">
          {{ saving ? 'Saving…' : 'Save' }}
        </button>
      </div>
      <p id="batch-size-hint" class="hint" :class="{ invalid }">
        <template v-if="invalid">{{ invalid }}</template>
        <template v-else>{{ cadence }}</template>
      </p>
      <p class="muted small">
        <template v-if="!noneEnabled">Between 1 and {{ num(max) }}. </template>The config default is {{ settings.batch_size_default }}.
        A run started with its own count (Runs tab) uses that instead.
      </p>
    </form>
    <p v-if="saveError" class="notice error" role="alert">{{ saveError }}</p>
    <p v-if="saved" class="notice ok" role="status">{{ saved }}</p>
    </div>

    <div
      v-else
      id="settings-panel-appearance"
      role="tabpanel"
      aria-labelledby="settings-tab-appearance"
    >
    <h3 class="section-title">Appearance</h3>
    <div class="panel-box appearance">
      <p id="theme-label" class="question">Colour theme</p>
      <div class="cycle-options" role="radiogroup" aria-labelledby="theme-label">
        <label
          v-for="t in THEMES"
          :key="t.id"
          class="theme-option"
          :class="{ active: t.id === theme }"
          :data-choice="t.id"
        >
          <input
            type="radio"
            name="theme"
            class="visually-hidden"
            :value="t.id"
            :checked="t.id === theme"
            @change="chooseTheme(t.id)"
          >
          <span class="cycle-name">{{ t.label }}</span>
        </label>
      </div>
      <p class="muted small">Saved in this browser only. System follows your device's light or dark setting.</p>
    </div>
    </div>
  </section>
</template>

<style scoped>
.views {
  display: inline-flex; flex-wrap: wrap; gap: 2px; padding: 2px;
  background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius);
}
.view-tab {
  border: 1px solid transparent; background: transparent; box-shadow: none; color: var(--text-2);
  border-radius: calc(var(--radius) - 2px);
}
.view-tab:hover:not(:disabled) { background: var(--surface); color: var(--text); }
.view-tab.active, .view-tab.active:hover:not(:disabled) {
  background: var(--surface); border-color: var(--border-strong); box-shadow: var(--shadow-sm);
  color: var(--text); font-weight: 650;
}
/* The attention count: a dot and a number, so it is not colour alone. */
.view-badge {
  display: inline-flex; align-items: center; gap: var(--space-1);
  font-size: var(--text-xs); font-weight: 700; color: var(--state-attention-fg);
}
.view-badge::before { content: ''; width: 0.5rem; height: 0.5rem; border-radius: 50%; background: currentColor; }
@media (max-width: 640px) {
  .views { display: flex; width: 100%; }
  .view-tab { flex: 1 1 40%; min-height: var(--touch-min); }
}
.batch, .panel-box {
  display: grid; gap: var(--space-2); max-width: 40rem;
  padding: var(--space-4); background: var(--surface);
  border: 1px solid var(--border); border-radius: var(--radius-lg); box-shadow: var(--shadow);
}
.batch label { font-weight: 600; font-size: var(--text-sm); }
.row { display: flex; flex-wrap: wrap; gap: var(--space-2) var(--space-3); align-items: center; }
.hint { margin: 0; color: var(--text); font-size: var(--text-sm); }
.hint.invalid { color: var(--danger); }
.small { font-size: var(--text-sm); margin: 0; }
.question { margin: 0; font-weight: 600; font-size: var(--text-sm); }
.cycle-options {
  display: flex; flex-wrap: wrap; gap: var(--space-1); padding: var(--space-1);
  background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-lg);
}
.cycle-option, .theme-option {
  flex: 1 1 6.5rem; display: flex; flex-direction: column; align-items: center;
  padding: var(--space-2) var(--space-3); border-radius: var(--radius); cursor: pointer;
  border: 1px solid transparent; color: var(--text-2);
}
.cycle-option:hover, .theme-option:hover { background: var(--surface); }
.cycle-option.active, .theme-option.active {
  background: var(--surface); border-color: var(--border); box-shadow: var(--shadow);
  color: var(--text);
}
.cycle-option:has(input:focus-visible), .theme-option:has(input:focus-visible) { outline: 2px solid var(--focus); outline-offset: 2px; }
.cycle-name { font-weight: 600; font-size: var(--text-sm); }
.theme-option { flex-basis: 5rem; }
.cycle-days { font-size: var(--text-xs); color: var(--muted); }
.notice { margin-top: var(--space-4); max-width: 34rem; }
</style>
