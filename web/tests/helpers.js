// A fake of the JobScraper API, backed by the same fixture shortlist the Python
// tests use (tests/fixtures/shortlist.json, the PRD 8.3[6] shape). Every call is
// recorded so tests can assert exactly which requests the UI made. Status writes
// behave like the real store: an event is appended only on a real change.
import { vi } from 'vitest'
import shortlist from '../../tests/fixtures/shortlist.json'

export const FIXTURE = shortlist
export const STATUSES = ['to_apply', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn']

// jsdom keeps one URL per test file; start every test from a known hash.
export function setHash(hash = '') {
  window.history.replaceState(null, '', `${window.location.pathname}${hash}`)
}

export function runsFrom(fixture = shortlist) {
  return fixture.runs.map(r => ({ ...r, status: 'ok' }))
}

function respond(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status === 200 ? 'OK' : 'Error',
    json: async () => JSON.parse(JSON.stringify(body)),
  }
}

// statuses: { job_id: status } - seeded as if each was set once.
// vocabulary: the ordered status list config serves via /api/stats (M8-T2).
export function fakeApi({ fixture = shortlist, statuses = {}, vocabulary = STATUSES } = {}) {
  const calls = []
  const apps = {}
  let eventId = 0
  let clock = 0
  const stamp = () => `2026-09-24T08:${String(10 + clock++).padStart(2, '0')}:00`

  function write(jobId, status, notes = null) {
    const prev = apps[jobId]
    const app = prev ?? { status: null, notes: null, events: [] }
    const changed = app.status !== status
    if (changed) {
      app.events.push({ id: ++eventId, job_id: jobId, from_status: app.status, to_status: status, at: stamp() })
    }
    app.status = status
    if (notes !== null) app.notes = notes
    apps[jobId] = app
    return changed
  }
  for (const [id, s] of Object.entries(statuses)) write(id, s)

  const fetch = vi.fn(async (url, init = {}) => {
    calls.push({ url, method: init.method || 'GET', body: init.body })
    if (url === 'api/runs') return respond(runsFrom(fixture))
    if (url === 'api/stats') {
      const byStatus = Object.fromEntries(vocabulary.map(s => [s, 0]))
      for (const a of Object.values(apps)) byStatus[a.status] = (byStatus[a.status] ?? 0) + 1
      return respond({ statuses: vocabulary, by_status: byStatus, by_run: {} })
    }
    if (url === 'api/applications') {
      return respond(Object.entries(apps).map(([jobId, a]) => {
        const job = fixture.jobs.find(j => j.id === jobId) ?? {}
        return {
          job_id: jobId, status: a.status, notes: a.notes,
          company: job.company ?? null, role: job.title ?? null, url: job.url ?? null,
          run_no: job.run_no ?? null, events: a.events,
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
    return respond({ detail: 'not found' }, 404)
  })
  return { fetch, calls, apps }
}
