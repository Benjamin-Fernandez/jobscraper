// Q-70 lane E: the Overview home page, inside the app shell with the fake API.
// Only Date is faked (vi.setSystemTime), so waits and fetch promises run normally.
// Spec: docs/architecture/ux/overview_design.md §4 and §8.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import App from '../src/App.vue'
import { resetSeenJobs } from '../src/composables/useJob.js'
import { resetDismissed } from '../src/dismissed.js'
import { dismissToast, toast } from '../src/toast.js'
import { FIXTURE, fakeApi, setHash } from './helpers.js'

let api

// The fixture's runs: 12 finished 23 Sep (accepted 3), 11 finished 21 Sep (accepted 2).
const NOW = '2026-09-29T12:00:00Z'
const LATER = '2026-10-09T12:00:00Z'      // run 12 is then 15 days old: stale
const ALL_TRACKED = Object.fromEntries(FIXTURE.jobs.map(j => [j.id, 'applied']))

function row(job_id, status, events = []) {
  let from = null
  return {
    job_id, status, company: `Co ${job_id}`, role: `Role ${job_id}`, url: null, run_no: null,
    events: events.map(([to_status, at]) => {
      const e = { from_status: from, to_status, at }
      from = to_status
      return e
    }),
  }
}

const group = (key, over = {}) => ({ key, title: key, status: 'open', labels: [key], employers: ['Acme'], waiting: 1, ...over })
const questionsOf = (n, waiting = 0) => ({
  mode: 'dry_run', busy: false, ready: [],
  groups: Array.from({ length: n }, (_, i) => group(`q${i}`)),
  waiting: Array.from({ length: waiting }, (_, i) => ({ job_id: `w${i}`, company: 'Acme', title: 'Engineer', open: 1 })),
})

function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
  return api
}

// Wrap the fake API: answer some URLs by hand, pass the rest through.
function intercept(handler) {
  const inner = api.fetch
  vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => (await handler(url, init)) ?? inner(url, init)))
}
const reply = body => ({ ok: true, status: 200, statusText: 'OK', json: async () => JSON.parse(JSON.stringify(body)) })
const failure = (status, statusText, detail = statusText) => ({
  ok: false, status, statusText, json: async () => ({ detail }),
})

beforeEach(() => {
  window.localStorage.clear()
  resetSeenJobs()
  resetDismissed()
  dismissToast()
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date(NOW))
  setHash('#/overview')
  useApi()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  dismissToast()
})
enableAutoUnmount(afterEach)

const loading = wrapper => wrapper.find('.overview [role="status"][aria-busy="true"]')

async function mountOverview() {
  const wrapper = mount(App, { attachTo: document.body })
  await vi.waitFor(() => expect(wrapper.find('.overview').exists()).toBe(true))
  await vi.waitFor(async () => {
    await flushPromises()
    expect(loading(wrapper).exists()).toBe(false)
    expect(api.count(/^api\/shortlist/)).toBeGreaterThan(0)     // the shell's jobs have landed too
  })
  await flushPromises()
  return wrapper
}

const kinds = wrapper => wrapper.findAll('.next-card').map(c => c.attributes('data-kind'))
const card = (wrapper, kind) => wrapper.find(`.next-card[data-kind="${kind}"]`)
const week = wrapper => Object.fromEntries(
  wrapper.findAll('.week-tile').map(t => [t.find('dt').text(), Number(t.find('dd').text())]),
)

describe('Overview: first load and the default route', () => {
  it('shows TabLoading until data settles', async () => {
    let release
    const gate = new Promise(r => { release = r })
    intercept(async url => {
      if (url === 'api/applications') await gate
      return undefined
    })
    const wrapper = mount(App, { attachTo: document.body })
    await vi.waitFor(() => expect(loading(wrapper).exists()).toBe(true))
    expect(wrapper.find('.overview h2.page-title').text()).toBe('Overview')   // the heading is there at once
    expect(wrapper.find('.next-card').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Next up')
    expect(wrapper.text()).not.toContain('Pipeline')

    release()
    await vi.waitFor(() => expect(card(wrapper, 'inbox').exists()).toBe(true))
    expect(loading(wrapper).exists()).toBe(false)
    expect(wrapper.text()).toContain('Pipeline')
  })

  it('fetches its own data on every visit (it is not kept alive)', async () => {
    const wrapper = await mountOverview()
    expect(api.count(/^api\/applications$/)).toBe(1)
    await wrapper.find('[role="tab"][data-tab="runs"]').trigger('click')
    await wrapper.find('[role="tab"][data-tab="overview"]').trigger('click')
    await vi.waitFor(() => expect(api.count(/^api\/applications$/)).toBe(2))
  })

  it('has no badge on its tab', async () => {
    const wrapper = await mountOverview()
    expect(wrapper.find('[role="tab"][data-tab="overview"] .badge').exists()).toBe(false)
  })
})

describe('Overview: Next up', () => {
  it('renders a card per pending item and only one primary CTA', async () => {
    vi.setSystemTime(new Date(LATER))
    useApi({
      questions: questionsOf(2, 3),
      applicationRows: [row('late', 'applied', [['to_apply', '2026-09-19T08:00:00'], ['applied', '2026-09-20T08:00:00']])],
    })
    const wrapper = await mountOverview()

    expect(kinds(wrapper)).toEqual(['questions', 'inbox', 'follow-up', 'run'])
    expect(card(wrapper, 'questions').find('.next-title').text()).toBe('2 questions waiting for your answer')
    expect(card(wrapper, 'questions').find('.next-body').text()).toBe('Auto-apply is paused on 3 applications until you answer.')
    expect(card(wrapper, 'inbox').find('.next-title').text()).toBe('5 new roles to triage')
    expect(card(wrapper, 'inbox').find('a.button').attributes('href')).toBe('#/inbox')
    expect(card(wrapper, 'follow-up').find('.next-title').text()).toBe('1 application to follow up')
    expect(card(wrapper, 'follow-up').find('.follow-list').text()).toContain('Co late · Role late · 19 days')
    expect(card(wrapper, 'follow-up').find('a.button').attributes('href')).toBe('#/applications')
    expect(card(wrapper, 'run').find('.next-title').text()).toBe('Your last run was 15 days ago')

    // One primary action on the whole page, and it is the first card's.
    const primaries = wrapper.findAll('.overview .next-card .primary')
    expect(primaries).toHaveLength(1)
    expect(primaries[0].text()).toBe('Answer questions')
    expect(card(wrapper, 'questions').find('.primary').exists()).toBe(true)
    expect(card(wrapper, 'run').find('button').classes()).toContain('ghost')
  })

  it('the primary CTA moves to whichever card is first', async () => {
    vi.setSystemTime(new Date(LATER))
    const wrapper = await mountOverview()              // no questions (404), no follow-ups
    expect(kinds(wrapper)).toEqual(['inbox', 'run'])
    const primaries = wrapper.findAll('.overview .next-card .primary')
    expect(primaries).toHaveLength(1)
    expect(card(wrapper, 'inbox').find('.primary').text()).toBe('Open Inbox')
    expect(card(wrapper, 'run').find('.primary').exists()).toBe(false)
  })

  it('the follow-up card lists three roles and counts the rest', async () => {
    const stale = at => [['applied', at]]
    useApi({
      statuses: ALL_TRACKED,
      questions: questionsOf(0),
      applicationRows: [
        row('a', 'applied', stale('2026-09-01T08:00:00')), row('b', 'applied', stale('2026-09-02T08:00:00')),
        row('c', 'applied', stale('2026-09-03T08:00:00')), row('d', 'applied', stale('2026-09-04T08:00:00')),
        row('e', 'applied', stale('2026-09-05T08:00:00')),
      ],
    })
    const wrapper = await mountOverview()
    expect(card(wrapper, 'follow-up').find('.next-title').text()).toBe('5 applications to follow up')
    const items = card(wrapper, 'follow-up').findAll('.follow-list li').map(li => li.text())
    expect(items).toEqual(['Co a · Role a · 28 days', 'Co b · Role b · 27 days', 'Co c · Role c · 26 days', 'and 2 more'])
  })

  it('a failed run gets its own red card with a link to Runs, not a Start button', async () => {
    useApi({ fixture: { runs: [], jobs: [] }, questions: questionsOf(0) })
    // (the fake API stamps every run 'ok', so the failed run is served by hand)
    intercept(url => (url === 'api/runs'
      ? reply([{ run_no: 12, status: 'failed', started_at: '2026-09-28T09:00:00', finished_at: '2026-09-28T10:00:00', accepted: 0 }])
      : undefined))
    const wrapper = await mountOverview()
    expect(kinds(wrapper)).toEqual(['run'])
    const run = card(wrapper, 'run')
    expect(run.classes()).toContain('failed')
    expect(run.find('.next-title').text()).toBe('Your last run failed')
    expect(run.find('a.button').attributes('href')).toBe('#/runs')
    expect(run.find('button').exists()).toBe(false)
    expect(run.find('a.button').classes()).toContain('primary')       // first card, so primary
  })

  it('caught up when nothing is pending', async () => {
    useApi({ statuses: ALL_TRACKED, questions: questionsOf(0) })
    const wrapper = await mountOverview()
    expect(kinds(wrapper)).toEqual([])
    expect(wrapper.find('.empty-title').text()).toBe("You're all caught up.")
    expect(wrapper.find('.overview .primary').exists()).toBe(false)
  })

  it('does not claim to be caught up when the questions check failed', async () => {
    useApi({ statuses: ALL_TRACKED })               // /api/questions answers 404
    const wrapper = await mountOverview()
    expect(wrapper.find('.empty-title').exists()).toBe(false)
    const notice = wrapper.find('.notice.warn')
    expect(notice.text()).toContain('Could not check for open questions:')
    expect(notice.text()).not.toContain('..')
    expect(notice.find('button').text()).toBe('Try again')
  })

  it('a run in progress is said so and hides the Start a run card', async () => {
    vi.setSystemTime(new Date(LATER))
    useApi({ job: { id: 4, kind: 'run', state: 'running', started_at: '2026-10-09T11:50:00' } })
    const wrapper = await mountOverview()
    expect(wrapper.find('.run-line').text()).toContain('A run is in progress.')
    expect(wrapper.find('.run-line a').attributes('href')).toBe('#/runs')
    expect(kinds(wrapper)).toEqual(['inbox'])
  })

  it('says when the last run was and how many roles it found', async () => {
    const wrapper = await mountOverview()
    expect(wrapper.find('.run-line').text()).toBe('Last run 5 days ago: 3 new roles.')
  })
})

describe('Overview: the Questions card goes to Application details', () => {
  it('Answer questions stores profile.view=details and opens #/profile', async () => {
    useApi({ questions: questionsOf(1) })
    const wrapper = await mountOverview()
    const button = card(wrapper, 'questions').find('button')
    expect(button.text()).toBe('Answer questions')
    expect(window.localStorage.getItem('profile.view')).toBeNull()

    await button.trigger('click')
    expect(window.localStorage.getItem('profile.view')).toBe('details')
    expect(window.location.hash).toBe('#/profile')

    // And the Profile tab honours it: it opens on Application details.
    window.dispatchEvent(new HashChangeEvent('hashchange'))
    await vi.waitFor(async () => {
      await flushPromises()
      expect(wrapper.find('.profile-tab .view-details.active').exists()).toBe(true)
    })
  })

  it('one question reads in the singular', async () => {
    useApi({ questions: questionsOf(1) })
    const wrapper = await mountOverview()
    expect(card(wrapper, 'questions').find('.next-title').text()).toBe('1 question waiting for your answer')
    expect(card(wrapper, 'questions').find('.next-body').text()).toBe('Answer once; every later form reuses it.')
  })
})

describe('Overview: Start a run', () => {
  const posts = () => api.calls.filter(c => c.method === 'POST' && c.url === 'api/jobs/run')

  async function staleOverview() {
    vi.setSystemTime(new Date(LATER))
    return mountOverview()
  }

  it('posts jobs/run once and shows the toast; the card goes and the shell pill takes over', async () => {
    const wrapper = await staleOverview()
    const start = card(wrapper, 'run').find('button')
    expect(start.text()).toBe('Start a run')

    await start.trigger('click')
    await start.trigger('click')                     // a second click while it starts does nothing
    await vi.waitFor(() => expect(toast.current).not.toBeNull())

    expect(posts()).toHaveLength(1)
    expect(JSON.parse(posts()[0].body)).toEqual({})                    // the saved batch size
    expect(toast.current.message).toBe('Run started. New roles land in the Inbox when it finishes.')
    expect(toast.current.link).toEqual({ label: 'Open Runs', href: '#/runs' })
    await vi.waitFor(() => expect(card(wrapper, 'run').exists()).toBe(false))
    expect(wrapper.find('.masthead .job-pill').text()).toContain('Run running')
    expect(wrapper.find('.run-line').text()).toContain('A run is in progress.')
  })

  it('409 shows the already-running text and keeps the button', async () => {
    const wrapper = await staleOverview()
    intercept((url, init) => (url === 'api/jobs/run' && init.method === 'POST'
      ? failure(409, 'Conflict', 'a job is already running') : undefined))
    await card(wrapper, 'run').find('button').trigger('click')
    await vi.waitFor(() => expect(card(wrapper, 'run').find('.notice.error').exists()).toBe(true))
    expect(card(wrapper, 'run').find('.notice.error').text()).toBe('A job is already running. Follow it on the Runs tab.')
    expect(card(wrapper, 'run').find('.notice.error').attributes('role')).toBe('alert')
    expect(toast.current).toBeNull()
    const again = card(wrapper, 'run').find('button')
    expect(again.text()).toBe('Start a run')
    expect(again.attributes('disabled')).toBeUndefined()
  })

  it('any other failure says it could not start', async () => {
    const wrapper = await staleOverview()
    intercept((url, init) => (url === 'api/jobs/run' && init.method === 'POST'
      ? failure(500, 'Internal Server Error') : undefined))
    await card(wrapper, 'run').find('button').trigger('click')
    await vi.waitFor(() => expect(card(wrapper, 'run').find('.notice.error').exists()).toBe(true))
    expect(card(wrapper, 'run').find('.notice.error').text()).toMatch(/^Could not start the run: .*500/)
  })

  it('shows Starting… and disables the button while the request is out', async () => {
    const wrapper = await staleOverview()
    let release
    const gate = new Promise(r => { release = r })
    intercept(async (url, init) => {
      if (url === 'api/jobs/run' && init.method === 'POST') await gate
      return undefined
    })
    await card(wrapper, 'run').find('button').trigger('click')
    const busy = card(wrapper, 'run').find('button')
    expect(busy.text()).toBe('Starting…')
    expect(busy.attributes('disabled')).toBeDefined()
    release()
    await vi.waitFor(() => expect(card(wrapper, 'run').exists()).toBe(false))
  })
})

describe('Overview: Pipeline and Past 7 days', () => {
  const rows = () => [
    row('p1', 'applied', [['to_apply', '2026-09-26T08:00:00'], ['applied', '2026-09-27T09:00:00']]),
    row('p2', 'interviewing', [['applied', '2026-09-10T08:00:00'], ['interviewing', '2026-09-28T08:00:00']]),
    row('p3', 'rejected', [['applied', '2026-09-12T08:00:00'], ['rejected', '2026-09-15T08:00:00']]),
    row('p4', 'withdrawn', [['to_apply', '2026-09-01T08:00:00'], ['withdrawn', '2026-09-02T08:00:00']]),
    row('p5', 'to_apply', [['to_apply', '2026-09-28T08:00:00']]),
  ]

  it('counts each open stage in order, closed apart, with the response rate', async () => {
    useApi({ applicationRows: rows(), questions: questionsOf(0) })
    const wrapper = await mountOverview()
    const tiles = wrapper.findAll('.stage-tile:not(.closed)')
    expect(tiles.map(t => [t.attributes('data-status'), t.find('.tile-label').text(), t.find('.tile-n').text()])).toEqual([
      ['to_apply', 'Saved', '1'], ['applied', 'Applied', '1'], ['interviewing', 'Interviewing', '1'], ['offer', 'Offer', '0'],
    ])
    const closed = wrapper.find('.stage-tile.closed')
    expect(closed.find('.tile-n').text()).toBe('2')
    expect(closed.attributes('title')).toBe('Rejected 1 · Withdrawn 1')
    expect(closed.find('.visually-hidden').text()).toBe('(rejected 1, withdrawn 1)')
    expect(wrapper.find('.response').text()).toContain('67% response rate · 2 of 3 applications heard back')
    expect(wrapper.find('.pipe-link a').attributes('href')).toBe('#/applications')
  })

  it('past 7 days counts found, saved, applied and other updates', async () => {
    useApi({ applicationRows: rows(), questions: questionsOf(0) })
    const wrapper = await mountOverview()
    // Window starts 22 Sep 12:00: run 12 (3 accepted) is in, run 11 is not.
    expect(week(wrapper)).toEqual({ 'New roles found': 3, Saved: 2, Applied: 1, 'Other updates': 1 })
  })

  it('says so with nothing tracked or no applications sent', async () => {
    useApi({ applicationRows: [], questions: questionsOf(0) })
    const wrapper = await mountOverview()
    expect(wrapper.text()).toContain('Nothing tracked yet. Save a role in the Inbox and it shows up here.')
    expect(wrapper.find('.stage-tiles').exists()).toBe(false)

    useApi({ applicationRows: [row('s', 'to_apply', [['to_apply', '2026-09-28T08:00:00']])], questions: questionsOf(0) })
    const saved = await mountOverview()
    expect(saved.find('.response').text()).toContain('No applications sent yet.')
  })

  it('a quiet week says so', async () => {
    vi.setSystemTime(new Date(LATER))
    useApi({ applicationRows: [], questions: questionsOf(0) })
    const wrapper = await mountOverview()
    expect(wrapper.text()).toContain('A quiet week: nothing found or changed in the past 7 days.')
    expect(wrapper.find('.week-tiles').exists()).toBe(false)
  })
})

describe('Overview: failures stay in their own section', () => {
  it('an applications error keeps Next up and offers Try again', async () => {
    let broken = true
    intercept(url => (broken && url === 'api/applications' ? failure(500, 'Internal Server Error') : undefined))
    const wrapper = await mountOverview()

    expect(card(wrapper, 'inbox').exists()).toBe(true)                 // Next up still works
    const notices = wrapper.findAll('.notice.error')
    expect(notices).toHaveLength(2)                                    // Pipeline and Past 7 days
    for (const n of notices) {
      expect(n.attributes('role')).toBe('alert')
      expect(n.text()).toContain('Could not load your applications:')
      expect(n.find('button').text()).toBe('Try again')
    }
    expect(wrapper.find('.stage-tiles').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Nothing tracked yet')

    broken = false
    await notices[0].find('button').trigger('click')
    await vi.waitFor(() => expect(wrapper.findAll('.notice.error')).toHaveLength(0))
    expect(wrapper.find('.stage-tiles').exists() || wrapper.text().includes('Nothing tracked yet')).toBe(true)
  })

  it('a failed questions check skips only that card', async () => {
    const wrapper = await mountOverview()                              // /api/questions answers 404
    expect(wrapper.find('.notice.warn').text()).toContain('Could not check for open questions:')
    expect(kinds(wrapper)).toEqual(['inbox'])
    expect(wrapper.find('.pipe-link').exists() || wrapper.text().includes('Pipeline')).toBe(true)
  })
})

describe('Overview: before the first run', () => {
  it('no runs shows the setup checklist', async () => {
    useApi({ fixture: { runs: [], jobs: [] }, questions: questionsOf(0) })
    const wrapper = await mountOverview()
    await vi.waitFor(() => expect(wrapper.find('.overview .setup').exists()).toBe(true))
    expect(wrapper.find('.overview .setup-title').text()).toBe('Get set up')
    expect(wrapper.find('.run-line').exists()).toBe(false)
    expect(wrapper.find('.next-card').exists()).toBe(false)
    expect(wrapper.find('.empty-title').exists()).toBe(false)           // not "caught up" before the first run
    expect(wrapper.text()).toContain('Pipeline')                        // the rest of the page still renders
  })

  it('with runs, no setup checklist', async () => {
    const wrapper = await mountOverview()
    expect(wrapper.find('.overview .setup').exists()).toBe(false)
  })
})
