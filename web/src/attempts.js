// What the Applications tab says about an auto-apply attempt (Q-76 N11, Q-120 U3). The
// server decides the `kind` (attempt_view in routers/applications.py, plus `queued` from
// the queue); this only words it. Short labels that name the state, not the mechanism.
import { ordinal } from './api.js'
import { appliedAutomatically, inFlight } from './applications.js'

const LABELS = {
  queued: 'Queued',
  running: 'Auto-apply running',
  sent: 'Sent by auto-apply',
  unconfirmed: 'Sent, not confirmed',
  dry_run: 'Dry run ready',
  needs_input: 'Needs your input',
  cancelled: 'Auto-apply cancelled',
  stopped: 'Auto-apply stopped',
}

// The attempt-list label (the details panel and Runs' "Recently finished"). The row
// itself words its state with `rowState` below. `mode` is kept in the signature for the
// attempts list, which shows "Dry run" or "Real" beside it.
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

// ---- the state on an Applications row (Q-120 U3, D-205/D-207) ----

// While JobScraper works on a role the step it is on, in the owner's words (the same
// words the Runs panel uses; an unknown state shows nothing).
export const STEP_WORDS = {
  tailoring: 'Preparing the resume',
  planning: 'Reading the form',
  opening: 'Opening the site',
  signing_in: 'Signing in',
  signing_up: 'Creating an account',
  verifying_email: 'Checking email',
  filling: 'Filling the form',
  submitting: 'Submitting',
}

// What a removal of a role in flight answers (409 `in_progress`) when the server sends no text.
export const IN_PROGRESS_REMOVE = 'JobScraper is applying to this role right now. Stop it in Runs first.'

// Kinds that end without a send: after the owner has moved the role on (applied by
// hand, interviewing...) they are history, not a state to show or to retry.
const ENDED = new Set(['stopped', 'cancelled', 'needs_input'])
const REASON_CLIP = 60

function clip(text, n = REASON_CLIP) {
  const t = String(text ?? '').trim()
  return t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t
}

// The one state chip of a row, or null when it shows none:
//   {kind, label, tone, title, step, reason, icon}
// `tone` is a `.ui-badge` tone; `title` the full text; `step` the muted step word beside
// "Applying…"; `reason` a muted line beside "Cancelled"; `icon` true for the
// "Applied automatically" check. A role waiting in the queue (`row.queue`) reads Queued
// even when an older attempt of it stopped; one being applied to reads Applying.
export function rowState(row) {
  const a = row?.last_attempt ?? null
  let kind = a?.kind ?? null
  if (row?.queue && kind !== 'running') kind = 'queued'
  if (!kind) return null
  if (ENDED.has(kind) && row.status !== 'to_apply') return null
  const title = [a?.text, a?.hint].filter(Boolean).join(' ')
  switch (kind) {
    case 'queued': {
      const p = Number(row.queue?.position)
      return { kind, label: p > 0 ? `Queued · ${ordinal(p)}` : 'Queued', tone: 'neutral', title: '', step: '', reason: '', icon: false }
    }
    case 'running':
      return { kind, label: 'Applying…', tone: 'info', title, step: STEP_WORDS[a?.state] ?? '', reason: '', icon: false }
    case 'sent': {
      const auto = appliedAutomatically(row)
      return { kind, label: auto ? 'Applied automatically' : LABELS.sent, tone: 'ok', title, step: '', reason: '', icon: auto }
    }
    case 'unconfirmed':
      return { kind, label: LABELS.unconfirmed, tone: 'warn', title, step: '', reason: '', icon: false }
    case 'dry_run':
      return { kind, label: LABELS.dry_run, tone: 'info', title, step: '', reason: '', icon: false }
    case 'needs_input':
      return { kind, label: 'Needs your answers', tone: 'warn', title, step: '', reason: '', icon: false }
    case 'stopped': {
      const why = clip(a?.text)
      return { kind, label: why ? `Stopped: ${why}` : 'Stopped', tone: 'warn', title, step: '', reason: '', icon: false }
    }
    case 'cancelled':
      return { kind, label: 'Cancelled', tone: 'neutral', title, step: '', reason: clip(a?.text), icon: false }
    default:
      return { kind, label: attemptLabel(kind, a?.mode), tone: 'neutral', title, step: '', reason: '', icon: false }
  }
}

// "Try again" applies to a role that stopped, was cancelled, or waits for answers, and
// that is still To apply and not in the queue. The row cannot tell whether the answers
// are in, so needs_input offers it too; the server refuses with its own words when not.
export function canRetry(row) {
  const s = rowState(row)
  return Boolean(s) && ENDED.has(s.kind) && row.status === 'to_apply' && !inFlight(row)
}

// What a refused enqueue (422) says, in the owner's words: the refusals' own sentences,
// or the profile. Same wording as the Inbox.
export function refusalMessage(body) {
  if (body?.detail === 'profile_incomplete') return 'Finish your application details first.'
  const refused = Array.isArray(body?.refused) ? body.refused : []
  const texts = refused.map(r => [r.text, r.hint].filter(Boolean).join(' '))
  return texts.length ? texts.join(' ') : 'Could not add this role to the auto-apply queue.'
}
