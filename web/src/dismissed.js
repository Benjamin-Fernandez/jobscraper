// "Not interested" (M17). It used to hide a role for this browser tab only
// (sessionStorage), so after a restart the role came back at the top as new.
// It is now stored on the server (PUT/DELETE /api/dismissals/<id>) and the
// shortlist says when each role was dismissed (`dismissed_at`); the Inbox lists
// those roles in their own section at the bottom.
//
// `changes` holds this page's own marks until the next shortlist reload
// reflects them, so a card moves the moment it is clicked.
import { reactive } from 'vue'
import { dismissRole, undismissRole } from './api.js'

const changes = reactive(new Map())       // job id -> dismissed_at (string) or null

export function dismissedAt(job) {
  return changes.has(job.id) ? changes.get(job.id) : (job.dismissed_at ?? null)
}

export function isDismissed(job) {
  return Boolean(dismissedAt(job))
}

export async function dismiss(job) {
  changes.set(job.id, new Date().toISOString())
  try {
    await dismissRole(job.id)
  } catch (e) {
    changes.delete(job.id)
    throw e
  }
}

export async function restore(job) {
  changes.set(job.id, null)
  try {
    await undismissRole(job.id)
  } catch (e) {
    changes.delete(job.id)
    throw e
  }
}

// Before M17 a dismissal lived only in this tab's sessionStorage: carry any
// still there over to the server, once. Returns how many were carried.
const LEGACY_KEY = 'jobscraper.dismissed'

export async function migrateSessionDismissals() {
  let ids = []
  try {
    const raw = window.sessionStorage.getItem(LEGACY_KEY)
    ids = raw ? JSON.parse(raw) : []
  } catch {
    return 0
  }
  if (!Array.isArray(ids) || !ids.length) return 0
  let moved = 0
  for (const id of ids) {
    try {
      await dismissRole(String(id))
      changes.set(String(id), new Date().toISOString())
      moved++
    } catch {
      // A role that no longer exists: nothing to carry.
    }
  }
  try { window.sessionStorage.removeItem(LEGACY_KEY) } catch { /* blocked */ }
  return moved
}

// For tests: forget this page's marks.
export function resetDismissed() {
  changes.clear()
  try { window.sessionStorage.removeItem(LEGACY_KEY) } catch { /* blocked */ }
}
