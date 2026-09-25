// The only module that knows the API's URLs. The base is relative to the page,
// never a host: the same bundle then works on 127.0.0.1, behind a proxy, or in
// a container (PRD 8.6).
const BASE = 'api/'

// An API failure that keeps its HTTP status, so a tab can say something useful
// about a 409 or a 422 instead of printing the raw response.
export class ApiError extends Error {
  constructor(status, statusText, detail) {
    // FastAPI's own 404 says "Not Found" twice; say it once.
    const quiet = detail === undefined || detail === '' || detail === statusText
    const shown = quiet ? '' : ` - ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`
    super(`${status} ${statusText}${shown}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function request(path, init) {
  const res = await fetch(BASE + path, init)
  if (!res.ok) {
    let detail = ''
    try { detail = (await res.json()).detail ?? '' } catch { /* not JSON */ }
    throw new ApiError(res.status, res.statusText, detail)
  }
  return res.json()
}

function sendJson(path, method, body) {
  return request(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

// A sentence for the page, not a stack trace. A 404 on a route this bundle
// expects means the server is older than the UI, which is worth saying plainly.
export function describeError(e) {
  if (e instanceof ApiError && e.status === 404) {
    return `${e.message}. This server does not offer that yet - update JobScraper and restart the web app.`
  }
  return String(e?.message || e)
}

export function getRuns() {
  return request('runs')
}

// `run` is a run number, 'latest' or 'all'.
export function getShortlist(run) {
  return request(`shortlist?run=${encodeURIComponent(run)}`)
}

// Everything with a status, each row carrying its `events` timeline.
export function getApplications() {
  return request('applications')
}

// Counts, plus `statuses`: the ordered status vocabulary from config.
export function getStats() {
  return request('stats')
}

// Record an application status. `details` (company, role, url) is kept on the
// application row so the record survives the posting leaving the shortlist.
export function setApplicationStatus(jobId, status, { notes, ...details } = {}) {
  return sendJson(`applications/${encodeURIComponent(jobId)}`, 'POST',
    { status, notes: notes ?? null, ...details })
}

// ---- M11: control from the web app (PRD section 10, M11 API contract) ----

// {batch_size, batch_size_default, enabled_companies, cycle_days, runs_per_day_needed}
export function getSettings() {
  return request('settings')
}

export function saveSettings({ batch_size }) {
  return sendJson('settings', 'PUT', { batch_size })
}

// 202 + job, or 409 when a job is already running.
export function startRun({ batch_size, dry_run } = {}) {
  const body = {}
  if (batch_size !== undefined && batch_size !== null) body.batch_size = batch_size
  if (dry_run) body.dry_run = true
  return sendJson('jobs/run', 'POST', body)
}

// Re-derive the profile from the stored resume. 202 + job, or 409 when busy.
export function startProfileRefresh() {
  return sendJson('jobs/profile', 'POST')
}

// {id, kind, state: idle|running|succeeded|failed, started_at, finished_at, exit_code, log}
export function getCurrentJob(tail = 200) {
  return request(`jobs/current?tail=${encodeURIComponent(tail)}`)
}

export function cancelJob() {
  return sendJson('jobs/cancel', 'POST')
}

// {present, profile_version, source_file, parsed_at, summary, skills, target_titles, interests}
export function getProfile() {
  return request('profile')
}

export const RESUME_TYPES = {
  pdf: 'application/pdf',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}

// The file goes up as the raw request body with its own type - never as
// multipart/form-data, which the server refuses (M11: a cross-site form cannot
// send a non-form content type without a CORS preflight the app never grants).
// Some browsers report an empty type for .docx, so the extension decides then.
export function uploadResume(file) {
  const ext = (/\.([a-z0-9]+)$/i.exec(file.name || '')?.[1] || '').toLowerCase()
  const type = file.type || RESUME_TYPES[ext] || 'application/octet-stream'
  return request('resume', { method: 'PUT', headers: { 'Content-Type': type }, body: file })
}
