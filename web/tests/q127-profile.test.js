// Q-127 pins 6, 14, 18, 19 (design B.1 R1, B.4, B.8): the Profile page never shows a question tied to a
// company or an application, under any fill policy; an invalid `extra` entry never reaches it; saving a
// section never submits anything, and "Apply again" posts only on its click, with exactly the ready jobs.
// The page is `ApplicationDetails` (Your details) with a fake server; employer-named fixtures are the
// point. Made-up names only ("Example Co", "Northwind", "Acme Trading"). No network.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import ApplicationDetails from '../src/components/ApplicationDetails.vue'

const item = (path, label, kind, flags = {}) => ({
  path, label, kind, options: [], help: '', sub: [], required: false, recommended: false, sensitive: false, ...flags,
})
const FORM = [
  { id: 'contact', title: 'Contact', note: '', items: [
    item('contact.email', 'Email for applications', 'email', { required: true }),
    item('contact.city', 'City', 'text', { required: true }),
  ] },
  { id: 'availability', title: 'Availability', note: '', items: [item('availability.notice_period_days', 'Notice period (days)', 'int')] },
]
const SECTIONS = [
  { id: 'contact', title: 'Contact', paths: ['contact.email', 'contact.city'] },
  { id: 'availability_pay', title: 'Availability and pay', paths: ['availability.notice_period_days'] },
]

// The words of the employers and questions that must never reach the page.
const FORBIDDEN = ['Why Example Co', 'Example Co', 'Northwind', 'Acme Trading', 'Describe your ideal weekend',
  'Have you ever worked for', 'Preferred work arrangement', 'Answered for you', 'Questions from applications']
const EXTRA = {
  why_example_co: { title: 'Why Example Co?', description: 'asked by Northwind', kind: 'text', sensitive: false,
    labels: ['why example co'], value: 'Because of Acme Trading', employer: 'Example Co' },
  weekend: { title: 'Describe your ideal weekend', description: '', kind: 'text', sensitive: false,
    labels: ['describe your ideal weekend'], value: 'Hiking' },
}
const BAD_EXTRA = { why_example_co: { title: 'Why Example Co?', kind: 'number', sensitive: false, labels: ['why example co'], value: 'Northwind' } }

function payload(over = {}) {
  return {
    profile: { contact: { email: 'sam.sample@example.com', city: '' }, availability: { notice_period_days: null }, extra: EXTRA },
    etag: 'aaaaaaaaaaaaaaaa', errors: [], missing: ['contact.city'], completeness: { filled: 1, needed: 2 },
    from_resume: [], sensitive: [], form: FORM, sections: SECTIONS, needed_by: { 'contact.city': 2 },
    waiting: [], extra_errors: 0, file: { exists: true, has_comments: false, error: '' }, ...over,
  }
}
const reply = (body, status = 200) => ({
  ok: status < 300, status, statusText: 'x', json: async () => JSON.parse(JSON.stringify(body ?? {})),
})

// Old question groups an employer-named server could still return: they must never be asked for.
const OLD_QUESTIONS = {
  mode: 'dry_run', busy: false, ready: [], waiting: [],
  groups: [
    { key: 'a', status: 'open', title: 'Why Example Co?', labels: ['Why Example Co?'], employers: ['Example Co'] },
    { key: 'b', status: 'answered', title: 'Describe your ideal weekend', labels: ['x'], employers: ['Northwind'] },
    { key: 'c', status: 'assumed', title: 'Preferred work arrangement', labels: ['y'], employers: ['Acme Trading'] },
  ],
}

let calls
function server({ applicant = payload(), put = null } = {}) {
  calls = []
  const fetch = vi.fn(async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase()
    const path = String(url).replace(/^\/?/, '')
    const body = init.body ? JSON.parse(init.body) : undefined
    calls.push({ method, path, body })
    if (path === 'api/applicant' && method === 'GET') return reply(applicant)
    if (path === 'api/applicant' && method === 'PUT') {
      const r = put ? put(body) : { status: 200, body: { ...applicant, profile: body.profile, etag: 'bbbbbbbbbbbbbbbb' } }
      return reply(r.body, r.status)
    }
    if (path.startsWith('api/questions')) return reply(OLD_QUESTIONS)
    if (path === 'api/apply' && method === 'POST') return reply({ queued: [], paused: false, refused: [] }, 202)
    return reply({ detail: 'Not Found' }, 404)
  })
  vi.stubGlobal('fetch', fetch)
}
async function mountPage(opts) {
  server(opts)
  const w = mount(ApplicationDetails, { attachTo: document.body })
  await flushPromises()
  await flushPromises()
  return w
}
const open = async (w, id) => { await w.find(`#ds-${id}-button`).trigger('click'); await flushPromises() }
const posts = path => calls.filter(c => c.method === 'POST' && c.path === path)

beforeEach(() => { window.localStorage.clear(); window.sessionStorage.clear() })
afterEach(() => { vi.unstubAllGlobals() })
enableAutoUnmount(afterEach)

function expectClean(w) {
  const text = w.text()
  for (const word of FORBIDDEN) expect(text, `the page shows "${word}"`).not.toContain(word)
  const html = w.html()
  for (const word of FORBIDDEN) expect(html, `the page markup holds "${word}"`).not.toContain(word)
  expect(w.find('.q-card').exists()).toBe(false)
  expect(w.find('#answered-for-you').exists()).toBe(false)
  expect(w.find('section.questions, .questions-inbox, article.q-card').exists()).toBe(false)
}

describe('Q-127 pin 6: the Profile DOM holds no employer, no question label, no card', () => {
  it('at rest, with employer-named saved answers and waiting roles', async () => {
    const w = await mountPage({ applicant: payload({ waiting: [{ job_id: 'j1', paths: ['contact.city'], ready: false }] }) })
    expect(w.text()).toContain('Contact')                       // the sections are there
    expectClean(w)
  })

  it('with every section opened in turn', async () => {
    const w = await mountPage()
    for (const s of SECTIONS) {
      await open(w, s.id)
      expectClean(w)
    }
  })

  it('never asks the server for questions, and the Profile tab imports no card component', async () => {
    const w = await mountPage()
    expect(calls.some(c => c.path.startsWith('api/questions'))).toBe(false)
    expectClean(w)
    const src = readFileSync(resolve(process.cwd(), 'src/tabs/Profile.vue'), 'utf8')
      + readFileSync(resolve(process.cwd(), 'src/components/ApplicationDetails.vue'), 'utf8')
    for (const gone of ['QuestionsInbox', 'QuestionCard', 'getQuestions', 'answerQuestion', 'keepAssumed', 'changeAssumed']) {
      expect(src, gone).not.toContain(gone)
    }
  })
})

describe('Q-127 pin 14: the strict twin (open, answered and assumed question rows exist on the server)', () => {
  it('the three statuses of employer-named rows never reach the page, strict or always', async () => {
    for (const policy of ['strict', 'always']) {
      const w = await mountPage({ applicant: payload({ fill_policy: policy }) })
      expectClean(w)
      expect(calls.filter(c => c.path.startsWith('api/questions'))).toHaveLength(0)
      w.unmount()
    }
  })
})

describe('Q-127 pin 18: an invalid saved answer named after an employer wording never reaches the page', () => {
  const badError = { path: 'extra.why_example_co.value', message: 'Why Example Co? must be a number' }

  it('neither its key nor its message is drawn, even when an older server sends the error; a status line says so', async () => {
    const w = await mountPage({ applicant: payload({
      profile: { contact: { email: 'sam.sample@example.com', city: '' }, extra: BAD_EXTRA },
      errors: [badError], extra_errors: 1,
    }) })
    for (const word of ['why_example_co', 'Why Example Co', 'must be a number', 'Northwind']) {
      expect(w.text(), word).not.toContain(word)
      expect(w.html(), word).not.toContain(word)
    }
    expect(w.text()).toContain('A saved answer needs attention. Open Settings → Apply → Answers you corrected.')
    expect(w.find('.banner.invalid').exists()).toBe(false)
  })

  it('"Other keys in your file" never lists extra.*', async () => {
    const w = await mountPage({ applicant: payload({ profile: { contact: { email: 'a@example.com', city: 'x' }, extra: EXTRA } }) })
    const other = w.find('.other-keys')
    expect(other.exists() ? other.text() : '').not.toMatch(/extra|weekend|why_example_co/)
  })

  it('the section save succeeds past the unchanged invalid entry, and a refused save never shows the error', async () => {
    const w = await mountPage({ applicant: payload({
      profile: { contact: { email: 'sam.sample@example.com', city: '' }, extra: BAD_EXTRA }, extra_errors: 1,
    }) })
    await open(w, 'contact')
    await w.find('#f-contact-city-in').setValue('Singapore')
    await w.find('.ds-save').trigger('click')
    await flushPromises()
    const puts = calls.filter(c => c.method === 'PUT')
    expect(puts).toHaveLength(1)
    expect(puts[0].body.profile.contact.city).toBe('Singapore')
    expect(w.find('.banner.error, .banner.invalid').exists()).toBe(false)

    const w2 = await mountPage({
      applicant: payload({ profile: { contact: { email: 'sam.sample@example.com', city: '' }, extra: BAD_EXTRA }, extra_errors: 1 }),
      put: () => ({ status: 422, body: { detail: 'invalid', errors: [badError] } }),
    })
    await open(w2, 'contact')
    await w2.find('#f-contact-city-in').setValue('Singapore')
    await w2.find('.ds-save').trigger('click')
    await flushPromises()
    for (const word of ['why_example_co', 'Why Example Co', 'must be a number']) expect(w2.text(), word).not.toContain(word)
  })
})

describe('Q-127 pin 19: saving a section never submits; Apply again posts only on its click', () => {
  const ready = [{ job_id: 'job-a', paths: ['contact.city'], ready: true }, { job_id: 'job-b', paths: ['contact.city'], ready: true }]
  const stillWaiting = { job_id: 'job-c', paths: ['availability.notice_period_days'], ready: false }

  async function saveWithWaiting() {
    const waitingBefore = [{ job_id: 'job-a', paths: ['contact.city'], ready: false }, { job_id: 'job-b', paths: ['contact.city'], ready: false }, stillWaiting]
    const w = await mountPage({
      applicant: payload({ waiting: waitingBefore }),
      put: body => ({ status: 200, body: { ...payload({ waiting: [...ready, stillWaiting], missing: [] }), profile: body.profile, etag: 'bbbbbbbbbbbbbbbb' } }),
    })
    await open(w, 'contact')
    await w.find('#f-contact-city-in').setValue('Singapore')
    await w.find('.ds-save').trigger('click')
    await flushPromises()
    return w
  }

  it('a save issues the PUT and no POST api/apply, and says how many were waiting', async () => {
    const w = await saveWithWaiting()
    expect(calls.filter(c => c.method === 'PUT')).toHaveLength(1)
    expect(posts('api/apply')).toHaveLength(0)
    expect(w.find('.waiting-text').text()).toBe('Saved. 2 applications were waiting for this.')
    expect(w.find('button.apply-again').text()).toBe('Apply again to 2 applications')
    expect(posts('api/apply')).toHaveLength(0)                  // showing the button sends nothing
  })

  it('the button posts exactly the ready job ids, once, only when clicked; Dismiss posts nothing', async () => {
    const w = await saveWithWaiting()
    await w.find('button.apply-again').trigger('click')
    await flushPromises()
    expect(posts('api/apply')).toHaveLength(1)
    expect(posts('api/apply')[0].body).toEqual({ job_ids: ['job-a', 'job-b'] })
    const w2 = await saveWithWaiting()
    await w2.find('button.dismiss').trigger('click')
    await flushPromises()
    expect(posts('api/apply')).toHaveLength(0)
  })

  it('a save with nobody waiting shows no notice and posts nothing', async () => {
    const w = await mountPage()
    await open(w, 'contact')
    await w.find('#f-contact-city-in').setValue('Singapore')
    await w.find('.ds-save').trigger('click')
    await flushPromises()
    expect(w.find('.waiting-notice').exists()).toBe(false)
    expect(posts('api/apply')).toHaveLength(0)
  })
})
