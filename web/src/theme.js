// Light, dark or follow the system (Q-75 G40). The choice is kept in this browser
// only; with none stored, style.css follows prefers-color-scheme as before. It is
// applied as `data-theme` on <html>, which style.css reads. index.html applies the
// stored value in a tiny inline script before the first paint, so a dark choice
// never flashes white; this module only changes it from Settings.
export const THEME_KEY = 'jobscraper.theme'
export const THEMES = [
  { id: 'light', label: 'Light' },
  { id: 'dark', label: 'Dark' },
  { id: 'system', label: 'System' },
]

export function storedTheme() {
  try {
    const v = window.localStorage.getItem(THEME_KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'            // storage blocked: follow the system
  }
}

export function applyTheme(theme) {
  const root = document.documentElement
  if (theme === 'light' || theme === 'dark') root.setAttribute('data-theme', theme)
  else root.removeAttribute('data-theme')
}

export function setTheme(theme) {
  try {
    if (theme === 'light' || theme === 'dark') window.localStorage.setItem(THEME_KEY, theme)
    else window.localStorage.removeItem(THEME_KEY)
  } catch { /* private window: it applies for this page only */ }
  applyTheme(theme)
}
