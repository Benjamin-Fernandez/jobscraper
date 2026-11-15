// Q-121 WP-U1 pins (retargeted by Q-127 T0, D-215): the Applications chips, Settings -> Apply "How
// forms are answered" and "Trial applications", and the work-rights warning. The "Answered for you"
// cards (Keep / Change) are RETIRED: what was assumed is shown, and corrected for next time, in
// What was sent (web/tests/q127-what-was-sent.test.js). No live server:
// recorded shapes from the W1 handoff (GET /api/questions?status=assumed, POST .../keep|change,
// GET /api/apply/settings, GET /api/apply/status), dummy data only.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ApplicationDetails from '../src/components/ApplicationDetails.vue'
import ApplicationRow from '../src/components/ApplicationRow.vue'
import Settings from '../src/tabs/Settings.vue'
import { dismissToast, toast } from '../src/toast.js'
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

// RETIRED (Q-127 T0): 'Answered for you' (the group, Keep, Change, refusals): 15 tests of QuestionsInbox cards.
// Their needs live in q127-what-was-sent.test.js (assumed rows, remember, 409 / 422) and tests/test_q127_web.py.

const ETAG = 'aaaaaaaaaaaaaaaa'
const APPLICANT = {
  profile: {}, etag: ETAG, errors: [], missing: [], completeness: { filled: 1, needed: 1 },
  from_resume: [], sensitive: [], form: [], file: { exists: true, has_comments: false, error: '' },
}
const item = () => ({})
function world(items, { routes = {} } = {}) {
  const api = routeFetch({ 'GET applicant': APPLICANT, ...routes })
  return { api }
}

// ---- the Profile page: the badge and the work-rights warning ------------------------------

const SG_GROUP = {
  id: 'singapore_status', title: 'Work status', note: '', sensitive: false,
  items: [{ path: 'singapore_status.authorised_to_work', label: 'Authorised to work', kind: 'country_bool_map', options: [], help: '', sub: [], required: false, recommended: false, sensitive: false }],
}
async function details({ profile = {}, status = { mode: 'dry_run', missing: [], busy: false, fill: { fill_policy_effective: 'always' } }, items = [item()] } = {}) {
  world(items, {
    routes: {
      'GET applicant': { ...APPLICANT, profile, form: [SG_GROUP],
        sections: [{ id: 'all', title: 'All details', paths: ['singapore_status.authorised_to_work'] }] },
      'GET apply/status': typeof status === 'number' ? [status, { detail: 'Not Found' }] : status,
    },
  })
  const w = mount(ApplicationDetails, { attachTo: document.body })
  await flushPromises()
  await flushPromises()
  const row = w.find('#ds-all-button')
  if (row.exists()) { await row.trigger('click'); await flushPromises() }       // open the one section
  return w
}
const note = w => w.find('p.work-rights-note')
const SG = (authorised, nationality = 'Singaporean') => ({ singapore_status: { nationality, authorised_to_work: authorised } })

describe('Profile: the work-rights warning', () => {
  // RETIRED (Q-127 T0): 'the count Profile shows follows the OPEN questions only': the Profile has no question
  // count any more; the badge counts details_needed (q75-shell.test.js).

  it('warns about work rights only when the effective policy is "always", and says what it means', async () => {
    const everywhere = SG({ default: true })
    const w = await details({ profile: everywhere })
    expect(note(w).text()).toContain("Your profile says you may work in every country. Check the 'every other country' answer.")
    expect(note(w).find('button.work-rights-fix').text()).toBe('Check work rights')
    w.unmount()

    const none = await details({ profile: { singapore_status: { nationality: 'Singaporean' } } })
    expect(note(none).text()).toContain('Your profile has no work-rights answers, so right-to-work questions will be answered by assumption.')
    none.unmount()

    // two nationalities, or a "no" default: nothing to warn about
    expect(note(await details({ profile: SG({ default: true }, ['Singaporean', 'Malaysian']) })).exists()).toBe(false)
    expect(note(await details({ profile: SG({ default: false }) })).exists()).toBe(false)
    expect(note(await details({ profile: {} })).exists()).toBe(false)       // no Work status block at all
  })

  it('shows no warning under "strict", with no fill block (an older server) or when the status cannot be read', async () => {
    const profile = SG({ default: true })
    const strict = { mode: 'dry_run', missing: [], busy: false, fill: { fill_policy_effective: 'strict', fill_policy_inactive: 'Always answer is off for now: the AI model isn\'t on this computer.' } }
    expect(note(await details({ profile, status: strict })).exists()).toBe(false)
    expect(note(await details({ profile, status: { mode: 'dry_run', missing: [], busy: false } })).exists()).toBe(false)
    expect(note(await details({ profile, status: 404 })).exists()).toBe(false)
  })
})

// ---- Applications: the chips ---------------------------------------------------------------

const attempt = over => ({
  id: 7, mode: 'auto', state: 'submitted', kind: 'sent', reason_code: null, text: '', hint: '',
  queued_at: '2026-11-12T10:00:00', finished_at: '2026-11-12T10:05:00', submit_clicked_at: '2026-11-12T10:04:00',
  resume_source: null, assumed: 0, assumed_text: '', ...over,
})
const rowOf = (a, status = 'applied') => ({
  job_id: 'j1', company: 'Example Co', role: 'Software Engineer', url: 'https://jobs.example/1', status,
  notes: null, events: [{ id: 1, from_status: null, to_status: status, at: '2026-11-12T10:05:00', by: 'app' }],
  last_attempt: a, attempts: 1, queue: null, posting: null,
})
const chip = w => w.find('.app-chip')
const row = (a, status) => mount(ApplicationRow, { props: { row: rowOf(a, status) }, attachTo: document.body })

describe('Applications: what the chip tells the owner', () => {
  it('a sent application with assumptions says so and offers What was sent; without them nothing is added', async () => {
    const w = row(attempt({ assumed: 3, assumed_text: '3 answers assumed' }))
    expect(chip(w).text()).toBe('Submitted · 3 answers assumed')
    expect(chip(w).attributes('data-kind')).toBe('sent')
    expect(w.find('a.app-review').exists()).toBe(false)               // Q-127: the Review answers link is gone
    expect(w.find('button.app-sent').text()).toBe('See what was sent')
    w.unmount()

    const one = row(attempt({ assumed: 1, assumed_text: '1 answer assumed' }))
    expect(chip(one).text()).toBe('Submitted · 1 answer assumed')
    one.unmount()

    const plain = row(attempt())
    expect(chip(plain).text()).not.toContain('assumed')
    expect(plain.find('a.app-review').exists()).toBe(false)
  })

  it('unconfirmed and dry-run chips carry the count too, and a plain dry run reads as it always did', async () => {
    const unconfirmed = row(attempt({ state: 'submitted_unconfirmed', kind: 'unconfirmed', assumed: 2, assumed_text: '2 answers assumed' }))
    expect(chip(unconfirmed).text()).toBe('Sent, not confirmed · 2 answers assumed')
    unconfirmed.unmount()
    const dry = row(attempt({ state: 'ready_to_submit', kind: 'dry_run', mode: 'dry_run', assumed: 3, assumed_text: '3 answers assumed' }), 'to_apply')
    expect(chip(dry).text()).toBe('Ready to submit · 3 answers assumed')
    expect(dry.find('button.app-sent').text()).toBe('See what was filled')
    dry.unmount()
    const plainDry = row(attempt({ state: 'ready_to_submit', kind: 'dry_run', mode: 'dry_run' }), 'to_apply')
    expect(chip(plainDry).text()).toBe('Dry run ready')
  })

  it('a form that needs a fact only the owner has says which, and a missing document says which', async () => {
    const fact = row(attempt({
      state: 'failed', kind: 'needs_input', reason_code: 'owner_fact_missing', mode: 'dry_run',
      text: "This form asks for your date of birth, which isn't in your profile or resume. Nothing was sent.",
      hint: 'Add it in Profile → Your details, then click Try again.',   // contract v9 wording
    }), 'to_apply')
    expect(chip(fact).text()).toBe('Needs one detail: date of birth')
    expect(fact.find('a.app-add').text()).toBe('Add it')
    fact.unmount()

    const doc = row(attempt({
      state: 'failed', kind: 'stopped', reason_code: 'document_missing', mode: 'dry_run',
      text: 'This form needs a photo, and your profile has none. Nothing was sent.', hint: 'Add it in Profile → Your details → Files, then try again.',   // contract v9 wording
    }), 'to_apply')
    expect(chip(doc).text()).toBe('Needs one file: photo')
    expect(doc.find('a.app-add').text()).toBe('Add it')
    doc.unmount()

    const unsure = row(attempt({ state: 'failed', kind: 'needs_input', reason_code: 'owner_fact_missing', text: 'something else' }), 'to_apply')
    expect(chip(unsure).text()).toBe('Needs one detail')                  // never a made-up fact
  })
})

// ---- Settings -> Apply: "How forms are answered" and "Trial applications" ------------------

const W = {
  mode: 'dry_run', writable: true, daily_cap: 5, per_employer_daily_cap: 2, headed: false, captcha_wait_s: 120,
  compose_enabled: false, fill_policy: 'strict', always_trial_runs: 0, fill_policy_effective: 'strict',
  fill_policy_inactive: null, always_trial_used: 0, always_trial_left: 0, always_trial_text: 'Off',
  always_available: true,      // D-223: these pins are about the released row; the locked row is web/tests/q121-lock.test.js
}
const SUMMARY = { missing: [], completeness: { filled: 2, needed: 2 }, form: null }
function settingsServer(settings, routes = {}) {
  return routeFetch({
    'GET connections': cloneSample(sample),
    'GET mail': mailView({ accounts: [] }),
    'GET apply/status': { mode: settings.mode ?? 'dry_run', missing: [], busy: false },
    'GET apply/settings': settings,
    'GET applicant': SUMMARY,
    'PUT apply/settings': body => ({ ...settings, ...body }),
    ...routes,
  }, { fallback: fakeApi().fetch })
}
async function settingsPage(settings, routes) {
  const api = settingsServer(settings, routes)
  setHash('#/settings/apply')
  const w = mount(Settings, { props: { run: 'all', jobs: [] }, attachTo: document.body })
  await flushPromises()
  return { w, api }
}
const rowBtn = (w, id) => w.find(`#setting-${id} .setting-main`)
const puts = api => api.of('PUT', 'apply/settings')

describe('Settings: how forms are answered', () => {
  it('"Always answer" sends NOTHING until the confirm is accepted; Cancel and Esc leave the value; accepting sends one PUT and tells the shell', async () => {
    const heard = vi.fn()
    window.addEventListener('jobscraper:apply-settings', heard)
    const { w, api } = await settingsPage(W)
    expect(w.find('#setting-fill-policy .setting-value').text()).toBe('Stop when unsure')
    await rowBtn(w, 'fill-policy').trigger('click')
    const always = () => w.find('input[name="apply-fill-policy"][value="always"]')

    await always().setValue(true)
    await flushPromises()
    expect(w.find('.fill-confirm .confirm-title').text()).toBe('Answer every field automatically?')
    expect(w.find('.fill-confirm .fill-confirm-yes').text()).toBe('Switch to always answer')
    expect(puts(api)).toHaveLength(0)
    expect(w.find('#setting-fill-policy .setting-value').text()).toBe('Stop when unsure')   // still the saved choice

    await w.find('.fill-confirm-no').trigger('click')                    // "Keep stopping when unsure"
    await flushPromises()
    expect(puts(api)).toHaveLength(0)
    expect(w.find('.fill-confirm').exists()).toBe(false)
    expect(w.find('#setting-fill-policy .setting-value').text()).toBe('Stop when unsure')

    await always().setValue(true)
    await flushPromises()
    await w.find('.fill-confirm').trigger('keydown', { key: 'Escape' })       // Esc drops the question
    await flushPromises()
    expect(puts(api)).toHaveLength(0)
    expect(w.find('.fill-confirm').exists()).toBe(false)
    expect(w.find('#setting-fill-policy .setting-value').text()).toBe('Stop when unsure')

    await always().setValue(true)
    await flushPromises()
    expect(puts(api)).toHaveLength(0)
    expect(heard).not.toHaveBeenCalled()
    await w.find('.fill-confirm-yes').trigger('click')
    await flushPromises()
    expect(puts(api).map(c => c.body)).toEqual([{ fill_policy: 'always' }])
    expect(w.find('#setting-fill-policy .setting-value').text()).toBe('Always answer')
    expect(heard).toHaveBeenCalledTimes(1)
    window.removeEventListener('jobscraper:apply-settings', heard)
  })

  it('going back to "Stop when unsure" never asks: it saves at once', async () => {
    const { w, api } = await settingsPage({ ...W, fill_policy: 'always', fill_policy_effective: 'always' })
    expect(w.find('#setting-fill-policy .setting-value').text()).toBe('Always answer')
    await rowBtn(w, 'fill-policy').trigger('click')
    await w.find('input[name="apply-fill-policy"][value="strict"]').setValue(true)
    await flushPromises()
    expect(w.find('.fill-confirm').exists()).toBe(false)
    expect(puts(api).map(c => c.body)).toEqual([{ fill_policy: 'strict' }])
  })

  it('the confirm tells the truth about what happens next: automatic submit says it submits, a dry run says it does not', async () => {
    const auto = await settingsPage({ ...W, mode: 'auto' })
    await rowBtn(auto.w, 'fill-policy').trigger('click')
    await auto.w.find('input[name="apply-fill-policy"][value="always"]').setValue(true)
    await flushPromises()
    expect(auto.w.find('.fill-confirm .confirm-body').text()).toContain('submits the form with those answers')
    auto.w.unmount()

    const dry = await settingsPage(W)
    await rowBtn(dry.w, 'fill-policy').trigger('click')
    await dry.w.find('input[name="apply-fill-policy"][value="always"]').setValue(true)
    await flushPromises()
    const text = dry.w.find('.fill-confirm .confirm-body').text()
    expect(text).toContain('Dry run is on')
    expect(text).not.toContain('submits the form')
  })

  it('when "always" is configured but not in force the row says why instead of the value', async () => {
    const why = "Always answer is off for now: the AI model isn't on this computer."
    const { w } = await settingsPage({ ...W, fill_policy: 'always', fill_policy_effective: 'strict', fill_policy_inactive: why })
    const shown = w.find('#setting-fill-policy .setting-value')
    expect(shown.text()).toBe(why)
    expect(shown.text()).not.toBe('Always answer')
    await rowBtn(w, 'fill-policy').trigger('click')
    expect(w.find('.fill-inactive').text()).toBe(`${why} Forms are answered with Stop when unsure until then.`)
  })

  it('a server that lacks the fields (older backend) shows neither row', async () => {
    const { fill_policy, always_trial_runs, fill_policy_effective, fill_policy_inactive, always_trial_used, always_trial_left, always_trial_text, ...older } = W
    const { w } = await settingsPage(older)
    expect(w.find('#setting-fill-policy').exists()).toBe(false)
    expect(w.find('#setting-always-trial').exists()).toBe(false)
    expect(w.find('#setting-daily-cap').exists()).toBe(true)             // the rest of the page is intact
  })
})

describe('Settings: trial applications', () => {
  it('reads the server\'s words, offers Off / 3 / 5 and a 0..20 field, and saves only valid numbers', async () => {
    const { w, api } = await settingsPage({ ...W, fill_policy: 'always', fill_policy_effective: 'always', always_trial_runs: 3, always_trial_left: 2, always_trial_used: 1, always_trial_text: 'Next 3 not sent (2 left)' })
    expect(w.find('#setting-always-trial .setting-value').text()).toBe('Next 3 not sent (2 left)')
    await rowBtn(w, 'always-trial').trigger('click')
    expect(w.findAll('#setting-always-trial-editor .preset').map(b => b.text())).toEqual(['Off', '3', '5'])
    expect(w.find('#setting-always-trial-field').exists()).toBe(true)

    await w.find('#setting-always-trial-field').setValue('21')
    await w.find('#setting-always-trial-field').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(puts(api)).toHaveLength(0)
    expect(w.find('#setting-always-trial .field-error').text()).toMatch(/0.*20|whole number/)
    await w.find('#setting-always-trial-field').setValue('2.5')
    await w.find('#setting-always-trial-field').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(puts(api)).toHaveLength(0)

    const five = w.findAll('#setting-always-trial-editor .preset').find(b => b.text() === '5')
    await five.trigger('click')
    await flushPromises()
    expect(puts(api).map(c => c.body)).toEqual([{ always_trial_runs: 5 }])
  })

  it('says it only applies when forms are answered automatically while the effective policy is "strict"', async () => {
    const { w } = await settingsPage({ ...W, always_trial_runs: 3, always_trial_left: 3, always_trial_text: 'Next 3 not sent' })
    await rowBtn(w, 'always-trial').trigger('click')
    expect(w.find('#setting-always-trial-help').text()).toContain('It only applies when forms are answered automatically.')
    w.unmount()
    const live = await settingsPage({ ...W, fill_policy: 'always', fill_policy_effective: 'always', always_trial_runs: 3, always_trial_left: 3, always_trial_text: 'Next 3 not sent' })
    await rowBtn(live.w, 'always-trial').trigger('click')
    expect(live.w.find('#setting-always-trial-help').text()).not.toContain('only applies')
  })
})
