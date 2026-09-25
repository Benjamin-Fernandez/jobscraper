<script setup>
// One job's state and its log tail, as the server reports it (M11 contract:
// {id, kind, state, started_at, finished_at, exit_code, log}). The log follows
// new lines while you are at the bottom of it and leaves you alone once you
// scroll up to read.
import { computed, nextTick, ref, watch } from 'vue'
import { when } from '../format.js'

const props = defineProps({
  job: { type: Object, default: null },
  title: { type: String, default: 'Log' },
})

const KIND = { run: 'Run', profile: 'Profile refresh' }

const state = computed(() => props.job?.state ?? 'idle')
const lines = computed(() => props.job?.log ?? [])

const summary = computed(() => {
  const j = props.job
  if (!j || state.value === 'idle') return 'Nothing has run since the web app started.'
  const what = KIND[j.kind] ?? 'Job'
  if (state.value === 'running') return `${what} running since ${when(j.started_at)}`
  if (state.value === 'succeeded') return `${what} finished ${when(j.finished_at)}`
  const code = j.exit_code === null || j.exit_code === undefined ? '' : ` (exit ${j.exit_code})`
  return `${what} failed${code} ${when(j.finished_at)}`.trim()
})

const logEl = ref(null)
watch(() => lines.value.length, async () => {
  const el = logEl.value
  if (!el) return
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
  await nextTick()
  if (atBottom) el.scrollTop = el.scrollHeight
})
</script>

<template>
  <div class="job-status" :data-state="state">
    <!-- The state change is announced; the log lines are not (every 1.5 s
         would drown a screen reader) - the log is focusable to read instead. -->
    <p class="summary" role="status">
      <span class="dot" aria-hidden="true" />
      <span class="state-text">{{ summary }}</span>
    </p>
    <pre
      v-if="lines.length"
      ref="logEl"
      class="log"
      role="log"
      aria-live="off"
      :aria-label="title"
      tabindex="0"
    >{{ lines.join('\n') }}</pre>
  </div>
</template>

<style scoped>
.summary { display: flex; align-items: center; gap: var(--space-2); margin: 0 0 var(--space-2); font-size: var(--text-sm); }
.dot { width: 0.6rem; height: 0.6rem; border-radius: 50%; background: var(--muted); flex: none; }
[data-state="running"] .dot { background: var(--accent); animation: blink 1.2s ease-in-out infinite; }
[data-state="succeeded"] .dot { background: var(--ok); }
[data-state="failed"] .dot { background: var(--danger); }
@keyframes blink { 50% { opacity: 0.3; } }
.log {
  margin: 0; max-height: 20rem; overflow: auto; padding: var(--space-3);
  background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius);
  font-family: var(--mono); font-size: var(--text-xs); line-height: 1.6;
  white-space: pre-wrap; overflow-wrap: anywhere;
}
</style>
