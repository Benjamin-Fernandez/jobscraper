<script setup>
// A status select that commits on purpose (Q-70 B3, G5). A native select fires
// `change` on every ArrowDown, so a keyboard user passing over "Rejected" on
// the way to "Interviewing" would save it. A pointer choice (the menu click)
// commits at once; a keyboard change is held as `pending` until Enter or
// blur, and Escape drops it.
import { ref } from 'vue'
import { statusLabel } from '../stages.js'

const props = defineProps({
  modelValue: { type: String, default: '' },
  options: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
  label: { type: String, default: '' },
})
const emit = defineEmits(['commit'])

let viaPointer = false
const pending = ref(null)

function flush() {
  const v = pending.value
  pending.value = null
  if (v !== null && v !== props.modelValue) emit('commit', v)
}

function onKeydown(e) {
  viaPointer = false
  if (e.key === 'Enter') {
    e.preventDefault()
    flush()
  } else if (e.key === 'Escape') {
    pending.value = null
    e.target.value = props.modelValue
  }
}

function onChange(e) {
  const v = e.target.value
  if (viaPointer) {
    viaPointer = false
    pending.value = null
    if (v !== props.modelValue) emit('commit', v)
  } else {
    pending.value = v
  }
}
</script>

<template>
  <label class="status-field">
    <span class="visually-hidden">{{ label }}</span>
    <select
      class="status-select"
      :data-status="pending ?? modelValue"
      :value="pending ?? modelValue"
      :disabled="disabled"
      @pointerdown="viaPointer = true"
      @keydown="onKeydown"
      @change="onChange"
      @blur="flush"
    >
      <option v-for="s in options" :key="s" :value="s">{{ statusLabel(s) }}</option>
    </select>
  </label>
</template>

<style scoped>
.status-field { display: block; }
/* The status control wears its stage colour. */
.status-select {
  width: 100%;
  font-weight: 600;
  border-color: var(--control-border, var(--border-strong));
  color: var(--stage-closed);
  background-color: var(--stage-closed-soft);
}
.status-select[data-status='to_apply'] { color: var(--stage-saved); background-color: var(--stage-saved-soft); }
.status-select[data-status='applied'] { color: var(--stage-applied); background-color: var(--stage-applied-soft); }
.status-select[data-status='assessment'] { color: var(--stage-assessment); background-color: var(--stage-assessment-soft); }
.status-select[data-status='interviewing'] { color: var(--stage-interview); background-color: var(--stage-interview-soft); }
.status-select[data-status='offer'] { color: var(--stage-offer); background-color: var(--stage-offer-soft); }
.status-select[data-status='rejected'] { color: var(--stage-rejected); background-color: var(--stage-rejected-soft); }
.status-select option { color: var(--text); background: var(--surface); }
</style>
