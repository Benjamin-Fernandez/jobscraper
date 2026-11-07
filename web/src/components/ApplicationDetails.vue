<script setup>
// Profile -> Application details (Q-30, D-74): every key of data/applicant.yaml
// as a form, with what auto-apply still needs at the top and, above the form,
// the questions employers asked that JobScraper could not answer
// (QuestionsInbox). The form is generated from `form`, the schema the server
// sends (applicant.form_json), so a key added there appears here without a UI
// change. Layout and copy: docs/architecture/questions_design.md section 10.
//
// Saving sends the whole profile back with the etag it was loaded with. The
// server refuses a stale etag (409) and a profile that fails validation (422,
// with a message per path); both are said in words. Keys the form does not
// know round-trip untouched and are listed read-only in the last group.
//
// Q-71 (docs/reviews/Q-71-details-form-audit.md, lane F): a failed save lists
// every error with a "Go to" link; blank added entries are left out of the PUT;
// "Needed" clears as the owner types; a section rail and "Next needed" get
// around the long page; a field is checked when the owner leaves it
// (POST api/applicant/check, when the server has it). The schema's optional
// hints (`control`, `show_when`, `autocomplete`, `options` for countries,
// `documents_status`) are used when present; without them the form behaves as
// before.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { checkApplicant, describeError, getApplicant, getProfile, problemOf, saveApplicant } from '../api.js'
import {
  clone, conditionHolds, entryPart, errorMap, fieldId, findItem, getAt, isEmptyValue, isFilled, joinAnd,
  mergeEdits, newSkills, otherKeys, pruneBlankEntries, remapErrors, sectionStatus, setAt, showValue,
  todayIso, within,
} from '../applicantForm.js'
import FieldInput from './FieldInput.vue'
import Icon from './Icon.vue'
import QuestionsInbox from './QuestionsInbox.vue'
import SectionRail from './SectionRail.vue'
import TabLoading from './TabLoading.vue'

const emit = defineEmits(['counts', 'go-view'])

const PRIVATE = 'Private: never sent to the AI'
// The unsaved form survives a visit to another tab (Q-70 D1, D-100). sessionStorage
// only: it is this browser's, goes when the tab closes, and the same data already
// sits in data/applicant.yaml on this machine. Never localStorage.
const DRAFT_KEY = 'jobscraper.applicant.draft'
// A group's own control: a label for one input, a name for a set of them.
const GROUPED = new Set(['entries', 'salary', 'country_bool_map', 'yes_no', 'multi', 'fixed'])
// Two columns on a wide screen (Q71-19); these take the whole row.
const WIDE_KINDS = new Set(['entries', 'salary', 'country_bool_map', 'list_text', 'list_url', 'fixed', 'yes_no'])
const WIDE_GROUPS = new Set(['declarations', 'consents'])
const CHECK_MS = 400

const data = ref(null)
const draft = ref({})
const loading = ref(true)
const loadError = ref('')
const saving = ref(false)
const errors = ref([])          // [{path, message}] from the last save or load
const conflict = ref('')        // '' | 'changed' | 'unreadable' (a 409 on save)
const note = ref('')
const problem = ref('')         // a save that failed for a reason that is not 409 or 422
const openQuestions = ref(null)
const removing = ref('')        // the `extra` key whose Remove is being confirmed
const restored = ref(false)     // the draft came back from sessionStorage
const banner = ref(null)
const inbox = ref(null)
const root = ref(null)
const derivedSkills = ref([])   // the skills the resume parse found (GET api/profile)
const touched = ref([])         // item paths the owner changed since the last load or save
const checked = ref({})         // item path -> [{path, message}] from the last blur check
const currentSection = ref('')
const lastField = ref('')       // the item path that last had focus, for "Next needed"
let checkTimer = null
let checkOff = false            // the server has no check route: stop asking
let observer = null

const form = computed(() => data.value?.form ?? [])
// The schema also lists the two groups rendered from the profile (extra, other),
// with no items: those are drawn below from the profile, not here.
const groups = computed(() => form.value.filter(g => (g.items || []).length))
const missing = computed(() => data.value?.missing ?? [])
const fileError = computed(() => data.value?.file?.error || '')
const sensitive = computed(() => data.value?.sensitive ?? [])
const fromResumePaths = computed(() => data.value?.from_resume ?? [])
const extra = computed(() => Object.entries(draft.value?.extra ?? {}))
const dirty = computed(() => !!data.value && JSON.stringify(draft.value) !== JSON.stringify(data.value.profile ?? {}))
const meter = computed(() => data.value?.completeness ?? null)
const others = computed(() => (data.value ? otherKeys(draft.value, form.value) : []))

// ---- errors: the last save or load, with the fields re-checked on blur on top ----
const superseded = path => Object.keys(checked.value).some(p => within(path, p))
const liveErrors = computed(() => Object.values(checked.value).flat())
const shownErrors = computed(() => [...errors.value.filter(e => !superseded(e.path)), ...liveErrors.value])
const errMap = computed(() => errorMap(shownErrors.value))
// The summary lists what the last save or load refused; a field fixed since
// (checked clean on blur) drops off it, one still wrong keeps its newest message.
const bannerErrors = computed(() => errors.value.flatMap(e => {
  if (!superseded(e.path)) return [e]
  const live = liveErrors.value.find(x => x.path === e.path)
  return live ? [live] : []
}))

// The Profile tab shows "what needs you" in the view's label. `questions` is
// null until the inbox has loaded (or never, on a server without the routes).
function report() {
  emit('counts', { missing: missing.value.length, questions: openQuestions.value })
}
function onInboxLoaded(n) {
  openQuestions.value = n.open
  report()
}

// Keep the draft while it differs from the file; drop it as soon as it doesn't.
watch(draft, v => {
  if (!data.value) return
  try {
    if (dirty.value) {
      sessionStorage.setItem(DRAFT_KEY, JSON.stringify({ etag: data.value.etag, base: data.value.profile ?? {}, draft: v }))
    } else {
      sessionStorage.removeItem(DRAFT_KEY)
    }
  } catch { /* storage full or blocked: the form still works, it just won't survive */ }
}, { deep: true })

function restoreDraft() {
  let s = null
  try {
    const raw = sessionStorage.getItem(DRAFT_KEY)
    s = raw ? JSON.parse(raw) : null
  } catch { s = null }
  if (!s || typeof s.draft !== 'object' || s.draft === null) return
  // Same file version: take the draft as it was. The file moved on: keep only the leaves
  // the owner changed (`mergeEdits`), the rest comes from the file.
  draft.value = s.etag === data.value.etag ? s.draft : mergeEdits(s.base ?? {}, s.draft, data.value.profile ?? {})
  restored.value = true
}

function adopt(res) {
  data.value = res
  draft.value = clone(res.profile ?? {})
  errors.value = res.errors ?? []
  conflict.value = ''
  touched.value = []
  checked.value = {}
  report()
}

// The resume's skills, for "Add them" under Skills (Q71-15). Quiet on failure:
// the form works without them.
async function loadDerived() {
  try {
    const p = await getProfile()
    derivedSkills.value = Array.isArray(p?.skills) ? p.skills : []
  } catch {
    derivedSkills.value = []
  }
}

async function load() {
  loadError.value = ''
  note.value = ''
  try {
    adopt(await getApplicant())
    restoreDraft()
  } catch (e) {
    loadError.value = describeError(e)
  } finally {
    loading.value = false
  }
}

// The Questions card rewrote the file: take its new etag and answers, but keep
// what is typed here and not yet saved. The merge is per leaf (`mergeEdits`):
// only the leaves the owner changed here come from the draft, everything else
// from the file. Merging whole sections lost a profile-gap answer (Q-30 F2): the
// owner edited another field of Contact, answered the card for
// contact.address_line1, and the draft's old Contact, kept with the new etag,
// wrote the answer away on the next "Save details".
async function reloadKeepingEdits() {
  const before = data.value?.profile ?? {}
  let res
  try {
    res = await getApplicant()
  } catch (e) {
    loadError.value = describeError(e)
    return
  }
  // `draft.value` is read after the await: what was typed while it ran is kept too.
  const next = mergeEdits(before, draft.value, res.profile ?? {})
  data.value = res
  draft.value = next
  errors.value = res.errors ?? []
  conflict.value = ''
  checked.value = {}
  report()
}

// Throw away what was typed and go back to what the file holds.
function discard() {
  draft.value = clone(data.value.profile ?? {})
  errors.value = data.value.errors ?? []
  touched.value = []
  checked.value = {}
  restored.value = false
  try { sessionStorage.removeItem(DRAFT_KEY) } catch { /* nothing to remove */ }
}

// Closing the tab or reloading the page would lose the draft's unsaved state in the
// owner's mind (it is restored, but only within this tab): ask first.
const guard = e => {
  if (dirty.value) {
    e.preventDefault()
    e.returnValue = ''
  }
}

// ---- labels, tags, ids ----

const labelOf = path => findItem(form.value, path)?.label ?? path
const valueOf = item => getAt(draft.value, item.path)
// A bool the schema marks as a question (`control: 'yes_no'`) is Yes / No radios (Q71-12).
const kindOf = item => (item.kind === 'bool' && item.control === 'yes_no' ? 'yes_no' : item.kind)
const grouped = item => GROUPED.has(kindOf(item))
const isMissing = item => missing.value.some(m => within(m, item.path))
// Filled as the server counts it (applicant._filled), so "Needed" goes as soon
// as the field is filled here, not at the next save (Q71-06).
const filledHere = item => isFilled(item, valueOf(item))
// "Needed": the server says it is missing and it has not been filled in here yet.
const needed = item => isMissing(item) && !filledHere(item)
const fromResume = item => fromResumePaths.value.some(p => within(p, item.path))
const privatePath = path => sensitive.value.some(s => within(path, s))
const labelTag = item => (grouped(item) ? 'span' : 'label')
const wide = (g, item) => WIDE_GROUPS.has(g.id) || WIDE_KINDS.has(kindOf(item)) || !!item.multiline
// The group title already says it ("Education" / "Education"): keep the label for screen readers only.
const labelHidden = (g, item) => (g.items || []).length === 1 && item.label === g.title
const requiredText = item => (item.kind === 'bool' ? 'Must be Yes for auto-apply' : 'Required for auto-apply')

// "Private" once per section (Q71-20). A group that is all private says so in
// its header; one that is mostly private names the exceptions; one with a few
// private fields tags those. Each private field still carries the full words
// for screen readers (in its description).
function privacyOf(g) {
  const items = g.items || []
  const open = items.filter(i => !i.sensitive)
  if (open.length === items.length) return { header: '', perItem: false }
  if (g.sensitive || !open.length) return { header: PRIVATE, perItem: false }
  if (open.length < items.length - open.length) return { header: `${PRIVATE}, except ${joinAnd(open.map(i => i.label))}`, perItem: false }
  return { header: '', perItem: true }
}

// A follow-up field shows only when it applies (Q71-14), but never hides a
// value or an error: a hidden value would still be sent to employers.
const visible = item => conditionHolds(item, draft.value) || !isEmptyValue(valueOf(item)) || invalid(item)

const itemErrors = item => shownErrors.value.filter(e => within(e.path, item.path) && !handledInside(item, e.path))
const invalid = item => shownErrors.value.some(e => within(e.path, item.path))
// Inside an entries field each message sits under its own sub-field.
function handledInside(item, path) {
  if (item.kind !== 'entries') return false
  const part = entryPart(item.path, path)
  return part !== null && (!part || (item.sub || []).some(s => s.path === part))
}
// ---- warnings that never block (Q71-09, Q71-02) ----

const pastDate = item => item.path === 'availability.earliest_start_date'
  && typeof valueOf(item) === 'string' && !!valueOf(item) && valueOf(item) < todayIso()
const countryName = code => {
  const o = (findItem(form.value, 'contact.country')?.item?.options || []).find(x => x?.value === code)
  return o ? String(o.label).replace(/\s*\([A-Z]{2}\)$/, '') : code
}
const countryWarning = computed(() => {
  const c = getAt(draft.value, 'contact.country')
  const cc = String(getAt(draft.value, 'contact.phone_country_code') ?? '').trim().replace(/^\+/, '')
  if (!c || c === 'SG' || cc !== '65') return ''
  return `Your country is ${countryName(c)}, but your phone code is +65. Is that right?`
})
const warningOf = item => {
  if (pastDate(item)) return 'This date has passed. Employers will read it as your start date.'
  if (item.path === 'contact.country') return countryWarning.value
  return ''
}

const describedBy = (g, item) => [
  item.help && item.kind !== 'fixed' ? `${fieldId(item.path)}-help` : '',
  warningOf(item) ? `${fieldId(item.path)}-warn` : '',
  item.sensitive ? `${fieldId(item.path)}-private` : '',
  itemErrors(item).length ? `${fieldId(item.path)}-err` : '',
].filter(Boolean).join(' ')

const extraErrors = key => shownErrors.value.filter(e => within(e.path, `extra.${key}`))

// ---- the error summary (Q71-03) ----

const extraKey = path => String(path).split('.')[1] ?? ''
const entryIndex = path => {
  const m = /^[^[]*\[(\d+)\]/.exec(String(path))
  return m ? Number(m[1]) : null
}
// "Email for applications", "School 1 · Degree", or the bare path for a key the form doesn't know.
function errorLabel(path) {
  if (within(path, 'extra')) return draft.value.extra?.[extraKey(path)]?.title || extraKey(path)
  const hit = findItem(form.value, path)
  if (!hit) return path
  const i = hit.item.kind === 'entries' ? entryIndex(path) : null
  if (i === null) return hit.label
  const name = `${hit.item.entry_label || hit.item.label} ${i + 1}`
  return hit.sub ? `${name} · ${hit.sub.label}` : name
}
const canGo = path => (within(path, 'extra') ? !!draft.value.extra?.[extraKey(path)] : !!findItem(form.value, path))
const summaryTitle = computed(() => {
  const n = bannerErrors.value.length
  return n === 1 ? '1 detail needs fixing before you can save' : `${n} details need fixing before you can save`
})

// ---- going to a field: Fill in, Go to, Next needed ----

// The element for a path: an entry's own sub-field ("education[0].end"), the
// entry, or the item's block.
function targetOf(path) {
  if (within(path, 'extra')) return document.getElementById(fieldId(`extra.${extraKey(path)}`))
  const hit = findItem(form.value, path)
  if (!hit) return null
  const i = hit.item.kind === 'entries' ? entryIndex(path) : null
  if (i !== null) {
    const id = fieldId(hit.item.path)
    if (hit.sub) {
      const el = document.getElementById(`${id}-in-${i}-${hit.sub.path.replace(/[^a-z0-9]+/gi, '-')}`)
      if (el) return el
    }
    const entry = document.getElementById(id)?.querySelectorAll('fieldset.entry')[i]
    if (entry) return entry
  }
  return document.getElementById(fieldId(hit.item.path))
}
function fillIn(path) {
  const el = targetOf(path)
  if (!el) return
  const control = el.matches?.('input, select, textarea, button')
    ? el
    : el.querySelector('input:not([type="hidden"]), select, textarea, button')
  const closed = control?.closest?.('details')
  if (closed && !closed.open) closed.open = true
  el.scrollIntoView?.({ block: 'center' })
  control?.focus?.()
}
const canFill = path => !!findItem(form.value, path)

// ---- sections: the rail, the group headers, Next needed (Q71-13) ----

const extraToFix = computed(() => extra.value.filter(([key]) => extraErrors(key).length).length)
const sections = computed(() => {
  const out = groups.value.map(g => {
    const items = (g.items || []).filter(visible)
    return { id: g.id, title: g.title, needed: items.filter(needed).length, toFix: items.filter(invalid).length }
  })
  if (extra.value.length) out.push({ id: 'extra', title: 'Answers you gave to application questions', needed: 0, toFix: extraToFix.value })
  if (others.value.length) out.push({ id: 'other', title: 'Other keys in your file', needed: 0, toFix: 0 })
  return out
})
const sectionOf = id => sections.value.find(s => s.id === id) ?? {}
const neededItems = computed(() => groups.value.flatMap(g => (g.items || []).filter(i => visible(i) && needed(i))))
const order = computed(() => groups.value.flatMap(g => (g.items || []).map(i => i.path)))

function goSection(id) {
  const h = document.getElementById(`g-${id}`)
  if (!h) return
  currentSection.value = id
  h.closest('section')?.scrollIntoView?.({ block: 'start' })
  h.focus?.({ preventScroll: true })
}

// The next needed field after the one last focused (or, if none, after the
// last one scrolled past), wrapping round to the first.
function nextNeeded() {
  const list = neededItems.value
  if (!list.length) return
  let from = order.value.indexOf(lastField.value)
  if (from < 0) {
    // Fields whose top is above the sticky header have been scrolled past.
    const limit = 100
    order.value.forEach((p, i) => {
      const el = document.getElementById(fieldId(p))
      if (el && el.getBoundingClientRect().top < limit) from = i
    })
  }
  const next = list.find(i => order.value.indexOf(i.path) > from) ?? list[0]
  lastField.value = next.path
  fillIn(next.path)
}
function onFocusIn(e) {
  const path = e.target?.closest?.('.field')?.dataset?.path
  if (path && order.value.includes(path)) lastField.value = path
}

// The section on screen, for the rail's aria-current. Not in jsdom.
function observeSections() {
  observer?.disconnect()
  observer = null
  if (typeof IntersectionObserver === 'undefined' || !root.value) return
  observer = new IntersectionObserver(entries => {
    for (const en of entries) if (en.isIntersecting) currentSection.value = en.target.dataset.section
  }, { rootMargin: '-15% 0px -75% 0px' })
  root.value.querySelectorAll('section[data-section]').forEach(el => observer.observe(el))
}
watch(() => sections.value.map(s => s.id).join(' '), () => nextTick(observeSections))

// ---- skills and experience from the resume (Q71-15) ----

const resumeSkills = computed(() => newSkills(derivedSkills.value, getAt(draft.value, 'skills')))
const skillPreview = computed(() => {
  const s = resumeSkills.value
  return s.length > 8 ? `${s.slice(0, 8).join(', ')} and ${s.length - 8} more` : s.join(', ')
})
function addResumeSkills() {
  const now = getAt(draft.value, 'skills')
  setAt(draft.value, 'skills', [...(Array.isArray(now) ? now : []), ...resumeSkills.value])
  markTouched('skills')
}

// ---- files (Q71-16): which resume is in use, and where to upload one ----

const hasDocs = computed(() => !!data.value && 'documents_status' in data.value)
const docs = computed(() => data.value?.documents_status ?? {})
const stampFmt = new Intl.DateTimeFormat('en-GB', {
  day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  timeZone: 'Asia/Singapore',
})
function stamp(iso) {
  const d = new Date(String(iso || ''))
  return Number.isNaN(d.getTime()) ? '' : stampFmt.format(d)
}
// Found / Not found only describes the saved path: a path typed since is checked on save.
const savedPath = item => getAt(data.value?.profile, item.path)
const transcriptKnown = item => !!valueOf(item) && valueOf(item) === savedPath(item)
const goUpload = () => emit('go-view', 'resume')

// ---- editing, and the check when the owner leaves a field (Q71-18) ----

function markTouched(path) {
  if (!touched.value.includes(path)) touched.value.push(path)
}
function onEdit(item, v) {
  setAt(draft.value, item.path, v)
  markTouched(item.path)
}
// Cheap fixes on the way out: "linkedin.com/in/x" gets https://, "65" is "+65", an email is trimmed.
function tidy(item) {
  const v = valueOf(item)
  if (typeof v !== 'string') return
  const t = v.trim()
  let out = v
  if (item.kind === 'email') out = t
  else if (item.kind === 'url' && t && !/^[a-z][a-z0-9+.-]*:/i.test(t) && /^[^\s/]+\.[^\s]+$/.test(t)) out = `https://${t}`
  else if (item.kind === 'phone_cc' && /^\d{1,3}$/.test(t)) out = `+${t}`
  if (out !== v) setAt(draft.value, item.path, out)
}
function onFocusOut(item, e) {
  if (e.currentTarget?.contains?.(e.relatedTarget)) return     // still inside this field
  if (!touched.value.includes(item.path)) return
  tidy(item)
  if (checkOff) return
  clearTimeout(checkTimer)
  checkTimer = setTimeout(runCheck, CHECK_MS)
}
async function runCheck() {
  if (!data.value || checkOff || !touched.value.length) return
  const paths = [...touched.value]
  const { profile, kept } = pruneBlankEntries(draft.value)
  let res
  try {
    res = await checkApplicant(profile)
  } catch (e) {
    if ([404, 405].includes(problemOf(e).status)) checkOff = true
    return
  }
  const found = remapErrors(Array.isArray(res?.errors) ? res.errors : [], kept)
  const next = {}
  for (const p of paths) next[p] = found.filter(x => within(x.path, p))
  checked.value = next
}

// ---- saving ----

async function save() {
  if (saving.value || fileError.value) return
  saving.value = true
  note.value = ''
  problem.value = ''
  conflict.value = ''
  // Entries added and left empty are not sent (Q71-04); the rows stay on screen.
  const { profile, kept } = pruneBlankEntries(draft.value)
  try {
    adopt(await saveApplicant(profile, data.value.etag))
    note.value = 'Saved.'
  } catch (e) {
    const p = problemOf(e)
    if (p.status === 409) {
      conflict.value = p.code === 'unreadable' ? 'unreadable' : 'changed'
    } else if (p.status === 422 && (p.code === 'invalid' || p.errors.length)) {
      errors.value = remapErrors(p.errors, kept)
      checked.value = {}
    } else {
      problem.value = `Could not save your details: ${p.text}`
    }
    await nextTick()
    banner.value?.focus?.()
  } finally {
    saving.value = false
  }
}

// ---- answers the owner gave to application questions (group 15) ----

const entryKind = e => e?.kind || 'text'
const scopeOf = (entry, scope) => (scope ? entry.by_employer?.[scope] ?? {} : entry)
function extraValue(entry, scope) {
  const s = scopeOf(entry, scope)
  if (entry.kind === 'choice') return s.picks?.[0] ?? null
  if (entry.kind === 'multi') return s.picks ?? []
  return s.value
}
function setExtra(key, scope, v) {
  const entry = draft.value.extra[key]
  const base = scope ? `extra.${key}.by_employer.${scope}` : `extra.${key}`
  if (entry.kind === 'choice') setAt(draft.value, `${base}.picks`, v ? [v] : [])
  else if (entry.kind === 'multi') setAt(draft.value, `${base}.picks`, v)
  else setAt(draft.value, `${base}.value`, v)
}
// Options are stored normalised (lower case); show them capitalised, keep the stored value.
const titled = norm => String(norm).replace(/\b\w/g, c => c.toUpperCase())
const seenOptions = (entry, scope) => (scopeOf(entry, scope).seen ?? entry.seen ?? []).map(n => [n, titled(n)])
const employerName = titled
async function removeAnswer(key) {
  delete draft.value.extra[key]
  if (!Object.keys(draft.value.extra).length) delete draft.value.extra
  removing.value = ''
  await save()
}

onMounted(() => {
  window.addEventListener('beforeunload', guard)
  load()
  loadDerived()
})
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', guard)
  clearTimeout(checkTimer)
  observer?.disconnect()
})
defineExpose({ load })
</script>

<template>
  <div ref="root" class="app-details" :aria-busy="loading ? 'true' : 'false'">
    <TabLoading v-if="loading" :rows="3" />
    <div v-else-if="loadError" class="notice error" role="alert">
      <p>Could not load your application details: {{ loadError }}</p>
      <button type="button" @click="load">Try again</button>
    </div>

    <template v-else-if="data">
      <div v-if="fileError" class="notice error" role="alert">
        <p>JobScraper can't read data/applicant.yaml ({{ fileError }}). Fix the file by hand. Nothing will be saved over it until then.</p>
        <button type="button" class="reload" @click="load">Check again</button>
      </div>
      <div v-else-if="conflict" ref="banner" class="notice error banner conflict" role="alert" tabindex="-1">
        <p v-if="conflict === 'changed'">
          This file changed since you opened it, in another tab or by hand. Reload to take in the latest. What you typed here is kept.
        </p>
        <p v-else>
          JobScraper can't read data/applicant.yaml. Fix the file by hand. Nothing will be saved over it until then.
        </p>
        <button type="button" class="reload" @click="conflict === 'changed' ? reloadKeepingEdits() : load()">Reload</button>
      </div>
      <div v-else-if="problem" ref="banner" class="notice error banner" role="alert" tabindex="-1">
        <p>{{ problem }}</p>
      </div>
      <div v-else-if="bannerErrors.length" ref="banner" class="notice error banner invalid" role="alert" tabindex="-1" aria-labelledby="ad-summary">
        <p id="ad-summary" class="summary-title">{{ summaryTitle }}</p>
        <ul class="summary-list">
          <li v-for="e in bannerErrors" :key="e.path + e.message">
            <span><span :class="{ mono: !canGo(e.path) }">{{ errorLabel(e.path) }}</span>: {{ e.message }}</span>
            <button v-if="canGo(e.path)" type="button" class="link go" :aria-label="`Go to ${errorLabel(e.path)}`" @click="fillIn(e.path)">Go to</button>
          </li>
        </ul>
      </div>

      <template v-if="!fileError">
        <section v-if="missing.length" class="missing surface" aria-labelledby="ad-missing">
          <h2 id="ad-missing" class="section-title">Needed before auto-apply</h2>
          <p class="muted lead">Auto-apply won't start until these are filled in.</p>
          <ul class="missing-list">
            <li v-for="path in missing" :key="path">
              <span class="missing-label">{{ labelOf(path) }}</span>
              <button v-if="path === 'documents.resume'" type="button" class="link upload" @click="goUpload">Upload in Resume and titles</button>
              <button v-else-if="canFill(path)" type="button" class="link fill" @click="fillIn(path)">Fill in</button>
              <span v-else class="muted mono path">{{ path }}</span>
            </li>
          </ul>
        </section>
      </template>

      <QuestionsInbox
        ref="inbox"
        :form="form"
        :etag="data.etag"
        @saved="reloadKeepingEdits"
        @reload="load"
        @loaded="onInboxLoaded"
      />

      <template v-if="!fileError">
        <p v-if="restored && dirty" class="notice warn restored" role="status">
          Your unsaved changes are back. <button type="button" class="link" @click="discard">Discard them</button>
        </p>
        <h2 class="section-title">Your details</h2>
        <p v-if="!data.file?.exists" class="muted lead">There is no data/applicant.yaml yet. Saving creates it.</p>
        <div v-if="meter" class="meter-row">
          <div
            class="meter"
            role="meter"
            aria-label="Details filled"
            :aria-valuenow="meter.filled"
            aria-valuemin="0"
            :aria-valuemax="meter.needed"
            :aria-valuetext="`${meter.filled} of ${meter.needed} details filled`"
          >
            <span :style="{ width: meter.needed ? `${Math.min(100, Math.round((meter.filled / meter.needed) * 100))}%` : '0%' }" />
          </div>
          <span class="meter-text">{{ meter.filled }} of {{ meter.needed }} details filled</span>
        </div>
        <!-- Only while the file still has hand-written comments (the first save removes them). -->
        <p
          v-if="data.file?.has_comments"
          class="notice warn comments-note"
          title="The copy is data/applicant.commented-backup.yaml"
        >
          Saving tidies your details file and removes its notes. A copy with your notes is kept.
        </p>

        <div class="details-body" :class="{ 'has-rail': sections.length > 1 }">
        <SectionRail v-if="sections.length > 1" class="details-rail" :sections="sections" :current="currentSection" @go="goSection" />
        <form class="the-form" novalidate @submit.prevent="save" @focusin="onFocusIn">
          <section
            v-for="g in groups"
            :key="g.id"
            class="group surface"
            :data-section="g.id"
            :aria-labelledby="`g-${g.id}`"
          >
            <header class="group-head">
              <h3 :id="`g-${g.id}`" tabindex="-1">{{ g.title }}</h3>
              <span v-if="sectionStatus(sectionOf(g.id)).tone !== 'done'" class="tag section-tag" :class="sectionStatus(sectionOf(g.id)).tone">{{ sectionStatus(sectionOf(g.id)).text }}</span>
              <span v-if="privacyOf(g).header" class="tag private">{{ privacyOf(g).header }}</span>
            </header>
            <p v-if="g.note" class="muted note">{{ g.note }}</p>

            <template v-for="item in g.items" :key="item.path">
              <div
                v-if="visible(item)"
                :id="fieldId(item.path)"
                class="field"
                :class="{ wide: wide(g, item) }"
                :data-path="item.path"
                @focusout="onFocusOut(item, $event)"
              >
                <div class="field-head">
                  <component
                    :is="labelTag(item)"
                    :id="`${fieldId(item.path)}-label`"
                    class="field-label"
                    :class="{ 'visually-hidden': labelHidden(g, item) }"
                    :for="labelTag(item) === 'label' ? `${fieldId(item.path)}-in` : undefined"
                  >{{ item.label }}</component>
                  <span v-if="needed(item)" class="tag needed">Needed</span>
                  <span v-else-if="item.required" class="tag required">{{ requiredText(item) }}</span>
                  <span v-if="item.sensitive && privacyOf(g).perItem" class="tag private" :title="PRIVATE">Private</span>
                  <span v-if="fromResume(item) && item.kind !== 'entries'" class="tag resume">From your resume, please check</span>
                  <span v-if="item.sensitive" :id="`${fieldId(item.path)}-private`" class="visually-hidden">{{ PRIVATE }}.</span>
                </div>

                <!-- Files: the resume in use and where to upload one; the path box is the exception -->
                <div v-if="hasDocs && item.path === 'documents.resume'" class="doc-status">
                  <p v-if="docs.resume" class="doc-line"><Icon name="check" :size="14" /> Using {{ docs.resume.name }}<template v-if="stamp(docs.resume.modified)">, uploaded {{ stamp(docs.resume.modified) }}</template></p>
                  <p v-else class="doc-line none">No resume yet.</p>
                  <button type="button" class="upload" @click="goUpload">Upload in Resume and titles</button>
                </div>
                <details v-if="hasDocs && item.path === 'documents.resume'" class="other-file" :open="!!valueOf(item)">
                  <summary>Use a different file</summary>
                  <FieldInput
                    :id="`${fieldId(item.path)}-in`"
                    kind="text"
                    :model-value="valueOf(item)"
                    :describedby="describedBy(g, item)"
                    :invalid="invalid(item)"
                    @update:model-value="onEdit(item, $event)"
                  />
                  <p v-if="item.help" :id="`${fieldId(item.path)}-help`" class="hint">{{ item.help }}</p>
                </details>
                <template v-else>
                  <div :class="{ 'with-status': hasDocs && item.path === 'documents.transcript' }">
                    <FieldInput
                      :id="`${fieldId(item.path)}-in`"
                      :kind="kindOf(item)"
                      :model-value="valueOf(item)"
                      :options="item.options || []"
                      :country-options="item.country_options || []"
                      :sub="item.sub || []"
                      :path="item.path"
                      :label="item.entry_label || item.label"
                      :from-resume="fromResumePaths"
                      :errors="errMap"
                      :nullable="item.nullable ?? !item.required"
                      :fixed-text="item.fixed_text || item.help || ''"
                      :multiline="!!item.multiline"
                      :autocomplete="item.autocomplete || 'off'"
                      :show-unset="true"
                      :clearable="!!item.nullable_bool"
                      :labelledby="grouped(item) ? `${fieldId(item.path)}-label` : ''"
                      :describedby="describedBy(g, item)"
                      :invalid="invalid(item)"
                      @update:model-value="onEdit(item, $event)"
                    />
                    <span v-if="hasDocs && item.path === 'documents.transcript' && transcriptKnown(item)" class="doc-found" :class="{ none: !docs.transcript }">
                      {{ docs.transcript ? 'Found' : 'Not found' }}
                    </span>
                  </div>
                  <p v-if="item.help && item.kind !== 'fixed'" :id="`${fieldId(item.path)}-help`" class="hint">{{ item.help }}</p>
                </template>

                <p v-if="warningOf(item)" :id="`${fieldId(item.path)}-warn`" class="field-warn">{{ warningOf(item) }}</p>
                <div v-if="item.path === 'skills' && resumeSkills.length" class="suggest">
                  <p class="hint">Your resume lists {{ resumeSkills.length === 1 ? '1 skill that isn\'t' : `${resumeSkills.length} skills that aren't` }} here: {{ skillPreview }}.</p>
                  <button type="button" class="add-skills" @click="addResumeSkills">
                    <Icon name="plus" /> Add {{ resumeSkills.length === 1 ? '1 skill' : `${resumeSkills.length} skills` }} from your resume
                  </button>
                </div>
                <p v-if="item.path === 'experience' && !(valueOf(item) || []).length" class="hint">
                  Experience isn't filled from your resume yet. Add your jobs here.
                </p>
                <p v-if="itemErrors(item).length" :id="`${fieldId(item.path)}-err`" class="field-error">
                  <template v-for="(e, i) in itemErrors(item)" :key="e.path + e.message"><template v-if="i"> </template>{{ e.message }}</template>
                </p>
              </div>
            </template>
          </section>

          <!-- 15: answers given to application questions -->
          <section v-if="extra.length" class="group surface extra" data-section="extra" aria-labelledby="g-extra">
            <header class="group-head">
              <h3 id="g-extra" tabindex="-1">Answers you gave to application questions</h3>
              <span v-if="extraToFix" class="tag section-tag fix">{{ extraToFix }} to fix</span>
            </header>
            <div v-for="[key, entry] in extra" :id="fieldId(`extra.${key}`)" :key="key" class="field extra-row" :data-path="`extra.${key}`">
              <div class="field-head">
                <span :id="`${fieldId(`extra.${key}`)}-label`" class="field-label">{{ entry.title || key }}</span>
                <span v-if="entry.sensitive" class="tag private">{{ PRIVATE }}</span>
              </div>
              <p v-if="entry.description" class="hint">{{ entry.description }}</p>
              <FieldInput
                :id="`${fieldId(`extra.${key}`)}-in`"
                :kind="entryKind(entry)"
                :model-value="extraValue(entry)"
                :options="seenOptions(entry)"
                :multiline="entry.kind === 'text'"
                :labelledby="`${fieldId(`extra.${key}`)}-label`"
                :invalid="extraErrors(key).length > 0"
                @update:model-value="setExtra(key, '', $event)"
              />
              <div v-for="(scoped, emp) in entry.by_employer || {}" :key="emp" class="scoped">
                <span :id="`${fieldId(`extra.${key}.${emp}`)}-label`" class="scoped-label">Only for {{ employerName(emp) }}</span>
                <FieldInput
                  :id="`${fieldId(`extra.${key}.${emp}`)}-in`"
                  :kind="entryKind(entry)"
                  :model-value="extraValue(entry, emp)"
                  :options="seenOptions(entry, emp)"
                  :multiline="entry.kind === 'text'"
                  :labelledby="`${fieldId(`extra.${key}.${emp}`)}-label`"
                  @update:model-value="setExtra(key, emp, $event)"
                />
              </div>
              <p v-for="e in extraErrors(key)" :key="e.path + e.message" class="field-error">{{ e.message }}</p>
              <div v-if="removing === key" class="confirm" role="group" :aria-labelledby="`${fieldId(`extra.${key}`)}-confirm`">
                <p :id="`${fieldId(`extra.${key}`)}-confirm`">Remove this answer? Applications that ask it will stop and ask you again.</p>
                <p v-if="dirty" class="muted">Your other unsaved changes will be saved too.</p>
                <div class="confirm-buttons">
                  <button type="button" class="danger-btn remove-yes" :disabled="saving" @click="removeAnswer(key)">Remove answer</button>
                  <button type="button" class="remove-no" @click="removing = ''">Keep it</button>
                </div>
              </div>
              <button v-else type="button" class="ghost remove" :aria-label="`Remove ${entry.title || key}`" @click="removing = key">Remove</button>
            </div>
          </section>

          <!-- 16: keys the form does not know -->
          <section v-if="others.length" class="group surface other" data-section="other" aria-labelledby="g-other">
            <header class="group-head"><h3 id="g-other" tabindex="-1">Other keys in your file</h3></header>
            <p class="muted note">These keys aren't in the form. They're kept as they are. Edit them in data/applicant.yaml.</p>
            <dl class="others">
              <div v-for="o in others" :key="o.path">
                <dt class="mono">{{ o.path }}</dt>
                <dd class="mono">{{ privatePath(o.path) ? '•••' : showValue(o.value) }}</dd>
              </div>
            </dl>
          </section>

          <div class="save-bar">
            <span v-if="dirty" class="muted unsaved">You have unsaved changes.</span>
            <p v-if="note && !dirty" class="notice ok save-note" role="status">{{ note }}</p>
            <button v-if="neededItems.length" type="button" class="next-needed" @click="nextNeeded">Next needed ({{ neededItems.length }})</button>
            <button type="button" class="ghost discard" :disabled="saving || !dirty" @click="discard">Discard changes</button>
            <button type="submit" class="primary save" :disabled="saving || (!dirty && data.file?.exists)">{{ saving ? 'Saving…' : 'Save details' }}</button>
          </div>
        </form>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
/* Every grid track is minmax(0, 1fr): an implicit `auto` track grows to its widest
   child's min-content (the rail's chip row was 1587px at 390px, Q-71 D1). */
.app-details { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-4); }
.lead { margin: 0; font-size: var(--text-sm); }
.missing { padding: var(--space-4); display: grid; gap: var(--space-2); }
.missing .section-title { margin: 0; }
.missing-list { list-style: none; margin: var(--space-2) 0 0; padding: 0; display: grid; gap: var(--space-1); }
.missing-list li { display: flex; flex-wrap: wrap; align-items: baseline; gap: 0 var(--space-3); font-size: var(--text-sm); }
.missing-label { font-weight: 600; }
.path { font-size: var(--text-xs); }
.summary-title { font-weight: 650; }
.summary-list { margin: var(--space-2) 0 0; padding-left: var(--space-5); display: grid; gap: var(--space-1); }
.summary-list li { overflow-wrap: anywhere; }
.summary-list .go { margin-left: var(--space-2); min-height: 1.5rem; color: inherit; font-weight: 600; }
.banner:focus-visible { outline-offset: 2px; }
.app-details .section-title { margin: var(--space-2) 0 0; }
.meter-row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2) var(--space-3); }
.meter { flex: 0 1 16rem; height: 0.5rem; border-radius: 999px; background: var(--surface-3); overflow: hidden; }
.meter span { display: block; height: 100%; background: var(--accent); border-radius: 999px; }
.meter-text { font-size: var(--text-sm); color: var(--text-2); }
.comments-note { margin: 0; }
.details-body { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-4); align-items: start; }
.details-rail { min-width: 0; }
.the-form { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-4); min-width: 0; }
.group { padding: var(--space-4) var(--space-5); display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-4); align-items: start; min-width: 0; scroll-margin-top: calc(var(--header-h) + var(--space-4)); }
.group-head { display: flex; align-items: center; gap: var(--space-2) var(--space-3); flex-wrap: wrap; }
.group-head h3 { margin: 0; font-size: var(--text-md); font-weight: 650; }
.group-head h3:focus { outline: none; }
.group-head h3:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
.section-tag.needed { color: var(--warn); background: var(--warn-soft); border-color: color-mix(in srgb, var(--warn) 35%, transparent); }
.section-tag.fix { color: var(--danger); background: var(--danger-soft); border-color: color-mix(in srgb, var(--danger) 35%, transparent); }
.group-head .tag.private { white-space: normal; }
.note { margin: calc(-1 * var(--space-2)) 0 0; font-size: var(--text-sm); }
/* Two columns from 900px (Q71-19): short related fields pair up, the rest take the row. */
@media (min-width: 900px) {
  .details-body.has-rail { grid-template-columns: 13rem minmax(0, 1fr); }
  .group { grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: var(--space-5); }
  .group > .group-head, .group > .note, .field.wide, .extra-row, .others { grid-column: 1 / -1; }
}
/* The sticky save bar must not cover the field that has focus (WCAG 2.4.11). */
.field { display: grid; grid-template-columns: minmax(0, 1fr); min-width: 0; gap: var(--space-1); align-content: start; scroll-margin-top: calc(var(--header-h) + var(--space-4)); scroll-margin-bottom: 6rem; }
.missing-list .upload { min-height: 1.5rem; }
.field-head { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
.field-label { font-size: var(--text-sm); font-weight: 600; }
.hint { margin: 0; font-size: var(--text-xs); color: var(--muted); max-width: 60ch; }
.field-error { margin: 0; font-size: var(--text-sm); color: var(--danger); }
.field-warn { margin: 0; font-size: var(--text-sm); color: var(--warn); max-width: 60ch; }
.suggest { display: grid; gap: var(--space-2); justify-items: start; margin-top: var(--space-1); }
.doc-status { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2) var(--space-3); }
.doc-line { margin: 0; font-size: var(--text-sm); display: inline-flex; align-items: center; gap: var(--space-1); color: var(--text-2); }
.doc-line .icon { color: var(--ok); }
.other-file summary { cursor: pointer; font-size: var(--text-sm); color: var(--accent); min-height: 1.5rem; }
.other-file[open] { display: grid; gap: var(--space-1); }
.with-status { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2); }
.doc-found { font-size: var(--text-sm); color: var(--ok); }
.doc-found.none { color: var(--warn); }
.scoped { display: grid; gap: var(--space-1); padding-left: var(--space-4); border-left: 2px solid var(--border); }
.scoped-label { font-size: var(--text-sm); color: var(--text-2); }
.extra-row + .extra-row { padding-top: var(--space-4); border-top: 1px solid var(--border); }
.confirm { display: grid; gap: var(--space-2); padding: var(--space-3); background: var(--warn-soft); border-radius: var(--radius); }
.confirm p { margin: 0; font-size: var(--text-sm); }
.confirm-buttons { display: flex; gap: var(--space-2); }
.danger-btn { background: var(--danger); border-color: var(--danger); color: var(--surface); font-weight: 600; }
.danger-btn:hover:not(:disabled) { background: var(--danger); filter: brightness(0.92); color: var(--surface); }
.remove { justify-self: start; }
.others { margin: 0; display: grid; gap: var(--space-2); }
.others > div { display: flex; flex-wrap: wrap; gap: var(--space-1) var(--space-3); }
.others dt { color: var(--muted); font-size: var(--text-xs); }
.others dd { margin: 0; font-size: var(--text-xs); overflow-wrap: anywhere; }
.save-bar {
  position: sticky; bottom: 0; z-index: 5;
  display: flex; flex-wrap: wrap; align-items: center; justify-content: flex-end; gap: var(--space-2) var(--space-3);
  padding: var(--space-3) var(--space-4);
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
}
.unsaved { font-size: var(--text-sm); margin-right: auto; }
.save-note { margin: 0 auto 0 0; padding: var(--space-1) var(--space-3); }
/* A phone (Q71-24): the sentence on its own row, the buttons below it. */
@media (max-width: 639px) {
  .save-bar { padding: var(--space-2) var(--space-3); }
  .unsaved, .save-note { flex: 1 1 100%; }
}
</style>
