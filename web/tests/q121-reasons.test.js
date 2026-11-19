// Q-121 lane W (D-229, contract v10): "What was filled" says why a field was left empty and what to do.
// The panel under test is WhatWasSent.vue (and the Applications row chip, attempts.js rowState). The rule
// that matters: the link is chosen from `reason_code` + `reason_key`, NEVER from the sentence. Fake fetch
// only; no `POST api/apply` can be sent from here. Made-up names only. No network.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import ApplicationRow from '../src/components/ApplicationRow.vue'
import WhatWasSent from '../src/components/WhatWasSent.vue'
import { FIELD_FOCUS_KEY, emptyAction, rowState } from '../src/attempts.js'
import { routeFetch } from './q100Fake.js'

const ANSWERS = 'applications/job1/attempts/5/answers'
const EMPTY = { reason: '', reason_hint: '', reason_code: '', reason_key: '' }
const field = (id, label, over = {}) => ({
  id, step: 's1', label, type: 'text', required: true, value_text: 'Python', basis_text: 'From your resume',
  assumed: false, reason_text: '', status: 'not_sent', remembered_text: '', can_remember: true, refusal: '', options: [],
  ...EMPTY, ...over,
})
const empty = (id, label, why, over = {}) => field(id, label, {
  status: 'not_answered', value_text: '', basis_text: 'Not answered', ...why, ...over,
})
const CONSENT = {
  reason: "You haven't agreed to sharing your details with the employer's group companies.",
  reason_hint: 'To agree, switch it on in Profile → Your details → Consents and declarations.',
  reason_code: 'consent_not_agreed', reason_key: 'consents.group_sharing',
}
const PLACE = {
  reason: "The form asks about working in a place your details don't cover.",
  reason_hint: 'Add that country under Work rights in Your details, or apply by hand.',
  reason_code: 'place_unknown', reason_key: 'singapore_status.authorised_to_work',
}
const DETAIL = {
  reason: "This asks for a detail that's missing from Your details.",
  reason_hint: 'Add it in Your details, then click Try again.',
  reason_code: 'detail_missing', reason_key: 'identity.date_of_birth',
}
const PLAIN = {
  reason: "Your details and resume don't answer this.", reason_hint: 'Answer it for next time, or apply by hand.',
  reason_code: 'not_in_details', reason_key: '',
}
const body = fields => ({
  attempt: { id: 5, kind: 'dry_run', state: 'ready_to_submit', finished_at: '2026-11-15T10:00:00', trial: false, entries_note: '' },
  employer: 'Example Co', fields,
})

let api
async function panel(fields) {
  api = routeFetch({ [`GET ${ANSWERS}`]: body(fields), 'GET applicant': { etag: 'etag-1', profile: {} } })
  const w = mount(WhatWasSent, { props: { jobId: 'job1', attemptId: 5, sent: false, employerName: 'Example Co' }, attachTo: document.body })
  await flushPromises()
  return w
}
const rowOf = (w, id) => w.find(`li.wws-row[data-field="${id}"]`)
const link = (w, id) => rowOf(w, id).find('a.wws-why-link')

beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  window.location.hash = ''
})
afterEach(() => { vi.unstubAllGlobals() })
enableAutoUnmount(afterEach)

describe('W3: the reason and the hint under "Not answered"', () => {
  it('both render as text under the row, and an answered row has neither', async () => {
    const w = await panel([empty(1, 'Share with group companies', CONSENT), empty(2, 'Describe your project', PLAIN), field(3, 'First name')])
    expect(rowOf(w, 1).find('.wws-reason').text()).toContain(CONSENT.reason)
    expect(rowOf(w, 1).find('.wws-hint').text()).toContain(CONSENT.reason_hint)
    expect(rowOf(w, 2).find('.wws-reason').text()).toContain(PLAIN.reason)
    expect(rowOf(w, 2).find('.wws-hint').text()).toContain(PLAIN.reason_hint)
    expect(rowOf(w, 3).find('[data-why]').exists()).toBe(false)
    expect(rowOf(w, 3).find('.wws-reason').exists()).toBe(false)
  })

  it('the owner never sees a code or a profile key as text', async () => {
    const w = await panel([empty(1, 'Share with group companies', CONSENT), empty(2, 'Authorised to work in Atlantis', PLACE), empty(3, 'Date of birth', DETAIL)])
    const text = w.text()
    for (const raw of ['consent_not_agreed', 'place_unknown', 'detail_missing', 'consents.group_sharing', 'singapore_status.authorised_to_work', 'identity.date_of_birth']) {
      expect(text, raw).not.toContain(raw)
    }
  })

  it('the link has the label of its code and only exists when there is a key', async () => {
    const w = await panel([
      empty(1, 'Share with group companies', CONSENT),
      empty(2, 'Authorised to work in Atlantis', PLACE),
      empty(3, 'Date of birth', DETAIL),
      empty(4, 'Describe your project', PLAIN),
      empty(5, 'Share with group again', { ...CONSENT, reason_key: '' }),
    ])
    expect(link(w, 1).text()).toBe('Open the switch')
    expect(link(w, 2).text()).toBe('Add it')
    expect(link(w, 3).text()).toBe('Add it')
    expect(link(w, 4).exists()).toBe(false)
    expect(link(w, 5).exists()).toBe(false)           // a consent code with no key: no link beats a wrong link
  })

  it('NO link comes from the sentence: a consent-looking or place-looking sentence with an empty key has none', async () => {
    const w = await panel([
      empty(1, 'Looks like a consent', { ...PLAIN, reason: CONSENT.reason, reason_hint: CONSENT.reason_hint, reason_code: 'not_in_details', reason_key: '' }),
      empty(2, 'Looks like a place', { ...PLAIN, reason: PLACE.reason, reason_hint: PLACE.reason_hint, reason_code: '', reason_key: '' }),
      empty(3, 'Looks like a missing detail', { ...PLAIN, reason: DETAIL.reason, reason_hint: DETAIL.reason_hint, reason_code: '', reason_key: '' }),
      empty(4, 'A key but the wrong code', { ...PLAIN, reason_key: 'consents.group_sharing' }),
      empty(5, 'A key that is not a path', { ...CONSENT, reason_key: 'https://northwind.example/x' }),
      empty(6, 'A key with a space', { ...DETAIL, reason_key: 'identity date of birth' }),
    ])
    for (let id = 1; id <= 6; id += 1) expect(link(w, id).exists(), `row ${id}`).toBe(false)
    // the sentences are still shown as text
    expect(rowOf(w, 1).find('.wws-reason').text()).toContain('agreed')
    expect(emptyAction(empty(9, 'x', { ...CONSENT, reason_key: '' }))).toBeNull()
    expect(emptyAction(field(9, 'x', { reason_key: 'consents.group_sharing', reason_code: 'consent_not_agreed' }))).toBeNull()
  })

  it('a key is a link on a not-answered row only', async () => {
    const w = await panel([field(1, 'Answered with a stray key', { ...CONSENT })])
    expect(link(w, 1).exists()).toBe(false)
    expect(rowOf(w, 1).find('[data-why]').exists()).toBe(false)
  })

  it('clicking leaves the focus target for Your details and goes there; it does not apply', async () => {
    const w = await panel([empty(1, 'Share with group companies', CONSENT), empty(2, 'Authorised to work in Atlantis', PLACE)])
    const seen = []
    const onShow = e => seen.push(e.detail.path)
    window.addEventListener('jobscraper:show-field', onShow)
    try {
      await link(w, 1).trigger('click')
      expect(window.sessionStorage.getItem(FIELD_FOCUS_KEY)).toBe('consents.group_sharing')
      expect(window.location.hash).toBe('#/profile')
      expect(window.localStorage.getItem('jobscraper.profile.view') ?? 'details').toBe('details')
      await link(w, 2).trigger('click')
      expect(window.sessionStorage.getItem(FIELD_FOCUS_KEY)).toBe('singapore_status.authorised_to_work')
      expect(seen).toEqual(['consents.group_sharing', 'singapore_status.authorised_to_work'])
    } finally {
      window.removeEventListener('jobscraper:show-field', onShow)
    }
    expect(api.calls.filter(c => c.path === 'apply')).toHaveLength(0)
    expect(api.calls.filter(c => c.method !== 'GET')).toHaveLength(0)
  })

  it('"This answer follows your details" is absent on a not-answered row and present on an answered protected one', async () => {
    const w = await panel([
      empty(1, 'Share with group companies', CONSENT, { can_remember: false, refusal: 'follows_your_details' }),
      field(2, 'Authorised to work in Singapore', { can_remember: false, refusal: 'follows_your_details', basis_text: 'From your details: Authorised to work' }),
      empty(3, 'Salary', PLAIN, { can_remember: false, refusal: 'too_general' }),
    ])
    expect(rowOf(w, 1).find('.wws-refusal').exists()).toBe(false)
    expect(rowOf(w, 1).text()).not.toMatch(/follows your details/i)
    expect(rowOf(w, 2).find('.wws-refusal').exists()).toBe(true)
    expect(rowOf(w, 2).find('.wws-refusal').text()).toMatch(/follows your details/i)
    expect(rowOf(w, 3).find('.wws-refusal').exists()).toBe(true)     // another refusal stays
  })

  it('a row the server sent without the v10 keys still renders (an older server)', async () => {
    const old = { id: 1, step: 's1', label: 'Old row', type: 'text', required: true, value_text: '', basis_text: 'Not answered', assumed: false, reason_text: '', status: 'not_answered', remembered_text: '', can_remember: true, refusal: '', options: [] }
    const w = await panel([old])
    expect(rowOf(w, 1).exists()).toBe(true)
    expect(rowOf(w, 1).find('[data-why]').exists()).toBe(false)
    expect(link(w, 1).exists()).toBe(false)
  })

  it('the filter chips still narrow the list with reasons on it', async () => {
    const w = await panel([empty(1, 'Share with group companies', CONSENT), empty(2, 'Describe your project', PLAIN), field(3, 'First name'), field(4, 'Why us', { assumed: true })])
    const options = w.findAll('.ui-segmented [role="radio"]')
    const labels = options.map(x => x.text().replace(/\s+/g, ' ').trim())
    expect(labels).toEqual(expect.arrayContaining(['All 4', 'Assumed 1', 'Not answered 2']))
    await options.find(o => /^Not answered/.test(o.text().trim())).trigger('click')
    await flushPromises()
    expect(w.findAll('li.wws-row').map(r => r.attributes('data-field'))).toEqual(['1', '2'])
    expect(link(w, 1).exists()).toBe(true)
  })

  it('layout at 390: the sentences wrap, the row can shrink and the link stays a touch target (source rules)', () => {
    const src = readFileSync(resolve(__dirname, '../src/components/WhatWasSent.vue'), 'utf8')
    const css = src.slice(src.indexOf('<style'))
    expect(css).toMatch(/\.wws-main\s*\{[^}]*min-width:\s*0/)
    expect(css).toMatch(/\.wws-main p\s*\{[^}]*overflow-wrap:\s*anywhere/)
    expect(css).toMatch(/\.wws-why\s*\{[^}]*min-width:\s*0/)
    expect(css).toMatch(/\.wws-hint\s*\{[^}]*flex-wrap:\s*wrap/)
    expect(css).toMatch(/\.wws-hint span\s*\{[^}]*overflow-wrap:\s*anywhere/)
    expect(css).not.toMatch(/\.wws-(why|reason|hint)[^{]*\{[^}]*white-space:\s*nowrap/)
  })
})

// ---- W4: the row chip ----------------------------------------------------------------------------------

const attempt = over => ({
  id: 7, mode: 'auto', state: 'failed', kind: 'needs_input', reason_code: 'consent_refused', text: '', hint: '',
  queued_at: '2026-11-12T10:00:00', finished_at: '2026-11-12T10:05:00', submit_clicked_at: null,
  resume_source: null, assumed: 0, assumed_text: '', owner_fact_path: null, ...over,
})
const REFUSED_TEXT = 'This form needs you to agree to sharing your details with the employer\'s group companies, and your profile says no. Nothing was sent.'
const rowFor = a => ({
  job_id: 'j1', company: 'Example Co', role: 'Software Engineer', url: 'https://jobs.example/1', status: 'to_apply',
  notes: null, events: [{ id: 1, from_status: null, to_status: 'to_apply', at: '2026-11-12T10:05:00', by: 'app' }],
  last_attempt: a, attempts: 1, queue: null, posting: null,
})
const mountRow = a => mount(ApplicationRow, { props: { row: rowFor(a) }, attachTo: document.body })

describe('W4: the Applications row chip', () => {
  it('a refused consent reads "Needs your agreement: ..." and "Open the switch" lands on the switch', async () => {
    const a = attempt({ text: REFUSED_TEXT, owner_fact_path: 'consents.group_sharing' })
    const s = rowState(rowFor(a))
    expect(s.label).toBe("Needs your agreement: sharing your details with the employer's group companies")
    expect(s.addText).toBe('Open the switch')
    expect(s.target).toBe('consents.group_sharing')
    const w = mountRow(a)
    expect(w.find('.app-chip').text()).toBe(s.label)
    const open = w.find('a.app-add')
    expect(open.text()).toBe('Open the switch')
    await open.trigger('click')
    expect(window.sessionStorage.getItem(FIELD_FOCUS_KEY)).toBe('consents.group_sharing')
    expect(window.location.hash).toBe('#/profile')
  })

  it('a refused consent with no path lands on the Consents group, never on nothing', () => {
    expect(rowState(rowFor(attempt({ text: REFUSED_TEXT }))).target).toBe('consents')
  })

  it('the other chips are unchanged', () => {
    const fact = rowState(rowFor(attempt({ reason_code: 'owner_fact_missing', text: "This form asks for your date of birth, which isn't in your profile or resume. Nothing was sent.", owner_fact_path: 'identity.date_of_birth' })))
    expect(fact.label).toBe('Needs one detail: date of birth')
    expect(fact.add).toBe(true)
    expect(fact.addText).toBeUndefined()                                  // the row falls back to "Add it"
    const w = mountRow(attempt({ reason_code: 'owner_fact_missing', text: "This form asks for your date of birth, which isn't in your profile or resume. Nothing was sent.", owner_fact_path: 'identity.date_of_birth' }))
    expect(w.find('a.app-add').text()).toBe('Add it')
    w.unmount()
    const stop = rowState(rowFor(attempt({ reason_code: 'unanswerable_required', not_answered: 2 })))
    expect(stop.label).toBe('Stopped: 2 questions had no answer')
    expect(stop.addText).toBeUndefined()
    const noField = rowState(rowFor(attempt({ state: 'failed', kind: 'stopped', reason_code: 'owner_fact_missing', no_field: true, text: "This form asks for your passport number, which Your details can't hold." })))
    expect(noField.noField).toBe(true)
    expect(noField.noRetry).toBe(true)
    expect(noField.add).toBeUndefined()
    const ready = rowState(rowFor(attempt({ text: REFUSED_TEXT, owner_fact_path: 'consents.group_sharing', ready_to_retry: true })))
    expect(ready.label).toBe('Ready to try again')
    expect(ready.ready).toBe(true)
    const dry = rowState(rowFor(attempt({ state: 'ready_to_submit', kind: 'dry_run', mode: 'dry_run', reason_code: null })))
    expect(dry.label).toBe('Dry run ready')
    expect(dry.add).toBeUndefined()
  })
})
