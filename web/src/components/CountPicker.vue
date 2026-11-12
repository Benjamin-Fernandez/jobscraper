<script setup>
// How many companies a run takes: one click on a common size - 30, 50, 100,
// 200 or All - or type any number. The presets and the field are one value,
// so picking a preset fills the field and typing a preset's number lights it.
// "All" is every enabled company (`max`). A preset larger than `max` is shown
// but cannot be picked, so the row never reflows when the count changes.
//
// Two shapes of the same control (Q-118 LC):
//   custom="field"    (default; Settings -> Search) the presets, "or", and the number
//                     field always beside them.
//   custom="segment"  (Runs) the presets, All without its number inside the segment, and a
//                     "Custom" segment. The number field appears below only for Custom
//                     (or when the value is not a preset). Its label is `customLabel`.
// Both draw the presets with the global `.ui-segmented` look. The buttons keep
// `aria-pressed`, `.preset` and `data-preset`, and the field keeps `inputId`, so a
// caller's label, hint and tests work in either shape. The arrow keys move focus
// between the segments (they do not choose: a choice here can be a saved setting).
import { computed, nextTick, ref } from 'vue'

const props = defineProps({
  modelValue: { type: [Number, String], default: '' },
  // Enabled companies; null before it is known (then "All" waits for it).
  max: { type: Number, default: null },
  presets: { type: Array, default: () => [30, 50, 100, 200] },
  inputId: { type: String, required: true },
  label: { type: String, default: 'Companies' },
  invalid: { type: Boolean, default: false },
  describedby: { type: String, default: undefined },
  placeholder: { type: String, default: undefined },
  disabled: { type: Boolean, default: false },
  custom: { type: String, default: 'field', validator: v => v === 'field' || v === 'segment' },
  // The number field's label in the segment shape.
  customLabel: { type: String, default: 'Number of companies' },
})
const emit = defineEmits(['update:modelValue'])

const group = ref(null)
const field = ref(null)
const customOpen = ref(false)

const isSegment = computed(() => props.custom === 'segment')
const isAll = computed(() => props.max !== null && props.max > 0 && props.modelValue === props.max)
// Custom is lit after a click on it, or when the value is a number no segment stands for.
const customActive = computed(() => isSegment.value && (customOpen.value
  || (props.modelValue !== '' && !props.presets.includes(props.modelValue) && !isAll.value)))
const showField = computed(() => !isSegment.value || customActive.value)
const presetOn = n => props.modelValue === n && !isAll.value && !customActive.value

function pick(n) {
  customOpen.value = false
  if (!props.disabled) emit('update:modelValue', n)
}

async function openCustom() {
  if (props.disabled) return
  customOpen.value = true
  await nextTick()
  field.value?.focus?.()
}

// v-model.number semantics: '' stays '', a number stays a number, anything
// else (2.5, '1e', '-') is passed on for the owner's validation to refuse.
function onInput(event) {
  const raw = event.target.value
  if (raw === '') return emit('update:modelValue', '')
  const n = Number(raw)
  emit('update:modelValue', Number.isNaN(n) ? raw : n)
}

const tooMany = n => props.max !== null && props.max > 0 && n > props.max

// Left/Right/Home/End move focus along the enabled segments.
function onKeydown(event) {
  const keys = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End']
  if (!keys.includes(event.key)) return
  const list = [...(group.value?.querySelectorAll('button:not(:disabled)') ?? [])]
  if (!list.length) return
  const at = list.indexOf(document.activeElement)
  let to
  if (event.key === 'Home') to = 0
  else if (event.key === 'End') to = list.length - 1
  else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') to = at <= 0 ? list.length - 1 : at - 1
  else to = at === list.length - 1 ? 0 : at + 1
  event.preventDefault()
  list[to].focus()
}
</script>

<template>
  <div class="count-picker" :class="{ disabled, segment: isSegment }">
    <div
      ref="group"
      class="presets ui-segmented"
      role="group"
      :aria-label="`${label}: common sizes`"
      @keydown="onKeydown"
    >
      <button
        v-for="n in presets"
        :key="n"
        type="button"
        class="preset"
        :class="{ active: presetOn(n) }"
        :aria-pressed="presetOn(n) ? 'true' : 'false'"
        :disabled="disabled || tooMany(n)"
        :title="tooMany(n) ? `Only ${max} companies are enabled` : undefined"
        :data-preset="n"
        @click="pick(n)"
      >{{ n }}</button>
      <button
        type="button"
        class="preset all"
        :class="{ active: isAll && !customActive }"
        :aria-pressed="isAll && !customActive ? 'true' : 'false'"
        :aria-label="isSegment && max ? `All ${max} companies` : undefined"
        :title="isSegment && max ? `All ${max} enabled companies` : undefined"
        :disabled="disabled || !max"
        data-preset="all"
        @click="pick(max)"
      >All<span v-if="max && !isSegment" class="all-n">{{ max }}</span></button>
      <button
        v-if="isSegment"
        type="button"
        class="preset custom-toggle"
        :class="{ active: customActive }"
        :aria-pressed="customActive ? 'true' : 'false'"
        :disabled="disabled"
        data-preset="custom"
        @click="openCustom"
      >Custom</button>
    </div>
    <span v-if="!isSegment" class="or" aria-hidden="true">or</span>
    <div v-if="showField" class="custom-field">
      <label v-if="isSegment" :for="inputId" class="custom-label">{{ customLabel }}</label>
      <input
        :id="inputId"
        ref="field"
        class="custom num"
        type="number"
        inputmode="numeric"
        min="1"
        :max="max || undefined"
        :value="modelValue"
        :placeholder="placeholder"
        :aria-invalid="invalid ? 'true' : 'false'"
        :aria-describedby="describedby"
        :disabled="disabled"
        @input="onInput"
      >
    </div>
  </div>
</template>

<style scoped>
.count-picker { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2) var(--space-3); }
.count-picker.segment { display: grid; justify-items: start; gap: var(--space-3); }
/* The shared segmented track (style.css); this only keeps a narrow screen from clipping it. */
.presets { flex-wrap: wrap; border-radius: var(--radius-lg); }
.preset { min-width: 2.5rem; padding-inline: var(--space-3); }
.preset.all { gap: var(--space-1); }
/* The enabled count beside "All" (the Settings shape): small, muted, kept off the word. */
.all-n { margin-left: var(--space-1); font-size: var(--text-xs); font-weight: 400; color: var(--muted); font-variant-numeric: tabular-nums lining-nums; }
.preset.active .all-n { color: inherit; }
.or { color: var(--muted); font-size: var(--text-sm); }
.custom-field { display: grid; gap: var(--space-1); }
.custom-label { font-size: var(--text-xs); font-weight: var(--weight-medium); color: var(--muted); }
.custom { width: 8rem; }
.count-picker:not(.segment) .custom { width: 7rem; }
@media (max-width: 640px) {
  .preset { min-width: var(--touch-min); }
}
</style>
