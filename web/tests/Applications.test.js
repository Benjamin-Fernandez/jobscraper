import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import Applications from '../src/tabs/Applications.vue'
import App from '../src/App.vue'
import { fakeApi, runsFrom, setHash } from './helpers.js'

let api

async function mountTab(statuses, vocabulary) {
  api = fakeApi({ statuses, vocabulary })
  vi.stubGlobal('fetch', api.fetch)
  const wrapper = mount(Applications, { props: { run: 12, jobs: [] } })
  await flushPromises()
  return wrapper
}

function row(wrapper, jobId) {
  return wrapper.find(`tr[data-job="${jobId}"]`)
}

afterEach(() => vi.unstubAllGlobals())

describe('Applications tab', () => {
  it('groups rows by status, in the configured order', async () => {
    const wrapper = await mountTab({ m4n5o6: 'rejected', a1b2c3: 'applied', j1k2l3: 'interviewing' })
    const groups = wrapper.findAll('.group').map(g => g.attributes('data-status'))
    expect(groups).toEqual(['applied', 'interviewing', 'rejected'])
    expect(wrapper.find('.group[data-status="applied"]').text()).toContain('OKX')
  })

  it('offers exactly the statuses config serves, not a hardcoded list', async () => {
    const wrapper = await mountTab({ a1b2c3: 'applied' })
    const options = row(wrapper, 'a1b2c3').findAll('option').map(o => o.text())
    expect(options).toEqual(['to_apply', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn'])
    expect(row(wrapper, 'a1b2c3').find('select').element.value).toBe('applied')
  })

  it('a status added to config (on_hold) is offered and grouped with no code change', async () => {
    const vocabulary = ['to_apply', 'applied', 'interviewing', 'on_hold', 'offer', 'rejected', 'withdrawn']
    const wrapper = await mountTab({ a1b2c3: 'applied' }, vocabulary)
    const options = row(wrapper, 'a1b2c3').findAll('option').map(o => o.text())
    expect(options).toEqual(vocabulary)

    await row(wrapper, 'a1b2c3').find('select').setValue('on_hold')
    await flushPromises()
    const post = api.calls.find(c => c.method === 'POST')
    expect(JSON.parse(post.body).status).toBe('on_hold')
    expect(row(wrapper, 'a1b2c3').element.closest('.group').dataset.status).toBe('on_hold')
  })

  it('advancing applied -> interviewing shows both events, in order', async () => {
    const wrapper = await mountTab({ a1b2c3: 'applied' })
    await row(wrapper, 'a1b2c3').find('select').setValue('interviewing')
    await flushPromises()

    const post = api.calls.find(c => c.method === 'POST')
    expect(post.url).toBe('api/applications/a1b2c3')
    expect(JSON.parse(post.body).status).toBe('interviewing')

    const moved = row(wrapper, 'a1b2c3')
    expect(moved.element.closest('.group').dataset.status).toBe('interviewing')
    const steps = moved.findAll('.timeline li .to').map(s => s.text())
    expect(steps).toEqual(['applied', 'interviewing'])
    expect(moved.find('.timeline .at').text()).toMatch(/^24 Sep \d\d:\d\d UTC$/)
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('says so when nothing is tracked yet', async () => {
    const wrapper = await mountTab({})
    expect(wrapper.text()).toContain('Nothing tracked yet')
    expect(wrapper.findAll('.group')).toHaveLength(0)
  })

  it('reports a failed load instead of showing an empty list', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false, status: 500, statusText: 'Internal Server Error', json: async () => ({}),
    })))
    const wrapper = mount(Applications, { props: { run: 12, jobs: [] } })
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('500')
    expect(wrapper.text()).not.toContain('Nothing tracked yet')
  })

  it('shows every run by default and can be narrowed to one run', async () => {
    api = fakeApi({ statuses: { a1b2c3: 'applied', j1k2l3: 'interviewing' } })
    vi.stubGlobal('fetch', api.fetch)
    const wrapper = mount(Applications, { props: { run: 12, runs: runsFrom(), jobs: [] } })
    await flushPromises()
    // The Inbox is on run 12, but applications outlive their run.
    expect(wrapper.find('.run-selector select').element.value).toBe('all')
    expect(row(wrapper, 'a1b2c3').exists()).toBe(true)
    expect(row(wrapper, 'j1k2l3').exists()).toBe(true)

    await wrapper.find('.run-selector select').setValue('11')
    expect(row(wrapper, 'a1b2c3').exists()).toBe(false)
    expect(row(wrapper, 'j1k2l3').exists()).toBe(true)
    expect(wrapper.emitted('select-run')).toBeUndefined()
  })

  it('shows a loading placeholder until the data arrives', async () => {
    api = fakeApi()
    vi.stubGlobal('fetch', api.fetch)
    const wrapper = mount(Applications, { props: { run: 12, jobs: [] } })
    expect(wrapper.find('[role="status"][aria-busy="true"]').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('Nothing tracked yet')
    await flushPromises()
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })

  it('a status set in the Inbox is on the Applications tab when you switch to it', async () => {
    setHash('')
    api = fakeApi()
    vi.stubGlobal('fetch', api.fetch)
    const wrapper = mount(App)
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.findAll('.inbox .card').length).toBe(3)
    })
    await wrapper.find('.inbox .card button.apply').trigger('click')
    await flushPromises()

    const tab = wrapper.findAll('[role="tab"]').find(b => b.find('.tab-label').text() === 'Applications')
    await tab.trigger('click')
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.find('tr[data-job="a1b2c3"]').exists()).toBe(true)
    })
    expect(wrapper.find('tr[data-job="a1b2c3"] select').element.value).toBe('applied')
  })
})
