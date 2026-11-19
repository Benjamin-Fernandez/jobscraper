<script setup>
// "What was sent" / "What was filled" for one auto-apply attempt (Q-127 U2, D-215;
// q127_profile_questions_design B.2b and the B.4 copy table). The owner no longer answers a
// company's questions on the Profile page; every answer JobScraper gave is shown here, with
// the application, and one answer can be corrected for next time.
//
//   <WhatWasSent :job-id="row.job_id" :attempt-id="row.last_attempt.id" :sent="true"
//     :employer-name="row.company" @close="..." @loaded="({notAnswered}) => ..."
//     @saved="({ready}) => ..." />
//
// The rows, the basis words, the refusals and the badges all come from
// `GET /api/applications/{job}/attempts/{attempt}/answers`; the only copy kept here is what
// the payload does not carry (the title, the filter, the refusal sentences by code). A
// correction is `POST .../answers/{id}/remember` and NEVER starts an application: "Try again"
// stays the row's own button. The editor takes the field's own kind (attempts.js `fieldKind`):
// Yes/No, one or several of the options the form offered, text, number or date. The scope box
// "Only for applications to {employer}" is checked by default (H3).
//
// Focus: the heading takes focus when the panel opens (the row returns it to its trigger on
// close); Escape closes the editor first, then the panel. Status is always in words.
import { computed, nextTick, onMounted, ref } from 'vue'
import { describeError, getApplicant, getAttemptAnswers, problemOf, rememberAnswer } from '../api.js'
import {
  FILLED_TITLE, SAVED_SENT, SAVED_STOPPED, SENT_TITLE, answerBody, correctionLabel, emptyAction, fieldCounts,
  fieldKind, fieldTitle, filterFields, openAnswer, refusalCopy, sentSubLine, startValue, wasSent,
} from '../attempts.js'
import Segmented from '../ui/Segmented.vue'

// A choice with more options than this is a drop-down; fewer are radios.
const LIST_MAX = 6

const props = defineProps({
  jobId: { type: [String, Number], required: true },
  attemptId: { type: [String, Number], required: true },
  // What the row already knows, for the heading while the answers load.
  sent: { type: Boolean, default: false },
  // The application's own employer name (the payload's `employer` wins once it is there).
  employerName: { type: String, default: '' },
})
const emit = defineEmits(['close', 'loaded', 'saved'])

let uid = 0
const base = `wws-${++uid}-${Math.random().toString(36).slice(2, 7)}`
const headId = `${base}-title`

const phase = ref('loading')          // loading | ok | error
const data = ref(null)
const error = ref('')
const filter = ref('all')
const note = ref('')                  // a panel-level message (a change elsewhere, a refusal)
const live = ref('')                  // announced, not shown
const headRef = ref(null)

const attempt = computed(() => data.value?.attempt ?? null)
const fields = computed(() => data.value?.fields ?? [])
const sent = computed(() => (attempt.value ? wasSent(attempt.value.kind) : props.sent))
const title = computed(() => (sent.value ? SENT_TITLE : FILLED_TITLE))
const employer = computed(() => String(data.value?.employer || props.employerName || '').trim())
const counts = computed(() => fieldCounts(fields.value))
const sub = computed(() => sentSubLine(attempt.value, counts.value.assumed))
const shown = computed(() => filterFields(fields.value, filter.value))
// Unlabelled fields are numbered over the whole list (not the filtered one), so "Field with no
// label 3" is the same row under every filter.
const blankNumber = computed(() => {
  const out = {}
  let n = 0
  for (const f of fields.value) if (!String(f.label ?? '').trim()) out[f.id] = ++n
  return out
})
const titleOf = f => fieldTitle(f, blankNumber.value[f.id] ?? 0)
// Why a field was left empty (D-229): the contract's sentence and hint, and the link the hint
// points at. A not-answered protected field shows these INSTEAD of the "follows your details"
// refusal (that sentence is for answered fields, and sent the owner in a circle).
const hasWhy = f => f.status === 'not_answered' && Boolean(String(f.reason ?? '').trim() || String(f.reason_hint ?? '').trim())
const whyLink = f => emptyAction(f)
const showRefusal = f => !f.can_remember && !(hasWhy(f) && f.refusal === 'follows_your_details') && refusalView(f)
const filterOptions = computed(() => [
  { value: 'all', label: `All ${counts.value.all}`, ariaLabel: `All ${counts.value.all} answers` },
  { value: 'assumed', label: `Assumed ${counts.value.assumed}`, ariaLabel: `${counts.value.assumed} assumed answers`, disabled: counts.value.assumed === 0 },
  { value: 'not_answered', label: `Not answered ${counts.value.notAnswered}`, ariaLabel: `${counts.value.notAnswered} not answered`, disabled: counts.value.notAnswered === 0 },
])

// ---- loading ----

let seq = 0
async function load(quiet = false) {
  const mine = ++seq
  if (!quiet) { phase.value = 'loading'; error.value = '' }
  try {
    const d = await getAttemptAnswers(props.jobId, props.attemptId)
    if (mine !== seq) return
    data.value = { ...d, fields: Array.isArray(d?.fields) ? d.fields : [] }
    if (!fieldCounts(data.value.fields).all) filter.value = 'all'
    phase.value = 'ok'
    const c = fieldCounts(data.value.fields)
    emit('loaded', { notAnswered: c.notAnswered, assumed: c.assumed, all: c.all })
  } catch (e) {
    if (mine !== seq) return
    if (quiet && data.value) { note.value = `Couldn't reload the answers. ${describeError(e)}`; return }
    error.value = describeError(e)
    phase.value = 'error'
  }
}

onMounted(async () => {
  load()
  await nextTick()
  headRef.value?.focus?.()
})

// ---- the editor (one open at a time) ----

const editing = ref(null)             // the field id
const draft = ref('')                 // string | string[] by kind
const onlyEmployer = ref(true)
const saving = ref(false)
const fieldError = ref('')
const done = ref(null)                // {id, text}: the line shown after a save
const serverText = ref({})            // field id -> the remember route's own refusal text

const editorKind = computed(() => {
  const f = fields.value.find(x => x.id === editing.value)
  return f ? fieldKind(f) : 'text'
})

function open(f) {
  const kind = fieldKind(f)
  editing.value = f.id
  draft.value = startValue(f, kind)
  onlyEmployer.value = true
  fieldError.value = ''
  done.value = null
  nextTick(() => document.getElementById(`${base}-in-${f.id}`)?.focus?.())
}

function focusTrigger(id) {
  nextTick(() => document.getElementById(`${base}-do-${id}`)?.focus?.())
}

function cancel() {
  const id = editing.value
  editing.value = null
  fieldError.value = ''
  if (id != null) focusTrigger(id)
}

function onEscape() {
  if (editing.value != null) cancel()
  else emit('close')
}

const sentence = text => {
  const t = String(text ?? '').trim()
  if (!t) return ''
  const cap = t[0].toUpperCase() + t.slice(1)
  return /[.!?]$/.test(cap) ? cap : `${cap}.`
}

async function save(f) {
  if (saving.value) return
  fieldError.value = ''
  const kind = fieldKind(f)
  const pre = answerBody(kind, draft.value, onlyEmployer.value, '')
  if (pre.error) { fieldError.value = pre.error; return }
  saving.value = true
  try {
    // The saved answer lives in the owner's details file; the route wants its current etag.
    let etag = ''
    try {
      etag = (await getApplicant())?.etag ?? ''
    } catch (e) {
      fieldError.value = `Couldn't read your details to save this answer. ${describeError(e)}`
      return
    }
    const res = await rememberAnswer(props.jobId, props.attemptId, f.id, { ...pre, etag })
    f.remembered_text = String(res?.remembered_text ?? '')
    editing.value = null
    done.value = { id: f.id, text: sent.value ? SAVED_SENT : SAVED_STOPPED }
    live.value = `Saved for next time. ${done.value.text}`
    emit('saved', { ready: res?.ready_to_retry === true, answerId: f.id, key: res?.key ?? '' })
    focusTrigger(f.id)
  } catch (e) {
    await onSaveError(e, f)
  } finally {
    saving.value = false
  }
}

async function onSaveError(e, f) {
  const p = problemOf(e)
  const text = String(e?.body?.text ?? '')
  if (p.status === 409 && (p.code === 'changed' || p.code === 'unreadable')) {
    editing.value = null
    note.value = p.code === 'changed'
      ? 'Your details changed while you were editing, so the answers were reloaded. Choose your answer again.'
      : (text || "Your details file couldn't be read, so nothing was saved.")
    await load(true)
    return
  }
  if (['shared_answer', 'follows_your_details', 'too_general'].includes(p.code)) {
    f.refusal = p.code
    f.can_remember = false
    if (text) serverText.value = { ...serverText.value, [f.id]: text }
    editing.value = null
    focusTrigger(f.id)
    return
  }
  if (p.status === 422 && p.code === 'invalid') {
    fieldError.value = p.errors.map(x => sentence(x.message)).join(' ') || sentence(text) || 'That answer is not valid.'
    return
  }
  if (p.status === 404) {
    note.value = 'This answer is no longer on record. The answers were reloaded.'
    editing.value = null
    await load(true)
    return
  }
  fieldError.value = `Couldn't save this answer. ${describeError(e)}`
}

// The sentence for a refused row: the contract's words by code, or the server's own text
// (from a refused save) with the link kept.
function refusalView(f) {
  const copy = refusalCopy(f.refusal, f.label)
  if (!copy) return null
  // With no label the server's "too general" sentence quotes an empty label: use our own words.
  if (f.refusal === 'too_general' && !String(f.label ?? '').trim()) return copy
  const own = String(serverText.value[f.id] ?? '').trim()
  if (!own) return copy
  const lead = own.endsWith(copy.link) ? own.slice(0, -copy.link.length).trim() : own
  return { ...copy, lead: lead || copy.lead }
}

function toggleMulti(option, on) {
  const now = Array.isArray(draft.value) ? [...draft.value] : []
  const at = now.indexOf(option)
  if (on && at < 0) now.push(option)
  if (!on && at >= 0) now.splice(at, 1)
  draft.value = now
}
</script>

<template>
  <section
    class="wws"
    data-what-was-sent
    :aria-labelledby="headId"
    :aria-busy="phase === 'loading' ? 'true' : undefined"
    @keydown.esc.stop="onEscape"
  >
    <header class="wws-head">
      <h4 :id="headId" ref="headRef" class="wws-title" tabindex="-1">{{ title }}</h4>
      <span v-if="attempt?.trial" class="ui-badge wws-trial" data-tone="info">Trial: filled, not sent</span>
      <button type="button" class="ghost wws-close" @click="emit('close')">Close</button>
    </header>

    <p v-if="phase === 'ok'" class="wws-sub">{{ sub }}</p>
    <p v-if="phase === 'ok' && attempt?.entries_note" class="wws-entries muted">{{ attempt.entries_note }}</p>
    <div v-if="note" class="notice warn wws-note" role="alert">
      <p>{{ note }}</p>
      <button type="button" class="ghost wws-note-dismiss" @click="note = ''">Dismiss</button>
    </div>
    <p class="visually-hidden" role="status" aria-live="polite">{{ live }}</p>

    <div v-if="phase === 'loading'" class="wws-loading" role="status">
      <span class="visually-hidden">Loading the answers…</span>
      <span class="ui-skeleton wws-skel" />
      <span class="ui-skeleton wws-skel" />
      <span class="ui-skeleton wws-skel" />
    </div>

    <div v-else-if="phase === 'error'" class="notice error wws-error" role="alert">
      <p>Couldn't load the answers. {{ error }}</p>
      <button type="button" class="wws-retry" @click="load()">Try again</button>
    </div>

    <p v-else-if="!fields.length" class="muted wws-empty">No answers were recorded for this attempt.</p>

    <template v-else>
      <Segmented v-model="filter" class="wws-filter" label="Show answers" :options="filterOptions" />
      <ul class="wws-list">
        <li
          v-for="f in shown"
          :key="f.id"
          class="wws-row"
          :data-field="f.id"
          :data-status="f.status"
          :data-assumed="f.assumed ? 'true' : undefined"
        >
          <div class="wws-main">
            <p class="wws-label">{{ titleOf(f) }}</p>
            <p class="wws-value" :class="{ 'is-empty': !f.value_text }">
              <template v-if="f.value_text">{{ f.value_text }}</template>
              <template v-else><span aria-hidden="true">—</span><span class="visually-hidden">No value</span></template>
            </p>
            <p v-if="f.basis_text" class="wws-basis">{{ f.basis_text }}</p>
            <div v-if="hasWhy(f)" class="wws-why" data-why>
              <p v-if="f.reason" class="wws-reason"><span class="visually-hidden">Why it was left empty: </span>{{ f.reason }}</p>
              <p v-if="f.reason_hint || whyLink(f)" class="wws-hint">
                <span v-if="f.reason_hint">{{ f.reason_hint }}</span>
                <a
                  v-if="whyLink(f)"
                  class="button ghost wws-why-link"
                  href="#/profile"
                  :aria-label="`${whyLink(f).label}: ${titleOf(f)}`"
                  @click.prevent="openAnswer(whyLink(f).target)"
                >{{ whyLink(f).label }}</a>
              </p>
            </div>
            <p v-if="f.remembered_text" class="wws-next">Next time: {{ f.remembered_text }}</p>
          </div>
          <div class="wws-badges">
            <span v-if="f.assumed" class="ui-badge wws-badge-assumed" data-tone="warn">Assumed</span>
            <span v-if="f.status === 'not_answered'" class="ui-badge wws-badge-empty" data-tone="danger">Not answered</span>
            <span v-if="f.remembered_text" class="ui-badge wws-badge-saved" data-tone="ok">Saved for next time</span>
          </div>

          <div class="wws-act">
            <button
              v-if="f.can_remember && editing !== f.id"
              :id="`${base}-do-${f.id}`"
              type="button"
              class="ghost wws-correct"
              :aria-label="`${correctionLabel(f, sent)}: ${titleOf(f)}`"
              @click="open(f)"
            >{{ correctionLabel(f, sent) }}</button>
            <p v-else-if="showRefusal(f)" class="wws-refusal">
              {{ refusalView(f).lead }}
              <button
                v-if="refusalView(f).to === 'details'"
                type="button"
                class="link wws-refusal-link"
                @click="openAnswer('')"
              >{{ refusalView(f).link }}</button>
              <a v-else class="text-link wws-refusal-link" href="#/settings/apply/answers-corrected">{{ refusalView(f).link }}</a>
            </p>
          </div>

          <p v-if="done?.id === f.id && editing !== f.id" class="wws-done" role="status">{{ done.text }}</p>

          <form
            v-if="editing === f.id"
            class="wws-editor"
            :aria-label="`${correctionLabel(f, sent)}: ${titleOf(f)}`"
            @submit.prevent="save(f)"
          >
            <div v-if="editorKind === 'choice' && f.options.length > LIST_MAX" class="wws-field">
              <label class="wws-legend" :for="`${base}-in-${f.id}`">Your answer</label>
              <select
                :id="`${base}-in-${f.id}`"
                v-model="draft"
                :aria-invalid="fieldError ? 'true' : undefined"
                :aria-describedby="fieldError ? `${base}-err-${f.id}` : undefined"
              >
                <option value="" disabled>Choose an option</option>
                <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
              </select>
            </div>
            <fieldset v-else-if="editorKind === 'choice' || editorKind === 'yes_no' || editorKind === 'multi'" class="wws-choices" :aria-describedby="fieldError ? `${base}-err-${f.id}` : undefined">
              <legend class="wws-legend">Your answer</legend>
              <template v-if="editorKind === 'yes_no'">
                <label class="wws-option"><input :id="`${base}-in-${f.id}`" v-model="draft" type="radio" :name="`${base}-r-${f.id}`" value="yes"> Yes</label>
                <label class="wws-option"><input v-model="draft" type="radio" :name="`${base}-r-${f.id}`" value="no"> No</label>
              </template>
              <template v-else-if="editorKind === 'choice'">
                <label v-for="(o, i) in f.options" :key="o" class="wws-option">
                  <input :id="i === 0 ? `${base}-in-${f.id}` : undefined" v-model="draft" type="radio" :name="`${base}-r-${f.id}`" :value="o"> {{ o }}
                </label>
              </template>
              <template v-else>
                <label v-for="(o, i) in f.options" :key="o" class="wws-option">
                  <input
                    :id="i === 0 ? `${base}-in-${f.id}` : undefined"
                    type="checkbox"
                    :checked="Array.isArray(draft) && draft.includes(o)"
                    @change="toggleMulti(o, $event.target.checked)"
                  > {{ o }}
                </label>
              </template>
            </fieldset>
            <div v-else class="wws-field">
              <label class="wws-legend" :for="`${base}-in-${f.id}`">Your answer</label>
              <textarea
                v-if="editorKind === 'textarea'"
                :id="`${base}-in-${f.id}`"
                v-model="draft"
                rows="3"
                :aria-invalid="fieldError ? 'true' : undefined"
                :aria-describedby="fieldError ? `${base}-err-${f.id}` : undefined"
              />
              <input
                v-else
                :id="`${base}-in-${f.id}`"
                v-model="draft"
                :type="editorKind === 'number' ? 'number' : editorKind === 'date' ? 'date' : 'text'"
                :inputmode="editorKind === 'number' ? 'decimal' : undefined"
                :step="editorKind === 'number' ? 'any' : undefined"
                :aria-invalid="fieldError ? 'true' : undefined"
                :aria-describedby="fieldError ? `${base}-err-${f.id}` : undefined"
              >
            </div>
            <p v-if="fieldError" :id="`${base}-err-${f.id}`" class="wws-field-error" role="alert">{{ fieldError }}</p>
            <label class="wws-scope">
              <input v-model="onlyEmployer" type="checkbox">
              Only for applications to {{ employer || 'this employer' }}
            </label>
            <p v-if="sent" class="wws-help muted">{{ SAVED_SENT }}</p>
            <div class="wws-buttons">
              <button type="submit" class="primary wws-save" :disabled="saving">{{ saving ? 'Saving…' : 'Save for next time' }}</button>
              <button type="button" class="ghost wws-cancel" :disabled="saving" @click="cancel">Cancel</button>
            </div>
          </form>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.wws {
  display: grid;
  gap: var(--space-3);
  min-width: 0;
  margin-top: var(--space-3);
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface);
}
.wws:focus-within { border-color: var(--border-strong, var(--border)); }
.wws-head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2) var(--space-3); }
.wws-title { margin: 0; font-size: var(--text-sm); font-weight: var(--weight-bold); color: var(--text-2); }
.wws-title:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; border-radius: var(--radius-sm); }
.wws-close { margin-left: auto; min-height: 1.75rem; padding: 0 var(--space-2); font-size: var(--text-xs); }
.wws-sub, .wws-entries { margin: 0; font-size: var(--text-sm); overflow-wrap: anywhere; }
.wws-entries { font-size: var(--text-xs); }
.wws-note { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-2); }
.wws-note p { min-width: 0; overflow-wrap: anywhere; }
.wws-loading { display: grid; gap: var(--space-2); }
.wws-skel { height: 2.5rem; }
.wws-error { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-2); }
.wws-error p { min-width: 0; margin: 0; overflow-wrap: anywhere; }
.wws-empty { margin: 0; font-size: var(--text-sm); }
.wws-filter { justify-self: start; max-width: 100%; }

.wws-list { list-style: none; margin: 0; padding: 0; display: grid; }
.wws-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  grid-template-areas: 'main badges' 'act act' 'done done' 'editor editor';
  gap: var(--space-1) var(--space-3);
  padding: var(--space-3) 0;
  border-top: 1px solid var(--border);
  min-width: 0;
}
.wws-row:first-child { border-top: 0; }
.wws-main { grid-area: main; min-width: 0; }
.wws-main p { margin: 0; overflow-wrap: anywhere; }
.wws-label { font-size: var(--text-sm); color: var(--text-2); }
.wws-value { margin-top: 2px; font-weight: var(--weight-semibold); white-space: pre-wrap; }
.wws-value.is-empty { color: var(--muted); font-weight: var(--weight-regular, 400); }
.wws-basis, .wws-next { margin-top: 2px; font-size: var(--text-xs); color: var(--muted); }
/* Why a field was left empty: plain sentences (not colour alone), the link on the hint's line. */
.wws-why { margin-top: var(--space-1); display: grid; gap: 2px; min-width: 0; }
.wws-reason { font-size: var(--text-sm); color: var(--text-2); }
.wws-hint { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-2); font-size: var(--text-xs); color: var(--muted); }
.wws-hint span { min-width: 0; overflow-wrap: anywhere; }
.wws-why-link { min-height: 1.75rem; padding: 0 var(--space-2); font-size: var(--text-xs); }
.wws-badges { grid-area: badges; display: flex; flex-wrap: wrap; align-items: flex-start; justify-content: flex-end; gap: var(--space-1); }
.wws-act { grid-area: act; min-width: 0; }
.wws-act:empty { display: none; }
.wws-act p { margin: 0; }
.wws-correct { min-height: 1.75rem; padding: 0 var(--space-2); font-size: var(--text-xs); }
.wws-refusal { font-size: var(--text-xs); color: var(--muted); overflow-wrap: anywhere; }
.wws-refusal-link { font-size: var(--text-xs); min-height: 0; padding: 0; display: inline; }
.wws-done { grid-area: done; margin: 0; font-size: var(--text-xs); color: var(--ok); overflow-wrap: anywhere; }
.wws-editor {
  grid-area: editor;
  display: grid;
  gap: var(--space-2);
  margin-top: var(--space-2);
  padding: var(--space-3);
  background: var(--surface-2);
  border-radius: var(--radius-md);
  min-width: 0;
}
.wws-choices { display: grid; gap: var(--space-1); margin: 0; padding: 0; border: 0; min-width: 0; max-height: 16rem; overflow-y: auto; }
.wws-field select { width: 100%; max-width: 100%; box-sizing: border-box; }
.wws-field { display: grid; gap: var(--space-1); min-width: 0; }
.wws-legend { padding: 0; font-size: var(--text-xs); font-weight: var(--weight-semibold); color: var(--text-2); }
.wws-field input[type='text'], .wws-field input[type='number'], .wws-field input[type='date'], .wws-field textarea { width: 100%; max-width: 100%; box-sizing: border-box; }
.wws-option, .wws-scope { display: flex; align-items: center; gap: var(--space-2); min-height: 1.75rem; font-size: var(--text-sm); cursor: pointer; overflow-wrap: anywhere; }
.wws-field-error { margin: 0; font-size: var(--text-xs); color: var(--danger); }
.wws-help { margin: 0; font-size: var(--text-xs); }
.wws-buttons { display: flex; flex-wrap: wrap; gap: var(--space-2); }

@media (max-width: 640px) {
  .wws { padding: var(--space-3); }
  .wws-row { grid-template-columns: minmax(0, 1fr); grid-template-areas: 'main' 'badges' 'act' 'done' 'editor'; }
  .wws-badges { justify-content: flex-start; }
  .wws-close, .wws-correct, .wws-note-dismiss { min-height: var(--touch-min); }
  .wws-option, .wws-scope { min-height: var(--touch-min); }
  .wws-buttons button { min-height: var(--touch-min); }
  .wws-refusal-link { min-height: var(--touch-min); }
  .wws-why-link { min-height: var(--touch-min); display: inline-flex; align-items: center; }
  .wws-retry { min-height: var(--touch-min); }
}
</style>
