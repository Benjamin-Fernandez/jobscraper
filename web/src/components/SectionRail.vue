<script setup>
// Profile -> Your details: the form's sections as a list to jump around a long
// page (Q71-13). Beside the form on a wide screen (sticky), a row of chips above
// it on a narrow one. Each section says what it still needs: "2 needed",
// "1 to fix", or a check mark when nothing is needed. The caller owns the
// counts and the scrolling (`go`); `current` is the section on screen.
import Icon from './Icon.vue'
import { sectionStatus } from '../applicantForm.js'

defineProps({
  sections: { type: Array, default: () => [] },     // [{id, title, needed, toFix}]
  current: { type: String, default: '' },
})
const emit = defineEmits(['go'])
</script>

<template>
  <nav class="rail" aria-label="Sections">
    <ul>
      <li v-for="s in sections" :key="s.id">
        <button
          type="button"
          class="rail-link"
          :class="{ current: s.id === current }"
          :data-section="s.id"
          :aria-current="s.id === current ? 'true' : undefined"
          @click="emit('go', s.id)"
        >
          <span class="rail-title">{{ s.title }}</span>
          <span v-if="sectionStatus(s).tone !== 'done'" class="tag" :class="sectionStatus(s).tone">{{ sectionStatus(s).text }}</span>
          <span v-else class="done"><Icon name="check" :size="14" /><span class="visually-hidden">{{ sectionStatus(s).text }}</span></span>
        </button>
      </li>
    </ul>
  </nav>
</template>

<style scoped>
.rail ul { list-style: none; margin: 0; padding: 0; }
.rail-link {
  width: 100%; justify-content: space-between; gap: var(--space-2);
  min-height: 2rem; padding: var(--space-1) var(--space-2);
  border-color: transparent; background: transparent; box-shadow: none;
  color: var(--text-2); font-weight: 500; text-align: left; white-space: normal;
}
.rail-link:hover:not(:disabled) { background: var(--surface-2); color: var(--text); }
.rail-link.current { background: var(--surface); border-color: var(--border-strong); color: var(--text); font-weight: 650; }
.rail-title { min-width: 0; }
.done { display: inline-flex; color: var(--ok); }
.tag.needed { color: var(--warn); background: var(--warn-soft); border-color: color-mix(in srgb, var(--warn) 35%, transparent); }
.tag.fix { color: var(--danger); background: var(--danger-soft); border-color: color-mix(in srgb, var(--danger) 35%, transparent); }

/* Narrow: one row of chips that scrolls sideways inside the nav. The nav never
   takes its width from the chips (min-width: 0), so the page doesn't scroll. */
/* position: relative makes the rail the containing block of the chips'
   visually-hidden (absolute) text, so the scroller clips it too; otherwise it
   escaped and widened the page at 390px. Wide screens replace it with sticky,
   which is a containing block as well. */
.rail { position: relative; min-width: 0; max-width: 100%; }
@media (max-width: 899px) {
  .rail { overflow-x: auto; overscroll-behavior-x: contain; scroll-snap-type: x proximity; padding-bottom: var(--space-1); }
  .rail ul { display: flex; flex-wrap: nowrap; gap: var(--space-1); width: max-content; }
  .rail li { flex: none; scroll-snap-align: start; }
  .rail-link {
    width: auto; white-space: nowrap; min-height: 2rem;
    border-color: var(--border); background: var(--surface); border-radius: 999px;
  }
}
/* Wide: a column beside the form that stays in view. */
@media (min-width: 900px) {
  .rail {
    position: sticky; top: calc(var(--header-h) + var(--space-4));
    max-height: calc(100vh - var(--header-h) - var(--space-6)); overflow-y: auto;
  }
  .rail ul { display: grid; gap: 2px; }
}
</style>
