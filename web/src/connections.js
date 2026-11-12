// What the Connected accounts hub, the shell badge/banner and the setup checklist
// say about a connection (Q-100 design §2, §4.2, §4.4). Pure: the server computes
// each item's `state` and `code` (GET /api/connections, schema v1); this module
// turns them into words, a chip tone and counts. No fetching, no Vue.
//
// A connection is shown by its words first: the chip text always names the state,
// colour only helps (WCAG 1.4.1). Nothing here ever touches a secret - the response
// carries none (D-191).
import { when } from './format.js'

// ---- states and chips (§2.1) ----

export const STATES = ['connected', 'attention', 'neutral', 'not_set_up', 'paused', 'checking']

// The CSS tone behind a state: `.state-chip[data-tone=...]` in style.css. The six
// states have six tones; `neutral` is drawn like `not_set_up` (grey).
export function chipTone(state) {
  return STATES.includes(state) ? state : 'neutral'
}

// Chip words for codes whose state alone would say too little (§2.1).
const NEUTRAL_TEXT = {
  not_running: 'Not running',
  unreachable: 'Not running',
  model_missing: 'Model not downloaded',
  unconfirmed: 'Not confirmed',
  check_failed: "Couldn't check",
}

// The chip's default text for an item (or employer row): "Connected", "Needs
// attention", "Not running", "Optional", "Ready" for the Edge profile.
export function chipText(item) {
  const state = item?.state
  const kind = item?.kind
  switch (state) {
    case 'connected':
      if (kind === 'edge') return item.code === 'in_use' ? 'In use' : 'Ready'
      return 'Connected'
    case 'attention': return 'Needs attention'
    case 'neutral': return NEUTRAL_TEXT[item.code] ?? "Couldn't check"
    case 'not_set_up': return item.optional ? 'Optional' : 'Not set up'
    case 'paused': return 'Paused'
    case 'checking': return 'Checking…'
    default: return "Couldn't check"
  }
}

// The label of a card's fix disclosure (Q-104 c): an optional item nobody has set
// up is an invitation ("Set it up"); only a broken one is a repair ("See how to fix").
export function fixLabel(item) {
  return item?.optional && item.state === 'not_set_up' ? 'Set it up' : 'See how to fix'
}

// ---- copy (§4.4) ----

// Fixed lines the screens share (§4.4). Sentence case, what happened and how to fix.
export const COPY = Object.freeze({
  checkFailed: "Couldn't check this just now. Try again in a moment.",
  hubError: "Couldn't load your connections.",
  employerEmpty: 'No employer accounts yet. JobScraper creates one only when an application on a Workday site needs it, and lists it here.',
  readPassword: 'To see a password, open Windows Credential Manager (Windows asks for your password first), or, in PowerShell, in the JobScraper folder, run `.\\run.ps1 accounts export-edge` to import them into Edge.',
  setupAllFailed: "Couldn't check your setup just now.",
  browserNote: 'Created the first time an application runs. Sign-ins you make there are kept between restarts.',
  modeChip: 'Auto-apply on',
  modeChipTitle: 'JobScraper sends applications after a passing check. Change it in Settings → Apply.',
  modeDryRun: 'Dry run. JobScraper fills each form and leaves it open for you. Nothing is sent.',
  modeAuto: 'Automatic. JobScraper sends an application only after its final check passes.',
  noAccountNeeded: 'They apply as a guest.',
})

// The employer-row copy by code (§4.4); `ok` and `verified` say nothing.
const EMPLOYER_COPY = {
  signin_failed: "Sign-in failed. JobScraper won't try again, so the account isn't locked.",
  exists_no_password: "An account already exists for this email, and JobScraper doesn't have its password.",
  password_missing: 'The password is missing from Windows Credential Manager.',
  unconfirmed: 'Not confirmed. The sign-up may not have finished; JobScraper signs in with it next time.',
}

const DAY_MS = 24 * 60 * 60 * 1000

function gmailCopy(item, now) {
  switch (item.code) {
    case 'timer_off': return 'Automatic checks are off in this copy of the app. Use Check now.'
    case 'retrying': {
      const at = item.retry_after ? when(item.retry_after) : ''
      return at
        ? `The last check couldn't reach Gmail. Trying again at ${at}.`
        : "The last check couldn't reach Gmail. Trying again soon."
    }
    case 'switched_off': return 'Email updates are switched off. Switch them on to see status changes from email.'
    case 'consent': return 'Review how JobScraper reads this mailbox, then confirm.'
    case 'none': return 'Optional. Connect Gmail to see application status changes from email.'
    default: break
  }
  // The server's own words for a sync code (SYNC_TEXTS) win: they already say why.
  if (item.message) return item.message
  if (item.state === 'attention') {
    const t = item.last_ok_at ? Date.parse(`${String(item.last_ok_at).slice(0, 19)}Z`) : NaN
    const stale = Number.isNaN(t) || now - t > DAY_MS
    if (stale) {
      return item.last_ok_at
        ? `Gmail hasn't been checked since ${when(item.last_ok_at)}. Check now to see why.`
        : "Gmail hasn't been checked yet. Check now to see why."
    }
  }
  return null
}

function mailboxCopy(item) {
  const address = item.facts?.username
  switch (item.code) {
    case 'no_password':
      return `No app password is saved for ${address || 'this mailbox'}. Sites that email a code will stop at that step.`
    case 'none': return 'Optional. Needed only when an employer site emails you a code.'
    case 'ok': return 'Reads verification codes during applications. Also used for updates.'
    default: return null
  }
}

function edgeCopy(item) {
  switch (item.code) {
    case 'none': return COPY.browserNote
    case 'in_use': return 'In use by an application right now.'
    case 'ok': return 'Edge profile used only by JobScraper. Sign-ins are kept between restarts.'
    default: return null
  }
}

function modelCopy(item, ctx) {
  const model = item.facts?.model || 'The model'
  switch (item.code) {
    case 'ai_off':
      return 'Local AI is off in config.yaml (budget.enable_llm). Runs still work; screening and auto-apply wait for it.'
    case 'misconfigured':
      return "The AI setting in config.yaml isn't one JobScraper knows. Set budget.backend to ollama or off."
    case 'unreachable':
      return item.state === 'attention'
        ? `Ollama isn't running, and ${ctx.what || 'a task'} is waiting for it. Start Ollama, then check again.`
        : "Ollama isn't running. Nothing needs it right now."
    case 'model_missing':
      return `The model ${model} isn't downloaded. Run \`ollama pull ${model}\`, then check again.`
    case 'probing': return 'Checking the local AI…'
    case 'ok':
      return item.facts?.local === false ? `${model} through Ollama (not on this PC).` : `${model} runs on this PC.`
    default: return null
  }
}

// The line under a chip: the words for an item's `code` (§4.4). `item` is an entry
// of `items` or a row of `employer_accounts` (it has `ats` and no `kind`). `ctx`
// may carry `what` (what is waiting for the model: "a run", "an application",
// "3 emails") and `now` (ms, for the 24-hour stale rule). Returns null when the
// code has nothing to add - the caller then shows the chip alone.
export function codeCopy(item, ctx = {}) {
  if (!item) return null
  const now = ctx.now ?? Date.now()
  if (item.code === 'check_failed') return COPY.checkFailed
  const kind = item.kind ?? (item.ats ? 'employer' : '')
  switch (kind) {
    case 'gmail': return gmailCopy(item, now)
    case 'apply_mailbox': return mailboxCopy(item)
    case 'employer': return EMPLOYER_COPY[item.code] ?? null
    case 'employer_accounts': return item.state === 'not_set_up' ? COPY.employerEmpty : null
    case 'edge': return edgeCopy(item)
    case 'model': return modelCopy(item, ctx)
    default: return item.message ?? null
  }
}

// ---- attention (§2.2) ----

const MODEL_CODES = new Set(['unreachable', 'model_missing'])

// Does one item need the owner now? The server decided `state`; the model is the
// exception that the client double-checks: an Ollama that is down is a problem only
// when something is waiting for it (`facts.need_now`), never "because it is down".
function needsAttention(item) {
  if (item?.kind === 'model' && MODEL_CODES.has(item.code) && typeof item.facts?.need_now === 'boolean') {
    return item.facts.need_now
  }
  return item?.state === 'attention'
}

function itemsOf(response) {
  return Array.isArray(response?.items) ? response.items : []
}

// The items that need attention, given this load (`response`, a GET /api/connections
// answer) and the one before it (`history`, or null). One failed check is a blip and
// shows as neutral "Couldn't check"; the same item failing in two loads in a row
// (`check_failed` both times) counts (researcher m1). A failed load (null) counts
// nothing: no badge, never a false "all good" either.
export function attentionItems(response, history = null) {
  const previous = new Map(itemsOf(history).map(i => [i.id, i]))
  return itemsOf(response).filter(item => {
    if (needsAttention(item)) return true
    return item.code === 'check_failed' && previous.get(item.id)?.code === 'check_failed'
  })
}

// How many items need attention: the number on the Settings tab.
export function attentionCount(response, history = null) {
  return attentionItems(response, history).length
}

// ---- first-run setup, part 2: "Apply for me" (§4.2) ----

const DETAILS_HREF = '#/profile/details'

function stepFromItem(base, item, doneWhen) {
  if (!item) return { ...base, status: 'unknown', done: false, hint: "Couldn't check" }
  if (item.state === 'checking') return { ...base, status: 'checking', done: false, hint: 'Checking…' }
  const done = doneWhen(item)
  return { ...base, status: done ? 'done' : 'todo', done }
}

// { connections, applicant } -> { steps, done, total, allFailed, note }.
// `connections` is the GET /api/connections answer and `applicant` the
// getApplicantSummary() result; null or undefined means that check failed or the
// feature is absent. A step the app couldn't check has status 'unknown' and is not
// counted; "n of m" counts REQUIRED steps only, and Optional ones are never
// counted (Res m2). `allFailed` means no required step could be checked, so the
// page shows COPY.setupAllFailed instead of "0 of 2".
export function applySteps({ connections = null, applicant = null } = {}) {
  const items = itemsOf(connections)
  const steps = []

  // Details come from the applicant file, which exists whether or not auto-apply does.
  const missing = Array.isArray(applicant?.missing) ? applicant.missing : null
  steps.push(missing === null
    ? {
      id: 'details', label: 'Fill in your application details', href: DETAILS_HREF, cta: 'Fill in details',
      required: true, status: 'unknown', done: false, hint: "Couldn't check",
    }
    : {
      id: 'details', label: 'Fill in your application details', href: DETAILS_HREF, cta: 'Fill in details',
      required: true, status: missing.length ? 'todo' : 'done', done: missing.length === 0,
      hint: missing.length ? `${missing.length} missing` : 'Ready',
    })

  // Local AI is required; "off in settings" counts as done (an owner's choice).
  const model = stepFromItem(
    { id: 'model', label: 'Local AI', href: '#/settings/accounts/model', cta: 'Check again', required: true },
    items.find(i => i.kind === 'model'),
    i => i.state === 'connected' || (i.state === 'paused' && i.code === 'ai_off'),
  )
  if (model.status === 'done') model.hint = items.find(i => i.kind === 'model').code === 'ai_off' ? 'Off in settings' : 'Connected'
  else if (model.status === 'todo') model.hint = codeCopy(items.find(i => i.kind === 'model')) || 'Not ready'
  steps.push(model)

  // Optional: the application mailbox and Gmail.
  const mailbox = items.find(i => i.kind === 'apply_mailbox')
  steps.push({
    id: 'mailbox', label: 'Application mailbox', href: '#/settings/accounts/apply-mailbox', cta: 'Set up',
    required: false, status: mailbox ? (mailbox.state === 'connected' ? 'done' : 'todo') : 'unknown',
    done: mailbox?.state === 'connected',
    hint: mailbox?.state === 'connected' ? 'Connected' : 'For sites that email a code',
  })
  const gmail = items.filter(i => i.kind === 'gmail')
  const gmailOn = gmail.find(i => i.state === 'connected')
  steps.push({
    id: 'gmail', label: 'Email updates', href: '#/settings/accounts/gmail', cta: 'Connect',
    required: false, status: connections ? (gmailOn ? 'done' : 'todo') : 'unknown',
    done: Boolean(gmailOn),
    hint: gmailOn ? 'Gmail' : 'Gmail, to see status changes from email',
  })

  const counted = steps.filter(s => s.required && s.status !== 'unknown' && s.status !== 'checking')
  const required = steps.filter(s => s.required)
  return {
    steps,
    done: counted.filter(s => s.done).length,
    total: counted.length,
    allFailed: required.every(s => s.status === 'unknown'),
    note: 'The apply browser is created the first time an application runs.',
  }
}
