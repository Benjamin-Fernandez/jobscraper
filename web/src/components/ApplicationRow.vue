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
import { computed, ref } from 'vue'
import { ordinal } from '../api.js'
import { attemptLabel } from '../attempts.js'
import { LOCKED_REASON, ageLabel, appliedAutomatically, inFlight, lastAt, needsFollowUp, secondLine } from '../applications.js'
import { exactTime, safeUrl } from '../format.js'
import { openProfile } from '../profileView.js'
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
const locked = computed(() => inFlight(props.row))
const canDrag = computed(() => props.dragEnabled && !locked.value && !props.saving)
const removable = computed(() => (props.row.events?.length ?? 0) <= 1)
const meta = computed(() => [props.showCompany ? company.value : '', secondLine(props.row)].filter(Boolean).join(' · '))
const attempt = computed(() => props.row.last_attempt ?? null)
const auto = computed(() => appliedAutomatically(props.row))

// The queue lane's `queued` kind (U3) may arrive before attempts.js words it.
const attemptText = computed(() => {
  const a = attempt.value
  if (!a) return ''
  if (a.kind === 'queued') {
    const p = Number(props.row.queue?.position)
    return p > 0 ? `Queued · ${ordinal(p)}` : 'Queued'
  }
  return attemptLabel(a.kind, a.mode)
})

const moreItems = computed(() => [
  { id: 'note', label: props.row.notes ? 'Edit note' : 'Add note' },
  { id: 'details', label: props.detailsOpen ? 'Hide details' : 'Show details' },
  ...(url.value ? [{ id: 'open', label: 'Open the posting' }] : []),
  ...(removable.value ? [{ id: 'remove', label: 'Remove from Applications', danger: true }] : []),
])

function onMore(id) {
  if (id === 'note') emit('note')
  else if (id === 'details') emit('details')
  else if (id === 'remove') emit('remove')
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
    <!-- The state slot (Q-118 §3, shared with Q-120 U3). Today it shows the latest
         auto-apply attempt (Q-76 N11) as before; the queue lane words the queue states
         here ("Queued · 3rd", "Applying…", "Try again"). "Applied automatically" marks
         an applied status that an auto-apply submit made. -->
    <div class="app-state" :data-kind="attempt?.kind || null">
      <span v-if="auto" class="ui-badge app-auto" data-tone="ok"><Icon name="check" :size="12" />Applied automatically</span>
      <button
        v-else-if="attempt?.kind === 'needs_input'"
        type="button"
        class="pill attempt attempt-link"
        data-kind="needs_input"
        :title="attempt.text"
        @click="openProfile('details')"
      >{{ attemptText }}</button>
      <span
        v-else-if="attempt"
        class="pill attempt"
        :data-kind="attempt.kind"
        :title="attempt.text || undefined"
      >{{ attemptText }}</span>
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
.app-state { grid-area: state; display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: var(--space-2); min-width: 0; }
.app-state:empty { display: none; }
.app-auto { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
/* The auto-apply pill: green when sent, amber when it waits for you, red when it stopped. */
.attempt { color: var(--text-2); background: var(--surface-3); white-space: nowrap; }
.attempt[data-kind='sent'] { color: var(--ok); background: var(--ok-soft); }
.attempt[data-kind='dry_run'], .attempt[data-kind='unconfirmed'], .attempt[data-kind='needs_input'] { color: var(--warn); background: var(--warn-soft); }
.attempt[data-kind='stopped'] { color: var(--danger); background: var(--danger-soft); }
button.attempt-link { border: 0; cursor: pointer; font: inherit; font-size: var(--text-xs); font-weight: 600; line-height: 1.7; min-height: 0; padding: 0 var(--space-2); box-shadow: none; }
button.attempt-link:hover { text-decoration: underline; }
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
  button.attempt-link { min-height: var(--touch-min); }
}
@media (prefers-reduced-motion: reduce) {
  .app-grip { transition: none; }
}
</style>
