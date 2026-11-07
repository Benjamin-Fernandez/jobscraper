<script setup>
// The background job, visible from every tab (Q-70 C3, G33): a small pill in the
// masthead while a run or profile refresh is going, linking to the Runs tab.
// Nothing renders when no job is running.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { duration, utcMs } from '../format.js'

const props = defineProps({ job: { type: Object, default: null } })

const KINDS = { run: 'Run', profile: 'Profile refresh' }
const now = ref(Date.now())
let timer = null
onMounted(() => { timer = setInterval(() => { now.value = Date.now() }, 15000) })
onBeforeUnmount(() => clearInterval(timer))

const label = computed(() => KINDS[props.job?.kind] ?? 'Job')
const elapsed = computed(() => {
  const t = utcMs(props.job?.started_at)
  return t === null ? '' : duration((now.value - t) / 1000)
})
</script>

<template>
  <span v-if="job?.state === 'running'" class="job-pill" role="status">
    <span class="spinner" aria-hidden="true" />
    <a href="#/runs"><span class="job-text">{{ label }} running<template v-if="elapsed"> · {{ elapsed }}</template></span></a>
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
