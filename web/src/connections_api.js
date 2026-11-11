// The calls behind the Connected accounts hub, the shell signals and the Apply
// settings (Q-100 design §3, §4.3). Kept apart from api.js so three lanes can build
// on it without touching a shared file; it reuses api.js's `request`, so errors are
// the same ApiError.
//
// Several of these routes may not exist on the server in front of this bundle
// (`/api/connections` and `/api/apply/settings` land after the page does): a 404 or
// 405 means "this feature is absent" and answers `null`, which a screen draws as
// "hide the row", never as an error. Any other failure throws, as api.js does.
//
// No call here sends or expects a secret: the server never returns a password and
// these helpers never post one (D-191). Passwords are Wave 2, through the CLI.
import { ApiError, request } from './api.js'

const ABSENT = new Set([404, 405])

// Run a request; an absent route answers null.
async function orAbsent(path, init) {
  try {
    return await request(path, init)
  } catch (e) {
    if (e instanceof ApiError && ABSENT.has(e.status)) return null
    throw e
  }
}

function json(method, body) {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  }
}

// GET /api/connections -> schema v1 { version, checked_at, attention, items,
// employer_accounts, no_account_needed }, or null when the server has no hub yet.
export function getConnections() {
  return orAbsent('connections')
}

// POST /api/connections/model/check -> 202: "Check again" on the Local AI card. The
// probe runs in the background; the hub polls GET /api/connections afterwards.
export function checkModel() {
  return orAbsent('connections/model/check', { method: 'POST' })
}

// GET /api/apply/status -> { mode: 'auto'|'dry_run', missing: [paths], busy }, or null.
export function getApplyStatus() {
  return orAbsent('apply/status')
}

// GET /api/apply/settings (Q-111) -> { mode, writable, compose_enabled, ...limits },
// or null while the server doesn't offer it.
export function getApplySettings() {
  return orAbsent('apply/settings')
}

// PUT /api/apply/settings with the fields being changed. Resolves to the saved
// settings, or null when the server has no such route; a 422 throws an ApiError
// whose `detail` the caller shows as "Couldn't save: {detail}". Only call this
// after getApplySettings() said `writable: true`: a probe PUT would pin `apply.*`
// rows over config.yaml (design §4.3).
export function putApplySettings(changes) {
  return orAbsent('apply/settings', json('PUT', changes))
}

// What setup and Settings → Apply need from GET /api/applicant, and no more:
// { missing: [dotted paths], completeness: {filled, needed}, form }. The profile
// itself and its etag are dropped here, so a caller can't keep them by accident.
// null when the route is absent.
export async function getApplicantSummary() {
  const data = await orAbsent('applicant')
  if (!data) return null
  return {
    missing: Array.isArray(data.missing) ? data.missing : [],
    completeness: data.completeness ?? null,
    form: data.form ?? null,
  }
}
