<script setup>
// Profile -> Your details (Q-30, D-74; rebuilt by Q-127 U1, D-215, design B.4): what auto-apply
// puts on application forms, as one status line and ten collapsed section rows. The sections
// come from the server (`sections` on GET api/applicant; `detailSections.js` says each one in a
// line and counts what it still needs). A row opens in place, one at a time, and holds the
// fields the page has always drawn (`FieldInput`, the `entries` kind with add / remove / "from
// your resume" included, unchanged).
//
// There is no list of questions here and no company or question wording anywhere (D-215): a
// question an employer asked is answered by the model and kept with that application ("What
// was sent", Applications), never on this page. The page reads the profile, the form schema
// and the path counts `needed_by`; nothing else reaches it.
//
// Saving one section PUTs the whole profile with the etag it was loaded with, taking only that
// section's paths from the draft (`takeSection`), so a section's Save never writes another
// section's unsaved edits. The server refuses a stale etag (409) and a profile that fails
// validation (422, a message per path); both are said in words. Keys the form does not know
// round-trip untouched and sit in a muted disclosure at the bottom. An `extra.*` error is never
// drawn (M4): the status line carries one sentence instead.
//
// After a save that makes waiting applications ready the page says so in a persistent notice
// with "Apply again to n applications" (M6). Saving never starts an application; only that
// button does, through the same queue call the Applications "Try again" uses.
//
// Q-71: a failed save lists every error with a "Go to" link; blank added entries are left out
// of the PUT; "Needed" clears as the owner types; a field is checked when the owner leaves it
// (POST api/applicant/check, when the server has it). The schema's optional hints (`control`,
// `show_when`, `autocomplete`, `options` for countries, `documents_status`) are used when present.
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  ApiError, applyStatus, checkApplicant, describeError, enqueueMessage, getApplicant, getProfile, problemOf,
  saveApplicant, startAutoApply,
} from '../api.js'
import {
  clone, conditionHolds, entryPart, errorMap, fieldId, findItem, getAt, isEmptyValue, isFilled, joinAnd,
  mergeEdits, newSkills, otherKeys, pruneBlankEntries, remapErrors, setAt, showValue, todayIso, within,
} from '../applicantForm.js'
import { FIELD_FOCUS_KEY, refusalMessage } from '../attempts.js'
import {
  NOTHING_YET, applyAgainText, blocksOfSection, detailsNeeded, neededByFor, neededByText, newlyReady,
  revertSection, sectionDirty, sectionOfPath, sectionState, sectionSummary, sectionsOf, statusLine,
  takeSection, waitingNoticeText, withoutExtraErrors,
} from '../detailSections.js'
import { privateBadge, privateSentence } from '../privacy.js'
import { showToast } from '../toast.js'
import DetailSection from './DetailSection.vue'
import FieldInput from './FieldInput.vue'
import Icon from './Icon.vue'

const emit = defineEmits(['counts', 'go-view'])

// D-105: the Private tag's words follow the server's effective switch (q74 design §5).
const seesPrivate = computed(() => !!data.value?.model_sees_private)
const PRIVATE = computed(() => privateBadge(seesPrivate.value))
const PRIVATE_SENTENCE = computed(() => privateSentence(seesPrivate.value))
// What a screen reader hears on each private field: the sentence, ending in a stop.
const PRIVATE_SPOKEN = computed(() => (PRIVATE_SENTENCE.value.endsWith('.') ? PRIVATE_SENTENCE.value : `${PRIVATE_SENTENCE.value}.`))
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
const errors = ref([])          // [{path, message}] from the last save or load (never `extra.*`)
const conflict = ref('')        // '' | 'changed' | 'unreadable' (a 409 on save)
const problem = ref('')         // a save that failed for a reason that is not 409 or 422
const restored = ref(false)     // the draft came back from sessionStorage
const banner = ref(null)
const derivedSkills = ref([])   // the skills the resume parse found (GET api/profile)
const touched = ref([])         // item paths the owner changed since the last load or save
const checked = ref({})         // item path -> [{path, message}] from the last blur check
const openId = ref('')          // the one open section ('' = all collapsed)
const leaving = ref(null)       // {to, focus}: a dirty section is being left; the in-row confirm is up
const notice = ref(null)        // M6: {sectionId, jobIds, n, busy, error}, until dismissed
let checkTimer = null
let checkOff = false            // the server has no check route: stop asking

const form = computed(() => data.value?.form ?? [])
const sections = computed(() => sectionsOf(data.value))
const missing = computed(() => data.value?.missing ?? [])
const neededBy = computed(() => data.value?.needed_by ?? {})
const fileError = computed(() => data.value?.file?.error || '')
const sensitive = computed(() => data.value?.sensitive ?? [])
const fromResumePaths = computed(() => data.value?.from_resume ?? [])
const saved = computed(() => data.value?.profile ?? {})
const dirty = computed(() => !!data.value && JSON.stringify(draft.value) !== JSON.stringify(saved.value))
const others = computed(() => (data.value ? otherKeys(draft.value, form.value) : []))
const openSection = computed(() => sections.value.find(s => s.id === openId.value) ?? null)

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

// ---- the status line and the section rows ----
const needed = computed(() => detailsNeeded(missing.value, neededBy.value, form.value))
const status = computed(() => statusLine({
  form: form.value, needed: needed.value, waiting: data.value?.waiting ?? [], extraErrors: data.value?.extra_errors ?? 0,
}))
const noFile = computed(() => !!data.value && !data.value.file?.exists)
const rows = computed(() => sections.value.map(section => {
  const ctx = {
    form: form.value, profile: saved.value, missing: missing.value, neededBy: neededBy.value, errors: shownErrors.value,
  }
  return {
    section,
    state: sectionState(section, ctx),
    summary: noFile.value ? NOTHING_YET : sectionSummary(section, saved.value, form.value, hasDocs.value ? docs.value : null),
    dirty: sectionDirty(section, saved.value, draft.value),
  }
}))

// The Profile tab shows "what needs you" in the view's label.
function report() {
  emit('counts', { needed: needed.value.length })
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
  errors.value = withoutExtraErrors(res.errors)
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
  try {
    adopt(await getApplicant())
    restoreDraft()
  } catch (e) {
    loadError.value = describeError(e)
  } finally {
    loading.value = false
  }
  showWishedField()
}

// Another write changed the file (a 409): take its new etag and answers, but keep what is
// typed here and not yet saved. The merge is per leaf (`mergeEdits`): only the leaves the
// owner changed here come from the draft, everything else from the file.
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
  errors.value = withoutExtraErrors(res.errors)
  conflict.value = ''
  checked.value = {}
  report()
}

// Throw away every unsaved edit (the "Your unsaved changes are back" notice).
function discardAll() {
  draft.value = clone(data.value.profile ?? {})
  errors.value = withoutExtraErrors(data.value.errors)
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

const valueOf = item => getAt(draft.value, item.path)
// A bool the schema marks as a question (`control: 'yes_no'`) is Yes / No radios (Q71-12).
const kindOf = item => (item.kind === 'bool' && item.control === 'yes_no' ? 'yes_no' : item.kind)
const grouped = item => GROUPED.has(kindOf(item))
const isMissing = item => missing.value.some(m => within(m, item.path))
// Filled as the server counts it (applicant._filled), so "Needed" goes as soon
// as the field is filled here, not at the next save (Q71-06).
const filledHere = item => isFilled(item, valueOf(item))
// How many waiting applications need this item (0 = none), from the server's `needed_by`.
const waitingCount = item => neededByFor(item, neededBy.value)
// "Needed": the server says it is missing (or an application waits on it) and it has not been
// filled in here yet.
const needs = item => (isMissing(item) || waitingCount(item) > 0) && !filledHere(item)
const fromResume = item => fromResumePaths.value.some(p => within(p, item.path))
const privatePath = path => sensitive.value.some(s => within(path, s))
const labelTag = item => (grouped(item) ? 'span' : 'label')
const wide = (b, item) => WIDE_GROUPS.has(b.group.id) || WIDE_KINDS.has(kindOf(item)) || !!item.multiline
// The title already says it ("Education" / "Education"): keep the label for screen readers only.
const labelHidden = (b, item) => b.items.length === 1 && item.label === b.group.title
const requiredText = item => (item.kind === 'bool' ? 'Must be Yes for auto-apply' : 'Required for auto-apply')
const blocksOf = section => blocksOfSection(section, form.value)

// "Private" once per block (Q71-20). A block that is all private says so in its header; one
// that is mostly private names the exceptions; one with a few private fields tags those. Each
// private field still carries the full words for screen readers (in its description).
function privacyOf(b) {
  const items = b.items || []
  const open = items.filter(i => !i.sensitive)
  if (open.length === items.length) return { header: '', perItem: false }
  if (b.sensitive || !open.length) return { header: PRIVATE.value, perItem: false }
  if (open.length < items.length - open.length) return { header: `${PRIVATE.value}, except ${joinAnd(open.map(i => i.label))}`, perItem: false }
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

const describedBy = item => [
  item.help && item.kind !== 'fixed' ? `${fieldId(item.path)}-help` : '',
  warningOf(item) ? `${fieldId(item.path)}-warn` : '',
  item.sensitive ? `${fieldId(item.path)}-private` : '',
  itemErrors(item).length ? `${fieldId(item.path)}-err` : '',
].filter(Boolean).join(' ')

// ---- the error summary (Q71-03) ----

const entryIndex = path => {
  const m = /^[^[]*\[(\d+)\]/.exec(String(path))
  return m ? Number(m[1]) : null
}
// "Email for applications", "School 1 · Degree", or the bare path for a key the form doesn't know.
function errorLabel(path) {
  const hit = findItem(form.value, path)
  if (!hit) return path
  const i = hit.item.kind === 'entries' ? entryIndex(path) : null
  if (i === null) return hit.label
  const name = `${hit.item.entry_label || hit.item.label} ${i + 1}`
  return hit.sub ? `${name} · ${hit.sub.label}` : name
}
const canGo = path => !!findItem(form.value, path)
const summaryTitle = computed(() => {
  const n = bannerErrors.value.length
  return n === 1 ? '1 detail needs fixing before you can save' : `${n} details need fixing before you can save`
})

// ---- opening a section, and going to a field: Fill in, Go to ----

// The element for a path: an entry's own sub-field ("education[0].end"), the
// entry, or the item's block. Only a field of the open section is in the page.
function targetOf(path) {
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
  if (!el) return false
  const control = el.matches?.('input, select, textarea, button')
    ? el
    : el.querySelector('input:not([type="hidden"]), select, textarea, button')
  const closed = control?.closest?.('details')
  if (closed && !closed.open) closed.open = true
  el.scrollIntoView?.({ block: 'center' })
  control?.focus?.()
  return true
}
const canFill = path => !!findItem(form.value, path)

// Put the focus on the first control of a section (a wish that names a whole group).
function focusSection(id) {
  const panel = document.getElementById(`ds-${id}-panel`)
  const control = panel?.querySelector('input:not([type="hidden"]), select, textarea, button')
  control?.focus?.()
}

async function settle(to, focus = '', wholeSection = false) {
  leaving.value = null
  openId.value = to
  if (!to) return
  await nextTick()
  if (focus) fillIn(focus)
  else if (wholeSection) focusSection(to)
}

// One section open at a time. Leaving a section with unsaved edits asks first, in its row.
function requestOpen(to, focus = '', wholeSection = false) {
  const cur = openSection.value
  if (cur && cur.id !== to && sectionDirty(cur, saved.value, draft.value)) {
    leaving.value = { to, focus, wholeSection }
    return Promise.resolve()
  }
  return settle(to, focus, wholeSection)
}
const toggle = id => requestOpen(openId.value === id ? '' : id)

// "Fill in" and "Go to": open the section that holds the path, then focus the field.
function go(path) {
  const s = sectionOfPath(sections.value, path, form.value)
  if (s) requestOpen(s.id, canFill(path) ? path : '')
}

function revert(section) {
  draft.value = revertSection(section, saved.value, draft.value)
  errors.value = withoutExtraErrors(data.value.errors)
  touched.value = []
  checked.value = {}
}
function cancel() {
  if (openSection.value) revert(openSection.value)
  settle('')
}
async function confirmSave() {
  const l = leaving.value
  if (!l) return
  if (await save()) settle(l.to, l.focus, l.wholeSection)
  else leaving.value = null
}
function confirmDiscard() {
  const l = leaving.value
  if (!l) return
  if (openSection.value) revert(openSection.value)
  settle(l.to, l.focus, l.wholeSection)
}

// A wish from an application row ("Add it") leaves the profile path it wants in
// sessionStorage (`openAnswer`, attempts.js), and announces it for a form that is already
// drawn. A field path opens its section and focuses the field (the same as "Fill in"; no smooth
// scroll, so reduced motion is respected); a group id opens the section that holds the group.
// The wish is read and cleared whether or not it can be shown, so a stale one never fires
// later; an unknown path leaves the page where it is.
async function showWishedField(path) {
  let wish = typeof path === 'string' ? path : ''
  try {
    wish ||= window.sessionStorage.getItem(FIELD_FOCUS_KEY) || ''
    window.sessionStorage.removeItem(FIELD_FOCUS_KEY)
  } catch { /* private window */ }
  wish = wish.trim()
  if (!wish || !data.value) return
  const s = sectionOfPath(sections.value, wish, form.value)
  if (!s) return
  await nextTick()
  requestOpen(s.id, canFill(wish) ? wish : '', !canFill(wish))
}
function onShowField(e) {
  showWishedField(e?.detail?.path)
}

// ---- work rights under "Always answer" (Q-121 U1, llm_first_fill_design section 3.3) ----
// When forms are answered automatically, a right-to-work question is answered from these
// rows alone. Two things make that answer a guess: no rows at all, or "yes" for every other
// country with a single nationality. The warning needs the server to say that "always" is
// in force (`GET apply/status` -> fill.fill_policy_effective); an older server, or a
// profile without the Work status block, shows nothing.
const WORK_RIGHTS_PATH = 'singapore_status.authorised_to_work'
const fillEffective = ref(null)
async function loadFillPolicy() {
  try {
    fillEffective.value = (await applyStatus())?.fill?.fill_policy_effective ?? null
  } catch { fillEffective.value = null }   // a quiet look: no warning if the server won't say
}
const isMap = v => !!v && typeof v === 'object' && !Array.isArray(v) && Object.keys(v).length > 0
const workRightsNote = computed(() => {
  if (fillEffective.value !== 'always') return ''
  const st = draft.value?.singapore_status
  if (!st || typeof st !== 'object' || Array.isArray(st)) return ''
  if (!isMap(st.authorised_to_work) && !isMap(st.requires_sponsorship)) {
    return 'Your profile has no work-rights answers, so right-to-work questions will be answered by assumption.'
  }
  const nat = st.nationality
  const nationalities = (Array.isArray(nat) ? nat : [nat]).filter(n => typeof n === 'string' && n.trim())
  if (st.authorised_to_work?.default === true && nationalities.length <= 1) {
    return "Your profile says you may work in every country. Check the 'every other country' answer."
  }
  return ''
})

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
  const found = remapErrors(withoutExtraErrors(Array.isArray(res?.errors) ? res.errors : []), kept)
  const next = {}
  for (const p of paths) next[p] = found.filter(x => within(x.path, p))
  checked.value = next
}

// ---- saving one section ----

// True when the section was saved. A failure says why and leaves the section open.
async function save() {
  const section = openSection.value
  if (!section || saving.value || fileError.value) return false
  saving.value = true
  problem.value = ''
  conflict.value = ''
  // Entries added and left empty are not sent (Q71-04); the rows stay on screen.
  const { profile: pruned, kept } = pruneBlankEntries(draft.value)
  const body = takeSection(section, saved.value, pruned)
  // Other sections' unsaved edits survive this save: they are put back on the fresh profile.
  const keep = sections.value.filter(s => s.id !== section.id && sectionDirty(s, saved.value, draft.value))
  const waitingBefore = data.value.waiting ?? []
  try {
    const res = await saveApplicant(body, data.value.etag)
    let next = clone(res.profile ?? {})
    for (const s of keep) next = takeSection(s, next, draft.value)
    data.value = res
    draft.value = next
    errors.value = withoutExtraErrors(res.errors)
    touched.value = []
    checked.value = {}
    report()
    const ready = newlyReady(section, waitingBefore, res.waiting)
    if (ready.length) {
      notice.value = { sectionId: section.id, jobIds: ready.map(w => String(w.job_id)), n: ready.length, busy: false, error: '' }
    } else {
      showToast({ message: 'Saved.' })
    }
    return true
  } catch (e) {
    const p = problemOf(e)
    if (p.status === 409) {
      conflict.value = p.code === 'unreadable' ? 'unreadable' : 'changed'
    } else if (p.status === 422 && (p.code === 'invalid' || p.errors.length)) {
      errors.value = withoutExtraErrors(remapErrors(p.errors, kept))
      checked.value = {}
    } else {
      problem.value = `Could not save your details: ${p.text}`
    }
    // The section's controls are disabled while saving: enable them before moving the focus.
    saving.value = false
    await nextTick()
    // A refused save moves the focus to the first error: its field when it is in the open
    // section, else the summary above (with a "Go to" for each).
    const first = errors.value[0]
    const there = first && sectionOfPath(sections.value, first.path, form.value)?.id === openId.value
    if (!(there && !conflict.value && !problem.value && fillIn(first.path))) banner.value?.focus?.()
    return false
  } finally {
    saving.value = false
  }
}

// ---- the waiting notice (M6) ----

// The only thing on this page that starts applications, and only when the owner clicks it:
// the same queue call as "Try again" on an Applications row.
async function applyAgain() {
  const n = notice.value
  if (!n || n.busy) return
  n.busy = true
  n.error = ''
  try {
    const r = await startAutoApply(n.jobIds)
    const refused = Array.isArray(r?.refused) ? r.refused.map(x => x.text).filter(Boolean) : []
    showToast({ message: [enqueueMessage(r), ...refused].join(' '), link: { label: 'See the queue', href: '#/runs' } })
    window.dispatchEvent(new Event('jobscraper:apply-queue'))
    notice.value = null
  } catch (e) {
    n.busy = false
    n.error = e instanceof ApiError && e.status === 422
      ? refusalMessage(e.body)
      : `Could not add them to the auto-apply queue: ${describeError(e)}`
  }
}

onMounted(() => {
  window.addEventListener('beforeunload', guard)
  window.addEventListener('jobscraper:show-field', onShowField)
  load()
  loadDerived()
  loadFillPolicy()
})
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', guard)
  window.removeEventListener('jobscraper:show-field', onShowField)
  clearTimeout(checkTimer)
})
defineExpose({ load })
</script>

<template>
  <div class="app-details">
    <!-- Loading: ten rows about the height of the real ones. -->
    <div v-if="loading" class="ui-card sk-card" role="status" aria-busy="true">
      <span class="visually-hidden">Loading your details…</span>
      <span v-for="n in 10" :key="n" class="ui-skeleton sk-row" aria-hidden="true" />
    </div>
    <div v-else-if="loadError" class="notice error" role="alert">
      <p>Couldn't load your details. {{ loadError }}</p>
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
            <button v-if="canGo(e.path)" type="button" class="link go" :aria-label="`Go to ${errorLabel(e.path)}`" @click="go(e.path)">Go to</button>
          </li>
        </ul>
      </div>

      <template v-if="!fileError">
        <!-- The status line: one card, one row. -->
        <section class="ui-card status-card" aria-label="Details status">
          <div class="status-row">
            <span class="ui-badge status-badge" :data-tone="status.tone">{{ status.badge }}</span>
            <div class="status-text">
              <p class="status-main">{{ status.text }}</p>
              <p v-if="status.waitingText" class="status-waiting muted">{{ status.waitingText }}</p>
              <p v-if="status.attentionText" class="status-attention" role="status">{{ status.attentionText }}</p>
            </div>
            <button v-if="!status.ready && status.firstPath" type="button" class="primary fill-in" @click="go(status.firstPath)">Fill in</button>
          </div>
        </section>

        <p v-if="noFile" class="muted lead">Nothing saved yet. Your details stay on this computer.</p>
        <p v-if="restored && dirty" class="notice warn restored" role="status">
          Your unsaved changes are back. <button type="button" class="link" @click="discardAll">Discard them</button>
        </p>
        <!-- Only while the file still has hand-written comments (the first save removes them). -->
        <p
          v-if="data.file?.has_comments"
          class="notice warn comments-note"
          title="The copy is data/applicant.commented-backup.yaml"
        >
          Saving tidies your details file and removes its notes. A copy with your notes is kept.
        </p>
        <p v-if="workRightsNote" class="notice warn work-rights-note" role="status">
          {{ workRightsNote }}
          <button v-if="canFill(WORK_RIGHTS_PATH)" type="button" class="link work-rights-fix" @click="go(WORK_RIGHTS_PATH)">Check work rights</button>
        </p>

        <!-- The section rows: from the server's `sections`, collapsed, one open at a time. -->
        <div class="ui-card sections-card">
          <DetailSection
            v-for="r in rows"
            :id="r.section.id"
            :key="r.section.id"
            :title="r.section.title"
            :summary="r.summary"
            :status="{ text: r.state.text, tone: r.state.tone }"
            :fix-text="r.state.fixText"
            :dirty="r.dirty"
            :open="openId === r.section.id"
            :saving="saving && openId === r.section.id"
            :can-save="(r.dirty || noFile) && !saving"
            :confirming="!!leaving && openId === r.section.id"
            @toggle="toggle(r.section.id)"
            @save="save"
            @cancel="cancel"
            @confirm-save="confirmSave"
            @confirm-discard="confirmDiscard"
            @keep-editing="leaving = null"
          >
            <template #notice>
              <div v-if="notice && notice.sectionId === r.section.id" class="notice ok waiting-notice" role="status">
                <p class="waiting-text">{{ waitingNoticeText(notice.n) }}</p>
                <p v-if="notice.error" class="field-error" role="alert">{{ notice.error }}</p>
                <div class="waiting-buttons">
                  <button type="button" class="primary apply-again" :disabled="notice.busy" @click="applyAgain">{{ notice.busy ? 'Adding…' : applyAgainText(notice.n) }}</button>
                  <button type="button" class="ghost dismiss" :disabled="notice.busy" @click="notice = null">Dismiss</button>
                </div>
              </div>
            </template>

            <div v-for="b in blocksOf(r.section)" :key="b.group.id" class="block">
              <header v-if="blocksOf(r.section).length > 1 || privacyOf(b).header" class="block-head">
                <h4 v-if="blocksOf(r.section).length > 1" class="block-title">{{ b.group.title }}</h4>
                <span v-if="privacyOf(b).header" class="tag private" :title="PRIVATE_SENTENCE">{{ privacyOf(b).header }}</span>
              </header>
              <p v-if="b.group.note" class="muted note">{{ b.group.note }}</p>

              <div class="block-fields">
                <template v-for="item in b.items" :key="item.path">
                  <div
                    v-if="visible(item)"
                    :id="fieldId(item.path)"
                    class="field"
                    :class="{ wide: wide(b, item) }"
                    :data-path="item.path"
                    @focusout="onFocusOut(item, $event)"
                  >
                    <div class="field-head">
                      <component
                        :is="labelTag(item)"
                        :id="`${fieldId(item.path)}-label`"
                        class="field-label"
                        :class="{ 'visually-hidden': labelHidden(b, item) }"
                        :for="labelTag(item) === 'label' ? `${fieldId(item.path)}-in` : undefined"
                      >{{ item.label }}</component>
                      <span v-if="needs(item)" class="tag needed">Needed</span>
                      <span v-else-if="item.required" class="tag required">{{ requiredText(item) }}</span>
                      <span v-if="needs(item) && waitingCount(item) > 0" class="tag needed-by">{{ neededByText(waitingCount(item)) }}</span>
                      <span v-if="item.sensitive && privacyOf(b).perItem" class="tag private" :title="PRIVATE_SENTENCE">Private</span>
                      <span v-if="fromResume(item) && item.kind !== 'entries'" class="tag resume">From your resume, please check</span>
                      <span v-if="item.sensitive" :id="`${fieldId(item.path)}-private`" class="visually-hidden">{{ PRIVATE_SPOKEN }}</span>
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
                        :describedby="describedBy(item)"
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
                          :describedby="describedBy(item)"
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
              </div>
            </div>
          </DetailSection>
        </div>

        <!-- Keys the form does not know: kept as they are, edited by hand. Never an `extra.*` key. -->
        <details v-if="others.length" class="other-keys muted">
          <summary>Other keys in your file</summary>
          <p class="note">These keys aren't in the form. They're kept as they are. Edit them in data/applicant.yaml.</p>
          <dl class="others">
            <div v-for="o in others" :key="o.path">
              <dt class="mono">{{ o.path }}</dt>
              <dd class="mono">{{ privatePath(o.path) ? '•••' : showValue(o.value) }}</dd>
            </div>
          </dl>
        </details>

        <p class="muted pointer">Answers you corrected for next time are in <a class="text-link" href="#/settings/apply/answers-corrected">Settings → Apply</a>.</p>
      </template>
    </template>
  </div>
</template>

<style scoped>
/* Every grid track is minmax(0, 1fr): an implicit `auto` track grows to its widest
   child's min-content (the rail's chip row was 1587px at 390px, Q-71 D1). */
.app-details { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-4); }
.lead { margin: 0; font-size: var(--text-sm); }
.summary-title { font-weight: 650; }
.summary-list { margin: var(--space-2) 0 0; padding-left: var(--space-5); display: grid; gap: var(--space-1); }
.summary-list li { overflow-wrap: anywhere; }
.summary-list .go { margin-left: var(--space-2); min-height: 1.5rem; color: inherit; font-weight: 600; }
.banner:focus-visible { outline-offset: 2px; }
.comments-note, .work-rights-note, .restored { margin: 0; }

/* Loading. */
.sk-card { display: grid; gap: var(--space-3); }
.sk-row { height: 3rem; }

/* The status line. */
.status-row { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2) var(--space-4); }
.status-text { flex: 1 1 16rem; min-width: 0; display: grid; gap: var(--space-1); }
.status-text p { margin: 0; overflow-wrap: anywhere; }
.status-attention { color: var(--warn); font-size: var(--text-sm); }
.status-waiting { font-size: var(--text-sm); }
.fill-in { min-height: var(--touch-min); }
@media (max-width: 639px) {
  .status-row { display: grid; justify-items: start; }
  .fill-in { width: 100%; }
}

/* The card of section rows: the Settings row look (Q116 §3), no padding of its own. */
.sections-card { padding: 0; overflow: clip; }
.waiting-notice { margin: 0 var(--space-4) var(--space-3); display: grid; gap: var(--space-2); }
.waiting-notice p { margin: 0; }
.waiting-buttons { display: flex; flex-wrap: wrap; gap: var(--space-2); }
@media (max-width: 639px) {
  .waiting-notice { margin: 0 var(--space-3) var(--space-3); }
  .waiting-buttons button { min-height: var(--touch-min); }
}

/* Inside an open section. */
.block { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-3); min-width: 0; }
.block + .block { padding-top: var(--space-4); border-top: 1px solid var(--border); }
.block-head { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-2) var(--space-3); }
.block-title { margin: 0; font-size: var(--text-sm); font-weight: 650; }
.block-head .tag.private { white-space: normal; }
.note { margin: 0; font-size: var(--text-sm); color: var(--muted); }
.block-fields { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--space-4); min-width: 0; }
/* Two columns from 900px (Q71-19): short related fields pair up, the rest take the row. */
@media (min-width: 900px) {
  .block-fields { grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: var(--space-5); }
  .field.wide { grid-column: 1 / -1; }
}
/* The sticky Save bar must not cover the field that has focus (WCAG 2.4.11). */
.field { display: grid; grid-template-columns: minmax(0, 1fr); min-width: 0; gap: var(--space-1); align-content: start; scroll-margin-top: calc(var(--header-h) + var(--space-4)); scroll-margin-bottom: 8rem; }
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

/* The foot: unknown keys and the pointer to Settings. */
.other-keys summary { cursor: pointer; font-size: var(--text-sm); min-height: 1.5rem; }
.other-keys .note { margin: var(--space-2) 0; }
.others { margin: 0; display: grid; gap: var(--space-2); }
.others > div { display: flex; flex-wrap: wrap; gap: var(--space-1) var(--space-3); }
.others dt { color: var(--muted); font-size: var(--text-xs); }
.others dd { margin: 0; font-size: var(--text-xs); overflow-wrap: anywhere; }
.pointer { margin: 0; font-size: var(--text-sm); }
@media (max-width: 639px) {
  .other-keys summary { display: flex; align-items: center; min-height: var(--touch-min); }
}
</style>
