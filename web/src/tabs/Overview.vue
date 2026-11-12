<script setup>
// The home page (Q-70 wave 2, D-102/D-103; rebuilt by Q-118 LA): four headline numbers,
// then what needs the owner now and how the search is going, in a 12-column grid. It
// reads existing endpoints only, each on its own, so one failure blanks one section and
// not the page. Pure rules live in overview.js; this file is markup and the four
// fetches. It is not in the KeepAlive list (O8), so every visit loads fresh numbers.
// Design: docs/architecture/ux/overview_design.md, docs/architecture/q118_ui_polish_design.md §2.
import { computed, onMounted, ref } from 'vue'
import { ApiError, describeError, getApplications, getCurrentJob, getQuestions, getStats, startRun } from '../api.js'
import { useJob } from '../composables/useJob.js'
import { newRoleCount } from '../badges.js'
import { ago, plural } from '../format.js'
import { runStatusIcon, runStatusLabel, runStatusTitle, runStatusTone } from '../runs.js'
import { tabEmits, tabProps } from '../shell.js'
import { showToast } from '../toast.js'
import {
  FOLLOW_UP_SHOWN, HARD_RUN_FAILURES, PROFILE_VIEW_KEY, followUps, kpis, lastRunState, nextUp, pastWeek, pipeline,
} from '../overview.js'
import Icon from '../components/Icon.vue'
import SetupChecklist from '../components/SetupChecklist.vue'
import KpiCard from '../ui/KpiCard.vue'
import ProgressSegments from '../ui/ProgressSegments.vue'

const props = defineProps(tabProps)
defineEmits(tabEmits)

const apps = ref(null)          // application rows, null until loaded or failed
const statuses = ref([])        // the stage vocabulary from /api/stats (config order)
const questions = ref(null)     // GET /api/questions?status=open
const job = ref(null)           // the background job, if any
const errors = ref({ apps: '', questions: '' })
const firstLoad = ref(true)
const starting = ref(false)
const startError = ref('')
// Read once per load: the page is a snapshot, not a ticking clock.
const now = ref(Date.now())

// Hands a run this page started to the shell's pill and finish toast (Q-70 C1).
// `consume: false` keeps its list of seen jobs apart from the Runs tab's.
const watcher = useJob({ kind: 'run', consume: false })

async function load() {
  const [a, s, q, j] = await Promise.allSettled([
    getApplications(), getStats(), getQuestions('open'), getCurrentJob(),
  ])
  now.value = Date.now()
  apps.value = a.status === 'fulfilled' ? a.value : null
  errors.value.apps = a.status === 'rejected' ? describeError(a.reason) : ''
  statuses.value = s.status === 'fulfilled' ? (s.value?.statuses ?? []) : []
  questions.value = q.status === 'fulfilled' ? q.value : null
  errors.value.questions = q.status === 'rejected' ? describeError(q.reason) : ''
  job.value = j.status === 'fulfilled' ? j.value : null
  firstLoad.value = false
}
onMounted(load)

const rows = computed(() => apps.value ?? [])
const jobRunning = computed(() => job.value?.state === 'running')
const lastRun = computed(() => lastRunState(props.runs, now.value))
const due = computed(() => followUps(rows.value, now.value))
const pipe = computed(() => pipeline(rows.value))
const numbers = computed(() => kpis(rows.value, props.jobs, statuses.value))
const week = computed(() => pastWeek(rows.value, props.runs, now.value))
const weekQuiet = computed(() => Object.values(week.value).every(n => n === 0))

// The headline cards. Response rate has no link: it is a measure, not a list.
const REPLY_HINT = 'An interview, offer or rejection after you applied counts as a reply.'
const kpiCards = computed(() => {
  const n = numbers.value
  const known = !errors.value.apps
  const reply = n.reply
  return [
    { id: 'new', label: 'New roles', value: n.newRoles, caption: 'in your Inbox', href: '#/inbox' },
    {
      id: 'active', label: 'Active applications', value: known ? n.active : null,
      caption: known ? 'Not rejected or withdrawn' : 'Unavailable', href: '#/applications/active',
    },
    {
      id: 'interviews', label: 'Interviews', value: known ? n.interviews : null,
      caption: !known ? 'Unavailable' : n.offers > 0 ? plural(n.offers, 'offer') : 'No offers yet',
      href: '#/applications/interviewing',
    },
    {
      id: 'reply', label: 'Response rate', value: known && reply.rate !== null ? `${reply.rate}%` : null,
      caption: !known ? 'Unavailable'
        : reply.rate === null ? 'No applications sent yet.' : `${reply.heard} of ${reply.applied} heard back`,
      hint: REPLY_HINT,
    },
  ]
})

// The pipeline bar: a stage links to the Applications tab filtered to it. Rejected is set
// apart and muted (its tone is the grey one) and says how many of them were withdrawn.
const segments = computed(() => pipe.value.segments.map(s => ({
  ...s,
  tone: s.id === 'rejected' ? 'closed' : s.id,
  href: `#/applications/${s.id}`,
  apart: s.id === 'rejected',
  note: s.id === 'rejected' && pipe.value.withdrawn > 0 ? `(${pipe.value.withdrawn} withdrawn)` : '',
})))

const openGroups = computed(() =>
  (questions.value?.groups ?? []).filter(g => !g.status || g.status === 'open').length)
const waiting = computed(() => (questions.value?.waiting ?? []).length)

const cards = computed(() => nextUp({
  newRoles: newRoleCount(props.jobs),
  questions: openGroups.value,
  followUps: due.value,
  run: lastRun.value,
  jobRunning: jobRunning.value,
}))
// Not "caught up" when the questions check failed: we don't know.
const caughtUp = computed(() => cards.value.length === 0 && props.runs.length > 0 && !errors.value.questions)

// `week.saved` counts moves to "To apply" (a role saved or queued).
const weekStats = computed(() => [
  { label: 'New roles found', n: week.value.found },
  { label: 'To apply', n: week.value.saved },
  { label: 'Applied', n: week.value.applied },
  { label: 'Other updates', n: week.value.moved },
])

// Why the last run stopped, when the run stored a reason (Q-100 A15): the
// pipeline writes `stats.reason` - "cancelled" or the error.
const failReason = computed(() => {
  const reason = String(lastRun.value.run?.stats?.reason ?? '').trim().replace(/\.$/, '')
  if (!reason) return ''
  return reason === 'cancelled' ? 'It was cancelled.' : `Reason: ${reason}.`
})

// The Last run card: what the newest real run found. `companies_due` is how many companies
// that run checked (the Runs tab reads the same key).
const lastRunFacts = computed(() => {
  const run = lastRun.value.run
  if (!run) return ''
  const found = plural(Number(run.accepted) || 0, 'new role')
  const checked = Number(run.stats?.companies_due) || 0
  return checked ? `${found} · ${plural(checked, 'company', 'companies')} checked` : found
})
const lastRunReason = computed(() => (HARD_RUN_FAILURES.includes(lastRun.value.run?.status) ? failReason.value : ''))

// The questions row opens Profile on Application details: Profile reads this
// key on mount (O6), so Profile.vue needs no change.
function openQuestions() {
  try {
    window.localStorage.setItem(PROFILE_VIEW_KEY, 'details')
  } catch { /* storage blocked: Profile opens on its usual view */ }
  window.location.hash = '#/profile'
}

async function start() {
  if (starting.value) return
  starting.value = true
  startError.value = ''
  try {
    const started = await startRun({})
    if (started?.deferred) {
      // 202 {deferred: true} (Q-120): the auto-apply worker holds the slot, so no run has
      // started. The server starts it when the current application finishes.
      showToast({
        message: 'The search run starts when the current application finishes.',
        link: { label: 'Open Runs', href: '#/runs' },
      })
      return
    }
    watcher.track(started, { started: true })
    job.value = { ...started, state: started?.state ?? 'running' }
    showToast({
      message: 'Run started. New roles land in the Inbox when it finishes.',
      link: { label: 'Open Runs', href: '#/runs' },
    })
  } catch (e) {
    startError.value = e instanceof ApiError && e.status === 409
      ? 'A job is already running. Follow it on the Runs tab.'
      : `Could not start the run: ${describeError(e)}`
  } finally {
    starting.value = false
  }
}
</script>


<template>
  <section class="overview" aria-labelledby="overview-title">
    <header class="page-head">
      <div>
        <h2 id="overview-title" class="page-title">Overview</h2>
        <p class="page-sub">Where your search stands, and what to do next.</p>
      </div>
    </header>

    <!-- The page holds its shape while it loads: four number cards and two cards. -->
    <div v-if="firstLoad" class="ov-stack" role="status" aria-busy="true">
      <span class="visually-hidden">Loading…</span>
      <div class="ui-grid ov-kpis" aria-hidden="true">
        <span v-for="n in 4" :key="n" class="ui-skeleton ov-sk-kpi span-3" />
      </div>
      <div class="ui-grid" aria-hidden="true">
        <span class="ui-skeleton ov-sk-card span-8" />
        <span class="ui-skeleton ov-sk-card span-4" />
      </div>
    </div>
    <div v-else class="ov-stack">
      <!-- Q-100 §4.2: it decides itself what to show - part 1 while there are no
           runs, part 2 while applying still needs something - and shows nothing
           once both are done. -->
      <SetupChecklist :runs="runs" :runs-known="!runsError" with-apply />

      <div class="ui-grid ov-kpis" role="group" aria-label="Headline numbers">
        <KpiCard
          v-for="k in kpiCards"
          :key="k.id"
          class="span-3"
          :data-kpi="k.id"
          :label="k.label"
          :value="k.value"
          :caption="k.caption"
          :hint="k.hint"
          :href="k.href"
        />
      </div>

      <div class="ui-grid">
        <div class="ov-col span-8">
          <section
            v-if="cards.length || caughtUp || errors.questions"
            class="ui-card"
            aria-labelledby="todo-title"
          >
            <header class="ui-card-head">
              <h3 id="todo-title" class="ui-card-title">To do</h3>
              <span v-if="cards.length" class="ui-count num">{{ cards.length }}</span>
            </header>
            <div v-if="errors.questions" class="notice warn ov-notice" role="status">
              <p>Could not check for open questions: {{ errors.questions.replace(/\.$/, '') }}.</p>
              <button type="button" @click="load">Try again</button>
            </div>
            <ul v-if="cards.length" class="ui-list">
              <li
                v-for="(item, i) in cards"
                :key="item.id"
                class="ui-list-row todo-row"
                :class="{ failed: item.id === 'run' && lastRun.state === 'failed' }"
                :data-kind="item.id"
              >
                <template v-if="item.id === 'questions'">
                  <div>
                    <span class="ui-list-row-title">{{ plural(item.n, 'question') }} waiting for your answer</span>
                    <span class="ui-list-row-desc">
                      {{ waiting > 0
                        ? `Auto-apply is paused on ${plural(waiting, 'application')} until you answer.`
                        : 'Answer once; every later form reuses it.' }}
                    </span>
                  </div>
                  <button type="button" :class="{ primary: i === 0 }" @click="openQuestions">Answer questions</button>
                </template>
                <template v-else-if="item.id === 'inbox'">
                  <div>
                    <span class="ui-list-row-title">Triage {{ plural(item.n, 'new role') }}</span>
                    <span class="ui-list-row-desc">Save the ones worth applying to; mark the rest Not interested.</span>
                  </div>
                  <a class="button" :class="{ primary: i === 0 }" href="#/inbox">Open Inbox</a>
                </template>
                <template v-else-if="item.id === 'follow-up'">
                  <div>
                    <span class="ui-list-row-title">Follow up on {{ plural(item.n, 'application') }}</span>
                    <span class="ui-list-row-desc">Applied 14 or more days ago, with no reply recorded.</span>
                  </div>
                  <a class="button" :class="{ primary: i === 0 }" href="#/applications/applied">Review</a>
                  <ul class="todo-sub">
                    <li v-for="f in due.slice(0, FOLLOW_UP_SHOWN)" :key="f.job_id">
                      <span class="todo-sub-name">{{ f.company }} · {{ f.role }}</span>
                      <span class="todo-sub-days num">{{ plural(f.days, 'day') }}</span>
                    </li>
                    <li v-if="due.length > FOLLOW_UP_SHOWN" class="muted">
                      and {{ due.length - FOLLOW_UP_SHOWN }} more
                    </li>
                  </ul>
                </template>
                <template v-else-if="lastRun.state === 'failed'">
                  <div>
                    <span class="ui-list-row-title">Your last run {{ runStatusLabel(lastRun.run.status) }}</span>
                    <span class="ui-list-row-desc">{{ failReason ? `${failReason} ` : '' }}See what happened on the Runs tab.</span>
                  </div>
                  <a class="button" :class="{ primary: i === 0 }" href="#/runs">Open Runs</a>
                </template>
                <template v-else>
                  <div>
                    <span class="ui-list-row-title">Your last run was {{ plural(lastRun.days, 'day') }} ago</span>
                    <span class="ui-list-row-desc">New postings may be waiting. A run checks the companies that are due.</span>
                  </div>
                  <button type="button" :class="{ primary: i === 0 }" :disabled="starting" @click="start">
                    {{ starting ? 'Starting…' : 'Start a run' }}
                  </button>
                  <p v-if="startError" class="notice error todo-error" role="alert">{{ startError }}</p>
                </template>
              </li>
            </ul>
            <div v-else-if="caughtUp" class="ov-caught-up">
              <p class="ui-list-row-title">You're all caught up.</p>
              <p class="ui-list-row-desc">Nothing needs you right now. The next run brings new roles to your Inbox.</p>
            </div>
          </section>

          <section class="ui-card" aria-labelledby="pipe-title">
            <header class="ui-card-head">
              <h3 id="pipe-title" class="ui-card-title">Pipeline</h3>
              <span v-if="!errors.apps && pipe.total > 0" class="ui-count num">{{ pipe.total }} tracked</span>
            </header>
            <div v-if="errors.apps" class="notice error ov-notice" role="alert">
              <p>Could not load your applications: {{ errors.apps }}</p>
              <button type="button" @click="load">Try again</button>
            </div>
            <p v-else-if="pipe.total === 0" class="ov-empty muted">
              Nothing tracked yet. Save a role in the Inbox and it shows up here.
            </p>
            <template v-else>
              <ProgressSegments :segments="segments" label="Applications by stage" />
              <p v-if="pipe.toApply > 0" class="ov-foot muted">
                Also waiting to be applied to:
                <a class="text-link" href="#/applications/active">{{ pipe.toApply }} to apply</a>
              </p>
            </template>
          </section>
        </div>

        <div class="ov-col span-4">
          <section class="ui-card" aria-labelledby="run-title">
            <header class="ui-card-head">
              <h3 id="run-title" class="ui-card-title">Last run</h3>
            </header>
            <template v-if="jobRunning">
              <p class="ov-run-head">
                <span class="ui-badge" data-tone="info"><Icon name="clock" :size="12" /> Running</span>
              </p>
              <p class="ov-run-facts muted">Follow it on the Runs tab.</p>
            </template>
            <template v-else-if="lastRun.run">
              <p class="ov-run-head">
                <span class="ui-badge" :data-tone="runStatusTone(lastRun.run.status)">
                  <Icon v-if="runStatusIcon(lastRun.run.status)" :name="runStatusIcon(lastRun.run.status)" :size="12" />
                  {{ runStatusTitle(lastRun.run.status) }}
                </span>
                <span class="ov-run-ago muted">{{ ago(lastRun.run.finished_at, now) }}</span>
              </p>
              <p class="ov-run-facts">{{ lastRunFacts }}</p>
              <p v-if="lastRunReason" class="ov-run-facts muted">{{ lastRunReason }}</p>
            </template>
            <p v-else class="ov-run-facts muted">No runs yet.</p>
            <p class="ov-actions"><a class="button ghost" href="#/runs">Open Runs</a></p>
          </section>

          <section class="ui-card" aria-labelledby="week-title">
            <header class="ui-card-head">
              <h3 id="week-title" class="ui-card-title">Past 7 days</h3>
            </header>
            <div v-if="errors.apps" class="notice error ov-notice" role="alert">
              <p>Could not load your applications: {{ errors.apps }}</p>
              <button type="button" @click="load">Try again</button>
            </div>
            <p v-else-if="weekQuiet" class="ov-empty muted">
              A quiet week: nothing found or changed in the past 7 days.
            </p>
            <dl v-else class="week-stats">
              <div v-for="t in weekStats" :key="t.label" class="week-stat" :class="{ 'is-zero': t.n === 0 }">
                <dt>{{ t.label }}</dt>
                <dd class="num">{{ t.n }}</dd>
              </div>
            </dl>
          </section>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
/* One column of blocks, --space-6 apart (design section 1: sections --space-6 apart). */
.ov-stack { display: flex; flex-direction: column; gap: var(--space-6); }
/* Number cards are the same height whatever their caption says. */
.ov-kpis { align-items: stretch; }
.ov-col { display: flex; flex-direction: column; gap: var(--space-5); min-width: 0; }

.ov-sk-kpi { min-height: 6.5rem; border-radius: var(--radius-lg); }
.ov-sk-card { min-height: 12rem; border-radius: var(--radius-lg); }

.ov-notice { margin: 0 0 var(--space-3); }
.ov-empty { margin: 0; font-size: var(--text-sm); }
.ov-caught-up p { margin: 0; }
.ov-foot { margin: var(--space-3) 0 0; font-size: var(--text-sm); }
.ov-actions { margin: var(--space-3) 0 0; }
.ov-run-head { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2); margin: 0; }
.ov-run-ago { font-size: var(--text-sm); }
.ov-run-facts { margin: var(--space-2) 0 0; font-size: var(--text-sm); }

/* To do: a .ui-list row, an action on the right; the follow-up row lists its roles below. */
.todo-row.failed .ui-list-row-title { color: var(--danger); }
.todo-row > button, .todo-row > a.button { justify-self: end; }
.todo-sub, .todo-error { grid-column: 1 / -1; }
.todo-sub {
  list-style: none;
  margin: var(--space-2) 0 0;
  padding: var(--space-2) var(--space-3);
  display: grid;
  gap: var(--space-1);
  font-size: var(--text-sm);
  background: var(--surface-2);
  border-radius: var(--radius);
}
.todo-sub li { display: flex; justify-content: space-between; gap: var(--space-3); min-width: 0; }
.todo-sub-name { min-width: 0; overflow-wrap: anywhere; }
.todo-sub-days { flex: none; color: var(--muted); }
.todo-error { margin: var(--space-2) 0 0; }

/* Past 7 days: four small numbers, two across. */
.week-stats { margin: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-4) var(--space-3); }
.week-stat { display: flex; flex-direction: column-reverse; justify-content: flex-end; gap: 2px; min-width: 0; }
.week-stat dt { margin: 0; font-size: var(--text-xs); color: var(--muted); }
.week-stat dd { margin: 0; font-size: var(--text-lg); font-weight: var(--weight-semibold); line-height: var(--leading-tight); }
.week-stat.is-zero dd { color: var(--muted); font-weight: 400; }

@media (max-width: 480px) {
  /* Too narrow for words and a button side by side: the action drops under the text. */
  .todo-row { grid-template-columns: minmax(0, 1fr); row-gap: var(--space-2); }
  .todo-row > button, .todo-row > a.button { justify-self: start; }
}
@media (max-width: 640px) {
  .ov-stack { gap: var(--space-5); }
  .ov-col { gap: var(--space-3); }
  .ov-sk-kpi { min-height: 5.5rem; }
  .ov-foot .text-link { display: inline-flex; align-items: center; min-height: var(--touch-min); }
}
</style>
