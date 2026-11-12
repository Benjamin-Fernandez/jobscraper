<script setup>
// A sortable table header cell (Q-118 design section 1, 5): `th[aria-sort]` holding one
// button, so the column is sorted by keyboard too.
//
//   <SortHeader label="Open roles" column="roles" :sort="sort" numeric @sort="onSort" />
//
// `sort` is { key, dir } with dir 'asc' | 'desc'; the header whose `column` equals
// `sort.key` gets aria-sort "ascending" / "descending", the others "none". The chevron is
// hidden until the column is sorted and points up for ascending, down for descending.
// The caller decides what a click does (flip, or start ascending) in its `sort(column)`
// handler. `numeric` right-aligns the cell, to sit over a `.col-num` column.
import { computed } from 'vue'
import Icon from '../components/Icon.vue'

const props = defineProps({
  label: { type: String, required: true },
  column: { type: String, required: true },
  sort: { type: Object, default: () => ({ key: '', dir: 'asc' }) },
  numeric: { type: Boolean, default: false },
})
const emit = defineEmits(['sort'])

const active = computed(() => props.sort?.key === props.column)
const ariaSort = computed(() => (active.value ? (props.sort.dir === 'desc' ? 'descending' : 'ascending') : 'none'))
</script>

<template>
  <th scope="col" class="ui-th" :class="{ 'col-num': numeric }" :aria-sort="ariaSort">
    <button type="button" class="ui-th-sort" :class="{ 'is-active': active, 'is-desc': active && sort.dir === 'desc' }" @click="emit('sort', column)">
      <span>{{ label }}</span>
      <Icon class="ui-th-chevron" name="chevron" :size="14" />
    </button>
  </th>
</template>

<style scoped>
.ui-th-sort {
  gap: var(--space-1);
  min-height: 2rem;
  padding: 0 var(--space-2);
  font-size: inherit;
  font-weight: inherit;
  color: inherit;
  background: transparent;
  border: 0;
  border-radius: var(--radius-sm);
  box-shadow: none;
}
.ui-th-sort:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
.ui-th-sort.is-active { color: var(--text); }
.ui-th-chevron { opacity: 0; transform: rotate(180deg); transition: transform var(--motion) var(--ease-out), opacity var(--motion) var(--ease-out); }
.ui-th-sort:hover .ui-th-chevron { opacity: 0.4; }
.ui-th-sort.is-active .ui-th-chevron { opacity: 1; }
.ui-th-sort.is-active.is-desc .ui-th-chevron { transform: rotate(0deg); }
@media (max-width: 640px) {
  .ui-th-sort { min-height: var(--touch-min); }
}
@media (prefers-reduced-motion: reduce) {
  .ui-th-chevron { transition: none; }
}
</style>
