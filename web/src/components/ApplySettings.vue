<script setup>
// Settings -> Apply as rows (Q-116 design §2, §3, §5; Q-100 §4.3 kept). Every value is
// visible on its row and edited in place; each change saves at once, one PUT with only
// the changed key. There is no Save button and no draft of the whole form.
//
// Data: the panel loads nothing. `apply` is Settings.vue's `loadApplyData()` answer
// ({ status, settings, summary }, each null when its call failed or the route is
// absent) and `connections` is the one GET /api/connections it shares with the hub. A
// row whose source is missing is hidden, never faked: no `settings` hides the limits,
// window, wait and cover-letter rows and leaves Mode as read-only text from
// `status.mode`.
//
// Editable only when the server says `writable: true`. The page never sends a probe
// PUT: that would pin `apply.*` rows over config.yaml (Q-100 §4.3, config.py:162-172).
// A PUT that answers 404 or 405 turns the rows read-only for good; a 422 shows the
// server's message for that field under the row and leaves the form usable.
//
// Commit rules (design §3, one rule for the page):
//   radio    a click or Space saves at once; an arrow key only moves (the choice waits);
//            Enter, or focus leaving the editor, saves it; Esc drops it and closes.
//   number   Enter, or focus leaving the editor, saves if valid and changed; Esc reverts
//            and closes. An invalid number never sends; its error shows under the field.
//   preset   a click saves at once.
//   switch   saves on toggle; not optimistic. The row disables it while saving, so focus
//            is put back on it afterwards.
// Choosing Automatic submit sends nothing until "Switch to automatic submit" (the
// in-row confirm); "Keep dry run" or Esc puts Dry run back. Switching to Dry run never
// asks. A running application keeps the mode it started with (the job reads it once),
// so a change here only affects the next one.
//
// The Application mailbox row makes the hint "Set up the mailbox in Settings -> Apply"
// (apply/contracts.py:175) true. JobScraper waits for the owner at a human check; it
// never solves one.
import { computed, nextTick, reactive, ref, watch, onMounted } from 'vue'
import { ApiError } from '../api.js'
import { missingLabels } from '../applyData.js'
import { putApplySettings } from '../connections_api.js'
import { COPY, LINK_TEXT, capLabel, saveErrorText, useRows, waitLabel, wholeNumber } from '../settingsRows.js'
import SettingRow from './SettingRow.vue'
import SettingsGroup from './SettingsGroup.vue'
import StateChip from './StateChip.vue'

const props = defineProps({
  // The GET /api/connections answer Settings holds, or null.
  connections: { type: Object, default: null },
  // loadApplyData(): { status: {mode, missing, busy}|null, settings: {...}|null, summary: {...}|null }.
  apply: { type: Object, default: null },
  // The row id named in the hash (#/settings/apply/<item>): opened, scrolled to, focused.
  item: { type: String, default: null },
})
const emit = defineEmits(['saved'])

const rows = useRows()
const root = ref(null)
const rowRefs = {}
function setRef(id, el) {
  if (el) rowRefs[id] = el
  else delete rowRefs[id]
}
function focusRow(id) { rowRefs[id]?.focus() }

// ---- what the server last said ----
const current = ref(props.apply?.settings ?? null)
watch(() => props.apply?.settings, s => { current.value = s ?? null })
const noPut = ref(false)                       // the server answered 404/405 to a PUT
const editable = computed(() => current.value?.writable === true && !noPut.value)
const settingsReadOnly = computed(() => !editable.value)

const mode = computed(() => current.value?.mode ?? props.apply?.status?.mode ?? null)
const modeText = computed(() => (mode.value === 'auto' ? 'Automatic submit' : 'Dry run'))
const busy = computed(() => props.apply?.status?.busy === true)
const has = key => typeof current.value?.[key] === (key === 'headed' || key === 'compose_enabled' ? 'boolean' : 'number')

const mailbox = computed(() => (props.connections?.items ?? []).find(i => i.id === 'apply-mailbox') ?? null)
const summary = computed(() => props.apply?.summary ?? null)
const missingCount = computed(() => missingLabels(summary.value).length)
const detailsText = computed(() => (missingCount.value ? `${missingCount.value} to fill in` : 'Complete'))

// ---- one save ----
const NO_SAVE = "Couldn't save: this server doesn't accept changes yet."

// PUT one key. true on success; on failure the old value stays and the row says why.
async function save(id, key, value, { refocus = false } = {}) {
  if (rows.busy[id]) return false
  rows.clear(id)
  rows.setBusy(id, true)
  let ok = false
  try {
    const next = await putApplySettings({ [key]: value })
    if (next === null) {
      noPut.value = true
      rows.close()
      rows.fail(id, NO_SAVE)
    } else {
      current.value = next
      emit('saved', next)
      rows.flash(id)
      ok = true
    }
  } catch (e) {
    if (e instanceof ApiError && (e.status === 404 || e.status === 405)) {
      noPut.value = true
      rows.close()
      rows.fail(id, NO_SAVE)
    } else {
      rows.fail(id, saveErrorText(e, key))
    }
  } finally {
    rows.setBusy(id, false)
  }
  if (refocus) {
    await nextTick()
    focusRow(id)
  }
  return ok
}

// ---- Mode: two radios, Automatic asks first ----
const MODE_OPTIONS = [
  { value: 'dry_run', name: 'Dry run', sub: 'Fills each form and leaves it open for you. Nothing is submitted.' },
  { value: 'auto', name: 'Automatic submit', sub: 'When you click Auto-apply, JobScraper fills the form and submits it once its final check passes.' },
]
const pendingMode = ref(null)       // an arrow-key choice waiting for Enter or focus leaving; or a save in flight
const confirmAuto = ref(false)
let arrowed = false
// What the radios show: the confirm keeps Automatic selected until answered.
const modeShown = computed(() => (confirmAuto.value ? 'auto' : pendingMode.value ?? mode.value))

function onModeKey(e) {
  if (e.key === 'Enter') {
    e.preventDefault()
    commitMode()
  } else if (e.key !== 'Escape') {
    arrowed = e.key.startsWith('Arrow')
  }
}
function onModeChange(value) {
  if (arrowed) {
    arrowed = false
    pendingMode.value = value === mode.value ? null : value
  } else {
    pendingMode.value = null
    chooseMode(value)
  }
}
function commitMode() {
  const value = pendingMode.value
  pendingMode.value = null
  if (value !== null) chooseMode(value)
}
function onModeFocusout(e) {
  if (!e.currentTarget.contains(e.relatedTarget)) commitMode()
}
async function chooseMode(value) {
  if (value === mode.value) {
    confirmAuto.value = false           // picking the saved mode again cancels the question
    return
  }
  if (value === 'auto') {
    confirmAuto.value = true            // nothing is sent until the owner confirms
    await nextTick()
    root.value?.querySelector('.confirm-no')?.focus()
    return
  }
  await saveMode(value)
}
async function saveMode(value) {
  pendingMode.value = value             // keeps the radio where it was put while the PUT runs
  await save('mode', 'mode', value)
  pendingMode.value = null
}
async function confirmSwitch() {
  confirmAuto.value = false
  await saveMode('auto')
  await nextTick()
  focusEditor('mode')
}
function keepDryRun() {
  confirmAuto.value = false
  pendingMode.value = null
  nextTick(() => root.value?.querySelector('.mode-options input:checked')?.focus())
}
function onModeEsc() {
  if (confirmAuto.value) {
    keepDryRun()
    return
  }
  pendingMode.value = null
  rows.close()
  focusRow('mode')
}

// ---- the number rows: presets + a whole-number field ----
const preset = (text, v) => ({ text, v })
const NUMBER_ROWS = [
  {
    id: 'human-check-wait', key: 'captcha_wait_s', group: 'how', lo: 0, hi: 600,
    label: 'Human-check wait',
    description: 'How long JobScraper waits for you at a human check. It never solves one.',
    field: 'Seconds to wait',
    presets: [preset('Stop at once', 0), preset('1 min', 60), preset('2 min', 120), preset('5 min', 300)],
    show: n => waitLabel(n),
    help: n => (n > 0
      ? `JobScraper waits up to ${n} s for you to finish a human check in the window. It never solves one.`
      : 'JobScraper stops and leaves the page to you. It never solves a human check.'),
  },
  {
    id: 'daily-cap', key: 'daily_cap', group: 'limits', lo: 0, hi: 500,
    label: 'Applications a day',
    description: 'The most applications JobScraper submits in one day.',
    field: 'Applications a day',
    presets: [preset('No limit', 0), preset('10', 10), preset('25', 25), preset('50', 50)],
    show: n => capLabel(n, { daily: true }),
    help: () => '0 means no limit. Up to 500.',
  },
  {
    id: 'per-employer-cap', key: 'per_employer_daily_cap', group: 'limits', lo: 0, hi: 100,
    label: 'Per employer',
    description: 'The most applications to one employer in one day.',
    field: 'Per employer a day',
    presets: [preset('No limit', 0), preset('2', 2), preset('5', 5), preset('10', 10)],
    show: n => capLabel(n),
    help: () => '0 means no limit. Up to 100.',
  },
]
const numbersIn = group => NUMBER_ROWS.filter(n => n.group === group && has(n.key))
const numberRow = id => NUMBER_ROWS.find(n => n.id === id)

const drafts = reactive({})         // the typed text per number row
const attempted = reactive({})      // an Enter / focus-leave happened: show the error
const valueFor = n => current.value?.[n.key]
function resetDraft(n) {
  drafts[n.id] = String(valueFor(n) ?? '')
  attempted[n.id] = false
}
for (const n of NUMBER_ROWS) drafts[n.id] = String(valueFor(n) ?? '')
// After a save (or a reload) the field follows the server, unless it is being edited.
watch(current, () => {
  for (const n of NUMBER_ROWS) if (rows.open !== n.id) resetDraft(n)
})

const parsed = n => wholeNumber(drafts[n.id], n.lo, n.hi)
const fieldError = n => (attempted[n.id] ? parsed(n).error ?? '' : '')
// The wait helper follows a valid draft, else the saved value.
const helpFor = n => n.help(parsed(n).value ?? valueFor(n))

async function commitNumber(n) {
  if (rows.open !== n.id) return
  attempted[n.id] = true
  const r = parsed(n)
  if (r.error || r.value === valueFor(n)) return      // invalid never sends; unchanged sends nothing
  await save(n.id, n.key, r.value)
}
async function choosePreset(n, v) {
  drafts[n.id] = String(v)
  attempted[n.id] = false
  if (v === valueFor(n)) return
  const ok = await save(n.id, n.key, v)
  if (!ok) resetDraft(n)
}
function onNumberFocusout(e, n) {
  if (!e.currentTarget.contains(e.relatedTarget)) commitNumber(n)
}
function onNumberEnter(e, n) {
  e.preventDefault()
  commitNumber(n)
}
function onNumberEsc(n) {
  resetDraft(n)
  rows.close()
  focusRow(n.id)
}

// ---- switches ----
function setSwitch(id, key, value) {
  save(id, key, value, { refocus: true })
}

// ---- opening and focus ----
function focusEditor(id) {
  root.value
    ?.querySelector(`#setting-${id}-editor input:checked, #setting-${id}-editor input[type="text"]`)
    ?.focus()
}
let rowFocusOnly = false            // a hash row id focuses the row button, not its editor
watch(() => rows.open, async (id, was) => {
  if (was && was !== id) {
    // Opening another row (or closing) drops the draft of the one left behind.
    const left = numberRow(was)
    if (left) resetDraft(left)
    if (was === 'mode') {
      pendingMode.value = null
      confirmAuto.value = false
    }
  }
  if (!id) return
  await nextTick()
  if (rowFocusOnly) {
    rowFocusOnly = false
    return
  }
  focusEditor(id)
})

const visible = computed(() => {
  const ids = []
  if (mode.value) ids.push('mode')
  if (has('headed')) ids.push('browser-window')
  for (const n of NUMBER_ROWS) if (has(n.key)) ids.push(n.id)
  if (has('compose_enabled')) ids.push('cover-letters')
  ids.push('mailbox')
  if (summary.value) ids.push('details')
  ids.push('resume')
  return ids
})

let handled = null
async function followItem() {
  const id = props.item
  if (!id) {
    handled = null
    return
  }
  if (id === handled || !visible.value.includes(id)) return
  handled = id
  const opens = editable.value && (id === 'mode' || numberRow(id))
  if (opens && rows.open !== id) {
    rowFocusOnly = true
    rows.open = id
  }
  await nextTick()
  await nextTick()
  root.value?.querySelector(`#setting-${id}`)?.scrollIntoView?.({ block: 'center' })
  focusRow(id)
}
onMounted(followItem)
watch([() => props.item, visible], followItem)
</script>

<template>
  <div ref="root" class="apply-settings">
    <div class="apply-intro">
      <p class="apply-intro-text">
        <template v-if="busy">An application is running now. Changes apply to the next one.</template>
        <template v-else>To apply, open a role in the Inbox and choose Auto-apply. JobScraper never applies to a role you didn't click.</template>
      </p>
      <a class="button apply-cta" href="#/inbox">Open Inbox</a>
    </div>
    <p v-if="busy" class="apply-note">A running application keeps the mode it started with.</p>

    <SettingsGroup v-if="mode || has('headed') || numbersIn('how').length" :title="COPY.groups.howApplying">
      <SettingRow
        v-if="mode"
        :ref="el => setRef('mode', el)"
        id="mode"
        label="Mode"
        description="What happens when you click Auto-apply on a role."
        :value="modeText"
        kind="edit"
        :open="rows.open === 'mode'"
        :busy="rows.busy.mode"
        :saved="rows.saved.mode"
        :error="rows.error.mode"
        :read-only="settingsReadOnly"
        @toggle="rows.toggle('mode')"
      >
        <div class="editor" @keydown.esc.stop.prevent="onModeEsc">
          <div
            class="mode-options"
            role="radiogroup"
            aria-label="Mode"
            @keydown="onModeKey"
            @pointerdown="arrowed = false"
            @focusout="onModeFocusout"
          >
            <label v-for="o in MODE_OPTIONS" :key="o.value" class="mode-option" :class="{ active: modeShown === o.value }">
              <input
                type="radio"
                name="apply-mode"
                class="visually-hidden"
                :value="o.value"
                :checked="modeShown === o.value"
                @change="onModeChange(o.value)"
              >
              <span class="mode-name">{{ o.name }}</span>
              <span class="mode-sub">{{ o.sub }}</span>
            </label>
          </div>
          <div v-if="confirmAuto" class="confirm-auto" role="group" aria-labelledby="apply-confirm-title">
            <p id="apply-confirm-title" class="confirm-title">Submit applications automatically?</p>
            <p class="confirm-body">From now on, clicking Auto-apply on a role fills the form and submits it once its final check passes. There's no second confirmation.</p>
            <div class="confirm-buttons">
              <button type="button" class="primary confirm-yes" :disabled="rows.busy.mode" @click="confirmSwitch">Switch to automatic submit</button>
              <button type="button" class="confirm-no" @click="keepDryRun">Keep dry run</button>
            </div>
          </div>
        </div>
      </SettingRow>

      <SettingRow
        v-if="has('headed')"
        :ref="el => setRef('browser-window', el)"
        id="browser-window"
        label="Show the browser window"
        description="Watch each application in its own Edge window."
        kind="switch"
        :checked="current.headed"
        :busy="rows.busy['browser-window']"
        :saved="rows.saved['browser-window']"
        :error="rows.error['browser-window']"
        :read-only="settingsReadOnly"
        @change="v => setSwitch('browser-window', 'headed', v)"
      />

      <template v-for="n in numbersIn('how')" :key="n.id">
        <SettingRow
          :ref="el => setRef(n.id, el)"
          :id="n.id"
          :label="n.label"
          :description="n.description"
          :value="n.show(valueFor(n))"
          kind="edit"
          :open="rows.open === n.id"
          :busy="rows.busy[n.id]"
          :saved="rows.saved[n.id]"
          :error="rows.error[n.id]"
          :read-only="settingsReadOnly"
          @toggle="rows.toggle(n.id)"
        >
          <div class="editor" @keydown.esc.stop.prevent="onNumberEsc(n)" @focusout="onNumberFocusout($event, n)">
            <div class="presets">
              <button
                v-for="p in n.presets"
                :key="p.v"
                type="button"
                class="preset"
                :class="{ active: valueFor(n) === p.v }"
                :aria-pressed="valueFor(n) === p.v ? 'true' : 'false'"
                @mousedown.prevent
                @click="choosePreset(n, p.v)"
              >{{ p.text }}</button>
            </div>
            <div class="number-field">
              <label :for="`setting-${n.id}-field`">{{ n.field }}</label>
              <input
                :id="`setting-${n.id}-field`"
                v-model="drafts[n.id]"
                type="text"
                inputmode="numeric"
                autocomplete="off"
                :aria-invalid="fieldError(n) ? 'true' : 'false'"
                :aria-describedby="`setting-${n.id}-help`"
                @keydown.enter="onNumberEnter($event, n)"
              >
            </div>
            <p v-if="fieldError(n)" class="field-error" role="alert">{{ fieldError(n) }}</p>
            <p :id="`setting-${n.id}-help`" class="field-help">{{ helpFor(n) }}</p>
          </div>
        </SettingRow>
      </template>
    </SettingsGroup>

    <SettingsGroup v-if="numbersIn('limits').length" :title="COPY.groups.limits">
      <template v-for="n in numbersIn('limits')" :key="n.id">
        <SettingRow
          :ref="el => setRef(n.id, el)"
          :id="n.id"
          :label="n.label"
          :description="n.description"
          :value="n.show(valueFor(n))"
          kind="edit"
          :open="rows.open === n.id"
          :busy="rows.busy[n.id]"
          :saved="rows.saved[n.id]"
          :error="rows.error[n.id]"
          :read-only="settingsReadOnly"
          @toggle="rows.toggle(n.id)"
        >
          <div class="editor" @keydown.esc.stop.prevent="onNumberEsc(n)" @focusout="onNumberFocusout($event, n)">
            <div class="presets">
              <button
                v-for="p in n.presets"
                :key="p.v"
                type="button"
                class="preset"
                :class="{ active: valueFor(n) === p.v }"
                :aria-pressed="valueFor(n) === p.v ? 'true' : 'false'"
                @mousedown.prevent
                @click="choosePreset(n, p.v)"
              >{{ p.text }}</button>
            </div>
            <div class="number-field">
              <label :for="`setting-${n.id}-field`">{{ n.field }}</label>
              <input
                :id="`setting-${n.id}-field`"
                v-model="drafts[n.id]"
                type="text"
                inputmode="numeric"
                autocomplete="off"
                :aria-invalid="fieldError(n) ? 'true' : 'false'"
                :aria-describedby="`setting-${n.id}-help`"
                @keydown.enter="onNumberEnter($event, n)"
              >
            </div>
            <p v-if="fieldError(n)" class="field-error" role="alert">{{ fieldError(n) }}</p>
            <p :id="`setting-${n.id}-help`" class="field-help">{{ helpFor(n) }}</p>
          </div>
        </SettingRow>
      </template>
    </SettingsGroup>

    <SettingsGroup v-if="has('compose_enabled')" :title="COPY.groups.writing">
      <SettingRow
        :ref="el => setRef('cover-letters', el)"
        id="cover-letters"
        label="Write cover letters"
        description="Writes one from your resume when a form requires it. Off: you're asked instead."
        kind="switch"
        :checked="current.compose_enabled"
        :busy="rows.busy['cover-letters']"
        :saved="rows.saved['cover-letters']"
        :error="rows.error['cover-letters']"
        :read-only="settingsReadOnly"
        @change="v => setSwitch('cover-letters', 'compose_enabled', v)"
      />
    </SettingsGroup>

    <SettingsGroup :title="COPY.groups.beforeYouApply">
      <SettingRow
        :ref="el => setRef('mailbox', el)"
        id="mailbox"
        label="Application mailbox"
        description="Reads the codes some sites email you during an application."
        kind="link"
        href="#/settings/accounts/apply-mailbox"
        :link-text="LINK_TEXT.accounts"
      >
        <template #value>
          <StateChip v-if="mailbox" :item="mailbox" label="Application mailbox" />
        </template>
      </SettingRow>
      <SettingRow
        v-if="summary"
        :ref="el => setRef('details', el)"
        id="details"
        label="Application details"
        description="Contact details, work rights and the answers forms ask for."
        :value="detailsText"
        kind="link"
        href="#/profile/details"
        :link-text="LINK_TEXT.profileEdit"
      />
      <SettingRow
        :ref="el => setRef('resume', el)"
        id="resume"
        label="Resume"
        description="The resume JobScraper reads, tailors and uploads."
        kind="link"
        href="#/profile/resume"
        :link-text="LINK_TEXT.profileEdit"
      />
    </SettingsGroup>
  </div>
</template>

<style scoped>
.apply-settings { display: block; }
.apply-intro {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between;
  gap: var(--space-2) var(--space-4); margin-bottom: var(--space-4);
}
.apply-intro-text { margin: 0; flex: 1 1 18rem; font-size: var(--text-sm); color: var(--text-2); text-wrap: pretty; }
.apply-note { margin: calc(-1 * var(--space-2)) 0 var(--space-4); font-size: var(--text-sm); color: var(--muted); }

.editor { display: grid; gap: var(--space-3); }

.mode-options { display: grid; gap: var(--space-2); }
.mode-option {
  display: grid; gap: 2px; padding: var(--space-2) var(--space-3); cursor: pointer;
  border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface-2);
}
.mode-option.active { background: var(--surface); border-color: var(--accent); box-shadow: var(--shadow-sm); }
.mode-option:has(input:focus-visible) { outline: 2px solid var(--focus); outline-offset: 2px; }
.mode-name { font-weight: 650; font-size: var(--text-sm); }
.mode-sub { color: var(--text-2); font-size: var(--text-sm); }

.confirm-auto {
  display: grid; gap: var(--space-2); padding: var(--space-3);
  background: var(--warn-soft); border-radius: var(--radius);
}
.confirm-auto p { margin: 0; font-size: var(--text-sm); }
.confirm-title { font-weight: 650; }
.confirm-buttons { display: flex; flex-wrap: wrap; gap: var(--space-2); }

.presets { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.preset { min-height: 2.25rem; }
.preset.active { border-color: var(--accent); background: var(--surface); box-shadow: var(--shadow-sm); font-weight: 650; }
.number-field { display: grid; gap: var(--space-1); justify-items: start; }
.number-field label { font-size: var(--text-sm); font-weight: 600; }
.number-field input { width: 8rem; }
.number-field input[aria-invalid='true'] { border-color: var(--danger); }
.field-error { margin: 0; font-size: var(--text-sm); color: var(--danger); }
.field-help { margin: 0; font-size: var(--text-sm); color: var(--muted); text-wrap: pretty; }

@media (max-width: 640px) {
  .apply-cta, .preset, .number-field input, .confirm-buttons button { min-height: var(--touch-min); }
  .mode-option { min-height: var(--touch-min); }
}
</style>
