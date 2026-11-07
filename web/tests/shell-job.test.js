// Q-70 lane C pins (the shell and its tokens): the shell watches the background
// job for every tab (C1/C2), shows it in the masthead (C3), RunSelector's label
// and picker button (C7), and the tab bar's scroll fade (C8).
// Fake clock: timers and Date only, so polling is stepped by hand.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import App from '../src/App.vue'
import RunSelector from '../src/components/RunSelector.vue'
import { POLL_MS, resetSeenJobs, useJob } from '../src/composables/useJob.js'
import { dismissToast, toast } from '../src/toast.js'
import { resetDismissed } from '../src/dismissed.js'
import { fakeApi, runsFrom, setHash } from './helpers.js'

let api
const STARTED = '2026-09-24T08:10:00'
const running = (kind = 'run', id = 1) => ({ id, kind, state: 'running', started_at: STARTED })

function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
  return api
}

beforeEach(() => {
  setHash('#/profile')
  resetSeenJobs()
  resetDismissed()
  dismissToast()
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'Date'] })
  vi.setSystemTime(new Date('2026-09-24T08:14:00Z'))
  useApi()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  dismissToast()
})
enableAutoUnmount(afterEach)

async function settle(times = 3) {
  for (let i = 0; i < times; i++) await flushPromises()
}

async function mountApp() {
  const wrapper = mount(App, { attachTo: document.body })
  await settle()
  return wrapper
}

async function poll() {
  await vi.advanceTimersByTimeAsync(POLL_MS)
  await settle()
}

const shortlists = () => api.count(/^api\/shortlist\?run=all$/)
const runLists = () => api.count(/^api\/runs$/)
const jobPolls = () => api.count(/^api\/jobs\/current/)

// A throwaway "tab" that owns a useJob, to hand the shell a job the way a tab does.
function fakeTab(options = {}) {
  let handle
  const wrapper = mount(defineComponent({
    setup() {
      handle = useJob({ kind: 'run', ...options })
      return () => h('div')
    },
  }))
  return { wrapper, handle }
}

describe('the shell follows the background job for every tab (C2)', () => {
  it('a run that finishes while the owner is on Profile refreshes the Inbox data and says so', async () => {
    useApi({ job: running('run') })
    await mountApp()
    expect(window.location.hash).toBe('#/profile')
    const shortlistsBefore = shortlists()
    const runListsBefore = runLists()
    expect(toast.current).toBeNull()

    api.server.job = { ...running('run'), state: 'succeeded', exit_code: 0, finished_at: STARTED }
    await poll()

    expect(shortlists()).toBe(shortlistsBefore + 1)
    expect(runLists()).toBe(runListsBefore + 1)     // a run adds a row to the run list too
    expect(toast.current.message).toBe('Run finished. New roles are in the Inbox.')
    expect(toast.current.link).toEqual({ label: 'Open Runs', href: '#/runs' })
  })

  it('a failed run says it stopped; a cancelled one says it was cancelled', async () => {
    useApi({ job: running('run', 1) })
    await mountApp()
    api.server.job = { ...running('run', 1), state: 'failed', exit_code: 1 }
    await poll()
    expect(toast.current.message).toBe('The run stopped.')

  })

  it('a cancelled run says it was cancelled', async () => {
    useApi({ job: running('run', 2) })
    await mountApp()
    api.server.job = { ...running('run', 2), state: 'failed', exit_code: -15, reason: 'cancelled' }
    await poll()
    expect(toast.current.message).toBe('The job was cancelled.')
  })

  it('a profile refresh reloads the data but raises no toast', async () => {
    useApi({ job: running('profile') })
    await mountApp()
    const before = shortlists()
    const runsBefore = runLists()

    api.server.job = { ...running('profile'), state: 'succeeded', exit_code: 0 }
    await poll()

    expect(shortlists()).toBe(before + 1)
    expect(runLists()).toBe(runsBefore)             // no new run, so no run-list reload
    expect(toast.current).toBeNull()
  })

  it('does not announce a job it never saw running', async () => {
    useApi({ job: { ...running('run'), state: 'succeeded', exit_code: 0 } })
    await mountApp()
    expect(toast.current).toBeNull()
  })
})

describe('the masthead job pill (C3)', () => {
  it('shows "Run running" with the elapsed time and links to Runs', async () => {
    useApi({ job: running('run') })
    const wrapper = await mountApp()
    const pill = wrapper.find('.masthead .job-pill')
    expect(pill.exists()).toBe(true)
    expect(pill.text()).toContain('Run running')
    expect(pill.text()).toContain('4 min')          // started 08:10, now 08:14
    expect(pill.find('a').attributes('href')).toBe('#/runs')
  })

  it('names a profile refresh as such', async () => {
    useApi({ job: running('profile') })
    const wrapper = await mountApp()
    expect(wrapper.find('.job-pill').text()).toContain('Profile refresh running')
  })

  it('is absent with no job, and goes when the job ends', async () => {
    const wrapper = await mountApp()
    expect(wrapper.find('.job-pill').exists()).toBe(false)

    api.server.job = running('run')
    document.dispatchEvent(new Event('visibilitychange'))
    await settle()
    expect(wrapper.find('.job-pill').exists()).toBe(true)

    api.server.job = { ...running('run'), state: 'succeeded', exit_code: 0 }
    await poll()
    expect(wrapper.find('.job-pill').exists()).toBe(false)
  })
})

describe('the shell hears jobs a tab starts, and a returning page (C1)', () => {
  it('a tab handing over a started job shows the pill without any visibility event', async () => {
    const wrapper = await mountApp()
    const { handle } = fakeTab()
    expect(wrapper.find('.job-pill').exists()).toBe(false)

    handle.track(running('run', 7), { started: true })
    await settle()

    expect(wrapper.find('.job-pill').exists()).toBe(true)
    expect(wrapper.find('.job-pill').text()).toContain('Run running')
  })

  it('a started job that then ends is announced by the shell (follow-up toast)', async () => {
    useApi()
    await mountApp()
    const { handle } = fakeTab()
    handle.track(running('run', 7), { started: true })
    await settle()
    api.server.job = { ...running('run', 7), state: 'succeeded', exit_code: 0 }
    await poll()
    expect(toast.current.message).toBe('Run finished. New roles are in the Inbox.')
  })

  it('the page becoming visible asks the server for the current job; hidden does not', async () => {
    await mountApp()
    const hidden = jobPolls()
    Object.defineProperty(document, 'visibilityState', { value: 'hidden', configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
    await settle()
    expect(jobPolls()).toBe(hidden)

    Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
    document.dispatchEvent(new Event('visibilitychange'))
    await settle()
    expect(jobPolls()).toBe(hidden + 1)
  })
})

describe('useJob consume (C2)', () => {
  it('consume:false still reports an ending to a second watcher of the same kind', async () => {
    const heard = { shell: [], tab: [] }
    const shell = fakeTab({ consume: false, onFinish: j => heard.shell.push(j.id) })
    const tab = fakeTab({ onFinish: j => heard.tab.push(j.id) })

    tab.handle.track(running('run', 3))
    shell.handle.track(running('run', 3))
    const done = { ...running('run', 3), state: 'succeeded', exit_code: 0 }
    shell.handle.track(done)
    tab.handle.track(done)

    expect(heard.shell).toEqual([3])
    expect(heard.tab).toEqual([3])                  // the shell did not take it from the tab
  })

  it('a consuming watcher reports an ending once, however many tabs look', async () => {
    const heard = []
    const one = fakeTab({ onFinish: j => heard.push(['one', j.id]) })
    const two = fakeTab({ onFinish: j => heard.push(['two', j.id]) })
    one.handle.track(running('run', 4))
    const done = { ...running('run', 4), state: 'succeeded', exit_code: 0 }
    one.handle.track(done)
    two.handle.track(done)
    expect(heard).toEqual([['one', 4]])
  })
})

describe('RunSelector (C7)', () => {
  it('the label is tied to the select, so the control has an accessible name', () => {
    const wrapper = mount(RunSelector, { props: { runs: runsFrom(), modelValue: 'all' } })
    const select = wrapper.find('select')
    const label = wrapper.find('label')
    expect(select.attributes('id')).toBeTruthy()
    expect(label.attributes('for')).toBe(select.attributes('id'))
    expect(label.text()).toBe('Runs')
  })

  it('two selectors on one page get different ids', () => {
    const props = { runs: runsFrom(), modelValue: 'all' }
    const wrapper = mount(defineComponent({
      render: () => h('div', [h(RunSelector, props), h(RunSelector, props)]),
    }))
    const [a, b] = wrapper.findAll('select').map(s => s.attributes('id'))
    expect(a).toBeTruthy()
    expect(a).not.toBe(b)
  })

  it('Choose runs… is a button, absent when choosable is false', async () => {
    const wrapper = mount(RunSelector, { props: { runs: runsFrom(), modelValue: 'all' } })
    const button = wrapper.find('button.choose-runs')
    expect(button.attributes('type')).toBe('button')
    await button.trigger('click')
    expect(wrapper.emitted('choose')).toHaveLength(1)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()

    const none = mount(RunSelector, { props: { runs: runsFrom(), modelValue: 'all', choosable: false } })
    expect(none.find('.choose-runs').exists()).toBe(false)
  })
})

describe('the tab bar fades when it scrolls (C8)', () => {
  function mockScroll(el, { scrollWidth, clientWidth }) {
    let left = 0
    Object.defineProperty(el, 'scrollWidth', { value: scrollWidth, configurable: true })
    Object.defineProperty(el, 'clientWidth', { value: clientWidth, configurable: true })
    Object.defineProperty(el, 'scrollLeft', { get: () => left, set: v => { left = v }, configurable: true })
    return v => { left = v }
  }

  it('shows more-right while tabs are hidden to the right, and drops it at the end', async () => {
    const wrapper = await mountApp()
    const list = wrapper.find('.tablist')
    expect(list.classes()).not.toContain('more-right')   // jsdom: nothing overflows

    const scrollTo = mockScroll(list.element, { scrollWidth: 1000, clientWidth: 300 })
    await list.trigger('scroll')
    expect(list.classes()).toContain('more-right')

    scrollTo(300)
    await list.trigger('scroll')
    expect(list.classes()).toContain('more-right')       // still 400px off to the right

    scrollTo(700)
    await list.trigger('scroll')
    expect(list.classes()).not.toContain('more-right')
  })

  it('re-measures on window resize', async () => {
    const wrapper = await mountApp()
    const list = wrapper.find('.tablist')
    mockScroll(list.element, { scrollWidth: 1000, clientWidth: 300 })
    window.dispatchEvent(new Event('resize'))
    await settle()
    expect(list.classes()).toContain('more-right')
  })

  it('no overflow, no fade', async () => {
    const wrapper = await mountApp()
    const list = wrapper.find('.tablist')
    mockScroll(list.element, { scrollWidth: 300, clientWidth: 300 })
    await list.trigger('scroll')
    expect(list.classes()).not.toContain('more-right')
  })
})
