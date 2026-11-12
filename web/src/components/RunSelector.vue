<script setup>
// Which runs a tab shows (M15): All runs first - always - then Past week and
// Past month, then a "Choose runs…" button (Q-70 C7, G4: it was a select option,
// which read as a filter value), which asks the owner to open the picker on
// the Runs tab (`choose`). Runs chosen there show as one more option, so the
// selector always says what is on screen. It only reports the choice; whoever
// owns the data does the fetching, so switching never navigates (M7-T2).
import { computed, useId } from 'vue'
import { RANGES, isRange, runLabel } from '../runs.js'

const props = defineProps({
  runs: { type: Array, required: true },
  modelValue: { type: [Number, String, Array], default: 'all' },
  // false where a picker makes no sense (Applications filters by range only).
  choosable: { type: Boolean, default: true },
})
const emit = defineEmits(['update:modelValue', 'choose'])

const id = useId()
const chosen = computed(() => !isRange(props.modelValue) && props.modelValue !== null)
const selected = computed(() => (chosen.value ? 'chosen' : (props.modelValue ?? 'all')))

function onChange(event) {
  const v = event.target.value
  if (v !== 'chosen') emit('update:modelValue', v)
}
</script>

<template>
  <div class="run-selector">
    <label class="run-label" :for="id">Runs</label>
    <!-- Q-118: the shared .ui-select chevron; the select itself is unchanged. -->
    <span class="ui-select">
      <select :id="id" :value="selected" :disabled="!props.runs.length" @change="onChange">
        <option v-for="(label, value) in RANGES" :key="value" :value="value">{{ label }}</option>
        <option v-if="chosen" value="chosen">{{ runLabel(props.modelValue) }}</option>
      </select>
    </span>
    <button v-if="props.choosable" type="button" class="ghost choose-runs" @click="emit('choose')">Choose runs…</button>
  </div>
</template>

<style scoped>
.run-selector { display: inline-flex; align-items: center; gap: var(--space-2); max-width: 100%; }
.run-label { color: var(--muted); font-size: var(--text-sm); font-weight: 500; }
select { max-width: 100%; min-width: 9.5rem; }
</style>
