// What the tab badges count (M12-T1), kept apart from the components so the
// numbers are easy to test and cannot drift between the badge and the tab.
import { isDismissed } from './dismissed.js'

// Statuses that end an application. Everything else is still in play.
export const CLOSED_STATUSES = ['rejected', 'withdrawn']

// New roles: in the shown shortlist, with no application status, not dismissed.
export function newRoleCount(jobs = []) {
  return jobs.filter(j => !j.status && !isDismissed(j.id)).length
}

// Active applications, from /api/stats `by_status`.
export function activeApplicationCount(byStatus = {}) {
  return Object.entries(byStatus)
    .filter(([status]) => !CLOSED_STATUSES.includes(status))
    .reduce((n, [, count]) => n + (Number(count) || 0), 0)
}
