<script setup>
// "Move to" for one application (Q-118 design section 3): the stage pill doubles as
// the menu trigger, and choosing a stage emits `move(status)` for the caller to commit
// (the caller owns the toast with Undo and the live-region announcement).
//
//   <MoveMenu :status="row.status" :name="`${row.title} at ${row.company}`" @move="s => change(row, s)" />
//
// Built on MenuButton (kind radio). The trigger is the existing `.pill[data-status]`
// plus a chevron, its text `statusLabel(status)`; the accessible name is
// "Move {name}, now {Stage}"; the menu is headed "Move to"; the current stage is checked
// and disabled. A status that is not a target ("To apply", "Assessment", "Withdrawn")
// shows its own word on the pill and has no target checked. `disabled` (with a
// `disabledReason`) keeps the pill focusable and explains itself.
import { computed } from 'vue'
import Icon from '../components/Icon.vue'
import MenuButton from './MenuButton.vue'
import { MOVE_TARGETS, statusLabel } from '../stages.js'

const props = defineProps({
  status: { type: String, default: '' },
  targets: { type: Array, default: () => MOVE_TARGETS },
  // e.g. "SRE at Flowdesk"
  name: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  disabledReason: { type: String, default: '' },
})
const emit = defineEmits(['move'])

const stage = computed(() => statusLabel(props.status))
const label = computed(() => {
  const now = stage.value ? `, now ${stage.value}` : ''
  return `Move ${props.name}${now}`.replace(/\s+/g, ' ').trim()
})
const items = computed(() => props.targets.map(t => ({
  id: t,
  label: statusLabel(t),
  checked: t === props.status,
  disabled: t === props.status,
})))
</script>

<template>
  <MenuButton
    class="ui-move"
    kind="radio"
    heading="Move to"
    :label="label"
    :items="items"
    :disabled="disabled"
    :disabled-reason="disabledReason"
    trigger-class="ui-move-trigger"
    @select="emit('move', $event)"
  >
    <template #trigger>
      <span class="pill" :data-status="status">{{ stage }}</span>
      <Icon name="chevron" :size="14" />
    </template>
  </MenuButton>
</template>

<style scoped>
/* The pill is the control: take the button chrome off and keep the pill's own colours. */
.ui-move :deep(.ui-move-trigger) {
  position: relative;
  gap: var(--space-1);
  min-height: 0;
  padding: 0;
  color: var(--muted);
  background: transparent;
  border: 0;
  border-radius: var(--radius-pill);
  box-shadow: none;
}
.ui-move :deep(.ui-move-trigger:hover:not(.is-disabled)) { background: transparent; color: var(--text); }
.ui-move :deep(.ui-move-trigger:hover:not(.is-disabled) .pill) { filter: brightness(0.96); }
.ui-move :deep(.ui-move-trigger .pill) { padding: 2px var(--space-2); }
/* The look stays small; the hit area reaches --touch-min. */
@media (max-width: 640px) {
  .ui-move :deep(.ui-move-trigger)::after {
    content: '';
    position: absolute;
    left: 50%;
    top: 50%;
    width: max(100%, var(--touch-min));
    height: var(--touch-min);
    transform: translate(-50%, -50%);
  }
}
</style>
