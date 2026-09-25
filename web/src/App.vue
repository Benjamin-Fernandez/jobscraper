<script setup>
// The application shell (PRD 8.5, M12-T1): a sticky header with the tab bar,
// and the active tab below it. Tabs come from the TABS registry and nothing
// here names one, so a new tab never edits this file (M7-T4).
//
// The active tab lives in the URL hash (#/inbox, #/runs, ...): refresh, back,
// forward and bookmarks all work. The shell owns the shared dataset - the run
// list, the selected run's shortlist, and the stats behind the badges - and
// hands it to every tab (see shell.js). Choosing a run fetches that run's
// shortlist and swaps it in place: one request, no navigation (M7-T2).
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { describeError, getRuns, getShortlist, getStats } from './api.js'
import { TABS } from './tabs.js'
import { hashFor, tabFromHash } from './route.js'
import TabLoading from './components/TabLoading.vue'
import TabFailed from './components/TabFailed.vue'

const runs = ref([])
const run = ref(null)
const jobs = ref([])
const stats = ref(null)
const loading = ref(true)
const error = ref('')

// Resolve each registry entry's loader once, not on every render. A chunk that
// fails to load (say, the bundle was rebuilt under an open page) shows a
// message in the panel instead of an empty page.
const tabs = TABS.map(t => ({
  ...t,
  view: defineAsyncComponent({
    loader: t.component, loadingComponent: TabLoading, errorComponent: TabFailed, delay: 150,
  }),
}))
const ids = tabs.map(t => t.id)

const activeId = ref(tabFromHash(window.location.hash, ids))
const active = computed(() => tabs.find(t => t.id === activeId.value))

// An empty or unknown hash lands on the first tab and the URL says so, without
// adding a history entry the back button would then have to step over.
function normaliseHash() {
  const want = hashFor(activeId.value)
  if (window.location.hash !== want) window.history.replaceState(window.history.state, '', want)
}
normaliseHash()

function onHashChange() {
  activeId.value = tabFromHash(window.location.hash, ids)
  normaliseHash()
}

function open(id) {
  if (id === activeId.value) return
  activeId.value = id
  window.location.hash = hashFor(id) // one history entry per tab visit
}

// Arrow keys move between tabs (WAI-ARIA tabs pattern, automatic activation):
// Left/Right wrap around, Home/End jump to the ends.
const tabEls = {}
function onTabKey(event, index) {
  const last = tabs.length - 1
  const next = {
    ArrowRight: index === last ? 0 : index + 1,
    ArrowLeft: index === 0 ? last : index - 1,
    Home: 0,
    End: last,
  }[event.key]
  if (next === undefined) return
  event.preventDefault()
  const id = tabs[next].id
  open(id)
  tabEls[id]?.focus()
}

function badgeOf(tab) {
  if (!tab.badge) return null
  const n = tab.badge({ jobs: jobs.value, stats: stats.value, runs: runs.value, run: run.value })
  return Number.isFinite(n) && n > 0 ? n : null
}

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
    if (seq === requestSeq) error.value = describeError(e)
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

// The badges are a convenience: if stats cannot be had, there is no badge,
// and the Applications tab reports the failure itself when opened.
async function loadStats() {
  try {
    stats.value = await getStats()
  } catch {
    stats.value = null
  }
}

// `follow`: a run just finished - if the newest run was on screen, move to the
// new newest one, so the Inbox shows what the run found.
async function loadRuns({ follow = false } = {}) {
  const newest = runs.value[0]?.run_no ?? null
  runs.value = await getRuns()
  if (run.value === null || (follow && run.value === newest)) {
    run.value = runs.value[0]?.run_no ?? null
  }
}

function selectRun(value) {
  if (value === run.value) return
  run.value = value
  loadJobs()
}

async function onChanged(options = {}) {
  if (options?.runs) {
    try {
      await loadRuns({ follow: true })
    } catch (e) {
      error.value = describeError(e)
    }
  }
  await Promise.all([loadJobs(), loadStats()])
}

watch(active, tab => { document.title = tab ? `${tab.label} · JobScraper` : 'JobScraper' }, { immediate: true })

onMounted(async () => {
  window.addEventListener('hashchange', onHashChange)
  try {
    await loadRuns()
  } catch (e) {
    error.value = describeError(e)
  }
  await Promise.all([loadJobs(), loadStats()])
})
onBeforeUnmount(() => window.removeEventListener('hashchange', onHashChange))
</script>

<template>
  <div class="app">
    <header class="masthead">
      <div class="masthead-inner">
        <h1 class="brand"><a :href="`#/${tabs[0]?.id}`" @click.prevent="open(tabs[0]?.id)">JobScraper</a></h1>
        <div class="tabbar">
          <div class="tablist" role="tablist" aria-label="Sections">
            <button
              v-for="(tab, i) in tabs"
              :id="`tab-${tab.id}`"
              :key="tab.id"
              :ref="el => { tabEls[tab.id] = el }"
              role="tab"
              type="button"
              class="tab"
              :class="{ current: tab.id === activeId }"
              :aria-selected="tab.id === activeId ? 'true' : 'false'"
              :aria-controls="tab.id === activeId ? `panel-${tab.id}` : undefined"
              :tabindex="tab.id === activeId ? 0 : -1"
              :data-tab="tab.id"
              @click="open(tab.id)"
              @keydown="onTabKey($event, i)"
            >
              <span class="tab-label">{{ tab.label }}</span>
              <span v-if="badgeOf(tab) !== null" class="badge">
                {{ badgeOf(tab) }}<span class="visually-hidden"> {{ tab.badgeLabel || '' }}</span>
              </span>
            </button>
          </div>
        </div>
      </div>
    </header>

    <main
      v-if="active"
      :id="`panel-${active.id}`"
      class="panel"
      role="tabpanel"
      :aria-labelledby="`tab-${active.id}`"
      tabindex="0"
    >
      <component
        :is="active.view"
        :key="active.id"
        :run="run"
        :runs="runs"
        :jobs="jobs"
        :loading="loading"
        :error="error"
        @changed="onChanged"
        @select-run="selectRun"
      />
    </main>
  </div>
</template>

<style scoped>
.masthead {
  position: sticky;
  top: 0;
  z-index: 10;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
}
.masthead-inner {
  max-width: 960px;
  margin: 0 auto;
  padding: 0 16px;
  display: flex;
  align-items: center;
  gap: 1.5rem;
}
.brand { font-size: 1.1rem; margin: 0; white-space: nowrap; }
.brand a { color: var(--text); text-decoration: none; }
.tabbar { min-width: 0; flex: 1; }
.tablist { display: flex; gap: 0.25rem; overflow-x: auto; scrollbar-width: none; }
.tab {
  display: inline-flex; align-items: center; gap: 0.4rem;
  border: none; border-bottom: 2px solid transparent; border-radius: 0;
  background: none; padding: 0.9rem 0.8rem; color: var(--muted); white-space: nowrap;
}
.tab.current { color: var(--text); border-bottom-color: var(--accent); }
.badge {
  font-size: 0.75rem; line-height: 1; padding: 0.15rem 0.45rem; border-radius: 999px;
  background: var(--accent); color: var(--accent-text); font-variant-numeric: tabular-nums;
}
.panel { max-width: 960px; margin: 0 auto; padding: 1rem 16px 48px; }
@media (max-width: 600px) {
  .masthead-inner { flex-direction: column; align-items: stretch; gap: 0; }
  .brand { padding-top: 0.6rem; }
}
</style>
