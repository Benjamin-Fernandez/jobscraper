import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import App from '../src/App.vue'
import RunSelector from '../src/components/RunSelector.vue'
import { TABS } from '../src/tabs.js'
import { activeApplicationCount, newRoleCount } from '../src/badges.js'
import { resetDismissed } from '../src/dismissed.js'
import { tabFromHash } from '../src/route.js'
import { fakeApi, runsFrom, setHash } from './helpers.js'

let api
const LAST = TABS.at(-1).id

beforeEach(() => {
  setHash('')
  resetDismissed()
  api = fakeApi()
  vi.stubGlobal('fetch', api.fetch)
})
afterEach(() => vi.unstubAllGlobals())
enableAutoUnmount(afterEach)

async function mountApp(options = {}) {
  const wrapper = mount(App, options)
  await vi.waitFor(async () => {
    await flushPromises()
    expect(wrapper.findAll('.inbox .card').length).toBeGreaterThan(0)
  })
  return wrapper
}

// Mount and wait for whichever tab the URL names to render its root element.
async function mountOn(hash, selector) {
  setHash(hash)
  const wrapper = mount(App, { attachTo: document.body })
  await vi.waitFor(async () => {
    await flushPromises()
    expect(wrapper.find(selector).exists()).toBe(true)
  })
  return wrapper
}

function tab(wrapper, id) {
  return wrapper.find(`[role="tab"][data-tab="${id}"]`)
}

function selectedId(wrapper) {
  const selected = wrapper.findAll('[role="tab"]').filter(t => t.attributes('aria-selected') === 'true')
  expect(selected).toHaveLength(1)
  return selected[0].attributes('data-tab')
}

function badge(wrapper, id) {
  const b = tab(wrapper, id).find('.badge')
  return b.exists() ? Number(b.text().match(/^\d+/)[0]) : null
}

describe('App shell', () => {
  it('renders the page heading', () => {
    expect(mount(App).find('h1').text()).toBe('JobScraper')
  })

  it('renders one tab per TABS entry, in the top bar, in registry order', async () => {
    const wrapper = await mountApp()
    const labels = wrapper.findAll('[role="tab"] .tab-label').map(b => b.text())
    expect(labels).toEqual(TABS.map(t => t.label))
    // In this order (M16: Companies after Runs, Developer last); a later tab
    // (the M7-T4 probe) goes after them.
    expect(labels.slice(0, 7)).toEqual(['Inbox', 'Applications', 'Runs', 'Companies', 'Profile', 'Settings', 'Developer'])
    expect(wrapper.find('header [role="tablist"]').exists()).toBe(true)
  })

  it('opens on All runs (M15)', async () => {
    const wrapper = await mountApp()
    const dataset = api.calls.map(c => c.url).filter(u => /^api\/(runs|shortlist)/.test(u))
    expect(dataset).toEqual(['api/runs', 'api/shortlist?run=all'])
    expect(api.calls.filter(c => c.url === 'api/stats')).toHaveLength(1)
    expect(wrapper.find('.inbox .run-selector select').element.value).toBe('all')
    expect(wrapper.text()).toContain('OKX')
    expect(wrapper.text()).toContain('Grab')
  })

  it('the run selector belongs to the Inbox, not the global header', async () => {
    const wrapper = await mountApp()
    expect(wrapper.find('.masthead select').exists()).toBe(false)
    expect(wrapper.find('.inbox .run-selector select').exists()).toBe(true)
  })

  it('changing the run issues exactly one shortlist request and navigates nowhere', async () => {
    const wrapper = await mountApp()
    const before = window.location.href
    const callsBefore = api.calls.length

    await wrapper.find('.inbox .run-selector select').setValue('week')
    await flushPromises()

    const made = api.calls.slice(callsBefore).map(c => c.url)
    expect(made).toEqual(['api/shortlist?run=week'])
    expect(window.location.href).toBe(before)
    expect(wrapper.text()).toContain('OKX')         // run 12, finished 23 Sep
    expect(wrapper.text()).not.toContain('Grab')    // run 11, finished 21 Sep
  })

  it('Past month asks for run=month, and All runs goes back', async () => {
    const wrapper = await mountApp()
    await wrapper.find('.inbox .run-selector select').setValue('month')
    await flushPromises()
    expect(api.calls.at(-1).url).toBe('api/shortlist?run=month')
    await wrapper.find('.inbox .run-selector select').setValue('all')
    await flushPromises()
    expect(api.calls.at(-1).url).toBe('api/shortlist?run=all')
  })

  it('Choose runs… opens the picker on the Runs tab, and its choice comes back to the Inbox', async () => {
    const wrapper = await mountApp({ attachTo: document.body })
    const select = wrapper.find('.inbox .run-selector select')
    await select.setValue('choose')
    expect(window.location.hash).toBe('#/runs')
    expect(select.element.value).toBe('all')   // the selector still says what is shown
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.find('tr[data-run="11"] input[type="checkbox"]').exists()).toBe(true)
    })
    await wrapper.find('tr[data-run="11"] input[type="checkbox"]').setValue(true)
    await wrapper.find('button.show-picked').trigger('click')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.find('.inbox .card').exists()).toBe(true)
    })
    // The last dataset fetch (the detail pane then fetches its description).
    expect(api.calls.filter(c => !c.url.startsWith('api/postings/')).at(-1).url).toBe('api/shortlist?run=11')
    expect(wrapper.find('.inbox .run-selector select').element.value).toBe('chosen')
    expect(wrapper.find('.inbox .run-selector option[value="chosen"]').text()).toBe('Run 11')
    expect(wrapper.findAll('.inbox .card').map(c => c.find('.company').text()).sort()).toEqual(['Grab', 'Stripe'])
  })

  it('shows an error instead of a blank page when the API fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false, status: 500, statusText: 'Internal Server Error', json: async () => ({}),
    })))
    const wrapper = mount(App)
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    })
    expect(wrapper.find('[role="alert"]').text()).toContain('500')
    expect(wrapper.find('[role="alert"] button').text()).toBe('Try again')
  })

  it('shows a loading placeholder, not an empty list, while the shortlist loads', async () => {
    let release
    const gate = new Promise(r => { release = r })
    vi.stubGlobal('fetch', vi.fn(async (url, init) => {
      if (String(url).startsWith('api/shortlist')) await gate
      return api.fetch(url, init)
    }))
    const wrapper = mount(App)
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.find('.inbox [aria-busy="true"][role="status"]').exists()).toBe(true)
    })
    expect(wrapper.text()).not.toContain('No roles in')
    release()
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.findAll('.inbox .card')).toHaveLength(5)
    })
  })

  it('says so when no run has any roles', async () => {
    api = fakeApi({ fixture: { runs: [{ run_no: 3, finished_at: '2026-09-25T10:00:00', accepted: 0 }], jobs: [] } })
    vi.stubGlobal('fetch', api.fetch)
    const wrapper = mount(App)
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.text()).toContain('No roles in any run yet')
    })
  })
})

describe('Navigation: the active tab lives in the URL hash', () => {
  it('an empty hash opens the Inbox and the URL says #/inbox', async () => {
    const wrapper = await mountApp()
    expect(selectedId(wrapper)).toBe('inbox')
    expect(window.location.hash).toBe('#/inbox')
  })

  it('an unknown hash falls back to the Inbox', async () => {
    const wrapper = await mountOn('#/no-such-tab', '.inbox')
    expect(selectedId(wrapper)).toBe('inbox')
    expect(window.location.hash).toBe('#/inbox')
  })

  it('a bookmarked or refreshed hash opens that tab (URL -> tab)', async () => {
    const wrapper = await mountOn('#/applications', '.applications')
    expect(selectedId(wrapper)).toBe('applications')
    const panel = wrapper.find('[role="tabpanel"]')
    expect(panel.attributes('aria-labelledby')).toBe('tab-applications')
    expect(tab(wrapper, 'applications').attributes('aria-controls')).toBe(panel.attributes('id'))
    expect(document.title).toBe('Applications · JobScraper')
  })

  it('clicking a tab puts it in the URL (tab -> URL)', async () => {
    const wrapper = await mountApp({ attachTo: document.body })
    await tab(wrapper, 'applications').trigger('click')
    expect(window.location.hash).toBe('#/applications')
    expect(selectedId(wrapper)).toBe('applications')
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.find('.applications').exists()).toBe(true)
    })
  })

  it('back and forward move between tabs (hashchange -> tab)', async () => {
    const wrapper = await mountApp({ attachTo: document.body })
    window.history.pushState(null, '', '#/runs')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    await flushPromises()
    expect(selectedId(wrapper)).toBe('runs')

    setHash('#/inbox')
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    await flushPromises()
    expect(selectedId(wrapper)).toBe('inbox')
  })

  it('switching tabs does not refetch the shortlist', async () => {
    const wrapper = await mountApp({ attachTo: document.body })
    const before = api.calls.filter(c => c.url.startsWith('api/shortlist')).length
    await tab(wrapper, 'settings').trigger('click')
    await tab(wrapper, 'inbox').trigger('click')
    await flushPromises()
    expect(api.calls.filter(c => c.url.startsWith('api/shortlist')).length).toBe(before)
  })

  it('parses hashes strictly', () => {
    const ids = TABS.map(t => t.id)
    expect(tabFromHash('#/runs', ids)).toBe('runs')
    expect(tabFromHash('#/runs/', ids)).toBe('runs')
    expect(tabFromHash('#runs', ids)).toBe('inbox')
    expect(tabFromHash('#/Runs', ids)).toBe('inbox')
    expect(tabFromHash('', ids)).toBe('inbox')
    expect(tabFromHash('#/runs/../x', ids)).toBe('inbox')
  })
})

describe('Keyboard: WAI-ARIA tabs', () => {
  it('only the selected tab is in the Tab order', async () => {
    const wrapper = await mountApp()
    const stops = wrapper.findAll('[role="tab"]').map(t => t.attributes('tabindex'))
    expect(stops).toEqual(TABS.map((t, i) => (i === 0 ? '0' : '-1')))
  })

  it('ArrowRight / ArrowLeft move focus and selection, wrapping at the ends', async () => {
    const wrapper = await mountApp({ attachTo: document.body })
    tab(wrapper, 'inbox').element.focus()

    await tab(wrapper, 'inbox').trigger('keydown', { key: 'ArrowRight' })
    expect(selectedId(wrapper)).toBe('applications')
    expect(document.activeElement).toBe(tab(wrapper, 'applications').element)
    expect(window.location.hash).toBe('#/applications')

    await tab(wrapper, 'applications').trigger('keydown', { key: 'ArrowLeft' })
    expect(selectedId(wrapper)).toBe('inbox')

    await tab(wrapper, 'inbox').trigger('keydown', { key: 'ArrowLeft' })
    expect(selectedId(wrapper)).toBe(LAST)
    expect(document.activeElement).toBe(tab(wrapper, LAST).element)

    await tab(wrapper, LAST).trigger('keydown', { key: 'ArrowRight' })
    expect(selectedId(wrapper)).toBe('inbox')
  })

  it('Home and End jump to the first and last tab; other keys do nothing', async () => {
    const wrapper = await mountApp({ attachTo: document.body })
    await tab(wrapper, 'inbox').trigger('keydown', { key: 'End' })
    expect(selectedId(wrapper)).toBe(LAST)
    await tab(wrapper, LAST).trigger('keydown', { key: 'Home' })
    expect(selectedId(wrapper)).toBe('inbox')
    await tab(wrapper, 'inbox').trigger('keydown', { key: 'a' })
    expect(selectedId(wrapper)).toBe('inbox')
  })
})

describe('Badges', () => {
  it('Inbox counts the run\'s roles with no status; Applications counts active ones', async () => {
    api = fakeApi({ statuses: { a1b2c3: 'applied', j1k2l3: 'interviewing', m4n5o6: 'rejected' } })
    vi.stubGlobal('fetch', api.fetch)
    const wrapper = await mountApp()
    await flushPromises()
    // All runs: five roles, three of them tracked (OKX, Grab, Stripe).
    expect(badge(wrapper, 'inbox')).toBe(2)
    // applied + interviewing; rejected is not active.
    expect(badge(wrapper, 'applications')).toBe(2)
    expect(badge(wrapper, 'runs')).toBeNull()
    expect(tab(wrapper, 'inbox').find('.badge').text()).toContain('new roles')
  })

  it('follow the data: marking a role applied moves it from one badge to the other', async () => {
    const wrapper = await mountApp()
    await flushPromises()
    expect(badge(wrapper, 'inbox')).toBe(5)
    expect(badge(wrapper, 'applications')).toBeNull()

    await wrapper.find('.inbox .detail button.apply').trigger('click')
    await vi.waitFor(async () => {
      await flushPromises()
      expect(badge(wrapper, 'inbox')).toBe(4)
    })
    expect(badge(wrapper, 'applications')).toBe(1)
  })

  it('a dismissed role leaves the Inbox badge', async () => {
    const wrapper = await mountApp()
    await flushPromises()
    await wrapper.find('.inbox .detail button.dismiss').trigger('click')
    expect(badge(wrapper, 'inbox')).toBe(4)
  })

  it('count helpers', () => {
    expect(newRoleCount([{ id: 'x', status: null }, { id: 'y', status: 'applied' }])).toBe(1)
    expect(activeApplicationCount({ to_apply: 1, applied: 2, offer: 1, rejected: 5, withdrawn: 1 })).toBe(4)
    expect(activeApplicationCount(undefined)).toBe(0)
  })
})

describe('RunSelector', () => {
  it('All runs always comes first, then Past week, Past month and Choose runs…', () => {
    const wrapper = mount(RunSelector, { props: { runs: runsFrom(), modelValue: 'all' } })
    expect(wrapper.findAll('option').map(o => o.text()))
      .toEqual(['All runs', 'Past week', 'Past month', 'Choose runs…'])
    expect(wrapper.find('select').element.value).toBe('all')
  })

  it('runs chosen on the Runs tab show as their own option, after the ranges', () => {
    const one = mount(RunSelector, { props: { runs: runsFrom(), modelValue: [12] } })
    expect(one.findAll('option').map(o => o.text()))
      .toEqual(['All runs', 'Past week', 'Past month', 'Run 12', 'Choose runs…'])
    expect(one.find('select').element.value).toBe('chosen')
    const two = mount(RunSelector, { props: { runs: runsFrom(), modelValue: [12, 11] } })
    expect(two.find('option[value="chosen"]').text()).toBe('Runs 12, 11')
  })

  it('emits a range, and asks for the picker instead of emitting a value', async () => {
    const wrapper = mount(RunSelector, { props: { runs: runsFrom(), modelValue: 'all' } })
    await wrapper.find('select').setValue('week')
    await wrapper.find('select').setValue('choose')
    expect(wrapper.emitted('update:modelValue')).toEqual([['week']])
    expect(wrapper.emitted('choose')).toHaveLength(1)
  })

  it('Applications has no picker: ranges only', () => {
    const wrapper = mount(RunSelector, { props: { runs: runsFrom(), modelValue: 'all', choosable: false } })
    expect(wrapper.findAll('option').map(o => o.text())).toEqual(['All runs', 'Past week', 'Past month'])
  })

  it('is disabled when there are no runs', () => {
    const wrapper = mount(RunSelector, { props: { runs: [], modelValue: 'all' } })
    expect(wrapper.find('select').attributes('disabled')).toBeDefined()
  })

  it('has a visible label', () => {
    const wrapper = mount(RunSelector, { props: { runs: runsFrom(), modelValue: 12 } })
    expect(wrapper.find('label').text()).toContain('Run')
  })
})
