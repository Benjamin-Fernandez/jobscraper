// What the Applications tab says about an auto-apply attempt (Q-76 N11, Q-120 U3). The
// server decides the `kind` (attempt_view in routers/applications.py, plus `queued` from
// the queue); this only words it. Short labels that name the state, not the mechanism.
import { ordinal } from './api.js'
import { appliedAutomatically, inFlight } from './applications.js'
import { when } from './format.js'
import { openProfile } from './profileView.js'

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

// ---- assumed answers (Q-121 U1, llm_first_fill_design section 6) ----

// "3 answers assumed" for an attempt (or a Runs "recent" item) that carries it, else ''.
// The server words it (`assumed_text`); a count alone is worded here.
export function assumedText(a) {
  const n = Number(a?.assumed)
  if (!(n > 0)) return ''
  return String(a.assumed_text || '').trim() || `${n} ${n === 1 ? 'answer' : 'answers'} assumed`
}

// A label with the assumption count after it: "Submitted · 3 answers assumed".
export function withAssumed(label, a) {
  const t = assumedText(a)
  return t ? `${label} · ${t}` : label
}

// The fact an `owner_fact_missing` attempt waits for, from the contract's sentence
// ("This form asks for your date of birth, which isn't in your profile or resume...").
// Since flow review F4 the detail also says where the form asked it ("date of birth
// (“Date of Birth” on my_information)"); the chip keeps the fact alone, the title has all.
// '' when the sentence is not that one.
export function missingFact(a) {
  const fact = /^This form asks for your (.+?), which isn't in your profile/i.exec(String(a?.text ?? ''))?.[1]?.trim() ?? ''
  return fact.replace(/\s*\([^()]*\)\s*$/, '').trim() || fact
}

// The document a `document_missing` attempt needs ("This form needs a photo, and your profile has none...").
export function missingDocument(a) {
  return /^This form needs an? (.+?), and your profile has none/i.exec(String(a?.text ?? ''))?.[1]?.trim() ?? ''
}

// What a `consent_refused` attempt needs the owner to agree to (Q-121 A1, §17.6), from the
// contract's sentence ("This form needs you to agree to keeping your details on file for
// future roles, and your profile says no..."). '' when the sentence is not that one.
export function refusedConsent(a) {
  return /^This form needs you to agree to (.+?), and your profile says no/i.exec(String(a?.text ?? ''))?.[1]?.trim() ?? ''
}

// A content failure (§17.6, review C8): the server words an `unanswerable_required` whose
// detail starts with a content-failure marker as kind `stopped` ("The local AI couldn't
// answer this form without guessing..."). Nothing was captured, so there is nothing to
// answer and no Try again. An older server sends that reason as `needs_input`: never this.
export function contentFailure(a) {
  return a?.kind === 'stopped' && a?.reason_code === 'unanswerable_required'
}

// ---- "Add it" pointing at the field (Q-121 A1-W, Q-127) ----

// The Profile path (or Profile group) an attempt that waits for the owner points at:
// `owner_fact_path` when the server sends one ("identity.date_of_birth",
// "consents.data_retention_consent"), else the Consents group for `consent_refused`, else
// '' (the link opens Your details, as before). Absent-safe: an older server sends no
// `owner_fact_path`.
const PROFILE_PATH = /^[a-z_][a-z0-9_]*(\[\d+\])?(\.[a-z_][a-z0-9_]*(\[\d+\])?)*$/i
export const CONSENTS_GROUP = 'consents'
export function answerTarget(a) {
  const path = typeof a?.owner_fact_path === 'string' ? a.owner_fact_path.trim() : ''
  if (path && PROFILE_PATH.test(path)) return path
  return a?.reason_code === 'consent_refused' ? CONSENTS_GROUP : ''
}

// Open Profile -> Your details at `target` (a field path or a group id). The wish is left
// in sessionStorage for the details page to act on once it has drawn the field, and
// announced for a Profile tab that is already open. With no target this is
// `openProfile('details')`.
export const FIELD_FOCUS_KEY = 'jobscraper.profile.field'
export function openAnswer(target) {
  const t = String(target ?? '').trim()
  if (t) {
    try { window.sessionStorage.setItem(FIELD_FOCUS_KEY, t) } catch { /* private window */ }
  }
  openProfile('details')
  if (t) window.dispatchEvent(new CustomEvent('jobscraper:show-field', { detail: { path: t } }))
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
export const TRIAL_LABEL = 'Trial: filled, not sent'

function clip(text, n = REASON_CLIP) {
  const t = String(text ?? '').trim()
  return t.length > n ? `${t.slice(0, n - 1).trimEnd()}…` : t
}

// Q-127 (D-215, design B.4 copy table): the words of a role that waits for the owner.
export const READY_LABEL = 'Ready to try again'
export const ADD_IT = 'Add it'
export const OPEN_SWITCH = 'Open the switch'   // the link of a refused consent (D-229)
export const FILES_GROUP = 'documents'        // the Profile group (section Files) a file chip opens

// The words of a Profile path when the sentence names no fact: "identity.date_of_birth"
// -> "date of birth". '' for nothing usable.
export function pathWords(path) {
  const last = String(path ?? '').split('.').pop() ?? ''
  return last.replace(/\[\d+\]/g, '').replace(/_/g, ' ').trim()
}

// "This form asks for your passport number, ..." -> "this form asks for your passport number, ...".
function lowerFirst(text) {
  const t = String(text ?? '').trim()
  return t ? t[0].toLowerCase() + t.slice(1) : ''
}

// The one state chip of a row, or null when it shows none:
//   {kind, label, tone, title, step, reason, icon, ...}
// `tone` is a `.ui-badge` tone; `title` the full text; `step` the muted step word beside
// "Applying…"; `reason` a muted line beside "Cancelled"; `icon` true for the
// "Applied automatically" check. A role waiting in the queue (`row.queue`) reads Queued
// even when an older attempt of it stopped; one being applied to reads Applying.
//
// A role that waits for the owner reads, in the copy table's words:
//   "Needs one detail: {fact}" + `add` (Add it opens Your details at `target`),
//   "Needs one file: {detail}" + `add` (opens the Files section),
//   "Stopped: {n} questions had no answer" (a strict stop; its answers are in the panel),
//   "Ready to try again" (`ready`: the server says every detail it waited on is filled),
//   "Stopped: this form asks for your {fact}, ..." (`noField`: Your details cannot hold it).
// The count of unanswered questions is `last_attempt.not_answered` (Q-128: the list carries it,
// `store.not_answered_counts`, the same rows the panel's "Not answered n" counts); the row
// replaces it with the panel's own count once the panel has loaded the fields.
export function rowState(row) {
  const a = row?.last_attempt ?? null
  let kind = a?.kind ?? null
  if (row?.queue && kind !== 'running') kind = 'queued'
  if (!kind) return null
  if (ENDED.has(kind) && row.status !== 'to_apply') return null
  const title = [a?.text, a?.hint].filter(Boolean).join(' ')
  // A stopped role whose waited-for details are all in: Try again is the next step.
  if (ENDED.has(kind) && kind !== 'cancelled' && a?.ready_to_retry === true) {
    return { kind, label: READY_LABEL, tone: 'ok', title, step: '', reason: '', icon: false, ready: true }
  }
  switch (kind) {
    case 'queued': {
      const p = Number(row.queue?.position)
      return { kind, label: p > 0 ? `Queued · ${ordinal(p)}` : 'Queued', tone: 'neutral', title: '', step: '', reason: '', icon: false }
    }
    case 'running':
      return { kind, label: 'Applying…', tone: 'info', title, step: STEP_WORDS[a?.state] ?? '', reason: '', icon: false }
    case 'sent': {
      // With assumptions the chip reads "Submitted · 3 answers assumed"; the row's
      // "See what was sent" opens each answer with its basis (Q-127 B.2b).
      const auto = appliedAutomatically(row)
      const assumed = assumedText(a)
      return {
        kind, label: assumed ? withAssumed('Submitted', a) : auto ? 'Applied automatically' : LABELS.sent,
        tone: 'ok', title, step: '', reason: '', icon: auto, assumed,
      }
    }
    case 'unconfirmed': {
      const assumed = assumedText(a)
      return { kind, label: withAssumed(LABELS.unconfirmed, a), tone: 'warn', title, step: '', reason: '', icon: false, assumed }
    }
    case 'dry_run': {
      // A first-use trial (apply.always_trial_runs) is filled and not sent (§12). The API
      // marks it with `trial: true` on the attempt; a plain dry run reads as before.
      const assumed = assumedText(a)
      const trial = a?.trial === true
      const base = trial ? (String(a?.trial_text || '').trim() || TRIAL_LABEL) : assumed ? 'Ready to submit' : LABELS.dry_run
      return { kind, label: withAssumed(base, a), tone: 'info', title, step: '', reason: '', icon: false, assumed, trial }
    }
    case 'needs_input': {
      // owner_fact_missing (§9): name the fact the form asked for; Add it opens that field.
      // consent_refused (§17.6): name what the form needs the owner to agree to.
      // unanswerable_required (a strict stop): the questions are in "What was filled".
      const code = a?.reason_code
      const target = answerTarget(a)
      const base = { kind, tone: 'warn', title, step: '', reason: '', icon: false }
      if (code === 'owner_fact_missing') {
        const fact = missingFact(a) || pathWords(target)
        return { ...base, label: fact ? `Needs one detail: ${fact}` : 'Needs one detail', fact, target, add: true }
      }
      if (code === 'consent_refused') {
        // The link is the switch itself (D-229): `target` is `consents.<key>` (the server's
        // owner_fact_path) or the Consents group when the server named none.
        const consent = refusedConsent(a)
        return {
          ...base, label: consent ? `Needs your agreement: ${consent}` : 'Needs your agreement',
          consent, target, add: true, addText: OPEN_SWITCH,
        }
      }
      if (code === 'unanswerable_required') {
        const n = Number(a?.not_answered)
        const label = n > 0 ? `Stopped: ${n} ${n === 1 ? 'question' : 'questions'} had no answer` : 'Stopped: a question had no answer'
        return { ...base, label, filled: true }
      }
      return { ...base, label: 'Needs your details', target, add: true }
    }
    case 'stopped': {
      // document_missing (§9): the form needs a file the profile does not hold. A content
      // failure (§17.6) reads with the contract's own text and offers no Try again; nor does
      // a fact Your details cannot hold (`no_field`): there is nothing to add or to retry.
      const base = { kind, tone: 'warn', title, step: '', reason: '', icon: false }
      if (a?.no_field === true) return { ...base, label: `Stopped: ${lowerFirst(a.text)}`, noField: true, noRetry: true }
      const doc = a?.reason_code === 'document_missing' ? missingDocument(a) : ''
      if (doc) return { ...base, label: `Needs one file: ${doc}`, document: doc, target: FILES_GROUP, add: true }
      const why = clip(a?.text)
      return { ...base, label: why ? `Stopped: ${why}` : 'Stopped', noRetry: contentFailure(a) }
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
// Not for a content failure (§17.6, review C8): nothing was captured, so a retry would
// stop on the same form; the owner applies by hand or skips the role.
export function canRetry(row) {
  const s = rowState(row)
  return Boolean(s) && ENDED.has(s.kind) && !s.noRetry && row.status === 'to_apply' && !inFlight(row)
}

// What a refused enqueue (422) says, in the owner's words: the refusals' own sentences,
// or the profile. Same wording as the Inbox.
export function refusalMessage(body) {
  if (body?.detail === 'profile_incomplete') return 'Finish your details first.'
  const refused = Array.isArray(body?.refused) ? body.refused : []
  const texts = refused.map(r => [r.text, r.hint].filter(Boolean).join(' '))
  return texts.length ? texts.join(' ') : 'Could not add this role to the auto-apply queue.'
}

// ---- What was sent / What was filled (Q-127 U2, design B.2b, B.4 copy table) ----

// The attempt kinds that sent the form (a submit was clicked): "What was sent". Every other
// attempt that filled something reads "What was filled".
const SENT_KINDS = new Set(['sent', 'unconfirmed'])
// The kinds whose attempt may hold recorded answers; a queued or running one has none to show
// yet, and a cancelled one stopped before the form.
const ANSWER_KINDS = new Set(['sent', 'unconfirmed', 'dry_run', 'needs_input', 'stopped'])

export const SENT_TITLE = 'What was sent'
export const FILLED_TITLE = 'What was filled'

export function wasSent(kind) {
  return SENT_KINDS.has(kind)
}

// The entry of a row: `{id, sent, title, button}` for its last attempt, or null when there is
// nothing to open (no attempt row yet, or one that has recorded nothing).
export function sentEntry(row) {
  const a = row?.last_attempt ?? null
  if (!a || a.id == null || row?.queue || !ANSWER_KINDS.has(a.kind)) return null
  const sent = wasSent(a.kind)
  return { id: a.id, sent, title: sent ? SENT_TITLE : FILLED_TITLE, button: sent ? 'See what was sent' : 'See what was filled' }
}

// The line under the title: "Sent 24 Sep 16:50. 3 answers were assumed." (the sentence about
// assumptions only when there are some) / "Nothing was sent. These are the answers filled
// before it stopped."
export function sentSubLine(attempt, assumedCount = 0) {
  if (!wasSent(attempt?.kind)) return 'Nothing was sent. These are the answers filled before it stopped.'
  const at = when(attempt?.finished_at)
  const n = Number(assumedCount) || 0
  const assumed = n > 0 ? ` ${n} ${n === 1 ? 'answer was' : 'answers were'} assumed.` : ''
  return `${at ? `Sent ${at}.` : 'Sent.'}${assumed}`
}

// The filter's counts over the payload's fields: All · Assumed · Not answered.
export function fieldCounts(fields) {
  const list = Array.isArray(fields) ? fields : []
  return {
    all: list.length,
    assumed: list.filter(f => f.assumed).length,
    notAnswered: list.filter(f => f.status === 'not_answered').length,
  }
}

export function filterFields(fields, filter) {
  const list = Array.isArray(fields) ? fields : []
  if (filter === 'assumed') return list.filter(f => f.assumed)
  if (filter === 'not_answered') return list.filter(f => f.status === 'not_answered')
  return list
}

// The button on a row that offers a correction: a field that was left empty, or on a form that
// was not sent, reads "Answer for next time"; a sent answer reads "Use a different answer next time".
export function correctionLabel(field, sent) {
  return !sent || field?.status === 'not_answered' ? 'Answer for next time' : 'Use a different answer next time'
}

// What the owner reads after a correction is saved, by whether the form was already sent.
export const SAVED_SENT = 'This form was already sent. Your answer is used from the next application on.'
export const SAVED_STOPPED = "Saved. Try this application again when you're ready."

// Why a field cannot be corrected here, in the contract's own words (REMEMBER_REFUSAL_TEXTS;
// the answers route sends the code, the remember route the same text). `lead` is the plain
// sentence, `link` the part that opens somewhere: `to` is 'details' (Your details) or
// 'settings' (Settings → Apply). '' or an unknown code: null.
export function refusalCopy(code, label = '') {
  if (code === 'follows_your_details') {
    return { lead: 'This answer follows your details.', link: 'Change it in Your details.', to: 'details' }
  }
  if (code === 'shared_answer') {
    return {
      lead: 'This question shares a saved answer with other questions.',
      link: 'Change it in Settings → Apply → Answers you corrected.', to: 'settings',
    }
  }
  if (code === 'too_general') {
    // Real forms have inputs with no label (the parts of a repeating education or experience
    // block): there is no question to quote, so say that, never an empty pair of quotes.
    if (!String(label ?? '').trim()) {
      return {
        lead: "This field had no label on the form, so an answer can't be saved for it.",
        link: 'Change it in your details instead.', to: 'details',
      }
    }
    return { lead: `This question is too general to save on its own (“${label}”).`, link: 'Change it in your details instead.', to: 'details' }
  }
  return null
}

// ---- why a field was left empty (Q-121 W, D-229) ----

// A field left empty carries the contract's fixed sentence (`reason`), what to do
// (`reason_hint`), the reason's code (`reason_code`) and, for three codes, the profile key the
// hint points at (`reason_key`, "" = none). The link comes from code + key alone, never from
// the sentence: no key, no link.
//   consent_not_agreed -> "Open the switch" at `consents.<key>`
//   place_unknown      -> "Add it" at the Work rights field the server names
//   detail_missing     -> "Add it" at the detail the server found for the field
// `{label, target}` for `openAnswer(target)`, or null.
export function emptyAction(field) {
  if (field?.status !== 'not_answered') return null
  const key = typeof field.reason_key === 'string' ? field.reason_key.trim() : ''
  if (!key || !PROFILE_PATH.test(key)) return null
  if (field.reason_code === 'consent_not_agreed') return { label: OPEN_SWITCH, target: key }
  if (field.reason_code === 'place_unknown' || field.reason_code === 'detail_missing') return { label: ADD_IT, target: key }
  return null
}

// The title of one row in What was sent / filled. The payload's `label` when there is one; else
// the page step the field sat on (`step`, the only grouping text the answers payload carries:
// there is no section or group key per field); else "Field with no label". `n` (1-based) numbers
// the unlabelled rows of the list so a run of them can be told apart.
export function fieldTitle(field, n = 0) {
  const label = String(field?.label ?? '').trim()
  if (label) return label
  const step = String(field?.step ?? '').trim()
  const num = n > 0 ? ` ${n}` : ''
  return step ? `Field with no label${num} (on “${step}”)` : `Field with no label${num}`
}

// The widget that takes a field's answer, from the form's field type and the options it
// offered (the server decides the stored kind from the same two facts):
//   multi (several of the options) · choice (one of the options, Yes/No included: it is sent
//   as the option's own label) · yes_no (a tick box) · number · date · textarea · text.
// A choice-type field with no options on record is asked as text: the server then says why.
export function fieldKind(field) {
  const options = Array.isArray(field?.options) ? field.options.filter(o => typeof o === 'string' && o.trim()) : []
  const type = String(field?.type ?? '')
  if (options.length) return type === 'multi_choice' ? 'multi' : 'choice'
  if (type === 'checkbox') return 'yes_no'
  if (type === 'number') return 'number'
  if (type === 'date') return 'date'
  if (type === 'textarea') return 'textarea'
  return 'text'
}

// The editor's starting answer: what was filled, when it fits the widget.
export function startValue(field, kind) {
  const shown = String(field?.value_text ?? '').trim()
  if (kind === 'multi') {
    const parts = shown.split(',').map(p => p.trim()).filter(Boolean)
    return (field.options ?? []).filter(o => parts.includes(o))
  }
  if (kind === 'choice') return (field.options ?? []).includes(shown) ? shown : ''
  if (kind === 'yes_no') return ({ yes: 'yes', true: 'yes', no: 'no', false: 'no' })[shown.toLowerCase()] ?? ''
  return field?.status === 'not_answered' ? '' : shown
}

// The POST body for an answer from the editor, or `{error}` when there is nothing to send
// (so the owner is told before a call is made). `answer` is the editor's value for `kind`.
export function answerBody(kind, answer, onlyEmployer, etag) {
  const base = { only_employer: onlyEmployer === true, etag }
  if (kind === 'multi') {
    return Array.isArray(answer) && answer.length ? { ...base, picks: answer } : { error: 'Choose at least one option.' }
  }
  if (kind === 'choice') {
    return typeof answer === 'string' && answer ? { ...base, picks: [answer] } : { error: 'Choose an option.' }
  }
  if (kind === 'yes_no') {
    return answer === 'yes' || answer === 'no' ? { ...base, value: answer === 'yes' } : { error: 'Answer Yes or No.' }
  }
  if (kind === 'number') {
    const text = String(answer ?? '').trim()
    const n = Number(text)
    return text && Number.isFinite(n) ? { ...base, value: n } : { error: 'Give a number.' }
  }
  const text = String(answer ?? '').trim()
  return text ? { ...base, value: text } : { error: 'Give an answer.' }
}
