// Q-100 T1-B: a small fetch router for the Settings views (hub, Apply, MailCard).
// `routes` maps "METHOD path" (path without the "api/" prefix) to a body, a
// [status, body] pair, or a function (body, path) -> either. Anything not listed
// answers 404 like a server without that route, unless `fallback` (a fetch) is given.
// Every call is recorded, so a test can prove what was (and was not) sent.
import { vi } from 'vitest'

function respond(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: { 200: 'OK', 202: 'Accepted', 404: 'Not Found', 405: 'Method Not Allowed', 422: 'Unprocessable Entity', 500: 'Internal Server Error' }[status] ?? 'Error',
    json: async () => JSON.parse(JSON.stringify(body ?? null)),
  }
}

export function routeFetch(routes = {}, { fallback = null } = {}) {
  const calls = []
  const fetch = vi.fn(async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase()
    const path = String(url).replace(/^.*?api\//, '')
    const body = init.body ? JSON.parse(init.body) : undefined
    calls.push({ method, path, body, raw: init.body ?? '' })
    const h = routes[`${method} ${path}`]
    if (h === undefined) {
      return fallback ? fallback(url, init) : respond({ detail: 'Not Found' }, 404)
    }
    const out = typeof h === 'function' ? h(body, path) : h
    return Array.isArray(out) ? respond(out[1], out[0]) : respond(out)
  })
  vi.stubGlobal('fetch', fetch)
  return { calls, fetch, of: (method, path) => calls.filter(c => c.method === method && c.path === path) }
}

// A deep copy of the Q-100 sample response (without its `variants`), so a test can edit it freely.
export function cloneSample(sample) {
  const { variants, ...rest } = sample
  return JSON.parse(JSON.stringify(rest))
}
