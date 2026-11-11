// Q-100 T1-C pins for first-run setup (design section 4.2, A6, A7) and the audit fixes in
// the lane C files: the two-part checklist and its counts (required steps only), a failed
// check never reads as "0 of N", Upload opens Profile on Resume and titles and a hash view
// beats the remembered one, and Applications row actions (touch targets, Remove asks first).
import { readFileSync } from 'node:fs'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import SetupChecklist, { LATER_KEY } from '../src/components/SetupChecklist.vue'
import Applications from '../src/tabs/Applications.vue'
import Profile from '../src/tabs/Profile.vue'
import { PROFILE_VIEW_KEY } from '../src/profileView.js'
import { applySteps } from '../src/connections.js'
import { countSteps, setupSteps } from '../src/setup.js'
import { dismissToast } from '../src/toast.js'
import sample from './fixtures/connections.sample.json'
import { fakeApi, runsFrom, setHash } from './helpers.js'
import { cloneSample, routeFetch } from './q100Fake.js'

enableAutoUnmount(afterEach)
beforeEach(() => {
  window.localStorage.clear()
  setHash('')
  dismissToast()
})
afterEach(() => {
  vi.unstubAllGlobals()
  setHash('')
  dismissToast()
})

const FRESH = {
  'GET profile': { present: false },
  'GET titles': { titles: [] },
  'GET companies/list': { items: [] },
  'GET companies/health': { total: 0 },
  'GET applicant': { missing: ['profile.phone', 'profile.address.city', 'profile.work_rights'], completeness: { filled: 2, needed: 5 } },
  'GET apply/status': { mode: 'dry_run', missing: [], busy: false },
}
// Local AI connected, mailbox and Gmail not set up (both optional).
const connections = () => {
  const r = cloneSample(sample)
  r.items = r.items
    .filter(i => i.kind !== 'gmail')
    .map(i => (i.id === 'apply-mailbox' ? { ...i, state: 'not_set_up', code: 'none', optional: true } : i))
  return r
}

async function checklist(routes = {}, props = {}) {
  const api = routeFetch({ ...FRESH, 'GET connections': connections(), ...routes })
  const w = mount(SetupChecklist, { props: { runs: [], withApply: true, ...props }, attachTo: document.body })
  await flushPromises()
  return { api, w }
}
const progress = w => w.find('.setup-progress').text()
const step = (w, id) => w.find(`[data-step="${id}"]`)

describe('setup.js: counts over required steps only', () => {
  it('countSteps skips steps whose check failed, and says when none could be checked', () => {
    const steps = setupSteps({ hasResume: true, titleCount: 0, companyCount: 0, runCount: 0, unknown: ['companies'] })
    expect(steps.map(s => s.status)).toEqual(['done', 'todo', 'unknown', 'todo'])
    expect(countSteps(steps)).toEqual({ done: 1, total: 3, allFailed: false })
    const all = setupSteps({ unknown: ['resume', 'titles', 'companies', 'run'] })
    expect(countSteps(all)).toEqual({ done: 0, total: 0, allFailed: true })
  })

  it('the resume and titles steps both open Profile on Resume and titles (A6)', () => {
    const steps = setupSteps()
    expect(steps.find(s => s.id === 'resume').href).toBe('#/profile/resume')
    expect(steps.find(s => s.id === 'titles').href).toBe('#/profile/resume')
  })

  it('applySteps: optional steps are never counted, and unknown ones are not counted either', () => {
    const r = applySteps({ connections: connections(), applicant: { missing: ['x'] } })
    expect(r.steps.map(s => [s.id, s.required])).toEqual([['details', true], ['model', true], ['mailbox', false], ['gmail', false]])
    expect([r.done, r.total]).toEqual([1, 2])          // the model is done, details are not; mailbox and Gmail don't count
    const none = applySteps({ connections: null, applicant: null })
    expect(none.allFailed).toBe(true)
    expect(none.total).toBe(0)
  })
})

describe('SetupChecklist: two parts', () => {
  it('a new install sees both parts, titled "Get set up", with a count for each', async () => {
    const { w } = await checklist()
    expect(w.find('.setup-title').text()).toBe('Get set up')
    expect(progress(w)).toBe('Find jobs 0 of 4 · Apply for me 1 of 2')
    expect(w.find('[data-part="find"] .setup-part-title').text()).toBe('Find jobs')
    expect(w.find('[data-part="apply"] .setup-part-title').text()).toBe('Apply for me')
    expect(w.findAll('[data-part="find"] [data-step]').map(s => s.attributes('data-step'))).toEqual(['resume', 'titles', 'companies', 'run'])
    expect(w.findAll('[data-part="apply"] [data-step]').map(s => s.attributes('data-step'))).toEqual(['details', 'model', 'mailbox', 'gmail'])
  })

  it('optional steps are labelled Optional and never counted', async () => {
    const { w } = await checklist()
    expect(step(w, 'mailbox').find('.setup-optional').text()).toBe('Optional')
    expect(step(w, 'gmail').find('.setup-optional').text()).toBe('Optional')
    expect(step(w, 'details').find('.setup-optional').exists()).toBe(false)
    expect(progress(w)).toContain('Apply for me 1 of 2')
  })

  it('details and Local AI steps say what is left', async () => {
    const { w } = await checklist()
    expect(step(w, 'details').text()).toContain('3 missing')
    expect(step(w, 'details').find('a').attributes('href')).toBe('#/profile/details')
    expect(step(w, 'model').classes()).toContain('done')
  })

  it('the resume step\'s Upload opens Profile on Resume and titles (A6)', async () => {
    const { w } = await checklist()
    const up = step(w, 'resume').find('a.setup-go')
    expect(up.text()).toBe('Upload')
    expect(up.attributes('href')).toBe('#/profile/resume')
    expect(step(w, 'titles').find('a.setup-go').attributes('href')).toBe('#/profile/resume')
  })

  it('counts follow the facts: a resume and titles make Find jobs 2 of 4', async () => {
    const { w } = await checklist({ 'GET profile': { present: true }, 'GET titles': { titles: ['a', 'b'] } })
    expect(progress(w)).toBe('Find jobs 2 of 4 · Apply for me 1 of 2')
    expect(step(w, 'resume').classes()).toContain('done')
  })

  it('"Later" hides Apply for me, is remembered on this PC, and leaves Find jobs alone', async () => {
    const { w } = await checklist()
    await w.find('button.setup-later').trigger('click')
    expect(window.localStorage.getItem(LATER_KEY)).toBe('1')
    expect(LATER_KEY).toBe('setup.apply.later')
    expect(w.find('[data-part="apply"]').exists()).toBe(false)
    expect(w.find('[data-part="find"]').exists()).toBe(true)
    expect(progress(w)).toBe('Find jobs 0 of 4')
    w.unmount()
    const again = await checklist()
    expect(again.w.find('[data-part="apply"]').exists()).toBe(false)
  })

  it('an install with runs and nothing left to do shows no checklist at all', async () => {
    const done = {
      'GET applicant': { missing: [] },
    }
    const { w } = await checklist(done, { runs: runsFrom().slice(0, 1) })
    expect(w.find('.setup').exists()).toBe(false)
  })

  it('an install with runs but details still to do shows only Apply for me', async () => {
    const { w } = await checklist({}, { runs: runsFrom().slice(0, 1) })
    expect(w.find('[data-part="find"]').exists()).toBe(false)
    expect(w.find('[data-part="apply"]').exists()).toBe(true)
    expect(progress(w)).toBe('Apply for me 1 of 2')
  })

  it('without withApply (the empty Inbox) it is part 1 alone, as before', async () => {
    const { w, api } = await checklist({}, { withApply: false })
    expect(w.find('.setup-title').text()).toBe('Get your first matches')
    expect(w.find('[data-part="apply"]').exists()).toBe(false)
    expect(progress(w)).toBe('0 of 4 done')
    expect(api.of('GET', 'connections')).toHaveLength(0)
  })
})

describe('SetupChecklist: a failed check is "couldn\'t check", never "0 of N" (A7)', () => {
  const FAIL = [500, { detail: 'boom' }]
  const ALL_FAIL = Object.fromEntries(Object.keys({ ...FRESH, 'GET connections': 1 }).map(k => [k, FAIL]))

  it('every API failing on an install whose run list is unknown: one line with Try again, no counts', async () => {
    const { w } = await checklist(ALL_FAIL, { runs: [], runsKnown: false })
    expect(w.find('.setup-failed').text()).toContain("Couldn't check your setup just now.")
    expect(w.find('.setup-failed button.setup-retry').text()).toBe('Try again')
    expect(w.text()).not.toMatch(/\b0 of \d/)
    expect(w.find('[data-part]').exists()).toBe(false)
  })

  it('every API failing on an established install (runs exist): no "0 of N" either', async () => {
    const { w } = await checklist(ALL_FAIL, { runs: runsFrom().slice(0, 1), runsKnown: true })
    expect(w.text()).not.toMatch(/\b0 of \d/)
    expect(w.find('[data-part="find"]').exists()).toBe(false)
  })

  it('Try again checks again', async () => {
    let failing = true
    const routes = Object.fromEntries(Object.entries({ ...FRESH, 'GET connections': connections() })
      .map(([k, v]) => [k, () => (failing ? FAIL : v)]))
    const { w } = await checklist(routes, { runsKnown: false })
    expect(w.find('.setup-failed').exists()).toBe(true)
    failing = false
    await w.find('button.setup-retry').trigger('click')
    await flushPromises()
    expect(w.find('.setup-failed').exists()).toBe(false)
  })

  it('one failed step is marked "Couldn\'t check" and left out of the count', async () => {
    const { w } = await checklist({ 'GET profile': FAIL })
    expect(step(w, 'resume').classes()).toContain('unknown')
    expect(step(w, 'resume').text()).toContain("Couldn't check")
    expect(progress(w)).toBe('Find jobs 0 of 3 · Apply for me 1 of 2')
    expect(w.find('.setup-unknown').text()).toContain('Could not check every step just now')
  })

  it('a missing connections route leaves Local AI uncounted: "details" only', async () => {
    const { w } = await checklist({ 'GET connections': [404, {}] })
    expect(step(w, 'model').classes()).toContain('unknown')
    expect(progress(w)).toBe('Find jobs 0 of 4 · Apply for me 0 of 1')
  })
})

describe('Profile: a view in the hash beats the remembered one (A6)', () => {
  async function profile(hash, remembered) {
    setHash(hash)
    if (remembered) window.localStorage.setItem(PROFILE_VIEW_KEY, remembered)
    routeFetch({}, { fallback: fakeApi().fetch })
    const w = mount(Profile, { props: { run: 'all', jobs: [] }, attachTo: document.body })
    await flushPromises()
    return w
  }
  const active = w => w.findAll('[role="tab"]').filter(t => t.attributes('aria-selected') === 'true').map(t => t.attributes('id'))

  it('#/profile/resume opens Resume and titles although Application details was remembered', async () => {
    const w = await profile('#/profile/resume', 'details')
    expect(active(w)).toEqual(['profile-tab-resume'])
  })

  it('#/profile/details opens Application details although Resume was remembered', async () => {
    const w = await profile('#/profile/details', 'resume')
    expect(active(w)).toEqual(['profile-tab-details'])
  })

  it('with no view in the hash, the remembered one is still the fallback', async () => {
    const w = await profile('#/profile', 'details')
    expect(active(w)).toEqual(['profile-tab-details'])
  })
})

describe('Applications row actions (A13)', () => {
  const read = p => readFileSync(new URL(p, import.meta.url), 'utf8')
  let api
  async function tab(statuses = { a1b2c3: 'applied', j1k2l3: 'interviewing' }) {
    api = fakeApi({ statuses })
    vi.stubGlobal('fetch', api.fetch)
    const w = mount(Applications, { props: { run: 12, runs: runsFrom(), jobs: [] }, attachTo: document.body })
    await flushPromises()
    return w
  }
  const row = (w, id) => w.find(`.app-row[data-job="${id}"]`)
  const deletes = () => api.calls.filter(c => c.method === 'DELETE')

  it('the row\'s actions sit in one .row-actions group, Remove last after a rule', async () => {
    const w = await tab()
    const actions = row(w, 'a1b2c3').find('.row-actions')
    expect(actions.exists()).toBe(true)
    const kids = actions.findAll('*').map(e => e.classes())
    const rule = kids.findIndex(c => c.includes('row-actions-rule'))
    const remove = kids.findIndex(c => c.includes('row-remove'))
    expect(rule).toBeGreaterThan(-1)
    expect(remove).toBeGreaterThan(rule)
    expect(kids.at(-1)).toContain('row-remove')
    expect(actions.find('.note-edit').exists() || actions.find('.details-toggle').exists()).toBe(true)
  })

  it('the touch-target hook: --touch-min under 640px for every row action', () => {
    const src = read('../src/tabs/Applications.vue')
    const at = src.lastIndexOf('.row-actions .note-edit')
    const block = src.slice(at, src.indexOf('}', at))
    expect(src.lastIndexOf('@media', at)).toBe(src.lastIndexOf('@media (max-width: 640px)', at))
    for (const sel of ['.note-edit', '.details-toggle', '.row-remove', '.remove-yes', '.remove-keep']) {
      expect(block).toContain(sel)
    }
    expect(block).toMatch(/min-height:\s*var\(--touch-min\)/)
  })

  it('Remove asks first, with the company named; focus goes to Keep; nothing is deleted yet', async () => {
    const w = await tab()
    await row(w, 'a1b2c3').find('.row-remove').trigger('click')
    await flushPromises()
    const ask = row(w, 'a1b2c3').find('.remove-ask')
    expect(ask.attributes('role')).toBe('group')
    expect(ask.find('.remove-q').text()).toMatch(/^Remove .+ from Applications\? Its notes go too\.$/)
    expect(ask.find('.remove-yes').text()).toBe('Remove')
    expect(document.activeElement).toBe(ask.find('.remove-keep').element)
    expect(deletes()).toEqual([])
  })

  it('Keep keeps the row, deletes nothing, and returns focus to Remove', async () => {
    const w = await tab()
    await row(w, 'a1b2c3').find('.row-remove').trigger('click')
    await flushPromises()
    await row(w, 'a1b2c3').find('.remove-keep').trigger('click')
    await flushPromises()
    expect(row(w, 'a1b2c3').find('.remove-ask').exists()).toBe(false)
    expect(document.activeElement).toBe(row(w, 'a1b2c3').find('.row-remove').element)
    expect(deletes()).toEqual([])
    expect(row(w, 'a1b2c3').exists()).toBe(true)
  })

  it('only the asked row asks; confirming deletes that one and the row goes', async () => {
    const w = await tab({ a1b2c3: 'applied', z9y8x7: 'applied' })
    await row(w, 'a1b2c3').find('.row-remove').trigger('click')
    expect(row(w, 'z9y8x7').find('.remove-ask').exists()).toBe(false)
    await row(w, 'a1b2c3').find('.remove-yes').trigger('click')
    await flushPromises()
    expect(deletes().map(c => c.url)).toEqual(['api/applications/a1b2c3'])
    expect(row(w, 'a1b2c3').exists()).toBe(false)
  })
})
