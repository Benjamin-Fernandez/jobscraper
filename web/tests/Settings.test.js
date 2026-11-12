import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import Settings from '../src/tabs/Settings.vue'
import { fakeApi, setHash } from './helpers.js'

let api

function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
  return api
}

beforeEach(() => {
  setHash('#/settings/search')   // Q-100: Settings opens on Accounts; the form is in the Search view
  useApi()
})
afterEach(() => {
  vi.unstubAllGlobals()
  setHash('')
})
enableAutoUnmount(afterEach)

async function mountSettings() {
  const wrapper = mount(Settings)
  await flushPromises()
  return wrapper
}

const puts = () => api.calls.filter(c => c.url === 'api/settings' && c.method === 'PUT')
const input = w => w.find('#batch-size')
const hint = w => w.find('#batch-size-hint').text()
const row = w => w.find('#setting-batch-size')
const status = w => row(w).find('[role="status"]')
const rowError = w => row(w).find('[role="alert"]')

// Q-116: the editor renders only while its row is open; there is no Save button, a
// number saves on Enter or when focus leaves the editor, a preset saves at once.
async function openBatch(w) {
  await w.find('#setting-batch-size .setting-main').trigger('click')
  await flushPromises()
}
const enter = w => input(w).trigger('keydown', { key: 'Enter' })
const leave = w => input(w).trigger('focusout', { relatedTarget: document.body })

describe('Settings tab: companies per run', () => {
  it('shows the saved value on the row; the editor (cadence hint, default) opens with the row', async () => {
    const wrapper = await mountSettings()
    expect(row(wrapper).find('.setting-value').text()).toBe('10 companies')
    expect(input(wrapper).exists()).toBe(false)                       // closed until the row opens
    await openBatch(wrapper)
    expect(input(wrapper).element.value).toBe('10')
    expect(hint(wrapper)).toBe('A full 14-day sweep takes 1.6 runs a day at this size (23 runs to cover 224 companies).')
    expect(wrapper.text()).toContain('The config default is 10')
    expect(wrapper.find('button.save').exists()).toBe(false)           // save on change: no Save button
  })

  it('the hint follows the number as you type, and typing alone sends nothing', async () => {
    const wrapper = await mountSettings()
    await openBatch(wrapper)
    await input(wrapper).setValue('25')
    expect(hint(wrapper)).toBe('A full 14-day sweep takes about 1 run every 2 days at this size (9 runs to cover 224 companies).')
    expect(puts()).toHaveLength(0)
  })

  it('Enter saves: one PUT, the new value on the row, "Saved" beside it', async () => {
    const wrapper = await mountSettings()
    await openBatch(wrapper)
    await input(wrapper).setValue('25')
    await enter(wrapper)
    await flushPromises()

    expect(puts()).toHaveLength(1)
    expect(JSON.parse(puts()[0].body)).toEqual({ batch_size: 25 })
    // The visible word plus a hidden announcement ("Saved: <label>, <value>. ..."): match, don't equal.
    expect(status(wrapper).text()).toContain('Saved')
    expect(status(wrapper).text()).toContain('Companies per run, 25 companies')
    expect(row(wrapper).find('.setting-value').text()).toBe('25 companies')
    expect(input(wrapper).element.value).toBe('25')
    expect(api.server.settings.batch_size).toBe(25)
  })

  it('focus leaving the editor saves; an unchanged number sends nothing', async () => {
    const wrapper = await mountSettings()
    await openBatch(wrapper)
    await leave(wrapper)                                              // unchanged
    await flushPromises()
    expect(puts()).toHaveLength(0)
    await input(wrapper).setValue('40')
    await leave(wrapper)
    await flushPromises()
    expect(puts().map(c => JSON.parse(c.body))).toEqual([{ batch_size: 40 }])
  })

  it('a preset saves at once, without Enter', async () => {
    const wrapper = await mountSettings()
    await openBatch(wrapper)
    await wrapper.find('[data-preset="50"]').trigger('click')
    await flushPromises()
    expect(puts().map(c => JSON.parse(c.body))).toEqual([{ batch_size: 50 }])
    expect(row(wrapper).find('.setting-value').text()).toBe('50 companies')
  })

  it('Esc reverts the draft, sends nothing and closes the row', async () => {
    const wrapper = await mountSettings()
    await openBatch(wrapper)
    await input(wrapper).setValue('77')
    await input(wrapper).trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(puts()).toHaveLength(0)
    expect(input(wrapper).exists()).toBe(false)
    expect(row(wrapper).find('.setting-value').text()).toBe('10 companies')
    await openBatch(wrapper)
    expect(input(wrapper).element.value).toBe('10')                   // the draft did not survive
  })

  it('blocks out-of-range values with a reason, and never sends them', async () => {
    const wrapper = await mountSettings()
    await openBatch(wrapper)
    const reasons = {
      '': 'Enter how many companies',
      0: 'at least 1',
      '-1': 'at least 1',
      225: 'At most 224',
      2.5: 'whole number',
    }
    for (const [value, reason] of Object.entries(reasons)) {
      await input(wrapper).setValue(String(value))
      expect(input(wrapper).attributes('aria-invalid'), value).toBe('true')
      expect(hint(wrapper)).toContain(reason)
      await enter(wrapper)
      await leave(wrapper)
      await flushPromises()
    }
    expect(puts()).toHaveLength(0)

    await input(wrapper).setValue('224')
    expect(input(wrapper).attributes('aria-invalid')).toBe('false')
    await enter(wrapper)
    await flushPromises()
    expect(puts().map(c => JSON.parse(c.body))).toEqual([{ batch_size: 224 }])
  })

  it('shows a server 422 under the row and keeps the old value', async () => {
    const wrapper = await mountSettings()
    await openBatch(wrapper)
    // The watchlist shrank after the page loaded, so 200 is now out of range.
    api.server.settings.enabled_companies = 150
    await input(wrapper).setValue('200')
    await enter(wrapper)
    await flushPromises()

    expect(puts()).toHaveLength(1)
    expect(rowError(wrapper).text()).toBe("Couldn't save: batch_size must be between 1 and 150.")
    expect(status(wrapper).exists()).toBe(false)
    expect(row(wrapper).find('.setting-value').text()).toBe('10 companies')
  })

  it("before the first sync (0 enabled), the server's 422 message is what you see", async () => {
    useApi({ settings: { batch_size: 10, batch_size_default: 10, enabled_companies: 0, cycle_days: 14, runs_per_day_needed: 0 } })
    const wrapper = await mountSettings()
    await openBatch(wrapper)
    expect(hint(wrapper)).toBe('No companies yet. Add some in Companies, or start a run to load your watchlist.')   // A10 copy
    await input(wrapper).setValue('12')
    await enter(wrapper)
    await flushPromises()
    expect(puts()).toHaveLength(1)
    expect(rowError(wrapper).text()).toBe("Couldn't save: batch_size must be between 1 and 0.")
  })

  it('a FastAPI validation 422 (a list of errors) is shown as its messages', async () => {
    const real = api.fetch
    vi.stubGlobal('fetch', vi.fn(async (url, init) => (url === 'api/settings' && init?.method === 'PUT'
      ? { ok: false, status: 422, statusText: 'Unprocessable Entity', json: async () => ({ detail: [{ loc: ['body', 'batch_size'], msg: 'Input should be a valid integer' }] }) }
      : real(url, init))))
    const wrapper = await mountSettings()
    await openBatch(wrapper)
    await input(wrapper).setValue('12')
    await enter(wrapper)
    await flushPromises()
    expect(rowError(wrapper).text()).toBe("Couldn't save: Input should be a valid integer.")
  })

  it('without the M11 routes, shows a readable error and a retry', async () => {
    useApi({ m11: false })
    const wrapper = await mountSettings()
    // Q-100: the Search view's own alert (the Accounts view has its own, not mounted here).
    const alert = wrapper.find('#settings-panel-search [role="alert"]')
    expect(alert.text()).toContain('404')
    expect(alert.text()).toContain('does not offer that yet')
    expect(wrapper.find('form').exists()).toBe(false)
    expect(alert.find('button').text()).toBe('Try again')
  })

  it('shows a loading placeholder first', () => {
    const wrapper = mount(Settings)
    expect(wrapper.find('[role="status"][aria-busy="true"]').exists()).toBe(true)
  })
})
