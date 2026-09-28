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
import { computed, onMounted, ref } from 'vue'
import { ApiError, describeError, getSettings, saveSettings } from '../api.js'
import { plural } from '../format.js'
import { cycleLabel } from '../runs.js'
import { tabEmits, tabProps } from '../shell.js'
import TabLoading from '../components/TabLoading.vue'

defineProps(tabProps)
defineEmits(tabEmits)

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
  if (!noneEnabled.value && n > max.value) return `At most ${max.value} - that is every enabled company.`
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
  if (noneEnabled.value) return 'No companies are enabled yet - sync the watchlist first.'
  const runsPerCycle = Math.ceil(s.enabled_companies / draft.value)
  const perDay = unchanged.value && s.runs_per_day_needed !== undefined
    ? s.runs_per_day_needed
    : oneDecimal(runsPerCycle / s.cycle_days)
  return `A full ${s.cycle_days}-day sweep needs ${perDay} runs/day at this size `
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
  return `${every} At ${plural(s.batch_size, 'company', 'companies')} per run that takes `
    + `${s.runs_per_day_needed} runs a day.`
})

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

onMounted(load)
</script>

<template>
  <section class="settings">
    <h2 class="section-title">Cycle</h2>
    <TabLoading v-if="loading" :rows="1" />
    <div v-else-if="settings" class="panel-box cycle">
      <p id="cycle-label" class="question">How often every company is checked again</p>
      <div class="cycle-options" role="radiogroup" aria-labelledby="cycle-label">
        <label
          v-for="d in settings.cycle_day_options"
          :key="d"
          class="cycle-option"
          :class="{ active: d === settings.cycle_days }"
          :data-days="d"
        >
          <input
            type="radio"
            name="cycle"
            class="visually-hidden"
            :value="d"
            :checked="d === settings.cycle_days"
            :disabled="savingCycle"
            @change="chooseCycle(d)"
          >
          <span class="cycle-name">{{ cycleLabel(d) }}</span>
          <span class="cycle-days">{{ plural(d, 'day') }}</span>
        </label>
      </div>
      <p class="hint cycle-hint">{{ cycleHint }}</p>
      <p class="muted small">
        The choices come from your plan ({{ settings.plan }}). The config default is
        {{ cycleLabel(settings.cycle_days_default).toLowerCase() }}.
      </p>
    </div>
    <p v-if="cycleError" class="notice error" role="alert">{{ cycleError }}</p>
    <p v-if="cycleSaved" class="notice ok cycle-saved" role="status">{{ cycleSaved }}</p>

    <h2 class="section-title">Companies per run</h2>
    <TabLoading v-if="loading" :rows="1" />
    <div v-else-if="loadError" class="notice error" role="alert">
      <p>Could not load settings: {{ loadError }}</p>
      <button type="button" @click="load">Try again</button>
    </div>
    <form v-else class="batch" novalidate @submit.prevent="save">
      <label for="batch-size">How many watchlist companies one run fetches</label>
      <div class="row">
        <input
          id="batch-size"
          v-model.number="draft"
          type="number"
          inputmode="numeric"
          min="1"
          :max="noneEnabled ? undefined : max"
          :aria-invalid="invalid ? 'true' : 'false'"
          aria-describedby="batch-size-hint"
          @input="saved = ''"
        >
        <button type="submit" class="primary save" :disabled="Boolean(invalid) || unchanged || saving">
          {{ saving ? 'Saving…' : 'Save' }}
        </button>
      </div>
      <p id="batch-size-hint" class="hint" :class="{ invalid }">
        <template v-if="invalid">{{ invalid }}</template>
        <template v-else>{{ cadence }}</template>
      </p>
      <p class="muted small">
        <template v-if="!noneEnabled">Between 1 and {{ max }}. </template>The config default is {{ settings.batch_size_default }}.
        A run started with its own count (Runs tab) uses that instead.
      </p>
    </form>
    <p v-if="saveError" class="notice error" role="alert">{{ saveError }}</p>
    <p v-if="saved" class="notice ok" role="status">{{ saved }}</p>
  </section>
</template>

<style scoped>
.batch, .panel-box {
  display: grid; gap: var(--space-2); max-width: 40rem;
  padding: var(--space-4); background: var(--surface);
  border: 1px solid var(--border); border-radius: var(--radius-lg); box-shadow: var(--shadow);
}
.batch label { font-weight: 600; font-size: var(--text-sm); }
.row { display: flex; gap: var(--space-2); align-items: center; }
.row input { width: 8rem; }
.hint { margin: 0; color: var(--text); font-size: var(--text-sm); }
.hint.invalid { color: var(--danger); }
.small { font-size: var(--text-sm); margin: 0; }
.question { margin: 0; font-weight: 600; font-size: var(--text-sm); }
.cycle-options {
  display: flex; flex-wrap: wrap; gap: var(--space-1); padding: var(--space-1);
  background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-lg);
}
.cycle-option {
  flex: 1 1 6.5rem; display: flex; flex-direction: column; align-items: center;
  padding: var(--space-2) var(--space-3); border-radius: var(--radius); cursor: pointer;
  border: 1px solid transparent; color: var(--text-2);
}
.cycle-option:hover { background: var(--surface); }
.cycle-option.active {
  background: var(--surface); border-color: var(--border); box-shadow: var(--shadow);
  color: var(--text);
}
.cycle-option:has(input:focus-visible) { outline: 2px solid var(--focus); outline-offset: 2px; }
.cycle-name { font-weight: 600; font-size: var(--text-sm); }
.cycle-days { font-size: var(--text-xs); color: var(--muted); }
.notice { margin-top: var(--space-4); max-width: 34rem; }
</style>
