<script setup>
// The Settings category rail (Q-116 design §3, §6): a vertical tablist at the left of
// the page. Each entry is an icon, the name and an optional badge (a dot and a number,
// with the meaning in visually hidden words, so it is never colour alone). Arrow keys
// (Up/Down, and Left/Right as the old segmented control had), Home and End move AND
// select, with roving tabindex; the page owns what a selection does (the hash).
//
//   <SettingsRail :categories="[{ id, label, icon, badge, badgeText }]" v-model="view" />
//
// Tab ids are `settings-tab-<id>`, each controlling `settings-panel-<id>`.
import { nextTick } from 'vue'
import Icon from './Icon.vue'
import { COPY } from '../settingsRows.js'

const props = defineProps({
  categories: { type: Array, required: true },
  modelValue: { type: String, required: true },
})
const emit = defineEmits(['update:modelValue'])

function select(id) {
  emit('update:modelValue', id)
}

async function onKey(e, i) {
  const last = props.categories.length - 1
  const next = {
    ArrowDown: i + 1, ArrowRight: i + 1, ArrowUp: i - 1, ArrowLeft: i - 1, Home: 0, End: last,
  }[e.key]
  if (next === undefined) return
  e.preventDefault()
  const id = props.categories[(next + last + 1) % (last + 1)].id
  select(id)
  await nextTick()
  document.getElementById(`settings-tab-${id}`)?.focus()
}
</script>

<template>
  <div class="rail" role="tablist" aria-orientation="vertical" :aria-label="COPY.railLabel">
    <button
      v-for="(c, i) in categories"
      :id="`settings-tab-${c.id}`"
      :key="c.id"
      type="button"
      role="tab"
      class="rail-tab"
      :class="{ active: modelValue === c.id }"
      :aria-selected="modelValue === c.id ? 'true' : 'false'"
      :aria-controls="`settings-panel-${c.id}`"
      :tabindex="modelValue === c.id ? 0 : -1"
      @click="select(c.id)"
      @keydown="onKey($event, i)"
    >
      <Icon :name="c.icon" :size="18" />
      <span class="rail-name">{{ c.label }}</span>
      <span v-if="c.badge > 0" class="view-badge">
        <span aria-hidden="true">{{ c.badge }}</span>
        <span class="visually-hidden">{{ c.badge }} {{ c.badgeText }}</span>
      </span>
    </button>
  </div>
</template>

<style scoped>
.rail { display: flex; flex-direction: column; gap: 2px; position: sticky; top: var(--space-4); align-self: start; }
.rail-tab {
  display: flex; align-items: center; gap: var(--space-3); width: 100%;
  min-height: var(--touch-min); padding: var(--space-2) var(--space-3);
  border: 0; border-left: 3px solid transparent; border-radius: var(--radius);
  background: transparent; box-shadow: none; color: var(--text-2); text-align: left;
}
.rail-tab:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
.rail-tab.active, .rail-tab.active:hover:not(:disabled) {
  background: var(--surface); border-left-color: var(--border-strong);
  border-radius: 0 var(--radius) var(--radius) 0; color: var(--text); font-weight: 650;
}
.rail-name { flex: 1 1 auto; min-width: 0; }
/* The attention count: a dot and a number, so it is not colour alone. */
.view-badge {
  display: inline-flex; align-items: center; gap: var(--space-1);
  font-size: var(--text-xs); font-weight: 700; color: var(--state-attention-fg);
}
.view-badge::before { content: ''; width: 0.5rem; height: 0.5rem; border-radius: 50%; background: currentColor; }
</style>
