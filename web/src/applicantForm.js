// Small pure helpers for the Application details form and the questions inbox
// (Q-30, docs/architecture/questions_design.md section 3 and 10). No Vue here:
// the components stay about layout, and these stay easy to reason about.

const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

// ---- dotted paths with list indices: "education[0].end" ----

function tokens(path) {
  return String(path || '').split('.').flatMap(part => {
    const m = /^([^[\]]*)((?:\[\d+\])*)$/.exec(part)
    if (!m) return [part]
    const out = m[1] ? [m[1]] : []
    for (const idx of m[2].matchAll(/\[(\d+)\]/g)) out.push(Number(idx[1]))
    return out
  })
}

export function clone(value) {
  return value === undefined ? undefined : JSON.parse(JSON.stringify(value))
}

// ---- merging unsaved edits onto a fresh copy of the file (Q-30 F2) ----

const sameValue = (a, b) => JSON.stringify(a) === JSON.stringify(b)
const isBox = v => v !== null && typeof v === 'object'

// Can the edit at one key be merged below it, leaf by leaf? Both sides must be
// mappings, or lists that still hold every entry they had (the owner changed or
// added entries; removing one shifts the rest, so that list is taken whole). A
// section the owner created from nothing merges into the file's copy of it when
// that is a mapping too.
function canMerge(before, mine, theirs) {
  if (!isBox(mine) || !isBox(theirs) || Array.isArray(mine) !== Array.isArray(theirs)) return false
  if (before === undefined) return !Array.isArray(mine)
  if (!isBox(before) || Array.isArray(before) !== Array.isArray(mine)) return false
  return !Array.isArray(mine) || (mine.length >= before.length && theirs.length >= before.length)
}

function applyKey(before, mine, out, key) {
  if (sameValue(before[key], mine[key])) return              // not edited here
  if (canMerge(before[key], mine[key], out[key])) {
    applyEdits(before[key] ?? {}, mine[key], out[key])
  } else if (sameValue(out[key], before[key])) {             // the file did not change it
    if (mine[key] === undefined) delete out[key]
    else out[key] = clone(mine[key])
  }
  // else: edited here and saved differently elsewhere. The value saved
  // elsewhere is the newer, deliberate one (a question answered just now); it
  // is kept and shows in the form, so nothing disappears unseen.
}

function applyEdits(before, mine, out) {
  if (Array.isArray(mine)) {
    for (let i = 0; i < before.length; i++) applyKey(before, mine, out, i)
    for (const added of mine.slice(before.length)) out.push(clone(added))   // entries the owner added
    return
  }
  for (const key of new Set([...Object.keys(before), ...Object.keys(mine)])) applyKey(before, mine, out, key)
}

// A copy of `theirs` (the profile as the file holds it now) with the owner's
// unsaved edits applied: the leaves where `mine` (the draft) differs from
// `before` (the profile the draft was made from). A leaf that was not edited
// here comes from the file, so saving one thing never writes back an old value
// of another that was saved elsewhere, such as a profile-gap answer from the
// Questions card. A list merges per entry; one the owner shortened is taken whole.
export function mergeEdits(before, mine, theirs) {
  const out = clone(theirs ?? {})
  applyEdits(before ?? {}, mine ?? {}, out)
  return out
}

export function getAt(obj, path) {
  let cur = obj
  for (const t of tokens(path)) {
    if (cur === null || cur === undefined || typeof cur !== 'object') return undefined
    cur = cur[t]
  }
  return cur
}

// Writes `value` at `path`, creating the mappings and lists on the way.
export function setAt(obj, path, value) {
  const ts = tokens(path)
  let cur = obj
  ts.forEach((t, i) => {
    if (i === ts.length - 1) {
      cur[t] = value
      return
    }
    if (cur[t] === null || typeof cur[t] !== 'object') cur[t] = typeof ts[i + 1] === 'number' ? [] : {}
    cur = cur[t]
  })
}

// "education[0].end" -> "education.end"
export const bare = path => String(path || '').replace(/\[\d+\]/g, '')

// A DOM id for a field: stable, valid, unique per path.
export const fieldId = path => `f-${String(path || '').replace(/[^a-z0-9]+/gi, '-').replace(/^-|-$/g, '')}`

// path equals `base`, or is inside it ("a.b" in "a", "a[0]" in "a").
export function within(path, base) {
  return path === base || path.startsWith(`${base}.`) || path.startsWith(`${base}[`)
}

export function isEmptyValue(v) {
  if (v === null || v === undefined) return true
  if (typeof v === 'string') return v.trim() === ''
  if (Array.isArray(v)) return v.length === 0
  if (typeof v === 'object') return Object.keys(v).length === 0
  return false
}

// ---- the FORM schema (applicant.form_json) ----

export const allItems = form => (form || []).flatMap(g => (g.items || []).map(item => ({ group: g, item })))

// "languages[0].language" in the list "languages" -> "language"; "languages[1]"
// -> ''; null when `path` is not inside that list.
export function entryPart(listPath, path) {
  const m = new RegExp(`^${esc(listPath)}\\[\\d+\\](?:\\.(.+))?$`).exec(path)
  return m ? (m[1] ?? '') : null
}

// The form item (or the entries sub-field) a profile path belongs to, with a
// label to show: "languages[0].language" -> the Language sub-field.
export function findItem(form, path) {
  const p = String(path || '')
  const exact = allItems(form).find(x => x.item.path === p || x.item.path === bare(p))
  if (exact) return { group: exact.group, item: exact.item, sub: null, label: exact.item.label, path: exact.item.path }
  for (const { group, item } of allItems(form)) {
    if (item.kind === 'entries') {
      const part = entryPart(item.path, p)
      const sub = part && (item.sub || []).find(s => s.path === part)
      if (sub) return { group, item, sub, label: sub.label, path: p }
    }
  }
  // A path inside a compound item: pay.expected_salary.amount, ...authorised_to_work.SG
  const inside = allItems(form).find(x => within(p, x.item.path))
  return inside ? { group: inside.group, item: inside.item, sub: null, label: inside.item.label, path: inside.item.path } : null
}

// ---- options ----

// enum options arrive as [value, label] pairs or {value, label}; a question's
// options as plain strings or {label, norm}. One shape out: {value, label, norm}.
export function normalise(text) {
  return String(text ?? '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
}

export function optionList(options) {
  return (options || []).map(o => {
    if (Array.isArray(o)) return { value: o[0], label: String(o[1] ?? o[0]), norm: normalise(o[1] ?? o[0]) }
    if (o && typeof o === 'object') {
      const label = String(o.label ?? o.value ?? '')
      return { value: o.value ?? label, label, norm: o.norm ?? normalise(label) }
    }
    return { value: o, label: String(o), norm: normalise(o) }
  })
}

// ---- keys the form does not know: group 16 ----

function leaves(value, path, out) {
  if (Array.isArray(value) && value.length) {
    value.forEach((v, i) => leaves(v, `${path}[${i}]`, out))
  } else if (value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length) {
    for (const [k, v] of Object.entries(value)) leaves(v, path ? `${path}.${k}` : k, out)
  } else {
    out.push({ path, value })
  }
  return out
}

// Is this leaf shown by one of the form's items (or the extra group)?
function covered(path, form) {
  if (path === 'version' || within(path, 'extra')) return true
  return allItems(form).some(({ item }) => {
    const m = new RegExp(`^${esc(item.path)}((?:\\[\\d+\\])*)(?:\\.(.+))?$`).exec(path)
    if (!m) return false
    const rest = m[2]
    if (item.kind === 'entries') {
      // Keys an entry does not list (and is not the resume flag) are the owner's own.
      return !rest || rest === 'from_resume' || (item.sub || []).some(s => s.path === rest)
    }
    if (item.kind === 'salary') return !rest || ['amount', 'currency', 'period', 'negotiable'].includes(rest)
    return true
  })
}

// [{path, value}] for every leaf of `profile` that no form item shows.
export function otherKeys(profile, form) {
  return leaves(profile || {}, '', []).filter(l => l.path && !covered(l.path, form))
}

export function showValue(v) {
  if (v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length)) return '(empty)'
  return typeof v === 'string' ? v : JSON.stringify(v)
}

// ---- errors ----

// {path: "message; message"} from [{path, message}].
export function errorMap(errors) {
  const map = {}
  for (const e of errors || []) map[e.path] = map[e.path] ? `${map[e.path]}; ${e.message}` : e.message
  return map
}
