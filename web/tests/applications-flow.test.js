// Q-70 lane B (Applications): Verify B pins. The status select commits on purpose
// (B3), the Active chip is the default and is remembered (B2), a quiet applied role
// gets a follow-up cue (B5), a single-event row can be removed with Undo (B6),
// Undo is one more history event (D-101), and Clear filters resets all three.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import Applications from '../src/tabs/Applications.vue'
import { ageLabel, daysSince, FOLLOW_UP_DAYS, isActive, lastAt, needsFollowUp, secondLine, STAGE_KEY } from '../src/applications.js'
import { dismissToast, toast } from '../src/toast.js'
import { fakeApi, runsFrom } from './helpers.js'

let api
const wrappers = []

async function mountTab(statuses, { attach = false } = {}) {
  api = fakeApi({ statuses })
  vi.stubGlobal('fetch', api.fetch)
  const wrapper = mount(Applications, {
    props: { run: 12, runs: runsFrom(), jobs: [] },
    ...(attach ? { attachTo: document.body } : {}),
  })
  wrappers.push(wrapper)
  await flushPromises()
  return wrapper
}

const row = (w, id) => w.find(`.app-row[data-job="${id}"]`)
const stageButton = (w, id) => w.find(`.stage[data-status="${id}"]`)
const posts = () => api.calls.filter(c => c.method === 'POST')
const select = (w, id) => row(w, id).find('select')

beforeEach(() => {
  window.localStorage.clear()
  dismissToast()
})
afterEach(() => {
  wrappers.splice(0).forEach(w => w.unmount())
  vi.useRealTimers()
  vi.unstubAllGlobals()
  dismissToast()
})

describe('status select commits on purpose (B3)', () => {
  it('a keyboard change is held until blur', async () => {
    const w = await mountTab({ a1b2c3: 'applied' })
    const s = select(w, 'a1b2c3')
    await s.trigger('keydown', { key: 'ArrowDown' })
    await s.setValue('rejected')                       // change, no pointerdown
    await flushPromises()
    expect(posts()).toHaveLength(0)
    expect(s.element.value).toBe('rejected')           // shown, not saved
    await s.trigger('blur')
    await flushPromises()
    expect(posts()).toHaveLength(1)
    expect(JSON.parse(posts()[0].body).status).toBe('rejected')
  })

  it('passing over a status on the way to another saves only the last one', async () => {
    const w = await mountTab({ a1b2c3: 'applied' })
    const s = select(w, 'a1b2c3')
    for (const v of ['interviewing', 'offer', 'rejected']) {
      await s.trigger('keydown', { key: 'ArrowDown' })
      await s.setValue(v)
    }
    await s.trigger('keydown', { key: 'ArrowUp' })
    await s.setValue('interviewing')
    await s.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(posts()).toHaveLength(1)
    expect(JSON.parse(posts()[0].body).status).toBe('interviewing')
  })

  it('Enter commits the held change', async () => {
    const w = await mountTab({ a1b2c3: 'applied' })
    const s = select(w, 'a1b2c3')
    await s.trigger('keydown', { key: 'ArrowDown' })
    await s.setValue('interviewing')
    expect(posts()).toHaveLength(0)
    await s.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(posts()).toHaveLength(1)
    expect(row(w, 'a1b2c3').attributes('data-status')).toBe('interviewing')
  })

  it('Escape drops the held change, and the later blur saves nothing', async () => {
    const w = await mountTab({ a1b2c3: 'applied' })
    const s = select(w, 'a1b2c3')
    await s.trigger('keydown', { key: 'ArrowDown' })
    await s.setValue('rejected')
    await s.trigger('keydown', { key: 'Escape' })
    await s.trigger('blur')
    await flushPromises()
    expect(posts()).toHaveLength(0)
    expect(s.element.value).toBe('applied')
  })

  it('a pointer choice commits once, and the toast Undo restores the status (D-101)', async () => {
    const w = await mountTab({ a1b2c3: 'applied' })
    const s = select(w, 'a1b2c3')
    await s.trigger('pointerdown')
    await s.setValue('interviewing')
    await flushPromises()
    await s.trigger('blur')                            // a blur after the commit adds nothing
    await flushPromises()
    expect(posts()).toHaveLength(1)
    expect(toast.current.message).toMatch(/^Moved to Interviewing: /)
    expect(toast.current.action.label).toBe('Undo')

    await toast.current.action.run()
    await flushPromises()
    expect(posts()).toHaveLength(2)
    expect(JSON.parse(posts()[1].body).status).toBe('applied')
    expect(row(w, 'a1b2c3').attributes('data-status')).toBe('applied')
    // Undo is one more change: applied -> interviewing -> applied is three events.
    expect(row(w, 'a1b2c3').findAll('.timeline li .to').map(e => e.text()))
      .toEqual(['Applied', 'Interviewing', 'Applied'])
  })
})

describe('the Active chip (B2)', () => {
  it('is the default, hides rejected and withdrawn, and counts what it shows', async () => {
    const w = await mountTab({ a1b2c3: 'applied', m4n5o6: 'rejected', j1k2l3: 'withdrawn', g7h8i9: 'to_apply' })
    expect(stageButton(w, 'active').attributes('aria-pressed')).toBe('true')
    expect(row(w, 'a1b2c3').exists()).toBe(true)
    expect(row(w, 'g7h8i9').exists()).toBe(true)
    expect(row(w, 'm4n5o6').exists()).toBe(false)
    expect(row(w, 'j1k2l3').exists()).toBe(false)
    expect(stageButton(w, 'active').find('.stage-n').text()).toBe('2')
    expect(stageButton(w, 'all').find('.stage-n').text()).toBe('4')
    await stageButton(w, 'rejected').trigger('click')
    expect(row(w, 'm4n5o6').exists()).toBe(true)
  })

  it('persists the choice across a remount', async () => {
    const w = await mountTab({ a1b2c3: 'applied', m4n5o6: 'rejected' })
    await stageButton(w, 'all').trigger('click')
    expect(window.localStorage.getItem(STAGE_KEY)).toBe('all')
    w.unmount()
    const again = await mountTab({ a1b2c3: 'applied', m4n5o6: 'rejected' })
    expect(stageButton(again, 'all').attributes('aria-pressed')).toBe('true')
    expect(row(again, 'm4n5o6').exists()).toBe(true)
  })

  it('falls back to Active when the remembered stage is not offered any more', async () => {
    window.localStorage.setItem(STAGE_KEY, 'no_such_stage')
    const w = await mountTab({ a1b2c3: 'applied', m4n5o6: 'rejected' })
    expect(stageButton(w, 'active').attributes('aria-pressed')).toBe('true')
    expect(row(w, 'm4n5o6').exists()).toBe(false)
    expect(window.localStorage.getItem(STAGE_KEY)).toBe('active')
  })
})

describe('age and follow-up cues (B5)', () => {
  // The fake stamps the first event 2026-09-24T08:10:00 UTC.
  it('an applied role 15 days old shows Follow up?; 13 days does not', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-10-09T09:00:00Z'))
    const w = await mountTab({ a1b2c3: 'applied' })
    expect(row(w, 'a1b2c3').find('.follow-up').text()).toBe('Follow up?')
    expect(row(w, 'a1b2c3').find('.updated').text()).toBe('Applied · 15 days')
    w.unmount()

    vi.setSystemTime(new Date('2026-10-07T09:00:00Z'))
    const fresh = await mountTab({ a1b2c3: 'applied' })
    expect(row(fresh, 'a1b2c3').find('.follow-up').exists()).toBe(false)
    expect(row(fresh, 'a1b2c3').find('.updated').text()).toBe('Applied · 13 days')
  })

  it('only an applied role is nudged, however old', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-20T09:00:00Z'))
    const w = await mountTab({ a1b2c3: 'interviewing', g7h8i9: 'to_apply' })
    expect(w.findAll('.follow-up')).toHaveLength(0)
  })

  it('a role changed the same day reads "today"', async () => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-09-24T12:00:00Z'))
    const w = await mountTab({ a1b2c3: 'applied' })
    expect(row(w, 'a1b2c3').find('.updated').text()).toBe('Applied · today')
  })
})

describe('Remove from Applications (B6)', () => {
  it('shows only on a single-event row', async () => {
    api = fakeApi({ statuses: { a1b2c3: 'applied', j1k2l3: 'applied' } })
    vi.stubGlobal('fetch', api.fetch)
    await api.fetch('api/applications/j1k2l3', { method: 'POST', body: JSON.stringify({ status: 'interviewing', notes: null }) })
    const w = mount(Applications, { props: { run: 12, runs: runsFrom(), jobs: [] } })
    wrappers.push(w)
    await flushPromises()
    expect(row(w, 'a1b2c3').find('.row-remove').exists()).toBe(true)
    expect(row(w, 'j1k2l3').find('.history').exists()).toBe(true)
    expect(row(w, 'j1k2l3').find('.row-remove').exists()).toBe(false)
  })

  it('removes the role, and the toast Undo re-tracks it with its status', async () => {
    const w = await mountTab({ a1b2c3: 'applied', j1k2l3: 'interviewing' })
    await row(w, 'a1b2c3').find('.row-remove').trigger('click')
    await flushPromises()
    expect(api.calls.filter(c => c.method === 'DELETE').map(c => c.url)).toEqual(['api/applications/a1b2c3'])
    expect(row(w, 'a1b2c3').exists()).toBe(false)
    expect(toast.current.message).toMatch(/^Removed /)
    expect(w.emitted('changed')).toHaveLength(1)

    await toast.current.action.run()
    await flushPromises()
    expect(posts()).toHaveLength(1)
    const body = JSON.parse(posts()[0].body)
    expect(body.status).toBe('applied')
    expect(body.company).toBe('OKX')
    expect(row(w, 'a1b2c3').exists()).toBe(true)
    expect(row(w, 'a1b2c3').attributes('data-status')).toBe('applied')
    expect(w.emitted('changed')).toHaveLength(2)
  })
})

describe('Clear filters and search (B7)', () => {
  it('Clear filters resets the stage, the run filter and the query', async () => {
    const w = await mountTab({ a1b2c3: 'applied', m4n5o6: 'rejected' })
    await stageButton(w, 'offer').trigger('click')
    await w.find('.run-selector select').setValue('week')
    await w.find('input[type="search"]').setValue('zzz')
    expect(w.find('.clear-filters').exists()).toBe(true)

    await w.find('.clear-filters').trigger('click')
    expect(stageButton(w, 'all').attributes('aria-pressed')).toBe('true')
    expect(w.find('.run-selector select').element.value).toBe('all')
    expect(w.find('input[type="search"]').element.value).toBe('')
    expect(row(w, 'a1b2c3').exists()).toBe(true)
    expect(row(w, 'm4n5o6').exists()).toBe(true)
  })

  it('Escape in the search box clears the query first, then leaves the box', async () => {
    const w = await mountTab({ a1b2c3: 'applied' }, { attach: true })
    const input = w.find('input[type="search"]')
    input.element.focus()
    await input.setValue('grab')
    await input.trigger('keydown', { key: 'Escape' })
    expect(input.element.value).toBe('')
    expect(document.activeElement).toBe(input.element)
    await input.trigger('keydown', { key: 'Escape' })
    expect(document.activeElement).not.toBe(input.element)
  })
})

describe('applications.js helpers', () => {
  const NOW = Date.parse('2026-10-09T12:00:00Z')
  const ev = (at, to_status = 'applied') => ({ at, to_status })

  it('daysSince is whole days, and null for an unreadable stamp', () => {
    expect(daysSince('2026-10-09T11:00:00', NOW)).toBe(0)
    expect(daysSince('2026-10-08T12:00:00', NOW)).toBe(1)
    expect(daysSince('2026-09-24T08:10:00', NOW)).toBe(15)
    expect(daysSince('', NOW)).toBeNull()
    expect(daysSince(null, NOW)).toBeNull()
    expect(daysSince('not a date', NOW)).toBeNull()
  })

  it('ageLabel says today, 1 day and N days, and nothing for a row with no events', () => {
    expect(ageLabel({ events: [ev('2026-10-09T08:00:00')] }, NOW)).toBe('Applied · today')
    expect(ageLabel({ events: [ev('2026-10-08T08:00:00')] }, NOW)).toBe('Applied · 1 day')
    expect(ageLabel({ events: [ev('2026-10-06T08:00:00', 'interviewing')] }, NOW)).toBe('Interviewing · 3 days')
    expect(ageLabel({ events: [] }, NOW)).toBe('')
    expect(ageLabel({}, NOW)).toBe('')
  })

  it('ageLabel keeps the stage when the time is unreadable, and a future stamp reads today', () => {
    expect(ageLabel({ events: [ev('garbage', 'offer')] }, NOW)).toBe('Offer')
    expect(ageLabel({ events: [ev('2026-10-10T08:00:00')] }, NOW)).toBe('Applied · today')
  })

  it('needsFollowUp: applied only, from the threshold on, never on an unreadable stamp', () => {
    expect(FOLLOW_UP_DAYS).toBe(14)
    const applied = at => ({ status: 'applied', events: [ev(at)] })
    expect(needsFollowUp(applied('2026-09-25T12:00:00'), NOW)).toBe(true)    // exactly 14 days
    expect(needsFollowUp(applied('2026-09-25T12:00:01'), NOW)).toBe(false)   // 13 days 23 h
    expect(needsFollowUp({ status: 'interviewing', events: [ev('2026-01-01T00:00:00')] }, NOW)).toBe(false)
    expect(needsFollowUp({ status: 'applied', events: [] }, NOW)).toBe(false)
  })

  it('lastAt prefers the newest event, then updated_at, then applied_at', () => {
    expect(lastAt({ events: [ev('a'), ev('b')], updated_at: 'u' })).toBe('b')
    expect(lastAt({ events: [], updated_at: 'u', applied_at: 'p' })).toBe('u')
    expect(lastAt({ applied_at: 'p' })).toBe('p')
    expect(lastAt({})).toBe('')
  })

  it('isActive is false only for rejected and withdrawn', () => {
    for (const s of ['to_apply', 'applied', 'interviewing', 'offer', 'on_hold']) expect(isActive({ status: s })).toBe(true)
    for (const s of ['rejected', 'withdrawn']) expect(isActive({ status: s })).toBe(false)
  })

  it('secondLine joins location and a closed posting, skipping what is empty', () => {
    expect(secondLine({ location: 'Singapore', closed_at: '2026-10-01' })).toBe('Singapore · Posting closed')
    expect(secondLine({ location: 'Singapore' })).toBe('Singapore')
    expect(secondLine({ closed_at: '2026-10-01' })).toBe('Posting closed')
    expect(secondLine({})).toBe('')
  })
})
