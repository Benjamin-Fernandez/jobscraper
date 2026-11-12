<script setup>
// One application on the Applications tab (Q-118 design section 3, D-207): a single
// line of grip · title block · `.app-state` · age · status pill ("Move to…") · "⋯".
// The row only shows and reports; the tab owns every write (status, note, remove),
// the toast with Undo and the live-region announcement.
//
//   <ApplicationRow :row="row" :show-company="sort === 'recent'" :saving="saving === row.job_id"
//     :details-open="openId === row.job_id" @move="s => change(row, s)" @remove="askRemove(row)"
//     @note="editNote(row)" @details="toggleDetail(row)" @drag-start="onDragStart" @drag-end="onDragEnd">
//     ...note form, history and the detail panel, under the row...
//   </ApplicationRow>
//
// Drag (pointer, wider than a phone): the whole row drags, the grip is the cue. A row
// JobScraper is applying to, or that waits in the queue (`inFlight`), is not draggable
// and its Move menu is off with the reason; touch and keyboard always use Move to.
//
// The `.app-state` slot (Q-120 U3) says what is happening to the role: Queued · 3rd,
// Applying…, Applied automatically, Needs your answers, Stopped: <reason>. "Try again"
// adds a stopped, cancelled or waiting-for-answers role to the auto-apply queue again
// (the same call and toast as the Inbox) and announces `jobscraper:apply-queue`; the
// tab reloads its rows on that event.
import { computed, ref, watch } from 'vue'
import { ApiError, describeError, enqueueMessage, removeFromApplyQueue, startAutoApply } from '../api.js'
import { IN_PROGRESS_REMOVE, canRetry, refusalMessage, rowState } from '../attempts.js'
import { LOCKED_REASON, ageLabel, inFlight, lastAt, needsFollowUp, secondLine } from '../applications.js'
import { exactTime, safeUrl } from '../format.js'
import { openProfile } from '../profileView.js'
import { showToast } from '../toast.js'
import MenuButton from '../ui/MenuButton.vue'
import MoveMenu from '../ui/MoveMenu.vue'
import CompanyMark from './CompanyMark.vue'
import Icon from './Icon.vue'

const props = defineProps({
  row: { type: Object, required: true },
  // Recent sort: the company leads the row (mark + name), as there is no group header.
  showCompany: { type: Boolean, default: false },
  // A status write for this row is in flight.
  saving: { type: Boolean, default: false },
  detailsOpen: { type: Boolean, default: false },
  // False on a phone or a touch screen: there the Move menu is the only way.
  dragEnabled: { type: Boolean, default: true },
  // This row is being dragged (dims it).
  dragging: { type: Boolean, default: false },
})
const emit = defineEmits(['move', 'remove', 'note', 'details', 'drag-start', 'drag-end'])

const company = computed(() => props.row.company || 'Unknown company')
const role = computed(() => props.row.role ?? props.row.job_id)
const name = computed(() => `${role.value} at ${company.value}`)
const url = computed(() => safeUrl(props.row.url))
const locked = computed(() => inFlight(props.row) || justQueued.value > 0)
const canDrag = computed(() => props.dragEnabled && !locked.value && !props.saving)
const removable = computed(() => (props.row.events?.length ?? 0) <= 1)
const meta = computed(() => [props.showCompany ? company.value : '', secondLine(props.row)].filter(Boolean).join(' · '))

// ---- the state chip and "Try again" (Q-120 U3) ----

// After a successful "Try again": the place in line, shown at once until the tab's next
// load brings the real row (any change of the attempt or the queue place clears it).
const justQueued = ref(0)
const rowKey = computed(() => `${props.row.last_attempt?.id ?? ''}|${props.row.last_attempt?.kind ?? ''}|${props.row.queue?.position ?? ''}`)
watch(rowKey, () => { justQueued.value = 0 })

const shown = computed(() => (justQueued.value > 0 ? { ...props.row, queue: { position: justQueued.value } } : props.row))
const state = computed(() => rowState(shown.value))
const stoppedLike = computed(() => state.value?.kind === 'stopped' || state.value?.kind === 'cancelled')
const retryable = computed(() => canRetry(shown.value))
const retrying = ref(false)

const announceQueue = () => window.dispatchEvent(new Event('jobscraper:apply-queue'))

async function tryAgain() {
  if (retrying.value) return
  retrying.value = true
  const id = props.row.job_id
  try {
    const r = await startAutoApply([id])
    const refused = Array.isArray(r?.refused) ? r.refused.map(x => x.text).filter(Boolean) : []
    const mine = Array.isArray(r?.queued) ? r.queued.filter(q => String(q.job_id) === String(id)) : []
    if (mine.length) {
      justQueued.value = Number(mine[0].position) > 0 ? Number(mine[0].position) : 1
      showToast({
        message: [enqueueMessage({ ...r, queued: mine }), ...refused].join(' '),
        action: { label: 'Undo', run: undoTryAgain },
        link: { label: 'See the queue', href: '#/runs' },
      })
    } else {
      showToast({ message: refused.length ? refused.join(' ') : refusalMessage(r) })
    }
    announceQueue()
  } catch (e) {
    if (e instanceof ApiError && e.status === 422) showToast({ message: refusalMessage(e.body) })
    else showToast({ message: `Could not add this role to the auto-apply queue: ${describeError(e)}` })
  } finally {
    retrying.value = false
  }
}

// Take the role out of the queue again; once it has started that is Runs' Stop.
async function undoTryAgain() {
  try {
    await removeFromApplyQueue(props.row.job_id)
    justQueued.value = 0
    announceQueue()
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) showToast({ message: 'It has already started; stop it in Runs.' })
    else showToast({ message: `Could not take ${role.value} out of the queue: ${describeError(e)}` })
  }
}

const moreItems = computed(() => [
  { id: 'note', label: props.row.notes ? 'Edit note' : 'Add note' },
  { id: 'details', label: props.detailsOpen ? 'Hide details' : 'Show details' },
  ...(url.value ? [{ id: 'open', label: 'Open the posting' }] : []),
  ...(removable.value ? [{ id: 'remove', label: 'Remove from Applications', danger: true }] : []),
])

function onMore(id) {
  if (id === 'note') emit('note')
  else if (id === 'details') emit('details')
  else if (id === 'remove') {
    // Being applied to right now: the server refuses (409 in_progress) and keeps the row,
    // so say why here instead of asking first.
    if (props.row.last_attempt?.kind === 'running') showToast({ message: IN_PROGRESS_REMOVE })
    else emit('remove')
  }
  else if (id === 'open' && url.value) window.open(url.value, '_blank', 'noopener,noreferrer')
}

const moveRef = ref(null)
const moreRef = ref(null)
const rootRef = ref(null)
defineExpose({
  focusMove: () => moveRef.value?.$el?.querySelector?.('.ui-move-trigger')?.focus(),
  focusMore: () => moreRef.value?.focus(),
  focus: () => rootRef.value?.focus(),
  el: () => rootRef.value,
})

function onDragStart(event) {
  if (!canDrag.value) { event.preventDefault?.(); return }
  emit('drag-start', event)
}
</script>

<template>
  <li
    ref="rootRef"
    class="app-row"
    :class="{ 'is-dragging': dragging, 'is-locked': locked, 'can-drag': canDrag }"
    :data-job="row.job_id"
    :data-status="row.status"
    :draggable="canDrag ? 'true' : 'false'"
    tabindex="-1"
    @dragstart="onDragStart"
    @dragend="emit('drag-end', $event)"
  >
    <span class="app-grip" aria-hidden="true"><Icon v-if="canDrag" name="grip" :size="16" /></span>
    <div class="app-main">
      <CompanyMark v-if="showCompany" :name="company" size="sm" />
      <div class="app-title-block">
        <p class="app-title-line">
          <a v-if="url" class="role-title" :href="url" target="_blank" rel="noopener noreferrer" draggable="false">
            {{ role }}<Icon name="external" :size="13" />
          </a>
          <span v-else class="role-title">{{ role }}</span>
          <span v-if="needsFollowUp(row)" class="pill follow-up">Follow up?</span>
        </p>
        <p v-if="meta" class="row-meta">{{ meta }}</p>
      </div>
    </div>
    <!-- The state slot (Q-118 §3, Q-120 U3): one chip for what is happening to the role,
         then what the owner can do about it. "Applied automatically" marks an applied
         status that an auto-apply submit made. A later change adds "Submitted · N answers
         assumed" here (llm_first_fill_design §6): the slot wraps, so it has room. -->
    <div class="app-state" :data-kind="state?.kind || null">
      <span
        v-if="state"
        class="ui-badge app-chip"
        :class="{ 'app-auto': state.icon }"
        :data-tone="state.tone"
        :data-kind="state.kind"
        :title="state.title || undefined"
      ><Icon v-if="state.icon" name="check" :size="12" />{{ state.label }}</span>
      <span v-if="state?.step" class="app-step">{{ state.step }}</span>
      <span v-if="state?.reason" class="app-reason" :title="state.title || undefined">{{ state.reason }}</span>
      <a
        v-if="state?.kind === 'needs_input'"
        class="button ghost app-act app-answer"
        href="#/profile"
        @click.prevent="openProfile('details')"
      >Answer in Profile</a>
      <a
        v-if="stoppedLike && url"
        class="button ghost app-act app-open"
        :href="url"
        target="_blank"
        rel="noopener noreferrer"
        draggable="false"
      >Open the posting</a>
      <button
        v-if="retryable"
        type="button"
        class="app-act app-retry"
        :disabled="retrying || saving"
        @click="tryAgain"
      >{{ retrying ? 'Adding…' : 'Try again' }}</button>
    </div>
    <span class="updated num" :title="exactTime(lastAt(row))">{{ ageLabel(row) }}</span>
    <MoveMenu
      ref="moveRef"
      class="app-move"
      :status="row.status"
      :name="name"
      :disabled="locked || saving"
      :disabled-reason="locked ? LOCKED_REASON : saving ? 'Saving…' : ''"
      @move="s => emit('move', s)"
    />
    <MenuButton
      ref="moreRef"
      class="app-more"
      :label="`More actions for ${name}`"
      :items="moreItems"
      align="end"
      trigger-class="ghost app-more-trigger"
      @select="onMore"
    >
      <template #trigger><Icon name="more" :size="18" /></template>
    </MenuButton>
    <div class="app-below">
      <slot />
    </div>
  </li>
</template>

<style scoped>
.app-row {
  display: grid;
  grid-template-columns: 1rem minmax(0, 1fr) auto auto auto auto;
  grid-template-areas: 'grip main state age move more' 'below below below below below below';
  align-items: center;
  gap: 0 var(--space-3);
  min-height: 3.5rem;
  padding: var(--space-2) var(--space-4) var(--space-2) var(--space-2);
  border-top: 1px solid var(--border);
}
.app-row:first-child { border-top: 0; }
.app-row:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.app-row.can-drag { cursor: grab; }
.app-row.is-dragging { opacity: 0.5; }
.app-grip { grid-area: grip; display: inline-flex; color: var(--muted); opacity: 0; transition: opacity var(--motion) var(--ease-out); }
.app-row:hover .app-grip, .app-row:focus-within .app-grip { opacity: 1; }
.app-main { grid-area: main; display: flex; align-items: center; gap: var(--space-3); min-width: 0; }
.app-title-block { min-width: 0; }
.app-title-line { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1) var(--space-2); margin: 0; }
.role-title {
  display: inline-flex; align-items: center; gap: var(--space-1);
  font-weight: var(--weight-semibold); color: var(--text); text-decoration: none; overflow-wrap: anywhere;
}
a.role-title:hover { color: var(--accent); text-decoration: underline; }
a.role-title .icon { color: var(--muted); }
.row-meta { margin: 2px 0 0; font-size: var(--text-xs); color: var(--muted); }
.follow-up { color: var(--warn); background: var(--warn-soft); }
.app-state { grid-area: state; display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: var(--space-1) var(--space-2); min-width: 0; max-width: min(34rem, 50vw); }
.app-state:empty { display: none; }
/* The chip's tone comes from `.ui-badge[data-tone]`; a long "Stopped: ..." reason wraps. */
.app-chip { white-space: normal; max-width: 24rem; text-align: left; }
.app-auto { white-space: nowrap; }
.app-step, .app-reason { color: var(--muted); font-size: var(--text-xs); }
.app-act { min-height: 1.75rem; padding: 0 var(--space-2); font-size: var(--text-xs); }
.updated { grid-area: age; color: var(--muted); font-size: var(--text-xs); white-space: nowrap; }
.app-move { grid-area: move; justify-self: end; }
.app-more { grid-area: more; }
.app-more :deep(.app-more-trigger) { min-height: 2rem; min-width: 2rem; padding: 0; justify-content: center; color: var(--muted); }
.app-more :deep(.app-more-trigger:hover) { color: var(--text); }
.app-below { grid-area: below; min-width: 0; }
.app-below:empty { display: none; }

@media (max-width: 640px) {
  .app-row {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas: 'main main' 'state state' 'age age' 'move more' 'below below';
    gap: var(--space-1) var(--space-3);
    padding: var(--space-3);
  }
  .app-grip { display: none; }
  .app-state { justify-content: flex-start; }
  .app-move { justify-self: start; }
  .app-more :deep(.app-more-trigger) { min-height: var(--touch-min); min-width: var(--touch-min); }
  .app-state { max-width: none; }
  .app-act { min-height: var(--touch-min); }
}
@media (prefers-reduced-motion: reduce) {
  .app-grip { transition: none; }
}
</style>
