// Q-70 lane B (Applications): Verify B pins. A move commits on purpose (B3; the Move
// menu since Q-118 LB), the stage tab is remembered (B2; All is the first-visit default
// since D-207), a quiet applied role
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
// Q-118 LB: the status select became the row's status pill, a "Move to" menu button.
const moveTrigger = (w, id) => row(w, id).find('.ui-move-trigger')
const menuItem = (w, id, label) => row(w, id).findAll('[role^="menuitem"]').find(b => b.text().trim() === label)
const menuOf = (w, id) => row(w, id).find('[role="menu"]')
// The row's "⋯" menu: open it and choose an item by its text.
async function more(w, id, label) {
  await row(w, id).find('.app-more-trigger').trigger('click')
  await flushPromises()
  const it = menuItem(w, id, label)
  if (!it) return false
  await it.trigger('click')
  await flushPromises()
  return true
}

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

// Q-118 LB replaced B3's status <select> with the Move menu (MenuButton, kind radio):
// a move commits on Enter, Space or a click only; the arrows only move focus, so the
// old "held keyboard change" has no state to hold. These pins keep B3's intent on the
// menu's keyboard: passing over a status saves nothing, one choice saves once, Escape
// saves nothing, and focus comes back to the pill.
describe('Move to commits on purpose (B3, Q-118 LB)', () => {
  it('opening the menu by keyboard and arrowing through it saves nothing', async () => {
    const w = await mountTab({ a1b2c3: 'applied' }, { attach: true })
    const t = moveTrigger(w, 'a1b2c3')
    expect(t.attributes('aria-expanded')).toBe('false')
    await t.trigger('keydown', { key: 'ArrowDown' })
    await flushPromises()
    expect(t.attributes('aria-expanded')).toBe('true')
    // The current stage is checked and disabled, so focus lands on the first other one.
    expect(document.activeElement.textContent.trim()).toBe('Interviewing')
    await menuOf(w, 'a1b2c3').trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement.textContent.trim()).toBe('Offer')
    await menuOf(w, 'a1b2c3').trigger('keydown', { key: 'ArrowDown' })
    expect(document.activeElement.textContent.trim()).toBe('Rejected')
    await flushPromises()
    expect(posts()).toHaveLength(0)
    expect(row(w, 'a1b2c3').attributes('data-status')).toBe('applied')
  })

  it('passing over a status on the way to another saves only the chosen one', async () => {
    const w = await mountTab({ a1b2c3: 'applied' }, { attach: true })
    await moveTrigger(w, 'a1b2c3').trigger('keydown', { key: 'ArrowDown' })
    await flushPromises()
    for (const key of ['ArrowDown', 'ArrowDown', 'ArrowUp']) await menuOf(w, 'a1b2c3').trigger('keydown', { key })
    expect(document.activeElement.textContent.trim()).toBe('Offer')
    await menuOf(w, 'a1b2c3').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(posts()).toHaveLength(1)
    expect(JSON.parse(posts()[0].body).status).toBe('offer')
  })

  it('Enter commits once, the menu closes, and focus returns to the row\'s pill', async () => {
    const w = await mountTab({ a1b2c3: 'applied' }, { attach: true })
    await moveTrigger(w, 'a1b2c3').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(document.activeElement.textContent.trim()).toBe('Interviewing')
    expect(posts()).toHaveLength(0)
    await menuOf(w, 'a1b2c3').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(posts()).toHaveLength(1)
    expect(row(w, 'a1b2c3').attributes('data-status')).toBe('interviewing')
    expect(menuOf(w, 'a1b2c3').exists()).toBe(false)
    expect(document.activeElement).toBe(moveTrigger(w, 'a1b2c3').element)
  })

  it('Escape closes the menu, saves nothing, and returns focus to the pill', async () => {
    const w = await mountTab({ a1b2c3: 'applied' }, { attach: true })
    await moveTrigger(w, 'a1b2c3').trigger('keydown', { key: 'ArrowDown' })
    await flushPromises()
    await menuOf(w, 'a1b2c3').trigger('keydown', { key: 'ArrowDown' })
    await menuOf(w, 'a1b2c3').trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(menuOf(w, 'a1b2c3').exists()).toBe(false)
    expect(document.activeElement).toBe(moveTrigger(w, 'a1b2c3').element)
    expect(posts()).toHaveLength(0)
    expect(moveTrigger(w, 'a1b2c3').find('.pill').text()).toBe('Applied')
  })

  it('a pointer choice commits once, and the toast Undo restores the status (D-101)', async () => {
    const w = await mountTab({ a1b2c3: 'applied' })
    await moveTrigger(w, 'a1b2c3').trigger('click')
    await flushPromises()
    await menuItem(w, 'a1b2c3', 'Interviewing').trigger('click')
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

// Q-118 LB (D-207): the strip opens on All the first time; Active is one click away.
describe('the stage tabs: All first, Active one click away (B2, Q-118 LB)', () => {
  it('All is the default; Active hides rejected and withdrawn, and counts what it shows', async () => {
    const w = await mountTab({ a1b2c3: 'applied', m4n5o6: 'rejected', j1k2l3: 'withdrawn', g7h8i9: 'to_apply' })
    expect(stageButton(w, 'all').attributes('aria-pressed')).toBe('true')
    for (const id of ['a1b2c3', 'm4n5o6', 'j1k2l3', 'g7h8i9']) expect(row(w, id).exists(), id).toBe(true)
    await stageButton(w, 'active').trigger('click')
    expect(row(w, 'a1b2c3').exists()).toBe(true)
    expect(row(w, 'g7h8i9').exists()).toBe(true)
    expect(row(w, 'm4n5o6').exists()).toBe(false)
    expect(row(w, 'j1k2l3').exists()).toBe(false)
    expect(stageButton(w, 'active').find('.stage-n').text()).toBe('2')
    expect(stageButton(w, 'all').find('.stage-n').text()).toBe('4')
    await stageButton(w, 'rejected').trigger('click')
    expect(row(w, 'm4n5o6').exists()).toBe(true)
    expect(row(w, 'j1k2l3').exists()).toBe(true)   // withdrawn lives under Rejected
  })

  it('persists the choice across a remount', async () => {
    const w = await mountTab({ a1b2c3: 'applied', m4n5o6: 'rejected' })
    await stageButton(w, 'active').trigger('click')
    expect(window.localStorage.getItem(STAGE_KEY)).toBe('active')
    w.unmount()
    const again = await mountTab({ a1b2c3: 'applied', m4n5o6: 'rejected' })
    expect(stageButton(again, 'active').attributes('aria-pressed')).toBe('true')
    expect(row(again, 'm4n5o6').exists()).toBe(false)
  })

  it('falls back to All for an unknown remembered stage; an old stage opens the tab that holds it', async () => {
    window.localStorage.setItem(STAGE_KEY, 'no_such_stage')
    const w = await mountTab({ a1b2c3: 'applied', m4n5o6: 'rejected' })
    expect(stageButton(w, 'all').attributes('aria-pressed')).toBe('true')
    expect(row(w, 'm4n5o6').exists()).toBe(true)
    expect(window.localStorage.getItem(STAGE_KEY)).toBe('all')
    for (const [old, tab] of [['withdrawn', 'rejected'], ['to_apply', 'active'], ['assessment', 'interviewing']]) {
      window.localStorage.setItem(STAGE_KEY, old)
      const again = await mountTab({ a1b2c3: 'applied' })
      expect(stageButton(again, tab).attributes('aria-pressed'), old).toBe('true')
    }
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
    // Q-118 LB: Remove sits in the row's "⋯" menu, offered on a single-event row only.
    await row(w, 'a1b2c3').find('.app-more-trigger').trigger('click')
    expect(menuItem(w, 'a1b2c3', 'Remove from Applications')).toBeTruthy()
    expect(row(w, 'j1k2l3').find('.history').exists()).toBe(true)
    await row(w, 'j1k2l3').find('.app-more-trigger').trigger('click')
    const labels = row(w, 'j1k2l3').findAll('[role="menuitem"]').map(b => b.text().trim())
    expect(labels).toContain('Show details')
    expect(labels).not.toContain('Remove from Applications')
  })

  it('removes the role, and the toast Undo re-tracks it with its status', async () => {
    const w = await mountTab({ a1b2c3: 'applied', j1k2l3: 'interviewing' })
    expect(await more(w, 'a1b2c3', 'Remove from Applications')).toBe(true)
    expect(api.calls.filter(c => c.method === 'DELETE')).toEqual([])   // A13: Remove asks first
    await row(w, 'a1b2c3').find('.remove-yes').trigger('click')
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
