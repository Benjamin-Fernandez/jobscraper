// The Companies table's row model, pure so it can be tested without a page (Q-118 LD,
// design section 5). Two endpoints feed it and no company is counted twice:
//
//   GET /api/companies/health  every WATCHED company (the built-in watchlist plus the
//                              companies found from your list) and whether its careers
//                              site could be read. Taken whole: one row each.
//   GET /api/companies/list    your own list, in your order, with the search result of
//                              each name. Only the names that are NOT watched yet are
//                              rows here: "no job board found" and "waiting". A found or
//                              already watched name is already a health row.
//
// A company is in exactly one BUCKET, and the legend of the funnel bar filters by it:
//
//   checked    read OK, and last checked within `cycle_days` ("checked this cycle")
//   due        read OK, but checked longer ago than `cycle_days` (the pipeline will
//              check it again) - or never given a time
//   readable   read OK, when the cycle length is unknown (settings did not load): the
//              two buckets above merged
//   failed     the last check failed (the reason is in words)
//   never      watched, but no check has run yet
//   not_found  from your list, but the search found no job board for it
//   waiting    from your list, still to be searched (pending, searching or over the cap)
//
// "Checked this cycle" is computed here, in the browser, from the time of the last check
// and `cycle_days` (design assumption A4): the pipeline's own due rule may differ by hours.
import { utcMs } from './format.js'

export const BUCKETS = ['checked', 'due', 'readable', 'failed', 'never', 'not_found', 'waiting']

// The hiring system behind a careers site, as people know it.
const BOARDS = {
  generic_html: 'Own careers page', greenhouse: 'Greenhouse', lever: 'Lever', ashby: 'Ashby',
  smartrecruiters: 'SmartRecruiters', workable: 'Workable', recruitee: 'Recruitee', workday: 'Workday',
}
export const boardName = b => (b ? (BOARDS[b] ?? b) : '')

// Why a check failed (the server's `kind`), in a few words, and what to do.
export const CAUSES = {
  blocked: {
    label: 'Blocks automated access',
    fix: 'The company\'s site refuses automated readers. Check its careers page yourself, or find the job board it uses (Greenhouse, Lever, Workday…) and set that in config/watchlist.yaml.',
  },
  gone: {
    label: 'Careers page gone',
    fix: 'The careers address no longer exists - the company probably moved it. Find the new page and update careers_url in config/watchlist.yaml.',
  },
  schema: {
    label: 'No readable job listings',
    fix: 'The page loads, but no jobs could be read from it (often a site built entirely in JavaScript). Add a feed_url for its job board in config/watchlist.yaml.',
  },
  transient: {
    label: 'Temporary error',
    fix: 'A timeout, a busy server or a network blip. Nothing to do - it is tried again on the next check.',
  },
  other: {
    label: 'Unexpected error',
    fix: 'Something unusual went wrong; the error below says what. If it keeps happening, check the company\'s entry in config/watchlist.yaml.',
  },
}

// Before the server sent `kind` (older installs): read it from the reason.
export function causeOf(row) {
  if (row.kind && CAUSES[row.kind]) return row.kind
  const r = row.reason || ''
  if (/blocks/.test(r)) return 'blocked'
  if (/no longer exists/.test(r)) return 'gone'
  if (/no job listings/.test(r)) return 'schema'
  if (/temporary/.test(r)) return 'transient'
  return 'other'
}

// The badge of each bucket: the words carry the meaning, the tone only helps.
const BADGE = {
  checked: { label: 'Checked', tone: 'ok' },
  due: { label: 'Due for a check', tone: 'info' },
  readable: { label: 'Readable', tone: 'ok' },
  failed: { label: 'Failed', tone: 'danger' },
  never: { label: 'Never checked', tone: 'neutral' },
  not_found: { label: 'No job board found', tone: 'warn' },
}
// A waiting name says which kind of waiting.
const WAITING_BADGE = {
  pending: 'Waiting',
  searching: 'Searching…',
  over_limit: 'Over plan limit',
}
const WAITING = new Set(Object.keys(WAITING_BADGE))

// A health row's `last_scan` is a UTC stamp without a zone ("2026-11-12 08:50"); a list
// row's `searched_at` is ISO. Both read through utcMs; '' / null when unreadable.
export function stampMs(stamp) {
  const t = utcMs(String(stamp || '').replace(' ', 'T'))
  return t === null || !String(stamp || '').trim() ? null : t
}

// The bucket of one health row. `cycleDays` null / 0 / not a number = unknown.
export function bucketOf(item, cycleDays, now = Date.now()) {
  if (item.state === 'failed') return 'failed'
  if (item.state === 'not_scanned') return 'never'
  if (!(Number(cycleDays) > 0)) return 'readable'
  const t = stampMs(item.last_scan)
  return t !== null && now - t <= Number(cycleDays) * 86400 * 1000 ? 'checked' : 'due'
}

function fromHealth(item, cycleDays, now) {
  const bucket = bucketOf(item, cycleDays, now)
  const failed = bucket === 'failed'
  const ok = !failed && bucket !== 'never'
  const bits = []
  if (failed) {
    if (item.failures_in_a_row) bits.push(`${item.failures_in_a_row} ${item.failures_in_a_row === 1 ? 'failure' : 'failures'} in a row`)
    bits.push(item.last_success ? `last worked ${item.last_success} UTC` : 'never worked')
    if (item.error) bits.push(`error: ${item.error}`)
  }
  return {
    key: `h:${item.company}`,
    company: item.company,
    boardId: item.job_board || '',
    board: boardName(item.job_board),
    openRoles: ok && item.open_roles !== null && item.open_roles !== undefined ? item.open_roles : null,
    lastChecked: item.last_scan || '',
    checkedMs: stampMs(item.last_scan),
    bucket,
    badge: BADGE[bucket].label,
    tone: BADGE[bucket].tone,
    reason: item.reason || '',
    kind: failed ? causeOf(item) : '',
    paused: failed && Boolean(item.paused ?? /paused/.test(item.reason || '')),
    url: item.careers_url || '',
    source: item.source || 'watchlist',
    title: bits.join(' · '),
  }
}

function fromList(item) {
  const notFound = item.status === 'failed'
  const bucket = notFound ? 'not_found' : 'waiting'
  const badge = notFound ? BADGE.not_found : { label: WAITING_BADGE[item.status] ?? 'Waiting', tone: 'neutral' }
  return {
    key: `l:${item.position ?? item.name}`,
    company: item.name,
    boardId: item.provider || '',
    board: boardName(item.provider),
    openRoles: item.postings ?? null,
    lastChecked: item.searched_at || '',
    checkedMs: stampMs(item.searched_at),
    bucket,
    badge: badge.label,
    tone: badge.tone,
    reason: item.detail || '',
    kind: '',
    paused: false,
    url: item.careers_url || '',
    source: 'your list',
    title: '',
  }
}

// Both shapes as one list of rows (health rows first, then the names still to settle).
// `health` / `list` may be null (not loaded): that part is simply empty.
export function rows(health, list, cycleDays = null, now = Date.now()) {
  const out = (health?.items ?? []).map(i => fromHealth(i, cycleDays, now))
  for (const i of list?.items ?? []) {
    if (i.status === 'failed' || WAITING.has(i.status)) out.push(fromList(i))
  }
  return out
}

// The rows grouped by bucket: { checked: [...], due: [...], ... } with every bucket present.
export function partition(health, list, cycleDays = null, now = Date.now()) {
  const out = Object.fromEntries(BUCKETS.map(b => [b, []]))
  for (const r of rows(health, list, cycleDays, now)) out[r.bucket].push(r)
  return out
}

export function countsOf(buckets) {
  return Object.fromEntries(BUCKETS.map(b => [b, buckets[b]?.length ?? 0]))
}

// The funnel sentence's numbers: { list, watched, readable, checked }.
//   list      names in your list (0 = no list)      watched   every watched company
//   readable  the last check worked                 checked   ... and within the cycle
//   (`checked` is null when the cycle length is unknown: that stage is then left out.)
export function funnelOf(health, list, counts, cycleKnown) {
  return {
    list: list?.items?.length ?? 0,
    watched: health?.total ?? (health?.items?.length ?? 0),
    readable: counts.checked + counts.due + counts.readable,
    checked: cycleKnown ? counts.checked : null,
  }
}

// The legend of the bar, in the design's order. "Never checked" and "Waiting for search"
// only appear when there is one; without a cycle length "Readable" stands in for the first two.
export function segmentsOf(counts, cycleKnown) {
  const segs = cycleKnown
    ? [
      { id: 'checked', label: 'Checked this cycle', n: counts.checked, tone: 'ok' },
      { id: 'due', label: 'Due for a check', n: counts.due, tone: 'info' },
    ]
    : [{ id: 'readable', label: 'Readable', n: counts.readable + counts.checked + counts.due, tone: 'ok' }]
  segs.push({ id: 'failed', label: 'Failed', n: counts.failed, tone: 'danger' })
  if (counts.never) segs.push({ id: 'never', label: 'Never checked', n: counts.never, tone: 'neutral' })
  segs.push({ id: 'not_found', label: 'No job board found', n: counts.not_found, tone: 'warn' })
  if (counts.waiting) segs.push({ id: 'waiting', label: 'Waiting for search', n: counts.waiting, tone: 'neutral' })
  return segs
}

// Where the Runs tab's "N failed" link, and older callers, asked the view to start:
// a health state or a bucket id. '' = show everything.
const STATE_TO_BUCKET = { failed: 'failed', not_scanned: 'never' }
export function bucketFromState(state) {
  if (BUCKETS.includes(state)) return state
  return STATE_TO_BUCKET[state] ?? ''
}

// ---- sorting ----

export const DEFAULT_SORT = { key: 'company', dir: 'asc' }
// The direction a column starts in when first clicked: names A-Z, numbers and times
// biggest / newest first.
export const START_DIR = { company: 'asc', roles: 'desc', checked: 'desc' }

export function nextSort(sort, column) {
  if (sort.key === column) return { key: column, dir: sort.dir === 'asc' ? 'desc' : 'asc' }
  return { key: column, dir: START_DIR[column] ?? 'asc' }
}

const byName = (a, b) => String(a.company).localeCompare(String(b.company), undefined, { sensitivity: 'base' })

// Unknown values sort last in either direction; ties fall back to the name, A-Z.
function byNumber(pick, dir) {
  return (a, b) => {
    const x = pick(a)
    const y = pick(b)
    if (x === null && y === null) return byName(a, b)
    if (x === null) return 1
    if (y === null) return -1
    return (dir === 'desc' ? y - x : x - y) || byName(a, b)
  }
}

export function comparator(sort = DEFAULT_SORT) {
  const dir = sort.dir === 'desc' ? 'desc' : 'asc'
  if (sort.key === 'roles') return byNumber(r => (Number.isFinite(r.openRoles) ? r.openRoles : null), dir)
  if (sort.key === 'checked') return byNumber(r => r.checkedMs, dir)
  return dir === 'desc' ? (a, b) => byName(b, a) : byName
}

export function sorted(list, sort = DEFAULT_SORT) {
  return [...list].sort(comparator(sort))
}

// ---- searching ----

// The search box matches the name, the job board (as shown), the reason and the address.
export function matchesQuery(row, query) {
  const q = String(query || '').trim().toLowerCase()
  if (!q) return true
  return [row.company, row.board, row.boardId, row.reason, row.url]
    .some(v => String(v || '').toLowerCase().includes(q))
}
