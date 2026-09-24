// A fake of the JobScraper API, backed by the same fixture shortlist the Python
// tests use (tests/fixtures/shortlist.json, the PRD 8.3[6] shape). Every call is
// recorded so tests can assert exactly which requests the UI made.
import { vi } from 'vitest'
import shortlist from '../../tests/fixtures/shortlist.json'

export const FIXTURE = shortlist

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

// statuses: { job_id: status } merged onto jobs, as the server's join does.
export function fakeApi({ fixture = shortlist, statuses = {} } = {}) {
  const calls = []
  const state = { statuses: { ...statuses } }
  const fetch = vi.fn(async (url, init = {}) => {
    calls.push({ url, method: init.method || 'GET', body: init.body })
    if (url === 'api/runs') return respond(runsFrom(fixture))
    const m = /^api\/shortlist\?run=(\w+)$/.exec(url)
    if (m) {
      const nums = fixture.runs.map(r => r.run_no)
      const run = m[1] === 'latest' ? Math.max(...nums) : m[1] === 'all' ? 'all' : Number(m[1])
      const jobs = fixture.jobs
        .filter(j => run === 'all' || j.run_no === run)
        .map(j => ({ ...j, closed: false, status: state.statuses[j.id] ?? null, notes: null }))
      return respond(jobs)
    }
    const post = /^api\/applications\/(\w+)$/.exec(url)
    if (post && init.method === 'POST') {
      const { status } = JSON.parse(init.body)
      const appended = state.statuses[post[1]] !== status
      state.statuses[post[1]] = status
      return respond({ job_id: post[1], status, event_appended: appended })
    }
    return respond({ detail: 'not found' }, 404)
  })
  return { fetch, calls, state }
}
