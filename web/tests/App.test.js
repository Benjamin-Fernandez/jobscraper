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
    expect(labels).toEqual(['Inbox', 'Applications', 'Runs', 'Profile', 'Settings'])
    expect(wrapper.find('header [role="tablist"]').exists()).toBe(true)
  })

  it('opens on the newest run', async () => {
    const wrapper = await mountApp()
    const dataset = api.calls.map(c => c.url).filter(u => /^api\/(runs|shortlist)/.test(u))
    expect(dataset).toEqual(['api/runs', 'api/shortlist?run=12'])
    expect(api.calls.filter(c => c.url === 'api/stats')).toHaveLength(1)
    expect(wrapper.find('.inbox select').element.value).toBe('12')
    expect(wrapper.text()).toContain('OKX')
    expect(wrapper.text()).not.toContain('Grab')
  })

  it('the run selector belongs to the Inbox, not the global header', async () => {
    const wrapper = await mountApp()
    expect(wrapper.find('header select').exists()).toBe(false)
    expect(wrapper.find('.inbox .run-selector select').exists()).toBe(true)
  })

  it('changing the run issues exactly one shortlist request and navigates nowhere', async () => {
    const wrapper = await mountApp()
    const before = window.location.href
    const callsBefore = api.calls.length

    await wrapper.find('.inbox select').setValue('11')
    await flushPromises()

    const made = api.calls.slice(callsBefore).map(c => c.url)
    expect(made).toEqual(['api/shortlist?run=11'])
    expect(window.location.href).toBe(before)
    expect(wrapper.text()).toContain('Grab')
    expect(wrapper.text()).not.toContain('OKX')
  })

  it('the "all runs" option asks for run=all', async () => {
    const wrapper = await mountApp()
    await wrapper.find('.inbox select').setValue('all')
    await flushPromises()
    expect(api.calls.at(-1).url).toBe('api/shortlist?run=all')
    expect(wrapper.text()).toContain('OKX')
    expect(wrapper.text()).toContain('Grab')
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
    expect(wrapper.text()).not.toContain('No roles in this run')
    release()
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.findAll('.inbox .card')).toHaveLength(3)
    })
  })

  it('says so when the run has no roles', async () => {
    api = fakeApi({ fixture: { runs: [{ run_no: 3, finished_at: '2026-09-25T10:00:00', accepted: 0 }], jobs: [] } })
    vi.stubGlobal('fetch', api.fetch)
    const wrapper = mount(App)
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.text()).toContain('No roles in this run')
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
    expect(stops).toEqual(['0', '-1', '-1', '-1', '-1'])
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
    expect(selectedId(wrapper)).toBe('settings')
    expect(document.activeElement).toBe(tab(wrapper, 'settings').element)

    await tab(wrapper, 'settings').trigger('keydown', { key: 'ArrowRight' })
    expect(selectedId(wrapper)).toBe('inbox')
  })

  it('Home and End jump to the first and last tab; other keys do nothing', async () => {
    const wrapper = await mountApp({ attachTo: document.body })
    await tab(wrapper, 'inbox').trigger('keydown', { key: 'End' })
    expect(selectedId(wrapper)).toBe('settings')
    await tab(wrapper, 'settings').trigger('keydown', { key: 'Home' })
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
    // Run 12 holds OKX (applied), GovTech and Shopee (untouched).
    expect(badge(wrapper, 'inbox')).toBe(2)
    // applied + interviewing; rejected is not active.
    expect(badge(wrapper, 'applications')).toBe(2)
    expect(badge(wrapper, 'runs')).toBeNull()
    expect(tab(wrapper, 'inbox').find('.badge').text()).toContain('new roles')
  })

  it('follow the data: marking a role applied moves it from one badge to the other', async () => {
    const wrapper = await mountApp()
    await flushPromises()
    expect(badge(wrapper, 'inbox')).toBe(3)
    expect(badge(wrapper, 'applications')).toBeNull()

    await wrapper.findAll('.inbox .card button.apply')[0].trigger('click')
    await vi.waitFor(async () => {
      await flushPromises()
      expect(badge(wrapper, 'inbox')).toBe(2)
    })
    expect(badge(wrapper, 'applications')).toBe(1)
  })

  it('a dismissed role leaves the Inbox badge', async () => {
    const wrapper = await mountApp()
    await flushPromises()
    await wrapper.findAll('.inbox .card button.dismiss')[0].trigger('click')
    expect(badge(wrapper, 'inbox')).toBe(2)
  })

  it('count helpers', () => {
    expect(newRoleCount([{ id: 'x', status: null }, { id: 'y', status: 'applied' }])).toBe(1)
    expect(activeApplicationCount({ to_apply: 1, applied: 2, offer: 1, rejected: 5, withdrawn: 1 })).toBe(4)
    expect(activeApplicationCount(undefined)).toBe(0)
  })
})

describe('RunSelector', () => {
  it('labels each run with its number, date and role count', () => {
    const wrapper = mount(RunSelector, { props: { runs: runsFrom(), modelValue: 12 } })
    const options = wrapper.findAll('option').map(o => o.text())
    expect(options).toEqual(['run 12 · 23 Sep · 3 roles', 'run 11 · 21 Sep · 2 roles', 'all runs'])
  })

  it('emits a number for a run and the string "all" for every run', async () => {
    const wrapper = mount(RunSelector, { props: { runs: runsFrom(), modelValue: 12 } })
    await wrapper.find('select').setValue('11')
    await wrapper.find('select').setValue('all')
    expect(wrapper.emitted('update:modelValue')).toEqual([[11], ['all']])
  })

  it('is disabled with a message when there are no runs', () => {
    const wrapper = mount(RunSelector, { props: { runs: [], modelValue: null } })
    expect(wrapper.find('select').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('no runs yet')
  })

  it('has a visible label', () => {
    const wrapper = mount(RunSelector, { props: { runs: runsFrom(), modelValue: 12 } })
    expect(wrapper.find('label').text()).toContain('Run')
  })
})
