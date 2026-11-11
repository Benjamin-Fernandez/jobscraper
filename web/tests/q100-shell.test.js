// Q-100 T1-C pins for the shell (design sections 1, 2.2, 4.4, A14) with lanes A-C's pieces
// together: the hash keeps its view and item and a deep link reaches the hub card; the
// Settings tab badge is attentionCount (with the two-failures-in-a-row rule over two loads);
// the attention banner and the "Auto-apply on" chip appear from /api/connections and
// /api/apply/status and are absent when those routes are; the phone's bottom bar and its
// More sheet; and the CSS hooks that keep the page, the save bar and the toast above it.
import { readFileSync } from 'node:fs'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import App from '../src/App.vue'
import sample from './fixtures/connections.sample.json'
import { fakeApi, setHash } from './helpers.js'
import { cloneSample, routeFetch } from './q100Fake.js'

enableAutoUnmount(afterEach)
beforeEach(() => {
  window.sessionStorage.clear()
  window.localStorage.clear()
  setHash('#/inbox')
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  setHash('')
})

const ok = () => {
  const r = cloneSample(sample)
  r.items = r.items.filter(i => i.kind !== 'gmail').map(i => (i.state === 'attention' ? { ...i, state: 'connected', code: 'ok' } : i))
  return r
}
// A response where only the model (when need_now) needs the owner.
const oneProblem = () => {
  const r = ok()
  r.items = r.items.map(i => (i.kind === 'model' ? { ...i, state: 'attention', code: 'unreachable', facts: { ...i.facts, need_now: true } } : i))
  return r
}

async function boot(hash, routes = {}) {
  setHash(hash)
  const api = routeFetch(
    { 'GET connections': cloneSample(sample), 'GET apply/status': { mode: 'dry_run', missing: [], busy: false }, ...routes },
    { fallback: fakeApi().fetch },
  )
  const w = mount(App, { attachTo: document.body })
  await vi.waitFor(async () => {
    await flushPromises()
    expect(w.find('main.panel').exists()).toBe(true)
    expect(w.find('main.panel [aria-busy="true"]').exists()).toBe(false)
  })
  await flushPromises()
  return { api, w }
}
const tab = (w, id) => w.find(`[role="tab"][data-tab="${id}"]`)
const settingsBadge = w => tab(w, 'settings').find('.badge')
const selected = w => w.findAll('[role="tab"][data-tab]').filter(t => t.attributes('aria-selected') === 'true').map(t => t.attributes('data-tab'))
const banner = w => w.find('[data-attention-banner]')

describe('the hash keeps its view and item', () => {
  it('#/settings/accounts/gmail:3 survives a load, selects Settings, and reaches the card heading', async () => {
    const { w } = await boot('#/settings/accounts/gmail:3')
    expect(window.location.hash).toBe('#/settings/accounts/gmail:3')
    expect(selected(w)).toEqual(['settings'])
    await vi.waitFor(() => expect(document.activeElement?.id).toBe('conn-gmail-title'))
    expect(w.find('[data-card="gmail"]').classes()).toContain('is-target')
  })

  it('the old #/settings still works and lands on the Accounts view, hash untouched', async () => {
    const { w } = await boot('#/settings')
    expect(window.location.hash).toBe('#/settings')
    expect(selected(w)).toEqual(['settings'])
    expect(w.find('.hub').exists()).toBe(true)
    expect(w.find('#settings-tab-accounts').attributes('aria-selected')).toBe('true')
  })

  it.each([
    ['#/settings/search', 'settings-panel-search'],
    ['#/settings/appearance', 'settings-panel-appearance'],
    ['#/settings/apply', 'settings-panel-apply'],
  ])('%s stays as written and opens that view', async (hash, panel) => {
    const { w } = await boot(hash)
    expect(window.location.hash).toBe(hash)
    expect(w.find(`#${panel}`).exists()).toBe(true)
  })

  it('an unknown tab or an empty hash lands on Overview and the URL says so', async () => {
    let { w } = await boot('#/nowhere/x/y')
    expect(window.location.hash).toBe('#/overview')
    expect(selected(w)).toEqual(['overview'])
    w.unmount()
    ;({ w } = await boot(''))
    expect(window.location.hash).toBe('#/overview')
  })
})

describe('the Settings tab badge is the attention count', () => {
  it('shows the number, in the amber tone, with its words for a screen reader', async () => {
    const { w } = await boot('#/inbox')
    const b = settingsBadge(w)
    expect(b.exists()).toBe(true)
    expect(b.attributes('data-tone')).toBe('attention')
    expect(b.text()).toMatch(/^8 ?need attention$/)
    expect(b.find('.visually-hidden').text()).toBe('need attention')
  })

  it('no badge when nothing needs attention', async () => {
    const { w } = await boot('#/inbox', { 'GET connections': ok() })
    expect(settingsBadge(w).exists()).toBe(false)
  })

  it('a model that is down counts only when something is waiting for it (need_now)', async () => {
    const idle = oneProblem()
    idle.items = idle.items.map(i => (i.kind === 'model' ? { ...i, facts: { ...i.facts, need_now: false } } : i))
    const { w } = await boot('#/inbox', { 'GET connections': idle })
    expect(settingsBadge(w).exists()).toBe(false)
    w.unmount()
    const { w: w2 } = await boot('#/inbox', { 'GET connections': oneProblem() })
    expect(settingsBadge(w2).text()).toMatch(/^1 ?need attention$/)
  })

  describe('two failed checks in a row (check_failed twice)', () => {
    const blip = () => {
      const r = ok()
      r.items = r.items.map(i => (i.kind === 'edge' ? { ...i, state: 'neutral', code: 'check_failed' } : i))
      return r
    }
    // Leaving Settings reloads the signals (the owner may just have fixed something).
    async function visitAndLeave(w) {
      await tab(w, 'settings').trigger('click')
      await flushPromises()
      await tab(w, 'inbox').trigger('click')
      await flushPromises()
    }

    it('one failed check is a blip: no badge', async () => {
      const { w } = await boot('#/inbox', { 'GET connections': blip() })
      expect(settingsBadge(w).exists()).toBe(false)
    })

    it('the same check failing on the next load counts', async () => {
      const { w } = await boot('#/inbox', { 'GET connections': blip() })
      expect(settingsBadge(w).exists()).toBe(false)
      await visitAndLeave(w)
      await vi.waitFor(() => expect(settingsBadge(w).text()).toMatch(/^1 ?need attention$/))
    })

    it('a failure followed by a good load never counts', async () => {
      let phase = 'blip'
      const { w } = await boot('#/inbox', { 'GET connections': () => (phase === 'blip' ? blip() : ok()) })
      phase = 'ok'
      await visitAndLeave(w)
      await flushPromises()
      expect(settingsBadge(w).exists()).toBe(false)
    })
  })

  it('More on the phone bar carries the hidden tabs\' attention count', async () => {
    const { w } = await boot('#/inbox')
    const badge = w.find('[data-bnav="more"] .bnav-badge')
    expect(badge.attributes('data-tone')).toBe('attention')
    expect(badge.text()).toMatch(/^8 ?need attention$/)
  })
})

describe('the attention banner under the masthead', () => {
  it('shows for attention items, as a status line that links into the hub', async () => {
    const { w } = await boot('#/inbox', { 'GET connections': oneProblem() })
    expect(banner(w).exists()).toBe(true)
    expect(banner(w).element.closest('[role="status"]')).not.toBeNull()
    expect(banner(w).find('strong').text()).toBe('Local AI needs attention.')
    expect(banner(w).find('a.attention-go').attributes('href')).toBe('#/settings/accounts/model')
  })

  it('several problems read as one line, Review', async () => {
    const { w } = await boot('#/inbox')
    expect(banner(w).find('strong').text()).toBe('8 connections need attention.')
    expect(banner(w).find('a.attention-go').attributes('href')).toBe('#/settings/accounts')
  })

  it('no banner when everything is fine', async () => {
    const { w } = await boot('#/inbox', { 'GET connections': ok() })
    expect(banner(w).exists()).toBe(false)
    expect(w.find('.attention-region[role="status"]').exists()).toBe(true)
  })

  it('hides on the hub (the Accounts view, with or without an item), shows on the other views', async () => {
    const { w } = await boot('#/settings/accounts/gmail:3')
    expect(banner(w).exists()).toBe(false)
    await w.find('#settings-tab-apply').trigger('click')       // a view switch uses replaceState: the shell re-reads on click
    await flushPromises()
    expect(window.location.hash).toBe('#/settings/apply')
    expect(banner(w).exists()).toBe(true)
    await w.find('#settings-tab-accounts').trigger('click')
    await flushPromises()
    expect(banner(w).exists()).toBe(false)
  })

  it('hides on a bare #/settings (it opens on the hub) and shows on Inbox', async () => {
    const { w } = await boot('#/settings')
    expect(banner(w).exists()).toBe(false)
    await tab(w, 'inbox').trigger('click')
    await flushPromises()
    expect(banner(w).exists()).toBe(true)
  })

  it('Dismiss persists across a reload (sessionStorage), until something new goes wrong', async () => {
    const { w } = await boot('#/inbox', { 'GET connections': oneProblem() })
    await banner(w).find('button.attention-dismiss').trigger('click')
    expect(banner(w).exists()).toBe(false)
    w.unmount()
    const { w: again } = await boot('#/inbox', { 'GET connections': oneProblem() })
    expect(banner(again).exists()).toBe(false)
    again.unmount()
    const { w: worse } = await boot('#/inbox')                   // eight problems now
    expect(banner(worse).exists()).toBe(true)
  })
})

describe('the Auto-apply chip in the masthead', () => {
  const chip = w => w.find('a.mode-chip')

  it('shows only in auto mode, from any tab, linking to Settings -> Apply', async () => {
    const { w } = await boot('#/inbox', { 'GET apply/status': { mode: 'auto', missing: [], busy: false } })
    expect(chip(w).exists()).toBe(true)
    expect(chip(w).text()).toContain('Auto-apply on')
    expect(chip(w).attributes('href')).toBe('#/settings/apply')
    await tab(w, 'runs').trigger('click')
    await flushPromises()
    expect(chip(w).exists()).toBe(true)
  })

  it('is absent in dry run and when the status route is absent or fails', async () => {
    for (const status of [{ mode: 'dry_run', missing: [], busy: false }, [404, { detail: 'Not Found' }], [500, { detail: 'boom' }]]) {
      const { w } = await boot('#/inbox', { 'GET apply/status': status })
      expect(chip(w).exists()).toBe(false)
      w.unmount()
    }
  })
})

describe('/api/connections is absent or broken: the shell stays quiet', () => {
  it.each([
    ['404', [404, { detail: 'Not Found' }]],
    ['405', [405, { detail: 'Method Not Allowed' }]],
    ['500', [500, { detail: 'boom' }]],
    ['an answer without items', [200, { version: 1 }]],
  ])('%s: no badge, no banner, no chip, no error in the shell', async (_n, answer) => {
    const { w } = await boot('#/inbox', { 'GET connections': answer, 'GET apply/status': [404, {}] })
    expect(settingsBadge(w).exists()).toBe(false)
    expect(w.find('[data-bnav="more"] .bnav-badge').exists()).toBe(false)
    expect(banner(w).exists()).toBe(false)
    expect(w.find('.mode-chip').exists()).toBe(false)
    expect(w.find('.boot-error').exists()).toBe(false)
    expect(w.find('header [role="alert"]').exists()).toBe(false)
    expect(w.find('main.panel').attributes('role')).toBe('tabpanel')
  })
})

describe('the phone\'s bottom bar (A14)', () => {
  const bar = w => w.find('nav.bottom-nav')
  const items = w => bar(w).findAll('[data-bnav]').map(b => b.attributes('data-bnav'))

  it('has Overview, Inbox, Applications and More, and marks the current page', async () => {
    const { w } = await boot('#/inbox')
    expect(bar(w).attributes('aria-label')).toBe('Sections')
    expect(items(w)).toEqual(['overview', 'inbox', 'applications', 'more'])
    expect(bar(w).findAll('[aria-current="page"]').map(b => b.attributes('data-bnav'))).toEqual(['inbox'])
    await bar(w).find('[data-bnav="applications"]').trigger('click')
    await flushPromises()
    expect(selected(w)).toEqual(['applications'])
    expect(bar(w).findAll('[aria-current="page"]').map(b => b.attributes('data-bnav'))).toEqual(['applications'])
  })

  it('the top tab list is still the only role=tablist of the shell (the sheet adds none while closed)', async () => {
    const { w } = await boot('#/inbox')
    expect(w.findAll('.tablist[role="tablist"]')).toHaveLength(1)
    expect(w.find('.more-item').exists()).toBe(false)
  })

  it('More opens a sheet with the other tabs in order; a choice navigates and closes it', async () => {
    const { w } = await boot('#/inbox')
    const more = bar(w).find('[data-bnav="more"]')
    expect(more.attributes('aria-expanded')).toBe('false')
    await more.trigger('click')
    await flushPromises()
    expect(more.attributes('aria-expanded')).toBe('true')
    expect(w.findAll('.more-item').map(b => b.attributes('data-more'))).toEqual(['runs', 'companies', 'profile', 'settings', 'developer'])
    await w.find('.more-item[data-more="runs"]').trigger('click')
    await flushPromises()
    expect(selected(w)).toEqual(['runs'])
    expect(w.find('.more-item').exists()).toBe(false)
    expect(more.attributes('aria-expanded')).toBe('false')
    expect(more.attributes('aria-current')).toBe('page')       // Runs is under More
  })

  it('Close returns focus to More', async () => {
    const { w } = await boot('#/inbox')
    const more = bar(w).find('[data-bnav="more"]')
    await more.trigger('click')
    await flushPromises()
    await w.find('button.more-close').trigger('click')
    await flushPromises()
    expect(w.find('.more-item').exists()).toBe(false)
    expect(document.activeElement).toBe(more.element)
  })

  it('the sheet shows the Settings attention count too', async () => {
    const { w } = await boot('#/inbox')
    await bar(w).find('[data-bnav="more"]').trigger('click')
    await flushPromises()
    expect(w.find('.more-item[data-more="settings"]').text()).toMatch(/8/)
  })
})

describe('the bottom bar\'s CSS hooks (jsdom cannot measure, so the contract is read from the source)', () => {
  const read = p => readFileSync(new URL(p, import.meta.url), 'utf8')
  const app = read('../src/App.vue')
  const css = read('../src/style.css')

  it('--bottom-nav-h is 0 by default and the bar height under 640px', () => {
    expect(css).toMatch(/--bottom-nav-h:\s*0px/)
    expect(css).toMatch(/@media \(max-width: 640px\)\s*\{[^}]*--bottom-nav-h:\s*3\.5rem/)
  })

  it('the bar is hidden wider than 640px and fixed to the bottom under it, replacing the tab bar', () => {
    expect(app).toMatch(/\.bottom-nav\s*\{\s*display:\s*none;\s*\}/)
    const phone = app.slice(app.lastIndexOf('@media (max-width: 640px)'))
    expect(phone).toMatch(/\.tabbar\s*\{\s*display:\s*none;\s*\}/)
    expect(phone).toMatch(/\.bottom-nav\s*\{[^}]*position:\s*fixed[^}]*bottom:\s*0/)
    expect(phone).toMatch(/height:\s*calc\(var\(--bottom-nav-h\)/)
  })

  it('the page, the save bar and the toast all keep clear of it with --bottom-nav-h', () => {
    expect(app).toMatch(/\.panel\s*\{[^}]*var\(--bottom-nav-h\)/)
    expect(read('../src/components/ApplicationDetails.vue')).toMatch(/\.save-bar\s*\{[^}]*bottom:\s*calc\(var\(--bottom-nav-h\)/)
    expect(read('../src/components/ToastHost.vue')).toMatch(/bottom:\s*calc\([^;]*var\(--bottom-nav-h\)/)
  })
})
