// Q-76 (N11, N12) pins, vitest side (the Python side is tests/test_q76_attempts.py):
// the auto-apply pill on an Applications row and its "Needs your input" link to
// Profile -> Application details, the Details panel (one row open at a time),
// the attempts list (loading, empty, list, error with Try again), JobDetail (facts,
// why, skills, description with Show more) and the posting cache the Inbox and
// the Applications tab share.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import App from '../src/App.vue'
import Applications from '../src/tabs/Applications.vue'
import JobDetail from '../src/components/JobDetail.vue'
import { attemptLabel, modeLabel, needsInput } from '../src/attempts.js'
import { PROFILE_VIEW_KEY, openProfile } from '../src/profileView.js'
import { clearPostingCache, loadPosting, postingEntry } from '../src/postingCache.js'
import { resetSeenJobs } from '../src/composables/useJob.js'
import { resetDismissed } from '../src/dismissed.js'
import { dismissToast } from '../src/toast.js'
import { fakeApi, pinZone, runsFrom, setHash } from './helpers.js'

pinZone()

let api

function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
  return api
}

// One attempt as attempt_view serves it.
function attempt(kind, extra = {}) {
  return {
    id: 1, mode: 'dry_run', state: 'failed', kind, reason_code: null, text: '', hint: '',
    queued_at: '2026-11-02T01:00:00', finished_at: '2026-11-02T01:05:00', submit_clicked_at: null,
    resume_source: null, ...extra,
  }
}
const NEEDS = attempt('needs_input', {
  reason_code: 'unanswerable_required',
  text: 'A required question had no answer JobScraper could back up: “Why us?”.',
  hint: 'Answer it under Application details.',
})

beforeEach(() => {
  pinZone()
  clearPostingCache()
  resetSeenJobs()
  resetDismissed()
  dismissToast()
  window.localStorage.clear()
  setHash('')
  useApi()
})
afterEach(() => {
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})
enableAutoUnmount(afterEach)

async function mountTab(options = {}) {
  useApi({ statuses: { a1b2c3: 'applied', d4e5f6: 'applied' }, ...options })
  const w = mount(Applications, { props: { run: 12, runs: runsFrom(), jobs: [] }, attachTo: document.body })
  await flushPromises()
  return w
}
const row = (w, id) => w.find(`.app-row[data-job="${id}"]`)
// Q-118 LB: the Details toggle moved into the row's "⋯" menu ("Show details" /
// "Hide details"). `detailsItem` opens the menu and returns that item; `toggle` chooses it.
const moreTrigger = (w, id) => row(w, id).find('.app-more-trigger')
async function detailsItem(w, id) {
  await moreTrigger(w, id).trigger('click')
  await flushPromises()
  return row(w, id).findAll('[role="menuitem"]').find(b => /^(Show|Hide) details$/.test(b.text().trim()))
}
async function detailsLabel(w, id) {
  const label = (await detailsItem(w, id)).text().trim()
  await row(w, id).find('[role="menu"]').trigger('keydown', { key: 'Escape' })
  await flushPromises()
  return label
}
async function toggle(w, id) {
  await (await detailsItem(w, id)).trigger('click')
  await flushPromises()
}
const panels = w => w.findAll('.app-detail')
const attemptCalls = () => api.calls.filter(c => /\/attempts$/.test(c.url))

// ------------------------------------------------------------------ attempts.js

describe('attempts.js wording', () => {
  it('names every kind', () => {
    expect(attemptLabel('running')).toBe('Auto-apply running')
    expect(attemptLabel('sent')).toBe('Sent by auto-apply')
    expect(attemptLabel('unconfirmed')).toBe('Sent, not confirmed')
    expect(attemptLabel('dry_run')).toBe('Dry run ready')
    expect(attemptLabel('needs_input')).toBe('Needs your input')
    expect(attemptLabel('cancelled')).toBe('Auto-apply cancelled')
    expect(attemptLabel('stopped')).toBe('Auto-apply stopped')
  })

  it('a kind from a newer server still gets a label', () => {
    expect(attemptLabel('something_new', 'dry_run')).toBe('Dry run')
    expect(attemptLabel('something_new', 'auto')).toBe('Auto-apply')
  })

  it('mode and needs-input helpers', () => {
    expect(modeLabel('dry_run')).toBe('Dry run')
    expect(modeLabel('auto')).toBe('Real')
    expect(needsInput({ kind: 'needs_input' })).toBe(true)
    expect(needsInput({ kind: 'stopped' })).toBe(false)
    expect(needsInput(null)).toBe(false)
  })
})

// ------------------------------------------------------------------ the pill

// Q-118 LB + Q-120 U3: the row's attempt pill became one chip in the `.app-state` slot
// (`.ui-badge.app-chip[data-kind][data-tone]`), worded by `rowState`. Stopped, cancelled
// and needs-input show only while the role is still To apply (the owner moved on
// otherwise), so these rows are To apply. The attempt LIST under Details keeps
// `.pill.attempt` and `attemptLabel` (below).
describe('the auto-apply chip on a row (N11, Q-120 U3)', () => {
  const KINDS = [
    ['running', 'Applying…', 'info'], ['sent', 'Sent by auto-apply', 'ok'], ['unconfirmed', 'Sent, not confirmed', 'warn'],
    ['dry_run', 'Dry run ready', 'info'], ['cancelled', 'Cancelled', 'neutral'],
    ['stopped', 'Stopped: The site asked for a CAPTCHA.', 'warn'],
  ]
  const TO_APPLY = { a1b2c3: 'to_apply', d4e5f6: 'to_apply' }
  const chip = (w, id) => row(w, id).find('.app-state .app-chip')

  it.each(KINDS)('%s reads "%s" and carries its kind and tone', async (kind, label, tone) => {
    const w = await mountTab({ statuses: TO_APPLY, attempts: { a1b2c3: [attempt(kind, { text: kind === 'stopped' ? 'The site asked for a CAPTCHA.' : '' })] } })
    const c = chip(w, 'a1b2c3')
    expect(c.text()).toBe(label)
    expect(c.attributes('data-kind')).toBe(kind)
    expect(c.attributes('data-tone')).toBe(tone)
    expect(c.element.tagName).toBe('SPAN')
    expect(c.attributes('title')).toBe(kind === 'stopped' ? 'The site asked for a CAPTCHA.' : undefined)
    expect(row(w, 'a1b2c3').find('.pill.attempt').exists()).toBe(false)   // the old pill is gone
  })

  it('no attempt, no chip; only the row with an attempt has one', async () => {
    const w = await mountTab({ statuses: TO_APPLY, attempts: { a1b2c3: [attempt('dry_run')] } })
    expect(chip(w, 'a1b2c3').exists()).toBe(true)
    expect(chip(w, 'd4e5f6').exists()).toBe(false)
    expect(row(w, 'd4e5f6').find('.app-state').text()).toBe('')
  })

  it('the chip shows the newest attempt only', async () => {
    const w = await mountTab({ statuses: TO_APPLY, attempts: { a1b2c3: [attempt('sent', { id: 2 }), attempt('stopped', { id: 1 })] } })
    expect(row(w, 'a1b2c3').findAll('.app-chip')).toHaveLength(1)
    expect(chip(w, 'a1b2c3').text()).toBe('Sent by auto-apply')
  })

  it('"Needs your answers" carries the reason in its title, with an "Answer in Profile" link', async () => {
    const w = await mountTab({ statuses: TO_APPLY, attempts: { a1b2c3: [NEEDS] } })
    const c = chip(w, 'a1b2c3')
    expect(c.text()).toBe('Needs your answers')
    expect(c.attributes('data-tone')).toBe('warn')
    expect(c.attributes('title')).toContain('Why us?')
    const answer = row(w, 'a1b2c3').find('.app-answer')
    expect(answer.element.tagName).toBe('A')
    expect(answer.text()).toBe('Answer in Profile')
    expect(answer.attributes('href')).toBe('#/profile')
  })

  it('"Answer in Profile" remembers Application details and goes to Profile', async () => {
    const w = await mountTab({ statuses: TO_APPLY, attempts: { a1b2c3: [NEEDS] } })
    await row(w, 'a1b2c3').find('.app-answer').trigger('click')
    expect(window.localStorage.getItem(PROFILE_VIEW_KEY)).toBe('details')
    expect(window.location.hash).toBe('#/profile')
  })

  it('end to end in the app: the click lands on the Application details view', async () => {
    useApi({ statuses: { a1b2c3: 'to_apply' }, attempts: { a1b2c3: [NEEDS] } })
    // The owner last looked at Resume and titles.
    window.localStorage.setItem(PROFILE_VIEW_KEY, 'resume')
    setHash('#/applications')
    const w = mount(App, { attachTo: document.body })
    await vi.waitFor(async () => { await flushPromises(); expect(w.find('.app-row .app-answer').exists()).toBe(true) })
    await w.find('.app-row .app-answer').trigger('click')
    await vi.waitFor(async () => {
      await flushPromises()
      expect(window.location.hash).toBe('#/profile')
      expect(w.find('.view-details').exists()).toBe(true)
      expect(w.find('.view-details').attributes('aria-selected')).toBe('true')
      expect(w.find('.view-resume').attributes('aria-selected')).toBe('false')
    })
  })

  it('openProfile() takes a view, defaulting to details', () => {
    openProfile()
    expect(window.localStorage.getItem(PROFILE_VIEW_KEY)).toBe('details')
    openProfile('resume')
    expect(window.localStorage.getItem(PROFILE_VIEW_KEY)).toBe('resume')
  })
})

// ------------------------------------------------------------------ Details

describe('Details opens one row at a time (N12)', () => {
  // Q-118 LB: the toggle is the "⋯" menu's "Show details" item (a menu item carries no
  // aria-expanded/aria-controls); the menu trigger is named for its row, and the panel
  // is a region labelled by the posting's title.
  it('starts closed, with the menu named for its row and the panel labelled by its title', async () => {
    const w = await mountTab()
    expect(panels(w)).toHaveLength(0)
    expect(moreTrigger(w, 'a1b2c3').attributes('aria-label')).toMatch(/^More actions for .+ at OKX$/)
    expect(await detailsLabel(w, 'a1b2c3')).toBe('Show details')
    expect(attemptCalls()).toHaveLength(0)
    await toggle(w, 'a1b2c3')
    const panel = w.find('#app-panel-a1b2c3')
    expect(panel.attributes('role')).toBe('region')
    expect(panel.attributes('aria-labelledby')).toBe('app-detail-a1b2c3')
    expect(panel.find('#app-detail-a1b2c3').exists()).toBe(true)
  })

  it('opening one row closes the other; choosing it again closes it', async () => {
    const w = await mountTab()
    await toggle(w, 'a1b2c3')
    expect(panels(w)).toHaveLength(1)
    expect(await detailsLabel(w, 'a1b2c3')).toBe('Hide details')
    expect(w.find('#app-panel-a1b2c3').attributes('role')).toBe('region')

    await toggle(w, 'd4e5f6')
    expect(panels(w)).toHaveLength(1)
    expect(row(w, 'd4e5f6').find('.app-detail').exists()).toBe(true)
    expect(await detailsLabel(w, 'a1b2c3')).toBe('Show details')
    expect(await detailsLabel(w, 'd4e5f6')).toBe('Hide details')

    await toggle(w, 'd4e5f6')
    expect(panels(w)).toHaveLength(0)
    expect(await detailsLabel(w, 'd4e5f6')).toBe('Show details')
  })

  it('opening asks for that row\'s attempts, once', async () => {
    const w = await mountTab()
    await toggle(w, 'a1b2c3')
    expect(attemptCalls().map(c => c.url)).toEqual(['api/applications/a1b2c3/attempts'])
  })

  it('a row left off the shortlist still opens (no posting facts, no crash)', async () => {
    const w = await mountTab({ statuses: { gone99: 'applied' } })
    await toggle(w, 'gone99')
    const panel = w.find('.app-detail')
    expect(panel.exists()).toBe(true)
    expect(panel.find('.why .reason').exists()).toBe(false)
    expect(panel.find('.attempts').exists()).toBe(true)
  })
})

// ------------------------------------------------------------------ attempts list

describe('the attempts list (N11)', () => {
  const open = (w, id = 'a1b2c3') => toggle(w, id)

  it('says Loading while the request is out', async () => {
    useApi({ statuses: { a1b2c3: 'applied' } })
    const real = api.fetch
    let release
    vi.stubGlobal('fetch', vi.fn((url, init) => (/\/attempts$/.test(url)
      ? new Promise(resolve => { release = () => resolve(real(url, init)) })
      : real(url, init))))
    const w = mount(Applications, { props: { run: 12, runs: runsFrom(), jobs: [] }, attachTo: document.body })
    await flushPromises()
    await toggle(w, 'a1b2c3')
    expect(w.find('.attempts-status').text()).toBe('Loading…')
    release()
    await flushPromises()
    expect(w.find('.attempts-status').text()).toBe('No auto-apply attempts for this role.')
  })

  it('says so when there are none', async () => {
    const w = await mountTab()
    await open(w)
    expect(w.find('.attempts-status').text()).toBe('No auto-apply attempts for this role.')
    expect(w.find('.attempt-list').exists()).toBe(false)
  })

  it('lists them newest first, with time, mode, pill, text and hint', async () => {
    const w = await mountTab({
      attempts: {
        a1b2c3: [
          attempt('stopped', { id: 3, mode: 'auto', queued_at: '2026-11-03T01:00:00', text: 'The site asked for a CAPTCHA. Nothing was sent.', hint: 'Open the posting and apply by hand.' }),
          attempt('dry_run', { id: 2, mode: 'dry_run', queued_at: '2026-11-02T01:00:00', text: 'Stopped before Submit.', hint: '' }),
          attempt('sent', { id: 1, mode: 'auto', queued_at: '2026-11-01T01:00:00' }),
        ],
      },
    })
    await open(w)
    const items = w.findAll('.attempt-item')
    expect(items.map(i => i.attributes('data-kind'))).toEqual(['stopped', 'dry_run', 'sent'])
    expect(items[0].find('.attempt-mode').text()).toBe('Real')
    expect(items[1].find('.attempt-mode').text()).toBe('Dry run')
    expect(items[0].find('.pill.attempt').text()).toBe('Auto-apply stopped')
    expect(items[0].find('.attempt-text').text()).toBe('The site asked for a CAPTCHA. Nothing was sent.')
    expect(items[0].find('.attempt-hint').text()).toBe('Open the posting and apply by hand.')
    expect(items[1].find('.attempt-hint').exists()).toBe(false)      // empty hint: no empty paragraph
    expect(items[2].find('.attempt-text').exists()).toBe(false)
    // Local time (pinned UTC+8), exact UTC original on hover.
    expect(items[0].find('.at').text()).toBe('3 Nov 09:00')
    expect(items[0].find('.at').attributes('title')).toBe('2026-11-03 01:00 UTC')
  })

  it('a needs-input attempt offers the way to answer, which opens Application details', async () => {
    const w = await mountTab({ attempts: { a1b2c3: [NEEDS] } })
    await open(w)
    const answer = w.find('.attempt-answer')
    expect(answer.text()).toBe('Answer in Application details')
    await answer.trigger('click')
    expect(window.localStorage.getItem(PROFILE_VIEW_KEY)).toBe('details')
    expect(window.location.hash).toBe('#/profile')
    // Other kinds do not.
    const w2 = await mountTab({ attempts: { a1b2c3: [attempt('stopped')] } })
    await open(w2)
    expect(w2.find('.attempt-answer').exists()).toBe(false)
  })

  it('a failed load says why, and Try again asks again', async () => {
    const failing = ['a1b2c3']
    const w = await mountTab({ attemptsFail: failing, attempts: { a1b2c3: [attempt('sent')] } })
    await open(w)
    const err = w.find('.attempts-error')
    expect(err.attributes('role')).toBe('alert')
    expect(err.text()).toContain("Couldn't load the attempts")
    expect(attemptCalls()).toHaveLength(1)
    failing.length = 0                                  // the server is back
    await err.find('button').trigger('click')
    await flushPromises()
    expect(attemptCalls()).toHaveLength(2)
    expect(w.find('.attempts-error').exists()).toBe(false)
    expect(w.findAll('.attempt-item')).toHaveLength(1)
  })
})

// ------------------------------------------------------------------ JobDetail

describe('JobDetail (N12)', () => {
  const LONG = Array.from({ length: 40 }, (_, i) => `Paragraph ${i} about the role and the team and what you will be doing here every day.`).join('\n\n')
  const mountDetail = async (job, props = {}) => {
    const w = mount(JobDetail, { props: { job, ...props }, attachTo: document.body })
    await flushPromises()
    return w
  }
  const JOB = {
    id: 'a1b2c3', title: 'Platform Engineer', company: 'Acme', location: 'Singapore, Singapore', yoe_min: 0,
    decided_at: '2026-09-23T14:29:41', closed: false, reason: 'K8s and CI/CD match', matched_skills: ['kubernetes', 'terraform'],
  }

  it('shows head, facts, why, skills and the description', async () => {
    useApi({ postings: { a1b2c3: 'About the role\nYou will build things.\n\nWhat you will do\n- Ship\n- Run' } })
    const w = await mountDetail(JOB)
    expect(w.find('.detail-title').text()).toBe('Platform Engineer')
    expect(w.find('.detail-company').text()).toBe('Acme')
    expect(w.find('.facts').text()).toContain('Singapore')
    expect(w.find('.facts').text()).not.toContain('Singapore, Singapore')
    expect(w.find('.facts').text()).toContain('No experience required')
    expect(w.find('.facts').text()).toContain('Found 23 Sep')
    expect(w.find('.reason').text()).toBe('K8s and CI/CD match')
    expect(w.findAll('.skills li').map(l => l.text())).toEqual(['kubernetes', 'terraform'])
    expect(w.find('.jd-text').text()).toContain('You will build things.')
    expect(w.findAll('.jd-list li').map(l => l.text())).toEqual(['Ship', 'Run'])
    expect(w.find('.jd-more').exists()).toBe(false)
    expect(w.find('.stale-note').exists()).toBe(false)
  })

  it('leaves out what a role that left the shortlist does not have', async () => {
    const w = await mountDetail({ id: 'gone1', title: 'Old role', company: 'Old Co', closed: false })
    expect(w.find('.facts li').exists()).toBe(false)
    expect(w.find('.reason').exists()).toBe(false)
    expect(w.find('.skills').exists()).toBe(false)
    expect(w.find('.jd-status').text()).toContain('Could not load the description')   // 404 from the server
  })

  it('a closed posting says so', async () => {
    const w = await mountDetail({ ...JOB, closed: true })
    expect(w.find('.stale-note').text()).toContain('taken down')
  })

  it('a posting with no description says to read it on the site', async () => {
    useApi({ postings: { a1b2c3: '' } })
    const w = await mountDetail(JOB)
    expect(w.find('.jd-status').text()).toContain('gave no description')
  })

  it('a long description is cut, Show more opens it all, Show less cuts it again', async () => {
    useApi({ postings: { a1b2c3: LONG } })
    const w = await mountDetail(JOB)
    const cut = w.findAll('.jd-p').length
    expect(cut).toBeGreaterThan(0)
    expect(cut).toBeLessThan(40)
    expect(w.find('.jd-more').text()).toBe('Show more')
    await w.find('.jd-more').trigger('click')
    expect(w.findAll('.jd-p')).toHaveLength(40)
    expect(w.find('.jd-more').text()).toBe('Show less')
    await w.find('.jd-more').trigger('click')
    expect(w.findAll('.jd-p')).toHaveLength(cut)
  })

  it('switching to another job collapses the description again', async () => {
    useApi({ postings: { a1b2c3: LONG, d4e5f6: LONG } })
    const w = await mountDetail(JOB)
    await w.find('.jd-more').trigger('click')
    expect(w.find('.jd-more').text()).toBe('Show less')
    await w.setProps({ job: { ...JOB, id: 'd4e5f6' } })
    await flushPromises()
    expect(w.find('.jd-more').text()).toBe('Show more')
  })

  it('has slots for the Inbox\'s actions and the Applications attempts', async () => {
    const w = mount(JobDetail, {
      props: { job: JOB },
      slots: { actions: '<div class="the-actions">A</div>', extra: '<div class="the-extra">E</div>' },
      attachTo: document.body,
    })
    await flushPromises()
    const html = w.html()
    expect(html.indexOf('the-actions')).toBeLessThan(html.indexOf('Why it matches'))
    expect(html.indexOf('the-extra')).toBeGreaterThan(html.indexOf('About the job'))
  })

  it('the title id is the caller\'s, so a region can be labelled by it', async () => {
    const w = await mountDetail(JOB, { titleId: 'my-title' })
    expect(w.find('#my-title').text()).toBe('Platform Engineer')
  })
})

// ------------------------------------------------------------------ the shared cache

describe('the shared posting cache (N12)', () => {
  const postingCalls = id => api.calls.filter(c => c.url === `api/postings/${id}`)

  it('one fetch per role, however many ask', async () => {
    const a = loadPosting('a1b2c3')
    const b = loadPosting('a1b2c3')
    await Promise.all([a, b])
    expect(postingCalls('a1b2c3')).toHaveLength(1)
    expect(postingEntry('a1b2c3').state).toBe('ok')
    expect(postingEntry('a1b2c3').text).toContain('OKX')
    expect(postingEntry('nobody')).toBeNull()
    expect(postingEntry(null)).toBeNull()
  })

  it('two details of the same role (an Inbox pane and an Applications row) share one fetch', async () => {
    const job = { id: 'a1b2c3', title: 'T', company: 'OKX' }
    const one = mount(JobDetail, { props: { job }, attachTo: document.body })
    const two = mount(JobDetail, { props: { job }, attachTo: document.body })
    await flushPromises()
    expect(postingCalls('a1b2c3')).toHaveLength(1)
    expect(one.find('.jd-text').text()).toContain('OKX')
    expect(two.find('.jd-text').text()).toContain('OKX')
  })

  it('a failed fetch is kept, so a dead posting is not asked for on every selection', async () => {
    await loadPosting('nobody')
    await loadPosting('nobody')
    expect(postingCalls('nobody')).toHaveLength(1)
    expect(postingEntry('nobody').state).toBe('error')
  })

  it('clearPostingCache() forgets everything, and a fetch that lands afterwards is dropped', async () => {
    useApi()
    const real = api.fetch
    let release
    vi.stubGlobal('fetch', vi.fn((url, init) => (url === 'api/postings/a1b2c3'
      ? new Promise(resolve => { release = () => resolve(real(url, init)) })
      : real(url, init))))
    const pending = loadPosting('a1b2c3')
    expect(postingEntry('a1b2c3').state).toBe('loading')
    clearPostingCache()
    expect(postingEntry('a1b2c3')).toBeNull()
    release()
    await pending
    expect(postingEntry('a1b2c3')).toBeNull()          // the late answer did not repopulate it
  })

  it('the cache is dropped when the last detail goes, and kept while one is still up', async () => {
    const job = { id: 'a1b2c3', title: 'T', company: 'OKX' }
    const one = mount(JobDetail, { props: { job }, attachTo: document.body })
    const two = mount(JobDetail, { props: { job }, attachTo: document.body })
    await flushPromises()
    one.unmount()
    await flushPromises()
    expect(postingEntry('a1b2c3')).not.toBeNull()
    two.unmount()
    await flushPromises()
    expect(postingEntry('a1b2c3')).toBeNull()
  })

  it('in the app, the Inbox\'s open role is not fetched again by a second look at it', async () => {
    useApi()
    setHash('#/inbox')
    const w = mount(App, { attachTo: document.body })
    await vi.waitFor(async () => { await flushPromises(); expect(w.find('.inbox .card').exists()).toBe(true) })
    await vi.waitFor(async () => { await flushPromises(); expect(w.find('.jd-text').exists()).toBe(true) })
    const first = api.calls.filter(c => /^api\/postings\//.test(c.url))
    expect(first).toHaveLength(1)
    // Leave and return: the tab is kept alive, its detail and cache with it.
    window.location.hash = '#/runs'
    await vi.waitFor(async () => { await flushPromises(); expect(w.find('#panel-runs').exists()).toBe(true) })
    window.location.hash = '#/inbox'
    await vi.waitFor(async () => { await flushPromises(); expect(w.find('.jd-text').exists()).toBe(true) })
    expect(api.calls.filter(c => /^api\/postings\//.test(c.url))).toHaveLength(1)
  })
})
