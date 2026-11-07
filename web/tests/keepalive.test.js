// Q-70 C4 (G15): the shell keeps Inbox and Applications alive while another tab
// is open, so the owner's place (search text, scroll, focus) survives a detour.
// Every other tab is built fresh each visit.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import App from '../src/App.vue'
import { resetDismissed } from '../src/dismissed.js'
import { fakeApi, setHash } from './helpers.js'

let api

beforeEach(() => {
  setHash('#/inbox')
  resetDismissed()
  api = fakeApi()
  vi.stubGlobal('fetch', api.fetch)
})
afterEach(() => vi.unstubAllGlobals())
enableAutoUnmount(afterEach)

async function mountApp() {
  const wrapper = mount(App, { attachTo: document.body })
  await vi.waitFor(async () => {
    await flushPromises()
    expect(wrapper.findAll('.inbox .card').length).toBeGreaterThan(0)
  })
  return wrapper
}

// Click a tab and wait for its root element (the hash change drives the shell).
async function goto(wrapper, id, selector) {
  await wrapper.find(`[role="tab"][data-tab="${id}"]`).trigger('click')
  await vi.waitFor(async () => {
    await flushPromises()
    expect(wrapper.find(selector).exists()).toBe(true)
  })
}

const fetched = pattern => api.count(pattern)

describe('tabs kept alive across a detour (Q-70 C4)', () => {
  it('Inbox → Profile → Inbox keeps the Inbox as it was, without refetching its data', async () => {
    const wrapper = await mountApp()
    const search = wrapper.find('.inbox input[type="search"]')
    await search.setValue('okx')
    const inbox = wrapper.find('.inbox').element
    const shortlistsBefore = fetched(/^api\/shortlist/)
    const statsBefore = fetched(/^api\/stats$/)

    await goto(wrapper, 'profile', '.profile-tab')
    expect(wrapper.find('.inbox').exists()).toBe(false)     // not on screen while away
    await goto(wrapper, 'inbox', '.inbox')

    expect(wrapper.find('.inbox').element).toBe(inbox)       // the same element, not a rebuild
    expect(wrapper.find('.inbox input[type="search"]').element.value).toBe('okx')
    expect(wrapper.findAll('.inbox .card').length).toBeGreaterThan(0)
    expect(fetched(/^api\/shortlist/)).toBe(shortlistsBefore)
    expect(fetched(/^api\/stats$/)).toBe(statsBefore)
  })

  it('Applications is kept too, and refreshes its list when it comes back', async () => {
    setHash('#/applications')
    const wrapper = mount(App, { attachTo: document.body })
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.find('.applications').exists()).toBe(true)
    })
    const applications = wrapper.find('.applications').element
    const loadsBefore = fetched(/^api\/applications$/)

    await goto(wrapper, 'profile', '.profile-tab')
    await goto(wrapper, 'applications', '.applications')

    expect(wrapper.find('.applications').element).toBe(applications)
    await vi.waitFor(() => expect(fetched(/^api\/applications$/)).toBe(loadsBefore + 1))
  })

  it('Profile is not kept alive: each visit builds it fresh', async () => {
    const wrapper = await mountApp()
    await goto(wrapper, 'profile', '.profile-tab')
    const first = wrapper.find('.profile-tab').element
    const profileLoads = fetched(/^api\/profile$/)
    expect(profileLoads).toBeGreaterThan(0)

    await goto(wrapper, 'inbox', '.inbox')
    await goto(wrapper, 'profile', '.profile-tab')

    expect(wrapper.find('.profile-tab').element).not.toBe(first)
    expect(fetched(/^api\/profile$/)).toBeGreaterThan(profileLoads)
  })

  it('a kept-alive Inbox does not answer its keys while another tab is open, and does again on return', async () => {
    const wrapper = await mountApp()
    const key = k => document.body.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true }))
    const writes = () => api.calls.filter(c => c.method === 'POST' && c.url.startsWith('api/applications/')).length

    await goto(wrapper, 'profile', '.profile-tab')
    key('a')                                       // "mark applied" in the Inbox
    await flushPromises()
    expect(writes()).toBe(0)

    await goto(wrapper, 'inbox', '.inbox')
    key('a')
    await vi.waitFor(() => expect(writes()).toBe(1))
  })
})
