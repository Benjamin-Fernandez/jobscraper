// WP-T6 (Q-60): the Settings "Email updates" card (mail_status_design.md 11.1, F-50a-c, F-50p).
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import MailCard from '../src/components/MailCard.vue'
import { dismissToast, toast } from '../src/toast.js'
import { CONSENT, account, fakeMail, mailView } from './mailFake.js'

const PW = 'CANARYpw abcd efgh'

afterEach(() => {
  dismissToast()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

async function card(routes) {
  const api = fakeMail({ 'GET mail': mailView(), ...routes })
  const wrapper = mount(MailCard, { attachTo: document.body })
  await flushPromises()
  return { api, wrapper }
}

describe('MailCard', () => {
  it('lists each mailbox with its state and switch', async () => {
    const { wrapper } = await card({
      'GET mail': mailView({ accounts: [account(1), account(2, { enabled: false, state: 'paused', code: 'login_refused', message: 'Gmail refused the login.' })] }),
    })
    const rows = wrapper.findAll('.mail-account')
    expect(rows.map(r => r.attributes('data-account'))).toEqual(['1', '2'])
    expect(rows[1].attributes('data-state')).toBe('paused')
    expect(rows[0].find('input[role=switch].switch-input').element.checked).toBe(true)
    expect(rows[1].find('.account-status').text()).toContain('Off')
    wrapper.unmount()
  })

  it('switching a mailbox off sends enabled: false', async () => {
    const { api, wrapper } = await card({ 'PATCH mail/accounts/1': account(1, { enabled: false }) })
    await wrapper.find('.mail-account[data-account="1"] .switch-input').setValue(false)
    await flushPromises()
    expect(api.of('PATCH', 'mail/accounts/1')[0].body).toEqual({ enabled: false })
    expect(wrapper.find('.mail-account[data-account="1"]').attributes('data-enabled')).toBe('false')
    wrapper.unmount()
  })

  it('connect needs consent and both fields, sends the password once and clears it', async () => {
    const { api, wrapper } = await card({
      'GET mail': mailView({ accounts: [] }),
      'POST mail/accounts': { ok: true, account_id: 7 },
    })
    expect(wrapper.find('.connect').element.disabled).toBe(true)
    await wrapper.find('.consent-input').setValue(true)
    await wrapper.find('form.another').trigger('submit')
    await flushPromises()
    expect(wrapper.find('.connect-error').text()).toBe('Enter your Gmail address and app password, and tick the box.')
    expect(api.of('POST', 'mail/accounts')).toHaveLength(0)
    await wrapper.find('#mail-address').setValue(' alex@inbox.example ')
    wrapper.find('#mail-app-password').element.value = PW
    await wrapper.find('form.another').trigger('submit')
    await flushPromises()
    const posts = api.of('POST', 'mail/accounts')
    expect(posts).toHaveLength(1)
    expect(posts[0].body).toEqual({ address: 'alex@inbox.example', app_password: PW, consent_version: CONSENT.version })
    expect(wrapper.find('#mail-app-password').element.value).toBe('')
    expect(toast.current.message).toContain('Connected')
    const others = api.calls.filter(c => c !== posts[0])
    expect(others.every(c => !c.path.includes('CANARY') && !c.raw.includes('CANARY'))).toBe(true)
    expect(wrapper.html()).not.toContain('CANARY')
    wrapper.unmount()
  })

  it('a refused login shows the server text and keeps nothing', async () => {
    const { wrapper } = await card({
      'GET mail': mailView({ accounts: [] }),
      'POST mail/accounts': [400, { code: 'login_refused', detail: 'Gmail refused the login. Check the app password.' }],
    })
    await wrapper.find('.consent-input').setValue(true)
    await wrapper.find('#mail-address').setValue('alex@inbox.example')
    wrapper.find('#mail-app-password').element.value = PW
    await wrapper.find('form.another').trigger('submit')
    await flushPromises()
    expect(wrapper.find('.connect-error').text()).toBe('Gmail refused the login. Check the app password.')
    expect(wrapper.find('#mail-app-password').element.value).toBe('')
    expect(wrapper.html()).not.toContain('CANARY')
    wrapper.unmount()
  })

  it('Check now: 409 busy shows the reason; 202 polls every 5 s while running', async () => {
    let running = false
    const { api, wrapper } = await card({
      'GET mail': () => mailView({ sync: { running, started_at: null, next_at: null, last: null } }),
      'POST mail/sync': [409, { code: 'busy', detail: 'A check is already running.' }],
    })
    await wrapper.find('.check-now').trigger('click')
    await flushPromises()
    expect(wrapper.find('.check-error').text()).toBe('A check is already running.')
    wrapper.unmount()

    vi.useFakeTimers()
    running = true
    const second = await card({
      'GET mail': () => mailView({ sync: { running, started_at: null, next_at: null, last: { state: 'ok' } } }),
    })
    const n = second.api.of('GET', 'mail').length
    await vi.advanceTimersByTimeAsync(5000)
    expect(second.api.of('GET', 'mail').length).toBe(n + 1)
    running = false
    await vi.advanceTimersByTimeAsync(5000)
    await flushPromises()
    expect(toast.current?.message).toMatch(/^Check finished: 1 updated, 2 to review\.$/)
    const settled = second.api.of('GET', 'mail').length
    await vi.advanceTimersByTimeAsync(20000)
    expect(second.api.of('GET', 'mail').length).toBe(settled)
    second.wrapper.unmount()
    expect(api.fetch).toBeDefined()
  })

  it('disconnect asks first, then deletes', async () => {
    const { api, wrapper } = await card({ 'DELETE mail/accounts/1': { ok: true, vault_kept: false } })
    await wrapper.find('.mail-account[data-account="1"] .disconnect').trigger('click')
    const dlg = wrapper.find('.disconnect-confirm[role=group]')
    expect(dlg.exists()).toBe(true)
    expect(dlg.text()).toContain('deletes its app password')
    expect(api.of('DELETE', 'mail/accounts/1')).toHaveLength(0)
    await wrapper.find('.disconnect-yes').trigger('click')
    await flushPromises()
    expect(api.of('DELETE', 'mail/accounts/1')).toHaveLength(1)
    wrapper.unmount()
  })

  it('a server without /api/mail shows the not-offered note', async () => {
    const { wrapper } = await card({ 'GET mail': [404, { detail: 'Not Found' }] })
    expect(wrapper.find('.not-offered').exists()).toBe(true)
    expect(wrapper.find('.mail-account').exists()).toBe(false)
    wrapper.unmount()
  })
})
