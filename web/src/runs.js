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

// '0 matches', '1 match', '12 matches'.
export function matchLabel(n) {
  const count = Number(n) || 0
  return `${count} ${count === 1 ? 'match' : 'matches'}`
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
