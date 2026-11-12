<script setup>
// The job titles the title filter searches for, and Qwen's recommendations
// (M15). Titles are chips: add one by typing, remove one with its ×, and every
// change is saved at once (PUT /api/titles) - the next run re-checks the free
// prefilter against them. The limit is the plan's (`max_titles`), so a future
// tier changes the number shown here, not this code.
//
// "Recommend titles" starts a background job (Qwen reads the resume - field of
// study, internships - and the titles here) and follows it like a run; the
// recommendations then appear as one-click adds.
import { computed, onMounted, ref } from 'vue'
import {
  ApiError, describeError, failureText, getTitles, resetTitles, saveTitles, startTitleSuggestions,
} from '../api.js'
import { useJob } from '../composables/useJob.js'
import { plural, when } from '../format.js'
import Icon from './Icon.vue'
import JobStatus from './JobStatus.vue'

const data = ref(null)
const loading = ref(true)
const loadError = ref('')
const error = ref('')
const note = ref('')
const saving = ref(false)
const draft = ref('')

const { job, running, refresh, track } = useJob({
  kind: 'titles',
  onFinish: finished => {
    if (finished.state === 'failed') error.value = failureText(finished, 'Qwen could not recommend titles - the log below says why.')
    load()
  },
})

const titles = computed(() => data.value?.titles ?? [])
// The plan's cap on titles; null is no cap (the owner's local plan, M16).
const limit = computed(() => (data.value ? data.value.max_titles ?? null : 20))
const full = computed(() => limit.value !== null && titles.value.length >= limit.value)
const suggestions = computed(() => data.value?.suggestions ?? null)
const room = computed(() => (limit.value === null ? Infinity : Math.max(0, limit.value - titles.value.length)))
const countLabel = computed(() => (limit.value === null
  ? `${titles.value.length} ${titles.value.length === 1 ? 'title' : 'titles'}`
  : `${titles.value.length} / ${limit.value}`))
const showLog = computed(() => job.value?.kind === 'titles' && (running.value || job.value.state === 'failed'))
const basedOn = computed(() => {
  const s = suggestions.value
  return s ? [s.field_of_study, ...(s.experience ?? [])].filter(Boolean) : []
})

function reason(e) {
  if (e instanceof ApiError && e.status === 422) {
    return typeof e.detail === 'string' ? e.detail : 'the server refused it'
  }
  return describeError(e)
}

async function load() {
  loadError.value = ''
  try {
    data.value = await getTitles()
  } catch (e) {
    loadError.value = describeError(e)
  } finally {
    loading.value = false
  }
}

async function save(list, message) {
  error.value = ''
  note.value = ''
  saving.value = true
  try {
    data.value = await saveTitles(list)
    note.value = message
  } catch (e) {
    error.value = `Could not save the titles: ${reason(e)}`
  } finally {
    saving.value = false
  }
}

const clean = t => String(t || '').trim().replace(/\s+/g, ' ')
const has = t => titles.value.some(x => x.toLowerCase() === t.toLowerCase())

function add(title) {
  const t = clean(title)
  if (!t) return
  if (has(t)) {
    note.value = `“${t}” is already on the list.`
    return
  }
  if (full.value) {
    error.value = `Your plan allows ${limit.value} job titles - remove one to add another.`
    return
  }
  return save([...titles.value, t], `Added “${t}”. The next run searches for it.`)
}

async function addDraft() {
  const t = draft.value
  draft.value = ''
  await add(t)
}

function addAll() {
  const fresh = (suggestions.value?.items ?? []).map(s => s.title).filter(t => !has(t)).slice(0, room.value)
  if (fresh.length) save([...titles.value, ...fresh], `Added ${plural(fresh.length, 'title')}.`)
}

function remove(title) {
  if (titles.value.length <= 1) {
    error.value = 'Keep at least one job title - or reset to the titles from your resume.'
    return
  }
  save(titles.value.filter(t => t !== title), `Removed “${title}”.`)
}

async function reset() {
  error.value = ''
  saving.value = true
  try {
    data.value = await resetTitles()
    note.value = 'Back to the titles found in your resume.'
  } catch (e) {
    error.value = `Could not reset: ${reason(e)}`
  } finally {
    saving.value = false
  }
}

async function suggest() {
  error.value = ''
  note.value = ''
  try {
    track(await startTitleSuggestions(), { started: true })
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      error.value = 'Another job (a run or a profile refresh) is running. Try again when it ends.'
      refresh()
    } else {
      error.value = `Could not ask for recommendations: ${describeError(e)}`
    }
  }
}

onMounted(() => {
  load()
  refresh()
})
</script>

<template>
  <section class="title-editor ui-card" aria-labelledby="te-title" :aria-busy="loading ? 'true' : 'false'">
    <div v-if="loading" role="status" aria-busy="true">
      <span class="visually-hidden">Loading titles…</span>
      <div class="ui-card-head" aria-hidden="true"><span class="ui-skeleton te-sk-title" /></div>
      <span class="ui-skeleton te-sk-body" aria-hidden="true" />
    </div>
    <div v-else-if="loadError" class="notice error" role="alert">
      <p>Could not load the job titles: {{ loadError }}</p>
      <button type="button" @click="load">Try again</button>
    </div>

    <template v-else-if="data">
      <header class="ui-card-head te-head">
        <h3 id="te-title" class="ui-card-title te-question">Job titles to search for</h3>
        <span class="ui-count num te-count" :class="{ full }">{{ countLabel }}</span>
      </header>
      <p class="muted small te-desc">
        A posting is kept when its title contains every word of one of these.
        {{ data.source === 'custom' ? 'You have edited this list.' : 'These came from your resume.' }}
      </p>

      <ul class="te-chips" aria-label="Job titles searched for">
        <li v-for="t in titles" :key="t" class="chip is-removable te-chip">
          <span>{{ t }}</span>
          <button type="button" class="chip-remove te-remove" :disabled="saving" :aria-label="`Remove ${t}`" @click="remove(t)">
            <Icon name="x" :size="13" />
          </button>
        </li>
      </ul>

      <form class="te-add" @submit.prevent="addDraft">
        <label class="visually-hidden" for="new-title">Add a job title</label>
        <input
          id="new-title"
          v-model="draft"
          type="text"
          maxlength="80"
          autocomplete="off"
          placeholder="Add a job title, e.g. data analyst"
          :disabled="full || saving"
        >
        <button type="submit" :disabled="!draft.trim() || full || saving"><Icon name="plus" /> Add</button>
      </form>
      <p v-if="full" class="muted small te-full">
        {{ limit }} of {{ limit }} - the most your plan ({{ data.plan }}) allows. Remove one to add another.
      </p>
      <p v-if="data.source === 'custom'" class="small">
        <button type="button" class="ghost te-reset" :disabled="saving" @click="reset">Reset to the titles from your resume</button>
      </p>

      <p v-if="error" class="notice error" role="alert">{{ error }}</p>
      <p v-if="note" class="notice ok te-note" role="status">{{ note }}</p>

      <section class="te-suggest" aria-labelledby="te-suggest-title">
        <div class="te-suggest-head">
          <div>
            <h4 id="te-suggest-title" class="te-sub">Recommended titles</h4>
            <p class="muted small">
              Qwen reads your resume - field of study, internships, skills - and the titles above,
              and suggests {{ data.max_suggestions }} new ones each time: never a title it suggested before.
            </p>
          </div>
          <button type="button" class="te-suggest-btn" :disabled="running" @click="suggest">
            <Icon name="target" /> {{ running && job?.kind === 'titles' ? 'Recommending…' : suggestions ? 'Recommend again' : 'Recommend titles' }}
          </button>
        </div>

        <JobStatus v-if="showLog" :job="job" title="Title recommendation log" />

        <template v-if="suggestions">
          <p v-if="basedOn.length" class="small te-based"><span class="muted">Based on:</span> {{ basedOn.join(' · ') }}</p>
          <p v-if="suggestions.repeated" class="notice warn small te-repeated" role="status">
            Qwen found nothing new that fits you - these are earlier recommendations you have not added.
          </p>
          <ul v-if="suggestions.items.length" class="te-suggestions" aria-label="Recommended titles">
            <li v-for="s in suggestions.items" :key="s.title">
              <button type="button" class="chip is-suggested te-suggestion" :disabled="full || saving" @click="add(s.title)">
                <Icon name="plus" :size="14" />
                <span class="visually-hidden">Add </span>
                <span class="te-s-title">{{ s.title }}</span>
                <span v-if="s.why" class="te-s-why">{{ s.why }}</span>
              </button>
            </li>
          </ul>
          <p v-else class="muted small te-none">No new titles fit you right now - everything relevant is on your list or was suggested before.</p>
          <div class="te-foot">
            <span class="muted small">Recommended {{ when(suggestions.generated_at) }}<template v-if="suggestions.model"> by {{ suggestions.model }}</template>.</span>
            <button
              v-if="suggestions.items.length && !full"
              type="button"
              class="ghost te-add-all"
              :disabled="saving"
              @click="addAll"
            >Add {{ Math.min(room, suggestions.items.length) === suggestions.items.length ? 'all' : `the first ${room}` }}</button>
          </div>
        </template>
      </section>
    </template>
  </section>
</template>

<style scoped>
/* The card itself is the global .ui-card; the grid only spaces its parts. */
.title-editor { display: grid; gap: var(--space-3); align-content: start; }
.small { font-size: var(--text-sm); margin: 0; }
.te-head { margin-bottom: 0; }
.te-desc { margin-top: calc(-1 * var(--space-1)); }
.te-count.full { color: var(--warn); background: var(--warn-soft); }
.te-chips { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: var(--space-2); }
.te-remove:hover:not(:disabled) { background: var(--danger-soft); color: var(--danger); }
.te-add { display: flex; gap: var(--space-2); }
.te-add input { flex: 1; min-width: 0; }
.notice { margin: 0; }
.te-suggest { display: grid; gap: var(--space-2); padding-top: var(--space-3); border-top: 1px solid var(--border); }
.te-suggest-head { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-start; gap: var(--space-2) var(--space-3); }
.te-sub { margin: 0; font-size: var(--text-sm); font-weight: var(--weight-semibold); }
.te-based { color: var(--text-2); }
.te-suggestions { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: var(--space-2); }
.te-suggestions li { min-width: 0; max-width: 100%; }
/* A suggestion with a reason may wrap; the chip keeps its dashed outline. */
.te-suggestion { max-width: 100%; gap: var(--space-1); white-space: normal; text-align: left; }
.te-suggestion .icon { flex: none; color: var(--accent); }
.te-s-title { font-weight: var(--weight-semibold); }
.te-s-why { color: var(--muted); font-size: var(--text-xs); }
.te-foot { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: var(--space-2); }
/* Phone: a recommendation is one full-width row (title above its reason, plus at the
   start) and the touch targets are real 44px boxes, not just padded hit areas. */
@media (max-width: 640px) {
  .te-suggestions { flex-direction: column; flex-wrap: nowrap; }
  .te-suggestions li { width: 100%; }
  .te-suggestion {
    display: grid;
    grid-template-columns: auto minmax(0, 1fr);
    column-gap: var(--space-2);
    align-items: center;
    width: 100%;
    min-height: var(--touch-min);
    padding: var(--space-2) var(--space-3);
    border-radius: var(--radius-lg);
  }
  .te-suggestion .icon { grid-column: 1; grid-row: 1 / span 2; }
  .te-s-title { grid-column: 2; min-width: 0; overflow-wrap: anywhere; }
  .te-s-why { grid-column: 2; min-width: 0; white-space: normal; overflow-wrap: anywhere; }
  .te-chip { min-height: var(--touch-min); }
  .te-remove { width: var(--touch-min); height: var(--touch-min); min-height: var(--touch-min); }
  .te-remove::after { content: none; }
}
.te-sk-title { width: 10rem; height: 1.1rem; }
.te-sk-body { height: 6rem; }
</style>
