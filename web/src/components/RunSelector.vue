<script setup>
// Picks which run the page shows. It only reports the choice; the shell does
// the fetching, so switching runs never navigates (M7-T2).
const props = defineProps({
  runs: { type: Array, required: true },
  modelValue: { type: [Number, String], default: null },
})
const emit = defineEmits(['update:modelValue'])

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// "2026-09-23T14:30:00" -> "23 Sep". Parsed by hand so the label does not
// depend on the browser's locale or time zone.
function shortDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '')
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}` : 'unfinished'
}

function label(run) {
  const roles = `${run.accepted} role${run.accepted === 1 ? '' : 's'}`
  return `run ${run.run_no} · ${shortDate(run.finished_at)} · ${roles}`
}

function onChange(event) {
  const v = event.target.value
  emit('update:modelValue', v === 'all' ? 'all' : Number(v))
}
</script>

<template>
  <select
    class="run-selector"
    aria-label="Run"
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
</template>
