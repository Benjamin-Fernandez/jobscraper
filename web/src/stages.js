// Application stages as people read them (M13-T3). The vocabulary itself comes
// from config via /api/stats and is never hardcoded (M8-T2); this only says how
// a known status is written, and which ones close an application.

// Statuses that end an application. Everything else is still in play.
export const CLOSED_STATUSES = ['rejected', 'withdrawn']

// `to_apply` reads "To apply" (Q-118 design section 1, D-207, the queue design's word,
// AQ section 7.1): it covers a role saved from the Inbox and one waiting on or being
// auto-applied to. The Inbox Save button keeps the word "Save".
// `assessment` (Q-60): tests, coding challenges and one-way video, between
// applied and interviewing; email updates can set it (mail_status_design.md 8).
const LABELS = {
  to_apply: 'To apply',
  applied: 'Applied',
  assessment: 'Assessment',
  interviewing: 'Interviewing',
  offer: 'Offer',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
}

// 'to_apply' -> 'To apply'; a status config adds later ('on_hold') -> 'On hold'.
export function statusLabel(status) {
  if (!status) return ''
  if (LABELS[status]) return LABELS[status]
  const words = String(status).replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}

// ---- Applications stage tabs (Q-118 design sections 1, 3) ----
// The strip, in order. `all` and `active` are filters over every row; the other four
// are stages (`stageOf`).
export const STAGE_TABS = ['all', 'active', 'applied', 'interviewing', 'offer', 'rejected']

// Where a row can be moved to (MoveMenu, and a drop on a tab).
export const MOVE_TARGETS = ['applied', 'interviewing', 'offer', 'rejected']

// The stage tab a status counts under, or null when it counts under no stage tab
// (a `to_apply` row, or a status config added later: those show under All and Active only).
// `assessment` reads as Interviewing and `withdrawn` as Rejected; the row keeps its own
// word on its pill (`statusLabel`).
export function stageOf(status) {
  if (status === 'assessment') return 'interviewing'
  if (status === 'withdrawn') return 'rejected'
  return MOVE_TARGETS.includes(status) ? status : null
}

// A tab's label: "All", "Active", "Applied", "Interviewing", "Offer", "Rejected".
export function stageTabLabel(tab) {
  if (tab === 'all') return 'All'
  if (tab === 'active') return 'Active'
  return statusLabel(tab)
}
