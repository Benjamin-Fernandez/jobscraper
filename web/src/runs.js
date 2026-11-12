// What the user can show (M15): every run, a recent range, or runs they chose.
// One module owns the value's shapes so the selector, the shell, the Runs
// picker and the Applications filter can never disagree about them:
//
//   'all' | 'week' | 'month'   a range - the server works out which runs
//   [14, 12]                   runs chosen on the Runs tab
//   12                         one run (old bookmarks, the Runs picker's single tick)

export const RANGES = { all: 'All runs', week: 'Past week', month: 'Past month' }
const RANGE_DAYS = { week: 7, month: 30 }

export const isRange = value => typeof value === 'string' && value in RANGES

// The `?run=` value for /api/shortlist.
export function runQuery(value) {
  if (Array.isArray(value)) return value.join(',')
  if (value === null || value === undefined) return 'all'
  return String(value)
}

// How a choice reads in the selector: 'Past week', 'Run 12', 'Runs 14, 12'.
export function runLabel(value) {
  if (Array.isArray(value)) {
    if (value.length === 1) return `Run ${value[0]}`
    return value.length <= 3 ? `Runs ${value.join(', ')}` : `${value.length} runs`
  }
  return RANGES[value] ?? `Run ${value}`
}

export function asList(value) {
  if (Array.isArray(value)) return value
  return Number.isInteger(value) ? [value] : []
}

export function sameRun(a, b) {
  if (Array.isArray(a) || Array.isArray(b)) {
    const x = asList(a); const y = asList(b)
    return x.length === y.length && x.every((n, i) => n === y[i])
  }
  return a === b
}

// Stamps are UTC without a zone ('2026-09-23T14:30:00').
function finishedAt(run) {
  const t = Date.parse(`${String(run.finished_at || '').slice(0, 19)}Z`)
  return Number.isNaN(t) ? null : t
}

// The run numbers a choice covers, or null for "no filter" (All runs). Used
// where the client filters by itself - the Applications tab.
export function runsInRange(runs, value, now = Date.now()) {
  if (value === 'all' || value === null || value === undefined) return null
  if (value in RANGE_DAYS) {
    const since = now - RANGE_DAYS[value] * 24 * 60 * 60 * 1000
    return new Set(runs.filter(r => (finishedAt(r) ?? -Infinity) > since).map(r => r.run_no))
  }
  return new Set(asList(value))
}

// 1234 -> '1,234' (Q-75 G37). Anything that is not a number is returned as it is.
export function num(n) {
  const v = typeof n === 'string' && n.trim() !== '' ? Number(n) : n
  return typeof v === 'number' && Number.isFinite(v) ? v.toLocaleString('en-US') : n
}

// '0 matches', '1 match', '12 matches'.
export function matchLabel(n) {
  const count = Number(n) || 0
  return `${num(count)} ${count === 1 ? 'match' : 'matches'}`
}

// How often runs are needed, in words people use (Q-75 G37): "1.6 runs a day",
// and under one a day "about 1 run every 2 days" - never "0.6 runs a day".
export function runsPerDayLabel(perDay) {
  const x = Number(perDay)
  if (!Number.isFinite(x) || x <= 0) return ''
  if (x >= 1) {
    const n = Math.round(x * 10) / 10
    return `${num(n)} ${n === 1 ? 'run' : 'runs'} a day`
  }
  const days = Math.round(1 / x)
  return days <= 1 ? '1 run a day' : `about 1 run every ${num(days)} days`
}

// A run's status in words (M16): the store says `ok`, people read "success".
const RUN_STATUS = { ok: 'success', failed: 'failed', aborted_unhealthy: 'aborted', dry_run: 'dry run', running: 'running' }
export function runStatusLabel(status) {
  if (!status) return '—'
  return RUN_STATUS[status] ?? String(status).replace(/_/g, ' ')
}

// The run history's badge (Q-118 LC): the same words with a capital, a tone and an
// icon. The word always carries the meaning; the tone and the icon only help.
const RUN_STATUS_TITLE = { ok: 'Success', failed: 'Failed', aborted_unhealthy: 'Aborted', dry_run: 'Dry run', running: 'Running' }
export function runStatusTitle(status) {
  if (!status) return ''
  if (status in RUN_STATUS_TITLE) return RUN_STATUS_TITLE[status]
  const words = String(status).replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}
const RUN_STATUS_TONE = { ok: 'ok', failed: 'danger', aborted_unhealthy: 'warn', dry_run: 'neutral', running: 'info' }
export const runStatusTone = status => RUN_STATUS_TONE[status] ?? 'neutral'
const RUN_STATUS_ICON = { ok: 'check', failed: 'x', aborted_unhealthy: 'alert', dry_run: 'info', running: 'clock' }
export const runStatusIcon = status => RUN_STATUS_ICON[status] ?? null

// Why a run ended as it did, where the status alone does not say (Q-75 G27).
// `aborted_unhealthy` is the pipeline's network-fault guard: most due companies
// failed together, so nothing was counted against any of them.
const RUN_STATUS_NOTE = {
  aborted_unhealthy: 'Most companies failed together, which points to a network problem on this computer. '
    + 'None were counted against them and the batch was not marked done. Run again to retry.',
}
export function runStatusNote(status) {
  return RUN_STATUS_NOTE[status] ?? ''
}

// How often the cycle restarts, in words (M15, Settings).
const CYCLE_WORDS = { 1: 'Daily', 7: 'Weekly', 14: 'Fortnightly', 30: 'Monthly' }
export function cycleLabel(days) {
  return CYCLE_WORDS[days] ?? `Every ${days} days`
}

// "Choose runs…" in the Inbox opens the Runs tab; the tab then takes the user
// straight to the picker instead of the top of the page (the run form and a
// long log are above it). A one-shot request, not state: a plain visit to the
// Runs tab starts at the top as usual.
let pickerWanted = false
export function requestPicker() {
  pickerWanted = true
}
export function takePickerRequest() {
  const wanted = pickerWanted
  pickerWanted = false
  return wanted
}
