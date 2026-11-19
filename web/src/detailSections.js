// Profile -> Your details: the ten sections (Q-127 U1, D-215; design B.4). Pure: no Vue, no
// network, so a test can pin every rule without mounting the page.
//
// The server owns the sections (`applicant.SECTIONS`, sent as `sections: [{id, title, paths}]`
// on GET / PUT api/applicant); a path here is a FORM item path (an `entries` item is its list
// path, "education"). Nothing in this file lists which paths a section holds. What it does know
// is how to say a section in one line (`sectionSummary`) and what it still needs
// (`sectionState`), reading the profile.
//
// Nothing here ever sees a company's question: the only inputs are the profile, the form
// schema and the path counts the server sends (`needed_by`). That is the whole point of D-215.
import {
  allItems, bare, conditionHolds, findItem, getAt, isEmptyValue, isFilled, optionList, setAt, within,
} from './applicantForm.js'

export const NOTHING_YET = 'Nothing filled yet'

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`

// ---- which section holds what ----

// The sections to draw: the server's own list. A server that predates Q-127 sends none; then
// each form group that has items is one section, so the page still works (never a blank).
export function sectionsOf(data) {
  const sent = Array.isArray(data?.sections) ? data.sections.filter(s => s && s.id && Array.isArray(s.paths)) : []
  if (sent.length) return sent
  return (data?.form || []).filter(g => (g.items || []).length)
    .map(g => ({ id: g.id, title: g.title, paths: g.items.map(i => i.path) }))
}

// The form items of a section, in the section's own order: [{group, item}].
export function itemsOfSection(section, form) {
  const all = allItems(form)
  return (section?.paths ?? []).map(p => all.find(x => x.item.path === p)).filter(Boolean)
}

// The items cut into runs of one group each, so the page can head a section that spans
// several groups ("Availability and pay") and keep a group's note. [{group, items, sensitive}].
export function blocksOfSection(section, form) {
  const out = []
  for (const { group, item } of itemsOfSection(section, form)) {
    const last = out[out.length - 1]
    if (last && last.group.id === group.id) last.items.push(item)
    else out.push({ group, items: [item] })
  }
  for (const b of out) b.sensitive = b.items.every(i => i.sensitive)
  return out
}

// The section that holds a profile path, a sub-path ("pay.expected_salary.amount"), an entry
// path ("education[0].end") or a form group id ("consents": the shape a consent stop names).
export function sectionOfPath(sections, path, form = []) {
  const p = String(path || '')
  if (!p) return null
  const list = sections || []
  const hit = list.find(s => (s.paths || []).some(x => x === p || within(p, x) || within(bare(p), x)))
  if (hit) return hit
  const group = (form || []).find(g => g.id === p)
  const first = group?.items?.[0]?.path
  return first ? sectionOfPath(list, first) : null
}

// ---- what the page says about each section ----

const valueOf = (profile, path) => getAt(profile, path)
const optionLabel = (form, path, v) => {
  const item = findItem(form, path)?.item
  return optionList(item?.options).find(o => o.value === v)?.label ?? ''
}
const countryName = (form, path, v) => {
  const label = optionLabel(form, path, v)
  return label ? label.replace(/\s*\([A-Z]{2}\)$/, '') : String(v ?? '')
}
const text = v => (typeof v === 'string' ? v.trim() : '')
const cap = s => (s ? s[0].toUpperCase() + s.slice(1) : s)

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
// "2002-03-14" -> "14 Mar 2002"; "2026-07" -> "Jul 2026"; anything else as written.
export function shortDate(v) {
  const m = /^(\d{4})-(\d{2})(?:-(\d{2}))?$/.exec(text(v))
  if (!m || Number(m[2]) < 1 || Number(m[2]) > 12) return text(v)
  const month = MONTHS[Number(m[2]) - 1]
  return m[3] ? `${Number(m[3])} ${month} ${m[1]}` : `${month} ${m[1]}`
}

function salaryText(v) {
  if (!Number.isInteger(v?.amount) || v.amount <= 0) return ''
  const per = { monthly: ' a month', annual: ' a year' }[v.period] ?? ''
  return `${v.currency || 'SGD'} ${v.amount.toLocaleString('en-US')}${per}`
}

// "{n} entries · {first entry's title}" (the first entry that has a title of any kind).
function entriesText(list, titleKeys) {
  const entries = (Array.isArray(list) ? list : []).filter(e => e && typeof e === 'object'
    && Object.entries(e).some(([k, v]) => k !== 'from_resume' && !isEmptyValue(v)))
  if (!entries.length) return ''
  const first = entries.map(e => titleKeys.map(k => text(e[k])).find(Boolean)).find(Boolean)
  const head = plural(entries.length, 'entry', 'entries')
  return first ? `${head} · ${first}` : head
}

const SUMMARISERS = {
  identity: (p, form) => [
    [text(valueOf(p, 'identity.legal_first_name')), text(valueOf(p, 'identity.legal_last_name'))].filter(Boolean).join(' '),
    valueOf(p, 'identity.date_of_birth') ? `born ${shortDate(valueOf(p, 'identity.date_of_birth'))}` : '',
    optionLabel(form, 'identity.gender', valueOf(p, 'identity.gender')),
  ],
  contact: (p, form) => [
    text(valueOf(p, 'contact.email')),
    [text(valueOf(p, 'contact.phone_country_code')), text(valueOf(p, 'contact.phone_number'))].filter(Boolean).join(' '),
    valueOf(p, 'contact.country') ? countryName(form, 'contact.country', valueOf(p, 'contact.country')) : '',
  ],
  work_rights: (p, form) => {
    const pass = valueOf(p, 'singapore_status.work_pass')
    const ns = valueOf(p, 'singapore_status.ns_status')
    return [
      optionLabel(form, 'singapore_status.residency_status', valueOf(p, 'singapore_status.residency_status')),
      pass === 'none_required' ? 'no pass needed' : optionLabel(form, 'singapore_status.work_pass', pass),
      ns ? `NS ${optionLabel(form, 'singapore_status.ns_status', ns).toLowerCase()}`.trim() : '',
    ]
  },
  availability_pay: p => {
    const days = valueOf(p, 'availability.notice_period_days')
    const salary = salaryText(valueOf(p, 'pay.expected_salary'))
    return [
      Number.isInteger(days) && days >= 0 ? (days === 0 ? 'no notice period' : `${days} ${days === 1 ? "day's" : "days'"} notice`) : '',
      valueOf(p, 'availability.earliest_start_date') ? `from ${shortDate(valueOf(p, 'availability.earliest_start_date'))}` : '',
      salary ? `expects ${salary}` : '',
    ]
  },
  education: p => [entriesText(valueOf(p, 'education'), ['degree', 'institution'])],
  experience: p => [entriesText(valueOf(p, 'experience'), ['title', 'employer'])],
  skills_links: p => {
    const skills = (valueOf(p, 'skills') || []).filter(Boolean)
    const languages = (valueOf(p, 'languages') || []).map(l => text(l?.language)).filter(Boolean)
    const links = [
      ['links.linkedin', 'LinkedIn'], ['links.github', 'GitHub'], ['links.portfolio', 'Portfolio'],
    ].filter(([path]) => text(valueOf(p, path))).map(([, name]) => name)
    const other = (valueOf(p, 'links.other') || []).filter(Boolean).length
    if (other) links.push(`${other} other`)
    return [skills.length ? plural(skills.length, 'skill', 'skills') : '', languages.join(', '), links.join(', ')]
  },
  equal_opportunity: (p, form) => [
    optionLabel(form, 'singapore_status.race', valueOf(p, 'singapore_status.race')),
    text(valueOf(p, 'singapore_status.religion')),
    optionLabel(form, 'singapore_status.marital_status', valueOf(p, 'singapore_status.marital_status')),
    valueOf(p, 'us_self_id.eeo_gender') ? `US forms: ${optionLabel(form, 'us_self_id.eeo_gender', valueOf(p, 'us_self_id.eeo_gender'))}` : '',
  ],
  consents_declarations: (p, form, section) => {
    const items = itemsOfSection(section, form).map(x => x.item).filter(i => i.kind === 'bool')
    // The switches the server marks `default_off` (sharing, checks) are a decision, not a gap:
    // they stay out of the "n of m consents given" count and are mentioned only when on.
    const all = items.filter(i => i.path.startsWith('consents.'))
    const consents = all.filter(i => !i.default_off)
    const switches = all.filter(i => i.default_off)
    const switchesOn = switches.filter(i => valueOf(p, i.path) === true).length
    const decls = items.filter(i => i.path.startsWith('declarations.'))
    const given = consents.filter(i => valueOf(p, i.path) === true).length
    const answered = decls.filter(i => typeof valueOf(p, i.path) === 'boolean')
    const yes = answered.filter(i => valueOf(p, i.path) === true).length
    return [
      !consents.length ? '' : given === consents.length ? 'Consents given' : given === 0 ? 'No consents given' : `${given} of ${consents.length} consents given`,
      !switchesOn ? '' : switchesOn === switches.length ? 'sharing and checks agreed' : `${switchesOn} of ${switches.length} sharing and check switches on`,
      !decls.length || !answered.length ? '' : yes === 0 && answered.length === decls.length ? 'every declaration No' : yes === 0 ? 'declarations No where set' : `${plural(yes, 'declaration', 'declarations')} Yes`,
    ]
  },
  files: (p, form, section, docs) => {
    const resume = docs ? !!docs.resume : !!text(valueOf(p, 'documents.resume'))
    const transcript = docs ? !!docs.transcript : !!text(valueOf(p, 'documents.transcript'))
    return [resume ? 'Resume in use' : 'No resume yet', transcript ? 'transcript added' : 'no transcript']
  },
}

// A section the page has no sentence for (a newer server's): the first few filled values.
function genericSummary(profile, form, section) {
  const out = []
  for (const { item } of itemsOfSection(section, form)) {
    const v = valueOf(profile, item.path)
    if (typeof v === 'string' && v.trim()) out.push(optionLabel(form, item.path, v) || v.trim())
    else if (Array.isArray(v) && v.length) out.push(plural(v.length, 'item', 'items'))
    if (out.length === 3) break
  }
  return out
}

// One line for a collapsed row: "Sam Sample · born 14 Mar 2002 · Male". `docs` is the
// server's `documents_status` when it has one. "Nothing filled yet" when no part has a value.
export function sectionSummary(section, profile, form, docs = null) {
  if (!section) return NOTHING_YET
  const parts = (SUMMARISERS[section.id] ?? genericSummary)(profile || {}, form || [], section, docs)
  const shown = parts.filter(Boolean)
  return shown.length ? shown.join(' · ') : NOTHING_YET
}

// ---- completeness: Needed / {n} to fill / Complete, and Fix {n} ----

// Is this path filled the way the server counts it (applicant.path_filled)? A consent needs a Yes.
export function pathFilled(profile, path) {
  const v = getAt(profile, path)
  if (String(path).startsWith('consents.')) return v === true
  if (path.endsWith('.amount')) return Number.isInteger(v) && v > 0
  return !isEmptyValue(v)
}

// {path: n applications} that still need this item (the largest count under it).
export function neededByFor(item, neededBy) {
  let n = 0
  for (const [path, count] of Object.entries(neededBy || {})) {
    if (within(path, item.path) || within(bare(path), item.path)) n = Math.max(n, Number(count) || 0)
  }
  return n
}

const shows = (item, profile) => conditionHolds(item, profile) || !isEmptyValue(getAt(profile, item.path))

// What a section row says, from the SAVED profile (the status line and the shell badge say the
// same): `needed` = a required item is empty or a waiting application needs a path in it;
// `toFill` = recommended items still empty; `fix` = errors on paths this section holds.
// ctx: {form, profile, missing: [path], neededBy: {path: n}, errors: [{path, message}]}.
export function sectionState(section, ctx) {
  const { form = [], profile = {}, missing = [], neededBy = {}, errors = [] } = ctx || {}
  const items = itemsOfSection(section, form).map(x => x.item).filter(i => shows(i, profile))
  const needed = items.filter(i => missing.some(m => within(m, i.path)) || neededByFor(i, neededBy) > 0).length
  const toFill = items.filter(i => i.recommended && !isFilled(i, getAt(profile, i.path))).length
  const fix = errors.filter(e => (section.paths || []).some(p => within(e.path, p) || within(bare(e.path), p))).length
  const status = needed ? 'needed' : toFill ? 'fill' : 'complete'
  return {
    id: section.id, status, needed, toFill, fix,
    text: { needed: 'Needed', fill: `${toFill} to fill`, complete: 'Complete' }[status],
    tone: { needed: 'warn', fill: 'neutral', complete: 'ok' }[status],
    fixText: fix ? `Fix ${fix}` : '',
  }
}

// ---- the status line ----

// The paths auto-apply waits on: what the profile lacks (REQUIRED_PATHS plus the resume),
// then what a waiting application needs that is still empty. De-duplicated, in that order:
// the same list the Profile badge counts (`details_needed` on GET api/apply/status).
// With the form schema, two paths inside one field ("pay.expected_salary" the profile lacks,
// "pay.expected_salary.amount" an application waits on) count once, as the one detail they are.
export function detailsNeeded(missing, neededBy, form = null) {
  const paths = [...new Set([...(missing || []), ...Object.keys(neededBy || {})])]
  if (!form) return paths
  const seen = new Set()
  return paths.filter(p => {
    const key = findItem(form, p)?.path ?? p
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

export function labelOfPath(form, path) {
  return findItem(form, path)?.label ?? path
}

// The one status card: {ready, badge, tone, text, waitingText, attentionText, firstPath, labels}.
// `waiting` is the server's [{job_id, paths, ready}]; only the ones not ready count.
export function statusLine({ form = [], needed = [], waiting = [], extraErrors = 0 } = {}) {
  const n = needed.length
  const stuck = (waiting || []).filter(w => w && w.ready !== true).length
  const labels = [...new Set(needed.map(p => labelOfPath(form, p)))]
  return {
    ready: n === 0,
    count: n,
    badge: n === 0 ? 'Ready for auto-apply' : `${plural(n, 'detail', 'details')} needed`,
    tone: n === 0 ? 'ok' : 'warn',
    text: n === 0 ? 'Your required details are filled in.' : `Auto-apply waits until these are filled: ${labels.join(', ')}.`,
    labels,
    firstPath: needed[0] ?? '',
    waitingText: stuck ? `${stuck === 1 ? '1 application is' : `${stuck} applications are`} waiting for a detail below.` : '',
    attentionText: extraErrors > 0 ? 'A saved answer needs attention. Open Settings → Apply → Answers you corrected.' : '',
  }
}

// "Needed by 3 applications" / "Needed by 1 application".
export const neededByText = n => `Needed by ${plural(n, 'application', 'applications')}`

// The page never draws an `extra.*` error (M4): it is one line in the status card instead.
export const withoutExtraErrors = errors => (errors || []).filter(e => !within(String(e?.path ?? ''), 'extra'))

// ---- saving one section ----

const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null)

// Has the draft changed anything this section holds?
export function sectionDirty(section, saved, draft) {
  return (section?.paths || []).some(p => !same(getAt(saved, p), getAt(draft, p)))
}

// The whole profile to PUT: the saved one with only this section's paths taken from the draft.
export function takeSection(section, saved, draft) {
  const out = JSON.parse(JSON.stringify(saved ?? {}))
  for (const p of section?.paths || []) {
    const v = getAt(draft, p)
    if (v !== undefined) setAt(out, p, JSON.parse(JSON.stringify(v)))
  }
  return out
}

// The draft with this section's paths put back to what is saved (Cancel / Discard changes).
export function revertSection(section, saved, draft) {
  const out = JSON.parse(JSON.stringify(draft ?? {}))
  for (const p of section?.paths || []) {
    const v = getAt(saved, p)
    if (v !== undefined) setAt(out, p, JSON.parse(JSON.stringify(v)))
    else removeAt(out, p)
  }
  return out
}

function removeAt(obj, path) {
  const parts = String(path).split('.')
  let cur = obj
  for (const k of parts.slice(0, -1)) {
    if (cur === null || typeof cur !== 'object') return
    cur = cur[k]
  }
  if (cur && typeof cur === 'object') delete cur[parts[parts.length - 1]]
}

// ---- the waiting notice (M6) ----

// Roles that were waiting on a detail and are ready now that this save went through:
// `after` is the PUT's `waiting`, `before` the list the page held. Only roles whose paths
// touch this section, and that were not already ready. Returns [{job_id, paths}].
export function newlyReady(section, before, after) {
  const was = new Map((before || []).map(w => [String(w.job_id), w.ready === true]))
  return (after || []).filter(w => w && w.ready === true && !was.get(String(w.job_id))
    && (w.paths || []).some(p => (section?.paths || []).some(sp => within(p, sp) || within(bare(p), sp))))
}

export const waitingNoticeText = n =>
  `Saved. ${n === 1 ? '1 application was' : `${n} applications were`} waiting for this.`
export const applyAgainText = n => `Apply again to ${plural(n, 'application', 'applications')}`
