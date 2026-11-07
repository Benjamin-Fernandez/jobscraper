// What the Applications tab says about an auto-apply attempt (Q-76 N11). The
// server decides the `kind` (attempt_view in routers/applications.py); this only
// words it. Short labels that name the state, not the mechanism.

const LABELS = {
  running: 'Auto-apply running',
  sent: 'Sent by auto-apply',
  unconfirmed: 'Sent, not confirmed',
  dry_run: 'Dry run ready',
  needs_input: 'Needs your input',
  cancelled: 'Auto-apply cancelled',
  stopped: 'Auto-apply stopped',
}

// The pill text. A dry run never sends anything, so a stopped dry run is still
// "stopped"; `mode` is kept in the signature for the attempts list, which shows
// "Dry run" or "Real" beside it.
export function attemptLabel(kind, mode) {
  return LABELS[kind] ?? (mode === 'dry_run' ? 'Dry run' : 'Auto-apply')
}

export function modeLabel(mode) {
  return mode === 'dry_run' ? 'Dry run' : 'Real'
}

// Only these two wait for something the owner can fill in under Profile.
export function needsInput(attempt) {
  return attempt?.kind === 'needs_input'
}
