<script setup>
// An on/off setting as a row (Q-118 design section 1, 8), drawn like the Settings
// switch rows (SettingRow.vue, Q-116 section 3): the label over a muted description on
// the left, "On"/"Off" written out beside the track on the right, so state never rests
// on colour alone. Used by the Runs "Dry run" control.
//
//   <Switch v-model="dryRun" label="Dry run" description="Fetch and report; save nothing." />
//
// `button[role=switch][aria-checked]`, named by its label and described by the
// description. While `busy` it has `aria-busy` and ignores clicks (it stays focusable,
// so a keyboard user is not thrown off the control); `disabled` is a real disabled
// button. At 640px and below the row is at least 44px tall.
import { computed, useId } from 'vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  label: { type: String, required: true },
  description: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const uid = useId()
const labelId = computed(() => `ui-switch-${uid}-label`)
const descId = computed(() => `ui-switch-${uid}-desc`)

function toggle() {
  if (props.disabled || props.busy) return
  emit('update:modelValue', !props.modelValue)
}
</script>

<template>
  <button
    type="button"
    class="ui-switch"
    :class="{ 'is-busy': busy }"
    role="switch"
    :aria-checked="String(modelValue)"
    :aria-labelledby="labelId"
    :aria-describedby="description ? descId : undefined"
    :aria-busy="busy ? 'true' : undefined"
    :disabled="disabled || undefined"
    @click="toggle"
  >
    <span class="ui-switch-text">
      <span :id="labelId" class="ui-switch-label">{{ label }}</span>
      <span v-if="description" :id="descId" class="ui-switch-desc">{{ description }}</span>
    </span>
    <span class="ui-switch-side" aria-hidden="true">
      <span class="ui-switch-state">{{ modelValue ? 'On' : 'Off' }}</span>
      <span class="ui-switch-track" :class="{ on: modelValue }"><span class="ui-switch-thumb" /></span>
    </span>
  </button>
</template>

<style scoped>
.ui-switch {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  column-gap: var(--space-4);
  width: 100%;
  min-height: 3.5rem;
  padding: var(--space-3);
  background: transparent;
  border: 0;
  border-radius: var(--radius);
  box-shadow: none;
  color: var(--text);
  text-align: left;
  /* The global button style is `nowrap`; the description must wrap. */
  white-space: normal;
}
.ui-switch:hover:not(:disabled) { background: var(--surface-2); }
.ui-switch:disabled { cursor: not-allowed; }
.ui-switch.is-busy { cursor: progress; opacity: 0.7; }

.ui-switch-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.ui-switch-label { font-size: var(--text-sm); font-weight: var(--weight-semibold); overflow-wrap: anywhere; }
.ui-switch-desc { font-size: var(--text-sm); font-weight: 400; color: var(--muted); overflow-wrap: anywhere; }

.ui-switch-side { display: inline-flex; align-items: center; gap: var(--space-2); color: var(--text-2); font-size: var(--text-sm); }
.ui-switch-track {
  position: relative;
  flex: none;
  width: 2.25rem;
  height: 1.375rem;
  border-radius: var(--radius-pill);
  background: var(--border-strong);
  transition: background-color var(--motion) var(--ease-out);
}
.ui-switch-track.on { background: var(--accent); }
.ui-switch-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: calc(1.375rem - 4px);
  height: calc(1.375rem - 4px);
  border-radius: 50%;
  background: var(--surface);
  transition: transform var(--motion) var(--ease-out);
}
.ui-switch-track.on .ui-switch-thumb { transform: translateX(0.875rem); }

@media (max-width: 640px) {
  .ui-switch { min-height: max(3.5rem, var(--touch-min)); }
}
@media (prefers-reduced-motion: reduce) {
  .ui-switch-track, .ui-switch-thumb { transition: none; }
}
</style>
