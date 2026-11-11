// Q-100 T1-B pins for MailCard's `embedded` prop (lane B, design section 4.1; mail owner
// rows). Without the prop the card is exactly what Q-60 shipped: its own title and the
// connect form always open. Embedded (inside the Gmail card of Settings > Accounts): no
// title; no account yet -> the full connect form; one or more -> the form folds behind
// "Connect another Gmail"; opening it moves focus to the consent checkbox; Cancel folds it
// back (consent un-ticked) and returns focus to the button; a successful connect folds it.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import MailCard from '../src/components/MailCard.vue'
import { dismissToast } from '../src/toast.js'
import { account, CONSENT, fakeMail, mailView } from './mailFake.js'

enableAutoUnmount(afterEach)
afterEach(() => {
  dismissToast()
  vi.unstubAllGlobals()
})

async function card(props, routes) {
  const api = fakeMail({ 'GET mail': mailView({ accounts: [account(1)] }), ...routes })
  const wrapper = mount(MailCard, { props, attachTo: document.body })
  await flushPromises()
  return { api, wrapper }
}
const fold = w => w.find('button.connect-another')
const cancel = w => w.find('button.connect-cancel')
const consent = w => w.find('input.consent-input')

// The markup as the browser would see it, minus Vue's scope ids and comment markers.
const flat = html => html
  .replace(/ data-v-[0-9a-f]+=""/g, '')
  .replace(/<!--.*?-->/g, '')
  .replace(/>\s+</g, '><')
  .replace(/\s+/g, ' ')
  .trim()

describe('MailCard without the embedded prop: unchanged', () => {
  it('keeps its title and the connect form always open, with accounts or without', async () => {
    for (const accounts of [[], [account(1)], [account(1), account(2)]]) {
      const { wrapper } = await card({}, { 'GET mail': mailView({ accounts }) })
      expect(wrapper.find('.mail-title').text()).toBe('Application updates from email')
      expect(wrapper.classes()).not.toContain('embedded')
      expect(fold(wrapper).exists()).toBe(false)
      expect(wrapper.find('.mail-connect-fold').exists()).toBe(false)
      expect(cancel(wrapper).exists()).toBe(false)
      expect(wrapper.find('form.another').exists()).toBe(true)
      wrapper.unmount()
    }
  })

  it('markup pin: the title and the connect form are byte-for-byte what Q-60 shipped', async () => {
    const { wrapper } = await card({})
    expect(flat(wrapper.find('.mail-title').html()))
      .toBe('<h3 class="mail-title">Application updates from email</h3>')
    expect(flat(wrapper.find('.mail-connect').html())).toBe(
      '<div class="mail-connect">'
      + '<div class="consent"><p class="consent-text">JobScraper reads this Gmail read-only.</p>'
      + '<label class="consent-box"><input type="checkbox" class="consent-input"><span>Read this mailbox for application updates</span></label></div>'
      + '<form class="another" novalidate="">'
      + '<div class="field"><label for="mail-address">Gmail address</label><input id="mail-address" type="email" autocomplete="off" spellcheck="false"></div>'
      + '<div class="field"><label for="mail-app-password">App password</label>'
      + '<input id="mail-app-password" type="password" autocomplete="off" spellcheck="false" aria-describedby="mail-app-password-help">'
      + '<p id="mail-app-password-help" class="help"> A 16-character code from your Google Account (it needs 2-Step Verification). Your normal Google password won\'t work. '
      + '<a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener noreferrer">Create an app password</a></p></div>'
      + '<div><button type="submit" class="primary connect" disabled="">Connect mailbox</button></div></form></div>',
    )
  })

  it('a successful connect leaves the form open (it never folds)', async () => {
    const { api, wrapper } = await card({}, { 'POST mail/accounts': { ok: true, account_id: 7 } })
    await consent(wrapper).setValue(true)
    await wrapper.find('#mail-address').setValue('new@inbox.example')
    wrapper.find('#mail-app-password').element.value = 'CANARYpw abcd efgh'
    await wrapper.find('form.another').trigger('submit')
    await flushPromises()
    expect(api.of('POST', 'mail/accounts')).toHaveLength(1)
    expect(fold(wrapper).exists()).toBe(false)
    expect(wrapper.find('form.another').exists()).toBe(true)
  })
})

describe('MailCard embedded', () => {
  it('has no title of its own (the hub card has the heading)', async () => {
    const { wrapper } = await card({ embedded: true })
    expect(wrapper.find('.mail-title').exists()).toBe(false)
    expect(wrapper.classes()).toContain('embedded')
  })

  it('0 accounts: the full connect form, no fold button, no Cancel', async () => {
    const { wrapper } = await card({ embedded: true }, { 'GET mail': mailView({ accounts: [] }) })
    expect(wrapper.find('form.another').exists()).toBe(true)
    expect(consent(wrapper).exists()).toBe(true)
    expect(fold(wrapper).exists()).toBe(false)
    expect(cancel(wrapper).exists()).toBe(false)
  })

  it('1+ accounts: the form is folded behind "Connect another Gmail"', async () => {
    for (const accounts of [[account(1)], [account(1), account(2)]]) {
      const { wrapper } = await card({ embedded: true }, { 'GET mail': mailView({ accounts }) })
      expect(wrapper.findAll('.mail-account')).toHaveLength(accounts.length)
      expect(fold(wrapper).text()).toBe('Connect another Gmail')
      expect(fold(wrapper).attributes('aria-expanded')).toBe('false')
      expect(wrapper.find('form.another').exists()).toBe(false)
      expect(consent(wrapper).exists()).toBe(false)
      expect(wrapper.find('input[type="password"]').exists()).toBe(false)
      wrapper.unmount()
    }
  })

  it('clicking the button shows the form and moves focus to the consent checkbox', async () => {
    const { wrapper } = await card({ embedded: true })
    await fold(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.find('form.another').exists()).toBe(true)
    expect(fold(wrapper).exists()).toBe(false)
    expect(document.activeElement).toBe(consent(wrapper).element)
    expect(cancel(wrapper).text()).toBe('Cancel')
  })

  it('Cancel folds it back, un-ticks consent, and returns focus to the button', async () => {
    const { wrapper } = await card({ embedded: true })
    await fold(wrapper).trigger('click')
    await flushPromises()
    await consent(wrapper).setValue(true)
    await cancel(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.find('form.another').exists()).toBe(false)
    expect(cancel(wrapper).exists()).toBe(false)
    expect(document.activeElement).toBe(fold(wrapper).element)
    // Opened again, the box is not still ticked: consent is given each time.
    await fold(wrapper).trigger('click')
    await flushPromises()
    expect(consent(wrapper).element.checked).toBe(false)
  })

  it('a successful connect folds the form again and sends the password once, to the right place', async () => {
    const PW = 'CANARYpw abcd efgh'
    const views = [mailView({ accounts: [account(1)] }), mailView({ accounts: [account(1), account(7)] })]
    let n = 0
    const { api, wrapper } = await card({ embedded: true }, {
      'GET mail': () => views[Math.min(n++, 1)],
      'POST mail/accounts': { ok: true, account_id: 7 },
    })
    await fold(wrapper).trigger('click')
    await flushPromises()
    await consent(wrapper).setValue(true)
    await wrapper.find('#mail-address').setValue('second@inbox.example')
    wrapper.find('#mail-app-password').element.value = PW
    await wrapper.find('form.another').trigger('submit')
    await flushPromises()
    const posts = api.of('POST', 'mail/accounts')
    expect(posts).toHaveLength(1)
    expect(posts[0].body).toEqual({ address: 'second@inbox.example', app_password: PW, consent_version: CONSENT.version })
    expect(wrapper.find('form.another').exists()).toBe(false)
    expect(fold(wrapper).exists()).toBe(true)
    expect(wrapper.findAll('.mail-account')).toHaveLength(2)
    expect(wrapper.html()).not.toContain('CANARY')
  })

  it('a refused connect keeps the form open with the server\'s words', async () => {
    const { wrapper } = await card({ embedded: true }, {
      'POST mail/accounts': [400, { code: 'login_refused', detail: 'Gmail refused the login. Check the app password.' }],
    })
    await fold(wrapper).trigger('click')
    await flushPromises()
    await consent(wrapper).setValue(true)
    await wrapper.find('#mail-address').setValue('second@inbox.example')
    wrapper.find('#mail-app-password').element.value = 'whatever'
    await wrapper.find('form.another').trigger('submit')
    await flushPromises()
    expect(wrapper.find('.connect-error').text()).toBe('Gmail refused the login. Check the app password.')
    expect(wrapper.find('form.another').exists()).toBe(true)
    expect(fold(wrapper).exists()).toBe(false)
  })
})
