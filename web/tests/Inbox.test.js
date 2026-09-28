import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import Inbox from '../src/tabs/Inbox.vue'
import { resetDismissed } from '../src/dismissed.js'
import { dismissToast, toast } from '../src/toast.js'
import { FIXTURE, fakeApi } from './helpers.js'

let api

function jobsFor(run, statuses = {}) {
  return FIXTURE.jobs
    .filter(j => j.run_no === run)
    .map(j => ({ ...j, closed: false, status: statuses[j.id] ?? null, notes: null }))
}

function mountInbox(jobs = jobsFor(12)) {
  return mount(Inbox, { props: { run: 12, jobs } })
}

// Run 12, newest first: Shopee (14:29:58), GovTech (14:29:50), OKX (14:29:41).
const companies = w => w.findAll('.card .company').map(c => c.text())
const card = (w, company) => w.findAll('.card').find(c => c.find('.company').text() === company)
const detail = w => w.find('.detail')

beforeEach(() => {
  resetDismissed()
  dismissToast()
  api = fakeApi()
  vi.stubGlobal('fetch', api.fetch)
})
afterEach(() => vi.unstubAllGlobals())

describe('Inbox list', () => {
  it('lists the run\'s untouched roles, newest first, with a count', () => {
    const wrapper = mountInbox()
    expect(companies(wrapper)).toEqual(['Shopee', 'GovTech', 'OKX'])
    expect(wrapper.find('.count').text()).toContain('3 new roles at 3 companies')
    const okx = card(wrapper, 'OKX')
    expect(okx.find('.title').text()).toBe('DevOps / Site Reliability Engineer')
    expect(okx.find('.meta').text()).toBe('Singapore · Entry level')
    expect(card(wrapper, 'GovTech').find('.meta').text()).toBe('Singapore · 1+ yrs')
    expect(okx.find('.seen').text()).toBe('23 Sep')
  })

  it('every card carries the company\'s monogram', () => {
    const marks = mountInbox().findAll('.card .mark').map(m => m.text())
    expect(marks).toEqual(['S', 'GT', 'OK'])
  })

  it('a role you have saved or applied to is not in the Inbox: it is in Applications', () => {
    const wrapper = mountInbox(jobsFor(12, { a1b2c3: 'applied', g7h8i9: 'to_apply' }))
    expect(companies(wrapper)).toEqual(['GovTech'])
    const link = wrapper.find('.count a.tracked')
    expect(link.text()).toBe('2 in Applications')
    expect(link.attributes('href')).toBe('#/applications')
  })

  it('says you are caught up when every role in the run is tracked', () => {
    const wrapper = mountInbox(jobsFor(12, { a1b2c3: 'applied', d4e5f6: 'applied', g7h8i9: 'offer' }))
    expect(wrapper.find('.caught-up').text()).toContain('all caught up')
    expect(wrapper.find('.card').exists()).toBe(false)
  })

  it('search narrows by title, company or location, and says so when nothing matches', async () => {
    const wrapper = mountInbox()
    await wrapper.find('input[type="search"]').setValue('backend')
    expect(companies(wrapper)).toEqual(['Shopee'])
    await wrapper.find('input[type="search"]').setValue('govtech')
    expect(companies(wrapper)).toEqual(['GovTech'])
    await wrapper.find('input[type="search"]').setValue('nothing like this')
    expect(wrapper.text()).toContain('No roles match')
    await wrapper.find('.empty button.link').trigger('click')
    expect(companies(wrapper)).toHaveLength(3)
  })

  it('sorts by company A-Z on request', async () => {
    const wrapper = mountInbox()
    await wrapper.find('.sort select').setValue('company')
    expect(companies(wrapper)).toEqual(['GovTech', 'OKX', 'Shopee'])
  })

  it('marks a closed posting as stale rather than hiding it', () => {
    const jobs = jobsFor(12)
    jobs[0] = { ...jobs[0], closed: true }                  // OKX
    const wrapper = mountInbox(jobs)
    expect(card(wrapper, 'OKX').classes()).toContain('closed')
    expect(card(wrapper, 'OKX').find('.stale').text()).toBe('closed')
  })
})

describe('Inbox detail', () => {
  it('shows the newest role by default: title, company, facts and why it matches', () => {
    const d = detail(mountInbox())
    expect(d.find('.detail-title').text()).toBe('Software Engineer, Backend (New Grad)')
    expect(d.find('.detail-company').text()).toBe('Shopee')
    const facts = d.findAll('.facts li').map(f => f.text())
    expect(facts).toEqual(['Singapore', 'No experience required', 'Found 23 Sep'])
    expect(d.find('.reason').text()).toContain('Go and Kafka')
  })

  it('clicking a card shows that role, and marks it current', async () => {
    const wrapper = mountInbox()
    await card(wrapper, 'GovTech').find('.card-hit').trigger('click')
    expect(detail(wrapper).find('.detail-title').text()).toBe('Platform Infrastructure Engineer, AISO')
    expect(detail(wrapper).find('.facts').text()).toContain('1 year experience')
    expect(card(wrapper, 'GovTech').find('.card-hit').attributes('aria-current')).toBe('true')
    expect(card(wrapper, 'OKX').find('.card-hit').attributes('aria-current')).toBeUndefined()
  })

  it('arrow keys move through the list', async () => {
    const wrapper = mountInbox()
    await wrapper.find('.job-list').trigger('keydown', { key: 'ArrowDown' })
    expect(detail(wrapper).find('.detail-company').text()).toBe('GovTech')
    await wrapper.find('.job-list').trigger('keydown', { key: 'ArrowDown' })
    await wrapper.find('.job-list').trigger('keydown', { key: 'ArrowDown' })  // stops at the end
    expect(detail(wrapper).find('.detail-company').text()).toBe('OKX')
    await wrapper.find('.job-list').trigger('keydown', { key: 'ArrowUp' })
    expect(detail(wrapper).find('.detail-company').text()).toBe('GovTech')
  })

  it('opens the posting in a new tab without handing it this page', async () => {
    const wrapper = mountInbox()
    await card(wrapper, 'OKX').find('.card-hit').trigger('click')
    const link = detail(wrapper).find('a.open')
    expect(link.attributes('href')).toBe('https://job-boards.greenhouse.io/okx/jobs/7767872003')
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toContain('noopener')
  })

  it('never turns a non-http URL into a link', async () => {
    const jobs = jobsFor(12)
    jobs[0] = { ...jobs[0], url: 'javascript:alert(1)' }     // OKX
    const wrapper = mountInbox(jobs)
    await card(wrapper, 'OKX').find('.card-hit').trigger('click')
    expect(detail(wrapper).find('a.open').exists()).toBe(false)
  })

  it('shows matched skills when the shortlist carries them, and nothing when not', async () => {
    const jobs = jobsFor(12)
    jobs[0] = { ...jobs[0], matched_skills: ['kubernetes', 'terraform'] }
    const wrapper = mountInbox(jobs)
    await card(wrapper, 'OKX').find('.card-hit').trigger('click')
    expect(detail(wrapper).findAll('.skills li').map(s => s.text())).toEqual(['kubernetes', 'terraform'])
    await card(wrapper, 'GovTech').find('.card-hit').trigger('click')
    expect(detail(wrapper).find('.skills').exists()).toBe(false)
  })

  it('after opening the posting it asks whether you applied, and Yes records it', async () => {
    const wrapper = mountInbox()
    expect(detail(wrapper).find('.did-apply').exists()).toBe(false)
    await detail(wrapper).find('a.open').trigger('click')
    expect(detail(wrapper).find('.did-apply').text()).toContain('Did you apply at Shopee?')
    await detail(wrapper).find('.did-apply-yes').trigger('click')
    await flushPromises()
    const post = api.calls.find(c => c.method === 'POST')
    expect(post.url).toBe('api/applications/g7h8i9')
    expect(JSON.parse(post.body).status).toBe('applied')
  })
})

describe('Inbox actions', () => {
  it('Mark applied posts the status, moves the role out at once and offers Undo', async () => {
    const wrapper = mountInbox()
    await card(wrapper, 'OKX').find('.card-hit').trigger('click')
    await detail(wrapper).find('button.apply').trigger('click')
    await flushPromises()

    const post = api.calls.find(c => c.method === 'POST')
    expect(post.url).toBe('api/applications/a1b2c3')
    expect(JSON.parse(post.body)).toMatchObject({ status: 'applied', company: 'OKX', role: 'DevOps / Site Reliability Engineer' })
    expect(wrapper.emitted('changed')).toHaveLength(1)
    // Gone from the Inbox before the shell has even reloaded the shortlist.
    expect(companies(wrapper)).toEqual(['Shopee', 'GovTech'])
    // The neighbour takes its place in the detail pane.
    expect(detail(wrapper).find('.detail-company').text()).toBe('GovTech')
    expect(toast.current.message).toBe('Marked applied: DevOps / Site Reliability Engineer at OKX')
    expect(toast.current.action.label).toBe('Undo')
    expect(toast.current.link).toEqual({ label: 'View in Applications', href: '#/applications' })
  })

  it('Undo removes the application and brings the role back', async () => {
    const wrapper = mountInbox()
    await detail(wrapper).find('button.apply').trigger('click')     // Shopee
    await flushPromises()
    expect(companies(wrapper)).not.toContain('Shopee')

    await toast.current.action.run()
    await flushPromises()
    const del = api.calls.find(c => c.method === 'DELETE')
    expect(del.url).toBe('api/applications/g7h8i9')
    expect(api.apps.g7h8i9).toBeUndefined()
    expect(companies(wrapper)).toContain('Shopee')
    expect(detail(wrapper).find('.detail-company').text()).toBe('Shopee')
    expect(wrapper.emitted('changed')).toHaveLength(2)
  })

  it('Save keeps a role for later as `to_apply` - it moves to Applications too', async () => {
    const wrapper = mountInbox()
    await detail(wrapper).find('button.save').trigger('click')
    await flushPromises()
    const post = api.calls.find(c => c.method === 'POST')
    expect(JSON.parse(post.body).status).toBe('to_apply')
    expect(companies(wrapper)).toEqual(['GovTech', 'OKX'])
    expect(toast.current.message).toBe('Saved: Software Engineer, Backend (New Grad) at Shopee')
  })

  it('reports a failed write, and the role stays in the Inbox', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false, status: 500, statusText: 'Internal Server Error', json: async () => ({}),
    })))
    const wrapper = mountInbox()
    await detail(wrapper).find('button.apply').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('500')
    expect(wrapper.emitted('changed')).toBeUndefined()
    expect(companies(wrapper)).toContain('Shopee')
    expect(toast.current).toBeNull()
  })

  it('Not interested hides the role locally, touches no server, and can be undone', async () => {
    const wrapper = mountInbox()
    await card(wrapper, 'GovTech').find('.card-hit').trigger('click')
    await detail(wrapper).find('button.dismiss').trigger('click')

    expect(card(wrapper, 'GovTech')).toBeUndefined()
    expect(wrapper.find('.count').text()).toContain('1 hidden this session')
    expect(api.calls).toHaveLength(0)
    expect(JSON.parse(window.sessionStorage.getItem('jobscraper.dismissed'))).toEqual(['d4e5f6'])

    await toast.current.action.run()
    expect(companies(wrapper)).toHaveLength(3)
  })

  it('the count\'s "show" brings hidden roles back', async () => {
    const wrapper = mountInbox()
    await detail(wrapper).find('button.dismiss').trigger('click')
    await wrapper.find('.count button.show-hidden').trigger('click')
    expect(companies(wrapper)).toHaveLength(3)
  })

  it('a dismissal survives the tab being re-mounted within the session', async () => {
    const first = mountInbox()
    await detail(first).find('button.dismiss').trigger('click')
    first.unmount()
    expect(mountInbox().findAll('.card')).toHaveLength(2)
  })
})
