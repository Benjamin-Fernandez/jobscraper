// Q-127 Release 1 polish pass (D-215), pins on what the owner sees:
//   P1  the "Your details" pointer and the shared-answer refusal link both go to
//       `#/settings/apply/answers-corrected` (and that hash is a real Settings row);
//   P2  in the Applications tab every attempt that recorded answers offers "See what was sent"
//       (a sent / unconfirmed attempt) or "See what was filled" (a dry run, a needs-input or a
//       stopped attempt); the panel asks for THAT attempt's answers with the right ids;
//   P3  no control anywhere in the tab or the row says "Answer in Application details" / "Answer in
//       Profile";
//   P4  Settings -> Apply "Write cover letters" says what Off means under each fill policy, and no
//       longer says "you're asked instead".
// Fake fetch only (no `POST api/apply` is ever served). Made-up names only. No network.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ApplicationDetails from '../src/components/ApplicationDetails.vue'
import Applications from '../src/tabs/Applications.vue'
import Settings from '../src/tabs/Settings.vue'
import WhatWasSent from '../src/components/WhatWasSent.vue'
import sample from './fixtures/connections.sample.json'
import { fakeApi, pinZone, runsFrom, setHash } from './helpers.js'
import { mailView } from './mailFake.js'
import { cloneSample, routeFetch } from './q100Fake.js'

pinZone()
enableAutoUnmount(afterEach)

const HASH = '#/settings/apply/answers-corrected'

beforeEach(() => {
  pinZone()
  window.localStorage.clear()
  window.sessionStorage.clear()
  setHash('')
})
afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
  setHash('')
})

// One attempt as attempt_view serves it.
const attempt = (kind, id, extra = {}) => ({
  id, mode: kind === 'dry_run' ? 'dry_run' : 'auto', state: 'failed', kind, reason_code: null, text: '', hint: '',
  queued_at: '2026-11-02T01:00:00', finished_at: '2026-11-02T01:05:00', submit_clicked_at: null, resume_source: null, ...extra,
})
const answersBody = (id, kind) => ({
  attempt: { id, kind, state: 'submitted', finished_at: '2026-11-02T01:05:00', trial: false, entries_note: '' },
  employer: 'Example Co',
  fields: [{
    id: 1, step: 's1', label: 'First name', type: 'text', required: true, value_text: 'Sam', basis_text: 'From your details: First name',
    assumed: false, reason_text: '', status: 'not_sent', remembered_text: '', can_remember: true, refusal: '', options: [],
  }],
})

// ------------------------------------------------------------------ P1: the two links

describe('Q-127 polish P1: pointers to Settings -> Apply -> Answers you corrected', () => {
  it('the "Your details" pointer is a link to the answers-corrected row', async () => {
    const reply = body => ({ ok: true, status: 200, statusText: 'OK', json: async () => JSON.parse(JSON.stringify(body)) })
    vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => {
      const path = String(url).replace(/^\/?/, '')
      if (path === 'api/applicant' && (init.method || 'GET').toUpperCase() === 'GET') {
        return reply({
          profile: { contact: { email: 'sam.sample@example.com' } }, etag: 'aaaaaaaaaaaaaaaa', errors: [], missing: [],
          completeness: { filled: 1, needed: 1 }, from_resume: [], sensitive: [], needed_by: {}, waiting: [], extra_errors: 0,
          form: [{ id: 'contact', title: 'Contact', note: '', items: [{ path: 'contact.email', label: 'Email', kind: 'email', options: [], help: '', sub: [], required: true, recommended: false, sensitive: false }] }],
          sections: [{ id: 'contact', title: 'Contact', paths: ['contact.email'] }],
          file: { exists: true, has_comments: false, error: '' },
        })
      }
      return { ok: false, status: 404, statusText: 'Not Found', json: async () => ({ detail: 'Not Found' }) }
    }))
    const w = mount(ApplicationDetails, { attachTo: document.body })
    await flushPromises()
    await flushPromises()
    const link = w.find('.pointer a')
    expect(link.exists()).toBe(true)
    expect(link.attributes('href')).toBe(HASH)
    expect(w.find('.pointer').text()).toContain('Answers you corrected for next time')
  })

  it('the shared-answer refusal link in What was sent is a link to the same row', async () => {
    routeFetch({
      'GET applications/job1/attempts/5/answers': {
        ...answersBody(5, 'sent'),
        fields: [{ ...answersBody(5, 'sent').fields[0], id: 7, label: 'Why this role?', can_remember: false, refusal: 'shared_answer' }],
      },
      'GET applicant': { etag: 'etag-1', profile: {} },
    })
    const w = mount(WhatWasSent, { props: { jobId: 'job1', attemptId: 5, sent: true, employerName: 'Example Co' }, attachTo: document.body })
    await flushPromises()
    const link = w.find('.wws-refusal-link')
    expect(link.exists()).toBe(true)
    expect(link.element.tagName).toBe('A')
    expect(link.attributes('href')).toBe(HASH)
  })

  it('that hash is a real Settings row (the link lands somewhere)', async () => {
    const base = fakeApi()
    routeFetch({
      'GET connections': cloneSample(sample), 'GET mail': mailView({ accounts: [] }),
      'GET apply/status': { mode: 'dry_run', missing: [], busy: false },
      'GET apply/settings': { mode: 'dry_run', writable: true, daily_cap: 0, per_employer_daily_cap: 10, headed: false, captcha_wait_s: 120, compose_enabled: false },
      'GET applicant': { missing: [], completeness: { filled: 1, needed: 1 }, form: null },
      'GET apply/remembered': { items: [], count: 0, etag: 'e1', unreadable: false },
    }, { fallback: base.fetch })
    setHash(HASH)
    const w = mount(Settings, { props: { run: 'all', jobs: [] }, attachTo: document.body })
    await flushPromises()
    expect(w.find('#setting-answers-corrected').exists()).toBe(true)
  })
})

// ------------------------------------------------------------------ P2 + P3: the Applications tab

const OLD_BUTTONS = /Answer in (Application details|Profile)/i

describe('Q-127 polish P2/P3: Applications tab', () => {
  let net
  function open(attempts, statuses = { a1b2c3: 'to_apply', d4e5f6: 'to_apply' }) {
    const base = fakeApi({ statuses, attempts })
    const routes = {}
    for (const [job, list] of Object.entries(attempts)) {
      for (const a of list) routes[`GET applications/${job}/attempts/${a.id}/answers`] = answersBody(a.id, a.kind)
    }
    net = routeFetch(routes, { fallback: base.fetch })
  }
  const mountTab = async () => {
    const w = mount(Applications, { props: { run: 12, runs: runsFrom(), jobs: [] }, attachTo: document.body })
    await flushPromises()
    return w
  }
  const row = (w, id) => w.find(`.app-row[data-job="${id}"]`)
  async function showDetails(w, id) {
    await row(w, id).find('.app-more-trigger').trigger('click')
    await flushPromises()
    const item = row(w, id).findAll('[role="menuitem"]').find(b => /^Show details$/.test(b.text().trim()))
    await item.trigger('click')
    await flushPromises()
  }
  const answerCalls = () => net.calls.filter(c => /\/answers$/.test(c.path)).map(c => c.path)

  const KINDS = [
    ['sent', 'See what was sent'], ['unconfirmed', 'See what was sent'],
    ['dry_run', 'See what was filled'], ['needs_input', 'See what was filled'], ['stopped', 'See what was filled'],
  ]

  it.each(KINDS)('a %s attempt offers "%s" and its panel loads that attempt\'s own answers', async (kind, label) => {
    open({ a1b2c3: [attempt(kind, 42, { reason_code: kind === 'needs_input' ? 'unanswerable_required' : null })] })
    const w = await mountTab()
    await showDetails(w, 'a1b2c3')
    const btn = w.find('.attempt-item .attempt-filled')
    expect(btn.text()).toBe(label)
    expect(answerCalls()).toEqual([])                                   // nothing is asked until the click
    await btn.trigger('click')
    await flushPromises()
    expect(answerCalls()).toEqual(['applications/a1b2c3/attempts/42/answers'])
    expect(w.find('.attempt-item .wws-title').text()).toBe(label === 'See what was sent' ? 'What was sent' : 'What was filled')
    expect(w.find('.attempt-item .wws-label').text()).toBe('First name')
    expect(btn.text()).toBe('Hide')
  })

  it('every attempt in a list has its own button, and each opens its own ids', async () => {
    open({ a1b2c3: [attempt('sent', 9), attempt('stopped', 8), attempt('dry_run', 7)] })
    const w = await mountTab()
    await showDetails(w, 'a1b2c3')
    const btns = w.findAll('.attempt-item .attempt-filled')
    expect(btns.map(b => b.text())).toEqual(['See what was sent', 'See what was filled', 'See what was filled'])
    for (const b of btns) { await b.trigger('click'); await flushPromises() }
    // One panel at a time: the last click replaced the earlier ones; the three ids were each asked for.
    expect(answerCalls()).toEqual([
      'applications/a1b2c3/attempts/9/answers', 'applications/a1b2c3/attempts/8/answers', 'applications/a1b2c3/attempts/7/answers',
    ])
    expect(w.findAll('.attempt-item .wws-title')).toHaveLength(1)
  })

  it('an attempt with nothing recorded (running, cancelled) offers no button', async () => {
    open({ a1b2c3: [attempt('running', 3, { state: 'running' }), attempt('cancelled', 2)] })
    const w = await mountTab()
    await showDetails(w, 'a1b2c3')
    expect(w.findAll('.attempt-item')).toHaveLength(2)
    expect(w.find('.attempt-filled').exists()).toBe(false)
  })

  it('the row itself offers the same entry for its last attempt, with the same ids', async () => {
    open({ a1b2c3: [attempt('needs_input', 11, { reason_code: 'unanswerable_required', text: 'A required question had no answer.' })] })
    const w = await mountTab()
    const btn = row(w, 'a1b2c3').find('button.app-sent')
    expect(btn.text()).toBe('See what was filled')
    await btn.trigger('click')
    await flushPromises()
    expect(answerCalls()).toEqual(['applications/a1b2c3/attempts/11/answers'])
  })

  it('no control, menu item or text in the tab or the row says "Answer in Application details" / "Answer in Profile"', async () => {
    const all = [attempt('needs_input', 5, { reason_code: 'unanswerable_required', text: 'A required question had no answer.', hint: 'See what was filled.' })]
    open({ a1b2c3: all, d4e5f6: [attempt('stopped', 6, { text: 'The site asked for a CAPTCHA.' })] })
    const w = await mountTab()
    await row(w, 'a1b2c3').find('.app-more-trigger').trigger('click')
    await flushPromises()
    await row(w, 'a1b2c3').find('[role="menu"]').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    await showDetails(w, 'a1b2c3')
    expect(w.text()).not.toMatch(OLD_BUTTONS)
    expect(w.html()).not.toMatch(OLD_BUTTONS)
    expect(w.find('.attempt-answer').exists()).toBe(false)
    expect(w.find('.app-answer').exists()).toBe(false)
    for (const b of w.findAll('button, a, [role="menuitem"]')) {
      expect(`${b.text()} ${b.attributes('aria-label') ?? ''} ${b.attributes('title') ?? ''}`).not.toMatch(OLD_BUTTONS)
    }
    // The other row, opened too.
    await showDetails(w, 'd4e5f6')
    expect(w.text()).not.toMatch(OLD_BUTTONS)
  })
})

// ------------------------------------------------------------------ P4: the cover-letter sentence

describe('Q-127 polish P4: Settings -> Apply "Write cover letters"', () => {
  it('says what Off means under each fill policy, and no longer says you are asked instead', async () => {
    const base = fakeApi()
    routeFetch({
      'GET connections': cloneSample(sample), 'GET mail': mailView({ accounts: [] }),
      'GET apply/status': { mode: 'dry_run', missing: [], busy: false },
      'GET apply/settings': { mode: 'dry_run', writable: true, daily_cap: 0, per_employer_daily_cap: 10, headed: false, captcha_wait_s: 120, compose_enabled: false },
      'GET applicant': { missing: [], completeness: { filled: 1, needed: 1 }, form: null },
    }, { fallback: base.fetch })
    setHash('#/settings/apply')
    const w = mount(Settings, { props: { run: 'all', jobs: [] }, attachTo: document.body })
    await flushPromises()
    const text = w.find('#setting-cover-letters').text().replace(/\s+/g, ' ')
    expect(text).toContain('Write cover letters')
    // Half one: with Stop when unsure the application stops and its row says why.
    expect(text).toMatch(/Off: with Stop when unsure, an application whose form requires a cover letter stops and its row says why\./)
    // Half two: with Always answer a required one is still written.
    expect(text).toMatch(/With Always answer, a required one is still written\./)
    expect(text).not.toMatch(/you['’]re asked/i)
    expect(text).not.toMatch(/asked instead/i)
  })
})
