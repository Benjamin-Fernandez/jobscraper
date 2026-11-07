// Q-74 / D-105 UI pins (docs/architecture/q74_model_sees_sensitive.md section 5, T8): the "Private" tag follows
// the server's EFFECTIVE switch (`model_sees_private`), never the config key.
//   off: "Private: never sent to the AI"          on: "Private: local AI only"
//   header with a mix of private and open fields: "..., except City"
//   the on-state sentence goes in the title (and is the screen-reader text) of every tag.
// Synthetic data only. Verify: cd web; npx vitest run q74-private
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ApplicationDetails from '../src/components/ApplicationDetails.vue'
import QuestionCard from '../src/components/QuestionCard.vue'
import QuestionsInbox from '../src/components/QuestionsInbox.vue'
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
    if (path === 'api/applicant') return reply(payload)
    if (path.startsWith('api/questions')) return reply({ mode: 'dry_run', groups: [], ready: [], waiting: [], busy: false })
    return { ...reply({ detail: 'Not Found' }), ok: false, status: 404 }
  }))
  const w = mount(ApplicationDetails, { attachTo: document.body })
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

// ---------------------------------------------------------------- QuestionsInbox + QuestionCard

const group = (over = {}) => ({
  key: 'visa_status', title: 'Visa status', description: '', kind: 'choice', sensitive: true,
  target_path: '', status: 'open', named_by: 'rule', reason: 'no_rule', labels: ['What is your visa status?'],
  employers: ['Shopee'], waiting: 1, first_seen_at: '2026-11-02T10:00:00', last_seen_at: '2026-11-02T10:00:00',
  variants: [{ question_id: 11, label: 'What is your visa status?',
    options: [{ label: 'Citizen', norm: 'citizen' }, { label: 'Others', norm: 'others' }] }],
  ...over,
})
const questions = (groups, over = {}) => ({ mode: 'dry_run', groups, ready: [], waiting: [], busy: false, ...over })
const APPLICANT = { profile: {}, etag: 'aaaaaaaaaaaaaaaa', errors: [], missing: [], completeness: { filled: 1, needed: 2 },
  from_resume: [], sensitive: [], form: [], file: { exists: true, has_comments: false, error: '' } }

async function mountInbox(payload) {
  vi.stubGlobal('fetch', vi.fn(async url => {
    const path = String(url).replace(/^\/?/, '')
    if (path.startsWith('api/questions?')) return reply(payload)
    if (path === 'api/applicant') return reply(APPLICANT)
    return { ...reply({ detail: 'Not Found' }), ok: false, status: 404 }
  }))
  const w = mount(QuestionsInbox)
  await flushPromises()
  return w
}

describe('QuestionsInbox and QuestionCard: the badge follows the payload', () => {
  it('model_sees_private true: the card badge says "Private: local AI only" with the sentence as title', async () => {
    const w = await mountInbox(questions([group()], { model_sees_private: true }))
    const tag = w.find('.tag.private')
    expect(tag.text()).toBe(ON)
    expect(tag.attributes('title')).toBe(SENTENCE)
    expect(w.text()).not.toContain(OFF)
  })

  it('model_sees_private false or absent: the old words', async () => {
    for (const over of [{ model_sees_private: false }, {}]) {
      const w = await mountInbox(questions([group()], over))
      expect(w.find('.tag.private').text()).toBe(OFF)
      expect(w.text()).not.toContain(ON)
    }
  })

  it('an answered private question shows the same state in the "Answered questions" list', async () => {
    const answered = group({ status: 'answered', current: { value: null, picks: ['citizen'] } })
    const on = await mountInbox(questions([answered], { model_sees_private: true }))
    const off = await mountInbox(questions([answered], { model_sees_private: false }))
    const tagOf = w => w.find('.answered-item .tag.private')
    expect(tagOf(on).exists()).toBe(true)
    expect(tagOf(on).text()).toBe(ON)
    expect(tagOf(on).attributes('title')).toBe(SENTENCE)
    expect(tagOf(off).text()).toBe(OFF)
  })

  it('a bare QuestionCard follows the shared ref the inbox set', () => {
    setModelSeesPrivate(true)
    const on = mount(QuestionCard, { props: { group: group() } })
    expect(on.find('.tag.private').text()).toBe(ON)
    expect(on.find('.tag.private').attributes('title')).toBe(SENTENCE)
    setModelSeesPrivate(false)
    const off = mount(QuestionCard, { props: { group: group() } })
    expect(off.find('.tag.private').text()).toBe(OFF)
    expect(off.find('.tag.private').attributes('title')).toBe(OFF)
  })

  it('a non-private card has no tag in either state', () => {
    setModelSeesPrivate(true)
    const w = mount(QuestionCard, { props: { group: group({ sensitive: false }) } })
    expect(w.find('.tag.private').exists()).toBe(false)
  })
})
