// Q-121 release lock pins (D-223): Settings -> Apply "How forms are answered" while this install has
// NOT released "Always answer" (`always_available` in GET /api/apply/settings, read-only, from the
// config file). Locked: the row says "Stop when unsure", the "Always answer" option is visible but
// disabled (`disabled` + `aria-disabled="true"`) with the sentence beside it, and NOTHING is sent for
// it by any gesture. A payload without the key (an older server) is locked too. No live server: the
// recorded settings shape with dummy values.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import Settings from '../src/tabs/Settings.vue'
import { dismissToast } from '../src/toast.js'
import sample from './fixtures/connections.sample.json'
import { fakeApi, setHash } from './helpers.js'
import { mailView } from './mailFake.js'
import { cloneSample, routeFetch } from './q100Fake.js'

enableAutoUnmount(afterEach)
beforeEach(() => {
  window.localStorage.clear()
  window.sessionStorage.clear()
  setHash('')
  dismissToast()
})
afterEach(() => {
  vi.unstubAllGlobals()
  delete window.matchMedia
})

const SENTENCE = "Always answer isn't available yet: it is still being checked."
const BASE = {
  mode: 'dry_run', writable: true, daily_cap: 5, per_employer_daily_cap: 2, headed: false, captcha_wait_s: 120,
  compose_enabled: false, fill_policy: 'strict', always_trial_runs: 0, fill_policy_effective: 'strict',
  fill_policy_inactive: null, always_trial_used: 0, always_trial_left: 0, always_trial_text: 'Off',
}
const LOCKED = { ...BASE, always_available: false, fill_policy_inactive: SENTENCE }
const OPEN = { ...BASE, always_available: true }
const SUMMARY = { missing: [], completeness: { filled: 2, needed: 2 }, form: null }

function server(settings) {
  return routeFetch({
    'GET connections': cloneSample(sample),
    'GET mail': mailView({ accounts: [] }),
    'GET apply/status': { mode: settings.mode ?? 'dry_run', missing: [], busy: false },
    'GET apply/settings': settings,
    'GET applicant': SUMMARY,
    'PUT apply/settings': body => ({ ...settings, ...body }),
  }, { fallback: fakeApi().fetch })
}
async function page(settings) {
  const api = server(settings)
  setHash('#/settings/apply')
  const w = mount(Settings, { props: { run: 'all', jobs: [] }, attachTo: document.body })
  await flushPromises()
  return { w, api }
}
const rowBtn = (w, id) => w.find(`#setting-${id} .setting-main`)
const puts = api => api.of('PUT', 'apply/settings')
const always = w => w.find('input[name="apply-fill-policy"][value="always"]')
const strict = w => w.find('input[name="apply-fill-policy"][value="strict"]')
const shown = w => w.find('#setting-fill-policy .setting-value').text()

async function openRow(settings) {
  const p = await page(settings)
  await rowBtn(p.w, 'fill-policy').trigger('click')
  await flushPromises()
  return p
}

describe('release lock: always_available is false', () => {
  it('the row shows "Stop when unsure"; "Always answer" is disabled, aria-disabled, with the sentence beside it', async () => {
    const { w } = await openRow(LOCKED)
    expect(shown(w)).toBe('Stop when unsure')
    const a = always(w)
    expect(a.exists()).toBe(true)                                   // visible, not removed
    expect(a.element.disabled).toBe(true)
    expect(a.attributes('disabled')).toBeDefined()
    expect(a.attributes('aria-disabled')).toBe('true')
    const label = a.element.closest('label')
    expect(label.textContent).toContain('Always answer')
    expect(label.textContent).toContain(SENTENCE)                   // the sentence beside the option
    expect(w.find('#apply-fill-locked').text()).toContain(SENTENCE)
    expect(a.attributes('aria-describedby')).toBe('apply-fill-locked')
    expect(strict(w).element.disabled).toBe(false)                  // "Stop when unsure" stays selectable
    expect(strict(w).attributes('aria-disabled')).toBeUndefined()
    expect(strict(w).element.checked).toBe(true)
  })

  it('clicking, pressing Space or Enter, or any change event on "Always answer" sends no request and asks nothing', async () => {
    const { w, api } = await openRow(LOCKED)
    const a = always(w)
    // a real click on the input and on its label (a disabled control does not activate)
    a.element.click()
    a.element.closest('label').click()
    await a.trigger('click')                                        // VTU skips disabled elements: kept for the record
    // keys on the option and on the radiogroup
    for (const key of [' ', 'Enter', 'ArrowDown', 'ArrowUp']) {
      a.element.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true }))
      a.element.dispatchEvent(new KeyboardEvent('keyup', { key, bubbles: true, cancelable: true }))
    }
    w.find('.fill-options').element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }))
    // a forced change event (a script or a browser quirk): the handler itself refuses
    a.element.dispatchEvent(new Event('change', { bubbles: true }))
    await flushPromises()
    // an arrow-key choice followed by Enter (the keyboard commit path) is refused too
    a.element.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true, cancelable: true }))
    a.element.dispatchEvent(new Event('change', { bubbles: true }))
    w.find('.fill-options').element.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }))
    await flushPromises()
    expect(puts(api)).toHaveLength(0)
    expect(api.calls.filter(c => c.method !== 'GET')).toEqual([])    // no request of any other kind either
    expect(w.find('.fill-confirm').exists()).toBe(false)             // no "Answer every field automatically?"
    expect(shown(w)).toBe('Stop when unsure')
    expect(always(w).element.checked).toBe(false)
  })

  it('"Stop when unsure" stays selectable: choosing it when it is the stored value sends nothing', async () => {
    const { w, api } = await openRow(LOCKED)
    await strict(w).setValue(true)
    await flushPromises()
    expect(puts(api)).toHaveLength(0)
    expect(shown(w)).toBe('Stop when unsure')
  })

  it('an old stored "always" shows "Stop when unsure" and no gesture can send "always"', async () => {
    const { w, api } = await openRow({ ...LOCKED, fill_policy: 'always' })
    expect(shown(w)).toBe('Stop when unsure')                       // never "Always answer" while locked
    expect(strict(w).element.checked).toBe(true)
    await strict(w).setValue(true)
    always(w).element.dispatchEvent(new Event('change', { bubbles: true }))
    await flushPromises()
    expect(puts(api).filter(c => c.body.fill_policy === 'always')).toEqual([])
    expect(w.find('.fill-confirm').exists()).toBe(false)
    // KNOWN LIMIT (tester DEFECT D1, low): the strict radio is already checked, so picking it fires no
    // change event (browser and VTU alike) and the stored "always" row is NOT rewritten to strict by
    // this row, contrary to the comment in chooseFill. The server keeps it neutralised while locked.
    expect(puts(api)).toHaveLength(0)
  })

  it.each([
    ['a payload with no always_available key (an older server)', BASE],
    ['null', { ...BASE, always_available: null }],
    ['the string "true"', { ...BASE, always_available: 'true' }],
    ['the number 1', { ...BASE, always_available: 1 }],
  ])('%s is treated as locked', async (_label, settings) => {
    const { w, api } = await openRow(settings)
    expect(shown(w)).toBe('Stop when unsure')
    expect(always(w).element.disabled).toBe(true)
    expect(always(w).attributes('aria-disabled')).toBe('true')
    expect(w.find('#apply-fill-locked').text()).toContain(SENTENCE)
    always(w).element.dispatchEvent(new Event('change', { bubbles: true }))
    await flushPromises()
    expect(puts(api)).toHaveLength(0)
    expect(w.find('.fill-confirm').exists()).toBe(false)
  })

  it('a stale "not in force" sentence from the server never replaces the locked row text', async () => {
    const { w } = await page({ ...LOCKED, fill_policy: 'always', fill_policy_inactive: "Always answer is off for now: the AI model isn't on this computer." })
    expect(shown(w)).toBe('Stop when unsure')
  })
})

describe('release lock: always_available is true', () => {
  it('the option is enabled, shows no lock sentence, and a click asks once, then sends one PUT', async () => {
    const { w, api } = await openRow(OPEN)
    const a = always(w)
    expect(a.element.disabled).toBe(false)
    expect(a.attributes('aria-disabled')).toBeUndefined()
    expect(a.element.closest('label').textContent).not.toContain(SENTENCE)
    expect(w.find('#apply-fill-locked').exists()).toBe(false)
    await a.setValue(true)
    await flushPromises()
    expect(puts(api)).toHaveLength(0)                                // the confirm comes first, as today
    expect(w.find('.fill-confirm .confirm-title').text()).toBe('Answer every field automatically?')
    await w.find('.fill-confirm-yes').trigger('click')
    await flushPromises()
    expect(puts(api).map(c => c.body)).toEqual([{ fill_policy: 'always' }])
    expect(shown(w)).toBe('Always answer')
  })
})
