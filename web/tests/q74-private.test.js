// Q-74 / D-105 UI pins (docs/architecture/q74_model_sees_sensitive.md section 5, T8): the "Private" tag follows
// the server's EFFECTIVE switch (`model_sees_private`), never the config key.
//   off: "Private: never sent to the AI"          on: "Private: local AI only"
//   header with a mix of private and open fields: "..., except City"
//   the on-state sentence goes in the title (and is the screen-reader text) of every tag.
// Synthetic data only. Verify: cd web; npx vitest run q74-private
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ApplicationDetails from '../src/components/ApplicationDetails.vue'
import { dismissToast } from '../src/toast.js'
import { modelSeesPrivate, privateBadge, privateSentence, setModelSeesPrivate } from '../src/privacy.js'

enableAutoUnmount(afterEach)

const OFF = 'Private: never sent to the AI'
const ON = 'Private: local AI only'
const SENTENCE = "Private. Only the AI on this computer reads it, and it's never written to logs."

const reply = body => ({ ok: true, status: 200, statusText: 'OK', json: async () => JSON.parse(JSON.stringify(body ?? {})) })

beforeEach(() => { dismissToast(); setModelSeesPrivate(false) })
afterEach(() => { vi.unstubAllGlobals(); dismissToast(); setModelSeesPrivate(false) })   // module state

describe('privacy.js words', () => {
  it('privateBadge(on) gives the tag text for each state', () => {
    expect(privateBadge(true)).toBe(ON)
    expect(privateBadge(false)).toBe(OFF)
    expect(privateBadge()).toBe(OFF)                       // defaults to the last payload: off
  })

  it('privateSentence(on): the full sentence when on, the tag text when off', () => {
    expect(privateSentence(true)).toBe(SENTENCE)
    expect(privateSentence(false)).toBe(OFF)
  })

  it('setModelSeesPrivate drives the defaults and coerces to a boolean', () => {
    setModelSeesPrivate(1)
    expect(modelSeesPrivate.value).toBe(true)
    expect(privateBadge()).toBe(ON)
    expect(privateSentence()).toBe(SENTENCE)
    setModelSeesPrivate(undefined)
    expect(modelSeesPrivate.value).toBe(false)
    expect(privateBadge()).toBe(OFF)
  })
})

// ---------------------------------------------------------------- ApplicationDetails

const item = (path, label, kind, flags = {}) => ({
  path, label, kind, options: [], help: '', sub: [], required: false, recommended: false, sensitive: false, ...flags,
})
const FORM = [
  { id: 'contact', title: 'Contact', note: '', items: [
    item('contact.email', 'Email for applications', 'email', { sensitive: true }),
    item('contact.postal_code', 'Postal code', 'digits', { sensitive: true }),
    item('contact.city', 'City', 'text'),
  ] },
  { id: 'declarations', title: 'Declarations', note: '', sensitive: true, items: [
    item('declarations.pep', 'Politically exposed person', 'bool', { sensitive: true }),
  ] },
]
const applicant = over => ({
  profile: { contact: { email: 'a@example.com', postal_code: '000001', city: 'Singapore' }, declarations: { pep: false } },
  etag: 'aaaaaaaaaaaaaaaa', errors: [], missing: [], completeness: { filled: 4, needed: 4 }, from_resume: [],
  sensitive: ['contact.email', 'contact.postal_code', 'declarations.pep'], form: FORM,
  file: { exists: true, has_comments: false, error: '' }, ...over,
})

async function mountDetails(payload) {
  vi.stubGlobal('fetch', vi.fn(async url => {
    const path = String(url).replace(/^\/?/, '')
    // Q-127: one section holding every form item, opened below (the fields sit in collapsed sections).
    if (path === 'api/applicant') {
      return reply({ ...payload, sections: [{ id: 'all', title: 'All details', paths: FORM.flatMap(g => g.items.map(i => i.path)) }] })
    }
    if (path.startsWith('api/questions')) return reply({ mode: 'dry_run', groups: [], ready: [], waiting: [], busy: false })
    return { ...reply({ detail: 'Not Found' }), ok: false, status: 404 }
  }))
  const w = mount(ApplicationDetails, { attachTo: document.body })
  await flushPromises()
  await w.find('#ds-all-button').trigger('click')
  await flushPromises()
  return w
}

describe('ApplicationDetails: the tag follows model_sees_private', () => {
  it('off: the header variant says "never sent to the AI, except City"', async () => {
    const w = await mountDetails(applicant({ model_sees_private: false }))
    const tags = w.findAll('.tag.private').map(t => t.text())
    expect(tags).toContain(`${OFF}, except City`)
    expect(tags).toContain(OFF)                            // the fully private section
    expect(tags.some(t => t.includes('local AI only'))).toBe(false)
  })

  it('on: "Private: local AI only, except City" and the sentence as title', async () => {
    const w = await mountDetails(applicant({ model_sees_private: true }))
    const tags = w.findAll('.tag.private')
    const texts = tags.map(t => t.text())
    expect(texts).toContain(`${ON}, except City`)
    expect(texts).toContain(ON)
    expect(texts.some(t => t.includes('never sent to the AI'))).toBe(false)
    expect(tags.every(t => t.attributes('title') === SENTENCE)).toBe(true)
  })

  it('a payload without the key behaves as off (an old server never claims the AI reads it)', async () => {
    const w = await mountDetails(applicant())
    expect(w.findAll('.tag.private').map(t => t.text()).join('|')).not.toContain('local AI only')
  })

  it('the screen-reader text for a private field carries the on-state sentence', async () => {
    const w = await mountDetails(applicant({ model_sees_private: true }))
    const spoken = w.find('#f-contact-email-private')
    expect(spoken.exists()).toBe(true)
    expect(spoken.text()).toContain('Only the AI on this computer reads it')
    expect(spoken.text()).not.toContain('never sent to the AI')
  })
})

// The QuestionsInbox / QuestionCard badge pins that lived here are RETIRED by Q-127 (D-215): the
// cards are gone from the Profile page. The tag words themselves (privacy.js) are pinned above and
// on the Details form; the saved-answers list shows no Private tag.
