<script setup>
// A pill-shaped choice between a few options (Q-118 design section 1, 8): the sort
// switch, the stage count in Runs, the Profile tabs' look. Styled by the global
// `.ui-segmented` (style.css).
//
//   <Segmented v-model="sort" label="Sort" :options="[{ value: 'company', label: 'By company' }, ...]" />
//
// A radio group with a roving tabindex: Tab enters on the selected option (the first
// enabled one when nothing is selected), the arrow keys move AND select (so the choice
// must be safe to change, like a sort), Home/End jump to the ends. Disabled options
// are skipped. The selected option is told apart by weight and a lifted shadow as well
// as colour. An option's `ariaLabel` names it when the visible text is short ("All"
// with the number left out); `title` is the tooltip.
import { computed, ref } from 'vue'

const props = defineProps({
  modelValue: { type: [String, Number, Boolean], default: null },
  // [{ value, label, ariaLabel?, disabled?, title? }]
  options: { type: Array, required: true },
  // The group's accessible name.
  label: { type: String, required: true },
})
const emit = defineEmits(['update:modelValue'])

const root = ref(null)

const enabledIndexes = computed(() =>
  props.options.map((o, i) => (o.disabled ? -1 : i)).filter(i => i >= 0))
const selectedIndex = computed(() => props.options.findIndex(o => o.value === props.modelValue))
// The one option that sits in the tab order.
const tabIndex = computed(() => {
  if (selectedIndex.value >= 0 && !props.options[selectedIndex.value].disabled) return selectedIndex.value
  return enabledIndexes.value[0] ?? -1
})

function choose(i) {
  const option = props.options[i]
  if (!option || option.disabled) return
  if (option.value !== props.modelValue) emit('update:modelValue', option.value)
}

function moveTo(i) {
  choose(i)
  root.value?.querySelectorAll('[role="radio"]')[i]?.focus()
}

function onKeydown(event, from) {
  const list = enabledIndexes.value
  if (!list.length) return
  const at = list.indexOf(from)
  let target = null
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') target = list[(at + 1) % list.length]
  else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') target = list[(at - 1 + list.length) % list.length]
  else if (event.key === 'Home') target = list[0]
  else if (event.key === 'End') target = list[list.length - 1]
  else return
  event.preventDefault()
  moveTo(target)
}
</script>

<template>
  <div ref="root" class="ui-segmented" role="radiogroup" :aria-label="label">
    <button
      v-for="(option, i) in options"
      :key="String(option.value)"
      type="button"
      role="radio"
      :aria-checked="String(option.value === modelValue)"
      :aria-label="option.ariaLabel || undefined"
      :title="option.title || undefined"
      :tabindex="i === tabIndex ? 0 : -1"
      :disabled="option.disabled || undefined"
      @click="choose(i)"
      @keydown="onKeydown($event, i)"
    >{{ option.label }}</button>
  </div>
</template>
