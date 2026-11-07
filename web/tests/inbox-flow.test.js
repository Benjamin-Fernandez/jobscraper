// Q-70 lane A (Inbox flow, A1-A11): focus after an action, roving tabindex,
// Home/End, the folded Not interested section, the double-press guard, Undo,
// the refresh/error notices, the quiet description region and Escape in search.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import Inbox from '../src/tabs/Inbox.vue'
import { resetDismissed } from '../src/dismissed.js'
import { dismissToast, toast } from '../src/toast.js'
import { FIXTURE, fakeApi } from './helpers.js'

const NI_KEY = 'jobscraper.inbox.notInterestedOpen'
let api
let wrapper

function jobsFor(run, extra = {}) {
  return FIXTURE.jobs
    .filter(j => j.run_no === run)
    .map(j => ({ ...j, closed: false, status: null, notes: null, ...(extra[j.id] ?? {}) }))
}

function mountInbox(props = {}) {
  wrapper = mount(Inbox, { attachTo: document.body, props: { run: 12, jobs: jobsFor(12), ...props } })
  return wrapper
}

// Run 12, newest first: Shopee g7h8i9, GovTech d4e5f6, OKX.
const hits = () => wrapper.findAll('.card-hit')
const puts = () => api.calls.filter(c => c.method === 'PUT')
const dismissedAll = () => Object.fromEntries(jobsFor(12).map(j => [j.id, { dismissed_at: '2026-09-25T10:00:00' }]))

beforeEach(() => {
  resetDismissed()
  window.localStorage.clear()
  dismissToast()
  api = fakeApi()
  vi.stubGlobal('fetch', api.fetch)
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('Inbox flow: focus and keyboard (A1, A2)', () => {
  it('after Save, focus lands on the next card', async () => {
    mountInbox()
    const save = wrapper.find('button.save')
    save.element.focus()
    await save.trigger('click')
    await flushPromises()
    expect(hits()).toHaveLength(2)
    expect(document.activeElement).toBe(hits()[0].element)
    expect(hits()[0].text()).toContain('GovTech')
  })

  it('after Not interested, focus lands on the next card', async () => {
    mountInbox()
    const dismiss = wrapper.find('button.dismiss')
    dismiss.element.focus()
    await dismiss.trigger('click')
    await flushPromises()
    expect(document.activeElement).toBe(hits()[0].element)
    expect(hits()[0].text()).toContain('GovTech')
  })

  it('after a failed write, focus returns to the same role', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false, status: 500, statusText: 'Internal Server Error', json: async () => ({}),
    })))
    mountInbox()
    const save = wrapper.find('button.save')
    save.element.focus()
    await save.trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('500')
    expect(hits()).toHaveLength(3)
    expect(document.activeElement).toBe(hits()[0].element)
    expect(hits()[0].text()).toContain('Shopee')
  })

  it('does not steal focus when it was somewhere else (an unrelated input)', async () => {
    mountInbox()
    const outside = document.createElement('input')
    document.body.appendChild(outside)
    try {
      outside.focus()
      await wrapper.find('button.save').trigger('click')   // a click does not move focus in jsdom
      await flushPromises()
      expect(document.activeElement).toBe(outside)
    } finally {
      outside.remove()
    }
  })

  it('exactly one card is a tab stop: the selected one', async () => {
    mountInbox()
    const stops = () => hits().filter(h => h.attributes('tabindex') === '0')
    expect(stops()).toHaveLength(1)
    expect(hits().filter(h => h.attributes('tabindex') === '-1')).toHaveLength(2)
    expect(stops()[0].text()).toContain('Shopee')
    await hits()[1].trigger('click')
    expect(stops()).toHaveLength(1)
    expect(stops()[0].text()).toContain('GovTech')
  })

  it('End focuses the last card and Home the first', async () => {
    mountInbox()
    hits()[1].element.focus()
    await hits()[1].trigger('keydown', { key: 'End' })
    await flushPromises()
    expect(document.activeElement).toBe(hits()[2].element)
    await hits()[2].trigger('keydown', { key: 'Home' })
    await flushPromises()
    expect(document.activeElement).toBe(hits()[0].element)
  })
})

describe('Inbox flow: Not interested is folded by default (A3)', () => {
  it('the section is closed with nothing stored, and the toggle opens and stores it', async () => {
    mountInbox({ jobs: jobsFor(12, { d4e5f6: { dismissed_at: '2026-09-25T10:00:00' } }) })
    expect(wrapper.find('.cards.ni').exists()).toBe(false)
    expect(wrapper.find('.ni-head').exists()).toBe(true)
    await wrapper.find('.ni-head').trigger('click')
    expect(wrapper.find('.cards.ni').exists()).toBe(true)
    expect(window.localStorage.getItem(NI_KEY)).toBe('1')
  })

  it('"You\'re all caught up" shows when only dismissed roles remain, and Show opens the section', async () => {
    mountInbox({ jobs: jobsFor(12, dismissedAll()) })
    expect(wrapper.find('.caught-up').exists()).toBe(true)
    expect(wrapper.find('.cards.ni').exists()).toBe(false)
    expect(wrapper.find('.split').exists()).toBe(false)
    await wrapper.find('button.show-ni').trigger('click')
    await flushPromises()
    expect(wrapper.find('.cards.ni').exists()).toBe(true)
    expect(wrapper.findAll('.cards.ni .card')).toHaveLength(3)
    expect(window.localStorage.getItem(NI_KEY)).toBe('1')
  })

  it('a search whose only matches are in the folded section offers to show them', async () => {
    mountInbox({ jobs: jobsFor(12, { d4e5f6: { dismissed_at: '2026-09-25T10:00:00' } }) })
    await wrapper.find('.search input').setValue('GovTech')
    expect(wrapper.find('.cards.ni').exists()).toBe(false)
    expect(wrapper.find('.split').exists()).toBe(false)
    const show = wrapper.find('button.show-ni')
    expect(show.exists()).toBe(true)
    expect(show.text()).toBe('Show 1 in Not interested')
    expect(wrapper.text()).toContain('No roles match')
    await show.trigger('click')
    await flushPromises()
    expect(wrapper.find('.cards.ni').exists()).toBe(true)
    expect(wrapper.findAll('.cards.ni .card .company').map(c => c.text())).toEqual(['GovTech'])
    expect(wrapper.text()).not.toContain('No roles match')
  })
})

describe('Inbox flow: the press guard and Undo (A5)', () => {
  it('two Not interested clicks within 400 ms dismiss one role; 1 s later, a second', async () => {
    mountInbox()
    await wrapper.find('button.dismiss').trigger('click')
    await flushPromises()
    await wrapper.find('button.dismiss').trigger('click')       // the next role, still inside 400 ms
    await flushPromises()
    expect(puts()).toHaveLength(1)
    expect(puts()[0].url).toBe('api/dismissals/g7h8i9')

    vi.useFakeTimers({ toFake: ['Date'], now: Date.now() + 1000 })
    await wrapper.find('button.dismiss').trigger('click')
    await flushPromises()
    expect(puts()).toHaveLength(2)
    expect(puts()[1].url).toBe('api/dismissals/d4e5f6')
  })

  it('the toast Undo works right after Not interested, with no wait', async () => {
    mountInbox()
    await wrapper.find('button.dismiss').trigger('click')
    await flushPromises()
    expect(hits()).toHaveLength(2)
    await toast.current.action.run()
    await flushPromises()
    expect(api.calls.filter(c => c.method === 'DELETE').map(c => c.url)).toEqual(['api/dismissals/g7h8i9'])
    expect(hits()).toHaveLength(3)
    expect(wrapper.find('.detail-company').text()).toBe('Shopee')
  })

  it('the toast Undo works right after Save, with no wait', async () => {
    mountInbox()
    await wrapper.find('button.save').trigger('click')
    await flushPromises()
    await toast.current.action.run()
    await flushPromises()
    expect(api.calls.filter(c => c.method === 'DELETE').map(c => c.url)).toEqual(['api/applications/g7h8i9'])
    expect(hits()).toHaveLength(3)
  })
})

describe('Inbox flow: refresh and error states (A6, A7)', () => {
  it('our own reload after a Save does not dim the list; a later load does', async () => {
    mountInbox()
    await wrapper.find('button.save').trigger('click')
    await flushPromises()
    await wrapper.setProps({ loading: true })
    expect(wrapper.find('.split').exists()).toBe(true)
    expect(wrapper.find('.split').classes()).not.toContain('refreshing')
    await wrapper.setProps({ loading: false })
    await wrapper.setProps({ loading: true })
    expect(wrapper.find('.split').classes()).toContain('refreshing')
  })

  it('an error with roles already loaded keeps the list and says so', () => {
    mountInbox({ error: 'timed out' })
    expect(wrapper.find('.split').exists()).toBe(true)
    const note = wrapper.find('.notice.error').text()
    expect(note).toContain('Could not refresh the shortlist: timed out')
    expect(note).toContain('Showing the last list loaded')
  })

  it('an error with no roles says it could not load', () => {
    mountInbox({ jobs: [], error: 'timed out' })
    expect(wrapper.find('.split').exists()).toBe(false)
    const note = wrapper.find('.notice.error').text()
    expect(note).toContain('Could not load the shortlist: timed out')
    expect(note).not.toContain('Showing the last list')
  })
})

describe('Inbox flow: the description region (A8)', () => {
  it('.jd is not a live region, and its status line is empty when the description loads', async () => {
    mountInbox()
    await flushPromises()
    const jd = wrapper.find('.jd')
    expect(jd.attributes('aria-live')).toBeUndefined()
    expect(wrapper.find('.jd [role="status"]').text()).toBe('')
  })

  it('a failed posting fetch is announced through the status line', async () => {
    vi.stubGlobal('fetch', vi.fn(async url => (String(url).startsWith('api/postings/')
      ? { ok: false, status: 502, statusText: 'Bad Gateway', json: async () => ({}) }
      : api.fetch(url))))
    mountInbox()
    await flushPromises()
    expect(wrapper.find('.jd').attributes('aria-live')).toBeUndefined()
    expect(wrapper.find('.jd [role="status"]').text()).toBe('Could not load the description.')
  })
})

describe('Inbox flow: search and counts (A9, A11)', () => {
  it('Escape clears the search first, then leaves the field', async () => {
    mountInbox()
    const input = wrapper.find('.search input')
    input.element.focus()
    await input.setValue('GovTech')
    expect(hits()).toHaveLength(1)
    await input.trigger('keydown', { key: 'Escape' })
    expect(input.element.value).toBe('')
    expect(hits()).toHaveLength(3)
    expect(document.activeElement).toBe(input.element)
    await input.trigger('keydown', { key: 'Escape' })
    expect(document.activeElement).not.toBe(input.element)
  })

  it('tracked roles are counted as "N already tracked" and link to Applications', () => {
    mountInbox({ jobs: jobsFor(12, { a1b2c3: { status: 'applied' }, g7h8i9: { status: 'to_apply' } }) })
    const link = wrapper.find('.count a.tracked')
    expect(link.text()).toBe('2 already tracked')
    expect(link.attributes('href')).toBe('#/applications')
  })
})
