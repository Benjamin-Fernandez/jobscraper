// Q-100 T1-0 pins for web/src/route.js (design §1): the hash grammar
// `#/<tab>[/<view>[/<item>]]`, the old one-segment hashes that must keep working,
// and the two composables a tab uses (`useView`, `useHashItem`).
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { effectScope } from 'vue'
import { hashFor, parseHash, tabFromHash, useHashItem, useView } from '../src/route.js'
import { TABS } from '../src/tabs.js'
import { setHash } from './helpers.js'

const IDS = TABS.map(t => t.id)
const VIEWS = ['overview', 'accounts', 'apply']

let scopes = []
let scope
// Run a composable inside an effect scope so its hashchange listener is removed
// after the test (jsdom keeps one window for the whole file).
function inScope(fn) {
  scope = effectScope()
  scopes.push(scope)
  return scope.run(fn)
}
// jsdom fires `hashchange` only for navigation, not for replaceState, so a test
// that wants the app to "see" a new hash writes it and dispatches the event.
function navigate(hash) {
  setHash(hash)
  window.dispatchEvent(new HashChangeEvent('hashchange'))
}

beforeEach(() => setHash(''))
afterEach(() => {
  scopes.forEach(s => s.stop())
  scopes = []
  scope = null
  vi.restoreAllMocks()
})

describe('tab registry', () => {
  it('has the tab ids every old hash used', () => {
    for (const id of ['overview', 'inbox', 'applications', 'runs', 'settings', 'profile']) expect(IDS).toContain(id)
  })
})

describe('tabFromHash: old one-segment hashes keep their contract', () => {
  it.each(IDS)('#/%s is the %s tab', id => {
    expect(tabFromHash(`#/${id}`, IDS)).toBe(id)
    expect(tabFromHash(`#/${id}/`, IDS)).toBe(id)
  })
  it('the old settings and profile hashes still land on those tabs', () => {
    expect(tabFromHash('#/settings', IDS)).toBe('settings')
    expect(tabFromHash('#/profile', IDS)).toBe('profile')
    expect(tabFromHash('#/runs', IDS)).toBe('runs')
  })
  it('a view or an item is ignored: the hash is still that tab', () => {
    expect(tabFromHash('#/settings/accounts', IDS)).toBe('settings')
    expect(tabFromHash('#/settings/accounts/gmail:3', IDS)).toBe('settings')
    expect(tabFromHash('#/profile/details', IDS)).toBe('profile')
  })
  it('junk and unknown tabs give the fallback (the first tab, or the one asked for)', () => {
    for (const junk of ['', undefined, null, '#', '#/', '#runs', '#/Runs', '#/nope', '#/runs/../x', '#/runs/a/b/c',
      '#/runs//x', '#/runs/a b', '#/runs?x=1', '/runs']) {
      expect(tabFromHash(junk, IDS), String(junk)).toBe(IDS[0])
    }
    expect(tabFromHash('#/nope', IDS, 'runs')).toBe('runs')
  })
})

describe('parseHash', () => {
  it('splits tab, view and item', () => {
    expect(parseHash('#/settings/accounts/gmail:3', IDS)).toEqual({ tab: 'settings', view: 'accounts', item: 'gmail:3' })
    expect(parseHash('#/settings/accounts', IDS)).toEqual({ tab: 'settings', view: 'accounts', item: null })
    expect(parseHash('#/settings', IDS)).toEqual({ tab: 'settings', view: null, item: null })
    expect(parseHash('#/settings/accounts/apply-mailbox:backup', IDS).item).toBe('apply-mailbox:backup')
    expect(parseHash('#/settings/accounts/employer-accounts/', IDS).item).toBe('employer-accounts')
  })
  it('keeps the view as written: whether the tab has it is the tab\'s business', () => {
    expect(parseHash('#/settings/nonsense', IDS)).toEqual({ tab: 'settings', view: 'nonsense', item: null })
  })
  it('an unknown tab or a non-route is the first tab with no view or item', () => {
    const home = { tab: IDS[0], view: null, item: null }
    for (const junk of ['', '#/nope/accounts/x', '#/runs/../x', '#/settings/accounts/gmail:3:4', '#/settings/a:b',
      '#/settings/accounts/gmail:3/more', '#/settings/accounts/ gmail', '#settings/accounts']) {
      expect(parseHash(junk, IDS), junk).toEqual(home)
    }
  })
})

describe('hashFor', () => {
  it('builds tab, tab/view and tab/view/item', () => {
    expect(hashFor('runs')).toBe('#/runs')
    expect(hashFor('settings', 'accounts')).toBe('#/settings/accounts')
    expect(hashFor('settings', 'accounts', 'gmail:3')).toBe('#/settings/accounts/gmail:3')
  })
  it('drops an item that has no view, and an empty view', () => {
    expect(hashFor('settings', null, 'gmail:3')).toBe('#/settings')
    expect(hashFor('settings', '', 'gmail:3')).toBe('#/settings')
    expect(hashFor('settings', undefined)).toBe('#/settings')
  })
  it('round-trips through parseHash', () => {
    for (const parts of [{ tab: 'settings', view: 'accounts', item: 'gmail:3' }, { tab: 'profile', view: 'details', item: null },
      { tab: 'runs', view: null, item: null }]) {
      expect(parseHash(hashFor(parts.tab, parts.view, parts.item), IDS)).toEqual(parts)
    }
  })
})

describe('useView', () => {
  it('no view in the hash: the default, and the hash is left alone', () => {
    setHash('#/settings')
    const spy = vi.spyOn(window.history, 'replaceState')
    const view = inScope(() => useView('settings', VIEWS))
    expect(view.value).toBe('overview')
    expect(window.location.hash).toBe('#/settings')
    expect(spy).not.toHaveBeenCalled()
  })
  it('takes the view from the hash, as ids or as {id} objects, and leaves an item in place', () => {
    setHash('#/settings/accounts/gmail:3')
    const view = inScope(() => useView('settings', VIEWS.map(id => ({ id, label: id }))))
    expect(view.value).toBe('accounts')
    expect(window.location.hash).toBe('#/settings/accounts/gmail:3')
  })
  it('the default is the fallback argument when it is a real view, else the first view', () => {
    setHash('#/settings')
    expect(inScope(() => useView('settings', VIEWS, 'apply')).value).toBe('apply')
    expect(inScope(() => useView('settings', VIEWS, 'bogus')).value).toBe('overview')
  })
  it('an unknown view: the default, and the canonical hash is written with replaceState', () => {
    setHash('#/settings/nonsense/gmail:3')
    const before = window.history.length
    const spy = vi.spyOn(window.history, 'replaceState')
    const view = inScope(() => useView('settings', VIEWS, 'accounts'))
    expect(view.value).toBe('accounts')
    expect(window.location.hash).toBe('#/settings/accounts')
    expect(spy).toHaveBeenCalledTimes(1)
    expect(window.history.length).toBe(before)   // no new history entry
  })
  it('another tab\'s hash never changes the value or the hash (a kept-alive tab stays mounted)', () => {
    setHash('#/runs/accounts')
    const view = inScope(() => useView('settings', VIEWS))
    expect(view.value).toBe('overview')
    const spy = vi.spyOn(window.history, 'replaceState')
    navigate('#/profile/nonsense')
    expect(view.value).toBe('overview')
    navigate('#/runs')
    expect(view.value).toBe('overview')
    expect(window.location.hash).toBe('#/runs')
    // only navigate()'s own two writes: the view never wrote the hash
    expect(spy).toHaveBeenCalledTimes(2)
  })
  it('keeps the view it had while another tab is open, and picks the hash up again on return', () => {
    setHash('#/settings/apply')
    const view = inScope(() => useView('settings', VIEWS))
    expect(view.value).toBe('apply')
    navigate('#/runs')
    expect(view.value).toBe('apply')
    navigate('#/settings/accounts')
    expect(view.value).toBe('accounts')
  })
  it('follows hashchange, and no view in the new hash means the default', () => {
    setHash('#/settings/apply')
    const view = inScope(() => useView('settings', VIEWS))
    navigate('#/settings/accounts')
    expect(view.value).toBe('accounts')
    navigate('#/settings')
    expect(view.value).toBe('overview')
    navigate('#/settings/junk')
    expect(view.value).toBe('overview')
    expect(window.location.hash).toBe('#/settings/overview')
  })
  it('assigning writes the hash without the old view\'s item, via replaceState', () => {
    setHash('#/settings/accounts/gmail:3')
    const before = window.history.length
    const view = inScope(() => useView('settings', VIEWS))
    view.value = 'apply'
    expect(view.value).toBe('apply')
    expect(window.location.hash).toBe('#/settings/apply')
    expect(window.history.length).toBe(before)
  })
  it('assigning a view the tab does not have is ignored', () => {
    setHash('#/settings/accounts')
    const view = inScope(() => useView('settings', VIEWS))
    view.value = 'nonsense'
    expect(view.value).toBe('accounts')
    expect(window.location.hash).toBe('#/settings/accounts')
  })
  it('assigning while another tab is open does not write that tab\'s hash', () => {
    setHash('#/runs')
    const view = inScope(() => useView('settings', VIEWS))
    view.value = 'apply'
    expect(window.location.hash).toBe('#/runs')
  })
  it('stops following the hash once its scope ends', () => {
    setHash('#/settings/accounts')
    const view = inScope(() => useView('settings', VIEWS))
    scope.stop()
    navigate('#/settings/apply')
    expect(view.value).toBe('accounts')
  })
})

describe('useHashItem', () => {
  it('reads the item of the open tab and follows hashchange', () => {
    setHash('#/settings/accounts/gmail:3')
    const item = inScope(() => useHashItem('settings'))
    expect(item.value).toBe('gmail:3')
    navigate('#/settings/accounts/apply-mailbox:backup')
    expect(item.value).toBe('apply-mailbox:backup')
    navigate('#/settings/accounts')
    expect(item.value).toBeNull()
  })
  it('is null when the hash has no item, or names another tab', () => {
    setHash('#/settings/accounts')
    expect(inScope(() => useHashItem('settings')).value).toBeNull()
    setHash('#/runs/accounts/gmail:3')
    expect(inScope(() => useHashItem('settings')).value).toBeNull()
    setHash('')
    expect(inScope(() => useHashItem('settings')).value).toBeNull()
  })
  it('stops following the hash once its scope ends', () => {
    setHash('#/settings/accounts/gmail:3')
    const item = inScope(() => useHashItem('settings'))
    scope.stop()
    navigate('#/settings/accounts/gmail:4')
    expect(item.value).toBe('gmail:3')
  })
})
