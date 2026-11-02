<script setup>
// Profile -> Application details (Q-30, D-74): every key of data/applicant.yaml
// as a form, with what auto-apply still needs at the top and, above the form,
// the questions employers asked that JobScraper could not answer
// (QuestionsInbox). The form is generated from `form`, the schema the server
// sends (applicant.form_json), so a key added there appears here without a UI
// change. Layout and copy: docs/architecture/questions_design.md section 10.
//
// Saving sends the whole profile back with the etag it was loaded with. The
// server refuses a stale etag (409) and a profile that fails validation (422,
// with a message per path); both are said in words. Keys the form does not
// know round-trip untouched and are listed read-only in the last group.
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { describeError, getApplicant, problemOf, saveApplicant } from '../api.js'
import {
  clone, entryPart, errorMap, fieldId, findItem, getAt, otherKeys, setAt, showValue, within,
} from '../applicantForm.js'
import FieldInput from './FieldInput.vue'
import TabLoading from './TabLoading.vue'

const emit = defineEmits(['counts'])

const PRIVATE = 'Private: never sent to the AI'
// A group's own control: a label for one input, a name for a set of them.
const GROUPED = new Set(['entries', 'salary', 'country_bool_map', 'yes_no', 'multi', 'fixed'])

const data = ref(null)
const draft = ref({})
const loading = ref(true)
const loadError = ref('')
const saving = ref(false)
const errors = ref([])          // [{path, message}] from the last save or load
const conflict = ref('')        // '' | 'changed' | 'unreadable' (a 409 on save)
const note = ref('')
const problem = ref('')         // a save that failed for a reason that is not 409 or 422
const openQuestions = ref(0)
const removing = ref('')        // the `extra` key whose Remove is being confirmed
const banner = ref(null)
const inbox = ref(null)

const form = computed(() => data.value?.form ?? [])
const missing = computed(() => data.value?.missing ?? [])
const fileError = computed(() => data.value?.file?.error || '')
const sensitive = computed(() => data.value?.sensitive ?? [])
const fromResumePaths = computed(() => data.value?.from_resume ?? [])
const extra = computed(() => Object.entries(draft.value?.extra ?? {}))
const dirty = computed(() => !!data.value && JSON.stringify(draft.value) !== JSON.stringify(data.value.profile ?? {}))
const meter = computed(() => data.value?.completeness ?? null)
const errMap = computed(() => errorMap(errors.value))
const others = computed(() => (data.value ? otherKeys(draft.value, form.value) : []))

watch([() => missing.value.length, openQuestions], () => {
  emit('counts', { missing: missing.value.length, questions: openQuestions.value })
})

function adopt(res) {
  data.value = res
  draft.value = clone(res.profile ?? {})
  errors.value = res.errors ?? []
  conflict.value = ''
}

async function load() {
  loadError.value = ''
  note.value = ''
  try {
    adopt(await getApplicant())
  } catch (e) {
    loadError.value = describeError(e)
  } finally {
    loading.value = false
  }
}

// The Questions card rewrote the file: take its new etag and answers, but keep
// what is typed here and not yet saved. A section (identity, contact, ...) the
// form changed is kept as edited; every other section comes from the file.
async function reloadKeepingEdits() {
  const before = data.value?.profile ?? {}
  const mine = draft.value
  let res
  try {
    res = await getApplicant()
  } catch (e) {
    loadError.value = describeError(e)
    return
  }
  const next = clone(res.profile ?? {})
  for (const key of Object.keys(mine)) {
    if (key !== 'extra' && JSON.stringify(mine[key]) !== JSON.stringify(before[key])) next[key] = mine[key]
  }
  data.value = res
  draft.value = next
  errors.value = res.errors ?? []
  conflict.value = ''
}

// ---- labels, tags, ids ----

const labelOf = path => findItem(form.value, path)?.label ?? path
const isMissing = item => missing.value.some(m => within(m, item.path))
function filledHere(item) {
  const v = getAt(draft.value, item.path)
  if (GROUPED.has(item.kind) || item.kind === 'list_text' || item.kind === 'list_url') return false
  return !(v === null || v === undefined || (typeof v === 'string' && !v.trim()))
}
// "Needed": the server says it is missing and it has not been filled in here yet.
const needed = item => isMissing(item) && !filledHere(item)
const isPrivate = item => !!item.sensitive
const fromResume = item => fromResumePaths.value.some(p => within(p, item.path))
const privatePath = path => sensitive.value.some(s => within(path, s))
const labelTag = item => (GROUPED.has(item.kind) ? 'span' : 'label')

const itemErrors = item => errors.value.filter(e => within(e.path, item.path) && !handledInside(item, e.path))
const invalid = item => errors.value.some(e => within(e.path, item.path))
// Inside an entries field each message sits under its own sub-field.
function handledInside(item, path) {
  if (item.kind !== 'entries') return false
  const part = entryPart(item.path, path)
  return part !== null && (!part || (item.sub || []).some(s => s.path === part))
}
const describedBy = item => [
  item.help && item.kind !== 'fixed' ? `${fieldId(item.path)}-help` : '',
  itemErrors(item).length ? `${fieldId(item.path)}-err` : '',
].filter(Boolean).join(' ')

// Messages for a path the form has no field for (a hand-added key).
const unplaced = computed(() => errors.value.filter(e => !within(e.path, 'extra') && !findItem(form.value, e.path)))
const extraErrors = key => errors.value.filter(e => within(e.path, `extra.${key}`))

// ---- Fill in ----

function fillIn(path) {
  const hit = findItem(form.value, path)
  const el = document.getElementById(fieldId(hit?.path ?? path))
  if (!el) return
  el.scrollIntoView?.({ block: 'center' })
  el.querySelector('input:not([type="hidden"]), select, textarea, button')?.focus?.()
}
const canFill = path => !!findItem(form.value, path)

// ---- saving ----

async function save() {
  if (saving.value || fileError.value) return
  saving.value = true
  note.value = ''
  problem.value = ''
  conflict.value = ''
  try {
    adopt(await saveApplicant(draft.value, data.value.etag))
    note.value = 'Saved.'
  } catch (e) {
    const p = problemOf(e)
    if (p.status === 409) {
      conflict.value = p.code === 'unreadable' ? 'unreadable' : 'changed'
    } else if (p.status === 422 && (p.code === 'invalid' || p.errors.length)) {
      errors.value = p.errors
    } else {
      problem.value = `Could not save your details: ${p.text}`
    }
    await nextTick()
    banner.value?.focus?.()
  } finally {
    saving.value = false
  }
}

// ---- answers the owner gave to application questions (group 15) ----

const entryKind = e => e?.kind || 'text'
const scopeOf = (entry, scope) => (scope ? entry.by_employer?.[scope] ?? {} : entry)
function extraValue(entry, scope) {
  const s = scopeOf(entry, scope)
  if (entry.kind === 'choice') return s.picks?.[0] ?? null
  if (entry.kind === 'multi') return s.picks ?? []
  return s.value
}
function setExtra(key, scope, v) {
  const entry = draft.value.extra[key]
  const base = scope ? `extra.${key}.by_employer.${scope}` : `extra.${key}`
  if (entry.kind === 'choice') setAt(draft.value, `${base}.picks`, v ? [v] : [])
  else if (entry.kind === 'multi') setAt(draft.value, `${base}.picks`, v)
  else setAt(draft.value, `${base}.value`, v)
}
const seenOptions = (entry, scope) => scopeOf(entry, scope).seen ?? entry.seen ?? []
const employerName = norm => norm.replace(/\b\w/g, c => c.toUpperCase())
async function removeAnswer(key) {
  delete draft.value.extra[key]
  if (!Object.keys(draft.value.extra).length) delete draft.value.extra
  removing.value = ''
  await save()
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <div class="app-details" :aria-busy="loading ? 'true' : 'false'">
    <TabLoading v-if="loading" :rows="3" />
    <div v-else-if="loadError" class="notice error" role="alert">
      <p>Could not load your application details: {{ loadError }}</p>
      <button type="button" @click="load">Try again</button>
    </div>

    <template v-else-if="data">
      <div v-if="fileError" class="notice error" role="alert">
        <p>JobScraper can't read data/applicant.yaml ({{ fileError }}). Fix the file by hand. Nothing will be saved over it until then.</p>
        <button type="button" class="reload" @click="load">Check again</button>
      </div>
      <div v-else-if="conflict" ref="banner" class="notice error banner conflict" role="alert" tabindex="-1">
        <p v-if="conflict === 'changed'">
          This file changed since you opened it, in another tab or by hand. Reload to get the latest, then make your change again.
        </p>
        <p v-else>
          JobScraper can't read data/applicant.yaml. Fix the file by hand. Nothing will be saved over it until then.
        </p>
        <button type="button" class="reload" @click="load">Reload</button>
      </div>
      <div v-else-if="problem" ref="banner" class="notice error banner" role="alert" tabindex="-1">
        <p>{{ problem }}</p>
      </div>
      <div v-else-if="errors.length" ref="banner" class="notice error banner invalid" role="alert" tabindex="-1">
        <p>Some details need fixing. They're marked below.</p>
        <ul v-if="unplaced.length" class="unplaced">
          <li v-for="e in unplaced" :key="e.path + e.message"><span class="mono">{{ e.path }}: </span>{{ e.message }}</li>
        </ul>
      </div>

      <template v-if="!fileError">
        <section v-if="missing.length" class="missing surface" aria-labelledby="ad-missing">
          <h2 id="ad-missing" class="section-title">Needed before auto-apply</h2>
          <p class="muted lead">Auto-apply won't start until these are filled in.</p>
          <ul class="missing-list">
            <li v-for="path in missing" :key="path">
              <span class="missing-label">{{ labelOf(path) }}</span>
              <button v-if="canFill(path)" type="button" class="link fill" @click="fillIn(path)">Fill in</button>
              <span v-else class="muted mono path">{{ path }}</span>
            </li>
          </ul>
        </section>
      </template>

      <template v-if="!fileError">
        <h2 class="section-title">Your details</h2>
        <p v-if="!data.file?.exists" class="muted lead">There is no data/applicant.yaml yet. Saving creates it.</p>
        <div v-if="meter" class="meter-row">
          <div
            class="meter"
            role="meter"
            aria-label="Details filled"
            :aria-valuenow="meter.filled"
            aria-valuemin="0"
            :aria-valuemax="meter.needed"
            :aria-valuetext="`${meter.filled} of ${meter.needed} details filled`"
          >
            <span :style="{ width: meter.needed ? `${Math.min(100, Math.round((meter.filled / meter.needed) * 100))}%` : '0%' }" />
          </div>
          <span class="meter-text">{{ meter.filled }} of {{ meter.needed }} details filled</span>
        </div>
        <p v-if="data.file?.has_comments" class="notice warn comments-note">
          Saving rewrites applicant.yaml without its comments. A copy with the comments is kept as applicant.commented-backup.yaml.
        </p>

        <form class="the-form" novalidate @submit.prevent="save">
          <section v-for="g in form" :key="g.id" class="group surface" :aria-labelledby="`g-${g.id}`">
            <header class="group-head">
              <h3 :id="`g-${g.id}`">{{ g.title }}</h3>
              <span v-if="g.sensitive" class="tag private">{{ PRIVATE }}</span>
            </header>
            <p v-if="g.note" class="muted note">{{ g.note }}</p>

            <div
              v-for="item in g.items"
              :id="fieldId(item.path)"
              :key="item.path"
              class="field"
              :data-path="item.path"
            >
              <div class="field-head">
                <component
                  :is="labelTag(item)"
                  :id="`${fieldId(item.path)}-label`"
                  class="field-label"
                  :for="labelTag(item) === 'label' ? `${fieldId(item.path)}-in` : undefined"
                >{{ item.label }}</component>
                <span v-if="needed(item)" class="tag needed">Needed</span>
                <span v-if="isPrivate(item)" class="tag private">{{ PRIVATE }}</span>
                <span v-if="fromResume(item) && item.kind !== 'entries'" class="tag resume">From your resume, please check</span>
              </div>
              <FieldInput
                :id="`${fieldId(item.path)}-in`"
                :kind="item.kind"
                :model-value="getAt(draft, item.path)"
                :options="item.options || []"
                :sub="item.sub || []"
                :path="item.path"
                :label="item.entry_label || item.label"
                :from-resume="fromResumePaths"
                :errors="errMap"
                :nullable="item.nullable ?? !item.required"
                :fixed-text="item.fixed_text || item.help || ''"
                :multiline="!!item.multiline"
                :labelledby="GROUPED.has(item.kind) ? `${fieldId(item.path)}-label` : ''"
                :describedby="describedBy(item)"
                :invalid="invalid(item)"
                @update:model-value="setAt(draft, item.path, $event)"
              />
              <p v-if="item.help && item.kind !== 'fixed'" :id="`${fieldId(item.path)}-help`" class="hint">{{ item.help }}</p>
              <p v-if="itemErrors(item).length" :id="`${fieldId(item.path)}-err`" class="field-error">
                <template v-for="(e, i) in itemErrors(item)" :key="e.path + e.message"><template v-if="i"> </template>{{ e.message }}</template>
              </p>
            </div>
          </section>

          <!-- 15: answers given to application questions -->
          <section v-if="extra.length" class="group surface extra" aria-labelledby="g-extra">
            <header class="group-head"><h3 id="g-extra">Answers you gave to application questions</h3></header>
            <div v-for="[key, entry] in extra" :id="fieldId(`extra.${key}`)" :key="key" class="field extra-row" :data-path="`extra.${key}`">
              <div class="field-head">
                <span :id="`${fieldId(`extra.${key}`)}-label`" class="field-label">{{ entry.title || key }}</span>
                <span v-if="entry.sensitive" class="tag private">{{ PRIVATE }}</span>
              </div>
              <p v-if="entry.description" class="hint">{{ entry.description }}</p>
              <FieldInput
                :id="`${fieldId(`extra.${key}`)}-in`"
                :kind="entryKind(entry)"
                :model-value="extraValue(entry)"
                :options="seenOptions(entry)"
                :multiline="entry.kind === 'text'"
                :labelledby="`${fieldId(`extra.${key}`)}-label`"
                :invalid="extraErrors(key).length > 0"
                @update:model-value="setExtra(key, '', $event)"
              />
              <div v-for="(scoped, emp) in entry.by_employer || {}" :key="emp" class="scoped">
                <span :id="`${fieldId(`extra.${key}.${emp}`)}-label`" class="scoped-label">Only for {{ employerName(emp) }}</span>
                <FieldInput
                  :id="`${fieldId(`extra.${key}.${emp}`)}-in`"
                  :kind="entryKind(entry)"
                  :model-value="extraValue(entry, emp)"
                  :options="seenOptions(entry, emp)"
                  :multiline="entry.kind === 'text'"
                  :labelledby="`${fieldId(`extra.${key}.${emp}`)}-label`"
                  @update:model-value="setExtra(key, emp, $event)"
                />
              </div>
              <p v-for="e in extraErrors(key)" :key="e.path + e.message" class="field-error">{{ e.message }}</p>
              <div v-if="removing === key" class="confirm" role="group" :aria-labelledby="`${fieldId(`extra.${key}`)}-confirm`">
                <p :id="`${fieldId(`extra.${key}`)}-confirm`">Remove this answer? Applications that ask it will stop and ask you again.</p>
                <div class="confirm-buttons">
                  <button type="button" class="danger-btn remove-yes" :disabled="saving" @click="removeAnswer(key)">Remove answer</button>
                  <button type="button" class="remove-no" @click="removing = ''">Keep it</button>
                </div>
              </div>
              <button v-else type="button" class="ghost remove" :aria-label="`Remove ${entry.title || key}`" @click="removing = key">Remove</button>
            </div>
          </section>

          <!-- 16: keys the form does not know -->
          <section v-if="others.length" class="group surface other" aria-labelledby="g-other">
            <header class="group-head"><h3 id="g-other">Other keys in your file</h3></header>
            <p class="muted note">These keys aren't in the form. They're kept as they are. Edit them in data/applicant.yaml.</p>
            <dl class="others">
              <div v-for="o in others" :key="o.path">
                <dt class="mono">{{ o.path }}</dt>
                <dd class="mono">{{ privatePath(o.path) ? '•••' : showValue(o.value) }}</dd>
              </div>
            </dl>
          </section>

          <div class="save-bar">
            <span v-if="dirty && !note" class="muted unsaved">You have unsaved changes.</span>
            <p v-if="note" class="notice ok save-note" role="status">{{ note }}</p>
            <button type="submit" class="primary save" :disabled="saving">{{ saving ? 'Saving…' : 'Save details' }}</button>
          </div>
        </form>
      </template>
    </template>
  </div>
</template>

<style scoped>
.app-details { display: grid; gap: var(--space-4); }
.lead { margin: 0; font-size: var(--text-sm); }
.missing { padding: var(--space-4); display: grid; gap: var(--space-2); }
.missing .section-title { margin: 0; }
.missing-list { list-style: none; margin: var(--space-2) 0 0; padding: 0; display: grid; gap: var(--space-1); }
.missing-list li { display: flex; align-items: baseline; gap: var(--space-3); font-size: var(--text-sm); }
.missing-label { font-weight: 600; }
.path { font-size: var(--text-xs); }
.unplaced { margin: var(--space-2) 0 0; padding-left: var(--space-5); }
.banner:focus-visible { outline-offset: 2px; }
.app-details .section-title { margin: var(--space-2) 0 0; }
.meter-row { display: flex; align-items: center; gap: var(--space-3); }
.meter { flex: 0 1 16rem; height: 0.5rem; border-radius: 999px; background: var(--surface-3); overflow: hidden; }
.meter span { display: block; height: 100%; background: var(--accent); border-radius: 999px; }
.meter-text { font-size: var(--text-sm); color: var(--text-2); }
.comments-note { margin: 0; }
.the-form { display: grid; gap: var(--space-4); }
.group { padding: var(--space-4) var(--space-5); display: grid; gap: var(--space-4); }
.group-head { display: flex; align-items: center; gap: var(--space-3); flex-wrap: wrap; }
.group-head h3 { margin: 0; font-size: var(--text-md); font-weight: 650; }
.note { margin: calc(-1 * var(--space-2)) 0 0; font-size: var(--text-sm); }
.field { display: grid; gap: var(--space-1); align-content: start; scroll-margin-top: calc(var(--header-h) + var(--space-4)); }
.field-head { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
.field-label { font-size: var(--text-sm); font-weight: 600; }
.hint { margin: 0; font-size: var(--text-xs); color: var(--muted); max-width: 60ch; }
.field-error { margin: 0; font-size: var(--text-sm); color: var(--danger); }
.scoped { display: grid; gap: var(--space-1); padding-left: var(--space-4); border-left: 2px solid var(--border); }
.scoped-label { font-size: var(--text-sm); color: var(--text-2); }
.extra-row + .extra-row { padding-top: var(--space-4); border-top: 1px solid var(--border); }
.confirm { display: grid; gap: var(--space-2); padding: var(--space-3); background: var(--warn-soft); border-radius: var(--radius); }
.confirm p { margin: 0; font-size: var(--text-sm); }
.confirm-buttons { display: flex; gap: var(--space-2); }
.danger-btn { background: var(--danger); border-color: var(--danger); color: var(--surface); font-weight: 600; }
.danger-btn:hover:not(:disabled) { background: var(--danger); filter: brightness(0.92); color: var(--surface); }
.remove { justify-self: start; }
.others { margin: 0; display: grid; gap: var(--space-2); }
.others > div { display: flex; flex-wrap: wrap; gap: var(--space-1) var(--space-3); }
.others dt { color: var(--muted); font-size: var(--text-xs); }
.others dd { margin: 0; font-size: var(--text-xs); overflow-wrap: anywhere; }
.save-bar {
  position: sticky; bottom: 0; z-index: 5;
  display: flex; align-items: center; justify-content: flex-end; gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
}
.unsaved { font-size: var(--text-sm); }
.save-note { margin: 0; padding: var(--space-1) var(--space-3); }
</style>
