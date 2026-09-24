// Dismiss, session-scoped. Open question Q2 (PRD section 11) asks whether Dismiss
// hides a role forever or only for a run, and it is the user's call. Until it is
// decided, Dismiss changes nothing on the server: it hides the role in this
// browser tab only (sessionStorage), and a new tab or session shows it again.
// Deciding Q2 means replacing this module, not patching around it.
import { reactive } from 'vue'

const KEY = 'jobscraper.dismissed'

function read() {
  try {
    const raw = window.sessionStorage.getItem(KEY)
    const ids = raw ? JSON.parse(raw) : []
    return Array.isArray(ids) ? ids : []
  } catch {
    return []
  }
}

function write(set) {
  try {
    window.sessionStorage.setItem(KEY, JSON.stringify([...set]))
  } catch {
    // Storage blocked (private mode, sandboxed preview): the in-memory set
    // still works for the life of the page.
  }
}

const ids = reactive(new Set(read()))

export function isDismissed(id) {
  return ids.has(id)
}

export function dismiss(id) {
  ids.add(id)
  write(ids)
}

export function restoreAll(idsToRestore) {
  for (const id of idsToRestore) ids.delete(id)
  write(ids)
}

// For tests: forget everything, including what sessionStorage held.
export function resetDismissed() {
  ids.clear()
  write(ids)
}
