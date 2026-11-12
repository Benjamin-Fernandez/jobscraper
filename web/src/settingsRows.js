// What every Settings category shares (Q-116 design §5, §7): the per-row state behind
// SettingRow (which row is open, which is saving, "Saved", errors), the value
// formatters, the save-error wording and the copy that isn't Apply-specific. Kept in
// one place so Apply, Search and Preferences read and fail the same way.
import { getCurrentInstance, onBeforeUnmount, reactive } from 'vue'
import { ApiError, describeError } from './api.js'

// ---- copy (design §5; sentence case) ----
export const SAVED_TEXT = 'Saved'
export const READ_ONLY_SUFFIX = ' Set in config.yaml.'
export const SAVED_FLASH_MS = 3000

export const LINK_TEXT = {
  accounts: 'Manage in Accounts',
  profileEdit: 'Edit in Profile',
  profileView: 'View in Profile',
  companies: 'Manage in Companies',
}

export const COPY = {
  title: 'Settings',
  subtitle: 'Accounts, applying, search and preferences.',
  railLabel: 'Settings categories',
  backLabel: 'Back to Settings',
  categories: { accounts: 'Accounts', apply: 'Apply', search: 'Search', preferences: 'Preferences' },
  groups: {
    howApplying: 'How applying works',
    limits: 'Limits',
    writing: 'Writing',
    beforeYouApply: 'Before you apply',
    schedule: 'Schedule',
    whatToLookFor: 'What to look for',
    display: 'Display',
    keyboard: 'Keyboard',
  },
  numberWhole: 'Enter a whole number.',
  numberRange: (lo, hi) => `Enter a number from ${lo} to ${hi}.`,
  // Search (kept from today's page, A10 / A15).
  cycleHint: (days, perRun, runs) =>
    `Every company is checked again every ${days} days. At ${perRun} companies per run that is ${runs}.`,
  cycleDefault: weekly => `The config default is ${weekly}.`,
  cyclePending: (chosen, current) =>
    `${chosen} is selected but not saved. Press Enter to save, or Esc to keep ${current}.`,
  // `perDay` "2 runs a day", `runs` "3 runs", `companies` "50 companies": already pluralised.
  batchCadence: (days, perDay, runs, companies) =>
    `A full ${days}-day sweep takes ${perDay} at this size (${runs} to cover ${companies}).`,
  batchRange: (max, def) =>
    `Between 1 and ${max}. The config default is ${def}. A run started with its own count (Runs tab) uses that instead.`,
  batchNone: 'No companies yet. Add some in Companies, or start a run to load your watchlist.',
  batchEmpty: 'Enter how many companies a run should take.',
  batchMin: 'A run needs at least 1 company.',
  batchMax: max => `At most ${max} - that is every enabled company.`,
  nextRunUsesIt: 'The next run uses it.',
  loadError: reason => `Couldn't load search settings: ${reason}.`,
  tryAgain: 'Try again',
}

// ---- value formatters ----
// "No daily limit" / "No limit" / "25 a day". null (not loaded) shows nothing.
export function capLabel(n, { daily = false } = {}) {
  if (n === null || n === undefined || n === '') return ''
  const v = Number(n)
  if (!Number.isFinite(v)) return ''
  if (v === 0) return daily ? 'No daily limit' : 'No limit'
  return `${v} a day`
}

// "Stops at once" / "Up to 90 s" / "Up to 2 min" (a whole number of minutes).
export function waitLabel(s) {
  if (s === null || s === undefined || s === '') return ''
  const v = Number(s)
  if (!Number.isFinite(v)) return ''
  if (v === 0) return 'Stops at once'
  if (v % 60 === 0) return `Up to ${v / 60} min`
  return `Up to ${v} s`
}

// ---- number field validation (design §5 "Number errors") ----
// `text` is what the person typed; the answer is { value } or { error }. Digits only:
// no sign, decimal point or exponent, so "2.5" and "1e3" are not whole numbers.
export function wholeNumber(text, lo, hi) {
  const t = String(text ?? '').trim()
  if (!/^\d+$/.test(t)) return { error: COPY.numberWhole }
  const value = Number(t)
  if (!Number.isSafeInteger(value) || value < lo || value > hi) return { error: COPY.numberRange(lo, hi) }
  return { value }
}

// ---- save errors (design §5 "Save errors") ----
const stop = text => String(text).trim().replace(/[.\s]+$/, '')

// A failed PUT in words, for the row's error line. A 422 carries `errors[{field,
// message}]` (Q-111): the message for this field, else the first one, else `detail`.
// Anything else (the server is down, a 500) keeps the previous setting and says so.
export function saveErrorText(e, field) {
  if (e instanceof ApiError && e.status === 422) {
    const errors = Array.isArray(e.body?.errors) ? e.body.errors : []
    const mine = errors.find(x => x?.field === field && x.message) ?? errors.find(x => x?.message)
    if (mine) return `Couldn't save: ${stop(mine.message)}.`
    if (typeof e.detail === 'string' && e.detail) return `Couldn't save: ${stop(e.detail)}.`
    return `Couldn't save: ${stop(describeError(e))}.`
  }
  return `Couldn't save: ${stop(describeError(e))}. Your previous setting is kept.`
}

// ---- per-row state ----
// One instance per page or panel. `open` is the id of the single open edit row (or
// null); `busy`, `saved` and `error` are maps keyed by row id, read straight in the
// template (`rows.busy['daily-cap']`). `flash` shows "Saved" for 3 s; the timers are
// cleared when the owning component unmounts.
export function useRows() {
  const state = reactive({ open: null, busy: {}, saved: {}, error: {} })
  const timers = new Map()

  function stopTimer(id) {
    if (timers.has(id)) {
      clearTimeout(timers.get(id))
      timers.delete(id)
    }
  }
  function toggle(id) {
    state.open = state.open === id ? null : id
  }
  function close() {
    state.open = null
  }
  function setBusy(id, on) {
    state.busy[id] = Boolean(on)
  }
  function flash(id) {
    stopTimer(id)
    state.error[id] = ''
    state.saved[id] = true
    timers.set(id, setTimeout(() => {
      timers.delete(id)
      state.saved[id] = false
    }, SAVED_FLASH_MS))
  }
  function fail(id, msg) {
    stopTimer(id)
    state.saved[id] = false
    state.error[id] = msg
  }
  // The next edit starts clean: no stale "Saved" and no stale error.
  function clear(id) {
    stopTimer(id)
    state.saved[id] = false
    state.error[id] = ''
  }
  function dispose() {
    for (const t of timers.values()) clearTimeout(t)
    timers.clear()
  }
  if (getCurrentInstance()) onBeforeUnmount(dispose)

  return Object.assign(state, { toggle, close, setBusy, flash, fail, clear, dispose })
}
