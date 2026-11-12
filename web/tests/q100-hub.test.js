// Q-100 T1-B pins for lane B's Connected accounts hub (design sections 1, 4.1, 4.4):
// every sample state draws the right chip words, a deep link focuses its card's
// heading, a failed load shows the error with Try again while Gmail stays reachable,
// no password is shown, asked for or sent (D-191), and employer emails are shown in
// full (D-193). The hub is mounted with the sample response as a prop; MailCard,
// inside the Gmail card, loads its own data through the fetch stub below.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ConnectionsHub from '../src/components/ConnectionsHub.vue'
import sample from './fixtures/connections.sample.json'
import { setHash } from './helpers.js'
import { cloneSample, routeFetch } from './q100Fake.js'
import { account, fakeMail, mailView } from './mailFake.js'

enableAutoUnmount(afterEach)
beforeEach(() => {
  setHash('')
  routeFetch()                     // mail, connections ...: every route answers 404
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  setHash('')
})

async function hub(connections = cloneSample(sample), props = {}) {
  const w = mount(ConnectionsHub, { props: { connections, ...props }, attachTo: document.body })
  await flushPromises()
  return w
}
const card = (w, id) => w.find(`[data-card="${id}"]`)
const chip = (w, id) => card(w, id).find('.conn-head .state-chip').text()
const variant = name => {
  const v = sample.variants[name]
  if (!v) throw new Error(`no fixture variant ${name}`)
  return v
}

// The words the owner reads, written out here on purpose (not taken from connections.js).
function words(item) {
  switch (item.state) {
    case 'connected': return item.kind === 'edge' ? (item.code === 'in_use' ? 'In use' : 'Ready') : 'Connected'
    case 'attention': return 'Needs attention'
    case 'paused': return 'Paused'
    case 'checking': return 'Checking…'
    case 'not_set_up': return item.optional ? 'Optional' : 'Not set up'
    case 'neutral': return { unreachable: 'Not running', model_missing: 'Model not downloaded', unconfirmed: 'Not confirmed' }[item.code]
    default: throw new Error(`unexpected state ${item.state}`)
  }
}

// The sample with one singleton item (same id) swapped for the variant's.
function withItem(item) {
  const r = cloneSample(sample)
  r.items = r.items.map(i => (i.id === item.id ? item : i))
  return r
}
// Only this Gmail item (the Gmail card shows the worst of all of them).
function onlyGmail(item) {
  const r = cloneSample(sample)
  r.items = r.items.filter(i => i.kind !== 'gmail').concat(item)
  return r
}

describe('ConnectionsHub: the whole sample', () => {
  it('draws the five cards in order, with the right chip words', async () => {
    const w = await hub()
    expect(w.findAll('.conn-card').map(c => c.attributes('data-card')))
      .toEqual(['gmail', 'apply-mailbox', 'edge', 'model', 'employer-accounts'])
    expect(w.find('.hub-title').text()).toBe('Connected accounts')
    expect(chip(w, 'gmail')).toBe('Needs attention')          // the worst of twelve mailboxes
    expect(card(w, 'gmail').find('.conn-line').text()).toBe('7 of 12 mailboxes need attention')
    expect(chip(w, 'apply-mailbox')).toBe('Connected')
    expect(chip(w, 'edge')).toBe('Ready')
    expect(chip(w, 'model')).toBe('Connected')
    expect(chip(w, 'employer-accounts')).toBe('Needs attention')
    expect(card(w, 'employer-accounts').find('.conn-line').text()).toBe('8 accounts, 3 need attention')
  })

  it('each card exposes its state as data-state and its title as a heading', async () => {
    const w = await hub()
    expect(card(w, 'model').attributes('data-state')).toBe('connected')
    expect(card(w, 'gmail').attributes('data-state')).toBe('attention')
    expect(w.find('#conn-model-title').text()).toBe('Local AI')
    expect(card(w, 'model').attributes('aria-labelledby')).toBe('conn-model-title')
  })

  it('no Gmail items at all: one Optional card with the connect form (MailCard)', async () => {
    const r = cloneSample(sample)
    r.items = r.items.filter(i => i.kind !== 'gmail')
    const w = await hub(r)
    expect(chip(w, 'gmail')).toBe('Optional')
    expect(card(w, 'gmail').find('.conn-line').text()).toBe('Optional. Connect Gmail to see application status changes from email.')
  })

  it('a Gmail card links to Applications and embeds the mail card without its own title', async () => {
    const w = await hub()
    expect(card(w, 'gmail').find('.mail-card.embedded').exists()).toBe(true)
    expect(card(w, 'gmail').find('.mail-title').exists()).toBe(false)
    expect(card(w, 'gmail').find('a[href="#/applications"]').exists()).toBe(true)
  })
})

describe('ConnectionsHub: every sample state shows the right chip', () => {
  const GMAIL = Object.keys(sample.variants).filter(n => variant(n).item?.kind === 'gmail' && n !== 'gmail_none')
  const EDGE = Object.keys(sample.variants).filter(n => variant(n).item?.kind === 'edge')
  const MODEL = Object.keys(sample.variants).filter(n => variant(n).item?.kind === 'model')
  const MAILBOX = Object.keys(sample.variants).filter(n => variant(n).item?.id === 'apply-mailbox')

  it.each(GMAIL)('gmail variant %s', async name => {
    const item = variant(name).item
    const w = await hub(onlyGmail(item))
    expect(chip(w, 'gmail')).toBe(words(item))
    expect(card(w, 'gmail').attributes('data-state')).toBe(item.state)
  })

  it.each(MAILBOX)('application mailbox variant %s', async name => {
    const item = variant(name).item
    const w = await hub(withItem(item))
    expect(chip(w, 'apply-mailbox')).toBe(words(item))
    // A mailbox that needs the owner (or isn't set up) says how to fix it, as commands.
    const fix = card(w, 'apply-mailbox').find('.conn-fix')
    if (item.state === 'attention' || item.state === 'not_set_up') {
      expect(fix.exists()).toBe(true)
      // Q-104 (c): an optional card that isn't set up invites ("Set it up"); only a card that
      // needs the owner says "See how to fix". The commands inside are the same either way.
      const label = fix.find('summary').text()
      if (item.state === 'not_set_up' && item.optional) {
        expect(label).toBe('Set it up')
        expect(fix.text()).not.toContain('See how to fix')
      } else if (item.state === 'attention') {
        expect(label).toBe('See how to fix')
      }
      // D-198 H1: run through run.ps1, introduced by where to run it
      expect(fix.text()).toContain('In PowerShell, in the JobScraper folder')
      expect(fix.text()).toContain('.\\run.ps1 mail set-password')
      expect(fix.text()).toContain('.\\run.ps1 mail test')
      expect(fix.text()).not.toContain('python -m jobscraper')
    } else {
      expect(fix.exists()).toBe(false)
    }
  })

  it.each(EDGE)('apply browser variant %s', async name => {
    const item = variant(name).item
    const w = await hub(withItem(item))
    expect(chip(w, 'edge')).toBe(words(item))
  })

  it.each(MODEL)('local AI variant %s', async name => {
    const item = variant(name).item
    const w = await hub(withItem(item))
    expect(chip(w, 'model')).toBe(words(item))
    // Check again is offered unless the AI is off or misconfigured or already probing.
    const offered = !['ai_off', 'misconfigured', 'probing'].includes(item.code)
    expect(card(w, 'model').find('button.check-again').exists()).toBe(offered)
  })

  it('the backup mailbox row shows its own chip once set up, and is absent when unset', async () => {
    const ok = variant('apply_mailbox_backup_ok').item
    const w1 = await hub(withItem(ok))
    expect(w1.find('[data-card-part="apply-mailbox:backup"] .state-chip').text()).toBe('Connected')
    const unset = variant('apply_mailbox_backup_unset').item
    const w2 = await hub(withItem(unset))
    expect(w2.find('[data-card-part="apply-mailbox:backup"]').exists()).toBe(false)
  })

  it('D-198 M2: with no backup item at all (same user as the primary) the mailbox card still draws, with no backup part', async () => {
    const r = cloneSample(sample)
    r.items = r.items.filter(i => i.id !== 'apply-mailbox:backup')
    const w = await hub(r)
    expect(card(w, 'apply-mailbox').exists()).toBe(true)
    expect(w.find('[data-card-part="apply-mailbox:backup"]').exists()).toBe(false)
    expect(w.text()).not.toContain('Backup mailbox')
  })

  it('D-198 H1/M1: the employer fix says where to run it, then gives one run.ps1 line with the careers URL', async () => {
    const row = variant('employer_signin_failed').employer_account
    const r = cloneSample(sample)
    r.employer_accounts = r.employer_accounts.map(a => (a.id === row.id ? row : a))
    const w = await hub(r)
    const fix = w.find(`.employer-detail[data-account="${row.id}"] details.employer-fix`)
    expect(fix.exists()).toBe(true)
    const text = fix.text()
    const intro = text.indexOf('In PowerShell, in the JobScraper folder')
    const cmd = text.indexOf('.\\run.ps1 accounts add')
    expect(intro).toBeGreaterThanOrEqual(0)
    expect(cmd).toBeGreaterThan(intro)                       // the introduction comes first
    expect(fix.findAll('pre')).toHaveLength(1)
    expect(fix.find('pre').text()).toBe(`.\\run.ps1 accounts add --url https://${row.tenant_host}/careers --email ${row.email}`)
    expect(fix.find('pre').text()).not.toMatch(/https:\/\/\S+\/ /)   // never the bare host root
    expect(fix.find('.employer-fix-note').text()).toContain('the password never goes through this page')
  })

  it('employer summary: worst state, or Optional with the empty-state text', async () => {
    const worst = variant('employer_summary_worst').item
    const w1 = await hub(withItem(worst))
    expect(chip(w1, 'employer-accounts')).toBe('Needs attention')
    const none = variant('employer_summary_none').item
    const r = withItem(none)
    r.employer_accounts = []
    const w2 = await hub(r)
    expect(chip(w2, 'employer-accounts')).toBe('Optional')
    expect(card(w2, 'employer-accounts').find('.employer-empty').text()).toMatch(/^No employer accounts yet\./)
  })

  const ROWS = Object.keys(sample.variants).filter(n => variant(n).employer_account)
  it.each(ROWS)('employer row variant %s', async name => {
    const row = variant(name).employer_account
    const r = cloneSample(sample)
    r.employer_accounts = r.employer_accounts.map(a => (a.id === row.id ? row : a))
    const w = await hub(r)
    const el = w.find(`.employer-row[data-account="${row.id}"]`)
    expect(el.exists()).toBe(true)
    expect(el.attributes('data-state')).toBe(row.state)
    expect(el.find('.state-chip').text()).toBe(words(row))
    // Only a failed sign-in, an existing account or a missing password has a fix command.
    const fixable = ['signin_failed', 'exists_no_password', 'password_missing'].includes(row.code)
    const detail = w.find(`.employer-detail[data-account="${row.id}"]`)
    expect(detail.exists() && detail.find('details.employer-fix').exists()).toBe(fixable)
    if (fixable) {
      // D-198 H1/M1: the URL names the careers site (the bare host root names no tenant to the
      // CLI), the command is run through run.ps1, and the owner is told where and in what.
      expect(detail.find('pre').text())
        .toBe(`.\\run.ps1 accounts add --url https://${row.tenant_host}/careers --email ${row.email}`)
      expect(detail.find('details.employer-fix').text()).toContain('In PowerShell, in the JobScraper folder')
      expect(detail.find('pre').text()).not.toContain('python -m jobscraper')
    }
  })
})

describe('ConnectionsHub: deep links focus the card heading', () => {
  it.each([
    ['#/settings/accounts/model', 'model'],
    ['#/settings/accounts/apply-mailbox', 'apply-mailbox'],
    ['#/settings/accounts/apply-mailbox:backup', 'apply-mailbox'],   // the backup lives on the mailbox card
    ['#/settings/accounts/gmail:3', 'gmail'],                        // any gmail:<id> is the Gmail card
    ['#/settings/accounts/employer-accounts', 'employer-accounts'],
    ['#/settings/accounts/edge', 'edge'],
  ])('%s focuses the %s heading', async (hash, id) => {
    setHash(hash)
    const w = await hub()
    const heading = w.find(`#conn-${id}-title`).element
    expect(document.activeElement).toBe(heading)
    expect(card(w, id).classes()).toContain('is-target')
    expect(heading.tagName).toBe('H4')
    expect(heading.getAttribute('tabindex')).toBe('-1')   // focusable by script, not a tab stop
  })

  it('no item in the hash focuses nothing; an unknown item does not throw', async () => {
    setHash('#/settings/accounts')
    let w = await hub()
    expect(w.find('.is-target').exists()).toBe(false)
    expect(document.activeElement.classList.contains('conn-title')).toBe(false)
    w.unmount()
    setHash('#/settings/accounts/no-such-card')
    w = await hub()
    expect(w.find('.is-target').exists()).toBe(false)
  })

  it('waits for the data: the link works once the connections arrive', async () => {
    setHash('#/settings/accounts/model')
    const w = await hub(null)
    expect(w.find('.conn-card').exists()).toBe(false)
    await w.setProps({ connections: cloneSample(sample) })
    await flushPromises()
    expect(document.activeElement).toBe(w.find('#conn-model-title').element)
  })
})

describe('ConnectionsHub: a failed or absent load', () => {
  it('null connections: the error with Try again, never a blank or an all-good', async () => {
    const w = await hub(null, { failed: true })
    const alert = w.find('[role="alert"]')
    expect(alert.text()).toContain("Couldn't load your connections.")
    expect(alert.find('button').text()).toBe('Try again')
    expect(w.find('.conn-card').exists()).toBe(false)
    expect(w.find('.state-chip').exists()).toBe(false)   // no chip, so nothing reads as connected
  })

  it('Try again asks the parent to reload', async () => {
    const w = await hub(null, { failed: true })
    await w.find('button.hub-retry').trigger('click')
    expect(w.emitted('reload')).toHaveLength(1)
  })

  it('Gmail stays reachable: the plain MailCard (with its title and connect form) is shown', async () => {
    fakeMail({ 'GET mail': mailView({ accounts: [] }) })
    const w = await hub(null, { failed: true })
    expect(w.find('.mail-card').exists()).toBe(true)
    expect(w.find('.mail-card.embedded').exists()).toBe(false)
    expect(w.find('.mail-title').text()).toBe('Application updates from email')
    expect(w.find('form.another').exists()).toBe(true)
  })

  it('still loading with no data: placeholder rows, no error yet', async () => {
    const w = await hub(null, { loading: true })
    expect(w.find('[role="alert"]').exists()).toBe(false)
    expect(w.find('[aria-busy="true"]').exists()).toBe(true)
  })

  it('a later failed refresh keeps the last cards and says so', async () => {
    const w = await hub(cloneSample(sample), { failed: true })
    expect(w.find('.conn-card').exists()).toBe(true)
    expect(w.find('.hub-stale').text()).toBe("Couldn't refresh just now. Showing the last result.")
    expect(w.find('[role="alert"]').exists()).toBe(false)
  })
})

describe('ConnectionsHub: no password, anywhere (D-191)', () => {
  const CANARY = 'CANARYsecret123'

  it('the hub has no password field, and nothing the server might wrongly send is drawn', async () => {
    const r = cloneSample(sample)
    for (const i of r.items) { i.password = CANARY; i.app_password = CANARY; i.facts = { ...i.facts, password: CANARY, secret: CANARY } }
    for (const a of r.employer_accounts) { a.password = CANARY; a.secret = CANARY }
    const w = await hub(r)
    expect(w.find('input[type="password"]').exists()).toBe(false)
    expect(w.html()).not.toContain(CANARY)
    expect(w.html()).not.toMatch(/--password/)
    expect(w.text()).toContain('Passwords stay in Windows Credential Manager on this PC')
  })

  it('fix commands never carry a password and tell the owner the command asks for it', async () => {
    const r = cloneSample(sample)
    r.items = r.items.map(i => (i.id === 'apply-mailbox' ? variant('apply_mailbox_no_password').item : i))
    const w = await hub(r)
    const fixes = w.findAll('.conn-fix, .employer-fix')
    expect(fixes.length).toBeGreaterThan(1)
    for (const f of fixes) {
      for (const pre of f.findAll('pre')) expect(pre.text()).not.toMatch(/password\s+\S|--password|-p\s/i)
    }
    expect(card(w, 'apply-mailbox').find('.conn-fix-note').text()).toContain('the password never goes through this page')
    expect(w.find('.employer-fix-note').text()).toContain('the password never goes through this page')
  })

  it('rendering sends nothing but reads; Check again posts with no body', async () => {
    const api = routeFetch({ 'POST connections/model/check': [202, {}] })
    const w = await hub()
    expect(api.calls.every(c => c.method === 'GET')).toBe(true)
    await w.find('button.check-again').trigger('click')
    await flushPromises()
    const posts = api.calls.filter(c => c.method !== 'GET')
    expect(posts.map(c => `${c.method} ${c.path}`)).toEqual(['POST connections/model/check'])
    expect(posts[0].raw).toBe('')
    expect(w.emitted('reload')).toHaveLength(1)
  })

  it('the Credential Manager hint is text, not a control', async () => {
    const w = await hub()
    const note = card(w, 'employer-accounts').text()
    expect(note).toContain('Windows Credential Manager')
    expect(card(w, 'employer-accounts').find('input').exists()).toBe(false)
    expect(card(w, 'employer-accounts').findAll('button').map(b => b.text())).toEqual([])
  })
})

describe('ConnectionsHub: employer accounts', () => {
  it('shows every email in full (D-193), one row per account', async () => {
    const w = await hub()
    const emails = w.findAll('.employer-row .cell-email').map(c => c.text())
    expect(emails).toEqual(sample.employer_accounts.map(a => a.email))
    expect(emails).toHaveLength(8)
    for (const e of emails) {
      expect(e).toMatch(/^owner\+\d+@example\.com$/)
      expect(e).not.toMatch(/[*•…]|\.\.\./)
    }
  })

  it('the site, sign-in and verified columns read in words', async () => {
    const w = await hub()
    const row13 = w.find('.employer-row[data-account="13"]')
    expect(row13.find('.cell-site').text()).toBe('acme.wd3.myworkdayjobs.com')
    expect(row13.find('.verified').text()).toBe('Verified')
    expect(w.find('.employer-row[data-account="14"] .verified').text()).toBe('Not verified')
    expect(w.find('.employer-row[data-account="14"]').text()).toMatch(/failed/)
  })

  it('names the sites that need no account and is read-only (no buttons in the table)', async () => {
    const w = await hub()
    expect(card(w, 'employer-accounts').text()).toContain('No account needed: Greenhouse, Lever, Ashby. They apply as a guest.')
    expect(w.find('.employer-table button').exists()).toBe(false)
  })
})

describe('ConnectionsHub: Gmail card uses the real MailCard', () => {
  it('with an account connected, the connect form is folded behind "Connect another Gmail"', async () => {
    fakeMail({ 'GET mail': mailView({ accounts: [account(1)] }) })
    const w = await hub()
    const mail = card(w, 'gmail')
    expect(mail.find('.mail-account').exists()).toBe(true)
    expect(mail.find('button.connect-another').text()).toBe('Connect another Gmail')
    expect(mail.find('form.another').exists()).toBe(false)
  })
})
