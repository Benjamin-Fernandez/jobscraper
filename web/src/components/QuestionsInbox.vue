<script setup>
// Questions from applications (Q-30, F-13, questions_design.md sections 9.2 and
// 10): required questions an application asked that JobScraper had no answer it
// could back up. The owner answers each once; the answer is saved in
// data/applicant.yaml and used on every later form that asks. Applications that
// stopped on a question can then be retried, from here.
//
// Calls (api.js): GET questions?status=open|answered, POST questions/answer,
// POST questions/<key>/dismiss, POST questions/retry. An answer carries the
// etag of data/applicant.yaml (a stale one is a 409), taken from the form that
// owns the file (`etag` prop) or, when this is used alone, fetched.
import { computed, onMounted, ref, watch } from 'vue'
import {
  ApiError, answerQuestion, describeError, dismissQuestion, getApplicant, getQuestions, problemOf, retryQuestions,
} from '../api.js'
import { findItem } from '../applicantForm.js'
import { plural } from '../format.js'
import { privateBadge, privateSentence, setModelSeesPrivate } from '../privacy.js'
import { showToast } from '../toast.js'
import QuestionCard from './QuestionCard.vue'
import TabLoading from './TabLoading.vue'

const props = defineProps({
  form: { type: Array, default: null },
  etag: { type: String, default: null },
})
const emit = defineEmits(['saved', 'reload', 'loaded'])

const MAX_RETRY = 20          // the server's cap per request

const open = ref(null)        // the open-questions response
const answered = ref([])      // groups with status answered
const loading = ref(true)
const loadError = ref('')
const notOffered = ref(false) // the server has no questions routes yet
const saving = ref({})        // key -> bool
const cardError = ref({})     // key -> text
const conflict = ref({})      // key -> 'changed' | 'unreadable'
const changing = ref('')      // the answered key being edited
const retrying = ref(false)
const confirming = ref(false)
const retryProblem = ref('')
const fetched = ref(null)     // applicant, fetched only when no parent gave form/etag
const knownEtag = ref(null)   // the etag an answer just returned, until the parent catches up

const groups = computed(() => (open.value?.groups ?? []).filter(g => !g.status || g.status === 'open'))
const ready = computed(() => open.value?.ready ?? [])
const mode = computed(() => open.value?.mode ?? 'dry_run')
const busy = computed(() => !!open.value?.busy)
// D-105: the Private tag's words follow the server's effective switch.
const seesPrivate = computed(() => !!open.value?.model_sees_private)
const form = computed(() => props.form ?? fetched.value?.form ?? null)
const sending = computed(() => ready.value.slice(0, MAX_RETRY))

watch(() => props.etag, () => { knownEtag.value = null })

async function load() {
  loadError.value = ''
  try {
    const [o, a] = await Promise.all([
      getQuestions('open'),
      getQuestions('answered').catch(() => null),   // the open list matters more
    ])
    open.value = o
    setModelSeesPrivate(o?.model_sees_private)   // the cards read it from privacy.js
    answered.value = (a?.groups ?? []).filter(g => g.status === 'answered')
    emit('loaded', { open: groups.value.length, answered: answered.value.length })
  } catch (e) {
    // A server older than this page has no such route: say so quietly, not as an alert.
    if (e instanceof ApiError && e.status === 404) notOffered.value = true
    else loadError.value = describeError(e)
  } finally {
    loading.value = false
  }
}

async function fetchApplicant() {
  try { fetched.value = await getApplicant() } catch { /* no form: cards fall back to the question's own kind */ }
}

async function currentEtag() {
  if (knownEtag.value !== null) return knownEtag.value
  if (props.etag !== null) return props.etag
  await fetchApplicant()
  return fetched.value?.etag ?? ''
}

const patch = (target, key, v) => { target.value = { ...target.value, [key]: v } }

async function save(g, body, wasChange) {
  patch(saving, g.key, true)
  patch(cardError, g.key, '')
  patch(conflict, g.key, '')
  try {
    const r = await answerQuestion({ ...body, etag: await currentEtag() })
    knownEtag.value = r?.etag ?? null
    if (open.value && Array.isArray(r?.ready)) open.value = { ...open.value, ready: r.ready }
    showToast({ message: 'Saved. JobScraper will use this answer from now on.' })
    if (wasChange) changing.value = ''
    emit('saved', { etag: r?.etag ?? '' })
    await load()
  } catch (e) {
    const p = problemOf(e)
    if (p.status === 409) {
      patch(conflict, g.key, p.code === 'unreadable' ? 'unreadable' : 'changed')
    } else if (p.status === 422) {
      patch(cardError, g.key, p.errors.map(x => x.message).join('; ') || "That answer didn't fit. Check it and try again.")
    } else if (p.status === 404) {
      patch(cardError, g.key, 'This question is no longer on the list.')
      await load()
    } else {
      patch(cardError, g.key, `Could not save the answer: ${p.text}`)
    }
  } finally {
    patch(saving, g.key, false)
  }
}

async function dismiss(g) {
  patch(cardError, g.key, '')
  try {
    await dismissQuestion(g.key)
    showToast({ message: 'Okay. Applications that ask this will stop there, so you can finish them by hand.' })
    await load()
  } catch (e) {
    patch(cardError, g.key, `Could not dismiss it: ${problemOf(e).text}`)
  }
}

// "Reload" on a 409: the form owns the file, so ask it; used alone, refetch here.
async function reloadFile(g) {
  patch(conflict, g.key, '')
  knownEtag.value = null
  emit('reload')
  if (props.etag === null) await fetchApplicant()
}

// ---- retry ----

function askRetry() {
  retryProblem.value = ''
  if (mode.value === 'auto') confirming.value = true
  else retry()
}

async function retry() {
  confirming.value = false
  retrying.value = true
  retryProblem.value = ''
  try {
    await retryQuestions(sending.value.map(r => r.job_id))
    showToast({
      message: mode.value === 'auto'
        ? 'Started. The applications are being filled in and sent in Edge.'
        : 'Started. Dry run: everything is filled in and nothing is sent.',
      link: { label: 'Follow it on the Developer tab', href: '#/developer' },
    })
    await load()
  } catch (e) {
    const p = problemOf(e)
    if (p.status === 409) retryProblem.value = 'Another job is running. Retry when it finishes.'
    else if (p.status === 422) retryProblem.value = "Some of those applications can't go again yet. The list has been refreshed."
    else retryProblem.value = `Could not start the retry: ${p.text}`
    await load()
  } finally {
    retrying.value = false
  }
}

// ---- answered questions ----

const yesNo = v => (v === true ? 'Yes' : v === false ? 'No' : '')
const nice = norm => String(norm).replace(/\b\w/g, c => c.toUpperCase())
function answerText(g) {
  const c = g.current ?? {}
  const base = g.kind === 'choice' || g.kind === 'multi' ? (c.picks ?? []).map(nice).join(', ') : (yesNo(c.value) || String(c.value ?? ''))
  const per = Object.entries(c.by_employer ?? {}).map(([emp, e]) => `${nice(emp)}: ${
    g.kind === 'choice' || g.kind === 'multi' ? (e.picks ?? []).map(nice).join(', ') : (yesNo(e.value) || String(e.value ?? ''))}`)
  return [base, ...per].filter(Boolean).join(' · ')
}
const profileLabel = g => (g.target_path ? findItem(form.value ?? [], g.target_path)?.label ?? g.title : '')

onMounted(() => {
  load()
  if (props.form === null || props.etag === null) fetchApplicant()
})
defineExpose({ load })
</script>

<template>
  <section class="questions" aria-labelledby="qi-title">
    <h2 id="qi-title" class="section-title">Questions from applications</h2>
    <p class="muted lead">Employers asked these, and JobScraper had no answer it could back up. Answer once and it's used on every application that asks.</p>

    <TabLoading v-if="loading" :rows="2" />
    <p v-else-if="notOffered" class="notice warn not-offered" role="status">
      This server doesn't offer questions from applications yet. Update JobScraper and restart the web app.
    </p>
    <div v-else-if="loadError" class="notice error" role="alert">
      <p>Could not load the questions: {{ loadError }}</p>
      <button type="button" @click="load">Try again</button>
    </div>

    <template v-else>
      <div v-if="ready.length" class="ready surface" role="status">
        <p class="ready-text">
          {{ ready.length === 1 ? '1 application can go again now.' : `${ready.length} applications can go again now.` }}
          <span v-if="ready.length > MAX_RETRY" class="muted"> {{ MAX_RETRY }} at a time.</span>
        </p>
        <div v-if="confirming" class="confirm" role="group" aria-labelledby="qi-confirm-title">
          <p id="qi-confirm-title" class="confirm-title">Send {{ plural(sending.length, 'application') }} now?</p>
          <p>JobScraper fills them in and submits them in Edge.</p>
          <div class="confirm-buttons">
            <button type="button" class="primary retry-yes" @click="retry">Send applications</button>
            <button type="button" class="retry-no" @click="confirming = false">Not now</button>
          </div>
        </div>
        <button v-else type="button" class="primary retry" :disabled="retrying || busy" @click="askRetry">
          Retry {{ plural(sending.length, 'application') }}
        </button>
        <p v-if="busy" class="muted busy">Another job is running. Retry when it finishes.</p>
        <p v-if="retryProblem" class="notice error retry-problem" role="alert">{{ retryProblem }}</p>
      </div>

      <div v-if="!groups.length" class="empty none">
        <p class="empty-title">No questions waiting.</p>
        <p class="muted">When an application asks something JobScraper can't answer, it shows up here.</p>
      </div>
      <div v-else class="cards">
        <QuestionCard
          v-for="g in groups"
          :key="g.key"
          :group="g"
          :form="form"
          :saving="!!saving[g.key]"
          :error="cardError[g.key] || ''"
          :conflict="conflict[g.key] || ''"
          @save="save(g, $event, false)"
          @dismiss="dismiss(g)"
          @reload="reloadFile(g)"
        />
      </div>

      <details v-if="answered.length" class="answered">
        <summary>Answered questions ({{ answered.length }})</summary>
        <ul class="answered-list">
          <li v-for="g in answered" :key="g.key" class="answered-item" :data-key="g.key">
            <template v-if="changing !== g.key">
              <div class="answered-text">
                <span class="answered-title">{{ g.title }}</span>
                <span v-if="g.target_path" class="muted"> · in your profile: {{ profileLabel(g) }}</span>
                <span v-if="g.sensitive" class="tag private" :title="privateSentence(seesPrivate)">{{ privateBadge(seesPrivate) }}</span>
                <span class="muted answer"> {{ g.sensitive ? '•••' : answerText(g) }}</span>
              </div>
              <button type="button" class="ghost change" :aria-label="`Change answer: ${g.title}`" @click="changing = g.key">Change answer</button>
            </template>
            <QuestionCard
              v-else
              :group="g"
              :form="form"
              answered
              :saving="!!saving[g.key]"
              :error="cardError[g.key] || ''"
              :conflict="conflict[g.key] || ''"
              @save="save(g, $event, true)"
              @reload="reloadFile(g)"
              @cancel="changing = ''"
            />
          </li>
        </ul>
      </details>
    </template>
  </section>
</template>

<style scoped>
.questions { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-3); min-width: 0; }
.questions .section-title { margin: var(--space-2) 0 0; }
.lead { margin: 0; font-size: var(--text-sm); max-width: 62ch; }
.none { padding: var(--space-5) var(--space-4); }
.ready { display: grid; gap: var(--space-2); padding: var(--space-3) var(--space-4); justify-items: start; }
.ready-text { margin: 0; font-weight: 600; font-size: var(--text-sm); }
.busy { margin: 0; font-size: var(--text-sm); }
.retry-problem { margin: 0; }
.confirm { display: grid; gap: var(--space-2); padding: var(--space-3); background: var(--warn-soft); border-radius: var(--radius); }
.confirm p { margin: 0; font-size: var(--text-sm); }
.confirm-title { font-weight: 650; }
.confirm-buttons { display: flex; gap: var(--space-2); }
.cards { display: grid; gap: var(--space-3); }
.answered summary { cursor: pointer; font-size: var(--text-sm); font-weight: 600; padding: var(--space-1) 0; }
.answered-list { list-style: none; margin: var(--space-2) 0 0; padding: 0; display: grid; gap: var(--space-2); }
.answered-item { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: var(--space-2); padding: var(--space-2) var(--space-3); background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); }
.answered-item > :only-child { flex: 1 1 100%; }
.answered-title { font-weight: 600; }
.answered-text { font-size: var(--text-sm); display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-2); }
</style>
