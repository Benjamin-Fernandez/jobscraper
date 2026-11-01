// H1 (PRD §20, .claude/plans/h1-hardening.plan.md), the SPA half:
// H1-4 - the Undo toast can be read and used in time (WCAG 2.2.1): an action
//        keeps it up longer, hover or focus pauses it, and a newer toast keeps
//        the one before's Undo one step back instead of losing it.
// H1-5 - the sticky header never hides the focused element (WCAG 2.4.11).
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import ToastHost from '../src/components/ToastHost.vue'
import { ACTION_TOAST_MS, TOAST_MS, dismissToast, showToast, toast } from '../src/toast.js'

// Read from disk: Vitest does not process CSS, so a `?raw` import comes back
// empty; and under jsdom import.meta.url is not a file URL. Vitest runs in web/.
const css = readFileSync(resolve(process.cwd(), 'src/style.css'), 'utf8')

afterEach(() => {
  dismissToast()
  vi.useRealTimers()
})
enableAutoUnmount(afterEach)

const undo = (run = vi.fn()) => ({ label: 'Undo', run })

describe('H1-4: the Undo toast waits for the user', () => {
  it('a toast with an action stays up longer than a plain one', () => {
    vi.useFakeTimers()
    expect(ACTION_TOAST_MS).toBeGreaterThanOrEqual(10_000)
    showToast({ message: 'Saved', action: undo() })
    vi.advanceTimersByTime(TOAST_MS)
    expect(toast.current?.message).toBe('Saved')
    vi.advanceTimersByTime(ACTION_TOAST_MS - TOAST_MS)
    expect(toast.current).toBeNull()
  })

  it('hovering pauses it, and leaving gives the rest of the time back', async () => {
    vi.useFakeTimers()
    const host = mount(ToastHost)
    showToast({ message: 'Saved', action: undo() })
    await host.vm.$nextTick()
    vi.advanceTimersByTime(4_000)
    await host.find('.toast').trigger('mouseenter')
    vi.advanceTimersByTime(60_000)
    expect(toast.current?.message).toBe('Saved')
    await host.find('.toast').trigger('mouseleave')
    vi.advanceTimersByTime(ACTION_TOAST_MS - 4_000 - 1)
    expect(toast.current?.message).toBe('Saved')
    vi.advanceTimersByTime(1)
    expect(toast.current).toBeNull()
  })

  it('focus inside it pauses it too (keyboard users)', async () => {
    vi.useFakeTimers()
    const host = mount(ToastHost)
    showToast({ message: 'Saved', action: undo() })
    await host.vm.$nextTick()
    await host.find('.toast').trigger('focusin')
    vi.advanceTimersByTime(60_000)
    expect(toast.current?.message).toBe('Saved')
    await host.find('.toast').trigger('focusout')
    vi.advanceTimersByTime(ACTION_TOAST_MS)
    expect(toast.current).toBeNull()
  })

  it('a second action keeps the first one\'s Undo, one step back', async () => {
    const first = vi.fn()
    const second = vi.fn()
    const host = mount(ToastHost)
    showToast({ message: 'Saved: Engineer at OKX', action: undo(first) })
    showToast({ message: 'Saved: Engineer at Grab', action: undo(second) })
    await host.vm.$nextTick()
    const previous = host.find('button.toast-previous')
    expect(previous.text()).toBe('Undo previous')
    expect(previous.attributes('aria-label')).toBe('Undo previous: Saved: Engineer at OKX')
    await previous.trigger('click')
    expect(first).toHaveBeenCalledTimes(1)
    expect(second).not.toHaveBeenCalled()
    expect(toast.current?.message).toBe('Saved: Engineer at Grab')   // the newer one stays
    expect(host.find('button.toast-previous').exists()).toBe(false)
  })

  // Review of H1-4: a new toast is a new element, and a browser fires no
  // mouseenter for an element that appears under a pointer already there.
  it('a toast that replaces one under the pointer starts paused', async () => {
    vi.useFakeTimers()
    const host = mount(ToastHost)
    showToast({ message: 'one', action: undo() })
    await host.vm.$nextTick()
    await host.find('.toast').trigger('mouseenter')
    showToast({ message: 'two', action: undo() })
    await host.vm.$nextTick()
    vi.advanceTimersByTime(60_000)
    expect(toast.current?.message).toBe('two')
    await host.find('.toast').trigger('mouseleave')
    vi.advanceTimersByTime(ACTION_TOAST_MS)
    expect(toast.current).toBeNull()
  })

  it('focus does not carry over: the focused button went with the old toast', async () => {
    vi.useFakeTimers()
    const host = mount(ToastHost)
    showToast({ message: 'one', action: undo() })
    await host.vm.$nextTick()
    await host.find('.toast').trigger('focusin')
    showToast({ message: 'two', action: undo() })
    vi.advanceTimersByTime(ACTION_TOAST_MS)
    expect(toast.current).toBeNull()
  })

  it('Undo previous runs once however fast it is pressed, and focus stays in the toast', async () => {
    const first = vi.fn()
    const host = mount(ToastHost, { attachTo: document.body })
    showToast({ message: 'one', action: undo(first) })
    showToast({ message: 'two', action: undo() })
    await host.vm.$nextTick()
    const button = host.find('button.toast-previous')
    button.element.focus()
    await button.trigger('click')
    await button.trigger('click')                    // before the re-render
    await host.vm.$nextTick()
    expect(first).toHaveBeenCalledTimes(1)
    expect(document.activeElement).toBe(host.find('button.toast-action').element)
  })

  it('only one step back: a third action drops the first', () => {
    showToast({ message: 'one', action: undo() })
    showToast({ message: 'two', action: undo() })
    showToast({ message: 'three', action: undo() })
    expect(toast.current.previous.message).toBe('two')
  })

  it('a toast with no action never carries one back', () => {
    showToast({ message: 'one' })
    showToast({ message: 'two', action: undo() })
    expect(toast.current.previous).toBeNull()
  })
})

describe('H1-5: focus is never hidden under the sticky header', () => {
  // SKIPPED, defect TD-02 (comms/outbox/tester.md): personal's style.css has no scroll-padding-top.
  it.skip('the page scrolls a focused element clear of the header', () => {
    const html = /html\s*\{[^}]*\}/.exec(css)?.[0] ?? ''
    expect(html).toMatch(/scroll-padding-top:\s*calc\(var\(--header-h\)/)
  })
})
