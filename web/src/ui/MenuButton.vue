<script setup>
// A button that opens a menu of actions or a single choice (Q-118 design section 1, 8).
// The WAI-ARIA "menu button" pattern, built by hand (D-206: no component kit). The menu
// is drawn INLINE, right after the trigger, never teleported, so a test or a screen
// reader finds it where it belongs.
//
//   <MenuButton label="More actions for SRE at Flowdesk" :items="items" align="end"
//     trigger-class="ghost" @select="onPick"><Icon name="more" /></MenuButton>
//
// items: [{ id, label, checked?, disabled?, danger?, hint? }]. `kind`:
//   'menu'   (default) role=menuitem: actions.
//   'radio'  role=menuitemradio with aria-checked: one current choice (MoveMenu).
// `heading` (optional) is a small caption above the items ("Move to"). The trigger shows
// the default slot (its visible content; `label` when the slot is empty); `label` is its
// accessible name. `select(id)` is emitted when an enabled item is chosen; the menu then
// closes and focus returns to the trigger.
//
// Keyboard: Enter, Space or ArrowDown on the trigger opens and focuses the checked item
// (else the first); ArrowUp opens on the last. In the menu: Up/Down/Home/End move (wrapping),
// a letter jumps to the next item starting with it, Enter/Space choose, Esc closes and
// returns focus to the trigger, Tab closes, a click or focus outside closes. Disabled items
// are skipped. A disabled trigger keeps focus (aria-disabled, not `disabled`) and exposes
// `disabledReason` through aria-describedby and `title`. The panel flips upward when it
// would run past the viewport bottom (skipped where there is no layout, as in jsdom).
import { computed, nextTick, onBeforeUnmount, ref, useId } from 'vue'
import Icon from '../components/Icon.vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  label: { type: String, required: true },
  kind: { type: String, default: 'menu', validator: v => ['menu', 'radio'].includes(v) },
  align: { type: String, default: 'start', validator: v => ['start', 'end'].includes(v) },
  heading: { type: String, default: '' },
  triggerClass: { type: [String, Array, Object], default: '' },
  disabled: { type: Boolean, default: false },
  disabledReason: { type: String, default: '' },
})
const emit = defineEmits(['select'])

const uid = useId()
const triggerId = computed(() => `ui-menu-${uid}-trigger`)
const menuId = computed(() => `ui-menu-${uid}`)
const reasonId = computed(() => `ui-menu-${uid}-reason`)

const root = ref(null)
const trigger = ref(null)
const menu = ref(null)
const panel = ref(null)
const open = ref(false)
const flipUp = ref(false)

const itemRole = computed(() => (props.kind === 'radio' ? 'menuitemradio' : 'menuitem'))

function itemButtons() {
  return Array.from(menu.value?.querySelectorAll('[role^="menuitem"]') ?? [])
}
function enabledButtons() {
  return itemButtons().filter(b => !b.disabled)
}

// Keep the panel on screen: open upward when there is no room below and room above.
function placePanel() {
  flipUp.value = false
  const p = panel.value
  const t = trigger.value
  if (!p || !t || typeof window === 'undefined') return
  const pr = p.getBoundingClientRect()
  if (!pr.height) return // no layout (jsdom)
  // The phone's fixed bottom bar covers the lowest 3.5rem.
  const reserve = window.innerWidth <= 640 ? 72 : 8
  const tr = t.getBoundingClientRect()
  if (pr.bottom > window.innerHeight - reserve && tr.top - pr.height - 4 > 0) flipUp.value = true
}

async function openMenu(focus = 'first') {
  if (props.disabled || open.value) return
  open.value = true
  document.addEventListener('click', onOutside, true)
  document.addEventListener('focusin', onOutside, true)
  await nextTick()
  placePanel()
  const buttons = enabledButtons()
  if (!buttons.length) return
  if (focus === 'last') buttons[buttons.length - 1].focus()
  else (buttons.find(b => b.getAttribute('aria-checked') === 'true') ?? buttons[0]).focus()
}

function closeMenu(returnFocus = false) {
  if (!open.value) return
  open.value = false
  document.removeEventListener('click', onOutside, true)
  document.removeEventListener('focusin', onOutside, true)
  if (returnFocus) nextTick(() => trigger.value?.focus())
}

function onOutside(event) {
  if (root.value && !root.value.contains(event.target)) closeMenu()
}
onBeforeUnmount(() => closeMenu())

function onTriggerClick() {
  if (props.disabled) return
  if (open.value) closeMenu()
  else openMenu('first')
}

function onTriggerKeydown(event) {
  if (props.disabled) return
  if (event.key === 'ArrowDown' || event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    openMenu('first')
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    openMenu('last')
  } else if (event.key === 'Escape' && open.value) {
    event.preventDefault()
    closeMenu(true)
  }
}
// Space activates a button on keyup; swallow it so it cannot toggle the menu again.
function onTriggerKeyup(event) {
  if (event.key === ' ') event.preventDefault()
}

function choose(item) {
  if (!item || item.disabled) return
  closeMenu(true)
  emit('select', item.id)
}

let typed = ''
let typedTimer = null
function onMenuKeydown(event) {
  const buttons = enabledButtons()
  const at = buttons.indexOf(document.activeElement)
  const go = i => { if (buttons.length) buttons[(i + buttons.length) % buttons.length].focus() }
  switch (event.key) {
    case 'ArrowDown': event.preventDefault(); go(at + 1); return
    case 'ArrowUp': event.preventDefault(); go(at < 0 ? -1 : at - 1); return
    case 'Home': event.preventDefault(); go(0); return
    case 'End': event.preventDefault(); go(buttons.length - 1); return
    case 'Escape':
      event.preventDefault()
      event.stopPropagation()
      closeMenu(true)
      return
    case 'Tab': closeMenu(); return
    case 'Enter':
    case ' ': {
      event.preventDefault()
      const index = itemButtons().indexOf(document.activeElement)
      if (index >= 0) choose(props.items[index])
      return
    }
    default:
  }
  // Type-ahead: a letter jumps to the next item that starts with it.
  if (event.key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
    typed = (typed + event.key).toLowerCase()
    clearTimeout(typedTimer)
    typedTimer = setTimeout(() => { typed = '' }, 600)
    const labels = buttons.map(b => (b.textContent || '').trim().toLowerCase())
    const rotated = [...labels.keys()].map(k => (at + 1 + k) % labels.length)
    const hit = rotated.find(i => labels[i].startsWith(typed)) ?? rotated.find(i => labels[i].startsWith(event.key.toLowerCase()))
    if (hit !== undefined) buttons[hit].focus()
  }
}

defineExpose({ focus: () => trigger.value?.focus(), close: () => closeMenu(true) })
</script>

<template>
  <span ref="root" class="ui-menu-wrap">
    <button
      :id="triggerId"
      ref="trigger"
      type="button"
      class="ui-menu-trigger"
      :class="[triggerClass, { 'is-disabled': disabled, 'is-open': open }]"
      aria-haspopup="menu"
      :aria-expanded="String(open)"
      :aria-controls="menuId"
      :aria-label="label"
      :aria-disabled="disabled ? 'true' : undefined"
      :aria-describedby="disabled && disabledReason ? reasonId : undefined"
      :title="disabled && disabledReason ? disabledReason : undefined"
      @click="onTriggerClick"
      @keydown="onTriggerKeydown"
      @keyup="onTriggerKeyup"
    >
      <slot name="trigger" :open="open">{{ label }}</slot>
    </button>
    <span v-if="disabled && disabledReason" :id="reasonId" class="visually-hidden">{{ disabledReason }}</span>
    <div
      v-if="open"
      ref="panel"
      class="ui-menu-panel"
      :class="[`align-${align}`, { 'is-up': flipUp }]"
    >
      <p v-if="heading" class="ui-menu-heading" aria-hidden="true">{{ heading }}</p>
      <ul :id="menuId" ref="menu" class="ui-menu" role="menu" :aria-labelledby="triggerId" @keydown="onMenuKeydown">
        <li v-for="item in items" :key="item.id" role="none">
          <button
            type="button"
            class="ui-menu-item"
            :class="{ 'is-danger': item.danger, 'is-checked': kind === 'radio' && item.checked }"
            :role="itemRole"
            :aria-checked="kind === 'radio' ? String(Boolean(item.checked)) : undefined"
            :aria-disabled="item.disabled ? 'true' : undefined"
            :disabled="item.disabled || undefined"
            tabindex="-1"
            @click="choose(item)"
          >
            <span v-if="kind === 'radio'" class="ui-menu-check"><Icon v-if="item.checked" name="check" :size="14" /></span>
            <span class="ui-menu-label">{{ item.label }}</span>
            <span v-if="item.hint" class="ui-menu-hint">{{ item.hint }}</span>
          </button>
        </li>
      </ul>
    </div>
  </span>
</template>

<style scoped>
.ui-menu-wrap { position: relative; display: inline-flex; min-width: 0; }
.ui-menu-trigger.is-disabled { opacity: 0.5; cursor: not-allowed; }

.ui-menu-panel {
  position: absolute;
  top: calc(100% + 4px);
  z-index: 30;
  min-width: max(100%, 11rem);
  max-width: min(22rem, calc(100vw - 2 * var(--gutter)));
  padding: var(--space-1);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-md);
  animation: ui-menu-in var(--motion) var(--ease-out);
}
.ui-menu-panel.align-start { left: 0; }
.ui-menu-panel.align-end { right: 0; }
.ui-menu-panel.is-up { top: auto; bottom: calc(100% + 4px); }
@keyframes ui-menu-in { from { opacity: 0; } }

.ui-menu-heading {
  margin: 0;
  padding: var(--space-1) var(--space-3);
  font-size: var(--text-xs);
  font-weight: var(--weight-semibold);
  color: var(--muted);
}
.ui-menu { list-style: none; margin: 0; padding: 0; }

.ui-menu-item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  width: 100%;
  min-height: 2.25rem;
  padding: 0 var(--space-3);
  font-weight: var(--weight-medium);
  text-align: left;
  color: var(--text);
  background: transparent;
  border: 0;
  border-radius: var(--radius-sm);
  box-shadow: none;
}
.ui-menu-item:hover:not(:disabled), .ui-menu-item:focus-visible { background: var(--surface-2); }
/* The panel is small and bordered; the ring sits inside the item. */
.ui-menu-item:focus-visible { outline-offset: -2px; }
.ui-menu-item:disabled { cursor: default; opacity: 0.55; }
.ui-menu-item.is-checked { font-weight: var(--weight-semibold); opacity: 1; }
.ui-menu-item.is-danger { color: var(--danger); }
.ui-menu-item.is-danger:hover:not(:disabled), .ui-menu-item.is-danger:focus-visible { background: var(--danger-soft); }
.ui-menu-check { flex: none; display: inline-flex; width: 14px; color: var(--accent); }
.ui-menu-label { flex: 1 1 auto; min-width: 0; white-space: nowrap; }
.ui-menu-hint { flex: none; margin-left: var(--space-3); font-size: var(--text-xs); font-weight: 400; color: var(--muted); }

@media (max-width: 640px) {
  .ui-menu-item { min-height: var(--touch-min); }
}
@media (prefers-reduced-motion: reduce) {
  .ui-menu-panel { animation: none; }
}
</style>
