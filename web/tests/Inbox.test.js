import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import Inbox from '../src/tabs/Inbox.vue'
import { resetDismissed } from '../src/dismissed.js'
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

function card(wrapper, company) {
  return wrapper.findAll('.card').find(c => c.find('.company').text() === company)
}

beforeEach(() => {
  resetDismissed()
  api = fakeApi()
  vi.stubGlobal('fetch', api.fetch)
})
afterEach(() => vi.unstubAllGlobals())

describe('Inbox', () => {
  it('shows company, title, location, years, reason and when it was seen', () => {
    const okx = card(mountInbox(), 'OKX')
    expect(okx.find('.title').text()).toBe('DevOps / Site Reliability Engineer')
    expect(okx.find('.meta').text()).toBe('Singapore · 0 yrs · seen 23 Sep')
    expect(okx.find('.reason').text()).toContain('K8s and CI/CD match')
  })

  it('lists every job for the run, with a count', () => {
    const wrapper = mountInbox()
    expect(wrapper.findAll('.card')).toHaveLength(3)
    expect(wrapper.find('.count').text()).toContain('3 roles')
  })

  it('opens the posting in a new tab without handing it this page', () => {
    const link = card(mountInbox(), 'OKX').find('a.open')
    expect(link.attributes('href')).toBe('https://job-boards.greenhouse.io/okx/jobs/7767872003')
    expect(link.attributes('target')).toBe('_blank')
    expect(link.attributes('rel')).toContain('noopener')
  })

  it('never turns a non-http URL into a link', () => {
    const jobs = jobsFor(12)
    jobs[0] = { ...jobs[0], url: 'javascript:alert(1)' }
    const wrapper = mountInbox(jobs)
    expect(card(wrapper, 'OKX').find('a').exists()).toBe(false)
  })

  it('shows matched skills when the shortlist carries them, and nothing when not', () => {
    const jobs = jobsFor(12)
    jobs[0] = { ...jobs[0], matched_skills: ['kubernetes', 'terraform'] }
    const wrapper = mountInbox(jobs)
    expect(card(wrapper, 'OKX').findAll('.skills li').map(s => s.text())).toEqual(['kubernetes', 'terraform'])
    expect(card(wrapper, 'GovTech').find('.skills').exists()).toBe(false)
  })

  it('Mark applied posts the status and asks the shell to reload', async () => {
    const wrapper = mountInbox()
    await card(wrapper, 'OKX').find('button.apply').trigger('click')
    await flushPromises()

    const post = api.calls.find(c => c.method === 'POST')
    expect(post.url).toBe('api/applications/a1b2c3')
    expect(JSON.parse(post.body)).toMatchObject({ status: 'applied', company: 'OKX' })
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('a job already applied to shows its status and cannot be marked again', () => {
    const okx = card(mountInbox(jobsFor(12, { a1b2c3: 'applied' })), 'OKX')
    expect(okx.find('.status').text()).toBe('applied')
    expect(okx.find('button.apply').attributes('disabled')).toBeDefined()
    expect(okx.find('button.apply').text()).toBe('Applied')
  })

  it('reports a failed write instead of pretending it worked', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false, status: 500, statusText: 'Internal Server Error', json: async () => ({}),
    })))
    const wrapper = mountInbox()
    await card(wrapper, 'OKX').find('button.apply').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('500')
    expect(wrapper.emitted('changed')).toBeUndefined()
  })

  it('Dismiss hides the role locally, touches no server, and can be undone', async () => {
    const wrapper = mountInbox()
    await card(wrapper, 'GovTech').find('button.dismiss').trigger('click')

    expect(card(wrapper, 'GovTech')).toBeUndefined()
    expect(wrapper.findAll('.card')).toHaveLength(2)
    expect(wrapper.find('.count').text()).toContain('1 dismissed this session')
    expect(api.calls).toHaveLength(0)
    expect(JSON.parse(window.sessionStorage.getItem('jobscraper.dismissed'))).toEqual(['d4e5f6'])

    await wrapper.find('.count button').trigger('click')
    expect(wrapper.findAll('.card')).toHaveLength(3)
  })

  it('a dismissal survives the tab being re-mounted within the session', async () => {
    const first = mountInbox()
    await card(first, 'GovTech').find('button.dismiss').trigger('click')
    first.unmount()
    expect(mountInbox().findAll('.card')).toHaveLength(2)
  })

  it('marks a closed posting as stale rather than hiding it', () => {
    const jobs = jobsFor(12)
    jobs[0] = { ...jobs[0], closed: true }
    const okx = card(mountInbox(jobs), 'OKX')
    expect(okx.classes()).toContain('closed')
    expect(okx.find('.stale').text()).toBe('closed')
  })
})
