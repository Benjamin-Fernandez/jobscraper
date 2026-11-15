// Q-127 pin 5-UI (design B.2b, B.4, B.8): "Answers you corrected" (RememberedAnswers.vue) and its Settings
// row, and the Overview's three stopped-application counts as pure functions. The shell badge
// (`details_needed`) is pinned in q75-shell.test.js. Fake fetch only; nothing here can start an
// application. Made-up names only. No network.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import RememberedAnswers from '../src/components/RememberedAnswers.vue'
import ApplySettings from '../src/components/ApplySettings.vue'
import { nextUp, stoppedCounts } from '../src/overview.js'
import sample from './fixtures/connections.sample.json'
import { cloneSample, routeFetch } from './q100Fake.js'

const entry = (n, over = {}) => ({
  key: `answer_${n}`, title: `Question ${n}`, value_text: `Value ${n}`, scope_text: n % 2 ? 'Every application' : 'Only Example Co',
  employer: n % 2 ? '' : 'Example Co', kind: 'text', sensitive: false, needs_attention: false, ...over,
})
const list = (n, over = {}) => ({ items: Array.from({ length: n }, (_, i) => entry(i + 1)), count: n, etag: 'etag-1', unreadable: false, ...over })

let api
async function page(remembered, routes = {}) {
  api = routeFetch({ 'GET apply/remembered': remembered, ...routes })
  const w = mount(RememberedAnswers, { attachTo: document.body })
  await flushPromises()
  return w
}
const items = w => w.findAll('li.rem-item')
const forget = (w, key) => w.find(`button.rem-forget[data-key="${key}"]`)
const writes = () => api.calls.filter(c => c.method !== 'GET')

beforeEach(() => { window.localStorage.clear(); window.sessionStorage.clear() })
afterEach(() => { vi.unstubAllGlobals() })
enableAutoUnmount(afterEach)

describe('Q-127 pin 5-UI: Answers you corrected', () => {
  it('lists title, answer and scope, and reports the count', async () => {
    const w = await page(list(3))
    expect(items(w)).toHaveLength(3)
    expect(items(w)[0].find('.rem-title').text()).toBe('Question 1')
    expect(items(w)[0].find('.rem-detail').text()).toContain('Value 1')
    expect(items(w)[0].find('.rem-detail').text()).toContain('Every application')
    expect(items(w)[1].find('.rem-detail').text()).toContain('Only Example Co')
    expect(w.emitted('count').at(-1)).toEqual([3])
    expect(writes()).toHaveLength(0)
  })

  it('shows the first 20 and "Show all {n}" for the rest', async () => {
    const w = await page(list(25))
    expect(items(w)).toHaveLength(20)
    const more = w.find('.rem-more')
    expect(more.text()).toBe('Show all 25')
    await more.trigger('click')
    expect(items(w)).toHaveLength(25)
  })

  it('an entry that needs attention says so', async () => {
    const w = await page(list(2, { items: [entry(1, { needs_attention: true }), entry(2)] }))
    expect(items(w)[0].find('.rem-attention').text()).toBe('Needs attention')
    expect(items(w)[1].find('.rem-attention').exists()).toBe(false)
  })

  it('empty, unreadable and load-error states', async () => {
    const empty = await page(list(0))
    expect(empty.find('.rem-empty').text()).toBe('None yet. To save one, open an application and choose What was sent.')
    const unreadable = await page({ items: [], count: 0, etag: 'e', unreadable: true })
    expect(unreadable.find('.rem-unreadable').exists()).toBe(true)
    const failed = await page([500, { detail: 'boom' }])
    expect(failed.find('.rem-retry').exists()).toBe(true)
  })

  it('Forget asks first (Keep leaves everything), then DELETEs with the etag and the entry leaves the list', async () => {
    const w = await page(list(3), { 'DELETE apply/remembered/answer_2?etag=etag-1': { key: 'answer_2', forgotten: true, etag: 'etag-2' } })
    await forget(w, 'answer_2').trigger('click')
    expect(w.find('.rem-confirm').text()).toContain('Forget this answer? JobScraper will answer this question from your details again.')
    expect(writes()).toHaveLength(0)
    await w.find('button.rem-keep').trigger('click')
    expect(w.find('.rem-confirm').exists()).toBe(false)
    expect(writes()).toHaveLength(0)
    expect(items(w)).toHaveLength(3)

    await forget(w, 'answer_2').trigger('click')
    await w.find('button.rem-confirm-yes').trigger('click')
    await flushPromises()
    expect(writes()).toHaveLength(1)
    expect(writes()[0]).toMatchObject({ method: 'DELETE', path: 'apply/remembered/answer_2?etag=etag-1' })
    expect(items(w).map(i => i.attributes('data-key'))).toEqual(['answer_1', 'answer_3'])
    expect(w.emitted('count').at(-1)).toEqual([2])
  })

  it('a 409 reloads the list and says it changed; a 404 says it was already gone', async () => {
    let state = 'changed'
    const w = await page(list(2), {
      'DELETE apply/remembered/answer_1?etag=etag-1': () => (state === 'changed' ? [409, { detail: 'changed' }] : [404, { detail: 'not_found' }]),
    })
    const reads = () => api.calls.filter(c => c.method === 'GET' && c.path === 'apply/remembered').length
    const before = reads()
    await forget(w, 'answer_1').trigger('click')
    await w.find('button.rem-confirm-yes').trigger('click')
    await flushPromises()
    expect(reads()).toBe(before + 1)
    expect(w.find('.rem-note').text()).toContain('changed since this list was loaded')

    state = 'gone'
    await forget(w, 'answer_1').trigger('click')
    await w.find('button.rem-confirm-yes').trigger('click')
    await flushPromises()
    expect(w.find('.rem-note').text()).toContain('already gone')
  })

  it('the list never carries a Private tag, a promoted entry, or a path', async () => {
    const w = await page(list(2))
    expect(w.find('.tag.private').exists()).toBe(false)
    expect(w.text()).not.toMatch(/applicant\.yaml|data\//)
  })
})

describe('Q-127 pin 5-UI: the Settings row and its anchor', () => {
  const GOOD = { writable: true, mode: 'dry_run', daily_cap: 5, per_employer_daily_cap: 2, headed: false, captcha_wait_s: 120, compose_enabled: false }
  async function settings(item, remembered = list(2)) {
    api = routeFetch({ 'GET apply/remembered': remembered })
    const w = mount(ApplySettings, {
      props: { connections: cloneSample(sample), apply: { status: null, settings: GOOD, summary: null }, item },
      attachTo: document.body,
    })
    await flushPromises()
    return w
  }

  it('has one read-only GET on mount, shows "{n} saved", and writes nothing', async () => {
    const w = await settings(null)
    expect(api.calls.filter(c => c.method === 'GET' && c.path === 'apply/remembered')).toHaveLength(1)
    expect(writes()).toHaveLength(0)
    expect(w.find('#setting-answers-corrected .setting-value').text()).toBe('2 saved')
  })

  it('says "None yet" for an empty list and is hidden on a server without the route', async () => {
    const none = await settings(null, list(0))
    expect(none.find('#setting-answers-corrected .setting-value').text()).toBe('None yet')
    api = routeFetch({})                                            // 404 on apply/remembered
    const old = mount(ApplySettings, {
      props: { connections: cloneSample(sample), apply: { status: null, settings: GOOD, summary: null }, item: null }, attachTo: document.body,
    })
    await flushPromises()
    expect(old.find('#setting-answers-corrected').exists()).toBe(false)
  })

  it('#/settings/apply/answers-corrected opens the row and focuses it', async () => {
    const w = await settings('answers-corrected')
    expect(w.find('#setting-answers-corrected .setting-main').attributes('aria-expanded')).toBe('true')
    expect(w.find('#setting-answers-corrected-editor').exists()).toBe(true)
    expect(document.activeElement?.closest('#setting-answers-corrected')).not.toBeNull()
  })
})

describe('Q-127 pin 5-UI: the Overview\'s three stopped-application counts (pure)', () => {
  const stopped = (id, attempt, status = 'to_apply') => ({
    job_id: id, status, queue: null,
    last_attempt: { id: 1, state: 'failed', mode: 'dry_run', kind: 'needs_input', reason_code: 'owner_fact_missing',
      text: "This form asks for your date of birth, which isn't in your profile or resume. Nothing was sent.",
      owner_fact_path: 'identity.date_of_birth', ready_to_retry: false, no_field: false, ...attempt },
  })
  const noField = (id, fact) => stopped(id, {
    kind: 'stopped', no_field: true, reason_code: 'owner_fact_missing', owner_fact_path: null,
    text: `This form asks for your ${fact}, which your details can't hold. Nothing was sent.`,
  })

  it('waiting, no-field (one entry per fixed fact) and stuck are counted from the rows', () => {
    const rows = [
      stopped('a', {}), stopped('b', { reason_code: 'consent_refused', text: 'This form needs you to agree to keeping your details on file for future roles, and your profile says no. Nothing was sent.', owner_fact_path: 'consents.data_retention_consent' }),
      noField('c', 'passport number'), noField('d', 'passport number'), noField('e', 'bank account details'),
      stopped('f', { reason_code: 'unanswerable_required', text: 'A required question had no answer JobScraper could back up: “Why us?”.', owner_fact_path: null }),
    ]
    expect(stoppedCounts(rows)).toEqual({
      waiting: 2, noField: [{ fact: 'passport number', n: 2 }, { fact: 'bank account details', n: 1 }], stuck: 1,
    })
  })

  it('a ready-to-retry row, an applied row and a queued row count for nothing; an unknown fact is "stuck", never named', () => {
    const rows = [
      stopped('a', { ready_to_retry: true }), stopped('b', {}, 'applied'),
      { ...stopped('c', {}), queue: { position: 1 } },
      noField('d', 'secret handshake'),
    ]
    const out = stoppedCounts(rows)
    expect(out.waiting).toBe(0)
    expect(out.noField).toEqual([])
    expect(out.stuck).toBe(1)
    expect(JSON.stringify(out)).not.toContain('secret handshake')
  })

  it('nextUp lists them in order and a row with no work is absent', () => {
    expect(nextUp({ waiting: 2, noField: [{ fact: 'passport number', n: 1 }], stuck: 1 }).map(c => c.id)).toEqual(['details', 'no-field', 'stuck'])
    expect(stoppedCounts([])).toEqual({ waiting: 0, noField: [], stuck: 0 })
    expect(nextUp(stoppedCounts([]))).toEqual([])
  })
})
