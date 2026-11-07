// The only module that knows the API's URLs. The base is relative to the page,
// never a host: the same bundle then works on 127.0.0.1, behind a proxy, or in
// a container (PRD 8.6).
const BASE = 'api/'

// An API failure that keeps its HTTP status, so a tab can say something useful
// about a 409 or a 422 instead of printing the raw response.
export class ApiError extends Error {
  constructor(status, statusText, detail, body = null) {
    // FastAPI's own 404 says "Not Found" twice; say it once.
    const quiet = detail === undefined || detail === '' || detail === statusText
    const shown = quiet ? '' : ` - ${typeof detail === 'string' ? detail : JSON.stringify(detail)}`
    super(`${status} ${statusText}${shown}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
    // The whole JSON answer, for the routes whose 409/422 carry more than a
    // `detail` (the applicant form's `errors`, a retry's `job_ids`; U-block).
    this.body = body
  }
}

async function request(path, init) {
  const res = await fetch(BASE + path, init)
  if (!res.ok) {
    let detail = ''
    let body = null
    try { body = await res.json(); detail = body?.detail ?? '' } catch { /* not JSON */ }
    throw new ApiError(res.status, res.statusText, detail, body)
  }
  if (res.status === 204) return null   // dismiss answers with no body
  return res.json()
}

function sendJson(path, method, body) {
  return request(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

// FastAPI's own 422 is a list of {msg}; ours is a string. Either way, words.
function detailText(detail) {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    return detail.map(d => String(d?.msg ?? d).replace(/^Value error, /, '')).join('; ')
  }
  return ''
}

// A sentence for the page, not a stack trace. A 404 on a route this bundle
// expects means the server is older than the UI, which is worth saying plainly.
export function describeError(e) {
  if (e instanceof ApiError && e.status === 404) {
    return `${e.message}. This server does not offer that yet - update JobScraper and restart the web app.`
  }
  if (e instanceof ApiError && [413, 415, 422].includes(e.status)) {
    const text = detailText(e.detail)
    if (text) return text
  }
  return String(e?.message || e)
}

// Why a finished job did not succeed, in words: cancelled, else `fallback`.
export function failureText(job, fallback) {
  if (job?.reason === 'cancelled') return 'The job was cancelled.'
  return fallback
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

// One posting's full description, for the Inbox's detail pane (M16).
// {job_id, title, company, location, posted_at, url, description}
export function getPosting(jobId) {
  return request(`postings/${encodeURIComponent(jobId)}`)
}

// Undo tracking (M13): the application and its history are removed and the role
// is back in the Inbox with no status. 404 when there was nothing to remove.
export function untrackApplication(jobId) {
  return request(`applications/${encodeURIComponent(jobId)}`, { method: 'DELETE' })
}

// ---- M11: control from the web app (PRD section 10, M11 API contract) ----

// {batch_size, batch_size_default, enabled_companies, cycle_days,
//  cycle_days_default, cycle_day_options, plan, runs_per_day_needed}
export function getSettings() {
  return request('settings')
}

// Either or both: { batch_size }, { cycle_days } (M15). The server validates
// cycle_days against the plan's options.
export function saveSettings({ batch_size, cycle_days } = {}) {
  const body = {}
  if (batch_size !== undefined) body.batch_size = batch_size
  if (cycle_days !== undefined) body.cycle_days = cycle_days
  return sendJson('settings', 'PUT', body)
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

// ---- M15: the job titles the title filter searches for ----

// {titles, source: 'custom'|'resume', resume_titles, max_titles,
//  max_suggestions, plan, suggestions: null | {generated_at, model,
//  field_of_study, experience, items: [{title, why}]}}
export function getTitles() {
  return request('titles')
}

// The full list, in order. 422 past the plan's limit, or for an empty list.
export function saveTitles(titles) {
  return sendJson('titles', 'PUT', { titles })
}

// Back to the resume's titles.
export function resetTitles() {
  return request('titles', { method: 'DELETE' })
}

// Ask Qwen for recommendations: a background job like a run. 202, or 409 when busy.
export function startTitleSuggestions() {
  return sendJson('jobs/titles', 'POST')
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

// ---- M16: the user's own list of companies ----

// {items: [{position, name, status, careers_url, provider, postings, detail,
//  searched_at}], counts, searched, max_companies, plan}
// status: pending | searching | found | watched | failed | over_limit
export function getCompanyList() {
  return request('companies/list')
}

export const LIST_TYPES = {
  txt: 'text/plain',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}

// One company per line, in the user's order of preference. Sent raw like the
// resume. The answer is the list plus `upload: {read, kept, new, dropped, capped}`.
export function uploadCompanyList(file) {
  const ext = (/\.([a-z0-9]+)$/i.exec(file.name || '')?.[1] || '').toLowerCase()
  const type = LIST_TYPES[ext] || file.type || 'application/octet-stream'
  return request('companies/list', { method: 'PUT', headers: { 'Content-Type': type }, body: file })
}

export function clearCompanyList() {
  return request('companies/list', { method: 'DELETE' })
}

// Search the list's unsearched companies: a background job. 202, or 409 when busy.
export function startCompanySearch() {
  return sendJson('jobs/companies', 'POST')
}

// ---- M17 ----

// "Not interested", kept on the server: the role moves to the Inbox's
// Not interested section and stays there after a restart. DELETE moves it back.
export function dismissRole(jobId) {
  return request(`dismissals/${encodeURIComponent(jobId)}`, { method: 'PUT' })
}

export function undismissRole(jobId) {
  return request(`dismissals/${encodeURIComponent(jobId)}`, { method: 'DELETE' })
}

// Every watched company and whether it can be scanned:
// {total, counts: {ok, failed, not_scanned}, items: [...]}
export function getCompanyHealth() {
  return request('companies/health')
}

// The same list as a CSV file (the browser downloads it).
export const COMPANY_EXPORT_URL = 'api/companies/export.csv'

// ---- Q-30 (D-74): Application details and Questions from applications ----
// The shapes are fixed in docs/architecture/questions_design.md section 9.

// {profile, etag, errors:[{path,message}], missing:[path], completeness:{filled,needed},
//  from_resume:[path], sensitive:[path], form:[group], file:{exists, has_comments, error}}
export function getApplicant() {
  return request('applicant')
}

// {profile, etag}. 200 is the same shape as GET with the new etag; 409 is
// {detail:'changed'|'unreadable'}; 422 is {detail:'invalid', errors:[{path,message}]}.
export function saveApplicant(profile, etag) {
  return sendJson('applicant', 'PUT', { profile, etag })
}

// {profile} -> {errors:[{path,message}]}: the PUT's checks on a profile that is
// not saved (Q71-18, a field checked when the owner leaves it). Nothing is
// written; an older server answers 404 and the form simply stops asking.
export function checkApplicant(profile) {
  return sendJson('applicant/check', 'POST', { profile })
}

// {mode:'auto'|'dry_run', groups:[...], ready:[{job_id,attempt_id,company,title}],
//  waiting:[...], busy}. `status` is open, answered or all.
export function getQuestions(status = 'open') {
  return request(`questions?status=${encodeURIComponent(status)}`)
}

// body: {key, etag, employer?, value?, picks?}. 200 {answered, ready, etag}; 404 unknown
// key; 409 changed/unreadable; 422 invalid.
export function answerQuestion(body) {
  return sendJson('questions/answer', 'POST', body)
}

// "I'll answer this one by hand": 204, no body.
export function dismissQuestion(key) {
  return request(`questions/${encodeURIComponent(key)}/dismiss`, { method: 'POST' })
}

// Run the apply job again for jobs that stopped on a question now answered.
// 202 + job; 409 {detail:'busy'}; 422 {detail:'not_ready', job_ids}.
export function retryQuestions(jobIds) {
  return sendJson('questions/retry', 'POST', { job_ids: jobIds })
}

// ---- Q-60 (F-50): application status from email ----
// The shapes are fixed in docs/architecture/mail_status_design.md section 11.1.
// An app password goes out in one request body and nowhere else: these helpers
// take it as an argument and keep no copy (MS section 13).

// {enabled, interval_min, consent: {version, text},
//  application_mailbox: {address, ready, connected} | null,
//  accounts: [{id, address, enabled, shared_with_apply, state, code, message,
//    notes: [{code, message}], last_sync_at, last_ok_at, first_sync_from, counts}],
//  sync: {running, started_at, next_at, last: {state, code, finished_at}}, open_suggestions}
export function getMail() {
  return request('mail')
}

// 200 {ok, account_id} | 400 {code, detail} | 409 {code: 'exists', detail}.
export function connectMailbox({ address, appPassword, consentVersion }) {
  return sendJson('mail/accounts', 'POST',
    { address, app_password: appPassword, consent_version: consentVersion })
}

// The application mailbox (F-50b): no password, its vault entry is reused.
export function connectApplicationMailbox(consentVersion) {
  return sendJson('mail/accounts/application', 'POST', { consent_version: consentVersion })
}

export function setMailboxPassword(id, appPassword) {
  return sendJson(`mail/accounts/${encodeURIComponent(id)}/password`, 'PUT', { app_password: appPassword })
}

// The switch: {enabled} -> the account view.
export function setMailboxEnabled(id, enabled) {
  return sendJson(`mail/accounts/${encodeURIComponent(id)}`, 'PATCH', { enabled })
}

// {ok, vault_kept}
export function disconnectMailbox(id) {
  return request(`mail/accounts/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

// 202 {started: true} | 409 {code: 'busy', detail} | 400 {code: 'no_mailbox'}.
export function startMailSync() {
  return sendJson('mail/sync', 'POST')
}

// {suggestions: [{id, job_id, company, role, status, to_status, category, reason,
//  reason_text, quote, subject, sender_domain, received_at,
//  candidates: [{job_id, company, role, status}], gmail_url}]}
export function getMailSuggestions() {
  return request('mail/suggestions')
}

// {ok, status} | 409 {code, detail}. `jobId` only for an ambiguous suggestion.
export function acceptMailSuggestion(id, jobId) {
  return sendJson(`mail/suggestions/${encodeURIComponent(id)}/accept`, 'POST',
    jobId ? { job_id: jobId } : {})
}

export function dismissMailSuggestion(id) {
  return sendJson(`mail/suggestions/${encodeURIComponent(id)}/dismiss`, 'POST')
}

// {ok, status} | 409 {code: 'not_latest', detail}.
export function undoMailChange(evidenceId) {
  return sendJson(`mail/evidence/${encodeURIComponent(evidenceId)}/undo`, 'POST')
}

// A failed mail call as {status, code, detail}. The routes answer {code, detail}
// at the top level; FastAPI's HTTPException nests it under `detail`. Either way.
export function mailProblem(e) {
  if (!(e instanceof ApiError)) return { status: 0, code: '', detail: describeError(e) }
  const nested = e.detail && typeof e.detail === 'object' && !Array.isArray(e.detail) ? e.detail : null
  const code = String(e.body?.code ?? nested?.code ?? '')
  const raw = nested ? nested.detail : e.detail
  const detail = typeof raw === 'string' ? raw : ''
  return { status: e.status, code, detail }
}

// What a failed applicant/questions call means, in one shape: the HTTP status,
// a short `code` ('changed', 'unreadable', 'invalid', 'busy', 'not_ready', ...),
// and the per-field `errors` and `job_ids` the body may carry. The detail may
// arrive as a bare string or nested ({detail:{detail:'invalid', errors}}).
export function problemOf(e) {
  if (!(e instanceof ApiError)) return { status: 0, code: '', errors: [], jobIds: [], text: describeError(e) }
  const inner = e.detail && typeof e.detail === 'object' && !Array.isArray(e.detail) ? e.detail : null
  const code = typeof e.detail === 'string' ? e.detail : String(inner?.detail ?? '')
  const errors = e.body?.errors ?? inner?.errors ?? []
  const jobIds = e.body?.job_ids ?? inner?.job_ids ?? []
  return {
    status: e.status,
    code,
    errors: Array.isArray(errors) ? errors.filter(x => x && typeof x.path === 'string') : [],
    jobIds: Array.isArray(jobIds) ? jobIds : [],
    text: describeError(e),
  }
}
