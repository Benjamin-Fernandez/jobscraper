// A fake of the JobScraper API, backed by the same fixture shortlist the Python
// tests use (tests/fixtures/shortlist.json, the PRD 8.3[6] shape). Every call is
// recorded so tests can assert exactly which requests the UI made. Status writes
// behave like the real store: an event is appended only on a real change.
//
// It also plays the M11 contract (settings, background jobs, profile, resume
// upload) exactly as the PRD's M11 API table states it, so the tabs are built
// against the contract, not against whatever the backend happens to do. Pass
// `m11: false` for a server without those routes (every one answers 404).
import { vi } from 'vitest'
import shortlist from '../../tests/fixtures/shortlist.json'

export const FIXTURE = shortlist
export const STATUSES = ['to_apply', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn']
export const MB = 1024 * 1024
export const DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

// jsdom keeps one URL per test file; start every test from a known hash.
export function setHash(hash = '') {
  window.history.replaceState(null, '', `${window.location.pathname}${hash}`)
}

export function runsFrom(fixture = shortlist) {
  return fixture.runs.map(r => ({ ...r, status: 'ok' }))
}

export function defaultSettings() {
  return { batch_size: 10, batch_size_default: 10, enabled_companies: 224, cycle_days: 14, runs_per_day_needed: 1.6 }
}

export function defaultProfile() {
  return {
    present: true,
    profile_version: 2,
    source_file: 'resume.pdf',
    parsed_at: '2026-09-24T10:05:00',
    summary: 'Computer science graduate with cloud and backend internships.',
    skills: ['python', 'kubernetes', 'terraform'],
    target_titles: ['software engineer', 'site reliability engineer'],
    interests: ['infrastructure', 'fintech'],
  }
}

const IDLE = { id: null, kind: null, state: 'idle', started_at: null, finished_at: null, exit_code: null, log: [] }

function respond(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: { 200: 'OK', 202: 'Accepted', 404: 'Not Found', 409: 'Conflict', 413: 'Payload Too Large', 415: 'Unsupported Media Type', 422: 'Unprocessable Entity' }[status] ?? 'Error',
    json: async () => JSON.parse(JSON.stringify(body)),
  }
}

// A file's first bytes, the way the server checks them (M11-T4).
async function magic(body) {
  if (!body || typeof body.slice !== 'function') return ''
  const head = body.slice(0, 4)
  if (typeof head.text === 'function') return head.text()
  return new Promise(resolve => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.readAsText(head)
  })
}

// statuses: { job_id: status } - seeded as if each was set once.
// vocabulary: the ordered status list config serves via /api/stats (M8-T2).
export function fakeApi({
  fixture = shortlist, statuses = {}, vocabulary = STATUSES,
  m11 = true, settings = defaultSettings(), profile = defaultProfile(), job = null,
} = {}) {
  const calls = []
  const apps = {}
  const runs = runsFrom(fixture)
  const server = { settings: { ...settings }, profile: { ...profile }, job: job ? { ...IDLE, ...job } : { ...IDLE }, resume: null }
  let eventId = 0
  let jobId = 0
  let clock = 0
  const stamp = () => `2026-09-24T08:${String(10 + clock++).padStart(2, '0')}:00`

  function write(id, status, notes = null) {
    const prev = apps[id]
    const app = prev ?? { status: null, notes: null, events: [] }
    const changed = app.status !== status
    if (changed) {
      app.events.push({ id: ++eventId, job_id: id, from_status: app.status, to_status: status, at: stamp() })
    }
    app.status = status
    if (notes !== null) app.notes = notes
    apps[id] = app
    return changed
  }
  for (const [id, s] of Object.entries(statuses)) write(id, s)

  function startJob(kind) {
    if (server.job.state === 'running') return respond({ detail: 'a job is already running' }, 409)
    server.job = { id: ++jobId, kind, state: 'running', started_at: stamp(), finished_at: null, exit_code: null, log: [] }
    return respond(server.job, 202)
  }

  function runsPerDay(batch) {
    const { enabled_companies: n, cycle_days: days } = server.settings
    return Math.round((Math.ceil(n / batch) / days) * 10) / 10
  }

  async function m11Route(url, init) {
    const method = init.method || 'GET'
    if (url === 'api/settings' && method === 'GET') return respond(server.settings)
    if (url === 'api/settings' && method === 'PUT') {
      const { batch_size: n } = JSON.parse(init.body)
      if (!Number.isInteger(n) || n < 1 || n > server.settings.enabled_companies) {
        return respond({ detail: `batch_size must be between 1 and ${server.settings.enabled_companies}` }, 422)
      }
      server.settings = { ...server.settings, batch_size: n, runs_per_day_needed: runsPerDay(n) }
      return respond(server.settings)
    }
    if (url === 'api/jobs/run' && method === 'POST') return startJob('run')
    if (url === 'api/jobs/profile' && method === 'POST') return startJob('profile')
    if (/^api\/jobs\/current(\?|$)/.test(url)) return respond(server.job)
    if (url === 'api/jobs/cancel' && method === 'POST') {
      if (server.job.state !== 'running') return respond({ detail: 'no job is running' }, 409)
      server.job = { ...server.job, state: 'failed', exit_code: -15, finished_at: stamp(), log: [...server.job.log, 'cancelled'] }
      return respond(server.job)
    }
    if (url === 'api/profile') return respond(server.profile)
    if (url === 'api/resume' && method === 'PUT') {
      const type = init.headers?.['Content-Type'] ?? ''
      const body = init.body
      if (!['application/pdf', DOCX].includes(type)) return respond({ detail: `unsupported type ${type}` }, 415)
      if (body.size > 5 * MB) return respond({ detail: 'resume is larger than 5 MB' }, 413)
      const head = await magic(body)
      if (!(head.startsWith('%PDF') || head.startsWith('PK'))) return respond({ detail: 'not a PDF or DOCX file' }, 415)
      const saved = type === 'application/pdf' ? 'resume.pdf' : 'resume.docx'
      server.resume = { saved, bytes: body.size, sha256: 'ab'.repeat(32) }
      return respond(server.resume)
    }
    return null
  }

  const fetch = vi.fn(async (url, init = {}) => {
    calls.push({ url, method: init.method || 'GET', body: init.body, headers: init.headers })
    if (url === 'api/runs') return respond(runs)
    if (url === 'api/stats') {
      const byStatus = Object.fromEntries(vocabulary.map(s => [s, 0]))
      for (const a of Object.values(apps)) byStatus[a.status] = (byStatus[a.status] ?? 0) + 1
      return respond({ statuses: vocabulary, by_status: byStatus, by_run: {} })
    }
    if (url === 'api/applications') {
      return respond(Object.entries(apps).map(([id, a]) => {
        const j = fixture.jobs.find(x => x.id === id) ?? {}
        return {
          job_id: id, status: a.status, notes: a.notes,
          company: j.company ?? null, role: j.title ?? null, url: j.url ?? null,
          run_no: j.run_no ?? null, events: a.events,
        }
      }))
    }
    const m = /^api\/shortlist\?run=(\w+)$/.exec(url)
    if (m) {
      const nums = fixture.runs.map(r => r.run_no)
      const run = m[1] === 'latest' ? Math.max(...nums) : m[1] === 'all' ? 'all' : Number(m[1])
      const jobs = fixture.jobs
        .filter(j => run === 'all' || j.run_no === run)
        .map(j => ({ ...j, closed: false, status: apps[j.id]?.status ?? null, notes: null }))
      return respond(jobs)
    }
    const post = /^api\/applications\/(\w+)$/.exec(url)
    if (post && init.method === 'POST') {
      const { status, notes } = JSON.parse(init.body)
      const appended = write(post[1], status, notes ?? null)
      return respond({ job_id: post[1], status, event_appended: appended })
    }
    if (m11) {
      const answer = await m11Route(url, init)
      if (answer) return answer
    }
    return respond({ detail: 'Not Found' }, 404)
  })

  // Test controls for the running job.
  function log(...lines) {
    server.job = { ...server.job, log: [...server.job.log, ...lines] }
  }
  // End the job. A finished run appears in /api/runs, as the store would record it.
  function finishJob({ exit_code = 0 } = {}) {
    const ok = exit_code === 0
    server.job = { ...server.job, state: ok ? 'succeeded' : 'failed', exit_code, finished_at: stamp() }
    if (server.job.kind === 'run') {
      const n = Math.max(0, ...runs.map(r => r.run_no)) + 1
      runs.unshift({ run_no: n, finished_at: '2026-09-25T09:30:00', status: ok ? 'ok' : 'failed', accepted: 0 })
    }
    if (server.job.kind === 'profile' && ok) {
      server.profile = { ...server.profile, present: true, profile_version: (server.profile.profile_version ?? 0) + 1, source_file: server.resume?.saved ?? server.profile.source_file }
    }
  }
  const count = pattern => calls.filter(c => pattern.test(c.url)).length

  return { fetch, calls, apps, server, runs, log, finishJob, count }
}
