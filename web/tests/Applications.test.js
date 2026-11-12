import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import Applications from '../src/tabs/Applications.vue'
import App from '../src/App.vue'
import { statusLabel } from '../src/stages.js'
import { dismissToast } from '../src/toast.js'
import { fakeApi, pinZone, runsFrom, setHash } from './helpers.js'

pinZone()   // Q-75 G18: times show in the browser's zone; pin it (UTC+8) so the suite is machine-independent

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

beforeEach(() => { window.localStorage.clear() })
afterEach(() => vi.unstubAllGlobals())
// Q-118 LB: a mounted tab listens to hashchange (a bare #/applications goes to its last
// tab), so a tab left mounted by an earlier test would steer a later one's hash.
enableAutoUnmount(afterEach)

describe('Applications tab', () => {
  it('groups applications by company, A to Z', async () => {
    const wrapper = await mountTab({ m4n5o6: 'rejected', a1b2c3: 'applied', j1k2l3: 'interviewing', g7h8i9: 'to_apply' })
    // Q-118 LB (D-207): All is the first-visit tab, so the rejected role shows too.
    expect(stageButton(wrapper, 'all').attributes('aria-pressed')).toBe('true')
    expect(groupNames(wrapper)).toEqual(['Grab', 'OKX', 'Shopee', 'Stripe'])
    const okx = wrapper.find('.company-group[data-company="OKX"]')
    expect(okx.find('.group-n').text()).toBe('1 role')
    expect(okx.find('.mark').text()).toBe('OK')
    expect(okx.find('.role-title').text()).toBe('DevOps / Site Reliability Engineer')
    // The page sub counts the whole data set: active (not rejected/withdrawn) of tracked.
    expect(wrapper.find('.count').text()).toBe('3 active · 4 tracked at 4 companies')
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
    // Q-118 LB (D-207): All, Active, then the four stages; no Saved/Withdrawn tab.
    expect(strip).toEqual([
      ['All', '4'], ['Active', '3'], ['Applied', '2'], ['Interviewing', '0'],
      ['Offer', '0'], ['Rejected', '1'],
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

  // Q-118 LB (D-207): the move targets are the four stages, not every config status;
  // the menu is named for its row and the current stage is checked (and not offered).
  it('the Move menu offers the four stages, written for people, the current one checked', async () => {
    const wrapper = await mountTab({ a1b2c3: 'applied' })
    const trigger = row(wrapper, 'a1b2c3').find('.ui-move-trigger')
    expect(trigger.find('.pill').text()).toBe('Applied')
    expect(trigger.attributes('aria-label')).toBe('Move DevOps / Site Reliability Engineer at OKX, now Applied')
    await trigger.trigger('click')
    const items = row(wrapper, 'a1b2c3').findAll('[role="menuitemradio"]')
    expect(items.map(o => o.text().trim())).toEqual(['Applied', 'Interviewing', 'Offer', 'Rejected'])
    expect(items.map(o => o.attributes('aria-checked'))).toEqual(['true', 'false', 'false', 'false'])
    expect(items[0].attributes('disabled')).toBeDefined()
  })

  // D-207 dropped the config-driven strip and select: a status config adds later is not a
  // tab or a move target any more. What stays (no code change needed): the row still
  // shows, wears its own word, and counts under All and Active.
  it('a status added to config (on_hold) still shows, labelled, under All and Active', async () => {
    const vocabulary = ['to_apply', 'applied', 'interviewing', 'on_hold', 'offer', 'rejected', 'withdrawn']
    const wrapper = await mountTab({ a1b2c3: 'on_hold', j1k2l3: 'applied' }, vocabulary)
    expect(row(wrapper, 'a1b2c3').attributes('data-status')).toBe('on_hold')
    expect(row(wrapper, 'a1b2c3').find('.ui-move-trigger .pill').text()).toBe('On hold')
    expect(stageButton(wrapper, 'on_hold').exists()).toBe(false)
    expect(stageButton(wrapper, 'all').find('.stage-n').text()).toBe('2')
    expect(stageButton(wrapper, 'active').find('.stage-n').text()).toBe('2')
    await stageButton(wrapper, 'active').trigger('click')
    expect(row(wrapper, 'a1b2c3').exists()).toBe(true)
    await stageButton(wrapper, 'applied').trigger('click')
    expect(row(wrapper, 'a1b2c3').exists()).toBe(false)
  })

  it('advancing applied -> interviewing keeps both events, in order', async () => {
    const wrapper = await mountTab({ a1b2c3: 'applied' })
    await row(wrapper, 'a1b2c3').find('.ui-move-trigger').trigger('click')
    await row(wrapper, 'a1b2c3').findAll('[role="menuitemradio"]').find(b => b.text().trim() === 'Interviewing').trigger('click')
    await flushPromises()

    const post = api.calls.find(c => c.method === 'POST')
    expect(post.url).toBe('api/applications/a1b2c3')
    expect(JSON.parse(post.body).status).toBe('interviewing')

    const moved = row(wrapper, 'a1b2c3')
    expect(moved.attributes('data-status')).toBe('interviewing')
    expect(moved.find('.history summary').text()).toContain('2')
    const steps = moved.findAll('.timeline li .to').map(s => s.text())
    expect(steps).toEqual(['Applied', 'Interviewing'])
    // Stored 2026-09-24T08:10 UTC; shown in the (pinned) local zone, exact UTC original in the tooltip.
    expect(moved.find('.timeline .at').text()).toBe('24 Sep 16:10')
    expect(moved.find('.timeline .at').attributes('title')).toBe('2026-09-24 08:10 UTC')
    expect(moved.find('.updated').text()).toMatch(/^Interviewing · \d+ days$/)
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
    setHash('#/inbox')
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
    expect(wrapper.find('.app-row[data-job="a1b2c3"]').attributes('data-status')).toBe('applied')
    expect(wrapper.find('.app-row[data-job="a1b2c3"] .ui-move-trigger .pill').text()).toBe('Applied')
    expect(wrapper.find('.company-group[data-company="OKX"]').exists()).toBe(true)
  })
})

describe('stage labels', () => {
  it('writes known statuses for people and derives the rest', () => {
    expect(statusLabel('to_apply')).toBe('To apply')   // Q-118 D-207: was "Saved"
    expect(statusLabel('interviewing')).toBe('Interviewing')
    expect(statusLabel('on_hold')).toBe('On hold')
    expect(statusLabel('')).toBe('')
  })
})
