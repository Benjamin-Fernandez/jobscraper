// Q-75 lane I pins (the shell and the Inbox): the keyboard layer (N16: "g" then a
// letter, "?" sheet, "/"), Z undo (G3r), the Profile badge (N7), the Inbox's
// dismissable write error (N20) and local-time stamps (G18). Product first: the
// whole App is mounted and driven by key events, as a user would.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import App from '../src/App.vue'
import { TABS as tabs } from '../src/tabs.js'
import { createShellKeys, GO_WINDOW_MS, SHORTCUTS_KEY, goKeysOf } from '../src/shortcuts.js'
import { exactTime, shortDate, when } from '../src/format.js'
import { resetDismissed } from '../src/dismissed.js'
import { resetSeenJobs } from '../src/composables/useJob.js'
import { dismissToast } from '../src/toast.js'
import { fakeApi, pinZone, setHash } from './helpers.js'

pinZone()   // UTC+8, whatever the machine is

let api
const QUESTIONS = () => ({ groups: [{ key: 'a', status: 'open' }, { key: 'b', status: 'open' }, { key: 'c', status: 'answered' }] })

function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
}

beforeEach(() => {
  pinZone()
  setHash('#/inbox')
  resetSeenJobs()
  resetDismissed()
  dismissToast()
  window.localStorage.clear()
  useApi({ questions: QUESTIONS() })
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  dismissToast()
  document.body.innerHTML = ''
})
enableAutoUnmount(afterEach)

// A key press as the browser would deliver it: to the window, via the target.
function press(key, init = {}, target = window) {
  const e = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init })
  target.dispatchEvent(e)
  return flushPromises().then(() => e)
}

async function mountApp() {
  const w = mount(App, { attachTo: document.body })
  await vi.waitFor(async () => {
    await flushPromises()
    expect(w.findAll('.inbox .card').length).toBeGreaterThan(0)
  })
  return w
}

const writes = (method, prefix = 'api/applications/') =>
  api.calls.filter(c => c.method === method && c.url.startsWith(prefix))

describe('go-to keys (N16)', () => {
  const TARGETS = { o: 'overview', i: 'inbox', a: 'applications', r: 'runs', c: 'companies', p: 'profile', s: 'settings', d: 'developer' }

  it('the registry gives every tab its letter', () => {
    expect(Object.fromEntries(goKeysOf(tabs).map(k => [k.key, k.id]))).toEqual(TARGETS)
  })

  it('"g" then a letter goes to that tab; the panel takes the focus', async () => {
    // Pin the Profile view. With none remembered, Profile probes the server on its first
    // visit and, when answers are waiting (QUESTIONS has two open), switches itself to
    // Application details and rewrites the hash to `#/profile/details`. That lands a few
    // fetches after the key press, so the hash assertion below passed or failed on timing
    // (the flake seen only in full runs under load). A remembered view is the owner's
    // choice, so Profile leaves it and the hash stays `#/profile`.
    window.localStorage.setItem('profile.view', 'resume')
    await mountApp()
    for (const [letter, id] of Object.entries(TARGETS)) {
      // Start each hop from somewhere else so that going "to" the same tab proves nothing.
      const from = id === 'overview' ? 'runs' : 'overview'
      setHash(`#/${from}`)
      window.dispatchEvent(new HashChangeEvent('hashchange'))
      // Wait for that tab to be on screen, so no earlier hashchange is still in flight
      // when the key goes in.
      await vi.waitFor(() => expect(document.querySelector('main.panel')?.id).toBe(`panel-${from}`))
      await press('g')
      await press(letter)
      expect(window.location.hash, `g ${letter}`).toBe(`#/${id}`)
      await vi.waitFor(() => expect(document.activeElement?.id).toBe(`panel-${id}`))
    }
  })

  it('a go-to key does not also reach the Inbox (g then a is not "applied")', async () => {
    await mountApp()
    await press('g')
    await press('a')
    expect(window.location.hash).toBe('#/applications')
    expect(writes('POST')).toHaveLength(0)
  })

  it('the sequence lapses after 1.5 s, and the second key then does nothing', async () => {
    await mountApp()
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-09-24T08:00:00Z'))
    await press('g')
    vi.setSystemTime(new Date(Date.now() + GO_WINDOW_MS + 100))
    await press('r')
    expect(window.location.hash).toBe('#/inbox')
    // ...but within the window it works.
    await press('g')
    vi.setSystemTime(new Date(Date.now() + GO_WINDOW_MS - 200))
    await press('r')
    expect(window.location.hash).toBe('#/runs')
  })

  it('is ignored while typing, and typing disarms a pending "g"', async () => {
    const w = await mountApp()
    const box = w.find('input[type=search]').element
    await press('g', {}, box)
    await press('r', {}, box)
    expect(window.location.hash).toBe('#/inbox')
    // "g" outside, a keystroke in a field, then the letter outside: lapsed.
    await press('g')
    await press('x', {}, box)
    await press('r')
    expect(window.location.hash).toBe('#/inbox')
  })

  it('leaves Ctrl/Meta/Alt chords to the browser', async () => {
    await mountApp()
    await press('g', { ctrlKey: true })
    await press('r')
    await press('g')
    await press('r', { metaKey: true })
    expect(window.location.hash).toBe('#/inbox')
  })

  it('"g" follows the single-key switch; "?" does not', async () => {
    window.localStorage.setItem(SHORTCUTS_KEY, '0')
    await mountApp()
    await press('g')
    await press('r')
    expect(window.location.hash).toBe('#/inbox')
    await press('?')
    expect(document.querySelector('[role=dialog]')).not.toBeNull()
  })

  it('"/" focuses the open tab\'s search box', async () => {
    const w = await mountApp()
    await press('/')
    expect(document.activeElement).toBe(w.find('input[type=search]').element)
  })
})

describe('createShellKeys on its own', () => {
  it('uses the clock it is given for the window', () => {
    let t = 1000
    const seen = []
    const k = createShellKeys({ tabs, go: id => seen.push(id), toggleHelp() {}, focusSearch: () => false, now: () => t })
    const ev = key => ({ key, target: document.body, preventDefault() {}, stopPropagation() {} })
    k.onKeydown(ev('g')); t += GO_WINDOW_MS
    k.onKeydown(ev('s'))
    k.onKeydown(ev('g')); t += GO_WINDOW_MS + 1
    k.onKeydown(ev('d'))
    expect(seen).toEqual(['settings'])
  })
})

describe('the "?" sheet (N16)', () => {
  const dialog = () => document.querySelector('[role=dialog]')

  it('opens with focus on Close, lists the keys, and marks the page behind inert', async () => {
    const w = await mountApp()
    await press('?')
    expect(dialog()).not.toBeNull()
    expect(dialog().getAttribute('aria-modal')).toBe('true')
    expect(document.activeElement.textContent).toBe('Close')
    expect(dialog().textContent).toContain('Keyboard shortcuts')
    expect(dialog().textContent).toContain('Go to Settings')
    expect(dialog().textContent).toContain('Undo the last Save')
    expect(w.find('.masthead').attributes('inert')).toBeDefined()
  })

  it('Esc closes it and focus returns to where it was', async () => {
    const w = await mountApp()
    const box = w.find('input[type=search]').element
    box.focus()
    // "?" while typing does not open it (it is a character in a field)...
    await press('?', {}, box)
    expect(dialog()).toBeNull()
    // ...so open it from the page and come back.
    const before = w.find('[role=tab]').element
    before.focus()
    await press('?', {}, before)
    expect(dialog()).not.toBeNull()
    await press('Escape')
    expect(dialog()).toBeNull()
    expect(document.activeElement).toBe(before)
    expect(w.find('.masthead').attributes('inert')).toBeUndefined()
  })

  it('"?" again closes it; a click on the backdrop closes it', async () => {
    await mountApp()
    await press('?')
    await press('?')
    expect(dialog()).toBeNull()
    await press('?')
    document.querySelector('.sheet-backdrop').dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    await flushPromises()
    expect(dialog()).toBeNull()
  })

  it('Tab cycles inside the dialog (focus trap)', async () => {
    await mountApp()
    await press('?')
    const close = document.activeElement
    expect(close.textContent).toBe('Close')
    const switchBox = dialog().querySelector('input[type=checkbox]')
    // Shift+Tab from the first control wraps to the last...
    const back = await press('Tab', { shiftKey: true }, close)
    expect(back.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(switchBox)
    // ...and Tab from the last wraps to the first.
    const fwd = await press('Tab', {}, switchBox)
    expect(fwd.defaultPrevented).toBe(true)
    expect(document.activeElement).toBe(close)
  })

  it('no Inbox key or go-to key works behind it (S does not save, g r does not go)', async () => {
    await mountApp()
    await press('?')
    await press('s')
    await press('g')
    await press('r')
    expect(writes('POST')).toHaveLength(0)
    expect(window.location.hash).toBe('#/inbox')
  })

  it('the switch writes the shared key and updates an open Inbox at once', async () => {
    const w = await mountApp()
    expect(w.findAll('.shortcuts kbd').length).toBeGreaterThan(0)
    await press('?')
    const sw = dialog().querySelector('input[type=checkbox]')
    sw.checked = false
    sw.dispatchEvent(new Event('change', { bubbles: true }))
    await flushPromises()
    expect(window.localStorage.getItem(SHORTCUTS_KEY)).toBe('0')
    await press('Escape')
    await press('s')
    expect(writes('POST')).toHaveLength(0)             // Inbox keys are off now
    expect(w.findAll('.shortcuts kbd')).toHaveLength(0)  // and the Inbox's hint line knows
    expect(w.find('button.save').attributes('aria-keyshortcuts')).toBeUndefined()
  })
})

describe('Z undoes the last Save, Applied or Not interested (G3r)', () => {
  it('S then Z removes the application again (DELETE), once', async () => {
    await mountApp()
    await press('s')
    expect(writes('POST')).toHaveLength(1)
    await press('z')
    expect(writes('DELETE')).toHaveLength(1)
    expect(writes('DELETE')[0].url).toBe(writes('POST')[0].url)
    await press('z')
    expect(writes('DELETE')).toHaveLength(1)           // spent
  })

  it('Z with nothing done does nothing', async () => {
    await mountApp()
    await press('z')
    expect(api.calls.filter(c => c.method !== 'GET')).toHaveLength(0)
  })

  it('X then Z brings a Not interested role back (DELETE dismissal)', async () => {
    await mountApp()
    await press('x')
    expect(api.calls.some(c => c.method === 'PUT' && c.url.startsWith('api/dismissals/'))).toBe(true)
    await press('z')
    expect(api.calls.some(c => c.method === 'DELETE' && c.url.startsWith('api/dismissals/'))).toBe(true)
  })

  it('after 60 s there is nothing to undo', async () => {
    await mountApp()
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-09-24T08:00:00Z'))
    await press('s')
    vi.setSystemTime(new Date(Date.now() + 61000))
    await press('z')
    expect(writes('DELETE')).toHaveLength(0)
  })

  it('is ignored while typing in a field', async () => {
    const w = await mountApp()
    await press('s')
    await press('z', {}, w.find('input[type=search]').element)
    expect(writes('DELETE')).toHaveLength(0)
  })
})

describe('the Profile badge counts open question groups (N7)', () => {
  const badge = w => w.find('[data-tab=profile] .badge')

  it('shows the open groups only, and says what it counts', async () => {
    const w = await mountApp()
    await vi.waitFor(() => expect(badge(w).text()).toContain('2'))
    expect(w.find('[data-tab=profile]').text()).toContain('open questions')
  })

  it('shows none when the server has no questions route (404)', async () => {
    useApi()                                           // questions: null -> 404
    const w = await mountApp()
    await flushPromises()
    expect(api.calls.some(c => c.url.startsWith('api/questions'))).toBe(true)
    expect(badge(w).exists()).toBe(false)
  })

  it('shows none when there are no open groups', async () => {
    useApi({ questions: { groups: [{ key: 'c', status: 'answered' }] } })
    const w = await mountApp()
    await flushPromises()
    expect(badge(w).exists() ? badge(w).text() : '').not.toMatch(/[1-9]/)
  })

  it('refreshes when the owner leaves the Profile tab', async () => {
    const questions = QUESTIONS()
    useApi({ questions })
    setHash('#/profile')
    const w = mount(App, { attachTo: document.body })
    await vi.waitFor(async () => { await flushPromises(); expect(badge(w).text()).toContain('2') })
    // The owner answers one on the Profile tab, then goes elsewhere.
    questions.groups.splice(0, 1)
    const before = api.count(/^api\/questions/)
    await press('g')
    await press('i')
    await vi.waitFor(async () => { await flushPromises(); expect(badge(w).exists() ? badge(w).text() : '').toContain('1') })
    expect(api.count(/^api\/questions/)).toBeGreaterThan(before)
  })
})

describe('a failed write shows a dismissable error (N20)', () => {
  it('Dismiss clears it, and the role stays selectable', async () => {
    await mountApp()
    const real = api.fetch
    vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => (
      init.method === 'POST' && url.startsWith('api/applications/')
        ? { ok: false, status: 500, statusText: 'Error', json: async () => ({ detail: 'disk full' }) }
        : real(url, init))))
    await press('s')
    const w = document.querySelector('.write-error')
    expect(w).not.toBeNull()
    expect(w.getAttribute('role')).toBe('alert')
    expect(w.textContent).toContain('Could not update')
    w.querySelector('.write-error-close').dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await flushPromises()
    expect(document.querySelector('.write-error')).toBeNull()
    expect(document.querySelector('.inbox .card')).not.toBeNull()
  })
})

describe('times show in the browser zone, with the UTC original on hover (G18)', () => {
  it('when() and shortDate() convert a zoneless (UTC) stamp to the local zone', () => {
    pinZone('Asia/Singapore', -480)
    expect(when('2026-09-24T08:10:00')).toBe('24 Sep 16:10')
    expect(when('2026-09-24 08:10:05')).toBe('24 Sep 16:10')
    expect(shortDate('2026-09-24T23:10:00')).toBe('25 Sep')            // crosses midnight locally
    pinZone('America/New_York', 240)
    expect(when('2026-09-24T08:10:00')).toBe('24 Sep 04:10')
    expect(shortDate('2026-09-24T02:10:00')).toBe('23 Sep')
    pinZone()
  })

  it('a date alone is shown as written, in every zone', () => {
    for (const [tz, off] of [['Asia/Singapore', -480], ['America/New_York', 240]]) {
      pinZone(tz, off)
      expect(when('2026-09-24')).toBe('24 Sep')
      expect(shortDate('2026-09-24')).toBe('24 Sep')
    }
    expect(when('')).toBe('')
    expect(shortDate(null)).toBe('')
    pinZone()
  })

  it('a stamp that carries its own zone keeps it', () => {
    pinZone('Asia/Singapore', -480)
    expect(when('2026-09-24T08:10:00+08:00')).toBe('24 Sep 08:10')
    expect(when('2026-09-24T08:10:00Z')).toBe('24 Sep 16:10')
    expect(when('2026-09-24 08:10:00-05:00')).toBe('24 Sep 21:10')
  })

  it('exactTime() is the UTC original, whatever the zone', () => {
    for (const [tz, off] of [['Asia/Singapore', -480], ['America/New_York', 240]]) {
      pinZone(tz, off)
      expect(exactTime('2026-09-24T08:10:05')).toBe('2026-09-24 08:10 UTC')
      expect(exactTime('2026-09-24T08:10:00+08:00')).toBe('2026-09-24 00:10 UTC')
    }
    expect(exactTime('2026-09-24')).toBe('')
    expect(exactTime('garbage')).toBe('')
    pinZone()
  })
})
