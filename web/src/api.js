// The only module that knows the API's URLs. The base is relative to the page,
// never a host: the same bundle then works on 127.0.0.1, behind a proxy, or in
// a container (PRD 8.6).
const BASE = 'api/'

async function request(path, init) {
  const res = await fetch(BASE + path, init)
  if (!res.ok) {
    let detail = ''
    try { detail = (await res.json()).detail ?? '' } catch { /* not JSON */ }
    throw new Error(`${res.status} ${res.statusText}${detail ? ` - ${JSON.stringify(detail)}` : ''}`)
  }
  return res.json()
}

export function getRuns() {
  return request('runs')
}

// `run` is a run number, 'latest' or 'all'.
export function getShortlist(run) {
  return request(`shortlist?run=${encodeURIComponent(run)}`)
}
