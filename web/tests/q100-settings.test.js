// Q-100 T1-B pins for lane B's Settings restructure (design sections 1, 4.3, D-191, D-197),
// retargeted to the Q-116 page (rail, rows, save on change): the four categories and where
// each hash lands, the attention count on the Accounts tab, the hub's load/failure handling,
// Settings -> Apply (rows hide while their source is absent, read-only unless
// `writable: true`, never a PUT on load, one PUT per change), and useHashItem going null
// when the hash is another tab's.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ApplySettings from '../src/components/ApplySettings.vue'
import ConnectionsHub from '../src/components/ConnectionsHub.vue'
import Settings from '../src/tabs/Settings.vue'
import { useHashItem } from '../src/route.js'
import sample from './fixtures/connections.sample.json'
import { fakeApi, setHash } from './helpers.js'
import { mailView } from './mailFake.js'
import { cloneSample, routeFetch } from './q100Fake.js'

enableAutoUnmount(afterEach)
beforeEach(() => setHash(''))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  setHash('')
})

// The Settings tab against a server that answers the hub's routes; the older settings
// routes come from fakeApi. `routes` overrides or adds ("METHOD path").
function server(routes = {}) {
  const base = fakeApi()
  return routeFetch({
    'GET connections': cloneSample(sample),
    'GET mail': mailView({ accounts: [] }),
    ...routes,
  }, { fallback: base.fetch })
}
async function settings(hash = '') {
  setHash(hash)
  const w = mount(Settings, { props: { run: 'all', jobs: [] }, attachTo: document.body })
  await flushPromises()
  return w
}
const tabs = w => w.findAll('[role="tab"]')
const tabName = t => t.find('.rail-name').text()
const selected = w => tabs(w).filter(t => t.attributes('aria-selected') === 'true').map(tabName)
const panel = w => w.find('[role="tabpanel"]').attributes('id')
const rowIds = w => w.findAll('.setting').map(r => r.attributes('id').replace(/^setting-/, ''))

describe('Settings: four categories on a rail', () => {
  it('offers Accounts, Apply, Search and Preferences, in that order, as a vertical tablist', async () => {
    server()
    const w = await settings()
    const list = w.find('[role="tablist"]')
    expect(list.attributes('aria-label')).toBe('Settings categories')
    expect(list.attributes('aria-orientation')).toBe('vertical')
    expect(tabs(w).map(t => t.attributes('id'))).toEqual([
      'settings-tab-accounts', 'settings-tab-apply', 'settings-tab-search', 'settings-tab-preferences',
    ])
    expect(tabs(w).map(tabName)).toEqual(['Accounts', 'Apply', 'Search', 'Preferences'])
    expect(w.find('.page-title').text()).toBe('Settings')
    expect(w.find('.page-sub').text()).toBe('Accounts, applying, search and preferences.')
  })

  it.each([
    ['', 'Accounts', 'accounts'],
    ['#/settings', 'Accounts', 'accounts'],
    ['#/settings/accounts', 'Accounts', 'accounts'],
    ['#/settings/apply', 'Apply', 'apply'],
    ['#/settings/search', 'Search', 'search'],
    ['#/settings/preferences', 'Preferences', 'preferences'],
  ])('hash %j opens %s', async (hash, label, id) => {
    server()
    const w = await settings(hash)
    expect(selected(w)).toEqual([label])
    expect(panel(w)).toBe(`settings-panel-${id}`)
    // Only the selected tab is a tab stop.
    expect(tabs(w).filter(t => t.attributes('tabindex') === '0')).toHaveLength(1)
    expect(w.find('[role="tabpanel"]').attributes('aria-labelledby')).toBe(`settings-tab-${id}`)
  })

  it('an unknown view falls back to Accounts and the hash is made canonical', async () => {
    server()
    const w = await settings('#/settings/bogus')
    expect(selected(w)).toEqual(['Accounts'])
    expect(window.location.hash).toBe('#/settings/accounts')
  })

  it('Accounts is the hub (and the Email card moved into it); Search has the cycle and run size rows; Preferences the theme row', async () => {
    server()
    const w = await settings()
    expect(w.find('.hub').exists()).toBe(true)
    expect(w.find('.mail-card.embedded').exists()).toBe(true)
    expect(rowIds(w)).toEqual([])                                       // the hub has no rows of ours
    await tabs(w)[2].trigger('click')
    await flushPromises()
    expect(w.find('.hub').exists()).toBe(false)
    expect(rowIds(w)).toEqual(['cycle', 'batch-size', 'titles', 'interests', 'companies'])
    expect(w.find('input[name="theme"]').exists()).toBe(false)
    await tabs(w)[3].trigger('click')
    await flushPromises()
    expect(rowIds(w)).toEqual(['theme', 'density', 'shortcuts'])
    expect(w.find('#setting-cycle').exists()).toBe(false)
    await w.find('#setting-theme .setting-main').trigger('click')       // the radios appear once the row opens
    expect(w.findAll('input[name="theme"]').map(i => i.element.value)).toEqual(['light', 'dark', 'system'])
  })

  it('clicking a tab selects it and writes the hash without the old view\'s item', async () => {
    server()
    const w = await settings('#/settings/accounts/model')
    await tabs(w)[1].trigger('click')
    expect(selected(w)).toEqual(['Apply'])
    expect(window.location.hash).toBe('#/settings/apply')
    await tabs(w)[0].trigger('click')
    expect(window.location.hash).toBe('#/settings/accounts')
  })

  it('arrow keys (Up/Down and Left/Right), Home and End move between the tabs and focus them', async () => {
    server()
    const w = await settings()
    await tabs(w)[0].trigger('keydown', { key: 'ArrowDown' })
    expect(selected(w)).toEqual(['Apply'])
    expect(document.activeElement.id).toBe('settings-tab-apply')
    await tabs(w)[1].trigger('keydown', { key: 'ArrowRight' })
    expect(selected(w)).toEqual(['Search'])
    await tabs(w)[2].trigger('keydown', { key: 'End' })
    expect(selected(w)).toEqual(['Preferences'])
    await tabs(w)[3].trigger('keydown', { key: 'ArrowDown' })           // wraps
    expect(selected(w)).toEqual(['Accounts'])
    await tabs(w)[0].trigger('keydown', { key: 'ArrowUp' })             // wraps back
    expect(selected(w)).toEqual(['Preferences'])
    await tabs(w)[3].trigger('keydown', { key: 'ArrowLeft' })
    expect(selected(w)).toEqual(['Search'])
    await tabs(w)[2].trigger('keydown', { key: 'Home' })
    expect(selected(w)).toEqual(['Accounts'])
  })

  it('a deep link through Settings focuses the card heading', async () => {
    server()
    await settings('#/settings/accounts/model')
    expect(document.activeElement.id).toBe('conn-model-title')
  })
})

describe('Settings: the attention count on the Accounts tab', () => {
  const badge = w => w.find('#settings-tab-accounts .view-badge')

  it('shows the number of items that need attention', async () => {
    server()
    const w = await settings()
    expect(badge(w).exists()).toBe(true)
    expect(badge(w).find('[aria-hidden="true"]').text()).toBe('8')           // 7 mailboxes + the employer accounts
    expect(badge(w).find('.visually-hidden').text()).toBe('8 need attention')
    expect(w.find('#settings-tab-apply .view-badge').exists()).toBe(false)
  })

  it('no badge when everything is fine', async () => {
    const ok = cloneSample(sample)
    ok.items = ok.items.filter(i => i.kind !== 'gmail').map(i => (i.state === 'attention' ? { ...i, state: 'connected', code: 'ok' } : i))
    server({ 'GET connections': ok })
    const w = await settings()
    expect(badge(w).exists()).toBe(false)
  })

  it.each([
    ['an absent route (404)', undefined],
    ['a server error (500)', [500, { detail: 'boom' }]],
  ])('no badge, and no "all good", after %s', async (_n, answer) => {
    server(answer ? { 'GET connections': answer } : { 'GET connections': [404, { detail: 'Not Found' }] })
    const w = await settings()
    expect(badge(w).exists()).toBe(false)
    expect(w.find('#settings-panel-accounts [role="alert"]').text()).toContain("Couldn't load your connections.")
    expect(w.find('.conn-card').exists()).toBe(false)
  })

  it('a failed load still leaves Gmail reachable, and Try again reloads the hub', async () => {
    let calls = 0
    server({
      'GET connections': () => (++calls === 1 ? [500, { detail: 'boom' }] : cloneSample(sample)),
      'GET mail': mailView({ accounts: [] }),
    })
    const w = await settings()
    expect(w.find('.mail-card').exists()).toBe(true)
    expect(w.find('form.another').exists()).toBe(true)
    await w.find('button.hub-retry').trigger('click')
    await flushPromises()
    expect(calls).toBe(2)
    expect(w.find('.conn-card').exists()).toBe(true)
    expect(w.find('#settings-panel-accounts [role="alert"]').exists()).toBe(false)
    expect(w.find('#settings-tab-accounts .view-badge .visually-hidden').text()).toBe('8 need attention')
  })

  it('connections are fetched once on mount and shared with the Apply view', async () => {
    const api = server({ 'GET apply/status': { mode: 'dry_run', missing: [], busy: false } })
    const w = await settings()
    await tabs(w)[1].trigger('click')
    await flushPromises()
    expect(api.of('GET', 'connections')).toHaveLength(1)
    // the Apply view's mailbox row comes from that same answer
    expect(w.find('#setting-mailbox .state-chip').text()).toBe('Connected')
  })
})

describe('Settings -> Apply: what the page reads (through Settings)', () => {
  const GOOD = {
    mode: 'dry_run', writable: true, daily_cap: 5, per_employer_daily_cap: 2, headed: false,
    captcha_wait_s: 120, compose_enabled: false,
  }

  it.each([404, 405])('every optional source absent (%i): nothing faked, only the links, nothing sent', async code => {
    const api = server({
      'GET apply/status': [code, {}], 'GET apply/settings': [code, {}], 'GET applicant': [code, {}],
    })
    const w = await settings('#/settings/apply')
    expect(rowIds(w)).toEqual(['mailbox', 'resume'])
    expect(w.find('#setting-mailbox a').attributes('href')).toBe('#/settings/accounts/apply-mailbox')
    expect(w.find('#setting-mailbox a').text()).toContain('Manage in Accounts')
    expect(w.find('#settings-panel-apply input, #settings-panel-apply button.setting-main').exists()).toBe(false)
    expect(api.calls.filter(c => c.method !== 'GET')).toEqual([])
  })

  it('loading the page never sends a PUT, even when the server says writable: true (no probe write)', async () => {
    const api = server({
      'GET apply/status': { mode: 'dry_run', missing: [], busy: false },
      'GET apply/settings': GOOD,
    })
    const w = await settings('#/settings/apply')
    expect(w.find('#setting-daily-cap button.setting-main').exists()).toBe(true)      // editable
    expect(api.calls.map(c => c.method).every(m => m === 'GET')).toBe(true)
    expect(api.of('GET', 'apply/settings')).toHaveLength(1)
  })
})

describe('Settings -> Apply (ApplySettings)', () => {
  const GOOD = {
    mode: 'dry_run', writable: false, daily_cap: 5, per_employer_daily_cap: 2, headed: false,
    captcha_wait_s: 120, compose_enabled: false,
  }
  const W = { ...GOOD, writable: true }
  // ApplySettings now takes its data as props (Settings loads it once): `apply` is
  // loadApplyData()'s { status, settings, summary }; `connections` is the hub's answer.
  async function apply({ settings = null, status = null, summary = null, put, connections = cloneSample(sample), item = null } = {}) {
    const api = routeFetch(put ? { 'PUT apply/settings': put } : {})
    const w = mount(ApplySettings, {
      props: { connections, apply: { status, settings, summary }, item },
      attachTo: document.body,
    })
    await flushPromises()
    return { api, w }
  }
  const noCalls = api => api.calls
  const rowBtn = (w, id) => w.find(`#setting-${id} .setting-main`)
  const open = async (w, id) => {
    await rowBtn(w, id).trigger('click')
    await flushPromises()
  }
  const field = (w, id) => w.find(`#setting-${id}-field`)
  const value = (w, id) => w.find(`#setting-${id} .setting-value`).text()
  const enter = (w, id) => field(w, id).trigger('keydown', { key: 'Enter' })
  const putBodies = api => api.of('PUT', 'apply/settings').map(c => c.body)

  it('mode comes from /apply/status when /apply/settings is absent; read-only text', async () => {
    const { api, w } = await apply({ status: { mode: 'dry_run', missing: [], busy: false } })
    expect(rowIds(w)).toContain('mode')
    expect(value(w, 'mode')).toBe('Dry run')
    expect(w.find('#setting-mode button').exists()).toBe(false)
    expect(w.find('#setting-mode').text()).toContain('Set in config.yaml.')
    for (const id of ['browser-window', 'human-check-wait', 'daily-cap', 'per-employer-cap', 'cover-letters']) {
      expect(rowIds(w), id).not.toContain(id)
    }
    expect(noCalls(api)).toEqual([])
  })

  it('auto mode is spelled out', async () => {
    const { w } = await apply({ status: { mode: 'auto', missing: [], busy: false } })
    expect(value(w, 'mode')).toBe('Automatic submit')
  })

  it('read-only when the server does not say writable: true (false, or the key absent, or not a true)', async () => {
    for (const s of [GOOD, (({ writable, ...rest }) => rest)(GOOD), { ...GOOD, writable: 'yes' }]) {
      const { api, w } = await apply({ settings: s })
      expect(rowIds(w)).toEqual([
        'mode', 'browser-window', 'human-check-wait', 'daily-cap', 'per-employer-cap', 'cover-letters', 'mailbox', 'resume',
      ])
      expect(value(w, 'daily-cap')).toBe('5 a day')
      expect(value(w, 'per-employer-cap')).toBe('2 a day')
      expect(value(w, 'browser-window')).toBe('Off')
      expect(value(w, 'human-check-wait')).toBe('Up to 2 min')
      expect(value(w, 'cover-letters')).toBe('Off')
      // The wording on the human-check row: waits for the person, never solves.
      expect(w.find('#setting-human-check-wait').text()).toContain('It never solves one.')
      expect(w.find('#setting-daily-cap').text()).toContain('Set in config.yaml.')
      expect(w.find('input').exists()).toBe(false)
      expect(w.find('button').exists()).toBe(false)                     // no edit row, no switch
      expect(w.find('[role="switch"]').exists()).toBe(false)
      expect(noCalls(api)).toEqual([])
      w.unmount()
    }
  })

  it('writable: true shows the controls; mounting sends nothing at all (no probe write)', async () => {
    const { api, w } = await apply({ settings: W })
    expect(rowBtn(w, 'mode').attributes('aria-expanded')).toBe('false')
    expect(rowBtn(w, 'daily-cap').attributes('aria-expanded')).toBe('false')
    expect(rowBtn(w, 'browser-window').attributes('role')).toBe('switch')
    expect(w.find('input').exists()).toBe(false)                        // editors render when their row opens
    expect(w.find('.apply-save-btn, button.save').exists()).toBe(false) // no Save button anywhere
    expect(noCalls(api)).toEqual([])
    await open(w, 'daily-cap')
    await open(w, 'mode')
    expect(noCalls(api)).toEqual([])                                    // opening a row sends nothing either
  })

  it('a save sends only the changed key, on Enter, and tells the page (saved)', async () => {
    const { api, w } = await apply({ settings: W, put: { ...W, daily_cap: 8 } })
    await open(w, 'daily-cap')
    await field(w, 'daily-cap').setValue('8')
    expect(api.of('PUT', 'apply/settings')).toHaveLength(0)             // typing alone sends nothing
    await enter(w, 'daily-cap')
    await flushPromises()
    expect(putBodies(api)).toEqual([{ daily_cap: 8 }])
    expect(w.emitted('saved')).toHaveLength(1)
    expect(w.emitted('saved')[0][0].daily_cap).toBe(8)
    expect(value(w, 'daily-cap')).toBe('8 a day')
    expect(w.find('#setting-daily-cap .setting-saved').text()).toContain('Saved')
  })

  it('switching to automatic asks first; nothing is sent until confirmed, and Keep dry run sends nothing', async () => {
    const { api, w } = await apply({ settings: W, put: { ...W, mode: 'auto' } })
    await open(w, 'mode')
    await w.find('input[name="apply-mode"][value="auto"]').setValue(true)
    await flushPromises()
    expect(w.find('.confirm-auto').text()).toContain('Submit applications automatically?')
    expect(w.find('.confirm-yes').text()).toBe('Switch to automatic submit')
    expect(w.find('.confirm-no').text()).toBe('Keep dry run')
    expect(api.of('PUT', 'apply/settings')).toHaveLength(0)
    await w.find('.confirm-no').trigger('click')
    expect(api.of('PUT', 'apply/settings')).toHaveLength(0)
    expect(w.find('.confirm-auto').exists()).toBe(false)
    await w.find('input[name="apply-mode"][value="auto"]').setValue(true)
    await w.find('.confirm-yes').trigger('click')
    await flushPromises()
    expect(putBodies(api)).toEqual([{ mode: 'auto' }])
    expect(value(w, 'mode')).toBe('Automatic submit')
  })

  it('a 404 or 405 on save says "Couldn\'t save" and turns every row read-only', async () => {
    for (const status of [404, 405]) {
      const { w } = await apply({ settings: W, put: [status, { detail: 'nope' }] })
      await open(w, 'daily-cap')
      await field(w, 'daily-cap').setValue('9')
      await enter(w, 'daily-cap')
      await flushPromises()
      expect(w.find('#setting-daily-cap [role="alert"]').text()).toContain("Couldn't save: this server doesn't accept changes yet.")
      expect(w.find('input').exists()).toBe(false)
      expect(w.find('button').exists()).toBe(false)
      expect(value(w, 'daily-cap')).toBe('5 a day')
      w.unmount()
    }
  })

  it('a 422 shows the server\'s message for that field under the row, keeps the old value, and does NOT lock the form', async () => {
    const answers = [
      [422, { detail: 'invalid', errors: [{ field: 'daily_cap', message: 'daily_cap is over what this plan allows.' }] }],
      { ...W, daily_cap: 9 },
    ]
    const { api, w } = await apply({ settings: W, put: () => answers.shift() })
    await open(w, 'daily-cap')
    await field(w, 'daily-cap').setValue('9')
    await enter(w, 'daily-cap')
    await flushPromises()
    expect(w.find('#setting-daily-cap [role="alert"]').text()).toBe("Couldn't save: daily_cap is over what this plan allows.")
    expect(value(w, 'daily-cap')).toBe('5 a day')
    expect(w.find('#setting-daily-cap .setting-saved').exists()).toBe(false)
    // not locked: the rows are still controls, and the next try goes through
    expect(rowBtn(w, 'daily-cap').exists()).toBe(true)
    expect(field(w, 'daily-cap').exists()).toBe(true)
    await enter(w, 'daily-cap')
    await flushPromises()
    expect(putBodies(api)).toEqual([{ daily_cap: 9 }, { daily_cap: 9 }])
    expect(value(w, 'daily-cap')).toBe('9 a day')
    expect(w.find('#setting-daily-cap [role="alert"]').exists()).toBe(false)
  })

  it('caps run 0..500 and 0..100 (0 = no limit); out-of-range or non-whole numbers are refused without sending', async () => {
    const { api, w } = await apply({ settings: W })
    await open(w, 'daily-cap')
    for (const [text, reason] of [['501', 'Enter a number from 0 to 500.'], ['-1', 'Enter a whole number.'], ['2.5', 'Enter a whole number.'], ['', 'Enter a whole number.']]) {
      await field(w, 'daily-cap').setValue(text)
      await enter(w, 'daily-cap')
      expect(w.find('#setting-daily-cap .field-error').text(), text).toBe(reason)
      expect(field(w, 'daily-cap').attributes('aria-invalid')).toBe('true')
    }
    await open(w, 'per-employer-cap')                                     // opening another row drops that draft
    await field(w, 'per-employer-cap').setValue('101')
    await enter(w, 'per-employer-cap')
    expect(w.find('#setting-per-employer-cap .field-error').text()).toBe('Enter a number from 0 to 100.')
    await field(w, 'per-employer-cap').setValue('2')                      // the saved value again: not sent either
    await enter(w, 'per-employer-cap')
    await flushPromises()
    expect(api.of('PUT', 'apply/settings')).toHaveLength(0)
  })

  it('0 is a valid cap and means no limit', async () => {
    const { api, w } = await apply({ settings: W, put: { ...W, per_employer_daily_cap: 0 } })
    await open(w, 'per-employer-cap')
    await field(w, 'per-employer-cap').setValue('0')
    await enter(w, 'per-employer-cap')
    await flushPromises()
    expect(putBodies(api)).toEqual([{ per_employer_daily_cap: 0 }])
    expect(value(w, 'per-employer-cap')).toBe('No limit')
  })

  it('the human-check row says it waits for you and never solves one', async () => {
    const { w } = await apply({ settings: W })
    await open(w, 'human-check-wait')
    expect(w.find('#setting-human-check-wait-editor').text()).toContain('JobScraper waits up to 120 s for you to finish a human check in the window. It never solves one.')
    await field(w, 'human-check-wait').setValue('0')
    expect(w.find('#setting-human-check-wait-editor').text()).toContain('It never solves a human check.')
  })

  it('the Application details row lists how many are missing, or says Complete', async () => {
    const missing = await apply({ summary: { missing: ['profile.phone', 'profile.address'], completeness: { filled: 1, needed: 3 }, form: null } })
    expect(value(missing.w, 'details')).toBe('2 to fill in')
    expect(missing.w.find('#setting-details a').attributes('href')).toBe('#/profile/details')
    expect(missing.w.find('#setting-details a').text()).toContain('Edit in Profile')
    const done = await apply({ summary: { missing: [], completeness: { filled: 3, needed: 3 }, form: null } })
    expect(value(done.w, 'details')).toBe('Complete')
    const none = await apply({})
    expect(rowIds(none.w)).not.toContain('details')                      // no summary: nothing faked
  })

  it('the mailbox row shows the mailbox state from the connections answer, with a link to Accounts', async () => {
    const r = cloneSample(sample)
    r.items = r.items.map(i => (i.id === 'apply-mailbox' ? { ...i, state: 'attention', code: 'no_password' } : i))
    const { w } = await apply({ connections: r })
    expect(w.find('#setting-mailbox .state-chip').text()).toBe('Needs attention')
    expect(w.find('#setting-mailbox a').attributes('href')).toBe('#/settings/accounts/apply-mailbox')
    expect(w.find('#setting-mailbox a').text()).toContain('Manage in Accounts')
  })

  it('with no connections answer the mailbox row has the link and no chip', async () => {
    const { w } = await apply({ connections: null })
    expect(w.find('#setting-mailbox a').exists()).toBe(true)
    expect(w.find('#setting-mailbox .state-chip').exists()).toBe(false)
  })
})

describe('useHashItem goes null on another tab (D-197)', () => {
  const navigate = hash => {
    setHash(hash)
    window.dispatchEvent(new HashChangeEvent('hashchange'))
  }

  it('the ref follows a deep link, then drops to null when the hash is another tab\'s', () => {
    setHash('#/settings/accounts/model')
    const scope = effectScope()
    const item = scope.run(() => useHashItem('settings'))
    expect(item.value).toBe('model')
    navigate('#/runs/accounts/gmail:3')
    expect(item.value).toBeNull()
    navigate('#/settings/accounts/edge')
    expect(item.value).toBe('edge')
    navigate('#/inbox')
    expect(item.value).toBeNull()
    scope.stop()
  })

  it('a hub that stays mounted does not jump to a card when another tab\'s hash names one', async () => {
    setHash('#/settings/accounts/model')
    routeFetch()
    const w = mount(ConnectionsHub, { props: { connections: cloneSample(sample) }, attachTo: document.body })
    await flushPromises()
    expect(document.activeElement.id).toBe('conn-model-title')
    expect(w.find('[data-card="model"]').classes()).toContain('is-target')
    document.activeElement.blur()
    navigate('#/runs/accounts/gmail:3')
    await flushPromises()
    expect(w.find('.is-target').exists()).toBe(false)
    expect(document.activeElement.id).not.toBe('conn-gmail-title')
    expect(document.activeElement.classList.contains('conn-title')).toBe(false)
  })
})
