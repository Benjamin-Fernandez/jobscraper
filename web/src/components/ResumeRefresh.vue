<script setup>
// "Update your application details" (Q-44, docs/architecture/q44_refresh_from_resume.md
// sections 4 and 5). After a resume upload the profile job compares the resume
// with data/applicant.yaml; this panel lists what would change, one checkbox
// per change with its before and after, and saves only the ticked ones.
//
// Only entries that came from a resume (or the template's examples) are ever
// offered for change; an entry the owner edited shows as "Kept". Skills are only
// added. The server recomputes the plan on every GET, so it is never stale after
// a form edit, and POST runs under the same etag guard as the form's Save.
//
// Quiet on failure: a server without the route (404) or with no application
// details hides the panel. `reload` changes after each profile job, so the
// panel looks again; `unavailable` says that job could not reach the model.
import { computed, ref, watch, onMounted } from 'vue'
import { ApiError, describeError, getResumeRefresh, saveResumeRefresh } from '../api.js'

const props = defineProps({
  reload: { type: Number, default: 0 },
  unavailable: { type: Boolean, default: false },
})
const emit = defineEmits(['go-view', 'saved'])

const DISMISS_KEY = 'profile.refresh.dismissed'
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

const plan = ref(null)          // the GET answer, or null when hidden
const ticked = ref({})          // change id -> bool
const saving = ref(false)
const problem = ref('')
const conflict = ref(false)
const savedCount = ref(0)
const dismissed = ref(readDismissed())

function readDismissed() {
  try { return window.localStorage.getItem(DISMISS_KEY) || '' } catch { return '' }
}

async function load() {
  problem.value = ''
  conflict.value = false
  try {
    plan.value = await getResumeRefresh()
  } catch {
    plan.value = null
    return
  }
  const next = {}
  for (const c of plan.value?.changes ?? []) if (c.op !== 'kept') next[c.id] = !!c.default
  ticked.value = next
}

onMounted(load)
watch(() => props.reload, () => { savedCount.value = 0; load() })

const state = computed(() => plan.value?.state ?? '')
const actionable = computed(() => (plan.value?.changes ?? []).filter(c => c.op !== 'kept' && c.list !== 'skills'))
const kept = computed(() => (plan.value?.changes ?? []).filter(c => c.op === 'kept'))
const skillChange = computed(() => (plan.value?.changes ?? []).find(c => c.list === 'skills') ?? null)
const notOnResume = computed(() => plan.value?.skills?.not_on_resume ?? [])
const count = computed(() => Object.values(ticked.value).filter(Boolean).length)
const hasChanges = computed(() => actionable.value.length > 0 || !!skillChange.value)

// What shows: the plan, or one sentence (stale / unavailable), or nothing.
const mode = computed(() => {
  if (props.unavailable && state.value !== 'ready') return 'unavailable'
  if (state.value === 'stale') return 'stale'
  if (state.value !== 'ready') return 'hidden'
  if (savedCount.value) return 'saved'
  if (plan.value.resume_hash && plan.value.resume_hash === dismissed.value) return 'hidden'
  return hasChanges.value ? 'plan' : 'empty'
})

function month(v) {
  const m = /^(\d{4})-(\d{2})/.exec(String(v ?? ''))
  return m ? `${MONTHS[Number(m[2]) - 1] ?? m[2]} ${m[1]}` : ''
}
function dates(e) {
  const s = month(e?.start)
  const t = month(e?.end)
  if (!s && !t) return ''
  if (s && !t) return `${s} – Present`
  return s && s !== t ? `${s} – ${t}` : t
}
// "employer · title · start – end"
function line(list, e) {
  if (!e) return ''
  const org = list === 'experience' ? e.employer : e.institution
  const title = list === 'experience' ? e.title : e.degree
  return [org, title, dates(e)].filter(Boolean).join(' · ')
}
function label(c) {
  if (c.op === 'add') return 'Add'
  if (c.op === 'update') return 'Update'
  if (c.op === 'kept') return 'Kept: you edited this'
  return c.reason === 'template' ? 'Remove: example from the template' : 'Remove: no longer on your resume'
}
// The remove row's note repeats its label; the others' notes say something new.
const noteOf = c => (c.op === 'remove' ? '' : c.note || '')
const listName = c => (c.list === 'experience' ? 'Experience' : 'Education')
// The row's sentence is the checkbox label; the skills themselves follow as chips
// (the first 12, then "and N more"), like the summary card, so a long list is not
// one very long line.
const SKILL_CHIPS = 12
const allSkills = ref(false)
const addSkills = computed(() => plan.value?.skills?.add ?? [])
const shownSkills = computed(() => (allSkills.value ? addSkills.value : addSkills.value.slice(0, SKILL_CHIPS)))
const moreSkills = computed(() => Math.max(0, addSkills.value.length - SKILL_CHIPS))
const skillsText = computed(() => {
  const n = addSkills.value.length
  const what = `${n} ${n === 1 ? 'skill' : 'skills'} from your resume`
  return skillChange.value?.op === 'replace'
    ? `Replace the example skills with ${what}:`
    : `Add ${what}:`
})

function notNow() {
  const h = plan.value?.resume_hash || ''
  dismissed.value = h
  try { window.localStorage.setItem(DISMISS_KEY, h) } catch { /* private window */ }
}

async function save() {
  const accept = Object.entries(ticked.value).filter(([, v]) => v).map(([k]) => k)
  if (!accept.length || saving.value) return
  saving.value = true
  problem.value = ''
  conflict.value = false
  try {
    const res = await saveResumeRefresh(plan.value.etag, accept)
    savedCount.value = res?.saved ?? accept.length
    emit('saved', res)
    const fresh = await getResumeRefresh().catch(() => null)
    if (fresh) plan.value = fresh
  } catch (e) {
    if (e instanceof ApiError && e.status === 409 && e.detail === 'changed') {
      conflict.value = true
    } else if (e instanceof ApiError && e.status === 409 && e.detail === 'stale') {
      plan.value = { state: 'stale' }
    } else if (e instanceof ApiError && e.status === 422) {
      const paths = (e.body?.errors ?? []).map(x => x.path).join(', ')
      problem.value = `Couldn't save these changes${paths ? `: ${paths} would not be valid` : ''}. Nothing was saved.`
    } else {
      problem.value = `Couldn't save these changes: ${describeError(e)}`
    }
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section v-if="mode !== 'hidden'" class="resume-refresh" aria-labelledby="resume-refresh-title">
    <h3 id="resume-refresh-title" class="rr-title">Update your application details</h3>

    <p v-if="mode === 'unavailable'" class="notice warn rr-unavailable">
      Couldn't compare with your application details: the AI model isn't running. Start Ollama, then choose "Re-read resume".
    </p>
    <p v-else-if="mode === 'stale'" class="notice warn rr-stale">
      This was checked against an older resume. Choose "Re-read resume" to check again.
    </p>
    <p v-else-if="mode === 'empty'" class="muted rr-empty">Your application details match your resume.</p>
    <p v-else-if="mode === 'saved'" class="notice ok rr-saved" role="status">
      Saved {{ savedCount }} {{ savedCount === 1 ? 'change' : 'changes' }}. Check them in
      <button type="button" class="link rr-go" @click="emit('go-view', 'details')">Application details</button>.
    </p>

    <template v-else-if="mode === 'plan'">
      <p class="rr-intro">Your resume has changes your application details don't. Pick what to update. Entries you edited yourself are never changed.</p>
      <ul class="rr-list">
        <li v-for="c in actionable" :key="c.id" class="rr-row" :data-op="c.op">
          <label class="rr-label">
            <input v-model="ticked[c.id]" type="checkbox" class="rr-check" :data-id="c.id">
            <span class="rr-text">
              <span class="rr-op">{{ label(c) }}</span>
              <span class="rr-list-name muted"> · {{ listName(c) }}</span>
              <template v-if="c.op === 'update'">
                <span class="rr-before">{{ line(c.list, c.before) }}</span>
                <span class="rr-arrow"><span aria-hidden="true">→</span><span class="visually-hidden">becomes</span></span>
                <span class="rr-after">{{ line(c.list, c.after) }}</span>
              </template>
              <span v-else class="rr-entry">{{ line(c.list, c.op === 'add' ? c.after : c.before) }}</span>
              <span v-if="noteOf(c)" class="rr-note muted">{{ noteOf(c) }}</span>
            </span>
          </label>
        </li>
        <li v-if="skillChange" class="rr-row rr-skills" :data-op="skillChange.op">
          <label class="rr-label">
            <input v-model="ticked[skillChange.id]" type="checkbox" class="rr-check" :data-id="skillChange.id">
            <span class="rr-text"><span class="rr-entry">{{ skillsText }}</span></span>
          </label>
          <ul v-if="addSkills.length" class="rr-chips" aria-label="Skills from your resume">
            <li v-for="sk in shownSkills" :key="sk" class="chip">{{ sk }}</li>
          </ul>
          <button v-if="moreSkills" type="button" class="link rr-more-skills" :aria-expanded="allSkills" @click="allSkills = !allSkills">
            {{ allSkills ? 'Show fewer' : `and ${moreSkills} more` }}
          </button>
        </li>
        <li v-for="c in kept" :key="c.id" class="rr-row rr-kept" data-op="kept">
          <span class="rr-text">
            <span class="rr-op">{{ label(c) }}</span>
            <span class="rr-list-name muted"> · {{ listName(c) }}</span>
            <span class="rr-entry">{{ line(c.list, c.before) }}</span>
          </span>
        </li>
      </ul>
      <details v-if="notOnResume.length" class="rr-details">
        <summary>Details</summary>
        <p class="muted rr-not-on-resume">Not on your resume, so not added: {{ notOnResume.join(', ') }}</p>
      </details>

      <p v-if="conflict" class="notice error rr-conflict" role="alert">
        Your details changed in another window. Reload to see the latest.
        <button type="button" class="rr-reload" @click="load">Reload</button>
      </p>
      <p v-else-if="problem" class="notice error rr-problem" role="alert">{{ problem }}</p>

      <div class="rr-buttons">
        <button type="button" class="primary rr-save" :disabled="!count || saving" @click="save">
          {{ saving ? 'Saving…' : `Save ${count} ${count === 1 ? 'change' : 'changes'}` }}
        </button>
        <button type="button" class="rr-not-now" :disabled="saving" @click="notNow">Not now</button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.resume-refresh {
  margin: var(--space-4) 0; padding: var(--space-4);
  border: 1px solid var(--border); border-radius: var(--radius-lg); background: var(--surface);
  max-width: 100%; overflow-wrap: anywhere;
}
.rr-title { font-size: var(--text-base, 1rem); margin: 0 0 var(--space-2); font-weight: 650; }
.rr-intro { margin: 0 0 var(--space-3); max-width: 68ch; }
.rr-list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }
.rr-row { padding: var(--space-2) 0; border-top: 1px solid var(--border); min-width: 0; }
.rr-row:first-child { border-top: 0; }
.rr-label { display: flex; gap: var(--space-2); align-items: flex-start; cursor: pointer; min-width: 0; }
.rr-check { margin-top: 0.2rem; flex: none; }
.rr-text { display: flex; flex-wrap: wrap; gap: 0 var(--space-1); min-width: 0; font-size: var(--text-sm); }
.rr-op { font-weight: 600; }
.rr-before, .rr-after, .rr-entry, .rr-note { flex-basis: 100%; min-width: 0; }
.rr-arrow { flex-basis: 100%; color: var(--muted); }
.rr-before { text-decoration: line-through; color: var(--text-2); }
.rr-note { font-size: var(--text-xs); }
.rr-chips, .rr-more-skills { margin-left: calc(1rem + var(--space-2)); }
.rr-chips { list-style: none; padding: 0; margin-top: var(--space-1); margin-bottom: 0; display: flex; flex-wrap: wrap; gap: var(--space-1); }
.rr-more-skills { margin-top: var(--space-1); padding: 0; font-size: var(--text-sm); }
.rr-kept .rr-text { padding-left: calc(1rem + var(--space-2)); }
.rr-details { margin-top: var(--space-3); font-size: var(--text-sm); }
.rr-buttons { display: flex; flex-wrap: wrap; gap: var(--space-2); margin-top: var(--space-3); }
.rr-conflict .rr-reload { margin-left: var(--space-2); }
.rr-go { padding: 0; }
</style>
