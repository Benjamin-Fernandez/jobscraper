<script setup>
// The background job, visible from every tab (Q-70 C3, G33): a small pill in the
// masthead while a run or profile refresh is going, linking to the Runs tab.
// Nothing renders when no job is running.
//
// Auto-apply (Q-120, D-205): the worker runs the whole queue, so "1 of 4" would keep
// changing. The pill reads GET /api/apply/queue every 10 s while it runs and says
// "Auto-apply · {n} waiting", or "Auto-apply running" when nothing waits. A server
// without the queue (404) gets the plain "Auto-apply".
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ApiError, applyQueue } from '../api.js'
import { duration, utcMs } from '../format.js'

const props = defineProps({ job: { type: Object, default: null } })

const KINDS = { run: 'Run', profile: 'Profile refresh', apply: 'Auto-apply' }
const QUEUE_POLL_MS = 10000
const now = ref(Date.now())
let timer = null
onMounted(() => { timer = setInterval(() => { now.value = Date.now() }, 15000) })
onBeforeUnmount(() => clearInterval(timer))

const label = computed(() => KINDS[props.job?.kind] ?? 'Job')
const elapsed = computed(() => {
  const t = utcMs(props.job?.started_at)
  return t === null ? '' : duration((now.value - t) / 1000)
})

// ---- the queue behind an apply job ----
const waiting = ref(null)             // how many roles wait; null until known
const queueMissing = ref(false)       // the server has no queue route (old backend)
const watching = computed(() => props.job?.kind === 'apply' && props.job?.state === 'running')
let poll = null
let alive = true

async function readQueue() {
  try {
    const q = await applyQueue()
    if (!alive) return
    waiting.value = Array.isArray(q?.waiting) ? q.waiting.length : null
    queueMissing.value = false
  } catch (e) {
    if (alive && e instanceof ApiError && e.status === 404) queueMissing.value = true
    // Any other failure keeps the last number: the pill must not flicker.
  }
}
function stopPolling() {
  clearInterval(poll)
  poll = null
}
function startPolling() {
  stopPolling()
  waiting.value = null
  queueMissing.value = false
  readQueue()
  poll = setInterval(readQueue, QUEUE_POLL_MS)
}
watch(watching, on => (on ? startPolling() : stopPolling()), { immediate: true })
// The Inbox and Runs say when the queue changed: no need to wait for the next tick.
const onQueueChanged = () => { if (watching.value) readQueue() }
onMounted(() => window.addEventListener('jobscraper:apply-queue', onQueueChanged))
onBeforeUnmount(() => {
  alive = false
  stopPolling()
  window.removeEventListener('jobscraper:apply-queue', onQueueChanged)
})

const text = computed(() => {
  if (props.job?.kind === 'apply') {
    if (queueMissing.value) return 'Auto-apply'
    return waiting.value ? `Auto-apply · ${waiting.value} waiting` : 'Auto-apply running'
  }
  return `${label.value} running${elapsed.value ? ` · ${elapsed.value}` : ''}`
})
</script>

<template>
  <span v-if="job?.state === 'running'" class="job-pill" role="status">
    <span class="spinner" aria-hidden="true" />
    <a href="#/runs"><span class="job-text">{{ text }}</span></a>
  </span>
</template>

<style scoped>
.job-pill {
  display: inline-flex;
  align-items: center;
  align-self: center;
  gap: var(--space-2);
  flex: none;
  padding: 0.25rem var(--space-3);
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: var(--text-xs);
  font-weight: 600;
  white-space: nowrap;
}
.job-pill a { color: inherit; text-decoration: none; }
.job-pill a:hover { color: var(--accent-hover); text-decoration: underline; }
.spinner {
  width: 0.9rem; height: 0.9rem; flex: none; border-radius: 50%;
  border: 2px solid currentColor; border-right-color: transparent;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 640px) {
  /* Only the spinner stays; the link keeps its text for screen readers. The
     masthead is a column here, so the pill sits in the brand row's corner. */
  .job-text {
    position: absolute; width: 1px; height: 1px; overflow: hidden;
    clip: rect(0 0 0 0); white-space: nowrap;
  }
  .job-pill { position: absolute; top: 0.5rem; right: var(--gutter); padding: 0.4rem; }
}
</style>
