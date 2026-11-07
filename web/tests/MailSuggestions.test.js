// WP-T6 (Q-60): "From your email" suggestions and the History "From email" badge
// (mail_status_design.md 8, 11.1; F-50l, F-50m, F-50n; review F8).
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MailEvidence from '../src/components/MailEvidence.vue'
import MailSuggestions from '../src/components/MailSuggestions.vue'
import { dismissToast, toast } from '../src/toast.js'
import { fakeMail } from './mailFake.js'

const GMAIL = 'https://mail.google.com/mail/?authuser=alex@inbox.example#all/18f'
const ACCEPT_CONFLICT = 'This application changed after the email. Set the status by hand if you still want this.'
const UNDO_CONFLICT = "Can't undo: the status changed after this email. Set it by hand."

afterEach(() => {
  dismissToast()
  vi.unstubAllGlobals()
})

function suggestion(id, fields = {}) {
  return {
    id, job_id: 'nw-analyst', company: 'Northwind Traders', role: 'Graduate Analyst', status: 'applied',
    to_status: 'interviewing', category: 'interview', reason: 'suggest_only', reason_text: 'Check this one.',
    quote: 'We would like to invite you to an interview.', subject: 'Interview', sender_domain: 'greenhouse-mail.io',
    received_at: '2026-10-26T09:00:00', candidates: [], gmail_url: GMAIL, ...fields,
  }
}

const TWO = [{ job_id: 'nw-dataeng', company: 'Northwind Traders', role: 'Graduate Data Engineer', status: 'applied' },
  { job_id: 'nw-analyst', company: 'Northwind Traders', role: 'Graduate Analyst', status: 'applied' }]

async function list(routes) {
  const api = fakeMail(routes)
  const wrapper = mount(MailSuggestions)
  await flushPromises()
  return { api, wrapper }
}

describe('MailSuggestions', () => {
  it('is hidden with nothing to show and on a server without the route', async () => {
    expect((await list({ 'GET mail/suggestions': { suggestions: [] } })).wrapper.find('.mail-suggestions').exists()).toBe(false)
    expect((await list({})).wrapper.find('.mail-suggestions').exists()).toBe(false)
  })

  it('shows what the email says and only a Gmail link it can trust', async () => {
    const { wrapper } = await list({
      'GET mail/suggestions': { suggestions: [suggestion(1), suggestion(2, { gmail_url: 'https://evil.example/x' })] },
    })
    expect(wrapper.find('.ms-count').text()).toBe('2')
    const [a, b] = wrapper.findAll('.ms-item')
    expect(a.attributes('data-reason')).toBe('suggest_only')
    expect(a.find('.ms-says .pill').attributes('data-status')).toBe('interviewing')
    expect(a.find('.ms-quote').text()).toContain('invite you to an interview')
    expect(a.find('.ms-gmail').attributes('href')).toBe(GMAIL)
    expect(b.find('.ms-gmail').exists()).toBe(false)
  })

  it('an ambiguous one needs a pick first; nothing is preselected', async () => {
    let open = [suggestion(5, { job_id: null, candidates: TWO })]
    const { api, wrapper } = await list({
      'GET mail/suggestions': () => ({ suggestions: open }),
      'POST mail/suggestions/5/accept': () => { open = []; return { ok: true, status: 'interviewing' } },
    })
    const sel = wrapper.find('select.ms-pick')
    expect(sel.findAll('option').map(o => o.attributes('value'))).toEqual(['', 'nw-dataeng', 'nw-analyst'])
    expect(sel.element.value).toBe('')
    expect(wrapper.find('.ms-accept').element.disabled).toBe(true)
    await wrapper.find('.ms-accept').trigger('click')
    expect(api.of('POST', 'mail/suggestions/5/accept')).toHaveLength(0)
    await sel.setValue('nw-dataeng')
    expect(wrapper.find('.ms-accept').element.disabled).toBe(false)
    await wrapper.find('.ms-accept').trigger('click')
    await flushPromises()
    expect(api.of('POST', 'mail/suggestions/5/accept')[0].body).toEqual({ job_id: 'nw-dataeng' })
    expect(wrapper.emitted('changed')[0][0]).toEqual({ jobId: 'nw-dataeng', status: 'interviewing' })
    expect(wrapper.find('.mail-suggestions').exists()).toBe(false)
  })

  it('a 409 on Accept reloads the list and tells the tab to reload (status null)', async () => {
    let open = [suggestion(3), suggestion(4)]
    const { api, wrapper } = await list({
      'GET mail/suggestions': () => ({ suggestions: open }),
      'POST mail/suggestions/3/accept': () => { open = [suggestion(4)]; return [409, { code: 'changed', detail: 'x' }] },
    })
    const gets = api.of('GET', 'mail/suggestions').length
    await wrapper.find('.ms-item[data-suggestion="3"] .ms-accept').trigger('click')
    await flushPromises()
    expect(api.of('GET', 'mail/suggestions').length).toBe(gets + 1)
    expect(wrapper.find('.ms-item[data-suggestion="3"]').exists()).toBe(false)
    expect(toast.current.message).toBe(ACCEPT_CONFLICT)
    expect(wrapper.emitted('changed')[0][0]).toEqual({ jobId: 'nw-analyst', status: null })
  })

  it('a 409 on a suggestion still listed keeps its message on it', async () => {
    const { wrapper } = await list({
      'GET mail/suggestions': { suggestions: [suggestion(3)] },
      'POST mail/suggestions/3/accept': [409, { code: 'changed', detail: 'x' }],
    })
    await wrapper.find('.ms-accept').trigger('click')
    await flushPromises()
    expect(wrapper.find('.ms-error[role=alert]').text()).toBe(ACCEPT_CONFLICT)
  })

  it('"Check the email" offers Got it, which dismisses', async () => {
    let open = [suggestion(9, { to_status: null, reason: 'unclear', candidates: TWO })]
    const { api, wrapper } = await list({
      'GET mail/suggestions': () => ({ suggestions: open }),
      'POST mail/suggestions/9/dismiss': () => { open = []; return { ok: true } },
    })
    expect(wrapper.find('.ms-says').text()).toBe('Check the email')
    expect(wrapper.find('.ms-accept').exists()).toBe(false)
    await wrapper.find('.ms-got-it').trigger('click')
    await flushPromises()
    expect(api.of('POST', 'mail/suggestions/9/dismiss')).toHaveLength(1)
    expect(wrapper.find('.mail-suggestions').exists()).toBe(false)
  })

  // Q-72 a (D-161; MS 11.3 "Maybe untracked"): no application, so the company comes from candidates[0].
  it('"maybe untracked" shows the company alone, Check the email, Got it and Open in Gmail, no select', async () => {
    const REASON = "This email may be about an application you haven't added."
    const acme = { job_id: 'acme-1', company: 'Acme', role: 'Candidate Role Zed', status: 'rejected' }
    const s = suggestion(12, {
      job_id: null, company: null, role: null, status: null, to_status: null, category: 'acknowledged',
      reason: 'maybe_untracked', reason_text: REASON, candidates: [acme],
      quote: 'Thank you for applying for the DevOps Engineer role.',
    })
    const { api, wrapper } = await list({ 'GET mail/suggestions': { suggestions: [s] } })
    const item = wrapper.find('.ms-item')
    expect(item.attributes('data-reason')).toBe('maybe_untracked')
    expect(item.find('.ms-app').text()).toBe('Acme')
    expect(item.find('.ms-says').text()).toBe('Check the email')
    expect(item.find('.ms-reason').text()).toBe(REASON)
    expect(item.find('.ms-got-it').text()).toBe('Got it')
    expect(item.find('.ms-gmail').text()).toBe('Open in Gmail')
    expect(item.find('.ms-gmail').attributes('href')).toBe(GMAIL)
    expect(item.findAll('button').map(b => b.text())).toEqual(['Got it'])
    expect(item.find('select').exists()).toBe(false)
    expect(item.find('.ms-pick').exists()).toBe(false)
    expect(item.find('.ms-accept').exists()).toBe(false)
    expect(item.find('.ms-dismiss').exists()).toBe(false)
    expect(item.text()).not.toContain('Candidate Role Zed') // no candidate list
    expect(api.calls.filter(c => c.method === 'POST')).toHaveLength(0)
  })
})

function evidence(fields = {}) {
  return {
    id: 41, at: '2026-10-26T09:05:00', to_status: 'rejected', by: 'mail',
    mail: {
      evidence_id: 12, kind: 'auto', state: 'applied', quote: 'We will not be moving forward.', subject: 'Your application',
      sender_domain: 'greenhouse-mail.io', received_at: '2026-10-26T09:00:00', gmail_url: GMAIL, undoable: true, ...fields,
    },
  }
}

describe('MailEvidence', () => {
  it('expands to the quote, the sender and the Gmail link', async () => {
    fakeMail({})
    const wrapper = mount(MailEvidence, { props: { event: evidence() } })
    const badge = wrapper.find('button.mail-badge')
    expect(badge.attributes('aria-expanded')).toBe('false')
    await badge.trigger('click')
    expect(badge.attributes('aria-expanded')).toBe('true')
    expect(wrapper.find(`#${badge.attributes('aria-controls')}`).exists()).toBe(true)
    expect(wrapper.find('.evidence-quote').text()).toContain('not be moving forward')
    expect(wrapper.find('.evidence-from').text()).toContain('greenhouse-mail.io')
    expect(wrapper.find('.evidence-gmail').attributes('href')).toBe(GMAIL)
    const bad = mount(MailEvidence, { props: { event: evidence({ gmail_url: 'javascript:alert(1)', undoable: false }) } })
    await bad.find('button.mail-badge').trigger('click')
    expect(bad.find('.evidence-gmail').exists()).toBe(false)
    expect(bad.find('.evidence-undo').exists()).toBe(false)
  })

  it('Undo goes back and says so', async () => {
    const api = fakeMail({ 'POST mail/evidence/12/undo': { ok: true, status: 'interviewing' } })
    const wrapper = mount(MailEvidence, { props: { event: evidence() } })
    await wrapper.find('button.mail-badge').trigger('click')
    await wrapper.find('.evidence-undo').trigger('click')
    await flushPromises()
    expect(api.of('POST', 'mail/evidence/12/undo')).toHaveLength(1)
    expect(toast.current.message).toBe('Back to Interviewing.')
    expect(wrapper.emitted('undone')[0][0]).toEqual({ status: 'interviewing' })
    expect(wrapper.emitted('stale')).toBeUndefined()
  })

  it('a 409 on Undo shows why and emits stale (the tab reloads), not undone', async () => {
    fakeMail({ 'POST mail/evidence/12/undo': [409, { code: 'not_latest', detail: 'later change' }] })
    const wrapper = mount(MailEvidence, { props: { event: evidence() } })
    await wrapper.find('button.mail-badge').trigger('click')
    await wrapper.find('.evidence-undo').trigger('click')
    await flushPromises()
    expect(wrapper.find('.evidence-error[role=alert]').text()).toBe(UNDO_CONFLICT)
    expect(wrapper.emitted('stale')).toHaveLength(1)
    expect(wrapper.emitted('undone')).toBeUndefined()
  })

  it('another failure shows the detail and emits nothing', async () => {
    fakeMail({ 'POST mail/evidence/12/undo': [404, { code: 'not_found', detail: 'That email is gone.' }] })
    const wrapper = mount(MailEvidence, { props: { event: evidence() } })
    await wrapper.find('button.mail-badge').trigger('click')
    await wrapper.find('.evidence-undo').trigger('click')
    await flushPromises()
    expect(wrapper.find('.evidence-error').text()).toBe('Could not undo it: That email is gone.')
    expect(wrapper.emitted('stale')).toBeUndefined()
    expect(wrapper.emitted('undone')).toBeUndefined()
  })
})
