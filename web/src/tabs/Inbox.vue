<script setup>
// The Inbox (M13-T2): new roles to triage, laid out the way LinkedIn and Indeed
// lay out a job search - a list on the left, the selected role in full on the
// right (one column with a Back button on a phone).
//
// The Inbox holds only roles you have not acted on. Save (status `to_apply`)
// and Mark applied (`applied`) move a role to the Applications tab at once,
// with a toast offering Undo and a link there. Not interested (M17) moves it
// to its own section at the bottom, kept on the server, so it does not come
// back as new after a restart. A second listing of a role already tracked -
// the same posting under another id - is left out (M17). Opening the
// posting on the company's site asks afterwards whether you applied, the way
// LinkedIn does, so the record is one click away.
import { computed, nextTick, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import {
  ApiError, applyStatus, describeError, enqueueMessage, removeFromApplyQueue, setApplicationStatus, startAutoApply, untrackApplication,
} from '../api.js'
import { dismiss, dismissedAt, isDismissed, migrateSessionDismissals, restore } from '../dismissed.js'
import { cleanLocation, exactTime, plural, safeUrl, shortDate } from '../format.js'
import { loadPosting, postingEntry } from '../postingCache.js'
import { tabEmits, tabProps } from '../shell.js'
import { showToast } from '../toast.js'
import { requestPicker, runLabel } from '../runs.js'
import { SHORTCUTS_EVENT } from '../shortcuts.js'
import CompanyMark from '../components/CompanyMark.vue'
import Icon from '../components/Icon.vue'
import JobDetail from '../components/JobDetail.vue'
import RunSelector from '../components/RunSelector.vue'
import SetupChecklist from '../components/SetupChecklist.vue'
import TabLoading from '../components/TabLoading.vue'

const props = defineProps(tabProps)
const emit = defineEmits(tabEmits)

const query = ref('')
const sort = ref('newest')
const selectedId = ref(null)
const detailOpen = ref(false)          // phone layout: the detail replaces the list
const pending = ref(new Set())         // just saved/applied: gone before the reload lands
const opened = ref(new Set())          // postings opened on the company site this session
const busy = ref(false)
const rootEl = ref(null)
const quiet = ref(false)             // our own reload after an action: keep the list at full strength
const writeError = ref('')

watch(() => props.loading, (now, was) => { if (was && !now) quiet.value = false })

const firstLoad = computed(() => props.loading && !props.jobs.length)
// For the empty state: 'any run yet', 'the past week', 'run 12'.
const scope = computed(() => (props.run === 'all' ? 'any run yet'
  : props.run === 'week' || props.run === 'month' ? `the ${runLabel(props.run).toLowerCase()}`
    : runLabel(props.run).toLowerCase()))

// Untracked roles: no application status yet. Tracked ones live in Applications.
// A job whose posting is already tracked under another id (`tracked_as`, the
// same URL) is not new either (M17).
const untracked = computed(() => props.jobs.filter(j => !j.status && !j.tracked_as && !pending.value.has(j.id)))
const tracked = computed(() => props.jobs.filter(j => j.status).length)
const twins = computed(() => props.jobs.filter(j => !j.status && j.tracked_as).length)
const notInterestedCount = computed(() => untracked.value.filter(isDismissed).length)

function matches(job, q) {
  if (!q) return true
  return [job.title, job.company, job.location].some(v => (v || '').toLowerCase().includes(q))
}

const SORTS = {
  newest: (a, b) => String(b.decided_at || '').localeCompare(String(a.decided_at || '')),
  company: (a, b) => String(a.company || '').localeCompare(String(b.company || ''), undefined, { sensitivity: 'base' }),
  // Your own list's order (M16): its companies first, most wanted first, the
  // rest after them, newest first within each.
  yours: (a, b) => (a.company_rank ?? Infinity) - (b.company_rank ?? Infinity) || SORTS.newest(a, b),
}
const ranked = computed(() => untracked.value.some(j => j.company_rank !== null && j.company_rank !== undefined))

const visible = computed(() => {
  const q = query.value.trim().toLowerCase()
  return untracked.value
    .filter(j => !isDismissed(j) && matches(j, q))
    .sort(SORTS[sort.value] ?? SORTS.newest)
})

// Not interested (M17): below the new roles, most recently dismissed first.
const notInterested = computed(() => {
  const q = query.value.trim().toLowerCase()
  return untracked.value
    .filter(j => isDismissed(j) && matches(j, q))
    .sort((a, b) => String(dismissedAt(b)).localeCompare(String(dismissedAt(a))))
})

// The section's open/closed state is remembered on this device.
const NI_KEY = 'jobscraper.inbox.notInterestedOpen'
function readNiOpen() {
  try { return window.localStorage.getItem(NI_KEY) === '1' } catch { return false }
}
const niOpen = ref(readNiOpen())
watch(niOpen, open => {
  try { window.localStorage.setItem(NI_KEY, open ? '1' : '0') } catch { /* blocked */ }
})

const groups = computed(() => {
  const out = [{ id: 'new', label: 'New roles', jobs: visible.value, open: true }]
  if (notInterested.value.length) {
    out.push({ id: 'ni', label: 'Not interested', jobs: notInterested.value, open: niOpen.value })
  }
  return out
})
// Every card on screen, in order: the keyboard and "the next role" walk this.
const listed = computed(() => groups.value.filter(g => g.open).flatMap(g => g.jobs))

const companies = computed(() => new Set(visible.value.map(j => j.company)).size)
const selected = computed(() => listed.value.find(j => j.id === selectedId.value) ?? listed.value[0] ?? null)

function shortYears(job) {
  if (job.yoe_min === null || job.yoe_min === undefined) return null
  return job.yoe_min === 0 ? 'Entry level' : `${job.yoe_min}+ yrs`
}

function cardMeta(job) {
  return [cleanLocation(job.location), shortYears(job)].filter(Boolean).join(' · ')
}

// ---- the job description (M16): fetched when a role is opened, kept per role ----
// JobDetail shows it; the Inbox starts the fetch as soon as a role is selected
// (postingCache is shared with the Applications tab).
watch(() => selected.value?.id, id => {
  if (id && !postingEntry(id)) loadPosting(id)
}, { immediate: true })

// ---- selection and the keyboard ----

const itemEls = {}

// One column on a phone or a narrow window (matchMedia is absent in the test DOM).
const narrow = () => Boolean(window.matchMedia?.('(max-width: 900px)')?.matches)

async function select(job, { open = true } = {}) {
  selectedId.value = job.id
  if (!open) return
  detailOpen.value = true
  if (narrow()) {
    await nextTick()
    window.scrollTo?.(0, 0)
    document.getElementById('detail-title')?.focus()
  }
}

// After an action the selected role changes under the user's finger; put focus
// on the new one (its card, or the detail title when the detail replaces the
// list) so a keyboard user never falls to <body> (UX audit G1).
function hasFocus() {
  const el = document.activeElement
  return el === document.body || Boolean(rootEl.value?.contains(el)) || Boolean(el?.closest?.('.toast'))
}

async function refocus() {
  await nextTick()
  const id = selected.value?.id
  if (!id) return
  if (detailOpen.value && narrow()) document.getElementById('detail-title')?.focus()
  else itemEls[id]?.focus()
}

// A second press inside 400 ms, or while a write is in flight, is dropped (G21).
let lastActionAt = 0
function guard() {
  const t = Date.now()
  if (busy.value || t - lastActionAt < 400) return false
  lastActionAt = t
  return true
}

// The role to show once `job` leaves the list: the next one, else the previous.
function neighbour(job) {
  const list = isDismissed(job) ? notInterested.value : visible.value
  const i = list.findIndex(j => j.id === job.id)
  return (list[i + 1] ?? list[i - 1] ?? null)?.id ?? null
}

async function onListKey(event) {
  const step = { ArrowDown: 1, j: 1, ArrowUp: -1, k: -1 }[event.key]
  const edge = event.key === 'Home' || event.key === 'End'
  if ((!step && !edge) || !listed.value.length) return
  event.preventDefault()
  const list = listed.value
  const i = Math.max(0, list.findIndex(j => j.id === selected.value?.id))
  const next = edge ? list[event.key === 'Home' ? 0 : list.length - 1]
    : list[Math.min(list.length - 1, Math.max(0, i + step))]
  select(next, { open: false })
  await nextTick()
  itemEls[next.id]?.focus()
}

// ---- actions ----

function unpend(id) {
  const next = new Set(pending.value)
  next.delete(id)
  pending.value = next
}

// The last Save, Applied or Not interested can be taken back with Z for a minute
// (G3r), the same Undo the toast offers; whichever is used first spends it.
const UNDO_WINDOW_MS = 60000
let lastUndo = null
function rememberUndo(run) { lastUndo = { run, at: Date.now() } }
function spendUndo(run) { lastUndo = null; return run() }
function undoLast() {
  const u = lastUndo
  lastUndo = null
  if (!u || Date.now() - u.at > UNDO_WINDOW_MS) return
  return u.run()
}

const VERB = { applied: 'Marked applied', to_apply: 'Saved' }

async function track(job, status) {
  if (!guard()) return
  const hadFocus = hasFocus()
  writeError.value = ''
  busy.value = true
  const next = neighbour(job)
  pending.value = new Set(pending.value).add(job.id)
  selectedId.value = next
  try {
    await setApplicationStatus(job.id, status, { company: job.company, role: job.title, url: job.url })
    quiet.value = true
    emit('changed')
    rememberUndo(() => undo(job))
    showToast({
      message: `${VERB[status]}: ${job.title} at ${job.company}`,
      action: { label: 'Undo', run: () => spendUndo(() => undo(job)) },
      link: { label: 'View in Applications', href: '#/applications' },
    })
  } catch (e) {
    unpend(job.id)
    selectedId.value = job.id
    writeError.value = `Could not update ${job.company} · ${job.title}: ${describeError(e)}`
  } finally {
    busy.value = false
  }
  if (hadFocus) refocus()
}

async function undo(job) {
  if (busy.value) return               // Undo is not held back by the 400 ms cooldown
  const hadFocus = hasFocus()
  try {
    await untrackApplication(job.id)
  } catch (e) {
    if (e?.status !== 404) {
      writeError.value = `Could not undo ${job.company} · ${job.title}: ${describeError(e)}`
      if (hadFocus) refocus()
      return
    }
  }
  unpend(job.id)
  selectedId.value = job.id
  quiet.value = true
  emit('changed')
  if (hadFocus) refocus()
}

async function markNotInterested(job) {
  if (!guard()) return
  const hadFocus = hasFocus()
  writeError.value = ''
  busy.value = true
  try {
    selectedId.value = neighbour(job)
    try {
      await dismiss(job)
    } catch (e) {
      selectedId.value = job.id
      writeError.value = `Could not mark ${job.company} · ${job.title} as not interested: ${describeError(e)}`
      return
    }
    // A role this page put in the auto-apply queue must not stay there (Q-120).
    await leaveQueue(job).catch(e => {
      writeError.value = `${job.company} · ${job.title} may still be in the auto-apply queue: ${describeError(e)}`
    })
    showToast({
      message: `Moved to Not interested: ${job.title} at ${job.company}`,
      action: { label: 'Undo', run: () => spendUndo(() => moveBack(job, { undoing: true })) },
    })
    rememberUndo(() => moveBack(job, { undoing: true }))
  } finally {
    busy.value = false
    if (hadFocus) refocus()
  }
}

// `undoing`: the toast's Undo for a dismissal - only a write in flight stops it.
async function moveBack(job, { undoing = false } = {}) {
  if (undoing ? busy.value : !guard()) return
  const hadFocus = hasFocus()
  writeError.value = ''
  busy.value = true
  try {
    await restore(job)
    selectedId.value = job.id
  } catch (e) {
    writeError.value = `Could not move ${job.company} · ${job.title} back: ${describeError(e)}`
  } finally {
    busy.value = false
    if (hadFocus) refocus()
  }
}

// Roles dismissed before M17 were kept in this tab only; store them now.
migrateSessionDismissals().then(n => { if (n) emit('changed') })

// "Choose runs…": the picker is the Runs tab's run history (M15).
function chooseRuns() {
  requestPicker()
  window.location.hash = '#/runs'
}

// ---- Auto-apply (Q-110, F-30, D-200, D-203; the queue, Q-120, D-205) ----
// D-203: the click is the consent. In auto mode the worker fills the form and submits
// it, with no confirm dialog in any mode; dry_run only fills and never submits.
// D-205: the click ADDS the role to the auto-apply queue and the server's worker applies
// in the background, so the owner keeps adding roles. Nothing here waits for a running
// job: the button is off only when the profile is incomplete or the status is unknown.
// `applyState` is GET /api/apply/status ({mode, missing, busy, queue}); null until it
// loads or when it cannot, which keeps the button off rather than guessing. Its `busy`
// is deliberately not read.
const applyState = ref(null)
const applying = ref(new Set())        // role ids whose enqueue request is in flight (per role, no global lock)
const queuedIds = new Set()            // roles this page put in the queue (for Not interested)
const applyReady = computed(() => Boolean(applyState.value) && applyState.value.missing.length === 0)

const APPLY_HINTS = {
  auto: 'Adds this role to the auto-apply queue. JobScraper fills the form and submits it.',
  dry_run: 'Adds this role to the auto-apply queue. Dry run: the form is filled, never submitted.',
}
const applyHint = computed(() => APPLY_HINTS[applyState.value?.mode] ?? APPLY_HINTS.dry_run)
const applyOff = job => !applyReady.value || busy.value || applying.value.has(job.id)

async function loadApplyStatus() {
  try {
    const s = await applyStatus()
    applyState.value = s && Array.isArray(s.missing) ? s : null
  } catch {
    applyState.value = null
  }
}
onMounted(loadApplyStatus)

// The Applications tab and Runs listen for this and refresh their queue views.
const announceQueue = () => window.dispatchEvent(new Event('jobscraper:apply-queue'))

// What a 422 means, in the owner's words: the refusals' own sentences, or the profile.
function refusalText(body) {
  if (body?.detail === 'profile_incomplete') return 'Finish your application details first.'
  const refused = Array.isArray(body?.refused) ? body.refused : []
  const texts = refused.map(r => [r.text, r.hint].filter(Boolean).join(' '))
  return texts.length ? texts.join(' ') : 'Could not add this role to the auto-apply queue.'
}

function setApplying(id, on) {
  const next = new Set(applying.value)
  if (on) next.add(id)
  else next.delete(id)
  applying.value = next
}

// The role goes back into the list: the enqueue failed or was taken back.
function putBack(job) {
  unpend(job.id)
  selectedId.value = job.id
}

async function autoApply(job) {
  if (applyOff(job)) return
  const hadFocus = hasFocus()
  setApplying(job.id, true)
  // On success the server tracks the role as To apply, so it leaves the list at the
  // click (the same local removal Save uses); it comes back if the request fails.
  const next = neighbour(job)
  pending.value = new Set(pending.value).add(job.id)
  selectedId.value = next
  try {
    const r = await startAutoApply([job.id])
    const refused = Array.isArray(r?.refused) ? r.refused.map(x => x.text).filter(Boolean) : []
    const mine = Array.isArray(r?.queued) ? r.queued.filter(q => String(q.job_id) === String(job.id)) : []
    if (mine.length) {
      queuedIds.add(job.id)
      rememberUndo(() => undoQueued(job))
      showToast({
        message: [enqueueMessage({ ...r, queued: mine }), ...refused].join(' '),
        action: { label: 'Undo', run: () => spendUndo(() => undoQueued(job)) },
        link: { label: 'See the queue', href: '#/runs' },
      })
    } else {
      putBack(job)        // refused (a twin, the daily cap, ...): it stays where it was
      showToast({ message: refused.length ? refused.join(' ') : refusalText(r) })
    }
    quiet.value = true
    emit('changed')
    announceQueue()
  } catch (e) {
    putBack(job)
    if (e instanceof ApiError && e.status === 422) {
      showToast({ message: refusalText(e.body) })
    } else {
      showToast({ message: `Could not add this role to the auto-apply queue: ${describeError(e)}` })
    }
  } finally {
    setApplying(job.id, false)
    loadApplyStatus()
  }
  if (hadFocus) refocus()
}

// Take a role this page queued out of the queue. 404 `not_waiting` is fine: it has
// started or is gone, and there is nothing to remove.
async function leaveQueue(job) {
  if (!queuedIds.has(job.id)) return
  try {
    await removeFromApplyQueue(job.id)
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 404)) throw e
  }
  queuedIds.delete(job.id)
  announceQueue()
}

// Undo for an enqueue: out of the queue, then untracked, so the role is back as new.
// Once the worker has started it, it cannot be taken back here (the queue answers 404
// not_waiting, an untrack 409 in_progress): Runs has Stop.
async function undoQueued(job) {
  const started = () => showToast({ message: 'It has already started; stop it in Runs.' })
  const hadFocus = hasFocus()
  try {
    await removeFromApplyQueue(job.id)
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) { started(); return }
    writeError.value = `Could not undo ${job.company} · ${job.title}: ${describeError(e)}`
    return
  }
  queuedIds.delete(job.id)
  try {
    await untrackApplication(job.id)
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) { announceQueue(); started(); return }
    if (!(e instanceof ApiError && e.status === 404)) {
      writeError.value = `Could not undo ${job.company} · ${job.title}: ${describeError(e)}`
      announceQueue()
      return
    }
  }
  putBack(job)
  quiet.value = true
  emit('changed')
  announceQueue()
  if (hadFocus) refocus()
}

function markOpened(job) {
  opened.value = new Set(opened.value).add(job.id)
}

// ---- triage shortcuts (UX-1), the way Gmail's and LinkedIn's lists work ----
// Never while typing in a field, never with a modifier (Ctrl+S stays the
// browser's), and never twice: the list's own J/K handling marks its event.
// They can be turned off (WCAG 2.1.4 - single-key shortcuts misfire under
// speech input); the choice is remembered on this device. The `/` search key
// is the shell's own and is not affected.

const SHORTCUTS_KEY = 'jobscraper.inbox.shortcuts'
function readShortcuts() {
  try { return window.localStorage.getItem(SHORTCUTS_KEY) !== '0' } catch { return true }
}
const shortcutsOn = ref(readShortcuts())
watch(shortcutsOn, on => {
  try { window.localStorage.setItem(SHORTCUTS_KEY, on ? '1' : '0') } catch { /* blocked */ }
})
const keyOf = key => (shortcutsOn.value ? key : undefined)

function typing(target) {
  return Boolean(target?.closest?.('input, textarea, select, [contenteditable="true"]'))
}

function openPosting(job) {
  const url = safeUrl(job.url)
  if (!url) return
  window.open(url, '_blank', 'noopener,noreferrer')
  markOpened(job)
}

async function step(by) {
  const list = listed.value
  if (!list.length) return
  const i = Math.max(0, list.findIndex(j => j.id === selected.value?.id))
  const next = list[Math.min(list.length - 1, Math.max(0, i + by))]
  select(next, { open: false })
  await nextTick()
  itemEls[next.id]?.scrollIntoView?.({ block: 'nearest' })
}

function onShortcut(event) {
  if (!shortcutsOn.value || event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || typing(event.target)) return
  if (String(event.key).toLowerCase() === 'z') {
    if (!lastUndo || busy.value) return
    event.preventDefault()
    undoLast()
    return
  }
  const job = selected.value
  const act = {
    s: () => track(job, 'to_apply'),
    a: () => track(job, 'applied'),
    x: () => (isDismissed(job) ? moveBack(job) : markNotInterested(job)),
    o: () => openPosting(job),
    j: () => step(1),
    k: () => step(-1),
  }[String(event.key).toLowerCase()]
  if (!act || !job || busy.value) return
  event.preventDefault()
  act()
}

// The "?" sheet's switch reaches an open Inbox through this event.
function onShortcutsSwitch(event) { shortcutsOn.value = Boolean(event.detail?.on) }

onMounted(() => {
  window.addEventListener('keydown', onShortcut)
  window.addEventListener(SHORTCUTS_EVENT, onShortcutsSwitch)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onShortcut)
  window.removeEventListener(SHORTCUTS_EVENT, onShortcutsSwitch)
})
// A kept-alive Inbox must not keep its keys while another tab is showing
// (duplicate adds of the same listener are dropped by the browser).
onActivated(() => window.addEventListener('keydown', onShortcut))
onDeactivated(() => window.removeEventListener('keydown', onShortcut))
</script>

<template>
  <section ref="rootEl" class="inbox" :aria-busy="loading ? 'true' : 'false'">
    <header class="page-head">
      <div>
        <h2 class="page-title">Inbox</h2>
        <p v-if="!firstLoad && !error" class="page-sub count">
          {{ plural(visible.length, 'new role') }} at {{ plural(companies, 'company', 'companies') }}
          <template v-if="notInterestedCount">
            · <span class="ni-count">{{ notInterestedCount }} not interested</span>
          </template>
          <template v-if="tracked">
            · <a class="tracked" href="#/applications">{{ tracked }} already tracked</a>
          </template>
          <template v-if="twins">
            · <span class="twins" title="The same posting is listed under another company or id, and you already track it in Applications">{{ plural(twins, 'duplicate') }} of tracked roles hidden</span>
          </template>
        </p>
      </div>
      <div class="page-controls">
        <label class="search">
          <Icon name="search" />
          <span class="visually-hidden">Search roles</span>
          <input
            v-model="query"
            type="search"
            placeholder="Search title, company, location"
            aria-keyshortcuts="/"
            @keydown.esc="query ? (query = '') : $event.target.blur()"
          >
          <kbd class="key-hint" aria-hidden="true">/</kbd>
        </label>
        <label class="sort">
          <span class="visually-hidden">Sort</span>
          <select v-model="sort">
            <option value="newest">Newest first</option>
            <option value="company">Company A–Z</option>
            <option v-if="ranked" value="yours">Your company order</option>
          </select>
        </label>
        <RunSelector
          :runs="runs"
          :model-value="run"
          @update:model-value="v => emit('select-run', v)"
          @choose="chooseRuns"
        />
      </div>
    </header>

    <div v-if="writeError" class="notice error write-error" role="alert">
      <p>{{ writeError }}</p>
      <button type="button" class="ghost write-error-close" aria-label="Dismiss this error" @click="writeError = ''">Dismiss</button>
    </div>

    <div v-if="error" class="notice error" role="alert">
      <p>{{ jobs.length ? 'Could not refresh the shortlist: ' + error + '. Showing the last list loaded.' : 'Could not load the shortlist: ' + error }}</p>
      <button type="button" @click="emit('changed')">Try again</button>
    </div>
    <TabLoading v-if="firstLoad" :rows="3" />
    <SetupChecklist v-else-if="!jobs.length && !error" :runs="runs">
      <div class="empty">
        <Icon name="inbox" :size="28" />
        <p class="empty-title">No roles in {{ scope }}.</p>
        <p class="muted">Show other runs above, or start a new one from the <a href="#/runs">Runs tab</a>.</p>
      </div>
    </SetupChecklist>
    <div v-else-if="!error && !visible.length && !query.trim()" class="empty caught-up">
      <Icon name="check" :size="28" />
      <p class="empty-title">You're all caught up.</p>
      <p class="muted">Every new role is triaged.<template v-if="notInterested.length"> <button type="button" class="link show-ni" @click="niOpen = true">Show Not interested ({{ notInterested.length }})</button></template><template v-else> See <a href="#/applications">Applications</a>.</template></p>
    </div>
    <div v-else-if="!visible.length && query.trim() && !(notInterested.length && niOpen)" class="empty">
      <Icon name="search" :size="28" />
      <p class="empty-title">No roles match “{{ query.trim() }}”.</p>
      <p>
        <button type="button" class="link" @click="query = ''">Clear the search</button>
        <template v-if="notInterested.length">
          · <button type="button" class="link show-ni" @click="niOpen = true">Show {{ notInterested.length }} in Not interested</button>
        </template>
      </p>
    </div>

    <div v-if="untracked.length && (visible.length || (notInterested.length && niOpen))" class="split" :class="{ 'show-detail': detailOpen, refreshing: loading && !quiet }">
      <div class="job-list surface" @keydown="onListKey">
       <template v-for="group in groups" :key="group.id">
        <button
          v-if="group.id === 'ni'"
          type="button"
          class="ni-head"
          :aria-expanded="niOpen ? 'true' : 'false'"
          @click="niOpen = !niOpen"
        >
          <Icon name="chevron" /> Not interested <span class="ni-num">{{ group.jobs.length }}</span>
        </button>
        <ul v-if="group.open" class="cards" :class="group.id" :aria-label="group.label">
        <li v-if="group.id === 'new' && !group.jobs.length" class="list-note muted">
          No new roles{{ query.trim() ? ' match' : '' }} - everything left is marked Not interested.
        </li>
        <li
          v-for="job in group.jobs"
          :key="job.id"
          class="card"
          :class="{ selected: selected && job.id === selected.id, closed: job.closed }"
          :data-job="job.id"
        >
          <button
            :ref="el => { itemEls[job.id] = el }"
            type="button"
            class="card-hit"
            :aria-current="selected && job.id === selected.id ? 'true' : undefined"
            :tabindex="selected && job.id === selected.id ? 0 : -1"
            @click="select(job)"
          >
            <CompanyMark :name="job.company" />
            <span class="card-body">
              <span class="title">{{ job.title }}</span>
              <span class="company">{{ job.company }}</span>
              <span class="meta">{{ cardMeta(job) }}</span>
            </span>
            <span class="card-side">
              <span v-if="job.closed" class="pill stale" data-status="closed">closed</span>
              <span class="seen" :title="exactTime(job.decided_at)">{{ shortDate(job.decided_at) }}</span>
            </span>
          </button>
        </li>
        </ul>
       </template>
      </div>

      <article v-if="selected" :key="selected.id" class="detail surface" aria-labelledby="detail-title" :data-job="selected.id">
        <button type="button" class="ghost back" @click="detailOpen = false; nextTick(() => itemEls[selected?.id]?.focus())">
          <Icon name="back" /> All roles
        </button>

        <JobDetail :job="selected">
          <template #actions>
            <div class="action-bar">
            <div class="actions">
              <button
                type="button"
                class="button primary auto-apply"
                :disabled="applyOff(selected)"
                :title="applyHint"
                @click="autoApply(selected)"
              >
                <Icon name="briefcase" /> Auto-apply
              </button>
              <a
                v-if="safeUrl(selected.url)"
                class="button open"
                :href="safeUrl(selected.url)"
                target="_blank"
                rel="noopener noreferrer"
                :aria-keyshortcuts="keyOf('O')"
                @click="markOpened(selected)"
              >Apply on company site <Icon name="external" /><span class="visually-hidden"> (opens {{ selected.company }} in a new tab)</span></a>
              <button type="button" class="apply" :disabled="busy" :aria-keyshortcuts="keyOf('A')" @click="track(selected, 'applied')">
                <Icon name="check" /> Mark applied
              </button>
              <button type="button" class="save" :disabled="busy" :aria-keyshortcuts="keyOf('S')" @click="track(selected, 'to_apply')">
                <Icon name="bookmark" /> Save
              </button>
              <button v-if="isDismissed(selected)" type="button" class="ghost undismiss" :disabled="busy" :aria-keyshortcuts="keyOf('X')" @click="moveBack(selected)">
                <Icon name="undo" /> Move back to new roles
              </button>
              <button v-else type="button" class="ghost dismiss" :disabled="busy" :aria-keyshortcuts="keyOf('X')" @click="markNotInterested(selected)">
                <Icon name="x" /> Not interested
              </button>
            </div>
            <p v-if="applyState" class="auto-apply-note muted small">
              <template v-if="applyState.missing.length">
                <a class="auto-apply-profile" href="#/profile">Finish your application details first</a>
                ({{ applyState.missing.length }} missing).
              </template>
              <template v-else>{{ applyHint }}</template>
            </p>
            <p class="shortcuts muted">
              <template v-if="shortcutsOn">
                Keys: <kbd>S</kbd> save · <kbd>A</kbd> applied · <kbd>X</kbd> not interested · <kbd>O</kbd> open ·
                <kbd>J</kbd> <kbd>K</kbd> next, previous · <kbd>Z</kbd> undo · <kbd>?</kbd> all keys ·
              </template>
              <button
                type="button"
                class="link shortcuts-toggle"
                :aria-label="shortcutsOn ? 'Turn off keyboard shortcuts' : undefined"
                @click="shortcutsOn = !shortcutsOn"
              >
                {{ shortcutsOn ? 'Turn off' : 'Turn on keyboard shortcuts' }}
              </button>
            </p>
            </div>
            <p v-if="isDismissed(selected)" class="muted small ni-note">
              You marked this Not interested{{ dismissedAt(selected) ? ` on ${shortDate(dismissedAt(selected))}` : '' }}.
            </p>

            <div v-if="opened.has(selected.id)" class="did-apply" role="status">
              <span>Did you apply at {{ selected.company }}?</span>
              <button type="button" class="primary did-apply-yes" :disabled="busy" @click="track(selected, 'applied')">Yes, mark applied</button>
            </div>
          </template>
        </JobDetail>
      </article>
    </div>
  </section>
</template>

<style scoped>
.page-controls .search { width: 17rem; max-width: 100%; }
.tracked { font-weight: 500; }

/* List and detail side by side; the detail stays in view while the list scrolls. */
.split {
  display: grid;
  grid-template-columns: minmax(18rem, 25rem) minmax(0, 1fr);
  gap: var(--space-4);
  align-items: start;
  transition: opacity 0.15s;
}
.split.refreshing { opacity: 0.6; }

.job-list {
  list-style: none;
  margin: 0;
  padding: var(--space-1);
  max-height: calc(100vh - var(--header-h) - 9rem);
  overflow-y: auto;
  overscroll-behavior: contain;
}
.cards { list-style: none; margin: 0; padding: 0; }
.card + .card { border-top: 1px solid var(--border); }
.list-note { padding: var(--space-3); font-size: var(--text-sm); }

/* Not interested (M17): its own section under the new roles, quieter. */
.ni-head {
  display: flex; align-items: center; gap: var(--space-2); width: 100%;
  margin-top: var(--space-2); padding: var(--space-3) var(--space-3) var(--space-2);
  background: transparent; border: 0; border-top: 1px solid var(--border-strong);
  border-radius: 0; box-shadow: none; justify-content: flex-start;
  font-size: var(--text-xs); font-weight: 650; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--muted);
}
.ni-head:hover:not(:disabled) { background: transparent; color: var(--text-2); }
.ni-head .icon { transition: transform 0.15s; }
.ni-head[aria-expanded='false'] .icon { transform: rotate(-90deg); }
.ni-num { font-family: var(--mono); font-weight: 500; }
.cards.ni .mark { opacity: 0.65; }
.cards.ni .card .title { color: var(--text-2); font-weight: 500; }
.ni-note { margin: var(--space-2) 0 0; }
.twins { color: var(--muted); }
.card-hit {
  display: flex;
  align-items: flex-start;
  gap: var(--space-3);
  width: 100%;
  min-height: 0;
  padding: var(--space-3);
  text-align: left;
  white-space: normal;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius);
  box-shadow: none;
  font-weight: 400;
}
.card-hit:hover:not(:disabled) { background: var(--surface-2); }
.card.selected .card-hit {
  background: var(--accent-soft);
  border-color: transparent;
  box-shadow: inset 3px 0 0 var(--accent);
}
.card-body { display: flex; flex-direction: column; min-width: 0; flex: 1; }
.card .title { font-weight: 650; font-size: var(--text-sm); color: var(--text); line-height: 1.35; }
.card .company { font-size: var(--text-sm); color: var(--text-2); margin-top: 2px; }
.card .meta { font-size: var(--text-xs); color: var(--muted); margin-top: 2px; }
.card-side { display: flex; flex-direction: column; align-items: flex-end; gap: var(--space-1); flex: none; }
.seen { font-family: var(--mono); font-size: var(--text-xs); color: var(--muted); white-space: nowrap; }
.card.closed .title { color: var(--text-2); }

.detail {
  position: sticky;
  top: calc(var(--header-h) + var(--space-4));
  padding: var(--space-5);
  /* A long posting scrolls inside the detail, not past the screen, so the
     actions below stay in reach (G17). */
  max-height: calc(100vh - var(--header-h) - var(--space-4) * 2);
  max-height: calc(100dvh - var(--header-h) - var(--space-4) * 2);
  overflow-y: auto;
  overscroll-behavior: contain;
  scroll-padding-top: 5rem; /* a focused control is not left under the pinned action bar */
}
.back { display: none; margin: calc(-1 * var(--space-2)) 0 var(--space-3) calc(-1 * var(--space-2)); }
.actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--space-2);
}
/* The actions and their key hints, with the rule below both. */
.action-bar {
  margin-top: var(--space-5);
  padding-bottom: var(--space-5);
  border-bottom: 1px solid var(--border);
}
/* In the detail's own scroll box the bar pins to the top edge, as wide as the
   box so the text scrolling under it is hidden behind it, not beside it (G17). */
.detail .action-bar {
  position: sticky;
  top: calc(-1 * var(--space-5)); /* the detail's own padding sits above the content box */
  z-index: 1;
  margin: 0 calc(-1 * var(--space-5));
  padding: var(--space-5) var(--space-5) var(--space-3);
  background: var(--surface);
}
/* Dismissable write error (N20): the message wraps, the button stays in reach. */
.write-error { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--space-3); }
.write-error p { min-width: 0; overflow-wrap: anywhere; }
.write-error-close { flex: none; min-height: 1.75rem; padding-block: 0.1rem; color: inherit; }
.did-apply {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-2) var(--space-3);
  margin-top: var(--space-4);
  padding: var(--space-3) var(--space-4);
  background: var(--accent-soft);
  border-radius: var(--radius);
  font-size: var(--text-sm);
  font-weight: 500;
}

/* Keyboard hints: for a keyboard, not a touch screen. */
.auto-apply-note { margin: var(--space-2) 0 0; }
.shortcuts { margin: var(--space-2) 0 0; font-size: var(--text-xs); }
.shortcuts kbd {
  display: inline-block; min-width: 1.4em; padding: 0 0.3em; text-align: center;
  font-family: var(--mono); font-size: 0.7rem; line-height: 1.5;
  color: var(--text-2); background: var(--surface-2);
  border: 1px solid var(--border-strong); border-bottom-width: 2px; border-radius: 4px;
}
.shortcuts-toggle { font-size: inherit; color: var(--muted); }
.shortcuts-toggle:hover:not(:disabled) { color: var(--accent); }
@media (hover: none) { .shortcuts { display: none; } }

.empty .icon { display: block; margin: 0 auto var(--space-2); }

/* The dismiss button keeps a 44px target on a phone (Q-78 G31). */
@media (max-width: 640px) {
  .write-error-close { min-height: var(--control-h); }
}
/* A phone or a narrow window: one column. The list, or the role - not both. */
@media (max-width: 900px) {
  .split { grid-template-columns: minmax(0, 1fr); }
  .job-list { max-height: none; }
  .detail { position: static; display: none; max-height: none; overflow: visible; }
  .detail .action-bar { position: static; margin-inline: 0; padding: 0 0 var(--space-5); margin-top: var(--space-5); background: none; }
  /* Nothing is chosen on a phone's list until a role is opened (G38). */
  .split:not(.show-detail) .card.selected .card-hit { background: transparent; box-shadow: none; }
  .split:not(.show-detail) .card.selected .card-hit:hover:not(:disabled) { background: var(--surface-2); }
  .split.show-detail .job-list { display: none; }
  .split.show-detail .detail { display: block; }
  .back { display: inline-flex; }
  .page-controls .search { width: 100%; }
  .page-controls { width: 100%; }
}
</style>
