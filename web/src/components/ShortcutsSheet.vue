<script setup>
// The "?" sheet (Q-75 N16, G3r): every key the app answers to, in one dialog.
// A modal dialog (role="dialog", aria-modal): focus goes in when it opens, Tab
// cycles inside it, Esc or "?" or a click on the backdrop closes it, and focus
// returns to where it was. The shell marks the page behind it `inert`. While
// the dialog is up it listens on the window (capture) and stops every key from
// reaching the page's own shortcuts, so pressing S here never saves a role, and
// Esc works wherever the focus has landed (a click on the text, say).
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { INBOX_KEYS, setShortcutsEnabled, shortcutsEnabled } from '../shortcuts.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  // [{ key, label }] - the go-to keys, from the tab registry.
  goKeys: { type: Array, default: () => [] },
})
const emit = defineEmits(['close'])

const dialog = ref(null)
const closeBtn = ref(null)
const singleKeys = ref(true)
let returnTo = null

function listen(on) {
  window[on ? 'addEventListener' : 'removeEventListener']('keydown', onKey, true)
}
onBeforeUnmount(() => listen(false))

watch(() => props.open, async now => {
  listen(now)
  if (now) {
    returnTo = document.activeElement
    singleKeys.value = shortcutsEnabled()
    await nextTick()
    closeBtn.value?.focus()
  } else if (returnTo) {
    const el = returnTo
    returnTo = null
    if (el.isConnected && typeof el.focus === 'function') el.focus()
  }
})

function toggleSingle() {
  singleKeys.value = !singleKeys.value
  setShortcutsEnabled(singleKeys.value)
}

function focusables() {
  return [...(dialog.value?.querySelectorAll('button, input, [href], [tabindex]:not([tabindex="-1"])') ?? [])]
    .filter(el => !el.disabled)
}

function onKey(event) {
  if (event.key === 'Escape' || (event.key === '?' && !event.ctrlKey && !event.metaKey && !event.altKey)) {
    event.preventDefault()
    emit('close')
  } else if (event.key === 'Tab') {
    const list = focusables()
    if (!list.length) return
    const first = list[0]
    const last = list[list.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }
  // Nothing typed in here is a shortcut for the page behind.
  event.stopPropagation()
}
</script>

<template>
  <div v-if="open" class="sheet-backdrop" @mousedown.self="emit('close')">
    <div
      ref="dialog"
      class="sheet"
      role="dialog"
      aria-modal="true"
      aria-labelledby="sheet-title"
    >
      <header class="sheet-head">
        <h2 id="sheet-title">Keyboard shortcuts</h2>
        <button ref="closeBtn" type="button" class="ghost sheet-close" @click="emit('close')">Close</button>
      </header>

      <h3 class="sheet-group">Anywhere</h3>
      <dl class="keys">
        <div><dt><kbd>?</kbd></dt><dd>Show this list</dd></div>
        <div><dt><kbd>/</kbd></dt><dd>Search the open tab</dd></div>
        <div v-for="g in goKeys" :key="g.id">
          <dt><kbd>g</kbd> then <kbd>{{ g.key }}</kbd></dt>
          <dd>Go to {{ g.label }}</dd>
        </div>
      </dl>

      <h3 class="sheet-group">In the Inbox</h3>
      <dl class="keys">
        <div v-for="k in INBOX_KEYS" :key="k.label">
          <dt><template v-for="(key, i) in k.keys" :key="key"><template v-if="i"> </template><kbd>{{ key }}</kbd></template></dt>
          <dd>{{ k.label }}</dd>
        </div>
      </dl>

      <label class="sheet-switch">
        <input type="checkbox" :checked="singleKeys" @change="toggleSingle">
        <span>Use single-key shortcuts</span>
      </label>
      <p class="sheet-note muted">
        Turn this off if speech input or an assistive tool presses them by mistake. <kbd>?</kbd> and <kbd>/</kbd> keep working.
      </p>
    </div>
  </div>
</template>

<style scoped>
.sheet-backdrop {
  position: fixed;
  inset: 0;
  z-index: 40;
  display: grid;
  place-items: center;
  padding: var(--space-4);
  background: rgba(10, 10, 14, 0.5);
}
.sheet {
  width: min(32rem, 100%);
  max-height: 100%;
  overflow-y: auto;
  padding: var(--space-4) var(--space-5) var(--space-5);
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
}
.sheet-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-3); }
.sheet-head h2 { margin: 0; font-size: var(--text-lg); }
.sheet-close { min-height: 2rem; min-width: 2rem; }
.sheet-group {
  margin: var(--space-4) 0 var(--space-2);
  font-size: var(--text-xs);
  font-weight: 650;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--muted);
}
.keys { margin: 0; display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-1); }
.keys > div { display: grid; grid-template-columns: minmax(7rem, 9rem) minmax(0, 1fr); gap: var(--space-3); align-items: baseline; }
.keys dt { white-space: nowrap; }
.keys dd { margin: 0; font-size: var(--text-sm); }
kbd {
  display: inline-block; min-width: 1.4em; padding: 0 0.35em; text-align: center;
  font-family: var(--mono); font-size: 0.75rem; line-height: 1.6;
  color: var(--text); background: var(--surface-2);
  border: 1px solid var(--border-strong); border-bottom-width: 2px; border-radius: 4px;
}
.sheet-switch {
  display: flex; align-items: center; gap: var(--space-2);
  margin-top: var(--space-4); min-height: 1.5rem; font-size: var(--text-sm);
}
.sheet-switch input { width: 1.1rem; height: 1.1rem; flex: none; }
.sheet-note { margin: var(--space-1) 0 0; font-size: var(--text-xs); }
</style>
