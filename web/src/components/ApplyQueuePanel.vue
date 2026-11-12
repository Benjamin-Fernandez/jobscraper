<script setup>
// The auto-apply queue on the Runs tab (Q-120, D-205; docs/architecture/apply_queue_design.md
// section 7): what is being applied to now, what waits, what finished, and the three
// controls (Pause, Resume, Clear). Roles reach the queue from the Inbox; the worker is a
// background job on the server that takes them one at a time.
//
// It loads and polls GET /api/apply/queue itself: every 3 s while something is going on
// (a role in progress, roles waiting, a search run pending), every 15 s otherwise, and
// never while the browser tab is hidden. A server without the route (404) renders
// nothing: the Runs page then looks as it did before the queue and nothing is faked.
//
// Events to Runs:
//   status   { slot, runPending, available } whenever one of them changes. `slot` is who
//            holds the job slot ("free" | "apply" | "run" | "other"); Runs words its Start
//            button from it, so there is no second poller. An absent queue reports
//            { slot: 'free', runPending: false, available: false }.
//   changed  the slot, the role in progress, the newest finished role or the pending run
//            changed: Runs refreshes its own view of the current job.
// Window event `jobscraper:apply-queue`: listened to (reload at once) and sent after this
// panel's own changes, for the job pill and the Applications tab.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ApiError, applyQueue, clearApplyQueue, describeError, pauseApplyQueue, removeFromApplyQueue,
  resumeApplyQueue, stopApplyAttempt,
} from '../api.js'
import { attemptLabel } from '../attempts.js'
import { ago, duration, plural, utcMs } from '../format.js'
import StateChip from './StateChip.vue'

// The class Runs puts on the panel (`runs-queue ui-card`) goes on the section, which
// is absent while there is no queue to show.
defineOptions({ inheritAttrs: false })
const emit = defineEmits(['status', 'changed'])

const EVENT = 'jobscraper:apply-queue'
const POLL_ACTIVE_MS = 3000
const POLL_IDLE_MS = 15000

// What the worker is doing, in the owner's words.
const STATE_WORDS = {
  queued: 'Starting',
  tailoring: 'Preparing the resume',
  planning: 'Reading the form',
  opening: 'Opening the site',
  signing_in: 'Signing in',
  signing_up: 'Creating an account',
  verifying_email: 'Checking email',
  filling: 'Filling the form',
  submitting: 'Submitting',
}
const stateWord = s => STATE_WORDS[s]
  ?? (String(s || '').replace(/_/g, ' ').replace(/^./, c => c.toUpperCase()) || 'Working')

// The outcome chip of a finished role: the attempt kind's words, toned by what happened.
const OUTCOME_TONE = {
  sent: 'ok', dry_run: 'info', unconfirmed: 'warn', needs_input: 'warn', stopped: 'warn',
  cancelled: 'neutral',
}

const view = ref(null)        // the last good answer, normalised
const unavailable = ref(false) // the server has no queue (404)
const loadError = ref('')
const feedback = ref(null)    // { tone: 'ok' | 'error', text }: the result of the last control
const acting = ref('')        // 'pause' | 'resume' | 'clear' | 'stop' while its request is out
const removing = ref(new Set())
const confirmingClear = ref(false)
const clock = ref(Date.now())

const root = ref(null)
const upNextHeading = ref(null)

let timer = null
let ticker = null
let alive = true
let loadSeq = 0
let announcing = false
let lastStatus = ''
let lastSignature = null

// ---- reading the queue ----

function normalise(v) {
  return {
    paused: v?.paused ?? null,
    now: v?.now ?? null,
    slot: v?.slot ?? 'free',
    run_pending: Boolean(v?.run_pending),
    waiting: Array.isArray(v?.waiting) ? v.waiting : [],
    recent: Array.isArray(v?.recent) ? v.recent : [],
  }
}

function publish() {
  const v = view.value
  const status = {
    slot: unavailable.value || !v ? 'free' : v.slot,
    runPending: !unavailable.value && Boolean(v?.run_pending),
    available: !unavailable.value && Boolean(v),
  }
  const text = JSON.stringify(status)
  if (text !== lastStatus) {
    lastStatus = text
    emit('status', status)
  }
  if (!v || unavailable.value) return
  const signature = JSON.stringify([v.slot, v.now?.attempt_id ?? null, v.recent[0]?.attempt_id ?? null, v.run_pending])
  if (lastSignature !== null && signature !== lastSignature) emit('changed')
  lastSignature = signature
}

function setView(raw) {
  view.value = normalise(raw)
  clock.value = Date.now()
  publish()
}

const busyAny = computed(() => Boolean(acting.value) || removing.value.size > 0)
const active = computed(() => {
  const v = view.value
  return Boolean(v && (v.now || v.run_pending || v.slot === 'apply' || (v.waiting.length && !v.paused)))
})

function schedule() {
  clearTimeout(timer)
  if (!alive || unavailable.value || (typeof document !== 'undefined' && document.hidden)) return
  timer = setTimeout(poll, active.value ? POLL_ACTIVE_MS : POLL_IDLE_MS)
}

// A timer poll waits for a control's own request, whose answer is the newer view.
function poll() {
  if (busyAny.value) schedule()
  else load()
}

async function load() {
  clearTimeout(timer)
  const seq = ++loadSeq
  try {
    const v = await applyQueue()
    if (!alive || seq !== loadSeq) return
    loadError.value = ''
    setView(v)
  } catch (e) {
    if (!alive || seq !== loadSeq) return
    if (e instanceof ApiError && e.status === 404) {
      unavailable.value = true   // an older server: show nothing, ask no more
      publish()
      return
    }
    loadError.value = describeError(e)
  }
  schedule()
}

function onVisibility() {
  if (document.hidden) clearTimeout(timer)
  else if (!unavailable.value) load()
}
function onQueueEvent() {
  if (!announcing && !unavailable.value) load()
}
function announce() {
  announcing = true
  try { window.dispatchEvent(new Event(EVENT)) } finally { announcing = false }
}

onMounted(() => {
  document.addEventListener('visibilitychange', onVisibility)
  window.addEventListener(EVENT, onQueueEvent)
  load()
})
onBeforeUnmount(() => {
  alive = false
  clearTimeout(timer)
  clearInterval(ticker)
  document.removeEventListener('visibilitychange', onVisibility)
  window.removeEventListener(EVENT, onQueueEvent)
})

// The elapsed time of the role in progress ticks once a second, only while there is one.
watch(() => view.value?.now?.attempt_id ?? null, id => {
  clearInterval(ticker)
  if (id !== null) {
    clock.value = Date.now()
    ticker = setInterval(() => { clock.value = Date.now() }, 1000)
  }
}, { immediate: true })

// ---- what to show ----

const paused = computed(() => view.value?.paused ?? null)
const switchedOff = computed(() => paused.value?.reason === 'disabled')
const now = computed(() => view.value?.now ?? null)
const waiting = computed(() => view.value?.waiting ?? [])
const recent = computed(() => view.value?.recent ?? [])
const empty = computed(() => Boolean(view.value) && !paused.value && !now.value
  && !waiting.value.length && !recent.value.length && !view.value.run_pending)

const label = item => [item.company, item.role].filter(Boolean).join(' · ') || 'A role'
const plain = item => [item.company, item.role].filter(Boolean).join(' ') || 'this role'

const elapsed = computed(() => {
  const t = utcMs(now.value?.started_at)
  return t === null ? '' : duration(Math.max(0, (clock.value - t) / 1000))
})

// Roles wait because another job holds the slot, not because the queue is stuck.
const holdMessage = computed(() => {
  const v = view.value
  if (!v || v.paused || !v.waiting.length) return ''
  if (v.slot === 'run') return 'Waiting for the search run to finish. Auto-apply starts right after.'
  if (v.slot === 'other') return 'Waiting for the current job to finish.'
  return ''
})

const clearQuestion = computed(() => (waiting.value.length === 1
  ? 'Remove the waiting role from the queue? It stays in Applications under To apply.'
  : `Remove all ${waiting.value.length} waiting roles from the queue? They stay in Applications under To apply.`))

watch(() => waiting.value.length, n => { if (!n) confirmingClear.value = false })

const outcomeTone = kind => OUTCOME_TONE[kind] ?? 'neutral'
const outcomeText = item => attemptLabel(item.kind, item.mode)
const applicationHref = item => `#/applications/all/${encodeURIComponent(item.job_id)}`

// ---- the controls ----

function say(tone, text) { feedback.value = { tone, text } }

function missingPaths(e) {
  const list = e?.body?.missing
  return Array.isArray(list) && list.length ? list.join(', ') : ''
}

// Each control: busy while its request is out; the answer is the new view.
async function run(name, request, done) {
  if (busyAny.value) return
  feedback.value = null
  acting.value = name
  loadSeq++            // an older poll must not overwrite this answer
  try {
    const out = await request()
    if (!alive) return
    done(out)
    announce()
  } catch (e) {
    if (!alive) return
    failed(name, e)
  } finally {
    if (alive) {
      acting.value = ''
      schedule()
      // The flag is clear first, so the controls are enabled when focus moves.
      await nextTick()
      if (alive) restoreFocus(FOCUS_AFTER[name] ?? [])
    }
  }
}

// Where focus goes when the control that had it is gone or disabled (a button that
// turned into the paused banner, a confirm that closed). A user who moved on during the
// request is left alone. Falls back to the "Up next" heading.
const FOCUS_AFTER = {
  pause: ['.aq-resume', '.aq-pause'],
  resume: ['.aq-pause', '.aq-resume'],
  clear: ['.aq-resume', '.aq-pause'],
  stop: ['.aq-resume', '.aq-stop', '.aq-pause'],
}
function restoreFocus(selectors) {
  const el = root.value
  const a = document.activeElement
  const lost = !a || a === document.body || (el?.contains(a) && (a.disabled || !a.isConnected))
  if (!el || !lost) return
  for (const s of selectors) {
    const b = el.querySelector(s)
    if (b && !b.disabled) { b.focus(); return }
  }
  upNextHeading.value?.focus()
}

function failed(name, e) {
  if (name === 'resume' && e instanceof ApiError && e.status === 409 && e.detail === 'disabled') {
    say('error', 'Auto-apply is switched off in this copy of JobScraper (JOBSCRAPER_APPLY_QUEUE=0).')
  } else if (name === 'resume' && e instanceof ApiError && e.status === 422 && e.detail === 'profile_incomplete') {
    const missing = missingPaths(e)
    say('error', `Your application details are missing${missing ? `: ${missing}` : ''}. Fill them in under Profile → Application details, then resume.`)
  } else if (name === 'stop' && e instanceof ApiError && e.status === 409 && e.detail === 'already_finished') {
    say('error', 'That application had already finished. The queue is paused.')
    load()
  } else {
    const verbs = { pause: 'pause the queue', resume: 'resume the queue', clear: 'clear the queue', stop: 'stop the application' }
    say('error', `Could not ${verbs[name] ?? 'do that'}: ${e instanceof ApiError && typeof e.detail === 'string' && e.detail ? e.detail : describeError(e)}`)
  }
}

const pause = () => run('pause', pauseApplyQueue, v => { setView(v) })
const resume = () => run('resume', resumeApplyQueue, v => { setView(v) })

function askClear() {
  confirmingClear.value = true
  feedback.value = null
  nextTick(() => root.value?.querySelector('.aq-keep')?.focus())
}
// Focus goes back to the button that opened the question, not to the page.
function keepQueue() {
  confirmingClear.value = false
  nextTick(() => root.value?.querySelector('.aq-clear')?.focus())
}
function clearQueue() {
  confirmingClear.value = false
  return run('clear', clearApplyQueue, out => {
    if (out?.queue) setView(out.queue)
    else load()
    const n = Number(out?.removed) || 0
    say('ok', `Removed ${plural(n, 'role')} from the queue. They stay in Applications under To apply.`)
  })
}

function stop() {
  const id = now.value?.attempt_id
  if (id === undefined || id === null) return
  return run('stop', () => stopApplyAttempt(id), v => {
    setView(v)
    say('ok', 'Stopped. The queue is paused.')
  })
}

async function remove(item, index) {
  if (busyAny.value) return
  feedback.value = null
  removing.value = new Set(removing.value).add(item.job_id)
  loadSeq++
  let removed = false
  try {
    await removeFromApplyQueue(item.job_id)
    if (!alive) return
    view.value = { ...view.value, waiting: waiting.value.filter(w => w.job_id !== item.job_id) }
    publish()
    announce()
    removed = true
  } catch (e) {
    if (!alive) return
    if (e instanceof ApiError && e.status === 404) {
      say('error', `${label(item)} had already started or was no longer waiting, so it was not removed.`)
      load()
    } else {
      say('error', `Could not remove ${plain(item)} from the queue: ${describeError(e)}`)
    }
  } finally {
    if (alive) {
      const next = new Set(removing.value)
      next.delete(item.job_id)
      removing.value = next
      schedule()
      if (removed) {
        // The in-flight flag is clear first, then the DOM updates, then focus moves: a
        // disabled button cannot take it. The next Remove, else the "Up next" heading.
        await nextTick()
        if (alive) {
          const buttons = root.value?.querySelectorAll('.aq-remove') ?? []
          ;(buttons[index] ?? upNextHeading.value)?.focus()
        }
      }
    }
  }
}
</script>

<template>
  <section
    v-if="!unavailable"
    ref="root"
    v-bind="$attrs"
    class="apply-queue"
    aria-labelledby="aq-title"
    :aria-busy="!view && !loadError ? 'true' : undefined"
    @keydown.esc="confirmingClear && keepQueue()"
  >
    <header class="ui-card-head">
      <h3 id="aq-title" class="ui-card-title">Auto-apply queue</h3>
      <span v-if="view" class="ui-count" :title="plural(waiting.length, 'role') + ' waiting'">{{ waiting.length }}</span>
      <div v-if="view && !paused && (now || waiting.length)" class="ui-card-actions">
        <button type="button" class="aq-pause" :disabled="busyAny" @click="pause">
          {{ acting === 'pause' ? 'Pausing…' : 'Pause queue' }}
        </button>
        <button v-if="waiting.length" type="button" class="ghost aq-clear" :disabled="busyAny" @click="askClear">Clear queue</button>
      </div>
    </header>
    <p v-if="view && !paused && now" class="aq-note muted">The application in progress finishes first.</p>

    <!-- First load: a skeleton, so the page does not jump when the answer arrives. -->
    <div v-if="!view && !loadError" class="aq-skeleton" role="status">
      <span class="visually-hidden">Loading the queue…</span>
      <span v-for="n in 2" :key="n" class="ui-skeleton" aria-hidden="true" />
    </div>
    <div v-else-if="!view" class="notice error aq-error" role="alert">
      <p>Could not load the auto-apply queue: {{ loadError }}</p>
      <button type="button" @click="load">Try again</button>
    </div>

    <template v-if="view">
      <div v-if="paused" class="notice warn aq-paused" role="status">
        <p class="aq-paused-text"><strong>{{ paused.text }}</strong></p>
        <p v-if="paused.hint" class="aq-paused-hint">{{ paused.hint }}</p>
        <div class="aq-paused-foot">
          <span class="aq-paused-count">{{ waiting.length }} waiting</span>
          <button
            v-if="!switchedOff"
            type="button"
            class="primary aq-resume"
            :disabled="busyAny"
            @click="resume"
          >{{ acting === 'resume' ? 'Resuming…' : 'Resume' }}</button>
          <button
            v-if="waiting.length"
            type="button"
            class="aq-clear"
            :disabled="busyAny"
            @click="askClear"
          >Clear queue</button>
        </div>
      </div>

      <!-- In place, like the Settings confirm: nothing is removed until the owner says so. -->
      <div v-if="confirmingClear" class="aq-confirm" role="group" aria-labelledby="aq-confirm-text">
        <p id="aq-confirm-text" class="aq-confirm-text">{{ clearQuestion }}</p>
        <div class="aq-confirm-buttons">
          <button type="button" class="aq-confirm-yes" :disabled="busyAny" @click="clearQueue">Clear queue</button>
          <button type="button" class="aq-keep" @click="keepQueue">Keep them</button>
        </div>
      </div>

      <p v-if="feedback && feedback.text" class="notice aq-feedback" :class="feedback.tone === 'error' ? 'error' : 'ok'" :role="feedback.tone === 'error' ? 'alert' : 'status'">{{ feedback.text }}</p>
      <p v-if="loadError" class="aq-stale muted" role="status">Could not refresh the queue: {{ loadError }}. Showing the last answer.</p>

      <div v-if="empty" class="empty aq-empty-all">
        <p>No applications queued. Choose Auto-apply on roles in the Inbox; JobScraper applies to them one at a time in the background while you keep browsing.</p>
      </div>

      <template v-else>
        <h4 v-if="now" id="aq-now-title" class="aq-heading">Now applying</h4>
        <!-- The only live region: a role starting, a new step, the role ending. -->
        <div class="aq-live" aria-live="polite">
          <ul v-if="now" class="ui-list aq-now-list" aria-labelledby="aq-now-title">
            <li class="ui-list-row aq-now" :data-job="now.job_id">
              <div class="aq-main">
                <span class="ui-list-row-title aq-name">{{ label(now) }}</span>
                <span class="ui-list-row-desc aq-meta">
                  <StateChip
                    v-if="now.interrupted"
                    state="attention"
                    text="Interrupted"
                  />
                  <StateChip v-else state="checking" :text="stateWord(now.state)" />
                  <span v-if="elapsed && !now.interrupted" class="aq-elapsed" aria-hidden="true">{{ elapsed }}</span>
                  <span v-if="now.mode === 'dry_run'" class="ui-badge aq-dry" data-tone="neutral">Dry run</span>
                </span>
                <span v-if="now.interrupted" class="ui-list-row-desc aq-interrupted">Interrupted. JobScraper closes it when auto-apply next starts.</span>
              </div>
              <button
                v-if="!now.interrupted"
                type="button"
                class="aq-stop"
                :disabled="busyAny"
                @click="stop"
              >{{ acting === 'stop' ? 'Stopping…' : 'Stop this application' }}</button>
            </li>
          </ul>
        </div>

        <p v-if="view.run_pending" class="aq-line aq-run-pending muted">A search run starts when this application finishes. The queue continues after it.</p>
        <p v-else-if="holdMessage" class="aq-line aq-hold muted">{{ holdMessage }}</p>

        <h4 id="aq-next-title" ref="upNextHeading" class="aq-heading" tabindex="-1">
          Up next <span class="ui-count">{{ waiting.length }}</span>
        </h4>
        <ol v-if="waiting.length" class="ui-list aq-next" aria-labelledby="aq-next-title">
          <li v-for="(item, i) in waiting" :key="item.job_id" class="ui-list-row aq-item" :data-job="item.job_id">
            <div class="aq-main">
              <span class="ui-list-row-title aq-name">{{ i + 1 }}. {{ label(item) }}</span>
              <span class="ui-list-row-desc aq-meta">
                <span v-if="ago(item.enqueued_at, clock)" class="aq-added">added {{ ago(item.enqueued_at, clock) }}</span>
                <span v-if="item.mode === 'dry_run'" class="ui-badge aq-dry" data-tone="neutral">Dry run</span>
              </span>
              <span v-if="item.note" class="ui-list-row-desc aq-back">Back at the front: {{ item.note }}</span>
            </div>
            <button
              type="button"
              class="ghost aq-remove"
              :disabled="busyAny"
              :aria-label="`Remove ${plain(item)} from the queue`"
              @click="remove(item, i)"
            >Remove</button>
          </li>
        </ol>
        <p v-else class="aq-empty muted">Nothing waiting. Choose Auto-apply on a role in the Inbox to add it here.</p>

        <h4 class="aq-heading">Recently finished</h4>
        <ul v-if="recent.length" class="ui-list aq-recent">
          <li v-for="item in recent" :key="item.attempt_id" class="ui-list-row aq-done" :data-job="item.job_id">
            <div class="aq-main">
              <span class="ui-list-row-title aq-name">{{ label(item) }}</span>
              <span class="ui-list-row-desc aq-meta">
                <span class="ui-badge aq-outcome" :data-tone="outcomeTone(item.kind)" :title="item.text || undefined">{{ outcomeText(item) }}</span>
                <span v-if="ago(item.finished_at, clock)" class="aq-when">{{ ago(item.finished_at, clock) }}</span>
              </span>
            </div>
            <a class="text-link aq-open" :href="applicationHref(item)">Open in Applications</a>
          </li>
        </ul>
        <p v-else class="aq-empty muted">Finished applications show here.</p>
      </template>
    </template>
  </section>
</template>

<style scoped>
.aq-note { margin: calc(-1 * var(--space-1)) 0 var(--space-3); font-size: var(--text-sm); }
.aq-skeleton { display: grid; gap: var(--space-2); }
.aq-skeleton .ui-skeleton { height: var(--row-h); }
.aq-error p { margin: 0; }

.aq-heading {
  display: flex; align-items: center; gap: var(--space-2);
  margin: var(--space-4) 0 var(--space-1);
  font-size: var(--text-sm); font-weight: var(--weight-semibold); color: var(--text-2);
}
.aq-heading:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
.aq-live > .ui-list { margin-inline: calc(-1 * var(--space-4)); }
.aq-empty { margin: var(--space-2) 0 0; font-size: var(--text-sm); }
.aq-empty-all { margin-top: var(--space-2); border: 0; background: var(--surface-2); }
.aq-line { margin: var(--space-3) 0 0; font-size: var(--text-sm); }
.aq-stale { margin: 0 0 var(--space-3); font-size: var(--text-sm); }

.aq-main { display: grid; gap: var(--space-1); min-width: 0; }
.aq-meta { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-3); }
.aq-elapsed { font-variant-numeric: tabular-nums lining-nums; }
.aq-back { color: var(--warn); }

.aq-paused { display: grid; gap: var(--space-2); }
.aq-paused p { margin: 0; }
.aq-paused-foot { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2) var(--space-3); margin-top: var(--space-1); }
.aq-paused-count { margin-right: auto; font-weight: var(--weight-semibold); }

.aq-confirm {
  display: grid; gap: var(--space-2); margin-bottom: var(--space-3); padding: var(--space-3);
  background: var(--warn-soft); border-radius: var(--radius);
}
.aq-confirm p { margin: 0; font-size: var(--text-sm); }
.aq-confirm-text { font-weight: var(--weight-semibold); }
.aq-confirm-buttons { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.aq-confirm-yes, .aq-stop { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 45%, var(--border-strong)); }

.aq-feedback { margin: 0 0 var(--space-3); }

/* ---- phone: 44px targets ---- */
@media (max-width: 640px) {
  .aq-pause, .aq-clear, .aq-resume, .aq-stop, .aq-remove, .aq-confirm-buttons button, .aq-paused-foot button {
    min-height: var(--touch-min);
  }
  .aq-open { display: inline-flex; align-items: center; min-height: var(--touch-min); }
  .ui-list-row { grid-template-columns: minmax(0, 1fr); row-gap: var(--space-2); }
  .ui-list-row > button, .ui-list-row > .aq-open { justify-self: start; }
}
</style>
