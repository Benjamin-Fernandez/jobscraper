<script setup>
// Settings -> Preferences (Q-116 design §2): what is kept in THIS browser only - the
// colour theme (Q-75 G40, theme.js), the Companies list's row density (density.js) and
// the keyboard shortcuts switch (shortcuts.js; the Inbox keys and "g" + a letter).
//
// The density and shortcuts switches have a second home where they act (Companies'
// "Compact rows" button, the Inbox's "Turn off" link). All of them read the same key and
// tell each other through a window event, so this page follows them (and they follow
// it) without a reload. The stored values are read again when the page is re-activated.
//
// Same commit rule as every radio row on the page (design §3): a click or Space saves
// at once, an arrow key only moves the choice, Enter or focus leaving the editor saves
// it, Esc drops it and closes the row. A switch saves on toggle. Nothing is sent to the
// server; "Saved" just confirms the change took.
import { nextTick, onActivated, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { DENSITY_EVENT, densityCompact, setDensityCompact } from '../density.js'
import { COPY, useRows } from '../settingsRows.js'
import { SHORTCUTS_EVENT, setShortcutsEnabled, shortcutsEnabled } from '../shortcuts.js'
import { THEMES, setTheme, storedTheme } from '../theme.js'
import SettingRow from './SettingRow.vue'
import SettingsGroup from './SettingsGroup.vue'

const props = defineProps({
  // The row id from the hash (`#/settings/preferences/<row-id>`), or null.
  item: { type: String, default: null },
})

const rows = useRows()

const theme = ref(storedTheme())
const compact = ref(densityCompact())
const shortcuts = ref(shortcutsEnabled())

function refresh() {
  theme.value = storedTheme()
  compact.value = densityCompact()
  shortcuts.value = shortcutsEnabled()
}

const themeLabel = id => THEMES.find(t => t.id === id)?.label ?? ''

// ---- colour theme ----
const pending = ref(null)          // an arrow-key choice waiting for Enter or blur
let arrowed = false
const shownTheme = () => pending.value ?? theme.value

function chooseTheme(id) {
  pending.value = null
  rows.clear('theme')
  if (id === theme.value) return
  theme.value = id
  setTheme(id)
  rows.flash('theme')
}
function onThemeChange(id) {
  if (arrowed) {
    arrowed = false
    pending.value = id === theme.value ? null : id
    rows.clear('theme')
  } else {
    chooseTheme(id)
  }
}
function commitTheme() {
  const id = pending.value
  pending.value = null
  if (id !== null) chooseTheme(id)
}
function onThemeKey(e) {
  if (e.key === 'Enter') {
    e.preventDefault()
    commitTheme()
  } else if (e.key === 'Escape') {
    e.stopPropagation()
    pending.value = null
    arrowed = false
    closeRow('theme')
  } else {
    arrowed = e.key.startsWith('Arrow')
  }
}
function onThemeFocusout(e) {
  if (!e.currentTarget.contains(e.relatedTarget)) commitTheme()
}

// ---- switches ----
function setCompact(on) {
  rows.clear('density')
  setDensityCompact(on)
  compact.value = densityCompact()
  rows.flash('density')
}
function setShortcuts(on) {
  rows.clear('shortcuts')
  setShortcutsEnabled(on)
  shortcuts.value = shortcutsEnabled()
  rows.flash('shortcuts')
}
// Another view (Companies, the Inbox) changed one while this page is open.
const onDensity = e => { compact.value = typeof e.detail?.on === 'boolean' ? e.detail.on : densityCompact() }
const onShortcuts = e => { shortcuts.value = typeof e.detail?.on === 'boolean' ? e.detail.on : shortcutsEnabled() }
window.addEventListener(DENSITY_EVENT, onDensity)
window.addEventListener(SHORTCUTS_EVENT, onShortcuts)
onBeforeUnmount(() => {
  window.removeEventListener(DENSITY_EVENT, onDensity)
  window.removeEventListener(SHORTCUTS_EVENT, onShortcuts)
})

// ---- rows opening and closing ----
const rowButton = id => document.querySelector(`#setting-${id} .setting-main`)

function closeRow(id) {
  rows.close()
  nextTick(() => rowButton(id)?.focus())
}
async function onToggle(id) {
  const opening = rows.open !== id
  rows.toggle(id)
  if (!opening) return
  await nextTick()
  document.querySelector(`#setting-${id}-editor input:checked`)?.focus()
}
watch(() => rows.open, () => {
  pending.value = null
  arrowed = false
})

// ---- deep link ----
const ROW_IDS = ['theme', 'density', 'shortcuts']
async function goTo() {
  const id = props.item
  if (!ROW_IDS.includes(id)) return
  if (id === 'theme') rows.open = id
  await nextTick()
  const button = rowButton(id)
  if (!button) return
  const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches
  button.scrollIntoView?.({ block: 'center', behavior: reduce ? 'auto' : 'smooth' })
  button.focus({ preventScroll: true })
}
watch(() => props.item, goTo, { immediate: true, flush: 'post' })

let shownOnce = false
onMounted(() => { shownOnce = true })
onActivated(() => {
  if (shownOnce) {
    shownOnce = false
    return
  }
  refresh()
})
</script>

<template>
  <div class="preferences">
    <p class="muted intro">Kept in this browser only.</p>

    <SettingsGroup :title="COPY.groups.display">
      <SettingRow
        id="theme"
        label="Colour theme"
        description="Light, dark, or match your device."
        :value="themeLabel(theme)"
        kind="edit"
        :open="rows.open === 'theme'"
        :saved="rows.saved.theme"
        :error="rows.error.theme"
        @toggle="onToggle('theme')"
      >
        <div class="editor" @keydown="onThemeKey" @focusout="onThemeFocusout">
          <div class="cycle-options" role="radiogroup" aria-labelledby="setting-theme-label" @pointerdown="arrowed = false">
            <label
              v-for="t in THEMES"
              :key="t.id"
              class="theme-option"
              :class="{ active: t.id === shownTheme() }"
              :data-choice="t.id"
            >
              <input
                type="radio"
                name="theme"
                class="visually-hidden"
                :value="t.id"
                :checked="t.id === shownTheme()"
                @change="onThemeChange(t.id)"
              >
              <span class="cycle-name">{{ t.label }}</span>
            </label>
          </div>
          <p v-if="pending !== null" class="hint theme-pending" role="status">
            {{ COPY.cyclePending(themeLabel(pending), themeLabel(theme).toLowerCase()) }}
          </p>
          <p class="muted small">System follows your device's light or dark setting.</p>
        </div>
      </SettingRow>
      <SettingRow
        id="density"
        label="Compact company list"
        description="Shows each company on one line in Companies."
        kind="switch"
        :checked="compact"
        :saved="rows.saved.density"
        :error="rows.error.density"
        @change="setCompact"
      />
    </SettingsGroup>

    <SettingsGroup :title="COPY.groups.keyboard">
      <SettingRow
        id="shortcuts"
        label="Keyboard shortcuts"
        description="Single-key actions in the Inbox and g + a letter to switch tabs. / and ? always work."
        kind="switch"
        :checked="shortcuts"
        :saved="rows.saved.shortcuts"
        :error="rows.error.shortcuts"
        @change="setShortcuts"
      />
    </SettingsGroup>
  </div>
</template>

<style scoped>
.intro { margin: 0 0 var(--space-3); font-size: var(--text-sm); }
.editor { display: grid; gap: var(--space-2); }
.hint { margin: 0; color: var(--text); font-size: var(--text-sm); }
.small { font-size: var(--text-sm); margin: 0; }
.cycle-options {
  display: flex; flex-wrap: wrap; gap: var(--space-1); padding: var(--space-1);
  background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--radius-lg);
}
.theme-option {
  flex: 1 1 5rem; display: flex; flex-direction: column; align-items: center; justify-content: center;
  min-height: var(--touch-min); padding: var(--space-2) var(--space-3); border-radius: var(--radius); cursor: pointer;
  border: 1px solid transparent; color: var(--text-2);
}
.theme-option:hover { background: var(--surface); }
.theme-option.active {
  background: var(--surface); border-color: var(--border); box-shadow: var(--shadow); color: var(--text);
}
.theme-option:has(input:focus-visible) { outline: 2px solid var(--focus); outline-offset: 2px; }
.cycle-name { font-weight: 600; font-size: var(--text-sm); }
</style>
