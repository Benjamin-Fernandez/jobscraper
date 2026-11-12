// Pure helpers for the Applications tab (Q-70 lane B): what counts as active,
// how long a role has sat in its stage, and when to nudge a follow-up. No Vue
// here, so the rules are testable on their own and the tab stays markup.
import { cleanLocation, utcMs } from './format.js'
import { CLOSED_STATUSES, STAGE_TABS, stageOf, statusLabel } from './stages.js'

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

// ---- stage tabs (Q-118 design section 3, D-207) ----

// The tab a remembered value (localStorage) opens. Before Q-118 every status had a
// tab; those that left the strip map to the tab that now holds them (`to_apply` ->
// Active, `assessment` -> Interviewing, `withdrawn` -> Rejected). Nothing remembered,
// or a value no tab knows: All, which now leads the strip (assumption A1).
export function rememberedStage(raw) {
  if (STAGE_TABS.includes(raw)) return raw
  if (raw === 'to_apply') return 'active'
  return stageOf(raw) ?? 'all'
}

// Is this row in the tab? All = every row; Active = not closed; a stage = rows whose
// status counts under it (`stageOf`), so an assessment row shows under Interviewing
// and a withdrawn one under Rejected. A `to_apply` row, or a status config added
// later, shows under All and Active only.
export function inStage(row, tab) {
  if (tab === 'all') return true
  if (tab === 'active') return isActive(row)
  return stageOf(row.status) === tab
}

// {all, active, applied, interviewing, offer, rejected} -> count, for the strip.
export function stageCounts(rows) {
  return Object.fromEntries(STAGE_TABS.map(t => [t, rows.filter(r => inStage(r, t)).length]))
}

// JobScraper is applying to the role, or it waits in the auto-apply queue (the queue
// lane's `row.queue` and `last_attempt.kind === 'queued'` are read when present and
// ignored when absent). Such a row is not dragged and its Move menu is off: the
// status would change under a running attempt.
export const LOCKED_REASON = 'JobScraper is applying to this role. Stop it in Runs first.'

export function inFlight(row) {
  const kind = row?.last_attempt?.kind
  return kind === 'running' || kind === 'queued' || Boolean(row?.queue)
}

// The order rows in flight are pinned in at the top of All and Active: running
// first, then queued by queue position; everything else 0 (not pinned).
export function pinRank(row) {
  if (row?.last_attempt?.kind === 'running') return 1
  if (!inFlight(row)) return 0
  const p = Number(row?.queue?.position)
  return 2 + (Number.isFinite(p) && p > 0 ? p : 9999)
}

// The status came from a submit auto-apply made (the "Applied automatically" badge).
export function appliedAutomatically(row) {
  return row?.status === 'applied' && row?.last_attempt?.kind === 'sent'
}
