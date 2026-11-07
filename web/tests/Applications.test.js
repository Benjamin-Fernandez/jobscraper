import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import Applications from '../src/tabs/Applications.vue'
import App from '../src/App.vue'
import { statusLabel } from '../src/stages.js'
import { dismissToast } from '../src/toast.js'
import { fakeApi, runsFrom, setHash } from './helpers.js'

let api

async function mountTab(statuses, vocabulary) {
  api = fakeApi({ statuses, vocabulary })
  vi.stubGlobal('fetch', api.fetch)
  const wrapper = mount(Applications, { props: { run: 12, runs: runsFrom(), jobs: [] } })
  await flushPromises()
  return wrapper
}

const row = (w, jobId) => w.find(`.app-row[data-job="${jobId}"]`)
const groupNames = w => w.findAll('.company-group .group-name').map(g => g.text())
const stageButton = (w, id) => w.find(`.stage[data-status="${id}"]`)

afterEach(() => vi.unstubAllGlobals())

describe('Applications tab', () => {
  it('groups applications by company, A to Z', async () => {
    const wrapper = await mountTab({ m4n5o6: 'rejected', a1b2c3: 'applied', j1k2l3: 'interviewing', g7h8i9: 'to_apply' })
    expect(groupNames(wrapper)).toEqual(['Grab', 'OKX', 'Shopee', 'Stripe'])
    const okx = wrapper.find('.company-group[data-company="OKX"]')
    expect(okx.find('.group-n').text()).toBe('1 role')
    expect(okx.find('.mark').text()).toBe('OK')
    expect(okx.find('.role-title').text()).toBe('DevOps / Site Reliability Engineer')
    expect(wrapper.find('.count').text()).toBe('4 applications at 4 companies')
  })

  it('two roles at one company sit in one group, ordered by stage', async () => {
    // Re-badge Stripe's posting as another OKX role, to get two in one company.
    api = fakeApi({ statuses: { a1b2c3: 'interviewing', m4n5o6: 'to_apply' } })
    const real = api.fetch
    vi.stubGlobal('fetch', vi.fn(async (url, init) => {
      const res = await real(url, init)
      if (url !== 'api/applications') return res
      const body = await res.json()
      return { ...res, json: async () => body.map(r => (r.job_id === 'm4n5o6' ? { ...r, company: 'OKX' } : r)) }
    }))
    const wrapper = mount(Applications, { props: { run: 12, jobs: [] } })
    await flushPromises()
    expect(groupNames(wrapper)).toEqual(['OKX'])
    const roles = wrapper.findAll('.company-group .app-row').map(r => r.attributes('data-status'))
    expect(roles).toEqual(['to_apply', 'interviewing'])     // config order: saved before interviewing
    expect(wrapper.find('.group-n').text()).toBe('2 roles')
  })

  it('the stage strip counts each stage and filters to it', async () => {
    const wrapper = await mountTab({ m4n5o6: 'rejected', a1b2c3: 'applied', j1k2l3: 'applied', g7h8i9: 'to_apply' })
    const strip = wrapper.findAll('.stage').map(s => [s.find('.stage-label').text(), s.find('.stage-n').text()])
    expect(strip).toEqual([
      ['All', '4'], ['Saved', '1'], ['Applied', '2'], ['Interviewing', '0'],
      ['Offer', '0'], ['Rejected', '1'], ['Withdrawn', '0'],
    ])
    expect(stageButton(wrapper, 'all').attributes('aria-pressed')).toBe('true')

    await stageButton(wrapper, 'applied').trigger('click')
    expect(stageButton(wrapper, 'applied').attributes('aria-pressed')).toBe('true')
    expect(groupNames(wrapper)).toEqual(['Grab', 'OKX'])

    await stageButton(wrapper, 'interviewing').trigger('click')
    expect(wrapper.text()).toContain('Nothing here')
  })

  it('search narrows by company or role', async () => {
    const wrapper = await mountTab({ a1b2c3: 'applied', j1k2l3: 'applied', m4n5o6: 'offer' })
    await wrapper.find('input[type="search"]').setValue('payments')
    expect(groupNames(wrapper)).toEqual(['Stripe'])
    await wrapper.find('input[type="search"]').setValue('grab')
    expect(groupNames(wrapper)).toEqual(['Grab'])
    expect(stageButton(wrapper, 'all').find('.stage-n').text()).toBe('1')
  })

  it('offers exactly the statuses config serves, written for people', async () => {
    const wrapper = await mountTab({ a1b2c3: 'applied' })
    const select = row(wrapper, 'a1b2c3').find('select')
    expect(select.findAll('option').map(o => o.attributes('value')))
      .toEqual(['to_apply', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn'])
    expect(select.findAll('option').map(o => o.text()))
      .toEqual(['Saved', 'Applied', 'Interviewing', 'Offer', 'Rejected', 'Withdrawn'])
    expect(select.element.value).toBe('applied')
  })

  it('a status added to config (on_hold) is offered, labelled and counted with no code change', async () => {
    const vocabulary = ['to_apply', 'applied', 'interviewing', 'on_hold', 'offer', 'rejected', 'withdrawn']
    const wrapper = await mountTab({ a1b2c3: 'applied' }, vocabulary)
    expect(row(wrapper, 'a1b2c3').findAll('option').map(o => o.attributes('value'))).toEqual(vocabulary)

    await row(wrapper, 'a1b2c3').find('select').setValue('on_hold')
    await flushPromises()
    const post = api.calls.find(c => c.method === 'POST')
    expect(JSON.parse(post.body).status).toBe('on_hold')
    expect(row(wrapper, 'a1b2c3').attributes('data-status')).toBe('on_hold')
    expect(stageButton(wrapper, 'on_hold').text()).toContain('On hold')
    expect(stageButton(wrapper, 'on_hold').find('.stage-n').text()).toBe('1')
  })

  it('advancing applied -> interviewing keeps both events, in order', async () => {
    const wrapper = await mountTab({ a1b2c3: 'applied' })
    await row(wrapper, 'a1b2c3').find('select').setValue('interviewing')
    await flushPromises()

    const post = api.calls.find(c => c.method === 'POST')
    expect(post.url).toBe('api/applications/a1b2c3')
    expect(JSON.parse(post.body).status).toBe('interviewing')

    const moved = row(wrapper, 'a1b2c3')
    expect(moved.attributes('data-status')).toBe('interviewing')
    expect(moved.find('.history summary').text()).toContain('2')
    const steps = moved.findAll('.timeline li .to').map(s => s.text())
    expect(steps).toEqual(['Applied', 'Interviewing'])
    expect(moved.find('.timeline .at').text()).toMatch(/^24 Sep \d\d:\d\d UTC$/)
    expect(moved.find('.updated').text()).toBe('Interviewing 24 Sep')
    expect(wrapper.emitted('changed')).toHaveLength(1)
  })

  it('says so when nothing is tracked yet', async () => {
    const wrapper = await mountTab({})
    expect(wrapper.text()).toContain('Nothing tracked yet')
    expect(wrapper.find('.stages').exists()).toBe(false)
    expect(wrapper.findAll('.company-group')).toHaveLength(0)
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

  it('shows every run by default and can be narrowed to the past week or month', async () => {
    api = fakeApi({ statuses: { a1b2c3: 'applied', j1k2l3: 'interviewing' } })
    vi.stubGlobal('fetch', api.fetch)
    // Run 12 finished two days ago, run 11 twenty days ago (relative to now:
    // this tab filters on the client, by the runs' finish times).
    const ago = days => new Date(Date.now() - days * 86400000).toISOString().slice(0, 19)
    const runs = [{ run_no: 12, finished_at: ago(2), accepted: 3 }, { run_no: 11, finished_at: ago(20), accepted: 2 }]
    const wrapper = mount(Applications, { props: { run: 'all', runs, jobs: [] } })
    await flushPromises()
    // Applications outlive their run: all of them by default, and no picker.
    expect(wrapper.find('.run-selector select').element.value).toBe('all')
    expect(wrapper.find('.run-selector option[value="choose"]').exists()).toBe(false)
    expect(row(wrapper, 'a1b2c3').exists()).toBe(true)
    expect(row(wrapper, 'j1k2l3').exists()).toBe(true)

    await wrapper.find('.run-selector select').setValue('week')
    expect(row(wrapper, 'a1b2c3').exists()).toBe(true)
    expect(row(wrapper, 'j1k2l3').exists()).toBe(false)
    await wrapper.find('.run-selector select').setValue('month')
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

  it('marking applied in the Inbox moves the role to this tab', async () => {
    setHash('')
    dismissToast()
    api = fakeApi()
    vi.stubGlobal('fetch', api.fetch)
    const wrapper = mount(App)
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.findAll('.inbox .card').length).toBe(5)
    })
    await wrapper.find('.inbox .card[data-job="a1b2c3"] .card-hit').trigger('click')
    await wrapper.find('.inbox .detail button.apply').trigger('click')
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.findAll('.inbox .card').length).toBe(4)
    })
    expect(wrapper.find('.toast').text()).toContain('Marked applied')

    const tab = wrapper.findAll('[role="tab"]').find(b => b.find('.tab-label').text() === 'Applications')
    await tab.trigger('click')
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.find('.app-row[data-job="a1b2c3"]').exists()).toBe(true)
    })
    expect(wrapper.find('.app-row[data-job="a1b2c3"] select').element.value).toBe('applied')
    expect(wrapper.find('.company-group[data-company="OKX"]').exists()).toBe(true)
  })
})

describe('stage labels', () => {
  it('writes known statuses for people and derives the rest', () => {
    expect(statusLabel('to_apply')).toBe('Saved')
    expect(statusLabel('interviewing')).toBe('Interviewing')
    expect(statusLabel('on_hold')).toBe('On hold')
    expect(statusLabel('')).toBe('')
  })
})
