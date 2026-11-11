// Q-100 T1-C pins for the shell's two components (design section 1, 4.4, researcher M2):
// AttentionBanner (one item or several, the button words by kind, the link into the
// hub, role="status", hidden prop, Dismiss remembered as the sorted id:code list in
// sessionStorage, and storage that throws) and ModeChip (only for mode "auto").
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import AttentionBanner, { DISMISS_KEY } from '../src/components/AttentionBanner.vue'
import ModeChip from '../src/components/ModeChip.vue'
import { attentionItems } from '../src/connections.js'
import sample from './fixtures/connections.sample.json'

enableAutoUnmount(afterEach)
beforeEach(() => window.sessionStorage.clear())
afterEach(() => vi.restoreAllMocks())

const byId = id => sample.items.find(i => i.id === id)
const variant = name => sample.variants[name].item
const gmail3 = byId('gmail:3')
const mailbox = variant('apply_mailbox_no_password')
const employers = byId('employer-accounts')
const model = variant('model_unreachable_need_now')

const banner = items => mount(AttentionBanner, { props: { items }, attachTo: document.body })
const shown = w => w.find('[data-attention-banner]').exists()
const go = w => w.find('a.attention-go')

describe('AttentionBanner', () => {
  it('is a polite live region that is in the page even when nothing is wrong', () => {
    for (const items of [[], [gmail3]]) {
      const w = banner(items)
      expect(w.find('[role="status"]').exists()).toBe(true)
      expect(w.find('[role="alert"]').exists()).toBe(false)
      w.unmount()
    }
    expect(shown(banner([]))).toBe(false)
  })

  it('one item: names it, says why, and links into the hub at that card', () => {
    const w = banner([gmail3])
    expect(shown(w)).toBe(true)
    expect(w.find('.attention-text strong').text()).toBe('Email updates needs attention.')
    expect(w.find('.attention-text').text()).toContain(gmail3.message)
    expect(go(w).attributes('href')).toBe('#/settings/accounts/gmail:3')
    expect(go(w).text()).toBe('Fix it')
  })

  it.each([
    ['gmail', gmail3, 'Email updates', 'Fix it'],
    ['model', model, 'Local AI', 'Fix it'],
    ['application mailbox', mailbox, 'Application mailbox', 'See how to fix'],
    ['employer accounts', employers, 'Employer accounts', 'See how to fix'],
  ])('%s: "%s needs attention", button "%s"', (_n, item, name, button) => {
    const w = banner([item])
    expect(w.find('.attention-text strong').text()).toBe(`${name} needs attention.`)
    expect(go(w).text()).toBe(button)
    expect(go(w).attributes('href')).toBe(`#/settings/accounts/${item.id}`)
  })

  it('the employer-accounts summary says its worst row in that row\'s words', () => {
    const w = banner([employers])
    expect(w.find('.attention-text').text()).toContain("Sign-in failed. JobScraper won't try again")
  })

  it('several items: a count and Review, to the hub itself', () => {
    const w = banner([gmail3, mailbox, model])
    expect(w.find('.attention-text strong').text()).toBe('3 connections need attention.')
    expect(go(w).text()).toBe('Review')
    expect(go(w).attributes('href')).toBe('#/settings/accounts')
  })

  it('the hidden prop hides it (the hub shows it itself) and un-hiding brings it back', async () => {
    const w = banner([gmail3])
    await w.setProps({ hidden: true })
    expect(shown(w)).toBe(false)
    expect(w.find('[role="status"]').exists()).toBe(true)
    await w.setProps({ hidden: false })
    expect(shown(w)).toBe(true)
  })

  it('Dismiss hides it and remembers the sorted id:code list for this browser session', async () => {
    const w = banner([model, gmail3])
    await w.find('button.attention-dismiss').trigger('click')
    expect(shown(w)).toBe(false)
    expect(DISMISS_KEY).toBe('attention.dismissed')
    expect(window.sessionStorage.getItem('attention.dismissed')).toBe('gmail:3:login_refused|model:unreachable')
    // a fresh page load with the same problems stays quiet
    w.unmount()
    expect(shown(banner([gmail3, model]))).toBe(false)
  })

  it('a new problem, or the same item failing a new way, brings it back', async () => {
    const w = banner([gmail3])
    await w.find('button.attention-dismiss').trigger('click')
    await w.setProps({ items: [gmail3, model] })
    expect(shown(w)).toBe(true)
    await w.setProps({ items: [{ ...gmail3, code: 'network' }] })
    expect(shown(w)).toBe(true)
    // and the original problem alone is still the dismissed one
    await w.setProps({ items: [gmail3] })
    expect(shown(w)).toBe(false)
  })

  it('works when storage throws (a private window): Dismiss still hides it for now', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied') })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('denied') })
    const w = banner([gmail3])
    expect(shown(w)).toBe(true)
    await w.find('button.attention-dismiss').trigger('click')
    expect(shown(w)).toBe(false)
  })

  it('draws from attentionItems of the sample: the eight problems read as one line to Review', () => {
    const items = attentionItems(sample)
    expect(items).toHaveLength(8)
    const w = banner(items)
    expect(w.find('.attention-text strong').text()).toBe('8 connections need attention.')
  })
})

describe('ModeChip', () => {
  const chip = status => mount(ModeChip, { props: { status } })

  it('shows "Auto-apply on" only for mode auto, linking to Settings -> Apply', () => {
    const w = chip({ mode: 'auto', missing: [], busy: false })
    expect(w.find('a.mode-chip').exists()).toBe(true)
    expect(w.text()).toContain('Auto-apply on')
    expect(w.find('a').attributes('href')).toBe('#/settings/apply')
    expect(w.find('a').attributes('title')).toContain('Settings → Apply')
  })

  it.each([
    ['dry run', { mode: 'dry_run', missing: [], busy: false }],
    ['null (the route is absent or failed)', null],
    ['an empty answer', {}],
    ['an unknown mode', { mode: 'AUTO ' }],
    ['no props at all', undefined],
  ])('shows nothing for %s', (_n, status) => {
    const w = status === undefined ? mount(ModeChip) : chip(status)
    expect(w.find('.mode-chip').exists()).toBe(false)
    expect(w.text()).toBe('')
  })

  it('follows the status when it changes', async () => {
    const w = chip({ mode: 'dry_run' })
    await w.setProps({ status: { mode: 'auto' } })
    expect(w.find('.mode-chip').exists()).toBe(true)
    await w.setProps({ status: null })
    expect(w.find('.mode-chip').exists()).toBe(false)
  })
})
