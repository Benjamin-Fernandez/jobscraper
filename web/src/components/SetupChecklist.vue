<script setup>
// Getting started (UX-1, Q-100 design §4.2). It reads what already exists and
// ticks those steps, pointing at the next one.
//
// Two parts:
//   1. "Find jobs" - resume, job titles, companies, a first run (setup.js).
//   2. "Apply for me" - application details, Local AI, and two optional extras,
//      the application mailbox and email updates (connections.js `applySteps`).
//      Only with `with-apply` (the Overview). The empty Inbox shows part 1 alone
//      and its usual empty state (the slot) once that part is done.
//
// "n of m" counts required steps whose check answered; optional steps are never
// counted. A check that failed shows "Couldn't check" on its step and is not
// counted (A7). If every check failed, one line with Try again replaces the
// checklist - never "0 of 4" to an install that is already set up.
//
// Where it shows (Overview): part 1 while there are no runs (or the run list
// could not be read); part 2 while it has an unfinished required step and the
// owner hasn't chosen "Later" (stored on this PC; Settings → Apply always shows
// readiness). Nothing at all once both are done.
import { computed, onMounted, ref } from 'vue'
import { getCompanyHealth, getCompanyList, getProfile, getTitles } from '../api.js'
import { getApplicantSummary, getApplyStatus, getConnections } from '../connections_api.js'
import { COPY, applySteps } from '../connections.js'
import { countSteps, setupSteps } from '../setup.js'
import Icon from './Icon.vue'

const props = defineProps({
  runs: { type: Array, default: () => [] },
  // False when the run list could not be loaded: "no runs" is then unknown.
  runsKnown: { type: Boolean, default: true },
  // Show part 2, "Apply for me" (the Overview).
  withApply: { type: Boolean, default: false },
})

const ready = ref(false)
const findFacts = ref(null)       // { hasResume, titleCount, companyCount, unknown: [ids] }
const applyFacts = ref(null)      // { connections, applicant } for applySteps
const later = ref(readLater())

function readLater() {
  try { return window.localStorage.getItem(LATER_KEY) === '1' } catch { return false }
}

// An established install (runs exist) needs no part 1, so it isn't fetched.
const mayOnboard = computed(() => !props.withApply || !props.runsKnown || props.runs.length === 0)

const settled = r => (r.status === 'fulfilled' ? r.value : undefined)

async function loadFind() {
  const [profile, titles, list, health] = await Promise.allSettled([
    getProfile(), getTitles(), getCompanyList(), getCompanyHealth(),
  ])
  const unknown = []
  if (profile.status === 'rejected') unknown.push('resume')
  if (titles.status === 'rejected') unknown.push('titles')
  // Your own list, or companies already watched (the curated watchlist): one
  // answer above zero is enough; a zero next to a failure is not known.
  const counts = [settled(list)?.items?.length, settled(health)?.total].filter(n => Number.isFinite(n))
  const companyCount = counts.length ? Math.max(...counts) : 0
  const companiesFailed = list.status === 'rejected' || health.status === 'rejected'
  if (companiesFailed && companyCount === 0) unknown.push('companies')
  return {
    hasResume: Boolean(settled(profile)?.present),
    titleCount: settled(titles)?.titles?.length ?? 0,
    companyCount,
    unknown,
  }
}

// What part 2 needs: the connections (Local AI, mailbox, Gmail) and what the
// application details still miss - GET /api/applicant `missing`, plus
// GET /api/apply/status `missing` when that route exists. null = couldn't check.
async function loadApply() {
  const [conn, summary, status] = await Promise.allSettled([
    getConnections(), getApplicantSummary(), getApplyStatus(),
  ])
  const connections = settled(conn) ?? null
  const fromForm = Array.isArray(settled(summary)?.missing) ? settled(summary).missing : null
  const fromApply = Array.isArray(settled(status)?.missing) ? settled(status).missing : null
  const missing = fromForm || fromApply ? [...new Set([...(fromForm ?? []), ...(fromApply ?? [])])] : null
  return {
    connections: connections && Array.isArray(connections.items) ? connections : null,
    applicant: missing === null ? null : { missing },
  }
}

async function load() {
  ready.value = false
  const [find, apply] = await Promise.all([
    mayOnboard.value ? loadFind() : null,
    props.withApply ? loadApply() : null,
  ])
  findFacts.value = find
  applyFacts.value = apply
  ready.value = true
}
onMounted(load)

// ---- part 1: Find jobs ----
const findSteps = computed(() => {
  if (!findFacts.value) return []
  const unknown = [...findFacts.value.unknown, ...(props.runsKnown ? [] : ['run'])]
  return setupSteps({ ...findFacts.value, runCount: props.runs.length, unknown })
})
const find = computed(() => countSteps(findSteps.value))
const findTodo = computed(() => findSteps.value.some(s => s.status === 'todo'))
const findUnknown = computed(() => findSteps.value.some(s => s.status === 'unknown'))
const nextId = computed(() => findSteps.value.find(s => s.status === 'todo')?.id ?? null)

// ---- part 2: Apply for me ----
const apply = computed(() => (applyFacts.value ? applySteps(applyFacts.value) : null))
const applyRequired = computed(() => (apply.value?.steps ?? []).filter(s => s.required))
const applyOptional = computed(() => (apply.value?.steps ?? []).filter(s => !s.required))
const applyTodo = computed(() => applyRequired.value.some(s => s.status === 'todo'))
const applyNextId = computed(() => applyRequired.value.find(s => s.status === 'todo')?.id ?? null)

const showFind = computed(() => mayOnboard.value && findTodo.value)
const showApply = computed(() => props.withApply && !later.value && Boolean(apply.value)
  && (showFind.value || applyTodo.value))
// Every check failed: neither part can say anything true.
const allFailed = computed(() => mayOnboard.value && findSteps.value.length > 0 && find.value.allFailed
  && (!props.withApply || later.value || !apply.value || apply.value.allFailed))

function partCount(c) {
  return c.total ? `${c.done} of ${c.total}` : "couldn't check"
}
const progress = computed(() => {
  if (!props.withApply) return `${find.value.done} of ${find.value.total} done`
  const parts = []
  if (showFind.value) parts.push(`Find jobs ${partCount(find.value)}`)
  if (showApply.value) parts.push(`Apply for me ${partCount({ done: apply.value.done, total: apply.value.total })}`)
  return parts.join(' · ')
})

function chooseLater() {
  later.value = true
  try { window.localStorage.setItem(LATER_KEY, '1') } catch { /* private window */ }
}
</script>

<script>
// "Later" on "Apply for me", kept on this PC (a test may clear it).
export const LATER_KEY = 'setup.apply.later'
</script>

<template>
  <template v-if="ready">
    <section v-if="allFailed" class="setup setup-failed surface" aria-labelledby="setup-title" role="status">
      <h3 id="setup-title" class="setup-title">{{ withApply ? 'Get set up' : 'Get your first matches' }}</h3>
      <p class="setup-sub">
        {{ COPY.setupAllFailed }}
        <button type="button" class="link setup-retry" @click="load">Try again</button>
      </p>
    </section>
    <section v-else-if="showFind || showApply" class="setup surface" aria-labelledby="setup-title">
      <header class="setup-head">
        <div>
          <h3 id="setup-title" class="setup-title">{{ withApply ? 'Get set up' : 'Get your first matches' }}</h3>
          <p v-if="!withApply" class="setup-sub muted">Four steps, once. After that, new roles arrive here after every run.</p>
          <p v-else class="setup-sub muted">Find roles that fit you, then let JobScraper fill in the applications.</p>
        </div>
        <p class="setup-progress" :class="{ num: !withApply }">{{ progress }}</p>
      </header>

      <div v-if="showFind" class="setup-part" data-part="find">
        <h4 v-if="withApply" class="setup-part-title">Find jobs</h4>
        <p v-if="findUnknown" class="notice warn setup-unknown" role="status">
          Could not check every step just now, so some may already be done. Open a step to see.
        </p>
        <div v-if="find.total" class="setup-bar" aria-hidden="true">
          <span :style="{ width: `${(find.done / find.total) * 100}%` }" />
        </div>
        <ol class="setup-steps">
          <li
            v-for="(step, i) in findSteps"
            :key="step.id"
            class="setup-step"
            :class="{ done: step.done, next: step.id === nextId, unknown: step.status === 'unknown' }"
            :data-step="step.id"
          >
            <span class="setup-mark" aria-hidden="true">
              <Icon v-if="step.done" name="check" :size="14" />
              <template v-else-if="step.status === 'unknown'">?</template>
              <template v-else>{{ i + 1 }}</template>
            </span>
            <span class="setup-text">
              <span class="setup-label">
                {{ step.label }}<span v-if="step.done" class="visually-hidden"> (done)</span>
              </span>
              <span class="setup-hint muted">
                <template v-if="step.status === 'unknown'">Couldn't check. </template>{{ step.hint }}
              </span>
            </span>
            <a
              class="button setup-go"
              :class="{ primary: step.id === nextId, ghost: step.done }"
              :href="step.href"
            >{{ step.done ? 'Review' : step.cta }}</a>
          </li>
        </ol>
      </div>

      <div v-if="showApply" class="setup-part" data-part="apply">
        <div class="setup-part-head">
          <h4 class="setup-part-title">Apply for me</h4>
          <button type="button" class="ghost setup-later" @click="chooseLater">
            Later<span class="visually-hidden">: hide the Apply for me steps</span>
          </button>
        </div>
        <ul class="setup-steps">
          <li
            v-for="step in [...applyRequired, ...applyOptional]"
            :key="step.id"
            class="setup-step"
            :class="{
              done: step.done, next: step.id === applyNextId,
              unknown: step.status === 'unknown', optional: !step.required,
            }"
            :data-step="step.id"
          >
            <span class="setup-mark" aria-hidden="true">
              <Icon v-if="step.done" name="check" :size="14" />
              <template v-else-if="step.status === 'unknown'">?</template>
              <template v-else-if="step.required">○</template>
              <template v-else>–</template>
            </span>
            <span class="setup-text">
              <span class="setup-label">
                <span v-if="!step.required" class="tag setup-optional">Optional</span>
                {{ step.label }}<span v-if="step.done" class="visually-hidden"> (done)</span>
                <span v-else-if="step.required && step.status === 'todo'" class="visually-hidden"> (to do)</span>
              </span>
              <span class="setup-hint muted">{{ step.hint }}</span>
            </span>
            <a
              class="button setup-go"
              :class="{ primary: step.id === applyNextId, ghost: step.done || !step.required }"
              :href="step.href"
            >{{ step.done ? 'Review' : step.cta }}</a>
          </li>
        </ul>
        <p class="setup-note muted">Note: {{ apply.note.charAt(0).toLowerCase() + apply.note.slice(1) }}</p>
      </div>
    </section>
    <slot v-else />
  </template>
</template>

<style scoped>
.setup { padding: var(--space-5); }
.setup-head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: var(--space-2) var(--space-4); }
.setup-title { margin: 0; font-size: var(--text-lg); font-weight: 650; text-wrap: balance; }
.setup-sub { margin: var(--space-1) 0 0; font-size: var(--text-sm); text-wrap: pretty; }
.setup-progress { margin: 0; font-size: var(--text-sm); color: var(--text-2); }
.setup-unknown { margin: var(--space-3) 0 0; }
.setup-retry { margin-left: var(--space-1); }
.setup-part + .setup-part { margin-top: var(--space-4); padding-top: var(--space-3); border-top: 1px solid var(--border); }
.setup-part-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.setup-part-title {
  margin: var(--space-4) 0 var(--space-1);
  font-size: var(--text-xs);
  font-weight: 650;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--muted);
}
.setup-part-head .setup-part-title { margin: var(--space-2) 0; }
.setup-bar { height: 4px; margin: var(--space-3) 0 var(--space-2); border-radius: 999px; background: var(--surface-3); overflow: hidden; }
.setup-bar span { display: block; height: 100%; background: var(--ok); border-radius: inherit; transition: width 0.3s ease-out; }
.setup-steps { list-style: none; margin: 0; padding: 0; }
.setup-step {
  display: grid; grid-template-columns: 1.75rem minmax(0, 1fr) auto; align-items: center;
  gap: var(--space-3); padding: var(--space-3) 0; border-top: 1px solid var(--border);
}
.setup-step:first-child { border-top: 0; }
.setup-mark {
  display: inline-flex; align-items: center; justify-content: center;
  width: 1.75rem; height: 1.75rem; border-radius: 50%;
  font-family: var(--mono); font-size: var(--text-xs); font-weight: 600;
  color: var(--muted); border: 1px solid var(--border-strong); background: var(--surface);
}
.setup-step.next .setup-mark { color: var(--accent); border-color: var(--accent); background: var(--accent-soft); }
.setup-step.done .setup-mark { color: var(--ok); border-color: transparent; background: var(--ok-soft); }
.setup-step.unknown .setup-mark { color: var(--warn); border-style: dashed; border-color: var(--warn); }
.setup-step.optional .setup-mark { border-style: dotted; }
.setup-text { display: grid; min-width: 0; }
.setup-label { font-weight: 600; font-size: var(--text-sm); }
.setup-step.done .setup-label { color: var(--text-2); font-weight: 500; }
.setup-optional { margin-right: var(--space-1); }
.setup-hint { font-size: var(--text-sm); text-wrap: pretty; }
.setup-note { margin: var(--space-2) 0 0; font-size: var(--text-sm); }
@media (max-width: 640px) {
  .setup-step { grid-template-columns: 1.75rem minmax(0, 1fr); }
  .setup-go { grid-column: 2; justify-self: start; min-height: var(--touch-min); }
  .setup-later, .setup-retry { min-height: var(--touch-min); }
}
</style>
