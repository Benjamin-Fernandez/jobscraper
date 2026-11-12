// The Companies list's row density, remembered in this browser (G30; Q-116 moved the
// switch into Settings -> Preferences too). Kept apart from the components so Settings
// and the Companies list read and write one key and follow each other through a window
// event, the way the keyboard-shortcut switch does (shortcuts.js).
export const DENSITY_KEY = 'jobscraper.companies.density'
export const DENSITY_EVENT = 'jobscraper:density'

export function densityCompact() {
  try { return window.localStorage.getItem(DENSITY_KEY) === 'compact' } catch { return false }
}

// Writes the choice and tells any mounted view (`detail.on`).
export function setDensityCompact(on) {
  try { window.localStorage.setItem(DENSITY_KEY, on ? 'compact' : 'comfortable') } catch { /* private window */ }
  window.dispatchEvent(new CustomEvent(DENSITY_EVENT, { detail: { on: Boolean(on) } }))
}
