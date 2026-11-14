// Q-123 pins (a, c, d, e): four small UI follow-ups.
//   a  Companies: a waiting list name whose company is already watched is ONE row (the watched
//      one, with a note), counted once; the match is the server's rule (lower-case name or slug).
//   c  The pipeline bar's slices are links (retargeted pins are in q118-overview / q118-ui).
//   d  An unknown status is in the "tracked" total and in no bar segment.
//   e  Inbox: the "N already tracked" link keeps a 44px target on a phone. jsdom evaluates no
//      media query, so what a unit test can hold is the markup the rule targets and the rule's
//      text in the source; the 44px height itself is for the browser check at 390px.
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import App from '../src/App.vue'
import Inbox from '../src/tabs/Inbox.vue'
import ProgressSegments from '../src/ui/ProgressSegments.vue'
import WatchedCompanies from '../src/components/WatchedCompanies.vue'
import { LIST_PENDING_NOTE, countsOf, funnelOf, partition, rows, segmentsOf } from '../src/companyRows.js'
import { PIPELINE_STAGES } from '../src/overview.js'
import { resetSeenJobs } from '../src/composables/useJob.js'
import { resetDismissed } from '../src/dismissed.js'
import { dismissToast } from '../src/toast.js'
import { FIXTURE, fakeApi, healthOf, setHash } from './helpers.js'

enableAutoUnmount(afterEach)

const NOW = Date.parse('2026-11-12T12:00:00Z')
const stampAt = secondsAgo => new Date(NOW - secondsAgo * 1000).toISOString().slice(0, 16).replace('T', ' ')
const ok = (company, extra = {}) => ({ company, state: 'ok', reason: '', open_roles: 5, last_scan: stampAt(86400), job_board: 'greenhouse', ...extra })
const sumOf = counts => Object.values(counts).reduce((a, b) => a + b, 0)

// ---------------------------------------------------------------- (a) Companies: one row

describe('Q-123 a: a waiting list name whose company is already watched is one row', () => {
  it('pending, searching and over_limit each join the watched row, which carries the note; nothing is counted twice', () => {
    for (const status of ['pending', 'searching', 'over_limit']) {
      const health = healthOf([ok('Example Co')])
      const list = { items: [{ position: 1, name: 'Example Co', status }] }
      const out = rows(health, list, 14, NOW)
      expect(out.map(r => r.company), status).toEqual(['Example Co'])
      expect(out[0].key, status).toBe('h:Example Co')                         // the watched row, not the list row
      expect(out[0].bucket, status).toBe('checked')
      expect(out[0].listNote, status).toBe(LIST_PENDING_NOTE)
      const counts = countsOf(partition(health, list, 14, NOW))
      expect(counts.waiting, status).toBe(0)
      expect(sumOf(counts), status).toBe(1)                                   // one company, one bucket
      expect(funnelOf(health, list, counts, true).watched, status).toBe(1)
      expect(segmentsOf(counts, true).some(s => s.id === 'waiting'), status).toBe(false)
    }
  })

  it('the match is the server\'s: the same lower-case name, or the same slug (either side)', () => {
    const lower = rows(healthOf([ok('Example Co')]), { items: [{ position: 1, name: '  example co ', status: 'pending' }] }, 14, NOW)
    expect(lower.map(r => [r.company, r.listNote])).toEqual([['Example Co', LIST_PENDING_NOTE]])
    const slugList = rows(healthOf([ok('example-co')]), { items: [{ position: 1, name: 'Example / Co', status: 'pending' }] }, 14, NOW)
    expect(slugList.map(r => [r.company, r.listNote])).toEqual([['example-co', LIST_PENDING_NOTE]])
    const slugHealth = rows(healthOf([ok('Example / Co')]), { items: [{ position: 1, name: 'example-co', status: 'searching' }] }, 14, NOW)
    expect(slugHealth.map(r => [r.company, r.listNote])).toEqual([['Example / Co', LIST_PENDING_NOTE]])
  })

  it('a waiting name with no watched company is its own row; a different company is not joined', () => {
    const health = healthOf([ok('Example Co')])
    const list = { items: [{ position: 1, name: 'Northwind', status: 'pending' }, { position: 2, name: 'Example Corp', status: 'pending' }] }
    const out = rows(health, list, 14, NOW)
    expect(out.map(r => [r.company, r.bucket, r.listNote])).toEqual([
      ['Example Co', 'checked', ''], ['Northwind', 'waiting', ''], ['Example Corp', 'waiting', ''],
    ])
    expect(countsOf(partition(health, list, 14, NOW)).waiting).toBe(2)
  })

  it('a found or watched list name is still not duplicated, and carries no note (regression)', () => {
    const health = healthOf([ok('Example Co'), ok('Northwind')])
    const list = { items: [{ position: 1, name: 'Example Co', status: 'found' }, { position: 2, name: 'Northwind', status: 'watched' }] }
    const out = rows(health, list, 14, NOW)
    expect(out.map(r => [r.company, r.listNote])).toEqual([['Example Co', ''], ['Northwind', '']])
  })

  it('the table shows the note once, under the badge of the one row', () => {
    const w = mount(WatchedCompanies, {
      props: {
        health: healthOf([ok('Example Co')]),
        list: { items: [{ position: 1, name: 'example co', status: 'pending' }] },
        cycleDays: 14,
      },
    })
    expect(w.findAll('.companies-table tbody tr')).toHaveLength(1)
    expect(w.findAll('.status-note').map(n => n.text())).toEqual([LIST_PENDING_NOTE])
    expect(w.find('.ui-badge').text()).toBe('Checked')
  })
})

// ---------------------------------------------------------------- (c) bar slices

describe('Q-123 c: ProgressSegments without a link keeps the bar hidden', () => {
  it('link mode with no href is plain spans and aria-hidden; a slice with an href is a link, one without is not', () => {
    const plain = mount(ProgressSegments, { props: { label: 'Pipeline', segments: [{ id: 'applied', label: 'Applied', n: 3, tone: 'applied' }] } })
    expect(plain.find('.ui-progress').attributes('aria-hidden')).toBe('true')
    expect(plain.findAll('.ui-progress a')).toHaveLength(0)
    const mixed = mount(ProgressSegments, {
      props: {
        label: 'Pipeline',
        segments: [
          { id: 'applied', label: 'Applied', n: 3, tone: 'applied', href: '#/applications/applied' },
          { id: 'offer', label: 'Offer', n: 2, tone: 'offer' },
        ],
      },
    })
    expect(mixed.find('.ui-progress').attributes('aria-hidden')).toBeUndefined()
    expect(mixed.findAll('.ui-progress-seg').map(s => s.element.tagName)).toEqual(['A', 'SPAN'])
  })
})

// ---------------------------------------------------------------- (c, d) the Overview pipeline

describe('Q-123 c, d: the Overview pipeline bar', () => {
  let api
  const AT = '2026-09-10T08:00:00'
  const row = (job_id, status, events = []) => {
    let from = null
    return {
      job_id, status, company: `Co ${job_id}`, role: `Role ${job_id}`, url: null, run_no: null,
      events: events.map(([to_status, at]) => { const e = { from_status: from, to_status, at }; from = to_status; return e }),
    }
  }

  async function mountOverview(applicationRows) {
    api = fakeApi({ questions: { mode: 'dry_run', busy: false, ready: [], groups: [], waiting: [] }, applicationRows })
    vi.stubGlobal('fetch', api.fetch)
    const w = mount(App, { attachTo: document.body })
    await vi.waitFor(() => expect(w.find('.overview').exists()).toBe(true))
    await vi.waitFor(async () => {
      await flushPromises()
      expect(w.find('.overview [role="status"][aria-busy="true"]').exists()).toBe(false)
      expect(api.count(/^api\/shortlist/)).toBeGreaterThan(0)
    })
    await flushPromises()
    return w
  }

  beforeEach(() => {
    window.localStorage.clear()
    resetSeenJobs()
    resetDismissed()
    dismissToast()
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-09-29T12:00:00Z'))
    setHash('#/overview')
  })
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); dismissToast() })

  it('each slice link goes to #/applications/<stage> and is the same address as its legend link', async () => {
    const w = await mountOverview([
      row('a1', 'applied', [['applied', AT]]),
      row('i1', 'interviewing', [['applied', AT], ['interviewing', AT]]),
      row('o1', 'offer', [['applied', AT], ['offer', AT]]),
      row('r1', 'rejected', [['applied', AT], ['rejected', AT]]),
    ])
    const slices = w.findAll('.ui-progress a.ui-progress-seg')
    const legend = w.findAll('.ui-progress-legend a.ui-progress-item')
    expect(slices.map(s => s.attributes('href'))).toEqual(PIPELINE_STAGES.map(s => `#/applications/${s}`))
    expect(slices.map(s => s.attributes('href'))).toEqual(legend.map(a => a.attributes('href')))
  })

  it('an unknown status is in the tracked total and in no segment, no slice and no "to apply" note', async () => {
    const w = await mountOverview([
      row('a1', 'applied', [['applied', AT]]),
      row('x1', 'screening', [['screening', AT]]),
    ])
    expect(w.find('[aria-labelledby="pipe-title"] .ui-count').text()).toBe('2 tracked')
    expect(w.findAll('.ui-progress .ui-progress-seg')).toHaveLength(1)          // only Applied
    expect(w.findAll('.ui-progress-legend .ui-progress-n').map(n => n.text())).toEqual(['1', '0', '0', '0'])
    expect(w.find('[aria-labelledby="pipe-title"] .ov-foot').exists() ? w.find('[aria-labelledby="pipe-title"] .ov-foot').text() : '').not.toContain('to apply')
  })
})

// ---------------------------------------------------------------- (e) Inbox phone target

describe('Q-123 e: the Inbox "already tracked" link', () => {
  it('is an a.tracked (the class the 640px rule targets) and the rule gives it a 44px target', () => {
    vi.stubGlobal('fetch', fakeApi().fetch)
    const jobs = FIXTURE.jobs.filter(j => j.run_no === 12).map((j, i) => ({ ...j, closed: false, status: i === 0 ? 'applied' : null, notes: null }))
    const w = mount(Inbox, { props: { run: 12, jobs } })
    const link = w.find('a.tracked')
    expect(link.exists()).toBe(true)
    expect(link.attributes('href')).toBe('#/applications')
    expect(link.text()).toBe('1 already tracked')
    // jsdom cannot evaluate @media (max-width: 640px): read the rule from the source instead.
    const src = readFileSync(resolve(process.cwd(), 'src/tabs/Inbox.vue'), 'utf8')
    const block = src.slice(src.indexOf('@media (max-width: 640px)'))
    const rule = block.slice(0, block.indexOf('}', block.indexOf('.tracked')) + 1)
    expect(rule).toMatch(/\.tracked\s*\{[^}]*display:\s*inline-flex[^}]*min-height:\s*var\(--touch-min\)/)
    vi.unstubAllGlobals()
  })
})
