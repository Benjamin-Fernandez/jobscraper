// Q-127 pins 1-UI and 13-UI (design B.2b, B.4 copy table, B.8): `WhatWasSent.vue`, the owner's view of one
// attempt's answers and the only place to "Use a different answer next time". Fake fetch only; no
// `POST api/apply` can ever be sent from here. Also the PARITY pin: the refusal sentences held in
// `web/src/attempts.js` equal the contract's own texts (`src/jobscraper/apply/contracts.py`).
// Made-up names only. No network.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import WhatWasSent from '../src/components/WhatWasSent.vue'
import { refusalCopy } from '../src/attempts.js'
import { routeFetch } from './q100Fake.js'

const ANSWERS = 'applications/job1/attempts/5/answers'
const field = (id, label, over = {}) => ({
  id, step: 's1', label, type: 'text', required: true, value_text: 'Python', basis_text: 'From your resume',
  assumed: false, reason_text: '', status: 'not_sent', remembered_text: '', can_remember: true, refusal: '', options: [], ...over,
})
const BASES = [
  ['From your details: First name', {}], ['Your saved answer', {}], ['Worked out from your details', {}],
  ['Your standing answer', {}], ['From your resume', {}], ['From the job posting', {}],
  ['Written for this application', {}], ['Your resume file', {}], ['Your application email', {}],
  ['Written by the local AI from your details', {}], ['Kept from the site', {}],
]
const body = (fields, over = {}) => ({
  attempt: { id: 5, kind: 'sent', state: 'submitted', finished_at: '2026-11-15T10:00:00', trial: false, entries_note: '', ...over },
  employer: 'Example Co', fields,
})

let api
async function panel(fields, { attempt = {}, routes = {}, sent = true } = {}) {
  api = routeFetch({
    [`GET ${ANSWERS}`]: body(fields, attempt),
    'GET applicant': { etag: 'etag-1', profile: {} },
    ...routes,
  })
  const w = mount(WhatWasSent, { props: { jobId: 'job1', attemptId: 5, sent, employerName: 'Example Co' }, attachTo: document.body })
  await flushPromises()
  return w
}
const rows = w => w.findAll('li.wws-row')
const rowOf = (w, id) => w.find(`li.wws-row[data-field="${id}"]`)
const noApply = () => expect(api.calls.filter(c => c.path === 'apply'), 'POST api/apply').toHaveLength(0)

beforeEach(() => { window.localStorage.clear(); window.sessionStorage.clear() })
afterEach(() => { vi.unstubAllGlobals() })
enableAutoUnmount(afterEach)

describe('Q-127 pin 1-UI: what each row shows', () => {
  it('every basis in plain words, the value, the label', async () => {
    const w = await panel(BASES.map(([basis], i) => field(i + 1, `Question ${i + 1}`, { basis_text: basis, value_text: `v${i + 1}` })))
    expect(rows(w)).toHaveLength(BASES.length)
    BASES.forEach(([basis], i) => {
      const r = rowOf(w, i + 1)
      expect(r.find('.wws-label').text()).toBe(`Question ${i + 1}`)
      expect(r.find('.wws-value').text()).toContain(`v${i + 1}`)
      expect(r.find('.wws-basis').text()).toContain(basis)
    })
  })

  it('an assumed row shows its badge and reason; a not-answered row shows its badge; nothing is invented', async () => {
    const w = await panel([
      field(1, 'Preferred work arrangement', { assumed: true, basis_text: 'Assumed: no preference stated', reason_text: 'no preference stated' }),
      field(2, 'Visa status', { status: 'not_answered', value_text: '', basis_text: 'Not answered' }),
      field(3, 'First name', { basis_text: 'From your details: First name' }),
    ])
    expect(rowOf(w, 1).attributes('data-assumed')).toBe('true')
    expect(rowOf(w, 1).find('.wws-badge-assumed').exists()).toBe(true)
    expect(rowOf(w, 1).find('.wws-basis').text()).toContain('Assumed: no preference stated')
    expect(rowOf(w, 2).attributes('data-status')).toBe('not_answered')
    expect(rowOf(w, 2).find('.wws-badge-empty').exists()).toBe(true)
    expect(rowOf(w, 3).find('.wws-badge-assumed').exists()).toBe(false)
    expect(rowOf(w, 3).find('.wws-badge-empty').exists()).toBe(false)
  })

  it('the filter counts All / Assumed / Not answered and the filter narrows the list', async () => {
    const w = await panel([
      field(1, 'A one', { assumed: true }), field(2, 'A two', { assumed: true }),
      field(3, 'B three', { status: 'not_answered', value_text: '' }), field(4, 'C four'),
    ])
    const options = w.findAll('.ui-segmented [role="radio"]')
    const labels = options.map(x => x.text().replace(/\s+/g, ' ').trim())
    expect(labels).toEqual(expect.arrayContaining(['All 4', 'Assumed 2', 'Not answered 1']))
    await options.find(o => /^Assumed/.test(o.text().trim())).trigger('click')
    await flushPromises()
    expect(rows(w).map(r => r.attributes('data-field'))).toEqual(['1', '2'])
  })

  it('the entries note, the trial badge and the title say where the application stands', async () => {
    const w = await panel([field(1, 'City')], { attempt: { entries_note: '1 of 2 education entries added', trial: true, kind: 'dry_run' }, sent: false })
    expect(w.find('.wws-entries').text()).toContain('1 of 2 education entries added')
    expect(w.find('.wws-trial').exists()).toBe(true)
    expect(w.find('h4.wws-title').text()).toMatch(/filled/i)
    const sentPanel = await panel([field(1, 'City')])
    expect(sentPanel.find('h4.wws-title').text()).toMatch(/sent/i)
  })

  it('loading, empty and error states', async () => {
    api = routeFetch({ [`GET ${ANSWERS}`]: body([]), 'GET applicant': { etag: 'e', profile: {} } })
    const loading = mount(WhatWasSent, { props: { jobId: 'job1', attemptId: 5, sent: true }, attachTo: document.body })
    expect(loading.find('.wws-loading').exists()).toBe(true)          // before the answers arrive
    await flushPromises()
    expect(loading.find('.wws-loading').exists()).toBe(false)
    expect(loading.find('.wws-empty').exists()).toBe(true)

    api = routeFetch({ [`GET ${ANSWERS}`]: [500, { detail: 'boom' }] })
    const failed = mount(WhatWasSent, { props: { jobId: 'job1', attemptId: 5, sent: true }, attachTo: document.body })
    await flushPromises()
    expect(failed.find('.wws-error').exists()).toBe(true)
    expect(failed.find('button.wws-retry').exists()).toBe(true)
    noApply()
  })

  it('shows what was already saved for next time', async () => {
    const w = await panel([field(1, 'Preferred work arrangement', { remembered_text: 'Remote' })])
    expect(rowOf(w, 1).find('.wws-next').text()).toContain('Remote')
  })
})

describe('Q-127 pin 13-UI: the correction, its refusals and the save paths', () => {
  const REFUSED = [
    ['follows_your_details', 'This answer follows your details.', 'Change it in Your details.'],
    ['shared_answer', 'This question shares a saved answer with other questions.', 'Change it in Settings → Apply → Answers you corrected.'],
    ['too_general', 'This question is too general to save on its own', 'Change it in your details instead.'],
  ]

  it.each(REFUSED)('a %s row has no correction button and shows the refusal sentence and its link', async (code, lead, link) => {
    const w = await panel([field(1, 'Have you been convicted of an offence', { can_remember: false, refusal: code, basis_text: 'Your standing answer' })])
    const r = rowOf(w, 1)
    expect(r.find('button.wws-correct').exists()).toBe(false)
    expect(r.find('.wws-refusal').text()).toContain(lead)
    expect(r.find('.wws-refusal').text()).toContain(link)
    expect(r.find('.wws-refusal-link').exists()).toBe(true)
  })

  it('an allowed row offers the correction, with the scope checked by default; opening it sends nothing', async () => {
    const w = await panel([field(1, 'Preferred work arrangement', { assumed: true })])
    const before = api.calls.length
    await rowOf(w, 1).find('button.wws-correct').trigger('click')
    await flushPromises()
    expect(rowOf(w, 1).find('form.wws-editor').exists()).toBe(true)
    expect(rowOf(w, 1).find('.wws-scope input').element.checked).toBe(true)
    expect(api.calls.filter(c => c.method !== 'GET')).toHaveLength(0)
    expect(api.calls.length).toBeGreaterThanOrEqual(before)
  })

  async function correct(w, id, text) {
    await rowOf(w, id).find('button.wws-correct').trigger('click')
    await flushPromises()
    await rowOf(w, id).find('form.wws-editor input[type="text"], form.wws-editor textarea').setValue(text)
    await rowOf(w, id).find('button.wws-save').trigger('click')
    await flushPromises()
  }

  it('a successful remember posts the answer with the etag and the scope, marks the row and never calls apply', async () => {
    const route = `POST ${ANSWERS}/1/remember`
    const w = await panel([field(1, 'Describe your ideal weekend routine', { status: 'not_answered', value_text: '' })], {
      routes: { [route]: { key: 'describe_ideal_weekend', remembered_text: 'Hiking', ready_to_retry: true, etag: 'etag-2' } },
    })
    await correct(w, 1, 'Hiking')
    const posts = api.calls.filter(c => c.method === 'POST')
    expect(posts.map(c => c.path)).toEqual([`${ANSWERS}/1/remember`])
    expect(posts[0].body).toMatchObject({ value: 'Hiking', only_employer: true, etag: 'etag-1' })
    expect(rowOf(w, 1).find('.wws-badge-saved').exists()).toBe(true)
    expect(w.emitted('saved')).toBeTruthy()
    expect(w.emitted('saved')[0][0]).toMatchObject({ ready: true })
    noApply()
  })

  it('unchecking "Only for applications to {employer}" sends only_employer false', async () => {
    const route = `POST ${ANSWERS}/1/remember`
    const w = await panel([field(1, 'Describe your ideal weekend routine')], {
      routes: { [route]: { key: 'k', remembered_text: 'Hiking', ready_to_retry: false, etag: 'etag-2' } },
    })
    await rowOf(w, 1).find('button.wws-correct').trigger('click')
    await flushPromises()
    await rowOf(w, 1).find('.wws-scope input').setValue(false)
    await rowOf(w, 1).find('form.wws-editor input[type="text"], form.wws-editor textarea').setValue('Hiking')
    await rowOf(w, 1).find('button.wws-save').trigger('click')
    await flushPromises()
    expect(api.calls.filter(c => c.method === 'POST')[0].body.only_employer).toBe(false)
  })

  it('a 409 changed reloads the answers and says the saved answers changed', async () => {
    const route = `POST ${ANSWERS}/1/remember`
    const w = await panel([field(1, 'Describe your ideal weekend routine')], { routes: { [route]: [409, { detail: 'changed' }] } })
    const reads = () => api.calls.filter(c => c.method === 'GET' && c.path === ANSWERS).length
    const before = reads()
    await correct(w, 1, 'Hiking')
    expect(reads()).toBe(before + 1)
    expect(w.find('.wws-note').exists()).toBe(true)
    noApply()
  })

  it('a 422 follows_your_details switches the row to its refusal; a 422 invalid shows under the field', async () => {
    const refused = `POST ${ANSWERS}/1/remember`
    const w = await panel([field(1, 'Describe your ideal weekend routine')], {
      routes: { [refused]: [422, { detail: 'follows_your_details', text: 'This answer follows your details. Change it in Your details.' }] },
    })
    await correct(w, 1, 'Hiking')
    expect(rowOf(w, 1).find('.wws-refusal').exists()).toBe(true)
    expect(rowOf(w, 1).find('button.wws-correct').exists()).toBe(false)

    const w2 = await panel([field(1, 'How many projects did you lead', { type: 'number' })], {
      routes: { [`POST ${ANSWERS}/1/remember`]: [422, { detail: 'invalid', errors: [{ path: 'value', message: 'give a number' }] }] },
    })
    await rowOf(w2, 1).find('button.wws-correct').trigger('click')
    await flushPromises()
    await rowOf(w2, 1).find('form.wws-editor input').setValue('3')
    await rowOf(w2, 1).find('button.wws-save').trigger('click')
    await flushPromises()
    expect(rowOf(w2, 1).find('.wws-field-error').text().toLowerCase()).toContain('give a number')
    expect(rowOf(w2, 1).find('form.wws-editor').exists()).toBe(true)
    noApply()
  })
})

describe('Q-127 PARITY: the refusal sentences in attempts.js equal the contract', () => {
  const contracts = readFileSync(resolve(process.cwd(), '../src/jobscraper/apply/contracts.py'), 'utf8')
  // The contract's adjacent string literals for one RememberRefusal text, joined.
  function contractText(member) {
    const at = contracts.indexOf(`RememberRefusal.${member}:`, contracts.indexOf('REMEMBER_REFUSAL_TEXTS'))
    expect(at, member).toBeGreaterThan(0)
    const block = contracts.slice(at, contracts.indexOf('\n    RememberRefusal.', at + 10) > 0 && contracts.indexOf('\n    RememberRefusal.', at + 10) < contracts.indexOf('}', at)
      ? contracts.indexOf('\n    RememberRefusal.', at + 10) : contracts.indexOf('\n}', at))
    return [...block.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map(m => m[1].replace(/\\u201c/g, '“').replace(/\\u201d/g, '”')).join('')
  }
  const joined = c => `${c.lead} ${c.link}`

  it('follows_your_details and shared_answer are word for word the contract\'s', () => {
    expect(joined(refusalCopy('follows_your_details'))).toBe(contractText('FOLLOWS_YOUR_DETAILS'))
    expect(joined(refusalCopy('shared_answer'))).toBe(contractText('SHARED_ANSWER'))
  })

  it('too_general is the contract\'s with {label} filled in', () => {
    const want = contractText('TOO_GENERAL').replace('{label}', 'Please specify')
    expect(joined(refusalCopy('too_general', 'Please specify'))).toBe(want)
  })

  it('an unknown or empty code has no copy', () => {
    expect(refusalCopy('')).toBeNull()
    expect(refusalCopy('nonsense')).toBeNull()
  })
})
