<script setup>
// Picks which run a tab shows. It only reports the choice; whoever owns the
// data does the fetching, so switching runs never navigates (M7-T2).
import { plural, shortDate } from '../format.js'

const props = defineProps({
  runs: { type: Array, required: true },
  modelValue: { type: [Number, String], default: null },
})
const emit = defineEmits(['update:modelValue'])

function label(run) {
  return `run ${run.run_no} · ${shortDate(run.finished_at) || 'unfinished'} · ${plural(run.accepted ?? 0, 'role')}`
}

function onChange(event) {
  const v = event.target.value
  emit('update:modelValue', v === 'all' ? 'all' : Number(v))
}
</script>

<template>
  <label class="run-selector">
    <span class="run-label">Run</span>
    <select
      :value="props.modelValue"
      :disabled="!props.runs.length"
      @change="onChange"
    >
      <option v-if="!props.runs.length" :value="null">no runs yet</option>
      <option v-for="run in props.runs" :key="run.run_no" :value="run.run_no">
        {{ label(run) }}
      </option>
      <option v-if="props.runs.length" value="all">all runs</option>
    </select>
  </label>
</template>

<style scoped>
.run-selector { display: inline-flex; align-items: center; gap: 0.5rem; }
.run-label { color: var(--muted); font-size: 0.875rem; }
select { max-width: 100%; }
</style>
