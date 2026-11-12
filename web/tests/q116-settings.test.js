// Q-116 pins (design section 8): the one Settings page. Routes (desktop, phone, the
// Appearance alias, a row id in the hash), the save-on-change round trip with its refusals,
// the Automatic-submit confirm, a switch row, "the hub is mounted only on Accounts", no
// Settings row id equal to a hub id, and the Preferences rows staying in step with the
// keyboard shortcuts and the Companies density. The Q-100 pins (one /api/connections fetch,
// no PUT on load, read-only without writable: true, mailbox chip + link, Accounts badge,
// human-check wording) live on in q100-settings.test.js, retargeted.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ConnectionsHub from '../src/components/ConnectionsHub.vue'
import WatchedCompanies from '../src/components/WatchedCompanies.vue'
import { DENSITY_KEY } from '../src/density.js'
import { SHORTCUTS_EVENT, SHORTCUTS_KEY, setShortcutsEnabled } from '../src/shortcuts.js'
import Settings from '../src/tabs/Settings.vue'
import sample from './fixtures/connections.sample.json'
import { fakeApi, setHash } from './helpers.js'
import { mailView } from './mailFake.js'
import { cloneSample, routeFetch } from './q100Fake.js'

enableAutoUnmount(afterEach)
beforeEach(() => {
  window.localStorage.clear()
  setHash('')
})
afterEach(() => {
  vi.unstubAllGlobals()
  delete window.matchMedia
  window.localStorage.clear()
  setHash('')
})

const W = {
  mode: 'dry_run', writable: true, daily_cap: 5, per_employer_daily_cap: 2, headed: false,
  captcha_wait_s: 120, compose_enabled: false,
}
const SUMMARY = { missing: ['profile.phone'], completeness: { filled: 1, needed: 2 }, form: null }

// Settings against a server with the apply routes switched on (writable) unless overridden.
function server(routes = {}) {
  const base = fakeApi()
  return routeFetch({
    'GET connections': cloneSample(sample),
    'GET mail': mailView({ accounts: [] }),
    'GET apply/status': { mode: 'dry_run', missing: [], busy: false },
    'GET apply/settings': W,
    'GET applicant': SUMMARY,
    ...routes,
  }, { fallback: base.fetch })
}
async function settings(hash = '') {
  setHash(hash)
  const w = mount(Settings, { props: { run: 'all', jobs: [] }, attachTo: document.body })
  await flushPromises()
  return w
}
function phone() {
  window.matchMedia = vi.fn(query => ({
    matches: query === '(max-width: 640px)', media: query,
    addEventListener: () => {}, removeEventListener: () => {}, addListener: () => {}, removeListener: () => {},
  }))
}
const tabs = w => w.findAll('[role="tab"]')
const selected = w => tabs(w).filter(t => t.attributes('aria-selected') === 'true').map(t => t.find('.rail-name').text())
const rowIds = w => w.findAll('.setting').map(r => r.attributes('id').replace(/^setting-/, ''))
const rowBtn = (w, id) => w.find(`#setting-${id} .setting-main`)
const value = (w, id) => w.find(`#setting-${id} .setting-value`).text()
const puts = api => api.of('PUT', 'apply/settings')
const hashChange = async hash => {
  setHash(hash)
  window.dispatchEvent(new HashChangeEvent('hashchange'))
  await flushPromises()
}

describe('Q-116 routes', () => {
  it('desktop: #/settings is Accounts (hash left alone); an unknown view becomes #/settings/accounts', async () => {
    server()
    let w = await settings('#/settings')
    expect(selected(w)).toEqual(['Accounts'])
    expect(w.find('.hub').exists()).toBe(true)
    expect(w.find('nav.cat-list').exists()).toBe(false)
    expect(window.location.hash).toBe('#/settings')
    w.unmount()
    w = await settings('#/settings/bogus')
    expect(selected(w)).toEqual(['Accounts'])
    expect(window.location.hash).toBe('#/settings/accounts')
  })

  it('phone: #/settings is the category list; a drill-in sets #/settings/<id>; Back returns to the list', async () => {
    phone()
    server()
    const w = await settings('#/settings')
    const list = w.find('nav.cat-list')
    expect(list.attributes('aria-label')).toBe('Settings categories')
    expect(list.findAll('a.cat-link').map(a => a.attributes('href'))).toEqual([
      '#/settings/accounts', '#/settings/apply', '#/settings/search', '#/settings/preferences',
    ])
    expect(w.find('[role="tablist"]').exists()).toBe(false)             // no rail on a phone
    expect(w.find('.hub').exists()).toBe(false)                         // the list is not a category

    await list.find('#settings-list-apply').trigger('click')            // an anchor: the browser sets the hash
    await vi.waitFor(() => expect(window.location.hash).toBe('#/settings/apply'))
    await flushPromises()
    expect(w.find('nav.cat-list').exists()).toBe(false)
    expect(w.find('#settings-panel-apply').exists()).toBe(true)
    expect(w.find('.cat-title').text()).toBe('Apply')
    const back = w.find('a.back-link')
    expect(back.attributes('href')).toBe('#/settings')
    expect(back.attributes('aria-label')).toBe('Back to Settings')

    await back.trigger('click')
    await vi.waitFor(() => expect(window.location.hash).toBe('#/settings'))
    await flushPromises()
    expect(w.find('nav.cat-list').exists()).toBe(true)
    expect(w.find('#settings-panel-apply').exists()).toBe(false)
  })

  it('#/settings/appearance is rewritten to #/settings/preferences, on load and on a later hashchange, keeping the row id', async () => {
    server()
    let w = await settings('#/settings/appearance')
    expect(window.location.hash).toBe('#/settings/preferences')
    expect(selected(w)).toEqual(['Preferences'])
    w.unmount()

    w = await settings('#/settings/accounts')
    await hashChange('#/settings/appearance/theme')
    expect(window.location.hash).toBe('#/settings/preferences/theme')
    expect(selected(w)).toEqual(['Preferences'])
    expect(rowBtn(w, 'theme').attributes('aria-expanded')).toBe('true')   // the row id survived the alias
  })

  it('#/settings/apply/daily-cap opens that row and focuses it; an unknown row id opens nothing', async () => {
    server()
    const w = await settings('#/settings/apply/daily-cap')
    expect(selected(w)).toEqual(['Apply'])
    expect(rowBtn(w, 'daily-cap').attributes('aria-expanded')).toBe('true')
    expect(w.find('#setting-daily-cap-field').exists()).toBe(true)
    await vi.waitFor(() => expect(document.activeElement).toBe(rowBtn(w, 'daily-cap').element))
    w.unmount()

    const top = await settings('#/settings/apply/nonsense')
    expect(selected(top)).toEqual(['Apply'])
    expect(top.findAll('.setting.open')).toHaveLength(0)
    expect(top.find('.setting-editor').exists()).toBe(false)
  })
})

describe('Q-116 save on change', () => {
  it('round trip: Applications a day -> "No limit" sends exactly one PUT {daily_cap: 0}, reads "No daily limit", says Saved', async () => {
    const api = server({ 'PUT apply/settings': { ...W, daily_cap: 0 } })
    const w = await settings('#/settings/apply')
    expect(value(w, 'daily-cap')).toBe('5 a day')
    await rowBtn(w, 'daily-cap').trigger('click')
    const noLimit = w.findAll('#setting-daily-cap-editor .preset').find(b => b.text() === 'No limit')
    await noLimit.trigger('click')
    await flushPromises()
    expect(puts(api).map(c => c.body)).toEqual([{ daily_cap: 0 }])
    expect(api.calls.filter(c => c.method !== 'GET')).toHaveLength(1)
    expect(value(w, 'daily-cap')).toBe('No daily limit')
    expect(w.find('#setting-daily-cap .setting-saved').text()).toContain('Saved')   // a hidden suffix follows the word
    expect(w.find('#setting-daily-cap').attributes('aria-busy')).toBeUndefined()
  })

  it('refusals: a 422 shows its message under the row and keeps the old value and the form; an invalid number sends nothing', async () => {
    const answers = [
      [422, { detail: 'invalid', errors: [{ field: 'daily_cap', message: 'daily_cap must be at most 500' }] }],
    ]
    const api = server({ 'PUT apply/settings': () => answers.shift() })
    const w = await settings('#/settings/apply')
    await rowBtn(w, 'daily-cap').trigger('click')
    await w.find('#setting-daily-cap-field').setValue('20')
    await w.find('#setting-daily-cap-field').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(puts(api)).toHaveLength(1)
    expect(w.find('#setting-daily-cap [role="alert"]').text()).toBe("Couldn't save: daily_cap must be at most 500.")
    expect(value(w, 'daily-cap')).toBe('5 a day')                       // the old value is kept
    expect(w.find('#setting-daily-cap .setting-saved').exists()).toBe(false)
    expect(w.find('#setting-daily-cap-field').exists()).toBe(true)      // the form is still there ...
    expect(rowBtn(w, 'per-employer-cap').attributes('aria-expanded')).toBe('false')   // ... and the other rows still edit
    expect(w.find('#setting-daily-cap').attributes('aria-busy')).toBeUndefined()

    await w.find('#setting-daily-cap-field').setValue('12.5')
    await w.find('#setting-daily-cap-field').trigger('keydown', { key: 'Enter' })
    await w.find('#setting-daily-cap-field').setValue('abc')
    await w.find('#setting-daily-cap-field').trigger('focusout', { relatedTarget: document.body })
    await flushPromises()
    expect(w.find('#setting-daily-cap .field-error').text()).toBe('Enter a whole number.')
    expect(puts(api)).toHaveLength(1)                                    // still only the first one
  })

  it('Automatic submit: nothing is sent until "Switch to automatic submit"; "Keep dry run" sends nothing; confirming sends {mode: "auto"}; Dry run never asks', async () => {
    const api = server({ 'PUT apply/settings': body => ({ ...W, ...body }) })
    const w = await settings('#/settings/apply')
    await rowBtn(w, 'mode').trigger('click')
    const auto = () => w.find('input[name="apply-mode"][value="auto"]')

    await auto().setValue(true)
    await flushPromises()
    expect(w.find('.confirm-auto').attributes('role')).toBe('group')
    expect(w.find('.confirm-title').text()).toBe('Submit applications automatically?')
    expect(w.find('.confirm-yes').text()).toBe('Switch to automatic submit')
    expect(puts(api)).toHaveLength(0)
    expect(value(w, 'mode')).toBe('Dry run')                             // still the saved mode

    await w.find('.confirm-no').trigger('click')                         // Keep dry run
    await flushPromises()
    expect(puts(api)).toHaveLength(0)
    expect(w.find('.confirm-auto').exists()).toBe(false)
    expect(value(w, 'mode')).toBe('Dry run')

    await auto().setValue(true)
    await flushPromises()
    expect(puts(api)).toHaveLength(0)                                    // asking again still sends nothing
    await w.find('.confirm-yes').trigger('click')
    await flushPromises()
    expect(puts(api).map(c => c.body)).toEqual([{ mode: 'auto' }])
    expect(value(w, 'mode')).toBe('Automatic submit')
    expect(w.find('.confirm-auto').exists()).toBe(false)

    // The way back is never asked about: choosing Dry run sends {mode: 'dry_run'} at once.
    await w.find('input[name="apply-mode"][value="dry_run"]').setValue(true)
    await flushPromises()
    expect(w.find('.confirm-auto').exists()).toBe(false)
    expect(puts(api).map(c => c.body)).toEqual([{ mode: 'auto' }, { mode: 'dry_run' }])
    expect(value(w, 'mode')).toBe('Dry run')
  })

  it('a switch row (Write cover letters) sends {compose_enabled: true} once, and only after the click', async () => {
    const api = server({ 'PUT apply/settings': { ...W, compose_enabled: true } })
    const w = await settings('#/settings/apply')
    const sw = rowBtn(w, 'cover-letters')
    expect(sw.attributes('role')).toBe('switch')
    expect(sw.attributes('aria-checked')).toBe('false')
    expect(puts(api)).toHaveLength(0)
    await sw.trigger('click')
    await flushPromises()
    expect(puts(api).map(c => c.body)).toEqual([{ compose_enabled: true }])
    expect(rowBtn(w, 'cover-letters').attributes('aria-checked')).toBe('true')   // not optimistic: it follows the answer
    expect(value(w, 'cover-letters')).toBe('On')
  })
})

describe('Q-116 hub and ids', () => {
  it('ConnectionsHub is mounted only while Accounts is shown (v-if, not v-show)', async () => {
    server()
    const w = await settings('#/settings/accounts')
    expect(w.findComponent(ConnectionsHub).exists()).toBe(true)
    for (const [i, name] of [[1, 'Apply'], [2, 'Search'], [3, 'Preferences']]) {
      await tabs(w)[i].trigger('click')
      await flushPromises()
      expect(selected(w), name).toEqual([name])
      expect(w.findComponent(ConnectionsHub).exists(), name).toBe(false)
      expect(w.find('.hub, .conn-card, .mail-card').exists(), name).toBe(false)   // not even hidden in the DOM
    }
    await tabs(w)[0].trigger('click')
    await flushPromises()
    expect(w.findComponent(ConnectionsHub).exists()).toBe(true)
    // A row id in the hash must not reach a hub that is not shown: it would scroll and focus its cards.
    const other = await settings('#/settings/apply/mailbox')
    expect(other.findComponent(ConnectionsHub).exists()).toBe(false)
  })

  it('no Settings row id equals a hub item id (the hash item would be ambiguous)', async () => {
    server()
    const w = await settings('#/settings/accounts')
    const mine = []
    for (const i of [1, 2, 3]) {
      await tabs(w)[i].trigger('click')
      await flushPromises()
      mine.push(...rowIds(w))
    }
    expect(mine.sort()).toEqual([
      'batch-size', 'browser-window', 'companies', 'cover-letters', 'cycle', 'daily-cap', 'density', 'details',
      'human-check-wait', 'interests', 'mailbox', 'mode', 'per-employer-cap', 'resume', 'shortcuts', 'theme', 'titles',
    ])
    const hub = new Set([
      ...sample.items.map(i => i.id), 'gmail', 'apply-mailbox', 'edge', 'model', 'employer-accounts',
    ])
    expect(mine.filter(id => hub.has(id) || /^gmail:\d+$/.test(id))).toEqual([])
    expect(new Set(mine).size).toBe(mine.length)                         // and none repeats across categories
  })
})

describe('Q-116 Preferences stay in step with where the setting acts', () => {
  it('the shortcuts row and shortcuts.js follow each other through the window event', async () => {
    server()
    const heard = []
    const listen = e => heard.push(e.detail.on)
    window.addEventListener(SHORTCUTS_EVENT, listen)
    const w = await settings('#/settings/preferences')
    expect(rowBtn(w, 'shortcuts').attributes('aria-checked')).toBe('true')       // on by default
    await rowBtn(w, 'shortcuts').trigger('click')                                // the Settings row -> the key + the event
    expect(window.localStorage.getItem(SHORTCUTS_KEY)).toBe('0')
    expect(heard).toEqual([false])
    expect(rowBtn(w, 'shortcuts').attributes('aria-checked')).toBe('false')
    setShortcutsEnabled(true)                                                    // the Inbox's "Turn on" -> the row follows
    await flushPromises()
    expect(rowBtn(w, 'shortcuts').attributes('aria-checked')).toBe('true')
    expect(window.localStorage.getItem(SHORTCUTS_KEY)).toBe('1')
    window.removeEventListener(SHORTCUTS_EVENT, listen)
  })

  it('the density row writes the key WatchedCompanies reads, and follows its in-place button', async () => {
    server()
    const items = Array.from({ length: 3 }, (_, i) => ({
      company: `Co${i}`, state: 'ok', source: 'watchlist', job_board: 'greenhouse', careers_url: 'https://x.example',
      open_roles: 1, reason: '', kind: '',
    }))
    const companies = mount(WatchedCompanies, { props: { health: { total: 3, counts: {}, items } }, attachTo: document.body })
    expect(companies.find('.dir').classes()).not.toContain('compact')
    const w = await settings('#/settings/preferences')
    expect(DENSITY_KEY).toBe('jobscraper.companies.density')
    await rowBtn(w, 'density').trigger('click')
    expect(window.localStorage.getItem(DENSITY_KEY)).toBe('compact')
    await flushPromises()
    expect(companies.find('.dir').classes()).toContain('compact')                // the open list followed the Settings row
    await companies.find('.density').trigger('click')                            // ... and the other way round
    await flushPromises()
    expect(window.localStorage.getItem(DENSITY_KEY)).toBe('comfortable')
    expect(rowBtn(w, 'density').attributes('aria-checked')).toBe('false')
  })
})
