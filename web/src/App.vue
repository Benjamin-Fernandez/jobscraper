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
import { computed, defineAsyncComponent, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
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

// On a narrow screen the tab bar scrolls sideways; keep the current tab in view
// (after back/forward or a bookmark, it may be off to the right).
watch(activeId, async id => {
  await nextTick()
  tabEls[id]?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
})

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
              <!-- A tab that can carry a badge keeps its slot even while the
                   count is loading or zero, so the bar never shifts. -->
              <span v-if="tab.badge" class="badge-slot">
                <span v-if="badgeOf(tab) !== null" class="badge">
                  {{ badgeOf(tab) }}<span class="visually-hidden"> {{ tab.badgeLabel || '' }}</span>
                </span>
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
  background: color-mix(in srgb, var(--bg) 92%, transparent);
  backdrop-filter: blur(6px);
  border-bottom: 1px solid var(--border);
}
.masthead-inner {
  max-width: var(--page-w);
  margin: 0 auto;
  padding: 0 var(--gutter);
  display: flex;
  align-items: stretch;
  gap: var(--space-5);
  min-height: var(--header-h);
}
.brand {
  display: flex;
  align-items: center;
  margin: 0;
  font-size: var(--text-lg);
  font-weight: 700;
  letter-spacing: -0.01em;
  white-space: nowrap;
}
.brand a { color: var(--text); text-decoration: none; }
.brand a:hover { color: var(--text); }
.tabbar { min-width: 0; flex: 1; display: flex; }
.tablist {
  display: flex;
  gap: var(--space-1);
  overflow-x: auto;
  scrollbar-width: none;
  overscroll-behavior-x: contain;
}
.tablist::-webkit-scrollbar { display: none; }
.tab {
  position: relative;
  gap: var(--space-2);
  min-height: var(--header-h);
  padding: 0 var(--space-3);
  border: none;
  border-radius: 0;
  background: none;
  color: var(--muted);
  font-size: var(--text-sm);
  font-weight: 500;
}
.tab:hover:not(:disabled) { background: none; color: var(--text); }
/* The current tab's underline sits on the header's bottom rule. */
.tab::after {
  content: '';
  position: absolute;
  left: var(--space-2);
  right: var(--space-2);
  bottom: -1px;
  height: 2px;
  border-radius: 2px 2px 0 0;
  background: transparent;
}
.tab.current { color: var(--text); }
.tab.current::after { background: var(--accent); }
.tab:focus-visible { outline-offset: -4px; }
.badge-slot { display: inline-flex; min-width: 2.4em; }
.badge {
  font-family: var(--mono);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
  line-height: 1;
  padding: 0.2rem 0.4rem;
  border-radius: 999px;
  background: var(--accent-soft);
  color: var(--accent);
}
.tab.current .badge { background: var(--accent); color: var(--accent-text); }
.panel {
  max-width: var(--page-w);
  margin: 0 auto;
  padding: var(--space-5) var(--gutter) var(--space-7);
}
.panel:focus-visible { outline-offset: -2px; }
@media (max-width: 640px) {
  .masthead-inner { flex-direction: column; gap: 0; }
  .brand { min-height: 2.5rem; font-size: var(--text-md); }
  .tab { min-height: 2.75rem; }
  .tablist { margin: 0 calc(-1 * var(--space-3)); }
}
</style>
