<script setup>
// One input per kind, shared by the Application details form and the questions
// inbox (questions_design.md section 10.3). It renders only the control: the
// caller owns the visible label, the tags, the help text and the error line,
// and links them with `labelledby` / `describedby` / `invalid`.
//
// Kinds - the form's (text email phone_cc digits int date month bool enum
// country url list_text list_url entries salary country_bool_map fixed) and an
// application question's (yes_no choice multi text date number). `text` is a
// single line unless `multiline` is set (a question's answer is a textarea).
//
// The value goes out as the type the server stores: a cleared number, date or
// choice is null, never an empty string the validator would refuse.
//
// Numbers are text boxes (Q71-05): a number box drops "4,500" to nothing in
// Firefox and blocks the comma in Chrome. Here "4,500" is 4500, and text that
// is not a number goes out as typed so the server's message shows.
import { computed, nextTick, ref, watch } from 'vue'
import { optionList, parseNumberText } from '../applicantForm.js'
import Icon from './Icon.vue'

const props = defineProps({
  kind: { type: String, required: true },
  modelValue: { default: undefined },
  id: { type: String, required: true },
  labelledby: { type: String, default: '' },
  describedby: { type: String, default: '' },
  invalid: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  options: { type: Array, default: () => [] },
  multiline: { type: Boolean, default: false },
  placeholder: { type: String, default: '' },
  // entries: the fields of one entry, the list's path (nested error lookup),
  // a name for the Add / Remove buttons, and which entries came from the resume.
  sub: { type: Array, default: () => [] },
  path: { type: String, default: '' },
  label: { type: String, default: '' },
  fromResume: { type: Array, default: () => [] },
  errors: { type: Object, default: () => ({}) },
  // salary: a person may have no current salary (the value is then null).
  nullable: { type: Boolean, default: false },
  // fixed: the sentence to show.
  fixedText: { type: String, default: '' },
  // The browser's autofill token (WCAG 1.3.5); `off` unless the form names one.
  autocomplete: { type: String, default: 'off' },
  // yes_no: say "Not set" while there is no answer, and offer Clear (D-91: null
  // means "ask me") when `clearable`.
  showUnset: { type: Boolean, default: false },
  clearable: { type: Boolean, default: false },
  // country_bool_map: the countries its rows pick from ({value, label}).
  countryOptions: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue'])

const set = v => emit('update:modelValue', v)
const aria = computed(() => ({
  'aria-labelledby': props.labelledby || undefined,
  'aria-describedby': props.describedby || undefined,
  'aria-invalid': props.invalid ? 'true' : undefined,
}))
const opts = computed(() => optionList(props.options))

// ---- single-line and numeric inputs ----
const onText = e => set(e.target.value)
const onNullable = e => set(e.target.value === '' ? null : e.target.value)
// What is typed into a number box, kept while it still means the value, so
// "4,500" is not rewritten to "4500" under the cursor. A value set from outside
// (Discard, a reload) shows as itself.
const typed = ref(null)
const decimals = computed(() => props.kind === 'number')
function numText(v) {
  if (typed.value !== null && parseNumberText(typed.value, { decimals: decimals.value }) === v) return typed.value
  return v ?? ''
}
function onNumber(e, emitValue = set) {
  typed.value = e.target.value
  emitValue(parseNumberText(typed.value, { decimals: decimals.value }))
}
const onUpper = e => set(e.target.value.toUpperCase())

// ---- country: a list to pick from when the form sends one (Q71-02) ----
const countries = computed(() => optionList(props.options))
const onCountry = e => set(e.target.value === '' ? null : e.target.value)
const hintId = computed(() => `${props.id}-fmt`)
const countryAria = computed(() => ({
  ...aria.value,
  'aria-describedby': [props.describedby, hintId.value].filter(Boolean).join(' '),
}))

// ---- enum / choice ----
const onSelect = e => set(e.target.value === '' ? null : e.target.value)
// A value the list does not offer (a hand edit) stays visible instead of vanishing.
const unlisted = computed(() => {
  const v = props.modelValue
  return v !== null && v !== undefined && v !== '' && !opts.value.some(o => o.value === v) ? String(v) : ''
})

// ---- multi (checkboxes) ----
const picked = computed(() => (Array.isArray(props.modelValue) ? props.modelValue : []))
function togglePick(value, on) {
  set(on ? [...picked.value, value] : picked.value.filter(x => x !== value))
}

// ---- list_text / list_url (chips with an add box) ----
const draft = ref('')
const list = computed(() => (Array.isArray(props.modelValue) ? props.modelValue : []))
function addChip() {
  const t = draft.value.trim().replace(/\s+/g, ' ')
  draft.value = ''
  if (t && !list.value.includes(t)) set([...list.value, t])
}
const removeChip = t => set(list.value.filter(x => x !== t))

// ---- entries (education, experience, languages) ----
const entries = computed(() => (Array.isArray(props.modelValue) ? props.modelValue : []))
const subId = (i, s) => `${props.id}-${i}-${s.path.replace(/[^a-z0-9]+/gi, '-')}`
// An edited entry is the owner's now (Q71-07): `from_resume` goes false, so the
// "please check" tag clears and a later refresh from the resume (Q-44) leaves it.
function setEntry(i, key, value) {
  set(entries.value.map((e, j) => {
    if (j !== i) return e
    const next = { ...e, [key]: value }
    if ('from_resume' in e) next.from_resume = false
    return next
  }))
}
async function addEntry() {
  const fresh = {}
  for (const s of props.sub) fresh[s.path] = s.kind === 'text' || s.kind === 'digits' ? '' : null
  set([...entries.value, fresh])
  await nextTick()
  // After the emit the list already holds the new entry: it is the last one (Q71-11).
  document.getElementById(subId(entries.value.length - 1, props.sub[0] || { path: '' }))?.focus?.()
}
const removeEntry = i => set(entries.value.filter((_, j) => j !== i))
const entryFromResume = i => entries.value[i]?.from_resume !== false
  && props.fromResume.some(p => p === `${props.path}[${i}]` || p.startsWith(`${props.path}[${i}].`))
const entryName = i => `${props.label || 'Entry'} ${i + 1}`
const addText = computed(() => (props.label ? `Add ${props.label.toLowerCase()}` : 'Add an entry'))

// ---- salary ----
// A required salary (expected) always shows its inputs, even while the value is
// null or missing (Q-71: the grid used to vanish, leaving no way to enter one).
// The defaults are only shown; they are written on the first edit, so an
// untouched field stays unset ("Needed"). Only a nullable salary (current) can
// be "I don't have one", which hides the inputs.
const SALARY_DEFAULTS = { amount: null, currency: 'SGD', period: 'monthly' }
const salary = computed(() => (props.modelValue && typeof props.modelValue === 'object' ? props.modelValue : null))
const noSalary = computed(() => props.nullable && salary.value === null)
const shownSalary = computed(() => salary.value || SALARY_DEFAULTS)
const setSalary = (key, v) => set({ ...shownSalary.value, [key]: v })
function toggleNoSalary(none) {
  set(none ? null : { amount: null, currency: 'SGD', period: 'monthly' })
}

// ---- country_bool_map ({SG: true, default: true}) ----
// Rows are kept here, so a half-typed country code is not lost while the map
// (which cannot hold an empty key) goes out without it.
const toRows = m => Object.entries(m && typeof m === 'object' ? m : {}).filter(([k]) => k !== 'default').map(([k, v]) => ({ k, v }))
const rows = ref(toRows(props.modelValue))
const defaultValue = computed(() => (props.modelValue && typeof props.modelValue === 'object' ? props.modelValue.default : undefined))
function mapOf(rowList, def) {
  const out = {}
  for (const r of rowList) if (/^[A-Z]{2}$/.test(r.k) && typeof r.v === 'boolean') out[r.k] = r.v
  if (typeof def === 'boolean') out.default = def
  return out
}
function sendRows() {
  set(mapOf(rows.value, defaultValue.value))
}
watch(() => props.modelValue, v => {
  if (props.kind !== 'country_bool_map') return
  if (JSON.stringify(mapOf(rows.value, defaultValue.value)) !== JSON.stringify(v && typeof v === 'object' ? v : {})) {
    rows.value = toRows(v)
  }
}, { deep: true })
const mapCountries = computed(() => optionList(props.countryOptions))
const codeOk = k => /^[A-Z]{2}$/.test(k || '')
const rowError = r => (codeOk(r.k) ? '' : mapCountries.value.length ? 'Choose a country' : 'Type a 2-letter country code, such as US')
const triState = v => (v === true ? 'true' : v === false ? 'false' : '')
const fromTri = t => (t === 'true' ? true : t === 'false' ? false : null)
function setDefault(t) {
  set(mapOf(rows.value, fromTri(t) ?? undefined))
}
function setRow(i, key, value) {
  rows.value[i][key] = value
  sendRows()
}
async function addRow() {
  rows.value.push({ k: '', v: false })
  await nextTick()
  document.getElementById(`${props.id}-code-${rows.value.length - 1}`)?.focus?.()
}
function removeRow(i) {
  rows.value.splice(i, 1)
  sendRows()
}
</script>

<template>
  <div class="fi" :data-kind="kind">
    <!-- text, email, url, digits, phone code, country: one line -->
    <textarea
      v-if="multiline && (kind === 'text' || kind === 'multi_line')"
      :id="id"
      class="area"
      rows="3"
      maxlength="2000"
      :value="modelValue ?? ''"
      :disabled="disabled"
      :placeholder="placeholder"
      v-bind="aria"
      @input="onText"
    />
    <input
      v-else-if="kind === 'text' || kind === 'email' || kind === 'url' || kind === 'digits' || kind === 'phone_cc'"
      :id="id"
      :type="kind === 'email' ? 'email' : kind === 'url' ? 'url' : 'text'"
      :inputmode="kind === 'digits' ? 'numeric' : kind === 'phone_cc' ? 'tel' : undefined"
      :maxlength="kind === 'phone_cc' ? 4 : 300"
      :placeholder="kind === 'phone_cc' ? '+65' : placeholder"
      :autocomplete="autocomplete"
      :value="modelValue ?? ''"
      :disabled="disabled"
      v-bind="aria"
      @input="onText"
    >
    <!-- country: pick from the list (type "Sing" to jump there); without a list, the code -->
    <select
      v-else-if="kind === 'country' && countries.length"
      :id="id"
      :value="modelValue ?? ''"
      :disabled="disabled"
      :autocomplete="autocomplete === 'off' ? 'country' : autocomplete"
      v-bind="aria"
      @change="onCountry"
    >
      <option value="">Choose…</option>
      <option v-if="unlisted" :value="unlisted">{{ unlisted }}</option>
      <option v-for="o in countries" :key="String(o.value)" :value="o.value">{{ o.label }}</option>
    </select>
    <template v-else-if="kind === 'country'">
      <input
        :id="id"
        type="text"
        class="narrow upper"
        placeholder="SG"
        :autocomplete="autocomplete"
        :value="modelValue ?? ''"
        :disabled="disabled"
        v-bind="countryAria"
        @input="onUpper"
      >
      <p :id="hintId" class="hint">2-letter code, e.g. SG for Singapore</p>
    </template>

    <!-- numbers: text boxes that read "4,500" as 4500; empty means null -->
    <input
      v-else-if="kind === 'int' || kind === 'number'"
      :id="id"
      type="text"
      class="narrow num"
      :inputmode="kind === 'int' ? 'numeric' : 'decimal'"
      autocomplete="off"
      :value="numText(modelValue)"
      :disabled="disabled"
      v-bind="aria"
      @input="onNumber"
      @blur="typed = null"
    >
    <input
      v-else-if="kind === 'date' || kind === 'month'"
      :id="id"
      :type="kind"
      :value="modelValue ?? ''"
      :disabled="disabled"
      v-bind="aria"
      @input="onNullable"
    >

    <!-- a yes/no that may be unset: a switch; the question's yes_no: two radios -->
    <label v-else-if="kind === 'bool'" class="switch">
      <input
        :id="id"
        type="checkbox"
        role="switch"
        :checked="modelValue === true"
        :disabled="disabled"
        v-bind="aria"
        @change="set($event.target.checked)"
      >
      <span :aria-hidden="modelValue === true || modelValue === false ? 'true' : undefined">{{ modelValue === true ? 'Yes' : modelValue === false ? 'No' : 'Not set' }}</span>
    </label>
    <div v-else-if="kind === 'yes_no'" :id="id" class="radios" role="radiogroup" v-bind="aria">
      <label><input type="radio" :name="id" :checked="modelValue === true" :disabled="disabled" @change="set(true)"> Yes</label>
      <label><input type="radio" :name="id" :checked="modelValue === false" :disabled="disabled" @change="set(false)"> No</label>
      <span v-if="showUnset && modelValue !== true && modelValue !== false" class="unset">Not set</span>
      <button
        v-else-if="clearable && (modelValue === true || modelValue === false)"
        type="button"
        class="link clear"
        :disabled="disabled"
        @click="set(null)"
      >Clear</button>
    </div>

    <!-- one of a list -->
    <select
      v-else-if="kind === 'enum' || kind === 'choice'"
      :id="id"
      :value="modelValue ?? ''"
      :disabled="disabled"
      v-bind="aria"
      @change="onSelect"
    >
      <option value="">Choose…</option>
      <option v-if="unlisted" :value="unlisted">{{ unlisted }}</option>
      <option v-for="o in opts" :key="String(o.value)" :value="o.value">{{ o.label }}</option>
    </select>

    <!-- several of a list -->
    <div v-else-if="kind === 'multi'" :id="id" class="checks" role="group" v-bind="aria">
      <label v-for="o in opts" :key="String(o.value)">
        <input type="checkbox" :checked="picked.includes(o.value)" :disabled="disabled" @change="togglePick(o.value, $event.target.checked)">
        {{ o.label }}
      </label>
    </div>

    <!-- a list of short texts -->
    <div v-else-if="kind === 'list_text' || kind === 'list_url'" class="chips-input" role="group" v-bind="aria">
      <ul v-if="list.length" class="chip-list">
        <li v-for="t in list" :key="t" class="chip">
          <span>{{ t }}</span>
          <button type="button" class="chip-x" :disabled="disabled" :aria-label="`Remove ${t}`" @click="removeChip(t)">
            <Icon name="x" :size="13" />
          </button>
        </li>
      </ul>
      <div class="add">
        <input
          :id="id"
          v-model="draft"
          :type="kind === 'list_url' ? 'url' : 'text'"
          autocomplete="off"
          :placeholder="kind === 'list_url' ? 'https://…' : 'Type one and press Enter'"
          :disabled="disabled"
          :aria-labelledby="labelledby || undefined"
          :aria-describedby="describedby || undefined"
          @keydown.enter.prevent="addChip"
          @blur="addChip"
        >
        <button type="button" :disabled="disabled || !draft.trim()" @click="addChip"><Icon name="plus" /> Add</button>
      </div>
    </div>

    <!-- repeatable fieldsets -->
    <div v-else-if="kind === 'entries'" :id="id" class="entries" role="group" v-bind="aria">
      <fieldset v-for="(entry, i) in entries" :key="i" class="entry">
        <legend>
          <span class="entry-name">{{ entryName(i) }}</span>
          <span v-if="entryFromResume(i)" class="tag resume">From your resume, please check</span>
        </legend>
        <!-- Outside the legend, so the group's name stays "School 1"; shown at the legend row's end. -->
        <button type="button" class="ghost remove-entry" :disabled="disabled" :aria-label="`Remove ${entryName(i)}`" @click="removeEntry(i)">Remove</button>
        <div class="entry-grid">
          <div v-for="s in sub" :key="s.path" class="entry-field" :class="{ wide: s.multiline || s.path === 'description' }">
            <label :id="`${subId(i, s)}-label`" :for="subId(i, s)">{{ s.label }}</label>
            <FieldInput
              :id="subId(i, s)"
              :kind="s.kind"
              :model-value="entry[s.path]"
              :options="s.options || []"
              :multiline="!!s.multiline || s.path === 'description'"
              :disabled="disabled"
              :invalid="!!errors[`${path}[${i}].${s.path}`]"
              :describedby="errors[`${path}[${i}].${s.path}`] ? `${subId(i, s)}-err` : (s.help ? `${subId(i, s)}-help` : '')"
              @update:model-value="setEntry(i, s.path, $event)"
            />
            <p v-if="s.help" :id="`${subId(i, s)}-help`" class="hint">{{ s.help }}</p>
            <p v-else-if="path === 'experience' && s.path === 'end'" class="hint">Leave empty if you still work here.</p>
            <p v-if="errors[`${path}[${i}].${s.path}`]" :id="`${subId(i, s)}-err`" class="field-error">{{ errors[`${path}[${i}].${s.path}`] }}</p>
          </div>
        </div>
        <p v-if="errors[`${path}[${i}]`]" class="field-error">{{ errors[`${path}[${i}]`] }}</p>
      </fieldset>
      <button type="button" class="add-entry" :disabled="disabled" @click="addEntry"><Icon name="plus" /> {{ addText }}</button>
    </div>

    <!-- amount, currency, period, negotiable -->
    <div v-else-if="kind === 'salary'" class="salary" role="group" v-bind="aria">
      <label v-if="nullable" class="check">
        <input type="checkbox" :checked="noSalary" :disabled="disabled" @change="toggleNoSalary($event.target.checked)">
        I don't have one
      </label>
      <div v-if="!noSalary" class="salary-grid">
        <div>
          <label :for="id">Amount</label>
          <input
            :id="id"
            type="text"
            class="narrow num"
            inputmode="numeric"
            autocomplete="off"
            :value="numText(shownSalary.amount)"
            :disabled="disabled"
            :aria-invalid="invalid ? 'true' : undefined"
            :aria-describedby="describedby || undefined"
            @input="onNumber($event, v => setSalary('amount', v))"
            @blur="typed = null"
          >
        </div>
        <div>
          <label :for="`${id}-currency`">Currency</label>
          <input
            :id="`${id}-currency`"
            type="text"
            class="narrow upper"
            maxlength="3"
            placeholder="SGD"
            autocomplete="off"
            :value="shownSalary.currency ?? ''"
            :disabled="disabled"
            @input="setSalary('currency', $event.target.value.toUpperCase())"
          >
        </div>
        <div>
          <label :for="`${id}-period`">Period</label>
          <select :id="`${id}-period`" :value="shownSalary.period ?? ''" :disabled="disabled" @change="setSalary('period', $event.target.value || null)">
            <option value="">Choose…</option>
            <option value="monthly">per month</option>
            <option value="annual">per year</option>
          </select>
        </div>
        <label v-if="!nullable" class="check">
          <input type="checkbox" :checked="shownSalary.negotiable === true" :disabled="disabled" @change="setSalary('negotiable', $event.target.checked)">
          Negotiable
        </label>
      </div>
    </div>

    <!-- {SG: true, default: true}: a default, and the countries that differ -->
    <div v-else-if="kind === 'country_bool_map'" class="cbm" role="group" v-bind="aria">
      <div class="cbm-default">
        <label :for="id">Default</label>
        <select :id="id" :value="triState(defaultValue)" :disabled="disabled" @change="setDefault($event.target.value)">
          <option value="">Not set</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      </div>
      <ul v-if="rows.length" class="cbm-rows">
        <li v-for="(r, i) in rows" :key="i">
          <div class="cbm-row">
            <label class="visually-hidden" :for="`${id}-code-${i}`">Country</label>
            <select
              v-if="mapCountries.length"
              :id="`${id}-code-${i}`"
              :value="r.k"
              :disabled="disabled"
              :aria-invalid="rowError(r) ? 'true' : undefined"
              :aria-describedby="rowError(r) ? `${id}-code-${i}-err` : undefined"
              @change="setRow(i, 'k', $event.target.value)"
            >
              <option value="">Choose…</option>
              <option v-if="r.k && !mapCountries.some(o => o.value === r.k)" :value="r.k">{{ r.k }}</option>
              <option v-for="o in mapCountries" :key="String(o.value)" :value="o.value">{{ o.label }}</option>
            </select>
            <input
              v-else
              :id="`${id}-code-${i}`"
              type="text"
              class="narrow upper"
              maxlength="2"
              placeholder="US"
              autocomplete="off"
              :value="r.k"
              :disabled="disabled"
              :aria-invalid="rowError(r) ? 'true' : undefined"
              :aria-describedby="rowError(r) ? `${id}-code-${i}-err` : undefined"
              @input="setRow(i, 'k', $event.target.value.toUpperCase())"
            >
            <label class="visually-hidden" :for="`${id}-val-${i}`">Answer for {{ r.k || 'this country' }}</label>
            <select :id="`${id}-val-${i}`" :value="triState(r.v)" :disabled="disabled" @change="setRow(i, 'v', fromTri($event.target.value) ?? false)">
              <option value="true">Yes</option>
              <option value="false">No</option>
            </select>
            <button type="button" class="ghost" :disabled="disabled" :aria-label="`Remove ${r.k || 'this country'}`" @click="removeRow(i)">Remove</button>
          </div>
          <p v-if="rowError(r)" :id="`${id}-code-${i}-err`" class="field-error">{{ rowError(r) }}</p>
        </li>
      </ul>
      <button type="button" :disabled="disabled" @click="addRow"><Icon name="plus" /> Add a country</button>
    </div>

    <!-- a fixed answer: shown, not editable -->
    <p v-else-if="kind === 'fixed'" :id="id" class="fixed" v-bind="aria">{{ fixedText || 'Fixed.' }}</p>

    <!-- a kind this build does not know: say so, never drop the value -->
    <p v-else :id="id" class="fixed">This field type ({{ kind }}) can't be edited here. Edit it in data/applicant.yaml.</p>
  </div>
</template>

<style scoped>
.fi { min-width: 0; }
.fi input:not([type='checkbox']):not([type='radio']), .fi select, .fi textarea {
  min-height: var(--control-h);
  padding: 0 var(--space-3);
  background: var(--surface);
  border: 1px solid var(--control-border, var(--border-strong));
  border-radius: var(--radius);
  max-width: 100%;
}
.fi input:not([type='checkbox']):not([type='radio']):not(.narrow), .fi textarea { width: min(100%, 28rem); }
.fi textarea { width: min(100%, 36rem); padding: var(--space-2) var(--space-3); line-height: var(--leading); resize: vertical; }
.fi input[aria-invalid='true'], .fi select[aria-invalid='true'], .fi textarea[aria-invalid='true'] { border-color: var(--danger); }
.fi input:focus-visible, .fi select:focus-visible, .fi textarea:focus-visible {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent);
}
.narrow { width: 8rem; }
.num { font-family: var(--mono); font-variant-numeric: tabular-nums; }
.upper { text-transform: uppercase; }
.fi label { font-size: var(--text-sm); }
.switch, .check, .radios label, .checks label { display: inline-flex; align-items: center; gap: var(--space-2); cursor: pointer; }
.radios { display: inline-flex; flex-wrap: wrap; align-items: center; gap: var(--space-2) var(--space-4); min-height: var(--control-h); }
.radios label { min-height: 1.5rem; }
.unset { font-size: var(--text-sm); color: var(--muted); }
.checks { display: grid; gap: var(--space-1); }
.chip-list { list-style: none; margin: 0 0 var(--space-2); padding: 0; display: flex; flex-wrap: wrap; gap: var(--space-1); }
.chip { gap: 2px; padding-right: 2px; font-size: var(--text-sm); }
.chip-x {
  min-height: 0; width: 1.5rem; height: 1.5rem; padding: 0; border: none; box-shadow: none;
  background: transparent; color: var(--muted); border-radius: 999px;
}
.chip-x:hover:not(:disabled) { background: var(--danger-soft); color: var(--danger); }
.add { display: flex; gap: var(--space-2); }
.add input { flex: 1; min-width: 0; }
.entries { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-3); justify-items: start; }
/* A block, not a grid: the floated legend is then a normal row at the top (Q71-21). */
.entry { position: relative; width: 100%; margin: 0; padding: var(--space-3) var(--space-4); border: 1px solid var(--border); border-radius: var(--radius); display: block; }
.entry > .entry-grid, .entry > .field-error { clear: both; margin-top: var(--space-3); }
/* The legend row: the entry's name, its tag, and Remove at the far end (Q71-21). */
.entry legend {
  float: left; width: 100%; padding: 0 5rem 0 0; min-height: 1.75rem;
  display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2);
  font-size: var(--text-sm); font-weight: 600;
}
.entry legend .tag { margin-left: 0; }
.remove-entry {
  position: absolute; top: var(--space-3); right: var(--space-4);
  min-height: 1.75rem; padding: 0 var(--space-2); font-weight: 500;
}
.clear { min-height: 1.5rem; }
.entry-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(15rem, 100%), 1fr)); gap: var(--space-3) var(--space-4); width: 100%; }
.entry-field { display: grid; gap: var(--space-1); align-content: start; min-width: 0; }
.entry-field.wide { grid-column: 1 / -1; }
.hint { margin: 0; font-size: var(--text-xs); color: var(--muted); }
.field-error { margin: 0; font-size: var(--text-sm); color: var(--danger); }
.salary { display: grid; gap: var(--space-2); }
.salary-grid { display: flex; flex-wrap: wrap; align-items: flex-end; gap: var(--space-3); }
.salary-grid > div { display: grid; gap: var(--space-1); }
.cbm { display: grid; gap: var(--space-2); justify-items: start; }
.cbm-default { display: flex; align-items: center; gap: var(--space-2); }
.cbm-rows { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }
.cbm-rows li { display: grid; gap: var(--space-1); }
.cbm-row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); }
.fixed { margin: 0; font-size: var(--text-sm); color: var(--text-2); }
.tag { margin-left: var(--space-2); }
</style>
