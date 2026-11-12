// Q-104 follow-ups to Q-100, pinned test-first (the (f) ModeChip refresh pin lives in
// q100-shell.test.js beside the other chip pins, and (d) in tests/test_connections.py):
//   (b) the employer accounts hint shows the export command the way the owner types it,
//       `.\run.ps1 accounts export-edge`, after "in PowerShell, in the JobScraper folder"
//       (D-198 M1 fixed the other commands and missed this one);
//   (c) a card that is optional and not set up invites ("Set it up"); only a card that
//       needs the owner says "See how to fix".
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ConnectionCard from '../src/components/ConnectionCard.vue'
import ConnectionsHub from '../src/components/ConnectionsHub.vue'
import EmployerAccounts from '../src/components/EmployerAccounts.vue'
import sample from './fixtures/connections.sample.json'
import { setHash } from './helpers.js'
import { cloneSample, routeFetch } from './q100Fake.js'

enableAutoUnmount(afterEach)
beforeEach(() => {
  setHash('')
  routeFetch()
})
afterEach(() => {
  vi.unstubAllGlobals()
  setHash('')
})

const COMMAND = '.\\run.ps1 accounts export-edge'      // one backslash in the string, and in the DOM text
const INTRO = /in powershell, in the jobscraper folder/i   // mid-sentence or sentence-start

describe('Q-104 b: the employer accounts export line', () => {
  const lineOf = w => w.findAll('.employer-note').find(p => p.text().includes('export-edge'))

  it('renders exactly .\\run.ps1 accounts export-edge, after the PowerShell introduction', () => {
    const w = mount(EmployerAccounts, { props: { accounts: cloneSample(sample).employer_accounts } })
    const line = lineOf(w)
    expect(line, 'a line mentioning export-edge').toBeTruthy()
    const text = line.text()
    const intro = text.search(INTRO)
    const cmd = text.indexOf(COMMAND)
    expect(intro).toBeGreaterThanOrEqual(0)
    expect(cmd).toBeGreaterThan(intro)                         // where to run it comes first
    expect(line.findAll('code').map(c => c.text())).toContain(COMMAND)
  })

  it('has one backslash, never two, and never the bare "accounts export-edge" without run.ps1', () => {
    const w = mount(EmployerAccounts, { props: { accounts: cloneSample(sample).employer_accounts } })
    const text = lineOf(w).text()
    expect(text).not.toContain('\\\\run.ps1')
    expect(text).not.toContain('python -m jobscraper')
    const bare = text.split('export-edge').length - 1
    const full = text.split(COMMAND).length - 1
    expect(bare).toBe(full)
    expect(full).toBe(1)
  })

  it('shows the same line inside the hub card, as text and not a control', async () => {
    const w = mount(ConnectionsHub, { props: { connections: cloneSample(sample) }, attachTo: document.body })
    await flushPromises()
    const card = w.find('[data-card="employer-accounts"]')
    const line = card.findAll('.employer-note').find(p => p.text().includes('export-edge'))
    expect(line.text()).toMatch(INTRO)
    expect(line.text()).toContain(COMMAND)
    expect(card.find('input').exists()).toBe(false)             // D-191
  })
})

describe('Q-104 c: "Set it up" for an optional card that is not set up', () => {
  const FIX = { note: 'In PowerShell, in the JobScraper folder.', commands: ['.\\run.ps1 mail set-password', '.\\run.ps1 mail test'] }
  const mountCard = item => mount(ConnectionCard, {
    props: { cardId: 'apply-mailbox', title: 'Application mailbox', item, fix: FIX },
  })

  it('an optional item in state not_set_up shows "Set it up", never "See how to fix"', () => {
    const w = mountCard({ id: 'apply-mailbox', kind: 'apply_mailbox', state: 'not_set_up', code: 'none', optional: true, facts: {} })
    expect(w.find('.conn-fix summary').text()).toBe('Set it up')
    expect(w.text()).toContain('Set it up')
    expect(w.text()).not.toContain('See how to fix')
    // the commands are still there to copy
    expect(w.findAll('.conn-fix pre').map(p => p.text())).toEqual(FIX.commands)
  })

  it('an attention item still shows "See how to fix"', () => {
    const w = mountCard({ id: 'apply-mailbox', kind: 'apply_mailbox', state: 'attention', code: 'no_password', optional: true, facts: {} })
    expect(w.find('.conn-fix summary').text()).toBe('See how to fix')
    expect(w.text()).not.toContain('Set it up')
  })

  it('an attention item that is not optional also keeps "See how to fix"', () => {
    const w = mountCard({ id: 'apply-mailbox', kind: 'apply_mailbox', state: 'attention', code: 'login_failed', optional: false, facts: {} })
    expect(w.find('.conn-fix summary').text()).toBe('See how to fix')
  })

  it('in the hub: the unset application mailbox says "Set it up"; a mailbox that needs attention says "See how to fix"', async () => {
    const unset = sample.variants.apply_mailbox_unset.item
    const bad = sample.variants.apply_mailbox_no_password.item
    expect(unset.optional).toBe(true)
    expect(unset.state).toBe('not_set_up')
    expect(bad.state).toBe('attention')
    for (const [item, label] of [[unset, 'Set it up'], [bad, 'See how to fix']]) {
      const r = cloneSample(sample)
      r.items = r.items.map(i => (i.id === item.id ? item : i))
      const w = mount(ConnectionsHub, { props: { connections: r }, attachTo: document.body })
      await flushPromises()
      const fix = w.find('[data-card="apply-mailbox"] .conn-fix')
      expect(fix.exists()).toBe(true)
      expect(fix.find('summary').text()).toBe(label)
      w.unmount()
    }
  })
})
