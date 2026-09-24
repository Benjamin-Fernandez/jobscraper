<script setup>
// The one page (PRD 8.5): header with the run selector, a tab bar built from
// TABS, and the active tab. Choosing a run fetches that run's shortlist and
// swaps it in place - one request, no navigation, no per-run HTML file.
import { computed, defineAsyncComponent, onMounted, ref, shallowRef } from 'vue'
import { getRuns, getShortlist } from './api.js'
import { TABS } from './tabs.js'
import RunSelector from './components/RunSelector.vue'

const runs = ref([])
const run = ref(null)
const jobs = ref([])
const loading = ref(true)
const error = ref('')

// Resolve each registry entry's loader once, not on every render.
const tabs = TABS.map(t => ({ ...t, view: defineAsyncComponent(t.component) }))
const activeId = ref(tabs[0]?.id)
const active = computed(() => tabs.find(t => t.id === activeId.value))

// Guards against a slow response for an old run landing after a newer one.
let requestSeq = 0

async function loadJobs() {
  const seq = ++requestSeq
  loading.value = true
  error.value = ''
  try {
    const data = await getShortlist(run.value ?? 'latest')
    if (seq === requestSeq) jobs.value = data
  } catch (e) {
    if (seq === requestSeq) error.value = String(e.message || e)
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function selectRun(value) {
  if (value === run.value) return
  run.value = value
  loadJobs()
}

onMounted(async () => {
  try {
    runs.value = await getRuns()
    run.value = runs.value[0]?.run_no ?? null
  } catch (e) {
    error.value = String(e.message || e)
  }
  await loadJobs()
})
</script>

<template>
  <div class="shell">
    <header class="bar">
      <h1>JobScraper</h1>
      <RunSelector :runs="runs" :model-value="run" @update:model-value="selectRun" />
    </header>

    <nav class="tabs" role="tablist">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        role="tab"
        type="button"
        :class="{ current: tab.id === activeId }"
        :aria-selected="tab.id === activeId"
        @click="activeId = tab.id"
      >
        {{ tab.label }}
      </button>
    </nav>

    <main>
      <p v-if="error" class="error" role="alert">Could not load: {{ error }}</p>
      <p v-else-if="loading && !jobs.length" class="muted">Loading…</p>
      <component
        :is="active.view"
        v-else-if="active"
        :run="run"
        :jobs="jobs"
        @changed="loadJobs"
      />
    </main>
  </div>
</template>

<style scoped>
.shell { max-width: 960px; margin: 0 auto; padding: 0 16px 48px; }
.bar { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 0.75rem; padding: 16px 0; }
h1 { font-size: 1.25rem; margin: 0; }
.tabs { display: flex; gap: 0.25rem; border-bottom: 1px solid var(--border); margin-bottom: 1rem; }
.tabs button { border: none; border-bottom: 2px solid transparent; border-radius: 0; background: none; padding: 0.5rem 0.9rem; color: var(--muted); }
.tabs button.current { color: var(--text); border-bottom-color: var(--accent); }
.muted { color: var(--muted); }
.error { color: var(--warn); }
</style>
