<script setup>
// "Auto-apply on" in the masthead (Q-100 design §1, researcher M2): seen from any
// tab, so the owner always knows applications may be sent without them. It shows
// only when GET /api/apply/status says `mode: "auto"`; dry run, an absent route
// (null) or a failed call shows nothing - never a guess. It links to
// Settings → Apply, where the mode is explained and, later, changed.
import { computed } from 'vue'
import { COPY } from '../connections.js'
import { hashFor } from '../route.js'

const props = defineProps({
  // The GET /api/apply/status answer ({mode, missing, busy}), or null.
  status: { type: Object, default: null },
})

const on = computed(() => props.status?.mode === 'auto')
</script>

<template>
  <a
    v-if="on"
    class="mode-chip"
    :href="hashFor('settings', 'apply')"
    :title="COPY.modeChipTitle"
    data-mode="auto"
  >
    <span class="mode-dot" aria-hidden="true" />
    {{ COPY.modeChip }}<span class="visually-hidden">. {{ COPY.modeChipTitle }}</span>
  </a>
</template>

<style scoped>
.mode-chip {
  position: relative;
  align-self: center;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  padding: 0 var(--space-2);
  font-size: var(--text-xs);
  font-weight: 650;
  line-height: 1.8;
  white-space: nowrap;
  color: var(--warn);
  background: var(--warn-soft);
  border: 1px solid color-mix(in srgb, var(--warn) 40%, transparent);
  border-radius: 999px;
  text-decoration: none;
}
.mode-chip:hover { color: var(--warn); text-decoration: underline; }
/* A filled dot repeats "on" as a shape. */
.mode-dot { width: 0.5rem; height: 0.5rem; border-radius: 50%; background: currentColor; flex: none; }
/* The chip stays small; its hit area reaches the touch minimum. */
.mode-chip::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 50%;
  width: max(100%, var(--touch-min));
  height: max(100%, var(--touch-min));
  transform: translate(-50%, -50%);
}
</style>
