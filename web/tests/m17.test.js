// M17: title recommendations say when nothing new was found; the Companies tab
// offers every watched company's scan status as a CSV; the Inbox badge counts
// neither Not interested roles nor second listings of tracked roles.
// (The Inbox's Not interested section is tested in Inbox.test.js.)
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import Companies from '../src/tabs/Companies.vue'
import TitleEditor from '../src/components/TitleEditor.vue'
import { newRoleCount } from '../src/badges.js'
import { resetDismissed } from '../src/dismissed.js'
import { resetSeenJobs } from '../src/composables/useJob.js'
import { defaultTitles, fakeApi } from './helpers.js'

let api

function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
}

beforeEach(() => {
  resetSeenJobs()
  resetDismissed()
  useApi()
})
afterEach(() => vi.unstubAllGlobals())
enableAutoUnmount(afterEach)

describe('Recommended titles', () => {
  const suggestions = extra => ({
    generated_at: '2026-09-28T04:00:00', model: 'qwen3:14b', field_of_study: '', experience: [],
    items: [{ title: 'data engineer', why: 'pipelines' }], ...extra,
  })

  it('says each request brings new titles', async () => {
    useApi({ titles: { ...defaultTitles(), max_suggestions: 5 } })
    const wrapper = mount(TitleEditor)
    await flushPromises()
    expect(wrapper.find('.te-suggest').text()).toContain('suggests 5 new ones each time')
  })

  it('says so when Qwen found nothing new and shows earlier ones', async () => {
    useApi({ titles: { ...defaultTitles(), suggestions: suggestions({ repeated: true }) } })
    const wrapper = mount(TitleEditor)
    await flushPromises()
    expect(wrapper.find('.te-repeated').text()).toContain('nothing new that fits you')
    expect(wrapper.findAll('.te-s-title').map(t => t.text())).toEqual(['data engineer'])
  })

  it('says so when there is nothing to recommend', async () => {
    useApi({ titles: { ...defaultTitles(), suggestions: suggestions({ items: [] }) } })
    const wrapper = mount(TitleEditor)
    await flushPromises()
    expect(wrapper.find('.te-repeated').exists()).toBe(false)
    expect(wrapper.find('.te-none').text()).toContain('No new titles fit you right now')
  })
})

describe('Companies: every watched company as a CSV', () => {
  it('shows how many can be scanned and links the download', async () => {
    const wrapper = mount(Companies, { props: { run: 'all', jobs: [] } })
    await flushPromises()
    expect(wrapper.find('.health-counts').text().replace(/\s+/g, ' '))
      .toBe('3 watched · 2 can be scanned · 1 failed the last fetch')
    const link = wrapper.find('a.health-csv')
    expect(link.attributes('href')).toBe('api/companies/export.csv')
    expect(link.attributes('download')).toBeDefined()
  })
})

describe('The Inbox badge', () => {
  it('counts only new roles', () => {
    const jobs = [
      { id: 'a', status: null },
      { id: 'b', status: 'applied' },
      { id: 'c', status: null, dismissed_at: '2026-09-25T10:00:00' },
      { id: 'd', status: null, tracked_as: { job_id: 'z', status: 'applied' } },
    ]
    expect(newRoleCount(jobs)).toBe(1)
  })
})
