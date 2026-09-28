// M15: the cycle choice (Settings), the job-title editor with Qwen's
// recommendations (Profile), and the run-value helpers behind the selector.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import Settings from '../src/tabs/Settings.vue'
import TitleEditor from '../src/components/TitleEditor.vue'
import { POLL_MS, resetSeenJobs } from '../src/composables/useJob.js'
import { cycleLabel, matchLabel, runLabel, runQuery, runsInRange, sameRun } from '../src/runs.js'
import { defaultSettings, defaultTitles, fakeApi } from './helpers.js'

let api

function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
  return api
}

beforeEach(() => {
  resetSeenJobs()
  useApi()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const puts = () => api.calls.filter(c => c.method === 'PUT').map(c => JSON.parse(c.body))

describe('Settings: the cycle', () => {
  async function mountSettings(settings) {
    if (settings) useApi({ settings: { ...defaultSettings(), ...settings } })
    const wrapper = mount(Settings, { props: { run: 'all', jobs: [] } })
    await flushPromises()
    return wrapper
  }

  it('offers the plan\'s cycles, in words, with the current one chosen', async () => {
    const wrapper = await mountSettings()
    const options = wrapper.findAll('.cycle-option')
    expect(options.map(o => o.find('.cycle-name').text()))
      .toEqual(['Daily', 'Every 3 days', 'Weekly', 'Fortnightly', 'Monthly'])
    expect(wrapper.find('.cycle-option.active').attributes('data-days')).toBe('14')
    expect(wrapper.find('input[type="radio"][value="14"]').element.checked).toBe(true)
    expect(wrapper.find('.cycle-hint').text()).toContain('every 14 days')
    expect(wrapper.text()).toContain('your plan (local)')
  })

  it('a smaller plan offers fewer cycles - nothing in the page is hardcoded', async () => {
    const wrapper = await mountSettings({ cycle_day_options: [7, 14, 30], plan: 'free' })
    expect(wrapper.findAll('.cycle-option').map(o => o.attributes('data-days'))).toEqual(['7', '14', '30'])
    expect(wrapper.text()).toContain('your plan (free)')
  })

  it('choosing a cycle saves it at once and the hint follows', async () => {
    const wrapper = await mountSettings()
    await wrapper.find('input[type="radio"][value="7"]').setValue(true)
    await flushPromises()
    expect(puts()).toEqual([{ cycle_days: 7 }])
    expect(wrapper.find('.cycle-option.active').attributes('data-days')).toBe('7')
    expect(wrapper.find('.cycle-saved').text()).toContain('weekly')
    expect(wrapper.find('.cycle-hint').text()).toContain('every 7 days')
  })

  it('says what the server refused', async () => {
    const wrapper = await mountSettings({ cycle_day_options: [1, 7] })
    api.server.settings.cycle_day_options = [7]   // the plan changed under the page
    await wrapper.find('input[type="radio"][value="1"]').setValue(true)
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('did not accept that cycle')
  })
})

describe('Profile: job titles', () => {
  async function mountEditor(titles) {
    if (titles) useApi({ titles: { ...defaultTitles(), ...titles } })
    const wrapper = mount(TitleEditor)
    await flushPromises()
    return wrapper
  }
  const chips = w => w.findAll('.te-chip span').map(s => s.text())

  it('shows the titles in use, where they came from, and the plan\'s limit', async () => {
    const wrapper = await mountEditor()
    expect(chips(wrapper)).toEqual(['software engineer', 'site reliability engineer'])
    // The owner's local plan has no cap (M16): a count, not "2 / 20".
    expect(wrapper.find('.te-count').text()).toBe('2 titles')
    expect(wrapper.text()).toContain('These came from your resume.')
    expect(wrapper.find('.te-reset').exists()).toBe(false)
  })

  it('adding and removing a title saves the whole list at once', async () => {
    const wrapper = await mountEditor()
    await wrapper.find('#new-title').setValue('  data   analyst ')
    await wrapper.find('form.te-add').trigger('submit')
    await flushPromises()
    expect(puts().at(-1)).toEqual({ titles: ['software engineer', 'site reliability engineer', 'data analyst'] })
    expect(chips(wrapper)).toContain('data analyst')
    expect(wrapper.text()).toContain('You have edited this list.')

    await wrapper.find('button[aria-label="Remove software engineer"]').trigger('click')
    await flushPromises()
    expect(puts().at(-1)).toEqual({ titles: ['site reliability engineer', 'data analyst'] })
  })

  it('a title already on the list is not added twice, whatever its case', async () => {
    const wrapper = await mountEditor()
    await wrapper.find('#new-title').setValue('Software Engineer')
    await wrapper.find('form.te-add').trigger('submit')
    await flushPromises()
    expect(puts()).toEqual([])
    expect(wrapper.find('.te-note').text()).toContain('already on the list')
  })

  it('at the plan\'s limit the input closes and says why', async () => {
    const wrapper = await mountEditor({ titles: ['a', 'b'], max_titles: 2 })
    expect(wrapper.find('#new-title').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.te-full').text()).toContain('the most your plan (local) allows')
  })

  it('the last title cannot be removed; Reset goes back to the resume\'s', async () => {
    const wrapper = await mountEditor({ titles: ['only one'], source: 'custom' })
    await wrapper.find('button[aria-label="Remove only one"]').trigger('click')
    expect(wrapper.find('[role="alert"]').text()).toContain('Keep at least one job title')
    expect(puts()).toEqual([])
    await wrapper.find('.te-reset').trigger('click')
    await flushPromises()
    expect(api.calls.some(c => c.url === 'api/titles' && c.method === 'DELETE')).toBe(true)
    expect(chips(wrapper)).toEqual(['software engineer', 'site reliability engineer'])
  })

  it('Recommend titles runs as a job, then offers one-click adds with what they were based on', async () => {
    vi.useFakeTimers()
    const wrapper = await mountEditor()
    await wrapper.find('.te-suggest-btn').trigger('click')
    await flushPromises()
    expect(api.calls.some(c => c.url === 'api/jobs/titles' && c.method === 'POST')).toBe(true)
    expect(wrapper.find('.te-suggest-btn').text()).toContain('Recommending')
    api.finishJob()
    await vi.advanceTimersByTimeAsync(POLL_MS)
    await flushPromises()

    const items = wrapper.findAll('.te-suggestion .te-s-title').map(s => s.text())
    expect(items).toEqual(['platform engineer', 'data engineer'])
    expect(wrapper.find('.te-based').text()).toContain('BEng Computer Engineering')
    expect(wrapper.find('.te-based').text()).toContain('Cloud intern at GovTech')

    await wrapper.findAll('.te-suggestion')[0].trigger('click')
    await flushPromises()
    expect(puts().at(-1).titles).toContain('platform engineer')
    // A recommendation you took leaves the list.
    expect(wrapper.findAll('.te-suggestion .te-s-title').map(s => s.text())).toEqual(['data engineer'])
  })

  it('Add all takes the recommendations that still fit', async () => {
    const wrapper = await mountEditor({
      titles: ['a', 'b'], max_titles: 3,
      suggestions: { generated_at: '2026-09-28T04:00:00', model: 'qwen3:14b', field_of_study: '', experience: [],
        items: [{ title: 'c', why: '' }, { title: 'd', why: '' }] },
    })
    expect(wrapper.find('.te-add-all').text()).toBe('Add the first 1')
    await wrapper.find('.te-add-all').trigger('click')
    await flushPromises()
    expect(puts().at(-1)).toEqual({ titles: ['a', 'b', 'c'] })
  })

  it('while another job runs, Recommend waits', async () => {
    useApi({ job: { id: 7, kind: 'run', state: 'running' } })
    const wrapper = mount(TitleEditor)
    await flushPromises()
    expect(wrapper.find('.te-suggest-btn').attributes('disabled')).toBeDefined()
  })
})

describe('run values (runs.js)', () => {
  it('turns every choice into the query and the label the page shows', () => {
    expect(runQuery('all')).toBe('all')
    expect(runQuery([14, 12])).toBe('14,12')
    expect(runQuery(undefined)).toBe('all')
    expect(runLabel('week')).toBe('Past week')
    expect(runLabel([12])).toBe('Run 12')
    expect(runLabel([14, 12, 9, 5])).toBe('4 runs')
    expect(sameRun([12, 11], [12, 11])).toBe(true)
    expect(sameRun([12], 12)).toBe(true)
    expect(sameRun('all', 'week')).toBe(false)
  })

  it('works out which runs a range covers from their finish times', () => {
    const now = Date.parse('2026-09-29T12:00:00Z')
    const runs = [{ run_no: 12, finished_at: '2026-09-23T14:30:00' },
      { run_no: 11, finished_at: '2026-09-21T09:12:00' }, { run_no: 3, finished_at: null }]
    expect(runsInRange(runs, 'all', now)).toBeNull()
    expect([...runsInRange(runs, 'week', now)]).toEqual([12])
    expect([...runsInRange(runs, 'month', now)]).toEqual([12, 11])
    expect([...runsInRange(runs, [3], now)]).toEqual([3])
  })

  it('writes matches and cycles for people', () => {
    expect(matchLabel(0)).toBe('0 matches')
    expect(matchLabel(1)).toBe('1 match')
    expect(matchLabel(null)).toBe('0 matches')
    expect([1, 3, 7, 14, 30].map(cycleLabel)).toEqual(['Daily', 'Every 3 days', 'Weekly', 'Fortnightly', 'Monthly'])
  })
})

describe('Choose runs… lands on the picker', () => {
  it('the Runs tab scrolls to the picker only when sent by Choose runs…', async () => {
    const { default: Runs } = await import('../src/tabs/Runs.vue')
    const { requestPicker } = await import('../src/runs.js')
    const scrolled = vi.fn()
    Element.prototype.scrollIntoView = scrolled
    try {
      const plain = mount(Runs, { props: { runs: [{ run_no: 1, accepted: 2 }], run: 'all' } })
      await flushPromises()
      expect(scrolled).not.toHaveBeenCalled()
      plain.unmount()
      requestPicker()
      const sent = mount(Runs, { props: { runs: [{ run_no: 1, accepted: 2 }], run: 'all' } })
      await flushPromises()
      expect(scrolled).toHaveBeenCalledTimes(1)
      expect(scrolled.mock.instances[0].id).toBe('choose-runs')
      sent.unmount()
    } finally {
      delete Element.prototype.scrollIntoView
    }
  })
})
