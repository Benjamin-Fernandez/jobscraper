// Application stages as people read them (M13-T3). The vocabulary itself comes
// from config via /api/stats and is never hardcoded (M8-T2); this only says how
// a known status is written, and which ones close an application.

// Statuses that end an application. Everything else is still in play.
export const CLOSED_STATUSES = ['rejected', 'withdrawn']

// `to_apply` reads as "Saved": the word LinkedIn's and Indeed's trackers use
// for a role kept for later.
const LABELS = {
  to_apply: 'Saved',
  applied: 'Applied',
  interviewing: 'Interviewing',
  offer: 'Offer',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
}

// 'to_apply' -> 'Saved'; a status config adds later ('on_hold') -> 'On hold'.
export function statusLabel(status) {
  if (!status) return ''
  if (LABELS[status]) return LABELS[status]
  const words = String(status).replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}
