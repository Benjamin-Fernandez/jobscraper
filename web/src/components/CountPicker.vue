<script setup>
// How many companies a run takes: one click on a common size - 30, 50, 100,
// 200 or All - or type any number. The presets and the field are one value,
// so picking a preset fills the field and typing a preset's number lights it.
// "All" is every enabled company (`max`). A preset larger than `max` is shown
// but cannot be picked, so the row never reflows when the count changes.
import { computed } from 'vue'

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
})
const emit = defineEmits(['update:modelValue'])

const isAll = computed(() => props.max !== null && props.max > 0 && props.modelValue === props.max)

function pick(n) {
  if (!props.disabled) emit('update:modelValue', n)
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
</script>

<template>
  <div class="count-picker" :class="{ disabled }">
    <div class="presets" role="group" :aria-label="`${label}: common sizes`">
      <button
        v-for="n in presets"
        :key="n"
        type="button"
        class="preset"
        :class="{ active: modelValue === n && !isAll }"
        :aria-pressed="modelValue === n && !isAll ? 'true' : 'false'"
        :disabled="disabled || tooMany(n)"
        :title="tooMany(n) ? `Only ${max} companies are enabled` : undefined"
        :data-preset="n"
        @click="pick(n)"
      >{{ n }}</button>
      <button
        type="button"
        class="preset all"
        :class="{ active: isAll }"
        :aria-pressed="isAll ? 'true' : 'false'"
        :disabled="disabled || !max"
        data-preset="all"
        @click="pick(max)"
      >All<span v-if="max" class="all-n">{{ max }}</span></button>
    </div>
    <span class="or" aria-hidden="true">or</span>
    <input
      :id="inputId"
      class="custom"
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
</template>

<style scoped>
.count-picker { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2) var(--space-3); }
.presets {
  display: inline-flex; flex-wrap: wrap; gap: 2px; padding: 2px;
  background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius);
}
.preset {
  min-width: 3rem; min-height: calc(var(--control-h) - 6px); padding: 0 var(--space-3);
  border: 1px solid transparent; border-radius: calc(var(--radius) - 2px);
  background: transparent; box-shadow: none; color: var(--text-2);
  font-family: var(--mono); font-variant-numeric: tabular-nums;
}
.preset.all { font-family: var(--font); gap: var(--space-1); }
.all-n { font-family: var(--mono); font-size: var(--text-xs); color: var(--muted); }
.preset:hover:not(:disabled) { background: var(--surface); color: var(--text); }
.preset.active, .preset.active:hover:not(:disabled) {
  background: var(--surface); border-color: var(--border-strong); box-shadow: var(--shadow-sm);
  color: var(--accent); font-weight: 650;
}
.preset.active .all-n { color: inherit; }
.or { color: var(--muted); font-size: var(--text-sm); }
.custom { width: 7rem; }
</style>
