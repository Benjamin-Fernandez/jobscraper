<script setup>
// One question an application asked and JobScraper could not answer
// (Q-30, questions_design.md section 10.2). A card is one `key`: every
// equivalent question the employers asked is grouped under it, and the owner
// answers it once. The card holds the typed answer itself and hands the finished
// payload up (`save`); the inbox adds the file's etag and makes the call.
//
// Widgets: a profile-gap question uses the profile field's own widget (the
// answer is saved in the profile, not in `extra`); a choice or multi question
// gets one picker per option set (a "variant"), because each employer words its
// options differently; everything else is one widget for the whole group.
import { computed, reactive, ref } from 'vue'
import { fieldId, findItem, isEmptyValue, optionList } from '../applicantForm.js'
import { plural } from '../format.js'
import FieldInput from './FieldInput.vue'

const props = defineProps({
  group: { type: Object, required: true },
  form: { type: Array, default: null },
  saving: { type: Boolean, default: false },
  error: { type: String, default: '' },
  conflict: { type: String, default: '' },     // '' | 'changed' | 'unreadable'
  answered: { type: Boolean, default: false },  // changing a saved answer
})
const emit = defineEmits(['save', 'dismiss', 'reload', 'cancel'])

const PRIVATE = 'Private: never sent to the AI'
const REASONS = {
  no_rule: 'Not in your profile',
  ungrounded: "The AI's answer couldn't be checked against your details",
  profile_gap: 'Missing from your profile',
  no_option_fits: "Your saved answer isn't one of this form's options",
  attestation_unclear: "A declaration JobScraper couldn't classify",
  conflict: 'Your work rights differ between the countries asked',
  compose_needed: "Needs a cover letter or motivation text JobScraper can't write yet",
}
// Fields that are one control per value; the rest fall back to the question's own kind.
const NOT_FOR_GAP = new Set(['entries', 'fixed', 'salary', 'country_bool_map'])
const TYPED = new Set(['text', 'email', 'url', 'digits', 'phone_cc', 'country', 'int', 'number', 'list_text', 'list_url'])

const g = computed(() => props.group)
const base = computed(() => `q-${fieldId(g.value.key)}`)
const labels = computed(() => g.value.labels ?? [])
const employers = computed(() => g.value.employers ?? [])
const variants = computed(() => g.value.variants ?? [])
const cur = computed(() => g.value.current ?? {})

// ---- what the card says ----
const reason = computed(() => {
  const code = g.value.reason ?? variants.value.find(v => v.reason)?.reason
  return REASONS[code] ?? ''
})
const meta = computed(() => {
  const asked = employers.value.length ? `Asked by ${employers.value.join(', ')}` : ''
  const n = g.value.waiting ?? 0
  const waiting = n > 0 ? `${plural(n, 'application')} waiting` : ''
  return [asked, waiting].filter(Boolean).join(' · ')
})
const alsoAsked = computed(() => labels.value.map(l => `“${l}”`).join(', '))

// ---- the widget ----
// A profile-gap question edits the profile's own field.
const gapField = computed(() => {
  if (!g.value.target_path) return null
  const hit = findItem(props.form ?? [], g.value.target_path)
  const field = hit && (hit.sub || hit.item)
  return field && !NOT_FOR_GAP.has(field.kind) ? field : null
})
const gapLabel = computed(() => (g.value.target_path
  ? (findItem(props.form ?? [], g.value.target_path)?.label ?? g.value.title)
  : ''))
const kind = computed(() => (gapField.value ? gapField.value.kind : g.value.kind))
const isPick = computed(() => !gapField.value && !g.value.target_path && (g.value.kind === 'choice' || g.value.kind === 'multi'))

const lister = typeof Intl !== 'undefined' && Intl.ListFormat ? new Intl.ListFormat('en', { style: 'long', type: 'conjunction' }) : null
const join = names => (lister ? lister.format(names) : names.join(', '))
function variantLabel(v, i) {
  const names = v.employers ?? (v.employer ? [v.employer] : employers.value.length === 1 && variants.value.length === 1 ? employers.value : [])
  if (names.length) return `${join(names)}'s options`
  return variants.value.length > 1 ? `Option set ${i + 1}` : 'Options as asked'
}

// ---- the typed answer ----
function start() {
  const d = { value: null, picks: {}, employer: '' }
  if (isPick.value) {
    for (const v of variants.value) {
      const chosen = optionList(v.options).filter(o => (cur.value.picks ?? []).includes(o.norm)).map(o => o.label)
      d.picks[v.question_id] = g.value.kind === 'choice' ? chosen.slice(0, 1) : chosen
    }
  } else if (g.value.kind === 'text' && !gapField.value) {
    d.value = cur.value.value ?? ''
  } else {
    d.value = cur.value.value ?? null
  }
  return d
}
const draft = reactive(start())
const mine = ref('')   // the card's own complaint (nothing chosen yet)

const pickOf = v => (g.value.kind === 'choice' ? draft.picks[v.question_id]?.[0] ?? null : draft.picks[v.question_id] ?? [])
function setPick(v, value) {
  draft.picks[v.question_id] = g.value.kind === 'choice' ? (value ? [value] : []) : value
}

function problem() {
  if (isPick.value) {
    return Object.values(draft.picks).some(p => p.length)
      ? '' : (g.value.kind === 'multi' ? 'Pick at least one option.' : 'Choose an answer first.')
  }
  const v = draft.value
  const empty = v === null || v === undefined || (typeof v === 'string' && !v.trim()) || (Array.isArray(v) && !v.length)
  if (!empty) return ''
  if (kind.value === 'date' || kind.value === 'month') return 'Pick a date first.'
  return TYPED.has(kind.value) ? 'Type an answer first.' : 'Choose an answer first.'
}

function save() {
  mine.value = problem()
  if (mine.value) return
  const body = { key: g.value.key }
  if (draft.employer && !g.value.target_path) body.employer = draft.employer
  if (isPick.value) {
    body.picks = Object.fromEntries(Object.entries(draft.picks).filter(([, p]) => p.length))
  } else {
    body.value = typeof draft.value === 'string' ? draft.value.trim() : draft.value
  }
  emit('save', body)
}
</script>

<template>
  <article class="q-card surface" :aria-labelledby="`${base}-title`" :data-key="group.key">
    <header class="q-head">
      <h3 :id="`${base}-title`" class="q-title">{{ group.title }}</h3>
      <span v-if="group.sensitive" class="tag private">{{ PRIVATE }}</span>
      <span v-if="reason && !answered" class="chip q-reason">{{ reason }}</span>
    </header>
    <p v-if="meta" class="q-meta muted">{{ meta }}</p>
    <p v-if="group.description" class="q-desc muted">{{ group.description }}</p>
    <p v-if="group.target_path" class="q-gap">This is your profile's {{ gapLabel }}. Your answer is saved there.</p>
    <p v-if="labels.length > 1" class="q-also">Also asked as: {{ alsoAsked }}</p>
    <p v-else-if="labels.length === 1" class="q-label">“{{ labels[0] }}”</p>

    <div v-if="isPick" class="q-pickers">
      <div v-for="(v, i) in variants" :key="v.question_id" class="q-picker">
        <span :id="`${base}-v${v.question_id}`" class="q-field-label">{{ variantLabel(v, i) }}</span>
        <FieldInput
          :id="`${base}-pick-${v.question_id}`"
          :kind="group.kind"
          :model-value="pickOf(v)"
          :options="optionList(v.options).map(o => o.label)"
          :labelledby="`${base}-v${v.question_id}`"
          @update:model-value="setPick(v, $event)"
        />
      </div>
    </div>
    <div v-else class="q-answer">
      <label v-if="!['yes_no', 'bool'].includes(kind)" :id="`${base}-ans-label`" class="q-field-label" :for="`${base}-ans`">Your answer</label>
      <span v-else :id="`${base}-ans-label`" class="q-field-label">Your answer</span>
      <FieldInput
        :id="`${base}-ans`"
        :kind="kind"
        :model-value="draft.value"
        :options="gapField?.options || []"
        :multiline="kind === 'text' && !gapField"
        :labelledby="['yes_no', 'bool', 'multi'].includes(kind) ? `${base}-ans-label` : ''"
        @update:model-value="draft.value = $event"
      />
    </div>

    <div v-if="employers.length && !group.target_path" class="q-scope">
      <label :for="`${base}-scope`">Use this answer for:</label>
      <select :id="`${base}-scope`" v-model="draft.employer">
        <option value="">All employers</option>
        <option v-for="e in employers" :key="e" :value="e">{{ e }}</option>
      </select>
    </div>

    <p v-if="mine" class="q-error" role="alert">{{ mine }}</p>
    <p v-if="error" class="q-error" role="alert">{{ error }}</p>
    <div v-if="conflict" class="notice error q-conflict" role="alert">
      <p v-if="conflict === 'changed'">
        This file changed since you opened it, in another tab or by hand. Reload to get the latest, then make your change again.
      </p>
      <p v-else>JobScraper can't read data/applicant.yaml. Fix the file by hand. Nothing will be saved over it until then.</p>
      <button type="button" class="q-reload" @click="emit('reload')">Reload</button>
    </div>

    <div class="q-buttons">
      <button type="button" class="primary q-save" :disabled="saving" @click="save">{{ saving ? 'Saving…' : 'Save answer' }}</button>
      <button v-if="!answered" type="button" class="q-dismiss" :disabled="saving" @click="emit('dismiss')">I'll answer this one by hand</button>
      <button v-else type="button" class="ghost q-cancel" :disabled="saving" @click="emit('cancel')">Cancel</button>
    </div>
  </article>
</template>

<style scoped>
.q-card { display: grid; gap: var(--space-3); padding: var(--space-4) var(--space-5); align-content: start; }
.q-head { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2) var(--space-3); }
.q-title { margin: 0; font-size: var(--text-md); font-weight: 650; }
.q-reason { background: var(--warn-soft); color: var(--warn); border-color: color-mix(in srgb, var(--warn) 30%, transparent); }
.q-meta, .q-desc { margin: 0; font-size: var(--text-sm); }
.q-gap, .q-also, .q-label { margin: 0; font-size: var(--text-sm); color: var(--text-2); overflow-wrap: anywhere; }
.q-label { font-style: italic; }
.q-answer, .q-picker { display: grid; gap: var(--space-1); }
.q-pickers { display: grid; gap: var(--space-3); }
.q-field-label { font-size: var(--text-sm); font-weight: 600; }
.q-scope { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); font-size: var(--text-sm); }
.q-error { margin: 0; font-size: var(--text-sm); color: var(--danger); }
.q-conflict { margin: 0; }
.q-buttons { display: flex; flex-wrap: wrap; gap: var(--space-2); }
</style>
