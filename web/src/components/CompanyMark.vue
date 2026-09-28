<script setup>
// A company's monogram tile (M13-T4): its initials on a colour derived from its
// name, so a company looks the same in the Inbox, the detail pane and the
// Applications list - the signature detail standing in for logos we do not
// have. Decorative: the company's name is always written next to it.
import { computed } from 'vue'
import { initials, hue } from '../marks.js'

const props = defineProps({
  name: { type: String, default: '' },
  size: { type: String, default: 'md' },   // sm | md | lg
})

const text = computed(() => initials(props.name))
const style = computed(() => ({ '--h': hue(props.name) }))
</script>

<template>
  <span class="mark" :class="size" :style="style" aria-hidden="true">{{ text }}</span>
</template>

<style scoped>
.mark {
  flex: none;
  display: inline-grid;
  place-items: center;
  width: 2.5rem;
  height: 2.5rem;
  border-radius: var(--radius);
  background: hsl(var(--h) var(--mark-bg-c) var(--mark-bg-l));
  color: hsl(var(--h) var(--mark-fg-c) var(--mark-fg-l));
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 0.95rem;
  letter-spacing: 0.02em;
  line-height: 1;
  user-select: none;
}
.mark.sm { width: 1.75rem; height: 1.75rem; font-size: 0.7rem; border-radius: var(--radius-sm); }
.mark.lg { width: 3.5rem; height: 3.5rem; font-size: 1.3rem; border-radius: var(--radius-lg); }
</style>
