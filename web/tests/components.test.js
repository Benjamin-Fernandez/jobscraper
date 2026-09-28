import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import CompanyMark from '../src/components/CompanyMark.vue'
import Icon from '../src/components/Icon.vue'
import ToastHost from '../src/components/ToastHost.vue'
import { hue, initials } from '../src/marks.js'
import { cleanLocation } from '../src/format.js'
import { dismissToast, showToast, toast, TOAST_MS } from '../src/toast.js'

afterEach(() => {
  dismissToast()
  vi.useRealTimers()
})

describe('company monograms (M13-T4)', () => {
  it('initials: two words, inner capitals, all caps, one plain word', () => {
    expect(initials('Standard Chartered')).toBe('SC')
    expect(initials('Futu / Moomoo')).toBe('FM')
    expect(initials('GovTech')).toBe('GT')
    expect(initials('OKX')).toBe('OK')
    expect(initials('Grab')).toBe('G')
    expect(initials('2C2P')).toBe('2C')
    expect(initials('')).toBe('?')
  })

  it('a company keeps one colour, whatever the case, and names spread apart', () => {
    expect(hue('Grab')).toBe(hue('grab'))
    expect(hue('Grab')).toBeGreaterThanOrEqual(0)
    expect(hue('Grab')).toBeLessThan(360)
    const hues = new Set(['OKX', 'GovTech', 'Shopee', 'Grab', 'Stripe', 'Visa'].map(hue))
    expect(hues.size).toBe(6)
  })

  it('the tile is decorative: the name is always written beside it', () => {
    const w = mount(CompanyMark, { props: { name: 'Standard Chartered', size: 'lg' } })
    expect(w.text()).toBe('SC')
    expect(w.attributes('aria-hidden')).toBe('true')
    expect(w.classes()).toContain('lg')
    expect(w.attributes('style')).toContain(`--h: ${hue('Standard Chartered')}`)
  })
})

describe('locations', () => {
  it('drops a place the feed repeats, keeping the order', () => {
    expect(cleanLocation('Singapore, Singapore')).toBe('Singapore')
    expect(cleanLocation('SG6 Singapore; Singapore')).toBe('SG6 Singapore, Singapore')
    expect(cleanLocation('Singapore | Hong Kong | SINGAPORE')).toBe('Singapore, Hong Kong')
    expect(cleanLocation(null)).toBe('')
  })
})

describe('icons', () => {
  it('draws from data - no v-html - and hides itself from screen readers', () => {
    const w = mount(Icon, { props: { name: 'check' } })
    expect(w.find('svg').attributes('aria-hidden')).toBe('true')
    expect(w.findAll('path')).toHaveLength(1)
    expect(mount(Icon, { props: { name: 'no-such-icon' } }).find('svg').element.children).toHaveLength(0)
  })
})

describe('toast (M13-T2)', () => {
  it('shows the message with Undo and a link, and Undo runs once and closes it', async () => {
    const run = vi.fn()
    const host = mount(ToastHost)
    showToast({ message: 'Marked applied: Engineer at OKX', action: { label: 'Undo', run }, link: { label: 'View in Applications', href: '#/applications' } })
    await host.vm.$nextTick()
    expect(host.find('[role="status"]').text()).toContain('Marked applied: Engineer at OKX')
    expect(host.find('.toast-link').attributes('href')).toBe('#/applications')
    await host.find('.toast-action').trigger('click')
    expect(run).toHaveBeenCalledTimes(1)
    expect(toast.current).toBeNull()
  })

  it('goes away by itself, and a newer toast replaces an older one', () => {
    vi.useFakeTimers()
    const first = showToast({ message: 'one' })
    showToast({ message: 'two' })
    expect(toast.current.message).toBe('two')
    dismissToast(first)                       // closing a stale id leaves the new one
    expect(toast.current.message).toBe('two')
    vi.advanceTimersByTime(TOAST_MS)
    expect(toast.current).toBeNull()
  })

  it('the region stays in the page so screen readers hear every message', () => {
    const host = mount(ToastHost)
    expect(host.find('[aria-live="polite"]').exists()).toBe(true)
  })
})
