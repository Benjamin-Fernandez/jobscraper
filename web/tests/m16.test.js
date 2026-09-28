// M16: your own list of companies (Companies tab), the background job's log on
// its own Developer tab, the job description in the Inbox, "Your company
// order", and no cap on job titles for the owner's plan.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import Companies from '../src/tabs/Companies.vue'
import Developer from '../src/tabs/Developer.vue'
import Inbox from '../src/tabs/Inbox.vue'
import TitleEditor from '../src/components/TitleEditor.vue'
import { POLL_MS, resetSeenJobs } from '../src/composables/useJob.js'
import { resetDismissed } from '../src/dismissed.js'
import { dismissToast } from '../src/toast.js'
import { runStatusLabel } from '../src/runs.js'
import { DOCX, FIXTURE, MB, defaultTitles, descriptionOf, fakeApi } from './helpers.js'

let api

function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
  return api
}

beforeEach(() => {
  resetSeenJobs()
  resetDismissed()
  dismissToast()
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  useApi()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
enableAutoUnmount(afterEach)

async function tick(times = 1) {
  for (let i = 0; i < times; i++) {
    await vi.advanceTimersByTimeAsync(POLL_MS)
    await flushPromises()
  }
}

const posts = url => api.calls.filter(c => c.method === 'POST' && c.url === url)

// ---------------------------------------------------------------- Companies

describe('Companies tab', () => {
  async function mountCompanies(options) {
    if (options) useApi(options)
    const wrapper = mount(Companies, { props: { run: 'all', jobs: [] } })
    await flushPromises()
    return wrapper
  }

  async function drop(wrapper, file) {
    const input = wrapper.find('input.file')
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    // jsdom's FileReader (the fake server reads the file) runs on a timer.
    for (let i = 0; i < 3; i++) {
      await vi.advanceTimersByTimeAsync(1)
      await flushPromises()
    }
  }

  const rows = w => w.findAll('.list .row:not(.none)').map(r => [
    r.find('.rank').text(), r.find('.name').text(), r.find('.status').text()])

  it('with no list, invites one', async () => {
    const wrapper = await mountCompanies()
    expect(wrapper.find('.empty-title').text()).toBe('No list yet.')
    expect(wrapper.find('.drop-title').text()).toContain('Drop your list of companies here')
    expect(wrapper.find('input.file').attributes('accept')).toContain('.txt')
    expect(wrapper.find('input.file').attributes('accept')).toContain('.docx')
  })

  it('uploads a TXT list raw, keeps its order, and starts the search', async () => {
    const wrapper = await mountCompanies()
    await drop(wrapper, new File(['1. Grab\n2. Ghost Holdings\n\n3. OKX\n'], 'dream.txt', { type: 'text/plain' }))

    const put = api.calls.find(c => c.method === 'PUT' && c.url === 'api/companies/list')
    expect(put.headers['Content-Type']).toBe('text/plain')
    expect(put.body).toBeInstanceOf(File)                 // the file itself, not a form
    expect(wrapper.find('.notice.ok').text()).toContain('Read 3 companies from dream.txt')
    expect(posts('api/jobs/companies')).toHaveLength(1)
    expect(rows(wrapper)).toEqual([['1', 'Grab', 'Waiting'], ['2', 'Ghost Holdings', 'Waiting'], ['3', 'OKX', 'Waiting']])
    expect(wrapper.find('.searching').text()).toContain('Searching 3 companies')
    expect(wrapper.find('.searching a').attributes('href')).toBe('#/developer')

    api.finishJob()
    await tick()
    expect(rows(wrapper)).toEqual([['1', 'Grab', 'Found'], ['2', 'Ghost Holdings', 'Failed'], ['3', 'OKX', 'Found']])
    expect(wrapper.find('.found-n').text()).toBe('2')
    expect(wrapper.find('.failed-n').text()).toBe('1')
    expect(wrapper.find('.cap').text()).toBe('2 companies counted · no limit on the local plan. Failed searches do not count.')
    expect(wrapper.find('.row[data-status="failed"] .detail').text()).toContain('no careers site found')
    expect(wrapper.find('.row[data-status="found"] a.site').attributes('href')).toBe('https://job-boards.greenhouse.io/grab')
    expect(wrapper.emitted('changed')).toBeTruthy()
  })

  it('sends a DOCX with its own type', async () => {
    const wrapper = await mountCompanies()
    await drop(wrapper, new File(['PK\u0003\u0004 list'], 'list.docx', { type: '' }))
    expect(api.calls.find(c => c.method === 'PUT').headers['Content-Type']).toBe(DOCX)
  })

  it('refuses other files before the network, and says what the server refused', async () => {
    const wrapper = await mountCompanies()
    await drop(wrapper, new File(['%PDF'], 'list.pdf', { type: 'application/pdf' }))
    expect(wrapper.find('[role="alert"]').text()).toContain('is not a TXT or DOCX file')
    await drop(wrapper, new File([new Uint8Array(MB + 1)], 'big.txt', { type: 'text/plain' }))
    expect(wrapper.find('[role="alert"]').text()).toContain('larger than 1 MB')
    expect(api.calls.filter(c => c.method === 'PUT')).toHaveLength(0)

    await drop(wrapper, new File(['\n  \n'], 'blank.txt', { type: 'text/plain' }))
    expect(wrapper.find('[role="alert"]').text()).toContain('No company names were found')
    expect(posts('api/jobs/companies')).toHaveLength(0)
  })

  it('filters by what the search did, keeping your order', async () => {
    const wrapper = await mountCompanies({ companies: [
      { name: 'Grab', status: 'found', detail: 'a greenhouse board, 4 open roles' },
      { name: 'Nowhere Ltd', status: 'failed', detail: 'no careers site found' },
      { name: 'OKX', status: 'watched', detail: 'already watched as OKX' },
      { name: 'Visa', status: 'pending' },
    ] })
    const filters = wrapper.findAll('.filter').map(b => b.text())
    expect(filters).toEqual(['All 4', 'Found 2', 'Failed 1', 'Waiting 1'])

    await wrapper.findAll('.filter')[1].trigger('click')
    expect(rows(wrapper)).toEqual([['1', 'Grab', 'Found'], ['3', 'OKX', 'Already watched']])
    await wrapper.findAll('.filter')[2].trigger('click')
    expect(rows(wrapper)).toEqual([['2', 'Nowhere Ltd', 'Failed']])
    expect(wrapper.findAll('.filter')[2].attributes('aria-pressed')).toBe('true')
  })

  it('downloads the found and the failed as TXT, one per line, in your order', async () => {
    const saved = []
    // A Blob that keeps what it was made of (jsdom's has no text()).
    vi.stubGlobal('Blob', class {
      constructor(parts, { type } = {}) { this.parts = parts; this.type = type }
      async text() { return this.parts.join('') }
    })
    const real = { create: URL.createObjectURL, revoke: URL.revokeObjectURL }
    URL.createObjectURL = blob => { saved.push(blob); return `blob:${saved.length}` }
    URL.revokeObjectURL = () => {}
    const clicks = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
      saved[saved.length - 1].filename = this.download
    })
    try {
      const wrapper = await mountCompanies({ companies: [
        { name: 'Grab', status: 'found' }, { name: 'Nowhere Ltd', status: 'failed' },
        { name: 'OKX', status: 'watched' }, { name: '=cmd', status: 'failed', detail: 'no, really' },
      ] })
      await wrapper.find('.dl-found').trigger('click')
      await wrapper.find('.dl-failed').trigger('click')
      await wrapper.find('.dl-report').trigger('click')
      expect(clicks).toHaveBeenCalledTimes(3)
      expect(saved.map(b => b.filename)).toEqual(['companies-found.txt', 'companies-failed.txt', 'companies-report.csv'])
      expect(await saved[0].text()).toBe('Grab\r\nOKX\r\n')
      expect(await saved[1].text()).toBe('Nowhere Ltd\r\n=cmd\r\n')
      const csv = await saved[2].text()
      expect(csv.split('\r\n')[0]).toBe('﻿rank,company,status,careers_url,open_roles,detail')
      expect(csv).toContain("4,'=cmd,Failed,,,\"no, really\"")     // never a formula; commas quoted
    } finally {
      clicks.mockRestore()
      URL.createObjectURL = real.create
      URL.revokeObjectURL = real.revoke
    }
  })

  it('a download with nothing in it is not offered', async () => {
    const wrapper = await mountCompanies({ companies: [{ name: 'Visa', status: 'pending' }] })
    expect(wrapper.find('.dl-found').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.dl-failed').attributes('disabled')).toBeDefined()
  })

  it('the plan cap counts only companies found; the rest wait over the limit', async () => {
    const wrapper = await mountCompanies({ maxCompanies: 1, companies: ['Ghost One', 'Grab', 'OKX'] })
    await wrapper.find('.search-now').trigger('click')
    await flushPromises()
    api.finishJob()
    await tick()
    expect(rows(wrapper)).toEqual([['1', 'Ghost One', 'Failed'], ['2', 'Grab', 'Found'], ['3', 'OKX', 'Over plan limit']])
    expect(wrapper.find('.cap').text()).toContain('1 of 1 companies used on the local plan')
  })

  it('Search now is refused while another job runs', async () => {
    const wrapper = await mountCompanies({ companies: ['Grab'] })
    api.server.job = { id: 7, kind: 'run', state: 'running', started_at: 'x', finished_at: null, exit_code: null, log: [] }
    await wrapper.find('.search-now').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('Another job is running')
  })

  it('Clear list asks first, then empties it', async () => {
    const wrapper = await mountCompanies({ companies: ['Grab'] })
    vi.stubGlobal('confirm', vi.fn(() => false))
    await wrapper.find('.clear').trigger('click')
    expect(api.calls.filter(c => c.method === 'DELETE')).toHaveLength(0)
    vi.stubGlobal('confirm', vi.fn(() => true))
    await wrapper.find('.clear').trigger('click')
    await flushPromises()
    expect(api.calls.filter(c => c.method === 'DELETE')).toHaveLength(1)
    expect(wrapper.find('.empty-title').text()).toBe('No list yet.')
  })
})

// ---------------------------------------------------------------- Developer

describe('Developer tab: the current job and its log', () => {
  async function mountDeveloper(options) {
    if (options) useApi(options)
    const wrapper = mount(Developer, { props: { run: 'all', jobs: [] } })
    await flushPromises()
    return wrapper
  }
  const running = { id: 3, kind: 'run', state: 'running', started_at: '2026-09-25T08:00:00', log: [] }

  it('says nothing has run, and does not poll', async () => {
    const wrapper = await mountDeveloper()
    expect(wrapper.find('.summary').text()).toContain('Nothing has run')
    await tick(3)
    expect(api.count(/^api\/jobs\/current/)).toBe(1)
  })

  it('follows a running job\'s log as lines arrive, and reloads the shell when a run ends', async () => {
    const wrapper = await mountDeveloper({ job: running })
    api.log('run 13: 10 companies due')
    await tick()
    expect(wrapper.find('.log').text()).toContain('run 13: 10 companies due')
    api.log('  -> OKX: 12 postings, 3 new')
    await tick()
    expect(wrapper.find('.log').text().split('\n')).toEqual(['run 13: 10 companies due', '  -> OKX: 12 postings, 3 new'])

    api.finishJob()
    await tick()
    expect(wrapper.find('.job-status').attributes('data-state')).toBe('succeeded')
    expect(wrapper.emitted('changed')).toEqual([[{ runs: true }]])
  })

  it('cancels the running job, whatever its kind', async () => {
    const wrapper = await mountDeveloper({ job: { ...running, kind: 'companies' } })
    expect(wrapper.find('button.cancel').text()).toBe('Cancel company search')
    await wrapper.find('button.cancel').trigger('click')
    await flushPromises()
    expect(posts('api/jobs/cancel')).toHaveLength(1)
    expect(wrapper.find('.summary').text()).toContain('exit -15')
    expect(wrapper.find('button.cancel').exists()).toBe(false)
  })

  it('a job left running across a web restart says it cannot be cancelled here', async () => {
    const wrapper = await mountDeveloper({ job: running })
    api.server.orphaned = true
    await wrapper.find('button.cancel').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('cannot be cancelled from here')
  })
})

// ---------------------------------------------------------------- Inbox

describe('Inbox: the job description', () => {
  const jobs = run => FIXTURE.jobs.filter(j => j.run_no === run).map(j => ({ ...j, closed: false, status: null, notes: null }))
  async function mountInbox(options, list = jobs(12)) {
    if (options) useApi(options)
    const wrapper = mount(Inbox, { props: { run: 12, jobs: list } })
    await flushPromises()
    return wrapper
  }

  it('shows the selected role\'s description as the employer wrote it', async () => {
    const wrapper = await mountInbox()
    const first = FIXTURE.jobs.find(j => j.id === 'g7h8i9')           // Shopee, newest
    expect(api.calls.filter(c => c.url.startsWith('api/postings/')).map(c => c.url)).toEqual(['api/postings/g7h8i9'])
    expect(wrapper.find('.jd-text').text()).toBe(descriptionOf(first))
    expect(wrapper.find('.jd').text()).toContain('About the job')
  })

  it('fetches another role\'s description when it is opened, once', async () => {
    const wrapper = await mountInbox()
    const okx = wrapper.findAll('.card').find(c => c.find('.company').text() === 'OKX')
    await okx.find('.card-hit').trigger('click')
    await flushPromises()
    expect(wrapper.find('.jd-text').text()).toContain('DevOps / Site Reliability Engineer at OKX.')
    const shopee = wrapper.findAll('.card').find(c => c.find('.company').text() === 'Shopee')
    await shopee.find('.card-hit').trigger('click')
    await flushPromises()
    expect(api.count(/^api\/postings\//)).toBe(2)
  })

  it('a long description is cut, with Show more', async () => {
    const long = Array.from({ length: 300 }, (_, i) => `word${i}`).join(' ')
    const wrapper = await mountInbox({ postings: { g7h8i9: long } })
    expect(wrapper.find('.jd-text').text().length).toBeLessThan(long.length)
    expect(wrapper.find('.jd-text').text().endsWith('…')).toBe(true)
    await wrapper.find('.jd-more').trigger('click')
    expect(wrapper.find('.jd-text').text()).toBe(long)
    expect(wrapper.find('.jd-more').text()).toBe('Show less')
  })

  it('says so when the board gave no description', async () => {
    const wrapper = await mountInbox({ postings: { g7h8i9: '' } })
    expect(wrapper.find('.jd-status').text()).toContain('gave no description')
    expect(wrapper.find('.jd-text').exists()).toBe(false)
  })

  it('"Your company order" appears with your list, and sorts by it', async () => {
    const plain = await mountInbox()
    expect(plain.find('.sort option[value="yours"]').exists()).toBe(false)

    const ranked = jobs(12).map(j => ({ ...j, company_rank: { OKX: 1, Shopee: 2 }[j.company] ?? null }))
    const wrapper = await mountInbox(undefined, ranked)
    expect(wrapper.find('.sort option[value="yours"]').text()).toBe('Your company order')
    await wrapper.find('.sort select').setValue('yours')
    expect(wrapper.findAll('.card .company').map(c => c.text())).toEqual(['OKX', 'Shopee', 'GovTech'])
  })
})

// ---------------------------------------------------------------- titles, run status

describe('No cap on job titles for the owner', () => {
  it('adds past 20 titles on the local plan', async () => {
    const many = Array.from({ length: 20 }, (_, i) => `title ${i}`)
    useApi({ titles: { ...defaultTitles(), titles: many } })
    const wrapper = mount(TitleEditor)
    await flushPromises()
    expect(wrapper.find('.te-count').text()).toBe('20 titles')
    expect(wrapper.find('.te-full').exists()).toBe(false)
    await wrapper.find('#new-title').setValue('data analyst')
    await wrapper.find('form.te-add').trigger('submit')
    await flushPromises()
    const put = api.calls.filter(c => c.method === 'PUT').at(-1)
    expect(JSON.parse(put.body).titles).toHaveLength(21)
    expect(wrapper.find('.te-count').text()).toBe('21 titles')
  })
})

describe('Run status in words', () => {
  it('says success, not ok', () => {
    expect(runStatusLabel('ok')).toBe('success')
    expect(runStatusLabel('failed')).toBe('failed')
    expect(runStatusLabel('aborted_unhealthy')).toBe('aborted')
    expect(runStatusLabel(null)).toBe('—')
  })
})
