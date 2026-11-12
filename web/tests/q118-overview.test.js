// Q-118 lane LA pins: the redesigned Overview (docs/architecture/q118_ui_polish_design.md §2,
// D-207). Product first: the whole App is mounted at #/overview with the fake API, and the
// page is read as the owner sees it. The old behaviour tests (To do rows, Start a run,
// failures) are in Overview.test.js; the pure rules are in overview.helpers.test.js.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import App from '../src/App.vue'
import SetupChecklist from '../src/components/SetupChecklist.vue'
import { resetSeenJobs } from '../src/composables/useJob.js'
import { resetDismissed } from '../src/dismissed.js'
import { dismissToast } from '../src/toast.js'
import { fakeApi, setHash } from './helpers.js'

let api

const NOW = '2026-09-29T12:00:00Z'

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
const AT = '2026-09-10T08:00:00'

// One of everything. Sent: a1 a2 i1 t1 o1 r1 w1 (7); heard: i1 t1 o1 r1 (4) = 57%.
// Active (not rejected or withdrawn): a1 a2 i1 t1 o1 s1 = 6. Interviews: i1 + the assessment = 2.
const MIXED = () => [
  row('a1', 'applied', [['to_apply', AT], ['applied', AT]]),
  row('a2', 'applied', [['applied', AT]]),
  row('i1', 'interviewing', [['applied', AT], ['interviewing', AT]]),
  row('t1', 'assessment', [['applied', AT], ['assessment', AT]]),
  row('o1', 'offer', [['applied', AT], ['offer', AT]]),
  row('r1', 'rejected', [['applied', AT], ['rejected', AT]]),
  row('w1', 'withdrawn', [['applied', AT], ['withdrawn', AT]]),
  row('s1', 'to_apply', [['to_apply', AT]]),
]

const questionsOf = () => ({ mode: 'dry_run', busy: false, ready: [], groups: [], waiting: [] })

function useApi(options) {
  api = fakeApi({ questions: questionsOf(), ...options })
  vi.stubGlobal('fetch', api.fetch)
  return api
}

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

async function mountOverview() {
  const wrapper = mount(App, { attachTo: document.body })
  await vi.waitFor(() => expect(wrapper.find('.overview').exists()).toBe(true))
  await vi.waitFor(async () => {
    await flushPromises()
    expect(wrapper.find('.overview [role="status"][aria-busy="true"]').exists()).toBe(false)
    expect(api.count(/^api\/shortlist/)).toBeGreaterThan(0)
  })
  await flushPromises()
  return wrapper
}

const kpi = (w, id) => w.find(`[data-kpi="${id}"]`)
const legendItems = w => w.findAll('.ui-progress-legend li')
const pipeCard = w => w.find('[aria-labelledby="pipe-title"]')

describe('Q-118 Overview: the headline numbers', () => {
  it('four cards in order, each with its value, caption and link', async () => {
    useApi({ applicationRows: MIXED() })
    const w = await mountOverview()
    const cards = w.findAll('.overview .ov-kpis [data-kpi]')
    expect(cards.map(c => c.attributes('data-kpi'))).toEqual(['new', 'active', 'interviews', 'reply'])
    const read = id => [
      kpi(w, id).find('.ui-kpi-label').text(), kpi(w, id).find('.ui-kpi-value').text(),
      kpi(w, id).find('.ui-kpi-caption').text(), kpi(w, id).attributes('href'),
    ]
    expect(read('new')).toEqual(['New roles', '5', 'in your Inbox', '#/inbox'])
    expect(read('active')).toEqual(['Active applications', '6', 'Not rejected or withdrawn', '#/applications/active'])
    expect(read('interviews')).toEqual(['Interviews', '2', '1 offer', '#/applications/interviewing'])
    expect(read('reply')).toEqual(['Response rate', '57%', '4 of 7 heard back', undefined])
  })

  it('the Interviews caption counts the offers, and says so when there are none', async () => {
    useApi({ applicationRows: MIXED().filter(r => r.job_id !== 'o1') })
    const none = await mountOverview()
    expect(kpi(none, 'interviews').find('.ui-kpi-caption').text()).toBe('No offers yet')

    useApi({ applicationRows: [...MIXED(), row('o2', 'offer', [['applied', AT], ['offer', AT]])] })
    const two = await mountOverview()
    expect(kpi(two, 'interviews').find('.ui-kpi-caption').text()).toBe('2 offers')
  })

  it('the response rate is a headline number only: no sentence under the pipeline, no link', async () => {
    useApi({ applicationRows: MIXED() })
    const w = await mountOverview()
    expect(kpi(w, 'reply').element.tagName).toBe('DIV')                  // a measure, not a list: not a link
    expect(kpi(w, 'reply').attributes('title')).toBe('An interview, offer or rejection after you applied counts as a reply.')
    // The old line ("57% response rate · 4 of 7 applications heard back") is gone from the page...
    expect(w.find('.response').exists()).toBe(false)
    expect(w.text()).not.toMatch(/response rate\s*·/i)
    expect(w.text()).not.toContain('applications heard back')
    // ...and from the Pipeline card, which now holds the bar and its legend only.
    expect(pipeCard(w).text()).not.toMatch(/response|heard back|%/i)
    // "heard back" is said exactly once on the page: in the KPI caption.
    expect(w.text().match(/heard back/g)).toHaveLength(1)
  })
})

describe('Q-118 Overview: the pipeline', () => {
  it('links exactly the stages of D-207 to the Applications tab; a stage with none is muted, not hidden', async () => {
    useApi({ applicationRows: MIXED().filter(r => r.job_id !== 'o1') })     // no offer
    const w = await mountOverview()
    const items = legendItems(w).map(li => ({
      label: li.find('.ui-progress-label').text(), n: li.find('.ui-progress-n').text(),
      href: li.find('a').attributes('href'), zero: li.classes().includes('is-zero'),
    }))
    expect(items).toEqual([
      { label: 'Applied', n: '2', href: '#/applications/applied', zero: false },
      { label: 'Interviewing', n: '2', href: '#/applications/interviewing', zero: false },
      { label: 'Offer', n: '0', href: '#/applications/offer', zero: true },       // visible, linked, muted
      { label: 'Rejected', n: '2', href: '#/applications/rejected', zero: false },
    ])
    // No Saved / To apply / Assessment / Withdrawn stage anywhere in the legend.
    expect(pipeCard(w).find('.ui-progress-legend').text()).not.toMatch(/saved|to apply|assessment/i)
    expect(legendItems(w).map(li => li.find('a').attributes('aria-label'))).toEqual([
      'Applied, 2', 'Interviewing, 2', 'Offer, 0', 'Rejected, 2 (1 withdrawn)',
    ])
  })

  it('counts a to-apply, an assessment and a withdrawn application where D-207 puts them', async () => {
    useApi({ applicationRows: MIXED() })
    const w = await mountOverview()
    const n = label => Number(legendItems(w).find(li => li.find('.ui-progress-label').text() === label).find('.ui-progress-n').text())
    expect(n('Interviewing')).toBe(2)                                   // interviewing + assessment
    expect(n('Rejected')).toBe(2)                                       // rejected + withdrawn
    expect(legendItems(w)[3].find('.ui-progress-note').text()).toBe('(1 withdrawn)')
    expect(n('Applied')).toBe(2)                                        // the to-apply role is in no stage
    // ...but it is tracked, still active, and not lost: a muted line links to it.
    expect(pipeCard(w).find('.ui-count').text()).toBe('8 tracked')
    expect(pipeCard(w).find('.ov-foot').text()).toContain('1 to apply')
    expect(pipeCard(w).find('.ov-foot a').attributes('href')).toBe('#/applications/active')
    expect(kpi(w, 'active').find('.ui-kpi-value').text()).toBe('6')     // to_apply counts as active, withdrawn does not
  })

  it('the bar has a slice per non-empty stage, and Rejected is set apart in the muted tone', async () => {
    useApi({ applicationRows: MIXED().filter(r => r.job_id !== 'o1') })
    const w = await mountOverview()
    const slices = w.findAll('.ui-progress .ui-progress-seg')
    expect(slices.map(s => s.attributes('data-tone'))).toEqual(['applied', 'interviewing', 'closed'])   // no slice for Offer (0)
    expect(slices.map(s => s.classes().includes('is-apart'))).toEqual([false, false, true])
    expect(w.find('.ui-progress').attributes('aria-hidden')).toBe('true')   // the legend carries every number
  })
})

describe('Q-118 Overview: layout and the set-up checklist', () => {
  it('the four cards and the two columns sit in the 12-column grid, which the stylesheet collapses on a phone', async () => {
    // jsdom evaluates no media query, so the wrapping itself is for the browser check at 390px.
    // What a unit test can hold: the page uses the grid classes, and the shared rules that
    // fold them are still there (3 of 12 -> half width <= 900px, 8 and 4 of 12 -> full width).
    useApi({ applicationRows: MIXED() })
    const w = await mountOverview()
    const kpiRow = w.find('.ov-kpis')
    expect(kpiRow.classes()).toContain('ui-grid')
    expect(kpiRow.findAll(':scope > .span-3')).toHaveLength(4)
    const main = w.find('.ov-col.span-8')
    const side = w.find('.ov-col.span-4')
    expect(main.element.parentElement.classList.contains('ui-grid')).toBe(true)
    expect(side.element.parentElement).toBe(main.element.parentElement)
    expect(main.findAll('section.ui-card h3').map(h => h.text())).toEqual(['To do', 'Pipeline'])
    expect(side.findAll('section.ui-card h3').map(h => h.text())).toEqual(['Last run', 'Past 7 days'])

    const css = readFileSync(resolve(process.cwd(), 'src/style.css'), 'utf8')
    const start = css.indexOf('/* ---- 12-column grid ---- */')
    expect(start).toBeGreaterThan(-1)
    const grid = css.slice(start, css.indexOf('/* ---- rows inside a card', start))
    const narrow = grid.slice(grid.indexOf('@media (max-width: 900px)'))
    expect(narrow).toMatch(/\.ui-grid > \.span-4[\s\S]*\.ui-grid > \.span-8[\s\S]*grid-column: span 12/)
    expect(narrow).toMatch(/\.ui-grid > \.span-3 \{ grid-column: span 6; \}/)
  })

  it('still embeds the set-up checklist with the apply part switched on, and tells it what the shell knows', async () => {
    const w = await mountOverview()
    const checklist = w.findComponent(SetupChecklist)
    expect(checklist.exists()).toBe(true)
    expect(checklist.props('withApply')).toBe(true)
    expect(checklist.props('runsKnown')).toBe(true)
    expect(Array.isArray(checklist.props('runs'))).toBe(true)
    expect(checklist.props('runs').length).toBeGreaterThan(0)

    // The shell could not read the runs: the checklist is told it does not know.
    useApi()
    const inner = api.fetch
    vi.stubGlobal('fetch', vi.fn(async (url, init = {}) => (url === 'api/runs'
      ? { ok: false, status: 500, statusText: 'Internal Server Error', json: async () => ({ detail: 'down' }) }
      : inner(url, init))))
    const w2 = await mountOverview()
    expect(w2.findComponent(SetupChecklist).props('runsKnown')).toBe(false)
    expect(w2.findComponent(SetupChecklist).props('withApply')).toBe(true)
  })
})
