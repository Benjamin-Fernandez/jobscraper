// Q-120 pins for the auto-apply queue in the web UI (apply_queue_design.md §3.5, §7):
// U1 the Inbox button, JobPill and the Questions retry; U2 the queue panel in Runs and
// "Run after this application"; U3 the state chips, Try again, the 10 s follow and
// Remove on a role in flight (Applications). No live server: recorded shapes only.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import Inbox from '../src/tabs/Inbox.vue'
import Runs from '../src/tabs/Runs.vue'
import Applications from '../src/tabs/Applications.vue'
import JobPill from '../src/components/JobPill.vue'
import ApplyQueuePanel from '../src/components/ApplyQueuePanel.vue'
import { resetDismissed } from '../src/dismissed.js'
import { resetSeenJobs } from '../src/composables/useJob.js'
import { dismissToast, toast } from '../src/toast.js'
import { FIXTURE, fakeApi, runsFrom, setHash } from './helpers.js'

const QUEUE_EVENT = 'jobscraper:apply-queue'

function respond(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: { 200: 'OK', 202: 'Accepted', 204: 'No Content', 404: 'Not Found', 409: 'Conflict', 422: 'Unprocessable Entity' }[status] ?? 'Error',
    json: async () => JSON.parse(JSON.stringify(body ?? {})),
  }
}

// fakeApi plus extra routes: [method, url or RegExp, (url, body) => response]. Every call
// (both layers) is in `calls`.
let calls
let base
function withRoutes(routes, options = {}) {
  base = fakeApi(options)
  calls = []
  const fetch = vi.fn(async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase()
    const body = init.body ? JSON.parse(init.body) : undefined
    calls.push({ url, method, body })
    for (const [m, p, handle] of routes) {
      if (m === method && (typeof p === 'string' ? p === url : p.test(url))) return handle(url, body)
    }
    return base.fetch(url, init)
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}
const callsTo = (method, url) => calls.filter(c => c.method === method && (typeof url === 'string' ? c.url === url : url.test(c.url)))

let heard
const onQueue = () => { heard += 1 }
beforeEach(() => {
  heard = 0
  window.addEventListener(QUEUE_EVENT, onQueue)
  window.localStorage.clear()
  setHash('')
  dismissToast()
  resetDismissed()
  resetSeenJobs()
})
afterEach(() => {
  window.removeEventListener(QUEUE_EVENT, onQueue)
  vi.useRealTimers()
  vi.unstubAllGlobals()
  dismissToast()
  setHash('')
  document.body.innerHTML = ''
})
enableAutoUnmount(afterEach)

// ---------------------------------------------------------------- U1: Inbox

const JOBS = FIXTURE.jobs.filter(j => j.run_no === 12).map(j => ({ ...j, closed: false, status: null, notes: null }))
const STATUS = (over = {}) => ({ mode: 'dry_run', missing: [], busy: false, queue: { waiting: 0, applying: false, paused: null }, ...over })

async function mountInbox({ status = STATUS(), enqueue = () => respond({ queued: [], refused: [] }, 202), queueDelete = () => respond(null, 204) } = {}) {
  withRoutes([
    ['GET', 'api/apply/status', () => respond(typeof status === 'function' ? status() : status)],
    ['POST', 'api/apply', (url, body) => enqueue(body)],
    ['DELETE', /^api\/apply\/queue\//, url => queueDelete(url)],
  ])
  const w = mount(Inbox, { props: { run: 12, jobs: JOBS }, attachTo: document.body })
  await flushPromises()
  return w
}
const card = (w, id) => w.find(`.card[data-job="${id}"]`)
async function pick(w, id) {
  await card(w, id).find('.card-hit').trigger('click')
  await flushPromises()
}
const autoButton = w => w.find('.detail button.auto-apply')

describe('Inbox: Auto-apply adds to the queue (U1)', () => {
  it('stays enabled while a job runs (status.busy); disabled only when details are missing', async () => {
    const w = await mountInbox({ status: STATUS({ busy: true }) })
    await pick(w, JOBS[0].id)
    expect(autoButton(w).attributes('disabled')).toBeUndefined()
    expect(w.text()).not.toContain('Another job is running')
    expect(w.find('.auto-apply-note').text()).toBe('Adds this role to the auto-apply queue. Dry run: the form is filled, never submitted.')
    w.unmount()

    const blocked = await mountInbox({ status: STATUS({ missing: ['personal.phone'] }) })
    await pick(blocked, JOBS[0].id)
    expect(autoButton(blocked).attributes('disabled')).toBeDefined()
    expect(blocked.find('.auto-apply-note').text()).toContain('Finish your application details first')
  })

  it('a click takes the role out of the list and the toast says what the queue did', async () => {
    const answers = [
      id => ({ queued: [{ job_id: id, position: 1 }], started: true, refused: [] }),
      id => ({ queued: [{ job_id: id, position: 2 }], started: false, refused: [] }),
      id => ({ queued: [{ job_id: id, position: 3 }], started: false, paused: true, refused: [] }),
    ]
    const said = []
    let n = 0
    const w = await mountInbox({ enqueue: body => respond(answers[n++](body.job_ids[0]), 202) })
    for (const job of JOBS.slice(0, 3)) {
      await pick(w, job.id)
      await autoButton(w).trigger('click')
      await flushPromises()
      expect(card(w, job.id).exists(), job.id).toBe(false)
      said.push(toast.current?.message)
    }
    expect(callsTo('POST', 'api/apply').map(c => c.body)).toEqual(JOBS.slice(0, 3).map(j => ({ job_ids: [j.id] })))
    expect(said).toEqual([
      'Applying now.',
      'Added to the auto-apply queue: 2nd in line.',
      'Added to the auto-apply queue. The queue is paused; resume it in Runs.',
    ])
    expect(toast.current.link).toEqual({ label: 'See the queue', href: '#/runs' })
    expect(heard).toBeGreaterThanOrEqual(3)
  })

  it('two quick clicks on two roles send two POSTs: no global lock', async () => {
    const held = []
    const w = await mountInbox({ enqueue: body => new Promise(resolve => held.push(() => resolve(respond({ queued: [{ job_id: body.job_ids[0], position: held.length }], refused: [] }, 202)))) })
    await pick(w, JOBS[0].id)
    await autoButton(w).trigger('click')
    await pick(w, JOBS[1].id)
    expect(autoButton(w).attributes('disabled')).toBeUndefined()   // the first is still in flight
    await autoButton(w).trigger('click')
    await flushPromises()
    expect(callsTo('POST', 'api/apply').map(c => c.body.job_ids[0])).toEqual([JOBS[0].id, JOBS[1].id])
    held.forEach(release => release())
    await flushPromises()
    expect(card(w, JOBS[0].id).exists()).toBe(false)
    expect(card(w, JOBS[1].id).exists()).toBe(false)
  })

  it('Undo takes the role out of the queue and puts it back; a 404 says it already started', async () => {
    let deleteStatus = 204
    const w = await mountInbox({
      enqueue: body => respond({ queued: [{ job_id: body.job_ids[0], position: 2 }], refused: [] }, 202),
      queueDelete: () => respond(deleteStatus === 204 ? null : { detail: 'not_waiting' }, deleteStatus),
    })
    const [a, b] = JOBS
    await pick(w, a.id)
    await autoButton(w).trigger('click')
    await flushPromises()
    expect(toast.current.action.label).toBe('Undo')
    await toast.current.action.run()
    await flushPromises()
    expect(callsTo('DELETE', `api/apply/queue/${a.id}`)).toHaveLength(1)
    expect(card(w, a.id).exists()).toBe(true)

    deleteStatus = 404
    await pick(w, b.id)
    await autoButton(w).trigger('click')
    await flushPromises()
    await toast.current.action.run()
    await flushPromises()
    expect(toast.current.message).toBe('It has already started; stop it in Runs.')
    expect(card(w, b.id).exists()).toBe(false)
  })
})

// ---------------------------------------------------------------- U1: JobPill, Questions retry

describe('JobPill and the Questions retry (U1)', () => {
  it('JobPill says how many wait, re-reads every 10 s, and stops when unmounted', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    let waiting = [{ job_id: 'x1' }, { job_id: 'x2' }]
    withRoutes([['GET', 'api/apply/queue', () => respond({ paused: null, now: null, slot: 'apply', run_pending: false, waiting, recent: [] })]])
    const w = mount(JobPill, { props: { job: { id: 7, kind: 'apply', state: 'running', started_at: '2026-11-12T08:00:00' } } })
    await flushPromises()
    expect(w.find('.job-text').text()).toBe('Auto-apply · 2 waiting')
    waiting = []
    await vi.advanceTimersByTimeAsync(10000)
    await flushPromises()
    expect(w.find('.job-text').text()).toBe('Auto-apply running')
    const reads = callsTo('GET', 'api/apply/queue').length
    w.unmount()
    await vi.advanceTimersByTimeAsync(30000)
    expect(callsTo('GET', 'api/apply/queue')).toHaveLength(reads)
  })

  it('a Questions retry on 202 says the queue took them (paused variant)', async () => {
    const READY = [{ job_id: 'j1', attempt_id: 5, company: 'Shopee', title: 'Software Engineer' }, { job_id: 'j2', attempt_id: 6, company: 'Grab', title: 'Data Engineer' }]
    withRoutes([
      ['GET', /^api\/questions\?/, () => respond({ mode: 'dry_run', groups: [], ready: READY, waiting: [], busy: true })],
      ['POST', 'api/questions/retry', () => respond({ queued: [{ job_id: 'j1', position: 1 }, { job_id: 'j2', position: 2 }], paused: true, refused: [] }, 202)],
    ])
    const QuestionsInbox = (await import('../src/components/QuestionsInbox.vue')).default
    const w = mount(QuestionsInbox)
    await flushPromises()
    await w.findAll('button').find(b => b.text().trim().startsWith('Retry 2 applications')).trigger('click')
    await flushPromises()
    expect(toast.current?.message).toBe('Added 2 to the auto-apply queue. The queue is paused; resume it in Runs.')
    expect(heard).toBe(1)
  })
})

// ---------------------------------------------------------------- U2: the queue panel

const view = (over = {}) => ({ paused: null, now: null, slot: 'free', run_pending: false, waiting: [], recent: [], ...over })
const NOW = { attempt_id: 41, job_id: 'a1b2c3', company: 'OKX', role: 'SRE', mode: 'dry_run', state: 'filling', started_at: '2026-11-12T08:00:00', interrupted: false }
const WAITING = [
  { job_id: 'j1k2l3', company: 'Grab', role: 'Data Engineer', mode: 'auto', position: 1, enqueued_at: '2026-11-12T08:01:00', source: 'inbox', note: null },
  { job_id: 'm4n5o6', company: 'Stripe', role: 'Payments Engineer', mode: 'auto', position: 2, enqueued_at: '2026-11-12T08:02:00', source: 'inbox', note: 'the site was busy' },
]
const RECENT = [{ attempt_id: 40, job_id: 'g7h8i9', company: 'Shopee', role: 'Analyst', mode: 'auto', kind: 'sent', text: 'Submitted.', finished_at: '2026-11-12T07:50:00' }]

let queue
function queueRoutes() {
  return [
    ['GET', 'api/apply/queue', () => (queue === 404 ? respond({ detail: 'Not Found' }, 404) : respond(queue))],
    ['POST', 'api/apply/queue/pause', () => { queue = { ...queue, paused: { reason: 'owner', text: 'You paused the queue.', hint: 'Resume it to go on.' } }; return respond(queue) }],
    ['POST', 'api/apply/queue/resume', () => { queue = { ...queue, paused: null }; return respond(queue) }],
    ['POST', 'api/apply/queue/clear', () => { const removed = queue.waiting.length; queue = { ...queue, waiting: [] }; return respond({ removed, queue }) }],
    ['POST', 'api/apply/queue/stop', () => { queue = { ...queue, now: null, paused: { reason: 'stopped', text: 'You stopped an application.', hint: '' } }; return respond(queue) }],
    ['DELETE', /^api\/apply\/queue\//, url => { const id = url.split('/').pop(); queue = { ...queue, waiting: queue.waiting.filter(x => x.job_id !== id) }; return respond(null, 204) }],
  ]
}
async function mountPanel(initial) {
  queue = initial
  withRoutes(queueRoutes())
  const w = mount(ApplyQueuePanel, { attrs: { class: 'runs-queue ui-card' }, attachTo: document.body })
  await flushPromises()
  return w
}

describe('Runs: the auto-apply queue panel (U2)', () => {
  it('a server without the queue (404) shows nothing in Runs and is not asked again', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    queue = 404
    withRoutes(queueRoutes())
    const w = mount(Runs, { props: { runs: runsFrom() } })
    await flushPromises()
    expect(w.find('.runs-top .runs-queue').exists()).toBe(false)
    expect(w.find('.apply-queue').exists()).toBe(false)
    expect(w.find('form.start').exists()).toBe(true)
    await vi.advanceTimersByTimeAsync(60000)
    expect(callsTo('GET', 'api/apply/queue')).toHaveLength(1)
  })

  it('Now applying: the role, its state word, Dry run, and Stop posts that attempt', async () => {
    const w = await mountPanel(view({ now: NOW, slot: 'apply', waiting: WAITING }))
    expect(w.find('#aq-title').text()).toBe('Auto-apply queue')
    const now = w.find('.aq-live[aria-live="polite"] li.aq-now')
    expect(now.find('.aq-name').text()).toBe('OKX · SRE')
    expect(now.text()).toContain('Filling the form')
    expect(now.find('.aq-dry').text()).toBe('Dry run')
    const stop = now.find('button.aq-stop')
    expect(stop.text()).toBe('Stop this application')
    await stop.trigger('click')
    await flushPromises()
    expect(callsTo('POST', 'api/apply/queue/stop').map(c => c.body)).toEqual([{ attempt_id: 41 }])
    expect(w.find('.aq-feedback').text()).toBe('Stopped. The queue is paused.')
    expect(heard).toBe(1)
  })

  it('Up next in order, each Remove named for its role, focus moves on; Recently finished links to Applications', async () => {
    const w = await mountPanel(view({ waiting: WAITING, recent: RECENT }))
    const items = () => w.findAll('ol.aq-next li.aq-item')
    expect(items().map(i => i.find('.aq-name').text())).toEqual(['1. Grab · Data Engineer', '2. Stripe · Payments Engineer'])
    expect(items()[1].find('.aq-back').text()).toBe('Back at the front: the site was busy')
    expect(items().map(i => i.find('.aq-remove').attributes('aria-label')))
      .toEqual(['Remove Grab Data Engineer from the queue', 'Remove Stripe Payments Engineer from the queue'])
    const done = w.find('ul.aq-recent li.aq-done')
    expect(done.find('.aq-name').text()).toBe('Shopee · Analyst')
    expect(done.find('.aq-outcome').attributes('data-tone')).toBe('ok')
    expect(done.find('a.aq-open').attributes('href')).toBe('#/applications/all/g7h8i9')

    await items()[0].find('.aq-remove').trigger('click')
    await flushPromises()
    expect(callsTo('DELETE', 'api/apply/queue/j1k2l3')).toHaveLength(1)
    expect(items().map(i => i.attributes('data-job'))).toEqual(['m4n5o6'])
    const focusAfterFirst = document.activeElement
    const nextRemove = items()[0].find('.aq-remove').element
    await items()[0].find('.aq-remove').trigger('click')
    await flushPromises()
    expect(document.activeElement.id).toBe('aq-next-title')                       // none left: the heading
    // Checked last so the rest still runs: after a removal focus goes to the Remove now at
    // that index (handoff U2, design §8 "focus moving after a removal").
    expect(focusAfterFirst, 'focus after the first removal').toBe(nextRemove)
  })

  it('Pause, the paused banner and Resume; Clear asks in place; switched off has no Resume', async () => {
    const w = await mountPanel(view({ now: NOW, slot: 'apply', waiting: WAITING }))
    expect(w.find('.aq-note').text()).toBe('The application in progress finishes first.')
    await w.find('button.aq-pause').trigger('click')
    await flushPromises()
    const banner = w.find('.notice.warn.aq-paused[role="status"]')
    expect(banner.find('.aq-paused-text').text()).toBe('You paused the queue.')
    expect(banner.find('.aq-paused-hint').text()).toBe('Resume it to go on.')
    expect(banner.find('.aq-paused-count').text()).toBe('2 waiting')

    await banner.find('button.aq-clear').trigger('click')
    await flushPromises()
    expect(w.find('.aq-confirm').text()).toContain('Remove all 2 waiting roles from the queue? They stay in Applications under To apply.')
    expect(document.activeElement).toBe(w.find('button.aq-keep').element)
    expect(callsTo('POST', 'api/apply/queue/clear')).toHaveLength(0)
    await w.find('button.aq-confirm-yes').trigger('click')
    await flushPromises()
    expect(callsTo('POST', 'api/apply/queue/clear')).toHaveLength(1)
    expect(w.find('.aq-feedback').text()).toBe('Removed 2 roles from the queue. They stay in Applications under To apply.')

    await w.find('button.aq-resume').trigger('click')
    await flushPromises()
    expect(callsTo('POST', 'api/apply/queue/resume')).toHaveLength(1)
    expect(w.find('.aq-paused').exists()).toBe(false)
    w.unmount()

    const off = await mountPanel(view({ waiting: WAITING, paused: { reason: 'disabled', text: 'Auto-apply is switched off in this copy.', hint: '' } }))
    expect(off.find('.aq-paused-text').text()).toBe('Auto-apply is switched off in this copy.')
    expect(off.find('button.aq-resume').exists()).toBe(false)
  })

  it('polls every 3 s while active, every 15 s when idle, and not while the tab is hidden', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    await mountPanel(view({ waiting: WAITING }))
    const gets = () => callsTo('GET', 'api/apply/queue').length
    expect(gets()).toBe(1)
    queue = view()                                        // the next answer is idle
    await vi.advanceTimersByTimeAsync(3000)
    await flushPromises()
    expect(gets()).toBe(2)
    await vi.advanceTimersByTimeAsync(14000)
    expect(gets()).toBe(2)
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(gets()).toBe(3)

    const hidden = vi.spyOn(document, 'hidden', 'get').mockReturnValue(true)
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(60000)
    expect(gets()).toBe(3)
    hidden.mockReturnValue(false)
    document.dispatchEvent(new Event('visibilitychange'))
    await flushPromises()
    expect(gets()).toBe(4)                                // visible again: at once
    hidden.mockRestore()
  })

  it('Runs: "Run after this application" while auto-apply holds the slot; a deferred 202 starts no run', async () => {
    queue = view({ now: NOW, slot: 'apply' })
    withRoutes([...queueRoutes(), ['POST', 'api/jobs/run', () => respond({ deferred: true }, 202)]])
    const w = mount(Runs, { props: { runs: runsFrom() } })
    await flushPromises()
    expect(w.find('.runs-top > .runs-queue').exists()).toBe(true)
    expect(w.find('button.start-run').text()).toBe('Run after this application')
    const gets = callsTo('GET', 'api/apply/queue').length
    await w.find('form.start').trigger('submit')
    await flushPromises()
    expect(callsTo('POST', 'api/jobs/run')).toHaveLength(1)
    expect(w.find('.run-deferred').text()).toBe('The search run starts when the current application finishes.')
    expect(w.find('.run-busy').exists()).toBe(false)                  // nothing tracked as a run
    expect(w.text()).not.toContain('A run in progress')
    expect(callsTo('GET', 'api/apply/queue').length).toBeGreaterThan(gets)   // the panel re-read
  })
})

// ---------------------------------------------------------------- U3: Applications rows

const EVENT = { id: 1, from_status: null, to_status: 'to_apply', at: '2026-11-10T08:00:00' }
const appRow = (job_id, over = {}) => ({
  job_id, status: 'to_apply', notes: null, company: 'OKX', role: `Role ${job_id}`, url: `https://example.test/${job_id}`,
  run_no: 12, events: [EVENT], last_attempt: null, attempts: 0, posting: null, ...over,
})
const tried = (kind, extra = {}) => ({ id: 9, mode: 'auto', state: kind === 'running' ? 'signing_in' : 'failed', kind, text: '', hint: '', queued_at: '2026-11-11T01:00:00', ...extra })

async function mountApps(rows, routes = []) {
  withRoutes(routes, { applicationRows: rows })
  const w = mount(Applications, { props: { run: 12, runs: runsFrom(), jobs: [] }, attachTo: document.body })
  await flushPromises()
  return w
}
const appRowEl = (w, id) => w.find(`.app-row[data-job="${id}"]`)
const chipOf = (w, id) => appRowEl(w, id).find('.app-state .app-chip')

describe('Applications: queue states on rows (U3)', () => {
  it('queued, applying and needs-answers chips: text and tone', async () => {
    const w = await mountApps([
      appRow('q1', { queue: { position: 3 }, last_attempt: tried('queued') }),
      appRow('r1', { last_attempt: tried('running') }),
      appRow('n1', { last_attempt: tried('needs_input', { text: 'A required question had no answer.' }) }),
    ])
    expect([chipOf(w, 'q1').text(), chipOf(w, 'q1').attributes('data-tone')]).toEqual(['Queued · 3rd', 'neutral'])
    expect([chipOf(w, 'r1').text(), chipOf(w, 'r1').attributes('data-tone')]).toEqual(['Applying…', 'info'])
    expect(appRowEl(w, 'r1').find('.app-step').text()).toBe('Signing in')
    expect([chipOf(w, 'n1').text(), chipOf(w, 'n1').attributes('data-tone')]).toEqual(['Needs your answers', 'warn'])
    expect(appRowEl(w, 'n1').find('.app-answer').text()).toBe('Answer in Profile')
  })

  it('Try again only on a To apply row that stopped, was cancelled or needs answers, and is not in flight', async () => {
    const w = await mountApps([
      appRow('s1', { last_attempt: tried('stopped', { text: 'The site asked for a CAPTCHA.' }) }),
      appRow('c1', { last_attempt: tried('cancelled') }),
      appRow('n1', { last_attempt: tried('needs_input') }),
      appRow('s2', { status: 'applied', last_attempt: tried('stopped') }),          // moved on: no chip, no retry
      appRow('q1', { queue: { position: 1 }, last_attempt: tried('stopped') }),    // queued again
      appRow('r1', { last_attempt: tried('running') }),
    ])
    const retryable = ['s1', 'c1', 'n1', 's2', 'q1', 'r1'].filter(id => appRowEl(w, id).find('.app-retry').exists())
    expect(retryable).toEqual(['s1', 'c1', 'n1'])
    expect(chipOf(w, 's1').text()).toBe('Stopped: The site asked for a CAPTCHA.')
    expect(appRowEl(w, 's1').find('.app-open').attributes('href')).toBe('https://example.test/s1')
    expect(chipOf(w, 's2').exists()).toBe(false)
  })

  it('Try again posts once, toasts the queue place and tells the others', async () => {
    const w = await mountApps([appRow('s1', { last_attempt: tried('stopped') })],
      [['POST', 'api/apply', (url, body) => respond({ queued: [{ job_id: body.job_ids[0], position: 3 }], started: false, refused: [] }, 202)]])
    const retry = appRowEl(w, 's1').find('.app-retry')
    expect(retry.text()).toBe('Try again')
    await retry.trigger('click')
    await retry.trigger('click')
    await flushPromises()
    expect(callsTo('POST', 'api/apply').map(c => c.body)).toEqual([{ job_ids: ['s1'] }])
    expect(toast.current.message).toBe('Added to the auto-apply queue: 3rd in line.')
    expect(toast.current.link).toEqual({ label: 'See the queue', href: '#/runs' })
    expect(heard).toBe(1)
    expect(chipOf(w, 's1').text()).toBe('Queued · 3rd')
    expect(appRowEl(w, 's1').find('.app-retry').exists()).toBe(false)
  })

  it('follows the queue every 10 s only while a row is queued or applying, and stops on unmount', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const reads = () => callsTo('GET', 'api/applications').length
    const quiet = await mountApps([appRow('s1', { status: 'applied' })])
    const r0 = reads()
    await vi.advanceTimersByTimeAsync(30000)
    expect(reads()).toBe(r0)                                   // nothing in flight: no timer
    quiet.unmount()

    const w = await mountApps([appRow('q1', { queue: { position: 1 }, last_attempt: tried('queued') })])
    const r1 = reads()
    await vi.advanceTimersByTimeAsync(10000)
    await flushPromises()
    expect(reads()).toBe(r1 + 1)
    window.dispatchEvent(new Event(QUEUE_EVENT))               // the event reloads at once
    await flushPromises()
    expect(reads()).toBe(r1 + 2)
    w.unmount()
    await vi.advanceTimersByTimeAsync(30000)
    expect(reads()).toBe(r1 + 2)
  })

  it('Remove on a role being applied to says why; a bare 409 says the same', async () => {
    const MSG = 'JobScraper is applying to this role right now. Stop it in Runs first.'
    const w = await mountApps([appRow('r1', { last_attempt: tried('running') }), appRow('d1', { status: 'applied' })],
      [['DELETE', 'api/applications/d1', () => respond({ detail: 'in_progress' }, 409)]])
    const remove = async id => {
      await appRowEl(w, id).find('.app-more-trigger').trigger('click')
      await appRowEl(w, id).findAll('[role="menuitem"]').find(b => b.text().trim() === 'Remove from Applications').trigger('click')
      await flushPromises()
    }
    await remove('r1')
    expect(toast.current.message).toBe(MSG)
    expect(callsTo('DELETE', /^api\/applications\//)).toHaveLength(0)
    await remove('d1')
    await appRowEl(w, 'd1').find('.remove-yes').trigger('click')
    await flushPromises()
    expect(w.find('[role="alert"] p').text()).toBe(`Could not remove OKX: ${MSG}`)
    expect(appRowEl(w, 'd1').exists()).toBe(true)
  })
})
