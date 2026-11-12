// Q-118 LC and LB pins (design sections 3, 4, 7, 8, 10): the Runs start card and history
// selection, and the Applications stage tabs, Move to, drag and drop, and in-flight rows.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import Runs from '../src/tabs/Runs.vue'
import Applications from '../src/tabs/Applications.vue'
import { STAGE_KEY } from '../src/applications.js'
import { dismissToast, toast } from '../src/toast.js'
import { fakeApi, runsFrom, setHash } from './helpers.js'

let api
function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
  return api
}

beforeEach(() => {
  window.localStorage.clear()
  setHash('')
  dismissToast()
})
afterEach(() => {
  vi.unstubAllGlobals()
  dismissToast()
  setHash('')
  document.body.innerHTML = ''
})
enableAutoUnmount(afterEach)

// ---------------------------------------------------------------- Runs (LC)

describe('Runs: the start card (Q-118 LC)', () => {
  it('the count is a segmented control; Custom reveals a labelled field; the button carries the count', async () => {
    useApi()
    const w = mount(Runs, { props: { runs: runsFrom() }, attachTo: document.body })
    await flushPromises()
    await w.find('[data-preset="30"]').trigger('click')
    expect(w.find('[data-preset="30"]').attributes('aria-pressed')).toBe('true')
    expect(w.find('#run-batch').exists()).toBe(false)                 // a preset: no field
    expect(w.find('button.start-run').text()).toBe('Check 30 companies')

    const custom = w.find('[data-preset="custom"]')
    expect(custom.text()).toBe('Custom')
    await custom.trigger('click')
    await flushPromises()
    const field = w.find('#run-batch')
    expect(field.exists()).toBe(true)
    expect(w.find('label[for="run-batch"]').text()).toBe('Number of companies')
    expect(document.activeElement).toBe(field.element)
    await field.setValue('42')
    expect(w.find('button.start-run').text()).toBe('Check 42 companies')
    expect(w.find('#run-batch-hint').text()).toContain('42 of 224 companies')
  })
})

describe('Runs: history selection (Q-118 LC)', () => {
  const RUNS = [14, 13, 12, 11].map(n => ({
    run_no: n, started_at: '2026-09-23T14:00:00', finished_at: '2026-09-23T14:10:00', status: 'ok',
    accepted: { 14: 2, 13: 0, 12: 3, 11: 1 }[n],
  }))
  const box = (w, n) => w.find(`tr[data-run="${n}"] td.col-select input[type="checkbox"]`)
  const header = w => w.find('thead th.col-select input[type="checkbox"]')

  it('Shift-click selects a range (0-match rows skipped); the header box goes indeterminate, then checked', async () => {
    useApi()
    const w = mount(Runs, { props: { runs: RUNS }, attachTo: document.body })
    await flushPromises()
    expect(w.find('thead th.col-select').text()).toBe('Select every run with matches')
    expect(w.find('.ui-bulkbar').exists()).toBe(false)                // nothing selected: no bar

    await box(w, 14).setValue(true)
    expect(header(w).element.indeterminate).toBe(true)
    expect(header(w).element.checked).toBe(false)
    expect(w.find('.ui-bulkbar').text()).toContain('1 run selected · 2 matches')

    await box(w, 11).trigger('click', { shiftKey: true })
    await box(w, 11).setValue(true)
    expect([14, 13, 12, 11].map(n => w.find(`tr[data-run="${n}"]`).attributes('aria-selected')))
      .toEqual(['true', 'false', 'true', 'true'])
    expect(header(w).element.indeterminate).toBe(false)
    expect(header(w).element.checked).toBe(true)
    expect(w.find('.ui-bulkbar').text()).toContain('3 runs selected · 6 matches')

    await w.find('button.clear-picked').trigger('click')
    await flushPromises()
    expect(w.find('.ui-bulkbar').exists()).toBe(false)
    expect(document.activeElement).toBe(box(w, 14).element)          // the first enabled row box
    await header(w).setValue(true)                                     // the header selects every run with matches
    expect(w.find('.ui-bulkbar').text()).toContain('3 runs selected')
  })
})

// ---------------------------------------------------------------- Applications (LB)

async function mountApps(statuses, options = {}) {
  useApi({ statuses, ...options })
  const w = mount(Applications, { props: { run: 12, runs: runsFrom(), jobs: [] }, attachTo: document.body })
  await flushPromises()
  return w
}
const row = (w, id) => w.find(`.app-row[data-job="${id}"]`)
const tab = (w, id) => w.find(`.stage[data-status="${id}"]`)
const posts = () => api.calls.filter(c => c.method === 'POST')
const live = w => w.find('p.app-live[aria-live="polite"]').text()

describe('Applications: stage tabs (Q-118 LB, D-207)', () => {
  it('All, Active, Applied, Interviewing, Offer, Rejected; folded statuses keep their own word', async () => {
    const w = await mountApps({ a1b2c3: 'to_apply', j1k2l3: 'assessment', m4n5o6: 'withdrawn', g7h8i9: 'applied' })
    expect(w.findAll('.stage').map(s => s.attributes('data-status')))
      .toEqual(['all', 'active', 'applied', 'interviewing', 'offer', 'rejected'])
    expect(w.findAll('.stage .stage-label').map(s => s.text()))
      .toEqual(['All', 'Active', 'Applied', 'Interviewing', 'Offer', 'Rejected'])
    for (const gone of ['to_apply', 'assessment', 'withdrawn']) expect(tab(w, gone).exists(), gone).toBe(false)
    const shows = () => ['a1b2c3', 'j1k2l3', 'm4n5o6', 'g7h8i9'].filter(id => row(w, id).exists())
    expect(shows()).toEqual(['a1b2c3', 'j1k2l3', 'm4n5o6', 'g7h8i9'])        // All
    await tab(w, 'active').trigger('click')
    expect(shows()).toEqual(['a1b2c3', 'j1k2l3', 'g7h8i9'])
    await tab(w, 'interviewing').trigger('click')
    expect(shows()).toEqual(['j1k2l3'])
    expect(row(w, 'j1k2l3').find('.ui-move-trigger .pill').text()).toBe('Assessment')
    await tab(w, 'rejected').trigger('click')
    expect(shows()).toEqual(['m4n5o6'])
    expect(row(w, 'm4n5o6').find('.ui-move-trigger .pill').text()).toBe('Withdrawn')
    await tab(w, 'all').trigger('click')
    expect(row(w, 'a1b2c3').find('.ui-move-trigger .pill').text()).toBe('To apply')
  })

  it('the stage is in the hash and remembered; an unknown stage opens All', async () => {
    setHash('#/applications/offer')
    let w = await mountApps({ a1b2c3: 'applied' })
    expect(tab(w, 'offer').attributes('aria-pressed')).toBe('true')
    await tab(w, 'interviewing').trigger('click')
    expect(window.location.hash).toBe('#/applications/interviewing')
    expect(window.localStorage.getItem(STAGE_KEY)).toBe('interviewing')
    w.unmount()

    setHash('#/applications')
    w = await mountApps({ a1b2c3: 'applied' })
    expect(tab(w, 'interviewing').attributes('aria-pressed')).toBe('true')   // remembered
    w.unmount()

    setHash('#/applications/bogus')
    w = await mountApps({ a1b2c3: 'applied' })
    expect(tab(w, 'all').attributes('aria-pressed')).toBe('true')
    expect(window.location.hash).toBe('#/applications/all')
  })
})

describe('Applications: Move to and drag and drop (Q-118 LB)', () => {
  it('Move to changes the status once, toasts with Undo and announces old and new', async () => {
    const w = await mountApps({ a1b2c3: 'applied' })
    await row(w, 'a1b2c3').find('.ui-move-trigger').trigger('click')
    await row(w, 'a1b2c3').findAll('[role="menuitemradio"]').find(b => b.text().trim() === 'Offer').trigger('click')
    await flushPromises()
    expect(posts()).toHaveLength(1)
    expect(JSON.parse(posts()[0].body).status).toBe('offer')
    expect(toast.current.message).toBe('Moved to Offer: DevOps / Site Reliability Engineer')
    expect(toast.current.action.label).toBe('Undo')
    expect(live(w)).toBe('DevOps / Site Reliability Engineer at OKX moved from Applied to Offer.')
  })

  it('a drop on a stage tab moves the row once and announces it; its own stage and All refuse it', async () => {
    const w = await mountApps({ a1b2c3: 'applied' })
    const dataTransfer = { setData() {}, getData() { return '' } }
    const r = row(w, 'a1b2c3')
    expect(r.attributes('draggable')).toBe('true')
    await r.trigger('dragstart', { dataTransfer })
    await flushPromises()
    expect(live(w)).toBe('Dragging DevOps / Site Reliability Engineer. Drop it on a stage tab.')
    expect(['all', 'active', 'applied', 'interviewing', 'offer', 'rejected'].map(s => tab(w, s).attributes('data-drop')))
      .toEqual(['no', 'no', 'no', 'ok', 'ok', 'ok'])
    // The row's own stage does nothing.
    await tab(w, 'applied').trigger('drop', { dataTransfer })
    await flushPromises()
    expect(posts()).toHaveLength(0)

    await r.trigger('dragstart', { dataTransfer })
    await tab(w, 'interviewing').trigger('dragover', { dataTransfer })
    expect(tab(w, 'interviewing').attributes('data-drop')).toBe('over')
    await tab(w, 'interviewing').trigger('drop', { dataTransfer })
    await flushPromises()
    expect(posts()).toHaveLength(1)
    expect(JSON.parse(posts()[0].body).status).toBe('interviewing')
    expect(live(w)).toBe('DevOps / Site Reliability Engineer at OKX moved from Applied to Interviewing.')

    await row(w, 'a1b2c3').trigger('dragstart', { dataTransfer })
    await row(w, 'a1b2c3').trigger('dragend', { dataTransfer })
    await flushPromises()
    expect(live(w)).toBe('Drop cancelled.')
    expect(posts()).toHaveLength(1)
  })

  it('an in-flight row is not draggable and its menu says why; a sent applied row reads "Applied automatically"', async () => {
    const attempt = kind => ({ id: 1, mode: 'auto', state: kind === 'running' ? 'filling' : 'succeeded', kind, text: '', hint: '', queued_at: '2026-11-02T01:00:00' })
    const w = await mountApps({ a1b2c3: 'to_apply', j1k2l3: 'applied' }, { attempts: { a1b2c3: [attempt('running')], j1k2l3: [attempt('sent')] } })
    const busy = row(w, 'a1b2c3')
    expect(busy.attributes('draggable')).toBe('false')
    const trigger = busy.find('.ui-move-trigger')
    expect(trigger.attributes('aria-disabled')).toBe('true')
    expect(document.getElementById(trigger.attributes('aria-describedby')).textContent)
      .toBe('JobScraper is applying to this role. Stop it in Runs first.')
    await trigger.trigger('click')
    expect(busy.find('[role="menu"]').exists()).toBe(false)
    await busy.trigger('dragstart', { dataTransfer: { setData() {}, getData() { return '' } } })
    expect(tab(w, 'interviewing').attributes('data-drop')).toBeUndefined()   // no drag began

    const badge = row(w, 'j1k2l3').find('.app-state .ui-badge.app-auto')
    expect(badge.text()).toBe('Applied automatically')
    expect(badge.attributes('data-tone')).toBe('ok')
  })
})
