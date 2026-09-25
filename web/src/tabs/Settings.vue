<script setup>
// Companies per run (M12-T4): how many watchlist companies one run takes. It is
// a stored setting on the server, not a config edit (config/ is read-only in
// Docker - M11), and every run without an explicit count uses it.
//
// The hint does the cadence arithmetic the user would otherwise do by hand: at
// this size, how many runs a day it takes to sweep every company once per cycle.
import { computed, onMounted, ref } from 'vue'
import { ApiError, describeError, getSettings, saveSettings } from '../api.js'
import { plural } from '../format.js'
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

onMounted(load)
</script>

<template>
  <section class="settings">
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
.batch {
  display: grid; gap: var(--space-2); max-width: 34rem;
  padding: var(--space-4); background: var(--surface);
  border: 1px solid var(--border); border-radius: var(--radius-lg); box-shadow: var(--shadow);
}
.batch label { font-weight: 600; font-size: var(--text-sm); }
.row { display: flex; gap: var(--space-2); align-items: center; }
.row input { width: 8rem; }
.hint { margin: 0; color: var(--text); font-size: var(--text-sm); }
.hint.invalid { color: var(--danger); }
.small { font-size: var(--text-sm); margin: 0; }
.notice { margin-top: var(--space-4); max-width: 34rem; }
</style>
