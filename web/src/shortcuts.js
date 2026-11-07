// The shell's keyboard layer (Q-75 N16, G3r): go-to keys ("g" then a letter, as
// on GitHub and Linear), "?" for the key sheet, and "/" for the open tab's
// search box. Kept apart from App.vue so the rules are testable without a page.
//
// The rules, in one place:
//  - never while typing in a field, never with Ctrl, Meta or Alt (the browser's
//    own shortcuts stay the browser's);
//  - "/" and "?" always work; the "g" sequence follows the same on/off switch as
//    the Inbox keys, because single-key shortcuts can misfire under speech input
//    (WCAG 2.1.4). The switch lives on this device (SHORTCUTS_KEY);
//  - the letter after "g" must come within GO_WINDOW_MS, else the sequence lapses.

export const SHORTCUTS_KEY = 'jobscraper.inbox.shortcuts' // the Inbox's key, kept so the choice carries over
export const SHORTCUTS_EVENT = 'jobscraper:shortcuts'
export const GO_WINDOW_MS = 1500

export function shortcutsEnabled() {
  try { return window.localStorage.getItem(SHORTCUTS_KEY) !== '0' } catch { return true }
}

// Writes the choice and tells any open Inbox, which keeps its own copy.
export function setShortcutsEnabled(on) {
  try { window.localStorage.setItem(SHORTCUTS_KEY, on ? '1' : '0') } catch { /* blocked */ }
  window.dispatchEvent(new CustomEvent(SHORTCUTS_EVENT, { detail: { on } }))
}

export function typing(target) {
  return Boolean(target?.closest?.('input, textarea, select, [contenteditable="true"]')) || Boolean(target?.isContentEditable)
}

// The Inbox keys, for the sheet. The Inbox itself owns their behaviour.
export const INBOX_KEYS = [
  { keys: ['S'], label: 'Save the selected role' },
  { keys: ['A'], label: 'Mark it applied' },
  { keys: ['X'], label: 'Mark it Not interested' },
  { keys: ['O'], label: 'Open the posting' },
  { keys: ['J', 'K'], label: 'Next role, previous role' },
  { keys: ['Z'], label: 'Undo the last Save, Applied or Not interested' },
]

// The go-to keys from the tab registry: a tab with a `goKey` gets "g <key>".
export function goKeysOf(tabs) {
  return tabs.filter(t => t.goKey).map(t => ({ key: t.goKey, id: t.id, label: t.label }))
}

// Returns { onKeydown(event) -> boolean (handled) }. `isOpen()` says whether the
// sheet is showing: then the sheet owns the keyboard and nothing here fires.
export function createShellKeys({ tabs, go, toggleHelp, focusSearch, isOpen = () => false, now = () => Date.now() }) {
  const byKey = new Map(goKeysOf(tabs).map(k => [k.key, k.id]))
  let armedAt = 0

  function onKeydown(event) {
    if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey) return false
    if (isOpen()) { armedAt = 0; return false }
    if (typing(event.target)) { armedAt = 0; return false }
    const armed = armedAt !== 0 && now() - armedAt <= GO_WINDOW_MS
    armedAt = 0
    const key = event.key

    if (armed && !event.shiftKey && byKey.has(String(key).toLowerCase())) {
      event.preventDefault()
      event.stopPropagation() // the Inbox's own keys must not also hear it
      go(byKey.get(String(key).toLowerCase()))
      return true
    }
    if (key === '?') {
      event.preventDefault()
      toggleHelp()
      return true
    }
    if (key === '/') {
      if (!focusSearch()) return false
      event.preventDefault()
      return true
    }
    if (key === 'g' && !event.shiftKey && shortcutsEnabled() && byKey.size) {
      event.preventDefault()
      armedAt = now()
      return true
    }
    return false
  }

  return { onKeydown }
}
