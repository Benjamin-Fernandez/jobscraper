<script setup>
// One row of Profile -> Your details (Q-127 U1, D-215; design B.4): the title over a one-line
// summary, what it still needs on the right, a chevron; it opens in place and holds the
// section's fields (the default slot, the markup ApplicationDetails has always drawn).
//
// The row only shows and reports. The page owns the draft, the save and the "one open at a
// time" rule; this component owns the accessible shape of a row:
//   * a heading that holds a <button aria-expanded aria-controls>, so a screen reader lists
//     the ten sections as headings and a keyboard user opens one with Enter or Space;
//   * the status in words ("Needed", "2 to fill", "Complete", "Fix 1", "Unsaved changes"),
//     never colour alone;
//   * saving: the panel is aria-busy and its controls are disabled;
//   * an in-row confirm when the owner leaves the section with unsaved edits;
//   * Save section / Cancel, sticky above the bottom bar on a phone so the buttons stay in
//     reach (the page gives each field a scroll margin so the bar never covers the focused one).
// The `notice` slot sits under the row whether or not it is open: the "Saved. n applications
// were waiting" notice stays until the owner dismisses it.
import Icon from './Icon.vue'

defineProps({
  id: { type: String, required: true },
  title: { type: String, required: true },
  summary: { type: String, default: '' },
  open: { type: Boolean, default: false },
  // {text, tone}: tone is a ui-badge tone (warn / neutral / ok).
  status: { type: Object, default: () => ({ text: '', tone: 'neutral' }) },
  fixText: { type: String, default: '' },
  dirty: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  canSave: { type: Boolean, default: true },
  // The owner clicked away from a dirty section: ask here, in the row being left.
  confirming: { type: Boolean, default: false },
})
const emit = defineEmits(['toggle', 'save', 'cancel', 'confirm-save', 'confirm-discard', 'keep-editing'])
</script>

<template>
  <section class="detail-section" :class="{ open }" :data-section="id" :aria-labelledby="`ds-${id}-title`">
    <h3 class="ds-heading">
      <button
        :id="`ds-${id}-button`"
        type="button"
        class="ds-toggle"
        :aria-expanded="open ? 'true' : 'false'"
        :aria-controls="`ds-${id}-panel`"
        @click="emit('toggle')"
      >
        <span :id="`ds-${id}-title`" class="ds-title">{{ title }}</span>
        <span class="ds-summary">{{ summary }}</span>
        <span class="ds-meta">
          <span v-if="dirty" class="ui-badge ds-unsaved" data-tone="info">Unsaved changes</span>
          <span v-if="fixText" class="ui-badge ds-fix" data-tone="danger">{{ fixText }}</span>
          <span class="ui-badge ds-status" :data-tone="status.tone">{{ status.text }}</span>
        </span>
        <Icon name="chevron" :size="18" class="ds-chevron" />
      </button>
    </h3>

    <div v-if="confirming" class="ds-confirm" role="group" :aria-labelledby="`ds-${id}-confirm`">
      <p :id="`ds-${id}-confirm`">Save your changes to {{ title }}?</p>
      <div class="ds-confirm-buttons">
        <button type="button" class="primary ds-confirm-save" :disabled="saving" @click="emit('confirm-save')">Save</button>
        <button type="button" class="ds-confirm-discard" :disabled="saving" @click="emit('confirm-discard')">Discard changes</button>
        <button type="button" class="ghost ds-confirm-keep" :disabled="saving" @click="emit('keep-editing')">Keep editing</button>
      </div>
    </div>

    <slot name="notice" />

    <div
      v-if="open"
      :id="`ds-${id}-panel`"
      class="ds-panel"
      role="region"
      :aria-labelledby="`ds-${id}-title`"
      :aria-busy="saving ? 'true' : 'false'"
    >
      <form class="ds-form" novalidate @submit.prevent="emit('save')">
        <fieldset class="ds-fields" :disabled="saving">
          <legend class="visually-hidden">{{ title }}</legend>
          <slot />
        </fieldset>
        <div class="ds-actions">
          <button type="button" class="ghost ds-cancel" :disabled="saving" @click="emit('cancel')">Cancel</button>
          <button type="submit" class="primary ds-save" :disabled="saving || !canSave">{{ saving ? 'Saving…' : 'Save section' }}</button>
        </div>
      </form>
    </div>
  </section>
</template>

<style scoped>
.detail-section { min-width: 0; }
.detail-section + .detail-section { border-top: 1px solid var(--border); }
.ds-heading { margin: 0; font: inherit; }
.ds-toggle {
  display: grid; grid-template-columns: minmax(0, 1fr) auto auto; align-items: center; column-gap: var(--space-3);
  grid-template-areas: "title meta chev" "summary meta chev";
  width: 100%; min-height: 3.5rem; padding: var(--space-3) var(--space-4);
  border: 0; border-radius: 0; background: transparent; color: inherit; text-align: left; cursor: pointer;
  font: inherit;
}
.ds-toggle:hover { background: var(--surface-2); }
.ds-toggle:focus-visible { outline: 2px solid var(--focus); outline-offset: -2px; }
.ds-title { grid-area: title; font-size: var(--text-sm); font-weight: var(--weight-semibold); overflow-wrap: anywhere; }
.ds-summary { grid-area: summary; font-size: var(--text-sm); color: var(--muted); overflow-wrap: anywhere; }
.ds-meta { grid-area: meta; display: inline-flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: var(--space-2); }
.ds-chevron { grid-area: chev; transition: transform var(--motion); color: var(--muted); }
.open .ds-chevron { transform: rotate(180deg); }
@media (prefers-reduced-motion: reduce) { .ds-chevron { transition: none; } }

.ds-confirm {
  display: grid; gap: var(--space-2); margin: 0 var(--space-4) var(--space-3); padding: var(--space-3);
  background: var(--warn-soft); border-radius: var(--radius);
}
.ds-confirm p { margin: 0; font-size: var(--text-sm); font-weight: var(--weight-semibold); }
.ds-confirm-buttons { display: flex; flex-wrap: wrap; gap: var(--space-2); }

.ds-panel { padding: var(--space-2) var(--space-4) var(--space-4); min-width: 0; }
.ds-form { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-4); min-width: 0; }
.ds-fields { margin: 0; padding: 0; border: 0; min-width: 0; display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-4); }
.ds-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--space-2) var(--space-3); }

/* A phone: the buttons stick above the bottom bar (Q-100 A14; --bottom-nav-h is 0 wider),
   44px targets, and the fields keep a scroll margin so the bar never covers the focused one. */
@media (max-width: 639px) {
  .ds-toggle {
    grid-template-columns: minmax(0, 1fr) auto; row-gap: var(--space-1); padding: var(--space-3); min-height: var(--touch-min);
    grid-template-areas: "title chev" "meta meta" "summary summary";
  }
  .ds-meta { justify-content: flex-start; }
  .ds-panel { padding: var(--space-2) var(--space-3) var(--space-3); }
  .ds-actions {
    position: sticky; bottom: calc(var(--bottom-nav-h) + env(safe-area-inset-bottom, 0px)); z-index: 5;
    padding: var(--space-2) var(--space-3); background: var(--surface);
    border: 1px solid var(--border); border-radius: var(--radius-lg); box-shadow: var(--shadow);
  }
  .ds-actions button, .ds-confirm-buttons button { min-height: var(--touch-min); }
}
</style>
