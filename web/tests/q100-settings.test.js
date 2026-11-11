// Q-100 T1-B pins for lane B's Settings restructure (design sections 1, 4.3, D-191, D-197):
// the four views and where each hash lands, the attention count on the Accounts tab, the
// hub's load/failure handling, Settings -> Apply (rows hide while their route is absent,
// read-only unless `writable: true`, never a PUT on load), and useHashItem going null
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
const selected = w => tabs(w).filter(t => t.attributes('aria-selected') === 'true').map(t => t.text().replace(/\d+ need attention|\d+/g, '').trim())
const panel = w => w.find('[role="tabpanel"]').attributes('id')

describe('Settings: four views', () => {
  it('offers Accounts, Apply, Search and Appearance, in that order, as a tablist', async () => {
    server()
    const w = await settings()
    expect(w.find('[role="tablist"]').attributes('aria-label')).toBe('Settings sections')
    expect(tabs(w).map(t => t.attributes('id'))).toEqual([
      'settings-tab-accounts', 'settings-tab-apply', 'settings-tab-search', 'settings-tab-appearance',
    ])
    expect(tabs(w).map(t => t.element.firstChild.textContent.trim())).toEqual(['Accounts', 'Apply', 'Search', 'Appearance'])
    expect(w.find('.page-title').text()).toBe('Settings')
    expect(w.find('.page-sub').text()).toBe('Accounts, applying, search and appearance.')   // A15
  })

  it.each([
    ['', 'Accounts', 'settings-panel-accounts'],
    ['#/settings', 'Accounts', 'settings-panel-accounts'],
    ['#/settings/accounts', 'Accounts', 'settings-panel-accounts'],
    ['#/settings/apply', 'Apply', 'settings-panel-apply'],
    ['#/settings/search', 'Search', 'settings-panel-search'],
    ['#/settings/appearance', 'Appearance', 'settings-panel-appearance'],
  ])('hash %j opens %s', async (hash, label, panelId) => {
    server()
    const w = await settings(hash)
    expect(selected(w)).toEqual([label])
    expect(panel(w)).toBe(panelId)
    // Only the selected tab is a tab stop.
    expect(tabs(w).filter(t => t.attributes('tabindex') === '0')).toHaveLength(1)
    expect(w.find('[role="tabpanel"]').attributes('aria-labelledby')).toBe(`settings-tab-${label.toLowerCase()}`)
  })

  it('an unknown view falls back to Accounts and the hash is made canonical', async () => {
    server()
    const w = await settings('#/settings/bogus')
    expect(selected(w)).toEqual(['Accounts'])
    expect(window.location.hash).toBe('#/settings/accounts')
  })

  it('Accounts is the hub (and the Email card moved into it); Search has the cycle and run size; Appearance the theme', async () => {
    server()
    const w = await settings()
    expect(w.find('.hub').exists()).toBe(true)
    expect(w.find('.mail-card.embedded').exists()).toBe(true)
    expect(w.find('input[name="cycle"]').exists()).toBe(false)
    await tabs(w)[2].trigger('click')
    await flushPromises()
    expect(w.find('.hub').exists()).toBe(false)
    expect(w.findAll('input[name="cycle"]')).toHaveLength(5)
    expect(w.find('#batch-size').exists()).toBe(true)
    expect(w.find('input[name="theme"]').exists()).toBe(false)
    await tabs(w)[3].trigger('click')
    expect(w.findAll('input[name="theme"]').map(i => i.element.value)).toEqual(['light', 'dark', 'system'])
    expect(w.find('#batch-size').exists()).toBe(false)
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

  it('arrow keys, Home and End move between the tabs and focus them', async () => {
    server()
    const w = await settings()
    await tabs(w)[0].trigger('keydown', { key: 'ArrowRight' })
    expect(selected(w)).toEqual(['Apply'])
    expect(document.activeElement.id).toBe('settings-tab-apply')
    await tabs(w)[1].trigger('keydown', { key: 'End' })
    expect(selected(w)).toEqual(['Appearance'])
    await tabs(w)[3].trigger('keydown', { key: 'ArrowRight' })      // wraps
    expect(selected(w)).toEqual(['Accounts'])
    await tabs(w)[0].trigger('keydown', { key: 'ArrowLeft' })       // wraps back
    expect(selected(w)).toEqual(['Appearance'])
    await tabs(w)[3].trigger('keydown', { key: 'Home' })
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
    expect(w.find('[data-row="mailbox"] .state-chip').text()).toBe('Connected')
  })
})

describe('Settings -> Apply (ApplySettings)', () => {
  const rows = w => w.findAll('[data-row]').map(r => r.attributes('data-row'))
  const GOOD = {
    mode: 'dry_run', writable: false, daily_cap: 5, per_employer_daily_cap: 2, headed: false,
    captcha_wait_s: 120, compose_enabled: false,
  }
  async function apply(routes = {}, connections = cloneSample(sample)) {
    const api = routeFetch(routes)
    const w = mount(ApplySettings, { props: { connections }, attachTo: document.body })
    await flushPromises()
    return { api, w }
  }
  const noWrites = api => api.calls.filter(c => c.method !== 'GET')

  it('every optional source absent (404): only the mailbox row, nothing faked, nothing sent', async () => {
    const { api, w } = await apply()
    expect(rows(w)).toEqual(['mailbox'])
    expect(w.find('[data-row="mailbox"] a').attributes('href')).toBe('#/settings/accounts/apply-mailbox')
    expect(w.find('[data-row="mailbox"] a').text()).toBe('Manage in Accounts →')
    expect(w.find('input, select, textarea').exists()).toBe(false)
    expect(w.find('.apply-save-btn').exists()).toBe(false)
    expect(noWrites(api)).toEqual([])
  })

  it('also hides everything when the routes answer null-ish errors (405)', async () => {
    const { api, w } = await apply({
      'GET apply/status': [405, {}], 'GET apply/settings': [405, {}], 'GET applicant': [405, {}],
    })
    expect(rows(w)).toEqual(['mailbox'])
    expect(noWrites(api)).toEqual([])
  })

  it('mode comes from /apply/status when /apply/settings is absent', async () => {
    const { w } = await apply({ 'GET apply/status': { mode: 'dry_run', missing: [], busy: false } })
    expect(rows(w)).toContain('mode')
    expect(w.find('.apply-mode-text').attributes('data-mode')).toBe('dry_run')
    expect(w.find('.apply-mode-text').text()).toMatch(/^Dry run\. .*Nothing is sent\.$/)
    expect(rows(w)).not.toContain('limits')
    expect(rows(w)).not.toContain('human-checks')
    expect(rows(w)).not.toContain('compose')
  })

  it('auto mode is spelled out', async () => {
    const { w } = await apply({ 'GET apply/status': { mode: 'auto', missing: [], busy: false } })
    expect(w.find('.apply-mode-text').text()).toMatch(/^Automatic\. .*final check passes\.$/)
  })

  it('read-only when the server does not say writable: true (false, or the key absent)', async () => {
    for (const s of [GOOD, (({ writable, ...rest }) => rest)(GOOD), { ...GOOD, writable: 'yes' }]) {
      const { api, w } = await apply({ 'GET apply/settings': s })
      expect(rows(w)).toEqual(['mode', 'limits', 'human-checks', 'mailbox', 'compose'])
      expect(w.find('[data-row="limits"] dd').text()).toBe('5 applications a day · 2 per employer · browser window hidden')
      expect(w.find('[data-row="human-checks"]').text()).toContain('waits up to 120 s')
      expect(w.find('[data-row="human-checks"]').text()).toContain('never solves them')
      expect(w.find('[data-row="compose"]').text()).toContain('Off.')
      expect(w.find('input').exists()).toBe(false)
      expect(w.find('.apply-save-btn').exists()).toBe(false)
      expect(noWrites(api)).toEqual([])
      w.unmount()
    }
  })

  it('writable: true shows the controls, and loading never sends a PUT (no probe write)', async () => {
    const { api, w } = await apply({ 'GET apply/settings': { ...GOOD, writable: true } })
    expect(w.findAll('input[name="apply-mode"]')).toHaveLength(2)
    expect(w.find('input[aria-invalid]').exists()).toBe(true)
    expect(w.find('.apply-save-btn').attributes('disabled')).toBeDefined()   // nothing changed yet
    expect(noWrites(api)).toEqual([])
    expect(api.calls.map(c => c.method).every(m => m === 'GET')).toBe(true)
  })

  it('a save sends only what changed', async () => {
    const { api, w } = await apply({
      'GET apply/settings': { ...GOOD, writable: true },
      'PUT apply/settings': { ...GOOD, writable: true, daily_cap: 8 },
    })
    await w.find('[data-row="limits"] input[type="number"]').setValue('8')
    await w.find('.apply-save-btn').trigger('click')
    await flushPromises()
    expect(api.of('PUT', 'apply/settings').map(c => c.body)).toEqual([{ daily_cap: 8 }])
    expect(w.text()).toContain('Saved.')
  })

  it('switching to automatic asks first; nothing is sent until confirmed, and Keep dry run sends nothing', async () => {
    const { api, w } = await apply({
      'GET apply/settings': { ...GOOD, writable: true },
      'PUT apply/settings': { ...GOOD, writable: true, mode: 'auto' },
    })
    await w.find('input[name="apply-mode"][value="auto"]').setValue(true)
    await w.find('.apply-save-btn').trigger('click')
    expect(w.find('.confirm-auto').text()).toContain('Send applications automatically?')
    expect(api.of('PUT', 'apply/settings')).toHaveLength(0)
    await w.find('.confirm-no').trigger('click')
    expect(api.of('PUT', 'apply/settings')).toHaveLength(0)
    expect(w.find('.confirm-auto').exists()).toBe(false)
    await w.find('input[name="apply-mode"][value="auto"]').setValue(true)
    await w.find('.apply-save-btn').trigger('click')
    await w.find('.confirm-yes').trigger('click')
    await flushPromises()
    expect(api.of('PUT', 'apply/settings').map(c => c.body)).toEqual([{ mode: 'auto' }])
  })

  it.each([
    [404, "Couldn't save"],
    [405, "Couldn't save"],
    [422, "Couldn't save: daily_cap must be at most 50"],
  ])('a %s on save says "Couldn\'t save" and puts the controls back to read-only', async (status, text) => {
    const { w } = await apply({
      'GET apply/settings': { ...GOOD, writable: true },
      'PUT apply/settings': [status, { detail: 'daily_cap must be at most 50' }],
    })
    await w.find('[data-row="limits"] input[type="number"]').setValue('9')
    await w.find('.apply-save-btn').trigger('click')
    await flushPromises()
    expect(w.text()).toContain(text)
    expect(w.find('input').exists()).toBe(false)
    expect(w.find('.apply-save-btn').exists()).toBe(false)
  })

  it('refuses out-of-range numbers in the form without sending', async () => {
    const { api, w } = await apply({ 'GET apply/settings': { ...GOOD, writable: true } })
    await w.find('[data-row="limits"] input[type="number"]').setValue('0')
    expect(w.find('.apply-problem').text()).toBe('Applications a day: between 1 and 50.')
    expect(w.find('.apply-save-btn').attributes('disabled')).toBeDefined()
    await w.find('.apply-save-btn').trigger('click')
    expect(noWrites(api)).toEqual([])
  })

  it('the Ready row lists what is missing, or says Ready', async () => {
    const missing = await apply({ 'GET applicant': { missing: ['profile.phone', 'profile.address'], completeness: { filled: 1, needed: 3 } } })
    expect(missing.w.find('[data-row="ready"]').text()).toContain('2 things to fill in first')
    expect(missing.w.find('[data-row="ready"] a[href="#/profile/details"]').exists()).toBe(true)
    const ready = await apply({ 'GET applicant': { missing: [], completeness: { filled: 3, needed: 3 } } })
    expect(ready.w.find('[data-row="ready"]').text()).toContain('Ready.')
  })

  it('the mailbox row shows the mailbox state from the connections answer', async () => {
    const r = cloneSample(sample)
    r.items = r.items.map(i => (i.id === 'apply-mailbox' ? { ...i, state: 'attention', code: 'no_password' } : i))
    const { w } = await apply({}, r)
    expect(w.find('[data-row="mailbox"] .state-chip').text()).toBe('Needs attention')
  })

  it('with no connections answer the mailbox row has the link and no chip', async () => {
    const { w } = await apply({}, null)
    expect(w.find('[data-row="mailbox"] a').exists()).toBe(true)
    expect(w.find('[data-row="mailbox"] .state-chip').exists()).toBe(false)
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
