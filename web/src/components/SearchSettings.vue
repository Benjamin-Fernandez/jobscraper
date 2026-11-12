<script setup>
// Settings -> Search (Q-116 design §2, §3): the cycle and companies per run as rows, and
// pointers to where the search is shaped elsewhere (job titles, kinds of role, the
// watchlist). Both settings are stored on the server (GET/PUT /api/settings), not config
// edits (config/ is read-only in Docker - M11), and every run uses them.
//
// The cycle (M15): how often every company is checked again. The choices are the plan's
// (`cycle_day_options`), so a future tier changes what is offered here without a code
// change. Companies per run (M12-T4): how many watchlist companies one run takes; the
// hint does the cadence arithmetic the owner would otherwise do by hand.
//
// One commit rule for the page (design §3), no Save button anywhere:
//   - radios: a click or Space saves at once; an arrow key only moves the choice (Q-75
//     N17), Enter or focus leaving the editor saves it, Esc drops it and closes the row;
//   - the number: Enter or focus leaving the editor saves it when it is valid and
//     changed, a preset saves at once, Esc reverts and closes; an invalid number is never
//     sent and its reason shows under the field; opening another row drops the draft.
// While a save is in flight the row is busy; on success "Saved" shows for 3 s; on failure
// the old value stays and the reason shows under the row until the next edit.
//
// A hash row id (`#/settings/search/batch-size`), passed in as `item`, opens that row.
import { computed, nextTick, onActivated, onMounted, ref, watch } from 'vue'
import { describeError, getSettings, saveSettings } from '../api.js'
import { plural } from '../format.js'
import { cycleLabel, num, runsPerDayLabel } from '../runs.js'
import { COPY, LINK_TEXT, saveErrorText, useRows } from '../settingsRows.js'
import CountPicker from './CountPicker.vue'
import SettingRow from './SettingRow.vue'
import SettingsGroup from './SettingsGroup.vue'
import TabLoading from './TabLoading.vue'

const props = defineProps({
  // The row id from the hash (`#/settings/search/<row-id>`), or null.
  item: { type: String, default: null },
})

const rows = useRows()

const settings = ref(null)
const loadError = ref('')
const loading = ref(true)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    settings.value = await getSettings()
    draft.value = settings.value.batch_size
  } catch (e) {
    loadError.value = COPY.loadError(describeError(e).replace(/\.$/, ''))
  } finally {
    loading.value = false
  }
}

// ---- companies per run ----
const draft = ref('')
const max = computed(() => settings.value?.enabled_companies ?? 0)
// Before the first sync no company is enabled and the server refuses every value. The
// editor then does not guess an upper bound: the server says why.
const noneEnabled = computed(() => Boolean(settings.value) && max.value < 1)

const invalid = computed(() => {
  const n = draft.value
  if (n === '' || n === null) return COPY.batchEmpty
  if (!Number.isInteger(n)) return COPY.numberWhole
  if (n < 1) return COPY.batchMin
  if (!noneEnabled.value && n > max.value) return COPY.batchMax(num(max.value))
  return ''
})
const unchanged = computed(() => draft.value === settings.value?.batch_size)

const oneDecimal = x => Math.round(x * 10) / 10

// The server's figure for the saved size; the same arithmetic for a draft.
const cadence = computed(() => {
  const s = settings.value
  if (!s || invalid.value) return ''
  if (noneEnabled.value) return COPY.batchNone
  const runsPerCycle = Math.ceil(s.enabled_companies / draft.value)
  const perDay = unchanged.value && s.runs_per_day_needed !== undefined
    ? s.runs_per_day_needed
    : oneDecimal(runsPerCycle / s.cycle_days)
  return COPY.batchCadence(
    s.cycle_days, runsPerDayLabel(perDay), plural(runsPerCycle, 'run'),
    plural(s.enabled_companies, 'company', 'companies'),
  )
})
const range = computed(() => {
  const s = settings.value
  if (!s) return ''
  return noneEnabled.value
    ? `The config default is ${s.batch_size_default}. A run started with its own count (Runs tab) uses that instead.`
    : COPY.batchRange(num(max.value), s.batch_size_default)
})
const batchValue = computed(() => (settings.value ? plural(settings.value.batch_size, 'company', 'companies') : ''))

async function saveBatch() {
  if (invalid.value || unchanged.value || rows.busy['batch-size']) return
  const n = draft.value
  rows.setBusy('batch-size', true)
  rows.clear('batch-size')
  try {
    settings.value = await saveSettings({ batch_size: n })
    draft.value = settings.value.batch_size
    rows.flash('batch-size')
  } catch (e) {
    rows.fail('batch-size', saveErrorText(e, 'batch_size'))
  } finally {
    rows.setBusy('batch-size', false)
  }
}

function onBatchKey(e) {
  if (e.key === 'Enter' && e.target?.tagName === 'INPUT') {
    e.preventDefault()
    saveBatch()
  } else if (e.key === 'Escape') {
    e.stopPropagation()
    draft.value = settings.value?.batch_size ?? ''
    closeRow('batch-size')
  }
}
// A preset sets the draft in CountPicker's own click handler, which runs before this
// bubbled one, so the draft is already the preset when it is saved.
function onBatchClick(e) {
  if (e.target?.closest?.('[data-preset]')) saveBatch()
}
function onBatchFocusout(e) {
  if (!e.currentTarget.contains(e.relatedTarget)) saveBatch()
}

// ---- the cycle ----
const cyclePending = ref(null)           // an arrow-key choice waiting for Enter or blur
let arrowed = false
const shownCycle = computed(() => cyclePending.value ?? settings.value?.cycle_days)
const lower = days => cycleLabel(days).toLowerCase()

const cycleHint = computed(() => {
  const s = settings.value
  if (!s) return ''
  const every = `Every company is checked again ${s.cycle_days === 1 ? 'every day' : `every ${plural(s.cycle_days, 'day')}`}.`
  if (!s.enabled_companies) return every
  return `${every} At ${plural(s.batch_size, 'company', 'companies')} per run that is `
    + `${runsPerDayLabel(s.runs_per_day_needed)}.`
})

function onCycleKey(e) {
  if (e.key === 'Enter') {
    e.preventDefault()
    commitCycle()
  } else if (e.key === 'Escape') {
    e.stopPropagation()
    cyclePending.value = null
    arrowed = false
    closeRow('cycle')
  } else {
    arrowed = e.key.startsWith('Arrow')
  }
}

function onCycleChange(days) {
  rows.clear('cycle')
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
  if (!settings.value || days === settings.value.cycle_days || rows.busy.cycle) return
  rows.setBusy('cycle', true)
  rows.clear('cycle')
  try {
    settings.value = await saveSettings({ cycle_days: days })
    rows.flash('cycle')
  } catch (e) {
    rows.fail('cycle', saveErrorText(e, 'cycle_days'))
  } finally {
    rows.setBusy('cycle', false)
  }
}

// ---- rows opening and closing ----
const rowButton = id => document.querySelector(`#setting-${id} .setting-main`)

function closeRow(id) {
  rows.close()
  nextTick(() => rowButton(id)?.focus())
}

// Opening a row puts focus in its editor: the checked radio, or the number field.
async function onToggle(id) {
  const opening = rows.open !== id
  rows.toggle(id)
  if (!opening) return
  await nextTick()
  const editor = document.getElementById(`setting-${id}-editor`)
  editor?.querySelector('input:checked, input[type="number"]')?.focus()
}

// Another row opened, or this one closed: drop what was half-typed.
watch(() => rows.open, () => {
  cyclePending.value = null
  arrowed = false
  if (settings.value) draft.value = settings.value.batch_size
})

// ---- deep link ----
const ROW_IDS = ['cycle', 'batch-size', 'titles', 'interests', 'companies']
const EDIT_IDS = ['cycle', 'batch-size']

async function goTo() {
  const id = props.item
  if (!ROW_IDS.includes(id)) return
  if (EDIT_IDS.includes(id)) {
    if (!settings.value) return           // wait for the data; the watch fires again
    rows.open = id
  }
  await nextTick()
  const button = rowButton(id)
  if (!button) return
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches
  button.scrollIntoView?.({ block: 'center', behavior: reduce ? 'auto' : 'smooth' })
  button.focus({ preventScroll: true })
}
watch([() => props.item, () => Boolean(settings.value)], goTo, { immediate: true, flush: 'post' })

let shownOnce = false
onMounted(() => {
  shownOnce = true
  load()
})
onActivated(() => {
  if (shownOnce) {
    shownOnce = false
    return
  }
  load()
})
</script>

<template>
  <div class="search-settings">
    <SettingsGroup :title="COPY.groups.schedule">
      <TabLoading v-if="loading && !settings" :rows="2" />
      <div v-else-if="loadError && !settings" class="notice error load-error" role="alert">
        <p>{{ loadError }}</p>
        <button type="button" @click="load">{{ COPY.tryAgain }}</button>
      </div>
      <template v-else-if="settings">
        <SettingRow
          id="cycle"
          label="Cycle"
          description="How often every company is checked again."
          :value="cycleLabel(settings.cycle_days)"
          kind="edit"
          :open="rows.open === 'cycle'"
          :busy="rows.busy.cycle"
          :saved="rows.saved.cycle ? COPY.nextRunUsesIt : false"
          :error="rows.error.cycle"
          @toggle="onToggle('cycle')"
        >
          <div class="editor" @keydown="onCycleKey" @focusout="onCycleFocusout">
            <div
              class="cycle-options"
              role="radiogroup"
              aria-labelledby="setting-cycle-label"
              @pointerdown="arrowed = false"
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
                  @change="onCycleChange(d)"
                >
                <span class="cycle-name">{{ cycleLabel(d) }}</span>
                <span class="cycle-days">{{ plural(d, 'day') }}</span>
              </label>
            </div>
            <p v-if="cyclePending !== null" class="hint cycle-pending" role="status">
              {{ COPY.cyclePending(cycleLabel(cyclePending), lower(settings.cycle_days)) }}
            </p>
            <p class="hint cycle-hint">{{ cycleHint }}</p>
            <p class="muted small">{{ COPY.cycleDefault(lower(settings.cycle_days_default)) }}</p>
          </div>
        </SettingRow>

        <SettingRow
          id="batch-size"
          label="Companies per run"
          description="How many watchlist companies one run checks."
          :value="batchValue"
          kind="edit"
          :open="rows.open === 'batch-size'"
          :busy="rows.busy['batch-size']"
          :saved="rows.saved['batch-size'] ? COPY.nextRunUsesIt : false"
          :error="rows.error['batch-size']"
          @toggle="onToggle('batch-size')"
        >
          <div class="editor batch" @keydown="onBatchKey" @click="onBatchClick" @focusout="onBatchFocusout">
            <CountPicker
              v-model="draft"
              input-id="batch-size"
              label="Companies per run"
              :max="noneEnabled ? null : max"
              :invalid="Boolean(invalid)"
              describedby="batch-size-hint"
              @update:model-value="rows.clear('batch-size')"
            />
            <p id="batch-size-hint" class="hint" :class="{ invalid }">
              <template v-if="invalid">{{ invalid }}</template>
              <template v-else>{{ cadence }}</template>
            </p>
            <p class="muted small">{{ range }}</p>
          </div>
        </SettingRow>
      </template>
    </SettingsGroup>

    <SettingsGroup :title="COPY.groups.whatToLookFor">
      <SettingRow
        id="titles"
        label="Job titles"
        description="The roles JobScraper searches for."
        kind="link"
        href="#/profile/resume"
        :link-text="LINK_TEXT.profileEdit"
      />
      <SettingRow
        id="interests"
        label="Kinds of role"
        description="The kinds of work you're open to. Set in config.yaml for now."
        kind="link"
        href="#/profile/resume"
        :link-text="LINK_TEXT.profileView"
      />
      <SettingRow
        id="companies"
        label="Companies to watch"
        description="The careers sites JobScraper checks."
        kind="link"
        href="#/companies"
        :link-text="LINK_TEXT.companies"
      />
    </SettingsGroup>
  </div>
</template>

<style scoped>
.editor { display: grid; gap: var(--space-2); }
.hint { margin: 0; color: var(--text); font-size: var(--text-sm); }
.hint.invalid { color: var(--danger); }
.small { font-size: var(--text-sm); margin: 0; }
.load-error { margin: var(--space-3) var(--space-4); }
.cycle-options {
  display: flex; flex-wrap: wrap; gap: var(--space-1); padding: var(--space-1);
  background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-lg);
}
.cycle-option {
  flex: 1 1 6.5rem; display: flex; flex-direction: column; align-items: center; justify-content: center;
  min-height: var(--touch-min); padding: var(--space-2) var(--space-3); border-radius: var(--radius); cursor: pointer;
  border: 1px solid transparent; color: var(--text-2);
}
.cycle-option:hover { background: var(--surface); }
.cycle-option.active {
  background: var(--surface); border-color: var(--border); box-shadow: var(--shadow); color: var(--text);
}
.cycle-option:has(input:focus-visible) { outline: 2px solid var(--focus); outline-offset: 2px; }
.cycle-name { font-weight: 600; font-size: var(--text-sm); }
.cycle-days { font-size: var(--text-xs); color: var(--muted); }
</style>
