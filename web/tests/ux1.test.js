// UX-1 (.claude/plans/ux1-frontend-polish.plan.md): a getting-started checklist in
// place of the empty Inbox, companies typed or pasted, application notes and a
// Recent activity sort, triage shortcuts in the Inbox, a readable job
// description, and shell polish (badge slots, page titles, plainer copy).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import App from '../src/App.vue'
import Applications from '../src/tabs/Applications.vue'
import Companies from '../src/tabs/Companies.vue'
import Inbox from '../src/tabs/Inbox.vue'
import Profile from '../src/tabs/Profile.vue'
import Runs from '../src/tabs/Runs.vue'
import Settings from '../src/tabs/Settings.vue'
import { setupSteps } from '../src/setup.js'
import { parseDescription, previewBlocks } from '../src/jd.js'
import { resetDismissed } from '../src/dismissed.js'
import { resetSeenJobs } from '../src/composables/useJob.js'
import { dismissToast } from '../src/toast.js'
import { FIXTURE, defaultTitles, fakeApi, runsFrom, setHash } from './helpers.js'

let api

function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
}

beforeEach(() => {
  resetSeenJobs()
  resetDismissed()
  window.localStorage.removeItem('jobscraper.inbox.shortcuts')
  useApi()
})
afterEach(() => {
  dismissToast()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
enableAutoUnmount(afterEach)

const EMPTY_HEALTH = { total: 0, counts: { ok: 0, failed: 0, not_scanned: 0 }, items: [] }
const NEW_USER = {
  fixture: { runs: [], jobs: [] },
  profile: { present: false },
  titles: { ...defaultTitles(), titles: [], resume_titles: [] },
  companies: [],
  health: EMPTY_HEALTH,
}

// ------------------------------------------------------------ A1: getting started

describe('Getting started: the steps', () => {
  it('lists resume, titles, companies and a first run, in that order', () => {
    const steps = setupSteps({ hasResume: false, titleCount: 0, companyCount: 0, runCount: 0 })
    expect(steps.map(s => s.id)).toEqual(['resume', 'titles', 'companies', 'run'])
    expect(steps.map(s => s.href)).toEqual(['#/profile/resume', '#/profile/resume', '#/companies', '#/runs'])
    expect(steps.every(s => !s.done)).toBe(true)
  })

  it('marks each step done from what already exists', () => {
    const steps = setupSteps({ hasResume: true, titleCount: 2, companyCount: 0, runCount: 0 })
    expect(steps.map(s => s.done)).toEqual([true, true, false, false])
  })
})

describe('Getting started: in the empty Inbox', () => {
  async function mountEmptyInbox(options) {
    useApi(options)
    const wrapper = mount(Inbox, { props: { run: 'all', runs: [], jobs: [] } })
    await flushPromises()
    return wrapper
  }

  it('a new user sees the checklist, not a dead end', async () => {
    const wrapper = await mountEmptyInbox(NEW_USER)
    expect(wrapper.find('.setup').exists()).toBe(true)
    expect(wrapper.find('.setup-progress').text()).toBe('0 of 4 done')
    expect(wrapper.findAll('.setup-step a').map(a => a.attributes('href')))
      .toEqual(['#/profile/resume', '#/profile/resume', '#/companies', '#/runs'])
    expect(wrapper.text()).not.toContain('No roles in')
  })

  it('ticks what is done and points at the next step', async () => {
    const wrapper = await mountEmptyInbox({ ...NEW_USER, profile: { present: true }, titles: defaultTitles() })
    expect(wrapper.find('.setup-progress').text()).toBe('2 of 4 done')
    const steps = wrapper.findAll('.setup-step')
    expect(steps.map(s => s.classes('done'))).toEqual([true, true, false, false])
    expect(steps[2].classes('next')).toBe(true)
  })

  it('says so when a step could not be checked (review)', async () => {
    useApi(NEW_USER)
    const real = api.fetch
    vi.stubGlobal('fetch', vi.fn(async (url, init) => (url === 'api/titles'
      ? { ok: false, status: 500, statusText: 'Error', json: async () => ({ detail: 'boom' }) }
      : real(url, init))))
    const wrapper = mount(Inbox, { props: { run: 'all', runs: [], jobs: [] } })
    await flushPromises()
    expect(wrapper.find('.setup-unknown').text()).toContain('Could not check')
  })

  it('companies from the watchlist count as added', async () => {
    const wrapper = await mountEmptyInbox({ ...NEW_USER, health: undefined })
    expect(wrapper.find('.setup-step[data-step="companies"]').classes('done')).toBe(true)
  })

  it('once everything is set up, the usual empty state returns', async () => {
    useApi({ fixture: { runs: [{ run_no: 3, finished_at: '2026-09-25T10:00:00', accepted: 0 }], jobs: [] } })
    const wrapper = mount(Inbox, { props: { run: 'all', runs: runsFrom(), jobs: [] } })
    await flushPromises()
    expect(wrapper.find('.setup').exists()).toBe(false)
    expect(wrapper.text()).toContain('No roles in any run yet')
  })
})

// ------------------------------------------------------------ A2: type or paste companies

describe('Companies: type or paste names', () => {
  async function mountCompanies(companies) {
    useApi({ companies })
    // Attached, so a submit button's click submits its form as in a browser.
    const wrapper = mount(Companies, { props: { run: 'all', jobs: [] }, attachTo: document.body })
    await flushPromises()
    // Personal keeps the Watched / Your list switch; the editor lives under "Your list".
    await wrapper.find('button.view-list').trigger('click')
    await flushPromises()
    return wrapper
  }

  it('opens an editor holding the current list, in order', async () => {
    const wrapper = await mountCompanies(['Grab', 'Shopee'])
    await wrapper.find('button.edit-list').trigger('click')
    await flushPromises()
    const box = wrapper.find('textarea.list-text').element
    expect(box.value).toBe('Grab\nShopee')
    expect(document.activeElement).toBe(box)
  })

  it('saves what was typed as the list, and searches the new names', async () => {
    const wrapper = await mountCompanies(['Grab'])
    await wrapper.find('button.edit-list').trigger('click')
    await wrapper.find('textarea.list-text').setValue('Stripe\nGrab')
    await wrapper.find('button.save-list').trigger('click')
    // The fake reads the file with a FileReader, which ends on a later task.
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.findAll('.list .row .name').map(n => n.text())).toEqual(['Stripe', 'Grab'])
    })
    const put = api.calls.find(c => c.url === 'api/companies/list' && c.method === 'PUT')
    expect(put.headers['Content-Type']).toBe('text/plain')
    expect(api.count(/^api\/jobs\/companies$/)).toBe(1)
    expect(wrapper.find('textarea.list-text').exists()).toBe(false)
  })

  it('an empty list is refused here, with a reason', async () => {
    const wrapper = await mountCompanies([])
    await wrapper.find('button.edit-list').trigger('click')
    await wrapper.find('textarea.list-text').setValue('  \n ')
    await wrapper.find('button.save-list').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('at least one company')
    expect(api.calls.some(c => c.method === 'PUT')).toBe(false)
  })

  it('Cancel leaves the list as it was', async () => {
    const wrapper = await mountCompanies(['Grab'])
    await wrapper.find('button.edit-list').trigger('click')
    await wrapper.find('textarea.list-text').setValue('Stripe')
    await wrapper.find('button.cancel-list').trigger('click')
    expect(wrapper.find('textarea.list-text').exists()).toBe(false)
    expect(api.calls.some(c => c.method === 'PUT')).toBe(false)
  })
})

// ------------------------------------------------------------ A3 + A4: notes and sort

describe('Applications: notes', () => {
  async function mountTab(statuses) {
    useApi({ statuses })
    const wrapper = mount(Applications, { props: { run: 12, runs: runsFrom(), jobs: [] }, attachTo: document.body })
    await flushPromises()
    return wrapper
  }
  const row = (w, id) => w.find(`.app-row[data-job="${id}"]`)

  it('adds a note without adding to the history', async () => {
    const wrapper = await mountTab({ a1b2c3: 'applied' })
    expect(row(wrapper, 'a1b2c3').find('button.note-edit').text()).toBe('Add note')
    await row(wrapper, 'a1b2c3').find('button.note-edit').trigger('click')
    await row(wrapper, 'a1b2c3').find('textarea.note-input').setValue('Recruiter call Friday')
    await row(wrapper, 'a1b2c3').find('button.note-save').trigger('click')
    await flushPromises()
    const post = api.calls.find(c => c.url === 'api/applications/a1b2c3' && c.method === 'POST')
    expect(JSON.parse(post.body)).toMatchObject({ status: 'applied', notes: 'Recruiter call Friday' })
    expect(api.apps.a1b2c3.events).toHaveLength(1)
    expect(row(wrapper, 'a1b2c3').find('.notes').text()).toBe('Recruiter call Friday')
    expect(row(wrapper, 'a1b2c3').find('button.note-edit').text()).toBe('Edit note')
  })

  it('a slow save never closes another row\'s open note (review)', async () => {
    const wrapper = await mountTab({ a1b2c3: 'applied', j1k2l3: 'applied' })
    await row(wrapper, 'a1b2c3').find('button.note-edit').trigger('click')
    await row(wrapper, 'a1b2c3').find('textarea.note-input').setValue('first')
    await row(wrapper, 'a1b2c3').find('button.note-save').trigger('click')
    // While that save is in flight, no other note can be opened.
    expect(row(wrapper, 'j1k2l3').find('button.note-edit').attributes('disabled')).toBeDefined()
    await flushPromises()
    expect(row(wrapper, 'j1k2l3').find('button.note-edit').attributes('disabled')).toBeUndefined()
  })

  it('Cancel sends nothing', async () => {
    const wrapper = await mountTab({ a1b2c3: 'applied' })
    await row(wrapper, 'a1b2c3').find('button.note-edit').trigger('click')
    await row(wrapper, 'a1b2c3').find('textarea.note-input').setValue('draft')
    await row(wrapper, 'a1b2c3').find('button.note-cancel').trigger('click')
    expect(api.calls.some(c => c.method === 'POST')).toBe(false)
    expect(row(wrapper, 'a1b2c3').find('textarea.note-input').exists()).toBe(false)
  })
})

describe('Applications: sort', () => {
  it('Recent activity puts the latest change first', async () => {
    // Grab is changed first, OKX after it.
    useApi({ statuses: { j1k2l3: 'applied', a1b2c3: 'applied' } })
    const wrapper = mount(Applications, { props: { run: 12, runs: runsFrom(), jobs: [] } })
    await flushPromises()
    const names = () => wrapper.findAll('.company-group .group-name').map(g => g.text())
    expect(names()).toEqual(['Grab', 'OKX'])
    await wrapper.find('select.app-sort').setValue('recent')
    expect(names()).toEqual(['OKX', 'Grab'])
  })
})

// ------------------------------------------------------------ A5: triage shortcuts

describe('Inbox: triage shortcuts', () => {
  const jobs = FIXTURE.jobs.filter(j => j.run_no === 12).map(j => ({ ...j, closed: false, status: null, notes: null }))
  async function mountInbox() {
    const wrapper = mount(Inbox, { props: { run: 12, jobs }, attachTo: document.body })
    await flushPromises()
    return wrapper
  }
  const press = (key, init = {}, target = window) => {
    target.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init }))
    return flushPromises()
  }
  const posted = () => api.calls.filter(c => c.method === 'POST' && c.url.startsWith('api/applications/'))
    .map(c => [c.url, JSON.parse(c.body).status])

  it('S saves the selected role', async () => {
    await mountInbox()
    await press('s')
    expect(posted()).toEqual([['api/applications/g7h8i9', 'to_apply']])
  })

  it('A marks it applied', async () => {
    await mountInbox()
    await press('a')
    expect(posted()).toEqual([['api/applications/g7h8i9', 'applied']])
  })

  it('X marks it not interested', async () => {
    await mountInbox()
    await press('x')
    expect(api.calls.some(c => c.url === 'api/dismissals/g7h8i9' && c.method === 'PUT')).toBe(true)
  })

  it('O opens the posting and asks whether you applied', async () => {
    const open = vi.spyOn(window, 'open').mockImplementation(() => null)
    const wrapper = await mountInbox()
    await press('o')
    expect(open).toHaveBeenCalledWith(jobs.find(j => j.id === 'g7h8i9').url, '_blank', 'noopener,noreferrer')
    expect(wrapper.find('.did-apply').exists()).toBe(true)
  })

  it('never fires while typing, or with a modifier', async () => {
    const wrapper = await mountInbox()
    await press('s', {}, wrapper.find('input[type="search"]').element)
    await press('s', { ctrlKey: true })
    await press('a', { metaKey: true })
    expect(posted()).toEqual([])
  })

  it('says which keys there are, to screen readers too', async () => {
    const wrapper = await mountInbox()
    expect(wrapper.findAll('.shortcuts kbd').map(k => k.text())).toEqual(['S', 'A', 'X', 'O', 'J', 'K', 'Z', '?'])
    expect(wrapper.find('.shortcuts').attributes('aria-hidden')).toBeUndefined()
    expect(wrapper.find('button.save').attributes('aria-keyshortcuts')).toBe('S')
  })

  // WCAG 2.1.4: single-key shortcuts can be turned off (review).
  it('can be turned off, and stay off on this device', async () => {
    const wrapper = await mountInbox()
    await wrapper.find('button.shortcuts-toggle').trigger('click')
    await press('s')
    expect(posted()).toEqual([])
    expect(wrapper.find('button.save').attributes('aria-keyshortcuts')).toBeUndefined()
    expect(wrapper.find('button.shortcuts-toggle').text()).toBe('Turn on keyboard shortcuts')
    wrapper.unmount()

    const again = await mountInbox()
    await press('s')
    expect(posted()).toEqual([])
    await again.find('button.shortcuts-toggle').trigger('click')
    await press('s')
    expect(posted()).toEqual([['api/applications/g7h8i9', 'to_apply']])
  })
})

// ------------------------------------------------------------ A6: the job description

describe('The job description, made readable', () => {
  it('finds headings, lists and paragraphs', () => {
    const text = 'About the role\nYou will run our cloud.\n\nWhat you will do\n- Operate CI/CD\n- Write Terraform\n\nRequirements:\n\n• Python\n• Go'
    expect(parseDescription(text)).toEqual([
      { type: 'heading', text: 'About the role' },
      { type: 'para', text: 'You will run our cloud.' },
      { type: 'heading', text: 'What you will do' },
      { type: 'list', items: ['Operate CI/CD', 'Write Terraform'] },
      { type: 'heading', text: 'Requirements' },
      { type: 'list', items: ['Python', 'Go'] },
    ])
  })

  it('keeps numbered items as a list and a sentence as a paragraph', () => {
    expect(parseDescription('1. Design\n2) Build')).toEqual([{ type: 'list', items: ['Design', 'Build'] }])
    expect(parseDescription('We are hiring.')).toEqual([{ type: 'para', text: 'We are hiring.' }])
    expect(parseDescription('')).toEqual([])
  })

  it('a long sentence line is never taken for a heading', () => {
    const blocks = parseDescription('You will work with a small team of engineers across the region on payments.\nMore.')
    expect(blocks.every(b => b.type === 'para')).toBe(true)
  })

  it('a preview stops at the limit and says it was cut', () => {
    const blocks = parseDescription(`Intro\n${'a '.repeat(40)}\n\nMore\n- one\n- two`)
    const { blocks: shown, cut } = previewBlocks(blocks, 30)
    expect(cut).toBe(true)
    expect(shown.at(-1).text.endsWith('…')).toBe(true)
    expect(previewBlocks(blocks, 10_000)).toEqual({ blocks, cut: false })
  })

  it('the Inbox renders it as headings and lists', async () => {
    const jobs = FIXTURE.jobs.filter(j => j.run_no === 12).map(j => ({ ...j, closed: false, status: null, notes: null }))
    const wrapper = mount(Inbox, { props: { run: 12, jobs } })
    await flushPromises()
    expect(wrapper.findAll('.jd-text .jd-h').map(h => h.text())).toEqual(['About the role', 'What you will do'])
    expect(wrapper.findAll('.jd-text li')).toHaveLength(2)
  })
})

// ------------------------------------------------------------ A7 + A8: shell and copy

describe('Shell polish', () => {
  it('a tab with no count keeps no empty badge slot', async () => {
    setHash('')
    const wrapper = mount(App)
    await flushPromises()
    expect(wrapper.find('[data-tab="runs"] .badge-slot').exists()).toBe(false)
    expect(wrapper.find('[data-tab="applications"] .badge-slot').exists()).toBe(false)   // nothing tracked yet
    expect(wrapper.find('[data-tab="inbox"] .badge-slot').exists()).toBe(true)
  })

  it.each([[Runs, 'Runs'], [Profile, 'Profile'], [Settings, 'Settings']])('%#: every tab has a page title', async (Tab, title) => {
    const wrapper = mount(Tab, { props: { run: 'all', runs: runsFrom(), jobs: [] } })
    await flushPromises()
    expect(wrapper.find('.page-title').text()).toBe(title)
  })

  // Not ported: the cloud's "Read my resume again" wording; personal's Profile keeps "Re-derive profile" (C-17 note).
})
