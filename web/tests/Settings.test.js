import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import Settings from '../src/tabs/Settings.vue'
import { fakeApi } from './helpers.js'

let api

function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
  return api
}

beforeEach(() => useApi())
afterEach(() => vi.unstubAllGlobals())
enableAutoUnmount(afterEach)

async function mountSettings() {
  const wrapper = mount(Settings)
  await flushPromises()
  return wrapper
}

const puts = () => api.calls.filter(c => c.url === 'api/settings' && c.method === 'PUT')
const input = w => w.find('#batch-size')
const save = w => w.find('button.save')
const hint = w => w.find('#batch-size-hint').text()

describe('Settings tab: companies per run', () => {
  it('shows the saved value and the cadence hint', async () => {
    const wrapper = await mountSettings()
    expect(input(wrapper).element.value).toBe('10')
    expect(hint(wrapper)).toBe('A full 14-day sweep needs 1.6 runs/day at this size (23 runs to cover 224 companies).')
    expect(wrapper.text()).toContain('The config default is 10')
    // Nothing to save until something changes.
    expect(save(wrapper).attributes('disabled')).toBeDefined()
  })

  it('the hint follows the number as you type', async () => {
    const wrapper = await mountSettings()
    await input(wrapper).setValue('25')
    expect(hint(wrapper)).toBe('A full 14-day sweep needs 0.6 runs/day at this size (9 runs to cover 224 companies).')
  })

  it('saving calls the API and shows the saved value', async () => {
    const wrapper = await mountSettings()
    await input(wrapper).setValue('25')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(puts()).toHaveLength(1)
    expect(JSON.parse(puts()[0].body)).toEqual({ batch_size: 25 })
    expect(wrapper.find('[role="status"]').text()).toBe('Saved: 25 companies per run.')
    expect(input(wrapper).element.value).toBe('25')
    expect(save(wrapper).attributes('disabled')).toBeDefined()
    expect(api.server.settings.batch_size).toBe(25)
  })

  it('blocks out-of-range values in the form, with a reason', async () => {
    const wrapper = await mountSettings()
    const reasons = {
      '': 'Enter how many companies',
      0: 'at least 1',
      '-1': 'at least 1',
      225: 'At most 224',
      2.5: 'whole number',
    }
    for (const [value, reason] of Object.entries(reasons)) {
      await input(wrapper).setValue(String(value))
      expect(save(wrapper).attributes('disabled'), value).toBeDefined()
      expect(input(wrapper).attributes('aria-invalid')).toBe('true')
      expect(hint(wrapper)).toContain(reason)
      await wrapper.find('form').trigger('submit')
      await flushPromises()
    }
    expect(puts()).toHaveLength(0)

    await input(wrapper).setValue('224')
    expect(save(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('shows a server 422', async () => {
    const wrapper = await mountSettings()
    // The watchlist shrank after the page loaded, so 200 is now out of range.
    api.server.settings.enabled_companies = 150
    await input(wrapper).setValue('200')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(puts()).toHaveLength(1)
    const alert = wrapper.find('[role="alert"]').text()
    expect(alert).toContain('did not accept 200')
    expect(alert).toContain('between 1 and 150')
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })

  it('without the M11 routes, shows a readable error and a retry', async () => {
    useApi({ m11: false })
    const wrapper = await mountSettings()
    const alert = wrapper.find('[role="alert"]')
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
