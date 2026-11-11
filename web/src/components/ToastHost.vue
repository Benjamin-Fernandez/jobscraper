<script setup>
// Where the toast appears (M13-T2): bottom centre, over the page. The region is
// always in the DOM so screen readers hear each new message (aria-live).
// H1-4: hover or focus inside it pauses its timer; "Undo previous" runs the
// Undo of the toast it replaced, and leaves this one up.
// Q-100 (A14): under 640px it sits above the bottom bar (--bottom-nav-h is 0 wider).
import { nextTick, ref } from 'vue'
import { dismissToast, dropPrevious, pauseToast, resumeToast, toast } from '../toast.js'
import Icon from './Icon.vue'

const box = ref(null)

async function act(t) {
  dismissToast(t.id)
  await t.action.run()
}

// Runs once however fast it is pressed: a second click before the re-render
// finds `previous` already gone. Focus moves to the toast's own Undo, rather
// than falling to the page when this button disappears.
async function actPrevious(t) {
  if (!t?.previous) return
  const { action } = t.previous
  dropPrevious(t.id)
  await nextTick()
  box.value?.querySelector('.toast-action, .toast-close')?.focus()
  await action.run()
}
</script>

<template>
  <div class="toast-region" role="status" aria-live="polite">
    <Transition name="toast">
      <div
        v-if="toast.current"
        :key="toast.current.id"
        ref="box"
        class="toast"
        @mouseenter="pauseToast('hover')"
        @mouseleave="resumeToast('hover')"
        @focusin="pauseToast('focus')"
        @focusout="resumeToast('focus')"
      >
        <span class="message">{{ toast.current.message }}</span>
        <button
          v-if="toast.current.action"
          type="button"
          class="toast-action"
          @click="act(toast.current)"
        >
          <Icon name="undo" :size="15" />{{ toast.current.action.label }}
        </button>
        <button
          v-if="toast.current.previous"
          type="button"
          class="toast-previous"
          :aria-label="`Undo previous: ${toast.current.previous.message}`"
          @click="actPrevious(toast.current)"
        >Undo previous</button>
        <a
          v-if="toast.current.link"
          class="toast-link"
          :href="toast.current.link.href"
          @click="dismissToast(toast.current.id)"
        >{{ toast.current.link.label }}</a>
        <button type="button" class="toast-close" aria-label="Close" @click="dismissToast(toast.current.id)">
          <Icon name="x" :size="15" />
        </button>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.toast-region {
  position: fixed;
  left: 50%;
  bottom: calc(var(--space-5) + var(--bottom-nav-h) + env(safe-area-inset-bottom, 0px));
  transform: translateX(-50%);
  z-index: 50;
  width: max-content;
  max-width: calc(100vw - 2 * var(--gutter));
}
.toast {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  padding: var(--space-2) var(--space-2) var(--space-2) var(--space-4);
  background: var(--text);
  color: var(--bg);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  font-size: var(--text-sm);
}
.message { min-width: 0; overflow-wrap: anywhere; }
.toast-action, .toast-close, .toast-previous {
  min-height: 2rem;
  padding: 0 var(--space-2);
  background: transparent;
  border: none;
  box-shadow: none;
  color: var(--bg);
  font-weight: 650;
}
.toast-action { color: color-mix(in srgb, var(--accent) 55%, var(--bg)); }
.toast-previous { font-weight: 500; opacity: 0.85; white-space: nowrap; }
.toast-action:hover:not(:disabled), .toast-close:hover:not(:disabled), .toast-previous:hover:not(:disabled) {
  background: color-mix(in srgb, var(--bg) 14%, transparent);
  color: var(--bg);
}
.toast-link { color: var(--bg); font-weight: 650; white-space: nowrap; }
.toast-link:hover { color: var(--bg); }
.toast-close { opacity: 0.7; }
.toast-enter-active, .toast-leave-active { transition: opacity 0.18s, transform 0.18s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(8px); }
</style>
