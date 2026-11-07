// The Profile tab's remembered view, shared so another tab can open it (Q-76).
// Applications links a "Needs your input" attempt to Profile -> Application
// details: it sets the remembered view, then moves to the tab. Profile reads the
// key when it is built and again each time it is shown, so it works whether the
// tab was already open (kept alive) or not.

export const PROFILE_VIEW_KEY = 'profile.view'

export function openProfile(view = 'details') {
  try { window.localStorage.setItem(PROFILE_VIEW_KEY, view) } catch { /* private window */ }
  window.location.hash = '#/profile'
}
