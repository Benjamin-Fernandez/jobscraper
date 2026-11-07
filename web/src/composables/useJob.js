// The background job - a run or a profile refresh - as a tab sees it (M11-T3).
// The server runs one job at a time and reports it at GET /api/jobs/current.
//
// Polling happens only while a job is running and only while the tab that asked
// is mounted: every POLL_MS until the job ends, then it stops. Unmounting the
// tab stops it too, so a closed tab never keeps a timer going.
import { computed, onBeforeUnmount, ref } from 'vue'
import { describeError, getCurrentJob } from '../api.js'

export const POLL_MS = 1500

// Ids of jobs this page has seen running. A job's end is reported once, to the
// first tab of its kind that sees it end - even if that happened while the tab
// was closed and the job is only found finished when the tab opens again.
const seenRunning = new Set()

// Listeners told when any tab starts a job (track(..., { started: true })), so
// the shell's watcher follows a job a tab began without being asked (Q-70 C1).
const starters = new Set()
export function onJobStarted(fn) {
  starters.add(fn)
  return () => starters.delete(fn)
}

// kind: 'run' | 'profile' - whose endings this tab cares about.
// onFinish(job): called once when a job of that kind is seen to end.
// consume: false makes this watcher keep its own list of seen jobs, so it can
// report an ending without taking it from the tab that is meant to hear it
// first (the shell watches all kinds and must not steal the Runs tab's toast).
export function useJob({ kind, onFinish, consume = true } = {}) {
  const seen = consume ? seenRunning : new Set()
  const job = ref(null)
  const error = ref('')
  const running = computed(() => job.value?.state === 'running')
  let timer = null
  let alive = true

  function accept(next) {
    job.value = next ?? null
    if (!next || next.id === null || next.id === undefined) return
    if (next.state === 'running') {
      seen.add(next.id)
    } else if (seen.has(next.id) && (!kind || next.kind === kind)) {
      seen.delete(next.id)
      onFinish?.(next)
    }
  }

  function schedule() {
    clearTimeout(timer)
    if (alive && running.value) timer = setTimeout(refresh, POLL_MS)
  }

  // A failed poll keeps the last known job and tries again on the next tick,
  // so a blip in the connection does not end the live view.
  async function refresh() {
    clearTimeout(timer)
    try {
      const next = await getCurrentJob()
      if (!alive) return
      error.value = ''
      accept(next)
    } catch (e) {
      if (!alive) return
      error.value = describeError(e)
    }
    schedule()
  }

  // Hand over a job the tab just started (202) or cancelled. A job this tab
  // started counts as seen running even if it has already ended by now.
  // announce: false is for a starter listener handing the job on, which would
  // otherwise announce it to itself again.
  function track(next, { started = false, announce = true } = {}) {
    if (started && next?.id !== null && next?.id !== undefined) seen.add(next.id)
    accept(next)
    if (started && announce) for (const fn of starters) fn(next)
    if (next && next.state === undefined) refresh()
    else schedule()
  }

  onBeforeUnmount(() => {
    alive = false
    clearTimeout(timer)
  })

  return { job, error, running, refresh, track }
}

// For tests: forget which jobs were seen running.
export function resetSeenJobs() {
  seenRunning.clear()
}
