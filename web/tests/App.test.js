import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import App from '../src/App.vue'
import RunSelector from '../src/components/RunSelector.vue'
import { TABS } from '../src/tabs.js'
import { fakeApi, runsFrom } from './helpers.js'

let api

beforeEach(() => {
  api = fakeApi()
  vi.stubGlobal('fetch', api.fetch)
})
afterEach(() => vi.unstubAllGlobals())

async function mountApp() {
  const wrapper = mount(App)
  await vi.waitFor(async () => {
    await flushPromises()
    expect(wrapper.findAll('.inbox').length).toBe(1)
  })
  return wrapper
}

describe('App shell', () => {
  it('renders the page heading', () => {
    expect(mount(App).find('h1').text()).toBe('JobScraper')
  })

  it('renders one tab button per TABS entry', async () => {
    const wrapper = await mountApp()
    const labels = wrapper.findAll('[role="tab"]').map(b => b.text())
    expect(labels).toEqual(TABS.map(t => t.label))
  })

  it('opens on the newest run', async () => {
    const wrapper = await mountApp()
    expect(api.calls.map(c => c.url)).toEqual(['api/runs', 'api/shortlist?run=12'])
    expect(wrapper.find('select').element.value).toBe('12')
    expect(wrapper.text()).toContain('OKX')
    expect(wrapper.text()).not.toContain('Grab')
  })

  it('changing the run issues exactly one shortlist request and navigates nowhere', async () => {
    const wrapper = await mountApp()
    const before = window.location.href
    const callsBefore = api.calls.length

    await wrapper.find('select').setValue('11')
    await flushPromises()

    const made = api.calls.slice(callsBefore).map(c => c.url)
    expect(made).toEqual(['api/shortlist?run=11'])
    expect(window.location.href).toBe(before)
    expect(wrapper.text()).toContain('Grab')
    expect(wrapper.text()).not.toContain('OKX')
  })

  it('the "all runs" option asks for run=all', async () => {
    const wrapper = await mountApp()
    await wrapper.find('select').setValue('all')
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
})
