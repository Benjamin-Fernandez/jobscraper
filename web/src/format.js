// Date and number formatting shared by the tabs. Dates are parsed by hand so a
// label never depends on the browser's locale or time zone; the store writes
// UTC, and the page says so where it shows a time.
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

const ISO = /^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?/

// "2026-09-23T14:30:00" -> "23 Sep"; '' when there is no date.
export function shortDate(iso) {
  const m = ISO.exec(iso || '')
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}` : ''
}

// "2026-09-24T08:50:05" -> "24 Sep 08:50 UTC".
export function when(iso) {
  const m = ISO.exec(iso || '')
  if (!m) return ''
  const day = `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}`
  return m[4] ? `${day} ${m[4]}:${m[5]} UTC` : day
}

// plural(3, 'role') -> "3 roles"; plural(2, 'company', 'companies').
export function plural(n, word, many = `${word}s`) {
  return `${n} ${n === 1 ? word : many}`
}

// Posting URLs are scraped from third-party boards. Only http(s) becomes a
// link, so a `javascript:` URL in a feed can never run in this page.
export function safeUrl(url) {
  return /^https?:\/\//i.test(url || '') ? url : null
}
