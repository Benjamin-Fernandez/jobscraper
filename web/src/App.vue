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
import { ApiError, describeError, failureText, getQuestions, getRuns, getShortlist, getStats } from './api.js'
import { onJobStarted, useJob } from './composables/useJob.js'
import { showToast } from './toast.js'
import { TABS } from './tabs.js'
import { runQuery, sameRun } from './runs.js'
import { hashFor, tabFromHash } from './route.js'
import { createShellKeys, goKeysOf } from './shortcuts.js'
import TabLoading from './components/TabLoading.vue'
import TabFailed from './components/TabFailed.vue'
import ToastHost from './components/ToastHost.vue'
import JobPill from './components/JobPill.vue'
import ShortcutsSheet from './components/ShortcutsSheet.vue'

const runs = ref([])
// What the Inbox shows (M15): 'all' (the default), 'week', 'month', or the
// runs chosen on the Runs tab. See runs.js.
const run = ref('all')
const jobs = ref([])
const stats = ref(null)
// Applications waiting on an answer (Q-75 N7); null until the server has said.
const openQuestions = ref(null)
const loading = ref(true)
const error = ref('')
// Why the run list failed to load (G20): apart from `error`, which every shortlist
// load clears; the Runs tab shows it.
const runsError = ref('')

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
  const n = tab.badge({ jobs: jobs.value, stats: stats.value, runs: runs.value, run: run.value, openQuestions: openQuestions.value })
  return Number.isFinite(n) && n > 0 ? n : null
}

// Guards against a slow response for an old run landing after a newer one.
let requestSeq = 0

async function loadJobs() {
  const seq = ++requestSeq
  loading.value = true
  error.value = ''
  try {
    const data = await getShortlist(runQuery(run.value))
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

// The Profile tab's badge. Open question groups, as the Application details
// view counts them; a server without the questions routes, or a failed call,
// means no badge. Only the newest call may write (as loadJobs).
let questionsSeq = 0
async function loadQuestions() {
  const seq = ++questionsSeq
  let n = null
  try {
    const data = await getQuestions('open')
    n = (data?.groups ?? []).filter(g => !g.status || g.status === 'open').length
  } catch {
    n = null
  }
  if (seq === questionsSeq) openQuestions.value = n
}

// A finished run needs no following any more (M15): All runs, Past week and
// Past month all take it in on the reload that comes with the new run list.
// Same guard as loadJobs (Vue review, M12): only the newest call may write.
let runsSeq = 0

async function loadRuns() {
  const seq = ++runsSeq
  const data = await getRuns()
  if (seq !== runsSeq) return
  runs.value = data
  runsError.value = ''
}

function selectRun(value) {
  if (sameRun(value, run.value)) return
  run.value = value
  loadJobs()
}

async function onChanged(options = {}) {
  if (options?.runs) {
    try {
      await loadRuns()
    } catch (e) {
      runsError.value = describeError(e)
    }
  }
  await Promise.all([loadJobs(), loadStats(), loadQuestions()])
}

// The shell watches the background job for every tab (Q-70 C2, G7): a run that
// finishes while the owner is on Profile or Applications still refreshes the
// Inbox and says so. `consume: false` keeps its list of seen jobs apart, so the
// Runs tab's own watcher still hears the ending first-hand.
const shell = useJob({
  consume: false,
  onFinish: j => {
    onChanged({ runs: j.kind === 'run' })
    if (j.kind === 'run') {
      showToast({
        message: j.state === 'succeeded' ? 'Run finished. New roles are in the Inbox.' : failureText(j, 'The run stopped.'),
        link: { label: 'Open Runs', href: '#/runs' },
      })
    }
  },
})
// Coming back to the page, the job may have ended while the timers slept.
function onVisible() {
  if (document.visibilityState === 'visible') shell.refresh()
}
let stopStarters = () => {}

watch(active, tab => { document.title = tab ? `${tab.label} · JobScraper` : 'JobScraper' }, { immediate: true })

// On a narrow screen the tab bar scrolls sideways; keep the current tab in view
// (after back/forward or a bookmark, it may be off to the right).
watch(activeId, async id => {
  await nextTick()
  tabEls[id]?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' })
})

// A fade at the right edge says the tab bar scrolls (Q-70 C8, G29): on a phone
// the later tabs are off screen with nothing to hint at them.
const tablistEl = ref(null)
const moreRight = ref(false)
function measureTabs() {
  const el = tablistEl.value
  if (el) moreRight.value = el.scrollLeft + el.clientWidth < el.scrollWidth - 1
}

// Leaving Profile, where questions get answered, refreshes its badge.
watch(activeId, (_, was) => { if (was === 'profile') loadQuestions() })

// The keyboard layer (Q-75 N16, shortcuts.js): "/" jumps to the open tab's
// search box, "g" then a letter goes to a tab, "?" opens the key sheet. It
// listens in the capture phase so a go-to key is spent before the Inbox's own
// keys (S, A, X ...) can hear it.
const helpOpen = ref(false)
const goKeys = goKeysOf(tabs)

function focusSearch() {
  const box = document.querySelector('.panel input[type="search"]')
  if (!box) return false
  box.focus()
  box.select?.()
  return true
}

// Going by key moves the focus to the new panel, which names itself to a
// screen reader (aria-labelledby the tab); a click on a tab needs no such help.
async function goTo(id) {
  open(id)
  await nextTick()
  document.getElementById(`panel-${id}`)?.focus({ preventScroll: true })
}

const keys = createShellKeys({
  tabs, go: goTo, focusSearch,
  toggleHelp: () => { helpOpen.value = !helpOpen.value },
  isOpen: () => helpOpen.value,
})
function onShellKey(event) { keys.onKeydown(event) }

// The first load. A network failure (not an ApiError: the server answered
// nothing at all) means every tab would show the same error, so one screen
// says so, with a Retry. A server that answers with an error is left to the
// tabs, as before.
const bootError = ref(false)
const retrying = ref(false)

async function boot() {
  retrying.value = true
  bootError.value = false
  try {
    await loadRuns()
  } catch (e) {
    if (!(e instanceof ApiError)) {
      bootError.value = true
      retrying.value = false
      return
    }
    runsError.value = describeError(e)
  }
  retrying.value = false
  await Promise.all([loadJobs(), loadStats(), loadQuestions()])
}

onMounted(() => {
  window.addEventListener('hashchange', onHashChange)
  window.addEventListener('keydown', onShellKey, true)
  window.addEventListener('resize', measureTabs)
  measureTabs()
  document.addEventListener('visibilitychange', onVisible)
  stopStarters = onJobStarted(j => shell.track(j, { started: true, announce: false }))
  shell.refresh()
  return boot()
})
onBeforeUnmount(() => {
  window.removeEventListener('hashchange', onHashChange)
  window.removeEventListener('keydown', onShellKey, true)
  window.removeEventListener('resize', measureTabs)
  document.removeEventListener('visibilitychange', onVisible)
  stopStarters()
})
</script>

<template>
  <div class="app">
    <header class="masthead" :inert="helpOpen || undefined">
      <div class="masthead-inner">
        <h1 class="brand">
          <a :href="`#/${tabs[0]?.id}`" @click.prevent="open(tabs[0]?.id)">
            <svg class="logo" viewBox="0 0 32 32" aria-hidden="true" focusable="false">
              <rect width="32" height="32" rx="8" />
              <path d="M9 11h14M9 16h14M9 21h9" />
            </svg>JobScraper</a>
        </h1>
        <div class="tabbar">
          <div
            ref="tablistEl"
            class="tablist"
            :class="{ 'more-right': moreRight }"
            role="tablist"
            aria-label="Sections"
            @scroll="measureTabs"
          >
            <button
              v-for="(tab, i) in tabs"
              :id="`tab-${tab.id}`"
              :key="tab.id"
              :ref="el => { tabEls[tab.id] = el }"
              role="tab"
              type="button"
              class="tab"
              :class="{ current: tab.id === activeId, quiet: tab.quiet }"
              :aria-selected="tab.id === activeId ? 'true' : 'false'"
              :aria-controls="tab.id === activeId ? `panel-${tab.id}` : undefined"
              :tabindex="tab.id === activeId ? 0 : -1"
              :data-tab="tab.id"
              @click="open(tab.id)"
              @keydown="onTabKey($event, i)"
            >
              <span class="tab-label">{{ tab.label }}</span>
              <!-- Only a count takes space (UX-1): an empty reserved slot left
                   uneven gaps between the tabs. -->
              <span v-if="badgeOf(tab) !== null" class="badge-slot">
                <span class="badge">
                  {{ badgeOf(tab) }}<span class="visually-hidden"> {{ tab.badgeLabel || '' }}</span>
                </span>
              </span>
            </button>
          </div>
        </div>
        <JobPill :job="shell.job.value" />
      </div>
    </header>

    <main v-if="bootError" class="panel boot-error" role="alert">
      <h2 class="page-title">Could not reach JobScraper</h2>
      <p class="notice error">
        Could not reach JobScraper – is <code>run.ps1 web</code> running? Start it, then try again.
      </p>
      <p><button type="button" class="primary boot-retry" :disabled="retrying" @click="boot">
        {{ retrying ? 'Trying…' : 'Retry' }}
      </button></p>
    </main>
    <main
      v-else-if="active"
      :id="`panel-${active.id}`"
      class="panel"
      :inert="helpOpen || undefined"
      role="tabpanel"
      :aria-labelledby="`tab-${active.id}`"
      tabindex="0"
    >
      <!-- Inbox and Applications keep their place (selection, scroll, filters)
           while another tab is open (Q-70 C4, G15). The names are the SFC file
           names; the async wrapper is matched by what it resolved to. Their
           onActivated hooks do the quiet refresh. -->
      <KeepAlive :include="['Inbox', 'Applications']">
        <component
          :is="active.view"
          :key="active.id"
          :run="run"
          :runs="runs"
          :jobs="jobs"
          :loading="loading"
          :error="error"
          :runs-error="runsError"
          @changed="onChanged"
          @select-run="selectRun"
        />
      </KeepAlive>
    </main>
    <ToastHost />
    <ShortcutsSheet :open="helpOpen" :go-keys="goKeys" @close="helpOpen = false" />
  </div>
</template>

<style scoped>
.masthead {
  position: sticky;
  top: 0;
  z-index: 10;
  background: color-mix(in srgb, var(--surface) 90%, transparent);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--border);
  box-shadow: var(--shadow-sm);
}
.masthead-inner {
  max-width: var(--page-w);
  margin: 0 auto;
  padding: 0 var(--gutter);
  display: flex;
  align-items: stretch;
  gap: var(--space-5);
  min-height: var(--header-h);
  position: relative;
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
.brand a { display: inline-flex; align-items: center; gap: var(--space-2); color: var(--text); text-decoration: none; }
.logo { width: 1.6rem; height: 1.6rem; flex: none; }
.logo rect { fill: var(--accent); }
.logo path { fill: none; stroke: var(--accent-text); stroke-width: 3; stroke-linecap: round; }
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
.tablist.more-right { mask-image: linear-gradient(to right, #000 calc(100% - 2rem), transparent); }
.tab {
  position: relative;
  gap: var(--space-2);
  min-height: var(--header-h);
  padding: 0 var(--space-3);
  border: none;
  border-radius: 0;
  background: none;
  box-shadow: none;
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
.tab.current { color: var(--text); font-weight: 650; }
/* Developer (Q-75 N19): last in the bar, set apart by a hairline and drawn smaller. */
.tab.quiet { margin-left: var(--space-2); padding-left: var(--space-4); font-size: var(--text-xs); }
.tab.quiet::before {
  content: '';
  position: absolute;
  left: 0;
  top: 25%;
  bottom: 25%;
  border-left: 1px solid var(--border-strong);
}
.tab.current::after { background: var(--accent); }
.tab:focus-visible { outline-offset: -4px; }
.badge-slot { display: inline-flex; }
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
  padding: var(--space-5) var(--gutter) calc(var(--space-7) + var(--space-6));
}
.panel:focus-visible { outline-offset: -2px; }
.boot-error .notice { margin: var(--space-3) 0; }
@media (max-width: 640px) {
  .masthead-inner { flex-direction: column; gap: 0; }
  .brand { min-height: 2.5rem; font-size: var(--text-md); }
  .tab { min-height: 2.75rem; }
  .tablist { margin: 0 calc(-1 * var(--space-3)); }
}
</style>
