// Pure helpers for the Applications tab (Q-70 lane B): what counts as active,
// how long a role has sat in its stage, and when to nudge a follow-up. No Vue
// here, so the rules are testable on their own and the tab stays markup.
import { cleanLocation, utcMs } from './format.js'
import { CLOSED_STATUSES, statusLabel } from './stages.js'

export const STAGE_KEY = 'jobscraper.applications.stage'

// An applied role with no change for this long gets a "Follow up?" cue.
export const FOLLOW_UP_DAYS = 14

// The time of a row's last change: its newest event, else what the row says.
export function lastAt(row) {
  return row.events?.at(-1)?.at ?? row.updated_at ?? row.applied_at ?? ''
}

// Still in play: everything but rejected / withdrawn.
export function isActive(row) {
  return !CLOSED_STATUSES.includes(row.status)
}

// Whole days between an ISO stamp and now; null when the stamp is unreadable.
export function daysSince(iso, now = Date.now()) {
  const t = utcMs(iso)
  return t === null ? null : Math.floor((now - t) / 86400000)
}

export function needsFollowUp(row, now = Date.now()) {
  const d = daysSince(lastAt(row), now)
  return row.status === 'applied' && d !== null && d >= FOLLOW_UP_DAYS
}

// "Applied · 3 days": the stage the last event moved to, and how long ago.
export function ageLabel(row, now = Date.now()) {
  const e = row.events?.at(-1)
  if (!e) return ''
  const d = daysSince(e.at, now)
  if (d === null) return statusLabel(e.to_status)
  return `${statusLabel(e.to_status)} · ${d <= 0 ? 'today' : d === 1 ? '1 day' : `${d} days`}`
}

// Under the title: where the role is, and whether the posting has closed.
export function secondLine(row) {
  return [cleanLocation(row.location), row.closed_at ? 'Posting closed' : ''].filter(Boolean).join(' · ')
}
