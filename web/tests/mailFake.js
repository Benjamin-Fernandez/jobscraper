// A tiny fake of the Q-60 mail routes (mail_status_design.md section 11.1) for the
// MailCard / MailSuggestions / MailEvidence tests. `routes` maps "METHOD path" to a
// handler (body, url) => [status, json] or a plain json. Every call is recorded.
import { vi } from 'vitest'

export const CONSENT = { version: 'test-consent-1', text: 'JobScraper reads this Gmail read-only.' }

export function account(id, fields = {}) {
  return {
    id, address: `box${id}@inbox.example`, enabled: true, shared_with_apply: false, state: 'ok',
    code: null, message: null, notes: [], last_sync_at: '2026-11-02T11:50:00', last_ok_at: '2026-11-02T11:50:00',
    first_sync_from: '2026-05-06T00:00:00', counts: { applied: 1, suggested: 2 }, consent_current: true,
    ...fields,
  }
}

export function mailView(fields = {}) {
  return {
    enabled: true, interval_min: 10, consent: CONSENT, application_mailbox: null,
    accounts: [account(1)], sync: { running: false, started_at: null, next_at: null, last: null },
    open_suggestions: 0, ...fields,
  }
}

function respond(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: { 200: 'OK', 202: 'Accepted', 400: 'Bad Request', 404: 'Not Found', 409: 'Conflict' }[status] ?? 'Error',
    json: async () => JSON.parse(JSON.stringify(body ?? null)),
  }
}

export function fakeMail(routes) {
  const calls = []
  const fetch = vi.fn(async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase()
    const path = String(url).replace(/^.*?api\//, '')
    const body = init.body ? JSON.parse(init.body) : undefined
    calls.push({ method, path, body, raw: init.body ?? '' })
    const h = routes[`${method} ${path}`]
    if (h === undefined) return respond({ code: 'not_found', detail: 'Not Found' }, 404)
    const out = typeof h === 'function' ? h(body, path) : h
    return Array.isArray(out) ? respond(out[1], out[0]) : respond(out)
  })
  vi.stubGlobal('fetch', fetch)
  return { calls, fetch, of: (method, path) => calls.filter(c => c.method === method && c.path === path) }
}
