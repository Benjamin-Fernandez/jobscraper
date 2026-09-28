<script setup>
// A small line-icon set (M13-T4), drawn here so the app needs no icon package.
// Shapes are data, rendered element by element - never v-html - so nothing in
// the page is ever parsed from a string. 24-unit grid, 1.8 stroke, round caps.
import { computed } from 'vue'

const ICONS = {
  search: [['circle', { cx: 11, cy: 11, r: 7 }], ['path', { d: 'm20 20-3.6-3.6' }]],
  external: [['path', { d: 'M14 4h6v6' }], ['path', { d: 'M20 4 10.5 13.5' }],
    ['path', { d: 'M18 14v4.5A1.5 1.5 0 0 1 16.5 20h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10' }]],
  check: [['path', { d: 'm5 12.5 4.5 4.5L19 7.5' }]],
  bookmark: [['path', { d: 'M7 4h10a1 1 0 0 1 1 1v15l-6-4-6 4V5a1 1 0 0 1 1-1z' }]],
  x: [['path', { d: 'M6.5 6.5l11 11M17.5 6.5l-11 11' }]],
  pin: [['path', { d: 'M12 21s-6.5-5.6-6.5-11a6.5 6.5 0 0 1 13 0c0 5.4-6.5 11-6.5 11z' }], ['circle', { cx: 12, cy: 10, r: 2.3 }]],
  clock: [['circle', { cx: 12, cy: 12, r: 8.5 }], ['path', { d: 'M12 7.5V12l3 2' }]],
  briefcase: [['rect', { x: 3.5, y: 7, width: 17, height: 12.5, rx: 2 }], ['path', { d: 'M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7M3.5 12.5h17' }]],
  undo: [['path', { d: 'M9 14 4.5 9.5 9 5' }], ['path', { d: 'M4.5 9.5H15a4.5 4.5 0 0 1 0 9h-3' }]],
  back: [['path', { d: 'm14.5 6-6 6 6 6' }]],
  chevron: [['path', { d: 'm6.5 9.5 5.5 5.5 5.5-5.5' }]],
  inbox: [['path', { d: 'M3.5 13h4.5l1.5 2.5h5L16 13h4.5' }], ['path', { d: 'M6 5h12l2.5 8v5.5a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5V13z' }]],
  target: [['circle', { cx: 12, cy: 12, r: 8.5 }], ['circle', { cx: 12, cy: 12, r: 4.5 }], ['circle', { cx: 12, cy: 12, r: 0.8 }]],
  layers: [['path', { d: 'm12 4 8.5 4.5L12 13 3.5 8.5z' }], ['path', { d: 'm3.5 12.5 8.5 4.5 8.5-4.5' }], ['path', { d: 'm3.5 16.5 8.5 4.5 8.5-4.5' }]],
}

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [Number, String], default: 16 },
})

const shapes = computed(() => ICONS[props.name] ?? [])
</script>

<template>
  <svg
    class="icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.8"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <component :is="tag" v-for="([tag, attrs], i) in shapes" :key="i" v-bind="attrs" />
  </svg>
</template>
