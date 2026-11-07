// Date and number formatting shared by the tabs. The store writes UTC stamps
// without a zone; the page shows them in the browser's own zone (Q-75 G18) so
// "10:05" on screen is the owner's 10:05. The month names stay hand-written so
// a label never depends on the browser's locale. Where the exact stamp matters,
// `exactTime` gives the UTC original for a tooltip.
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

const ISO = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/
const HAS_ZONE = /(?:[zZ]|[+-]\d{2}:?\d{2})$/

// The instant a stamp names, or null for a date with no time (or no date). A
// stamp with no zone is UTC, as the store writes it; one that carries a zone
// keeps it.
function instant(iso) {
  const s = String(iso || '').trim()
  const m = ISO.exec(s)
  if (!m || !m[4]) return null
  const d = new Date(HAS_ZONE.test(s) ? s.replace(' ', 'T') : `${s.slice(0, 16).replace(' ', 'T')}:00Z`)
  return Number.isNaN(d.getTime()) ? null : d
}

const pad = n => String(n).padStart(2, '0')

// "2026-09-23T14:30:00" -> "23 Sep" (the day in the browser's zone); a stamp
// that is only a date is shown as written; '' when there is no date.
export function shortDate(iso) {
  const d = instant(iso)
  if (d) return `${d.getDate()} ${MONTHS[d.getMonth()]}`
  const m = ISO.exec(iso || '')
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}` : ''
}

// "2026-09-24T08:50:05" -> "24 Sep 16:50" in the browser's zone.
export function when(iso) {
  const d = instant(iso)
  if (d) return `${d.getDate()} ${MONTHS[d.getMonth()]} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  return shortDate(iso)
}

// The stamp as stored, for a tooltip: "2026-09-24 08:50 UTC"; '' when unreadable.
export function exactTime(iso) {
  const d = instant(iso)
  if (!d) return ''
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())} UTC`
}

// plural(3, 'role') -> "3 roles"; plural(2, 'company', 'companies').
export function plural(n, word, many = `${word}s`) {
  return `${n} ${n === 1 ? word : many}`
}

// ATS feeds often repeat a place: "Singapore, Singapore" -> "Singapore".
// Parts are kept in order; a repeat (ignoring case) is dropped.
export function cleanLocation(loc) {
  const seen = new Set()
  return String(loc || '').split(/\s*[,;|]\s*/).map(p => p.trim()).filter(p => {
    const key = p.toLowerCase()
    if (!p || seen.has(key)) return false
    seen.add(key)
    return true
  }).join(', ')
}

// Posting URLs are scraped from third-party boards. Only http(s) becomes a
// link, so a `javascript:` URL in a feed can never run in this page.
export function safeUrl(url) {
  return /^https?:\/\//i.test(url || '') ? url : null
}

// Stamps are UTC without a zone ('2026-09-23T14:30:00'); null when unreadable.
export function utcMs(iso) {
  const t = Date.parse(`${String(iso || '').slice(0, 19)}Z`)
  return Number.isNaN(t) ? null : t
}

// 45 -> "45 s", 960 -> "16 min", 3900 -> "1 h 5 min"; '' for no time.
export function duration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return ''
  const s = Math.round(seconds)
  if (s < 60) return `${s} s`
  const min = Math.round(s / 60)
  if (min < 60) return `${min} min`
  const h = Math.floor(min / 60)
  return min % 60 ? `${h} h ${min % 60} min` : `${h} h`
}

// How long ago, in words: "just now", "5 min ago", "3 h ago", "2 days ago".
export function ago(iso, now = Date.now()) {
  const t = utcMs(iso)
  if (t === null) return ''
  const s = Math.max(0, (now - t) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  const d = Math.floor(s / 86400)
  return d === 1 ? 'yesterday' : `${d} days ago`
}

// "2026-10-22T03:45:00+00:00" -> "11:45" in Singapore time (a timestamp with no
// zone is read as UTC); empty string when it is not a time.
export function sgtClock(iso) {
  const s = String(iso || '')
  if (!/\d{2}:\d{2}/.test(s)) return ''
  const d = new Date(/[zZ]$|[+-]\d{2}:?\d{2}$/.test(s) ? s : `${s.replace(' ', 'T')}Z`)
  if (Number.isNaN(d.getTime())) return ''
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Singapore',
  }).format(d)
}
