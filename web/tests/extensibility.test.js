// M7-T4 / M12-T1: a tab is one registry entry plus one component. This probe
// adds a tab by changing only the registry - no edit to App.vue - and checks
// the shell gives it everything a built-in tab gets: a place in the tab bar, a
// URL, keyboard reach and the shared dataset. (The on-disk three-file check is
// recorded in the PRD notes for M12-T1.)
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { tabEmits, tabProps } from '../src/shell.js'
import { fakeApi, setHash } from './helpers.js'

const Probe = defineComponent({
  props: tabProps,
  emits: tabEmits,
  setup(props) {
    return () => h('p', { class: 'probe' }, `probe tab · ${props.jobs.length} jobs`)
  },
})

vi.mock('../src/tabs.js', async importOriginal => {
  const { TABS } = await importOriginal()
  return { TABS: [...TABS, { id: 'probe', label: 'Probe', component: async () => Probe }] }
})

const { default: App } = await import('../src/App.vue')

beforeEach(() => {
  vi.stubGlobal('fetch', fakeApi().fetch)
})
afterEach(() => vi.unstubAllGlobals())
enableAutoUnmount(afterEach)

describe('a tab added only in the registry', () => {
  it('appears in the tab bar, owns a URL and gets the shared dataset', async () => {
    setHash('#/probe')
    const wrapper = mount(App, { attachTo: document.body })
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.find('.probe').text()).toBe('probe tab · 3 jobs')
    })
    const labels = wrapper.findAll('[role="tab"] .tab-label').map(t => t.text())
    expect(labels.at(-1)).toBe('Probe')
    expect(wrapper.find('[data-tab="probe"]').attributes('aria-selected')).toBe('true')
    expect(wrapper.find('.probe').attributes('jobs')).toBeUndefined()
  })

  it('is reachable by keyboard like any other tab', async () => {
    setHash('#/inbox')
    const wrapper = mount(App, { attachTo: document.body })
    await flushPromises()
    await wrapper.find('[data-tab="inbox"]').trigger('keydown', { key: 'End' })
    expect(window.location.hash).toBe('#/probe')
  })
})
