<script setup>
// One setting as a row (Q-116 design §3, §6, §7 "SettingRow contract"). The whole row
// is the hit target; what it does depends on `kind`:
//
//   edit    a `button aria-expanded aria-controls`; emits `toggle`. The editor (default
//           slot) sits under the row inside the card, only while `open`.
//   switch  a `button role="switch" aria-checked`; emits `change(!checked)`. On/Off is
//           written out, so state never rests on colour alone.
//   link    an `a` to `href`, named "{label}, {linkText}".
//   static  plain text; nothing to click.
//
// `readOnly` (the server said `writable` is not true) turns edit and switch rows into
// static ones: no chevron, no switch, the value as text, and the description gains
// " Set in config.yaml.". Link rows still link.
//
// State words come from the caller (see settingsRows.js `useRows()`): `busy` sets
// `aria-busy` and disables the control, `saved` shows "Saved" with a check in a
// `role="status"` span, `error` shows under the row as a `role="alert"`. `saved` may be
// a string: extra words that are announced to screen readers but not shown ("The next
// run uses it."). Theme tokens only, so light and dark both work.
//
//   <SettingRow id="daily-cap" label="Applications a day" description="..."
//     :value="capLabel(n, { daily: true })" kind="edit" :open="rows.open === 'daily-cap'"
//     :busy="rows.busy['daily-cap']" :saved="rows.saved['daily-cap']"
//     :error="rows.error['daily-cap']" :read-only="!writable" @toggle="rows.toggle('daily-cap')">
//     ...the editor...
//   </SettingRow>
import { computed, ref } from 'vue'
import Icon from './Icon.vue'
import { READ_ONLY_SUFFIX, SAVED_TEXT } from '../settingsRows.js'

const props = defineProps({
  id: { type: String, required: true },
  label: { type: String, required: true },
  description: { type: String, default: '' },
  // The value shown at the right ("Dry run", "No daily limit"). A switch shows On/Off
  // from `checked` when this is empty. The `value` slot replaces it (a StateChip).
  value: { type: String, default: '' },
  kind: { type: String, default: 'static', validator: v => ['edit', 'switch', 'link', 'static'].includes(v) },
  checked: { type: Boolean, default: false },
  href: { type: String, default: '' },
  linkText: { type: String, default: '' },
  open: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
  saved: { type: [Boolean, String], default: false },
  error: { type: String, default: '' },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['toggle', 'change'])

const rowId = computed(() => `setting-${props.id}`)
const labelId = computed(() => `${rowId.value}-label`)
const descId = computed(() => `${rowId.value}-desc`)
const valueId = computed(() => `${rowId.value}-value`)
const linkId = computed(() => `${rowId.value}-link`)
const errorId = computed(() => `${rowId.value}-error`)
const editorId = computed(() => `${rowId.value}-editor`)

// What the row does. A read-only edit or switch row is just text.
const mode = computed(() => {
  if (props.kind === 'link') return 'link'
  if (props.readOnly || props.kind === 'static') return 'static'
  return props.kind
})
const showChevron = computed(() => mode.value === 'edit' || mode.value === 'link')

const valueText = computed(() => {
  if (props.value) return props.value
  return props.kind === 'switch' ? (props.checked ? 'On' : 'Off') : ''
})
const descriptionText = computed(() => {
  if (!props.readOnly) return props.description
  return props.description ? `${props.description}${READ_ONLY_SUFFIX}` : READ_ONLY_SUFFIX.trim()
})

// A control is named by its label and (for edit and switch) its value; the description
// and any error describe it.
const labelledBy = computed(() => {
  if (mode.value === 'link') return props.linkText ? `${labelId.value} ${linkId.value}` : labelId.value
  return `${labelId.value} ${valueId.value}`
})
const describedBy = computed(() => {
  const ids = []
  if (descriptionText.value) ids.push(descId.value)
  if (props.error) ids.push(errorId.value)
  return ids.join(' ') || undefined
})

const savedWords = computed(() => {
  const extra = typeof props.saved === 'string' ? ` ${props.saved}` : ''
  return `: ${props.label}, ${valueText.value}.${extra}`
})

const control = ref(null)
function onClick() {
  if (props.busy) return
  if (mode.value === 'edit') emit('toggle')
  else if (mode.value === 'switch') emit('change', !props.checked)
}
// Moves focus to the row's control (a hash row id, or Esc from an editor).
defineExpose({ focus: () => control.value?.focus() })
</script>

<template>
  <div
    :id="rowId"
    class="setting"
    :class="{ open, busy, [`kind-${mode}`]: true }"
  >
    <div class="setting-line">
      <component
        :is="mode === 'link' ? 'a' : mode === 'static' ? 'div' : 'button'"
        ref="control"
        class="setting-main"
        :type="mode === 'edit' || mode === 'switch' ? 'button' : undefined"
        :href="mode === 'link' ? href : undefined"
        :role="mode === 'switch' ? 'switch' : undefined"
        :aria-checked="mode === 'switch' ? String(checked) : undefined"
        :aria-expanded="mode === 'edit' ? String(open) : undefined"
        :aria-controls="mode === 'edit' ? editorId : undefined"
        :aria-labelledby="mode === 'static' ? undefined : labelledBy"
        :aria-describedby="mode === 'static' ? undefined : describedBy"
        :aria-busy="busy ? 'true' : undefined"
        :disabled="busy && (mode === 'edit' || mode === 'switch') ? true : undefined"
        @click="onClick"
      >
        <span class="setting-text">
          <span :id="labelId" class="setting-label">{{ label }}</span>
          <span v-if="descriptionText" :id="descId" class="setting-desc">{{ descriptionText }}</span>
        </span>
        <span class="setting-side">
          <span :id="valueId" class="setting-value">
            <slot name="value">{{ valueText }}</slot>
          </span>
          <span v-if="mode === 'link' && linkText" :id="linkId" class="setting-link-text">{{ linkText }}</span>
          <span v-if="mode === 'switch'" class="setting-track" :class="{ on: checked }" aria-hidden="true">
            <span class="setting-thumb" />
          </span>
          <Icon v-if="showChevron" class="setting-chevron" :class="{ open: mode === 'edit' && open }" name="chevron" :size="16" />
        </span>
      </component>
      <span v-if="saved" class="setting-saved" role="status">
        <Icon name="check" :size="14" />{{ SAVED_TEXT }}<span class="visually-hidden">{{ savedWords }}</span>
      </span>
    </div>
    <p v-if="error" :id="errorId" class="setting-error" role="alert">{{ error }}</p>
    <div
      v-if="mode === 'edit' && open && $slots.default"
      :id="editorId"
      class="setting-editor"
      role="group"
      :aria-labelledby="labelId"
    >
      <slot />
    </div>
  </div>
</template>

<style scoped>
.setting {
  /* Lets the value drop under the description when the row is narrow (below). */
  container-type: inline-size;
  background: var(--surface);
}
/* Rows in one card are separated by a 1px border (SettingsGroup holds only the frame). */
.setting + .setting { border-top: 1px solid var(--border); }
.setting-line { display: flex; align-items: stretch; }

.setting-main {
  flex: 1 1 auto;
  min-width: 0;
  min-height: 3.5rem;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  column-gap: var(--space-4);
  box-sizing: border-box;
  padding: var(--space-3) var(--space-4);
  margin: 0;
  background: transparent;
  border: 0;
  border-radius: 0;
  color: var(--text);
  font: inherit;
  text-align: left;
  text-decoration: none;
}
button.setting-main, a.setting-main { cursor: pointer; }
button.setting-main:hover:not(:disabled), a.setting-main:hover { background: var(--surface-2); color: var(--text); }
button.setting-main:disabled { cursor: progress; color: var(--text); opacity: 0.7; }
/* The card clips its children, so the ring sits inside the row. */
.setting-main:focus-visible { outline-offset: -2px; border-radius: 0; }

.setting-text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.setting-label { font-size: var(--text-sm); font-weight: 600; }
.setting-desc { font-size: var(--text-sm); color: var(--muted); overflow-wrap: anywhere; }

.setting-side { display: inline-flex; align-items: center; gap: var(--space-2); color: var(--text-2); font-size: var(--text-sm); }
.setting-value { text-align: right; }
.setting-link-text { color: var(--accent); font-weight: 600; }
.setting-chevron { color: var(--muted); transform: rotate(-90deg); transition: transform 0.15s ease; }
.setting-chevron.open { transform: rotate(0deg); }

.setting-track {
  position: relative;
  flex: none;
  width: 2.25rem;
  height: 1.375rem;
  border-radius: 999px;
  background: var(--border-strong);
  transition: background-color 0.15s ease;
}
.setting-track.on { background: var(--accent); }
.setting-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: calc(1.375rem - 4px);
  height: calc(1.375rem - 4px);
  border-radius: 50%;
  background: var(--surface);
  transition: transform 0.15s ease;
}
.setting-track.on .setting-thumb { transform: translateX(0.875rem); }

.setting-saved {
  flex: none;
  display: inline-flex;
  align-items: center;
  gap: var(--space-1);
  align-self: center;
  padding-right: var(--space-4);
  font-size: var(--text-sm);
  color: var(--text-2);
}
.setting-error {
  margin: 0;
  padding: 0 var(--space-4) var(--space-3);
  font-size: var(--text-sm);
  color: var(--danger);
}
.setting-error::before { content: '\26A0\FE0E\00a0'; }
.setting-editor {
  padding: var(--space-2) var(--space-4) var(--space-4);
  border-top: 1px solid var(--border);
  background: var(--surface);
}

/* Narrow row: the value moves under the description. */
@container (max-width: 22rem) {
  .setting-main { grid-template-columns: minmax(0, 1fr); row-gap: var(--space-1); }
  .setting-side { justify-content: space-between; }
  .setting-value { text-align: left; }
}

@media (max-width: 640px) {
  .setting-main { min-height: max(3.5rem, var(--touch-min)); }
}
@media (prefers-reduced-motion: reduce) {
  .setting-chevron, .setting-track, .setting-thumb { transition: none; }
}
</style>
