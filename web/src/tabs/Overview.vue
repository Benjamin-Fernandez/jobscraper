<script setup>
// The home page (Q-70 wave 2, D-102/D-103): what needs the owner now, and how
// the search is going, on one screen. It reads existing endpoints only, each
// on its own, so one failure blanks one section and not the page. Pure rules
// live in overview.js; this file is markup and the four fetches. It is not in
// the KeepAlive list (O8), so every visit loads fresh numbers.
// Design: docs/architecture/ux/overview_design.md.
import { computed, onMounted, ref } from 'vue'
import { ApiError, describeError, getApplications, getCurrentJob, getQuestions, getStats, startRun } from '../api.js'
import { useJob } from '../composables/useJob.js'
import { newRoleCount } from '../badges.js'
import { ago, plural } from '../format.js'
import { runStatusLabel } from '../runs.js'
import { tabEmits, tabProps } from '../shell.js'
import { showToast } from '../toast.js'
import {
  FOLLOW_UP_SHOWN, PROFILE_VIEW_KEY, followUps, lastRunState, nextUp, pastWeek, pipeline, responseRate,
} from '../overview.js'
import SetupChecklist from '../components/SetupChecklist.vue'
import TabLoading from '../components/TabLoading.vue'

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
const pipe = computed(() => pipeline(rows.value, statuses.value))
const reply = computed(() => responseRate(rows.value, statuses.value))
const week = computed(() => pastWeek(rows.value, props.runs, now.value))
const weekQuiet = computed(() => Object.values(week.value).every(n => n === 0))

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

const weekTiles = computed(() => [
  { label: 'New roles found', n: week.value.found },
  { label: 'Saved', n: week.value.saved },
  { label: 'Applied', n: week.value.applied },
  { label: 'Other updates', n: week.value.moved },
])

const lastRunLine = computed(() => {
  const run = lastRun.value.run
  return run ? `Last run ${ago(run.finished_at, now.value)}: ${plural(Number(run.accepted) || 0, 'new role')}.` : ''
})

// The Questions card opens Profile on Application details: Profile reads this
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
        <p v-if="!firstLoad && jobRunning" class="run-line muted">
          A run is in progress. Follow it on the <a href="#/runs">Runs tab</a>.
        </p>
        <p v-else-if="!firstLoad && lastRunLine" class="run-line muted">{{ lastRunLine }}</p>
      </div>
    </header>

    <TabLoading v-if="firstLoad" :rows="3" />
    <template v-else>
      <SetupChecklist v-if="runs.length === 0" :runs="runs" />

      <section v-if="cards.length || caughtUp || errors.questions" aria-labelledby="next-title">
        <h2 id="next-title" class="section-title">Next up</h2>
        <div v-if="errors.questions" class="notice warn" role="status">
          <p>Could not check for open questions: {{ errors.questions.replace(/\.$/, '') }}.</p>
          <button type="button" class="link" @click="load">Try again</button>
        </div>
        <ul v-if="cards.length" class="next-cards">
          <li
            v-for="(item, i) in cards"
            :key="item.id"
            class="next-card surface"
            :class="{ failed: item.id === 'run' && lastRun.state === 'failed' }"
            :data-kind="item.id"
          >
            <template v-if="item.id === 'questions'">
              <h3 class="next-title">{{ plural(item.n, 'question') }} waiting for your answer</h3>
              <p class="next-body muted">
                {{ waiting > 0
                  ? `Auto-apply is paused on ${plural(waiting, 'application')} until you answer.`
                  : 'Answer once; every later form reuses it.' }}
              </p>
              <button type="button" :class="i === 0 ? 'primary' : 'ghost'" @click="openQuestions">
                Answer questions
              </button>
            </template>
            <template v-else-if="item.id === 'inbox'">
              <h3 class="next-title">{{ plural(item.n, 'new role') }} to triage</h3>
              <p class="next-body muted">Save the ones worth applying to; mark the rest Not interested.</p>
              <a class="button" :class="i === 0 ? 'primary' : 'ghost'" href="#/inbox">Open Inbox</a>
            </template>
            <template v-else-if="item.id === 'follow-up'">
              <h3 class="next-title">{{ plural(item.n, 'application') }} to follow up</h3>
              <p class="next-body muted">Applied 14 or more days ago, with no reply recorded.</p>
              <ul class="follow-list">
                <li v-for="f in due.slice(0, FOLLOW_UP_SHOWN)" :key="f.job_id">
                  {{ f.company }} · {{ f.role }} · {{ plural(f.days, 'day') }}
                </li>
                <li v-if="due.length > FOLLOW_UP_SHOWN" class="muted">
                  and {{ due.length - FOLLOW_UP_SHOWN }} more
                </li>
              </ul>
              <a class="button" :class="i === 0 ? 'primary' : 'ghost'" href="#/applications">Open Applications</a>
            </template>
            <template v-else-if="lastRun.state === 'failed'">
              <h3 class="next-title">Your last run {{ runStatusLabel(lastRun.run.status) }}</h3>
              <p class="next-body muted">See what happened on the Runs tab.</p>
              <a class="button" :class="i === 0 ? 'primary' : 'ghost'" href="#/runs">Open Runs</a>
            </template>
            <template v-else>
              <h3 class="next-title">Your last run was {{ plural(lastRun.days, 'day') }} ago</h3>
              <p class="next-body muted">New postings may be waiting. A run checks the companies that are due.</p>
              <p v-if="startError" class="notice error" role="alert">{{ startError }}</p>
              <button
                type="button"
                :class="i === 0 ? 'primary' : 'ghost'"
                :disabled="starting"
                @click="start"
              >{{ starting ? 'Starting…' : 'Start a run' }}</button>
            </template>
          </li>
        </ul>
        <div v-else-if="caughtUp" class="empty">
          <p class="empty-title">You're all caught up.</p>
          <p class="muted">Nothing needs you right now. The next run brings new roles to your Inbox.</p>
        </div>
      </section>

      <div class="overview-lower">
        <section aria-labelledby="pipe-title">
          <h2 id="pipe-title" class="section-title">Pipeline</h2>
          <div v-if="errors.apps" class="notice error" role="alert">
            <p>Could not load your applications: {{ errors.apps }}</p>
            <button type="button" @click="load">Try again</button>
          </div>
          <p v-else-if="pipe.total === 0" class="muted">
            Nothing tracked yet. Save a role in the Inbox and it shows up here.
          </p>
          <template v-else>
            <ol class="stage-tiles" aria-label="Open applications by stage, in order">
              <li
                v-for="(stage, i) in pipe.stages"
                :key="stage.status"
                class="stage-tile"
                :data-status="stage.status"
              >
                <span class="tile-n">{{ stage.n }}</span>
                <span class="tile-label">{{ stage.label }}</span>
                <span v-if="i < pipe.stages.length - 1" class="flow" aria-hidden="true">→</span>
              </li>
              <li
                class="stage-tile closed"
                :title="`Rejected ${pipe.closed.rejected} · Withdrawn ${pipe.closed.withdrawn}`"
              >
                <span class="tile-n">{{ pipe.closed.n }}</span>
                <span class="tile-label">Closed</span>
                <span class="visually-hidden">
                  (rejected {{ pipe.closed.rejected }}, withdrawn {{ pipe.closed.withdrawn }})
                </span>
              </li>
            </ol>
            <p class="response">
              <template v-if="reply.rate === null">No applications sent yet.</template>
              <template v-else>
                <strong>{{ reply.rate }}%</strong> response rate · {{ reply.heard }} of
                {{ plural(reply.applied, 'application') }} heard back
              </template>
              <span class="muted"> An interview, offer or rejection after you applied counts as a reply.</span>
            </p>
            <p class="pipe-link"><a class="link" href="#/applications">Open Applications</a></p>
          </template>
        </section>

        <section aria-labelledby="week-title">
          <h2 id="week-title" class="section-title">Past 7 days</h2>
          <div v-if="errors.apps" class="notice error" role="alert">
            <p>Could not load your applications: {{ errors.apps }}</p>
            <button type="button" @click="load">Try again</button>
          </div>
          <p v-else-if="weekQuiet" class="muted">
            A quiet week: nothing found or changed in the past 7 days.
          </p>
          <dl v-else class="week-tiles">
            <div v-for="t in weekTiles" :key="t.label" class="week-tile">
              <dt class="tile-label">{{ t.label }}</dt>
              <dd class="tile-n">{{ t.n }}</dd>
            </div>
          </dl>
        </section>
      </div>
    </template>
  </section>
</template>

<style scoped>
.run-line { margin: var(--space-2) 0 0; font-size: var(--text-sm); }
.overview > section + section,
.overview > section + .overview-lower,
.overview > .setup + section { margin-top: var(--space-6); }
.overview > :deep(.setup) { margin-bottom: var(--space-6); }

/* Next up */
.next-cards {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
  gap: var(--space-4);
}
.next-card {
  display: grid;
  align-content: start;
  gap: var(--space-2);
  padding: var(--space-4);
  border-radius: var(--radius-lg);
  border-left: 3px solid var(--accent);
}
.next-card[data-kind='questions'],
.next-card[data-kind='run'] { border-left-color: var(--warn); }
.next-card[data-kind='run'].failed { border-left-color: var(--danger); }
.next-title { margin: 0; font-size: var(--text-md); font-weight: 650; text-wrap: balance; }
.next-body { margin: 0; font-size: var(--text-sm); text-wrap: pretty; }
.next-card .notice { margin: 0; }
.next-card > button,
.next-card > a.button { justify-self: start; margin-top: var(--space-2); }
.follow-list { margin: 0; padding-left: var(--space-4); font-size: var(--text-sm); }

/* Pipeline and the past week */
.overview-lower { display: grid; grid-template-columns: 3fr 2fr; gap: var(--space-5); }
.overview-lower .section-title { margin-top: 0; }
.stage-tiles {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  gap: var(--space-4);
}
.stage-tile {
  position: relative;
  flex: 1 1 0;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  padding: var(--space-3);
  background: var(--surface);
  border: 1px solid var(--border);
  border-top: 3px solid var(--stage-closed);
  border-radius: var(--radius);
}
.stage-tile[data-status='to_apply'] { border-top-color: var(--stage-saved); }
.stage-tile[data-status='applied'] { border-top-color: var(--stage-applied); }
.stage-tile[data-status='interviewing'] { border-top-color: var(--stage-interview); }
.stage-tile[data-status='offer'] { border-top-color: var(--stage-offer); }
.stage-tile[data-status='assessment'] { border-top-color: var(--stage-assessment, var(--stage-closed)); }
.stage-tile.closed { border-top-color: var(--stage-closed); }
.flow {
  position: absolute;
  top: 50%;
  right: calc(-1 * var(--space-4));
  width: var(--space-4);
  transform: translateY(-50%);
  text-align: center;
  color: var(--muted);
}
.tile-n {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
  font-size: var(--text-2xl);
  font-weight: 650;
  color: var(--text);
}
.tile-label { font-size: var(--text-sm); color: var(--muted); }
.response { margin: var(--space-3) 0 0; font-size: var(--text-sm); }
.pipe-link { margin: var(--space-2) 0 0; font-size: var(--text-sm); }
.week-tiles {
  margin: 0;
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-3);
}
.week-tile {
  display: flex;
  flex-direction: column-reverse;
  justify-content: flex-end;
  gap: var(--space-1);
  padding: var(--space-3);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}
.week-tile dd { margin: 0; }
.week-tile dt { margin: 0; }

@media (max-width: 900px) {
  .overview-lower { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .next-cards { grid-template-columns: 1fr; }
  .stage-tiles { flex-wrap: wrap; gap: var(--space-3); }
  .stage-tile { flex: 1 1 40%; }
  .flow { display: none; }
}
</style>
