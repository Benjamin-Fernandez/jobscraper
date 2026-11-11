<script setup>
// One card of the Connected accounts hub (Q-100 design §4.1): an icon, the name, the
// state as a chip (words first, colour second), one line saying why, when it was
// last checked, and one primary action. The hub decides what goes in the slots; the
// card only lays them out and answers a deep link (`#/settings/accounts/<card>`).
//
// A card never shows a password and never asks for one (D-191): where the fix is a
// command line, `fix.commands` lists the exact commands inside "See how to fix", and
// the command prompts for the secret itself.
import { computed } from 'vue'
import { ago, when } from '../format.js'
import StateChip from './StateChip.vue'

const props = defineProps({
  // The deep-link key: 'gmail', 'apply-mailbox', 'edge', 'model', 'employer-accounts'.
  cardId: { type: String, required: true },
  title: { type: String, required: true },
  icon: { type: String, default: '' },
  // The item whose state the chip shows (an entry of `items`, or a stand-in).
  item: { type: Object, default: null },
  // One line under the title: why the chip says what it says.
  line: { type: String, default: '' },
  checkedAt: { type: String, default: null },
  nextCheckAt: { type: String, default: null },
  // This card is the target of the open deep link: it is marked for a moment.
  target: { type: Boolean, default: false },
  // { commands: [string], note?: string } -> a "See how to fix" disclosure.
  fix: { type: Object, default: null },
})

const headingId = computed(() => `conn-${props.cardId}-title`)
const times = computed(() => {
  const parts = []
  if (props.checkedAt) parts.push(`Last checked ${ago(props.checkedAt) || when(props.checkedAt)}`)
  if (props.nextCheckAt) parts.push(`next check ${when(props.nextCheckAt)}`)
  const text = parts.join(' · ')
  return text ? text[0].toUpperCase() + text.slice(1) : ''
})
</script>

<template>
  <section
    class="conn-card surface"
    :class="{ 'is-target': target }"
    :data-card="cardId"
    :data-state="item?.state || ''"
    :aria-labelledby="headingId"
  >
    <header class="conn-head">
      <span class="conn-icon" aria-hidden="true">{{ icon }}</span>
      <h4 :id="headingId" class="conn-title" tabindex="-1">{{ title }}</h4>
      <StateChip v-if="item" :item="item" :label="title" class="conn-chip" />
    </header>

    <p v-if="line" class="conn-line">{{ line }}</p>
    <p v-if="times" class="conn-times muted">{{ times }}</p>

    <div class="conn-body"><slot /></div>

    <details v-if="fix" class="conn-fix">
      <summary>See how to fix</summary>
      <p v-if="fix.note" class="conn-fix-note">{{ fix.note }}</p>
      <pre v-for="c in fix.commands" :key="c" class="code-wrap conn-command">{{ c }}</pre>
    </details>

    <div v-if="$slots.actions" class="conn-actions"><slot name="actions" /></div>
  </section>
</template>

<style scoped>
.conn-card { display: grid; gap: var(--space-2); padding: var(--space-4); max-width: 46rem; }
.conn-card.is-target { outline: 2px solid var(--focus); outline-offset: 2px; }
.conn-head { display: flex; align-items: center; gap: var(--space-2); flex-wrap: wrap; }
.conn-icon { font-size: var(--text-md); color: var(--text-2); width: 1.5rem; text-align: center; flex: none; }
.conn-title { margin: 0; font-size: var(--text-md); font-weight: 650; flex: 1 1 auto; min-width: 0; overflow-wrap: anywhere; }
.conn-title:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
.conn-chip { flex: none; }
.conn-line, .conn-times { margin: 0; font-size: var(--text-sm); text-wrap: pretty; }
.conn-line { color: var(--text-2); }
.conn-body { display: grid; gap: var(--space-2); }
.conn-body:empty { display: none; }
.conn-actions { display: flex; flex-wrap: wrap; gap: var(--space-2); }
.conn-fix summary {
  display: flex; align-items: center; min-height: 2rem; cursor: pointer;
  font-size: var(--text-sm); font-weight: 600; color: var(--accent);
}
.conn-fix summary:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
.conn-fix-note { margin: var(--space-1) 0; font-size: var(--text-sm); color: var(--text-2); }
.conn-command { margin: var(--space-1) 0; }
@media (max-width: 640px) {
  .conn-card { padding: var(--space-3); }
  .conn-fix summary { min-height: var(--touch-min); }
}
</style>
