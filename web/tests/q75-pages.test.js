// Q-75 lane J pins (Companies, Runs, Settings polish): inline Clear-list confirm
// (G26), one set of counts (G25), density (G30; the A-Z jump and source chip went with Q-118 LD), the Runs
// error state (G20), why a run aborted and the failed link (G27), thousands
// separators and plain cadence wording (G37), Settings cycle keys and notices
// that clear (N17), and the theme switch (G40).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import App from '../src/App.vue'
import Companies from '../src/tabs/Companies.vue'
import Runs from '../src/tabs/Runs.vue'
import Settings from '../src/tabs/Settings.vue'
import WatchedCompanies from '../src/components/WatchedCompanies.vue'
import { num, runsPerDayLabel, matchLabel } from '../src/runs.js'
import { THEME_KEY, applyTheme, setTheme, storedTheme } from '../src/theme.js'
import { resetSeenJobs } from '../src/composables/useJob.js'
import { resetDismissed } from '../src/dismissed.js'
import { dismissToast } from '../src/toast.js'
import { chooseMore, companyRows, fakeApi, healthOf, legendItem, legendOf, setHash, utcStamp } from './helpers.js'

let api
function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
  return api
}
beforeEach(() => {
  resetSeenJobs()
  resetDismissed()
  dismissToast()
  window.localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
  setHash('')
  useApi()
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.body.innerHTML = ''
})
enableAutoUnmount(afterEach)

const calls = method => api.calls.filter(c => c.method === method)
const press = (target, key) => {
  const e = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true })
  target.dispatchEvent(e)
  return flushPromises()
}

// ------------------------------------------------------------------ Companies

describe('Companies: Clear list asks in place (G26)', () => {
  async function mountList(companies = [{ name: 'Grab', status: 'found' }, { name: 'OKX', status: 'watched' }]) {
    useApi({ companies })
    const w = mount(Companies, { props: { run: 'all', jobs: [] }, attachTo: document.body })
    await flushPromises()
    return w
  }

  // Q-118 LD: "Clear list…" is an item of the More menu (it was a button in the list head).
  const clearItem = async w => chooseMore(w, 'Clear list…')

  it('Clear list opens a question with Keep list focused first; no window.confirm', async () => {
    const confirmSpy = vi.fn(() => true)
    vi.stubGlobal('confirm', confirmSpy)
    const w = await mountList()
    expect(w.find('.clear-ask').exists()).toBe(false)
    await clearItem(w)
    expect(w.find('.clear-ask').exists()).toBe(true)
    expect(w.find('.clear-ask').attributes('role')).toBe('group')
    expect(document.activeElement).toBe(w.find('.keep-list').element)
    expect(calls('DELETE')).toHaveLength(0)
    expect(confirmSpy).not.toHaveBeenCalled()
  })

  it('Keep list closes it with no DELETE, and focus goes back to the More menu button', async () => {
    const w = await mountList()
    await clearItem(w)
    await w.find('.keep-list').trigger('click')
    await flushPromises()
    expect(w.find('.clear-ask').exists()).toBe(false)
    expect(calls('DELETE')).toHaveLength(0)
    expect(document.activeElement).toBe(w.find('button.more-actions').element)
  })

  it('Esc cancels it the same way', async () => {
    const w = await mountList()
    await clearItem(w)
    await press(w.find('.keep-list').element, 'Escape')
    expect(w.find('.clear-ask').exists()).toBe(false)
    expect(calls('DELETE')).toHaveLength(0)
    expect(document.activeElement).toBe(w.find('button.more-actions').element)
  })

  it('the confirm button empties the list with exactly one DELETE', async () => {
    const w = await mountList()
    await clearItem(w)
    api.server.health = healthOf([])                       // the server stops watching what the list added
    await w.find('.confirm-clear').trigger('click')
    await flushPromises()
    expect(calls('DELETE')).toHaveLength(1)
    expect(calls('DELETE')[0].url).toBe('api/companies/list')
    expect(w.find('.empty-title').text()).toBe('No list yet.')
  })
})

describe('Companies: one set of counts (G25)', () => {
  // Q-118 LD: the tiles are gone; the funnel, the legend and the table read the same buckets.
  it('a list name that is already watched is one row, and the funnel, legend and table agree', async () => {
    useApi({
      companies: [{ name: 'Grab', status: 'found' }, { name: 'OKX', status: 'watched' }, { name: 'Stripe', status: 'watched' }, { name: 'Ghost Co', status: 'failed' }],
      health: healthOf(['Grab', 'OKX', 'Stripe'].map(company => ({ company, state: 'ok', reason: '', open_roles: 3, last_scan: utcStamp(1) }))),
    })
    const w = mount(Companies, { props: { run: 'all', jobs: [] } })
    await flushPromises()
    expect(w.findAll('.funnel-n').map(n => n.text())).toEqual(['4', '3', '3', '3'])   // in your list, watched, readable, checked
    expect(legendOf(w)).toEqual([
      ['All', 4], ['Checked this cycle', 3], ['Due for a check', 0], ['Failed', 0], ['No job board found', 1],
    ])
    expect(companyRows(w).map(r => r[0])).toEqual(['Ghost Co', 'Grab', 'OKX', 'Stripe'])
    expect(w.find('.result-line').text()).toContain('4 companies')
  })

  it('shows no "not found" or "waiting" row when every name was found', async () => {
    useApi({
      companies: [{ name: 'Grab', status: 'found' }],
      health: healthOf([{ company: 'Grab', state: 'ok', reason: '', open_roles: 3, last_scan: utcStamp(1) }]),
    })
    const w = mount(Companies, { props: { run: 'all', jobs: [] } })
    await flushPromises()
    expect(companyRows(w)).toEqual([['Grab', 'Checked']])
    expect(legendItem(w, 'Waiting for search')).toBeUndefined()      // hidden at zero
    expect(legendItem(w, 'No job board found').find('.ui-progress-n').text()).toBe('0')
  })
})

describe('WatchedCompanies: density (G30)', () => {
  // The A-Z jump strip and the "your list" source chip went with Q-118 LD (see q118-companies.test.js
  // for the pins that they are gone); the density switch stayed.
  const row = (i, extra = {}) => ({
    company: `${String.fromCharCode(65 + (i % 6))}Co${String(i).padStart(2, '0')}`, state: 'ok', source: 'watchlist',
    job_board: 'greenhouse', careers_url: 'https://x.example', open_roles: 3, reason: '', kind: '', ...extra,
  })
  const mountWith = items => mount(WatchedCompanies, { props: { health: { total: items.length, counts: {}, items } }, attachTo: document.body })

  it('the Compact toggle sets the class, pressed state and a remembered choice', async () => {
    const w = mountWith(Array.from({ length: 5 }, (_, i) => row(i)))
    expect(w.find('table.companies-table').classes()).not.toContain('is-compact')
    expect(w.find('.density').attributes('aria-pressed')).toBe('false')
    await w.find('.density').trigger('click')
    expect(w.find('table.companies-table').classes()).toContain('is-compact')
    expect(w.find('.density').attributes('aria-pressed')).toBe('true')
    expect(window.localStorage.getItem('jobscraper.companies.density')).toBe('compact')
    w.unmount()
    const again = mountWith(Array.from({ length: 5 }, (_, i) => row(i)))   // a new visit
    expect(again.find('table.companies-table').classes()).toContain('is-compact')
    await again.find('.density').trigger('click')
    expect(window.localStorage.getItem('jobscraper.companies.density')).toBe('comfortable')
  })
})

// ----------------------------------------------------------------------- Runs

const aborted = {
  run_no: 1, status: 'aborted_unhealthy', accepted: 0, started_at: '2026-09-23T14:14:00', finished_at: '2026-09-23T14:30:00',
  stats: { companies_due: 1500, postings_seen: 41200, companies_failed: 9 },
}

describe('Runs: error state, aborted reason, separators (G20, G27, G37)', () => {
  const mountRuns = (props = {}) => mount(Runs, { props: { run: 'all', jobs: [], runs: [], ...props } })

  it('a failed run-history load says so with Try again, not "No runs yet."', async () => {
    const w = mountRuns({ runsError: 'boom' })
    await flushPromises()
    expect(w.find('.runs-error').text()).toContain('Could not load your run history: boom')
    expect(w.find('.runs-error').attributes('role')).toBe('alert')
    expect(w.find('.empty-title').exists()).toBe(false)
    await w.find('.runs-error button').trigger('click')
    expect(w.emitted('changed').at(-1)).toEqual([{ runs: true }])
  })

  it('an empty history without an error is still "No runs yet."', async () => {
    const w = mountRuns()
    await flushPromises()
    expect(w.find('.empty-title').text()).toBe('No runs yet.')
    expect(w.find('.runs-error').exists()).toBe(false)
  })

  it('the old `error` prop (the shortlist\'s) is not the run-history error', async () => {
    const w = mountRuns({ error: 'shortlist down' })
    await flushPromises()
    expect(w.find('.runs-error').exists()).toBe(false)
    expect(w.find('.empty-title').text()).toBe('No runs yet.')
  })

  it('end to end: a failing /api/runs shows the error even though the shortlist loads', async () => {
    useApi()
    const real = api.fetch
    vi.stubGlobal('fetch', vi.fn(async (url, init) => (url === 'api/runs'
      ? { ok: false, status: 500, statusText: 'Error', json: async () => ({ detail: 'db locked' }) }
      : real(url, init))))
    setHash('#/runs')
    const w = mount(App, { attachTo: document.body })
    await vi.waitFor(async () => {
      await flushPromises()
      expect(w.find('.runs-error').exists()).toBe(true)
    })
    expect(api.count(/^api\/shortlist/)).toBeGreaterThan(0)    // it did load; that must not clear the error
    await flushPromises()
    expect(w.find('.runs-error').exists()).toBe(true)
    expect(w.find('.empty-title').exists()).toBe(false)
  })

  it('an aborted run says why, in the pill\'s title and for screen readers', async () => {
    const w = mountRuns({ runs: [aborted] })
    await flushPromises()
    // Q-118 LC: the status is a badge (word "Aborted", tone warn) in the status cell.
    const pill = w.find('td.status .ui-badge')
    expect(pill.text()).toBe('Aborted')
    expect(pill.attributes('data-tone')).toBe('warn')
    expect(pill.attributes('title')).toContain('network problem on this computer')
    expect(pill.attributes('title')).toContain('Run again to retry')
    expect(w.find('td.status .visually-hidden').text()).toContain('network problem')
  })

  it('a successful run has no extra note', async () => {
    const w = mountRuns({ runs: [{ ...aborted, run_no: 2, status: 'ok' }] })
    await flushPromises()
    expect(w.find('td.status .ui-badge').text()).toBe('Success')
    expect(w.find('td.status .ui-badge').attributes('title')).toBeUndefined()
    expect(w.find('td.status .visually-hidden').exists()).toBe(false)
  })

  it('counts get thousands separators, in the table and the failed link', async () => {
    const w = mountRuns({ runs: [{ ...aborted, stats: { companies_due: 1500, postings_seen: 41200, companies_failed: 1234 } }] })
    await flushPromises()
    const cells = w.findAll('tr[data-run="1"] td.col-num').map(c => c.text())
    expect(cells).toContain('1,500')
    expect(cells).toContain('41,200')
    expect(w.find('.failed-link').text()).toBe('1,234')
  })

  // Q-78: plural() formats counts with a thousands separator, so title/aria match the visible text.
  it('the failed link title uses the same separators as its text', async () => {
    const w = mountRuns({ runs: [{ ...aborted, stats: { companies_due: 1500, postings_seen: 41200, companies_failed: 1234 } }] })
    await flushPromises()
    expect(w.find('.failed-link').attributes('title')).toContain('1,234 companies could not be read in this run')
  })
})

describe('runs.js: num, matchLabel, runsPerDayLabel (G37)', () => {
  it('num() groups thousands and leaves non-numbers alone', () => {
    expect(num(0)).toBe(0 + '')
    expect(num(999)).toBe('999')
    expect(num(1000)).toBe('1,000')
    expect(num(1234567)).toBe('1,234,567')
    expect(num('41200')).toBe('41,200')
    expect(num(1234.5)).toBe('1,234.5')
    expect(num(undefined)).toBeUndefined()
    expect(num(null)).toBeNull()
    expect(num('n/a')).toBe('n/a')
    expect(num('')).toBe('')
  })

  it('matchLabel() uses singular, plural and separators', () => {
    expect(matchLabel(0)).toBe('0 matches')
    expect(matchLabel(1)).toBe('1 match')
    expect(matchLabel(12345)).toBe('12,345 matches')
  })

  it('runsPerDayLabel() is never "0.6 runs a day"', () => {
    expect(runsPerDayLabel(1.6)).toBe('1.6 runs a day')
    expect(runsPerDayLabel(1)).toBe('1 run a day')
    expect(runsPerDayLabel(2)).toBe('2 runs a day')
    expect(runsPerDayLabel(0.6)).toBe('about 1 run every 2 days')
    expect(runsPerDayLabel(0.5)).toBe('about 1 run every 2 days')
    expect(runsPerDayLabel(0.14)).toBe('about 1 run every 7 days')
    expect(runsPerDayLabel(0.95)).toBe('1 run a day')
    for (const bad of [0, -1, NaN, null, undefined, 'x']) expect(runsPerDayLabel(bad)).toBe('')
  })
})

// ------------------------------------------------------------------- Settings

describe('Settings: the cycle radios (N17)', () => {
  const puts = () => calls('PUT').filter(c => c.url === 'api/settings').map(c => JSON.parse(c.body))
  // Q-116: the cycle is a row of the Search category; its radios exist only once it is open.
  async function mountSettings() {
    setHash('#/settings/search')
    const w = mount(Settings, { props: { run: 'all', jobs: [] }, attachTo: document.body })
    await flushPromises()
    await w.find('#setting-cycle .setting-main').trigger('click')
    await flushPromises()
    return w
  }
  const radio = (w, days) => w.find(`input[name="cycle"][value="${days}"]`)
  const active = w => w.find('.cycle-option.active').attributes('data-days')
  // The row's "Saved" (not the editor's own role=status "selected but not saved" line).
  const saved = w => w.find('#setting-cycle .setting-saved')

  it('a click saves at once', async () => {
    const w = await mountSettings()
    await radio(w, 7).setValue(true)
    await flushPromises()
    expect(puts()).toEqual([{ cycle_days: 7 }])
    expect(saved(w).text()).toContain('Saved')
    expect(w.find('#setting-cycle .setting-value').text()).toBe('Weekly')
    expect(w.find('.cycle-pending').exists()).toBe(false)
  })

  it('an arrow key only holds the choice: it says so, and nothing is saved yet', async () => {
    const w = await mountSettings()
    await radio(w, 7).trigger('keydown', { key: 'ArrowRight' })
    await radio(w, 7).setValue(true)
    await flushPromises()
    expect(puts()).toEqual([])
    expect(active(w)).toBe('7')
    expect(w.find('.cycle-pending').text()).toContain('Weekly is selected but not saved')
    expect(w.find('.cycle-pending').attributes('role')).toBe('status')
  })

  it('arrowing through several holds the last one; Enter saves just that', async () => {
    const w = await mountSettings()
    for (const d of [30, 7]) {
      await radio(w, d).trigger('keydown', { key: 'ArrowRight' })
      await radio(w, d).setValue(true)
    }
    await radio(w, 7).trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(puts()).toEqual([{ cycle_days: 7 }])
    expect(w.find('.cycle-pending').exists()).toBe(false)
  })

  it('Esc drops the held choice, closes the row and restores the saved one', async () => {
    const w = await mountSettings()
    await radio(w, 7).trigger('keydown', { key: 'ArrowRight' })
    await radio(w, 7).setValue(true)
    expect(w.find('.cycle-pending').exists()).toBe(true)
    await radio(w, 7).trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(w.find('#setting-cycle-editor').exists()).toBe(false)        // Q-116: Esc also closes the row
    expect(w.find('#setting-cycle .setting-value').text()).toBe('Fortnightly')
    expect(puts()).toEqual([])
    await w.find('#setting-cycle .setting-main').trigger('click')       // reopen: the held choice is gone
    await flushPromises()
    expect(active(w)).toBe('14')
    expect(radio(w, 14).element.checked).toBe(true)
    expect(radio(w, 7).element.checked).toBe(false)
    expect(w.find('.cycle-pending').exists()).toBe(false)
  })

  it('leaving the group (blur) saves the held choice; moving inside it does not', async () => {
    const w = await mountSettings()
    const group = w.find('.cycle-options')
    await radio(w, 7).trigger('keydown', { key: 'ArrowRight' })
    await radio(w, 7).setValue(true)
    await group.trigger('focusout', { relatedTarget: radio(w, 14).element })   // still inside
    expect(puts()).toEqual([])
    await group.trigger('focusout', { relatedTarget: null })
    await flushPromises()
    expect(puts()).toEqual([{ cycle_days: 7 }])
  })

  it('arrowing back to the saved value holds nothing', async () => {
    const w = await mountSettings()
    await radio(w, 14).trigger('keydown', { key: 'ArrowLeft' })
    await radio(w, 14).setValue(true)
    expect(w.find('.cycle-pending').exists()).toBe(false)
  })

  it('a Saved notice goes when the owner chooses again', async () => {
    const w = await mountSettings()
    await radio(w, 7).setValue(true)
    await flushPromises()
    expect(saved(w).exists()).toBe(true)
    await radio(w, 3).trigger('keydown', { key: 'ArrowLeft' })
    await radio(w, 3).setValue(true)
    expect(saved(w).exists()).toBe(false)
  })
})

describe('Settings: notices clear when the number is edited (N17)', () => {
  const input = w => w.find('#batch-size')
  async function mountSettings() {
    setHash('#/settings/search')   // Q-100: the number field is in the Search view
    const w = mount(Settings, { props: { run: 'all', jobs: [] } })
    await flushPromises()
    await w.find('#setting-batch-size .setting-main').trigger('click')   // Q-116: open the row
    await flushPromises()
    return w
  }
  const enter = w => input(w).trigger('keydown', { key: 'Enter' })       // Q-116: Enter saves, no form
  const status = w => w.find('#setting-batch-size [role="status"]')
  const rowError = w => w.find('#setting-batch-size [role="alert"]')

  it('Saved goes as soon as the number changes', async () => {
    const w = await mountSettings()
    await input(w).setValue('25')
    await enter(w)
    await flushPromises()
    expect(status(w).text()).toContain('Saved')
    expect(status(w).text()).toContain('25 companies')
    await input(w).setValue('26')
    expect(status(w).exists()).toBe(false)
  })

  it('an error goes the same way', async () => {
    const w = await mountSettings()
    const real = api.fetch
    vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => (init.method === 'PUT' && url === 'api/settings'
      ? { ok: false, status: 500, statusText: 'Error', json: async () => ({ detail: 'disk full' }) }
      : real(url, init))))
    await input(w).setValue('25')
    await enter(w)
    await flushPromises()
    expect(rowError(w).text()).toContain("Couldn't save")
    expect(rowError(w).text()).toContain('Your previous setting is kept')
    await input(w).setValue('26')
    expect(rowError(w).exists()).toBe(false)
  })

  it('the cadence sentences read plainly', async () => {
    const w = await mountSettings()
    expect(w.find('#batch-size-hint').text()).toBe('A full 14-day sweep takes 1.6 runs a day at this size (23 runs to cover 224 companies).')
    await input(w).setValue('25')
    expect(w.find('#batch-size-hint').text()).toBe('A full 14-day sweep takes about 1 run every 2 days at this size (9 runs to cover 224 companies).')
    expect(w.text()).not.toMatch(/0\.\d+ runs/)
  })
})

// ---------------------------------------------------------------------- Theme

describe('Settings: theme switch (G40)', () => {
  const mountSettings = async () => {
    setHash('#/settings/preferences')   // Q-116: Preferences (was Appearance) holds the theme row
    const w = mount(Settings, { props: { run: 'all', jobs: [] } })
    await flushPromises()
    await w.find('#setting-theme .setting-main').trigger('click')   // the radios render once the row is open
    await flushPromises()
    return w
  }
  const theme = (w, id) => w.find(`input[name="theme"][value="${id}"]`)

  it('offers Light, Dark and System, on System by default', async () => {
    const w = await mountSettings()
    expect(w.findAll('input[name="theme"]').map(i => i.element.value)).toEqual(['light', 'dark', 'system'])
    expect(theme(w, 'system').element.checked).toBe(true)
  })

  it('Dark sets data-theme on <html> and remembers it; System removes both', async () => {
    const w = await mountSettings()
    await theme(w, 'dark').setValue(true)
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(window.localStorage.getItem(THEME_KEY)).toBe('dark')
    await theme(w, 'light').setValue(true)
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
    expect(window.localStorage.getItem(THEME_KEY)).toBe('light')
    await theme(w, 'system').setValue(true)
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
    expect(window.localStorage.getItem(THEME_KEY)).toBeNull()
  })

  it('opens on the remembered choice', async () => {
    window.localStorage.setItem(THEME_KEY, 'dark')
    const w = await mountSettings()
    expect(theme(w, 'dark').element.checked).toBe(true)
  })

  it('blocked storage: it still applies for this page and nothing throws', () => {
    const boom = () => { throw new Error('SecurityError') }
    const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(boom)
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(boom)
    const del = vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(boom)
    expect(storedTheme()).toBe('system')
    expect(() => setTheme('dark')).not.toThrow()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(() => setTheme('system')).not.toThrow()
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
    get.mockRestore(); set.mockRestore(); del.mockRestore()
  })

  it('storedTheme() ignores junk, and applyTheme() ignores unknown names', () => {
    window.localStorage.setItem(THEME_KEY, 'neon')
    expect(storedTheme()).toBe('system')
    applyTheme('dark')
    applyTheme('neon')
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
  })
})
