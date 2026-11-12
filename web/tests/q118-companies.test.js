// Q-118 LD pins (design section 5): the Companies row model (companyRows.js, pure) and the
// one table that replaced the two views, the three tiles, the source select and the A-Z strip.
// The retargets of the older Companies tests are in m16 / m17 / q75-pages / ui / ux1.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import Companies from '../src/tabs/Companies.vue'
import WatchedCompanies from '../src/components/WatchedCompanies.vue'
import {
  bucketOf, comparator, countsOf, funnelOf, nextSort, partition, rows, segmentsOf, sorted,
} from '../src/companyRows.js'
import { resetSeenJobs } from '../src/composables/useJob.js'
import { companyRows, fakeApi, healthOf, legendItem, legendOf, utcStamp } from './helpers.js'

enableAutoUnmount(afterEach)

const NOW = Date.parse('2026-11-12T12:00:00Z')
const stampAt = secondsAgo => new Date(NOW - secondsAgo * 1000).toISOString().slice(0, 16).replace('T', ' ')
const DAY = 86400
const ok = (company, extra = {}) => ({ company, state: 'ok', reason: '', open_roles: 5, last_scan: stampAt(DAY), job_board: 'greenhouse', ...extra })

// ---------------------------------------------------------------- companyRows.js (pure)

describe('companyRows: which stage a company is in', () => {
  it('"checked this cycle" is inclusive at exactly cycle_days; a minute older is due', () => {
    expect(bucketOf(ok('A', { last_scan: stampAt(14 * DAY) }), 14, NOW)).toBe('checked')
    expect(bucketOf(ok('A', { last_scan: stampAt(14 * DAY + 60) }), 14, NOW)).toBe('due')
    expect(bucketOf(ok('A', { last_scan: '' }), 14, NOW)).toBe('due')           // read, but no time to count
    expect(bucketOf({ company: 'F', state: 'failed' }, 14, NOW)).toBe('failed')
    expect(bucketOf({ company: 'N', state: 'not_scanned' }, 14, NOW)).toBe('never')
  })

  it('without a usable cycle_days, "readable" replaces checked and due', () => {
    for (const unknown of [null, 0, undefined, 'x']) {
      expect(bucketOf(ok('A'), unknown, NOW), String(unknown)).toBe('readable')
    }
    const health = healthOf([ok('A'), ok('B', { last_scan: stampAt(40 * DAY) }), { company: 'F', state: 'failed' }])
    const counts = countsOf(partition(health, null, null, NOW))
    expect(counts).toMatchObject({ readable: 2, checked: 0, due: 0, failed: 1 })
    expect(funnelOf(health, null, counts, false)).toEqual({ list: 0, watched: 3, readable: 2, checked: null })
    expect(segmentsOf(counts, false).map(s => s.label)).toEqual(['Readable', 'Failed', 'No job board found'])
  })

  it('a list name that is also watched is one row, not two', () => {
    const health = healthOf([ok('Grab'), ok('OKX')])
    const list = { items: [
      { position: 1, name: 'Grab', status: 'found' }, { position: 2, name: 'OKX', status: 'watched' },
      { position: 3, name: 'Ghost', status: 'failed', detail: 'no careers site found' },
      { position: 4, name: 'Visa', status: 'pending' }, { position: 5, name: 'Slow', status: 'searching' },
      { position: 6, name: 'Cap', status: 'over_limit' },
    ] }
    expect(rows(health, list, 14, NOW).map(r => r.company)).toEqual(['Grab', 'OKX', 'Ghost', 'Visa', 'Slow', 'Cap'])
    const counts = countsOf(partition(health, list, 14, NOW))
    expect(counts).toMatchObject({ checked: 2, not_found: 1, waiting: 3 })
    expect(Object.values(counts).reduce((a, b) => a + b, 0)).toBe(6)           // every row in exactly one bucket
  })

  it('funnel numbers, and a legend that hides Never checked and Waiting at zero', () => {
    const health = healthOf([
      ok('A'), ok('B'), ok('C'), ok('D', { last_scan: stampAt(30 * DAY) }), ok('E', { last_scan: stampAt(30 * DAY) }),
      { company: 'F', state: 'failed' }, { company: 'G', state: 'not_scanned' },
    ])
    const list = { items: Array.from({ length: 10 }, (_, i) => ({ position: i + 1, name: `L${i}`, status: i < 7 ? 'found' : 'failed' })) }
    const counts = countsOf(partition(health, list, 14, NOW))
    expect(funnelOf(health, list, counts, true)).toEqual({ list: 10, watched: 7, readable: 5, checked: 3 })
    expect(funnelOf(health, null, counts, true).list).toBe(0)                  // no list: the sentence starts at "watched"
    expect(segmentsOf(counts, true).map(s => [s.label, s.n])).toEqual([
      ['Checked this cycle', 3], ['Due for a check', 2], ['Failed', 1], ['Never checked', 1], ['No job board found', 3],
    ])
    const quiet = countsOf(partition(healthOf([ok('A')]), null, 14, NOW))
    expect(segmentsOf(quiet, true).map(s => s.label)).toEqual(['Checked this cycle', 'Due for a check', 'Failed', 'No job board found'])
  })

  it('sorting: names A-Z ignoring case, roles biggest first, unknown last in both directions, ties by name', () => {
    const r = (company, openRoles, checkedMs = null) => ({ company, openRoles, checkedMs })
    const list = [r('beta', 5), r('Alpha', null), r('delta', 90), r('Charlie', 5), r('echo', null)]
    const names = (sort) => sorted(list, sort).map(x => x.company)
    expect(names({ key: 'company', dir: 'asc' })).toEqual(['Alpha', 'beta', 'Charlie', 'delta', 'echo'])
    expect(names({ key: 'company', dir: 'desc' })).toEqual(['echo', 'delta', 'Charlie', 'beta', 'Alpha'])
    expect(names({ key: 'roles', dir: 'desc' })).toEqual(['delta', 'beta', 'Charlie', 'Alpha', 'echo'])
    expect(names({ key: 'roles', dir: 'asc' })).toEqual(['beta', 'Charlie', 'delta', 'Alpha', 'echo'])
    const byTime = [r('old', 1, 100), r('new', 1, 900), r('never', 1, null)]
    expect(sorted(byTime, { key: 'checked', dir: 'desc' }).map(x => x.company)).toEqual(['new', 'old', 'never'])
    expect(sorted(byTime, { key: 'checked', dir: 'asc' }).map(x => x.company)).toEqual(['old', 'new', 'never'])
    expect(typeof comparator()).toBe('function')                              // the default is Company A-Z
    // a click starts names A-Z and numbers biggest first, a second click flips
    expect(nextSort({ key: 'company', dir: 'asc' }, 'roles')).toEqual({ key: 'roles', dir: 'desc' })
    expect(nextSort({ key: 'roles', dir: 'desc' }, 'roles')).toEqual({ key: 'roles', dir: 'asc' })
    expect(nextSort({ key: 'roles', dir: 'asc' }, 'company')).toEqual({ key: 'company', dir: 'asc' })
  })
})

// ---------------------------------------------------------------- the table

describe('Companies: the one table', () => {
  beforeEach(() => window.localStorage.clear())

  const mountTable = (health, list = null, cycleDays = 14) =>
    mount(WatchedCompanies, { props: { health, list, cycleDays } })

  const sample = () => mountTable(
    healthOf([
      ok('Alpha', { last_scan: utcStamp(1) }), ok('Bravo', { last_scan: utcStamp(2) }),
      ok('Charlie', { last_scan: utcStamp(40) }),
      { company: 'Delta', state: 'failed', reason: 'the site blocks automated access', kind: 'blocked', error: 'HTTP 403' },
    ]),
    { items: [{ position: 1, name: 'Echo', status: 'failed', detail: 'no careers site found (Qwen did not know one either)' }] },
  )

  it('the legend filters the table and shows its counts; pressing it again clears the filter', async () => {
    const w = sample()
    expect(legendOf(w)).toEqual([
      ['All', 5], ['Checked this cycle', 2], ['Due for a check', 1], ['Failed', 1], ['No job board found', 1],
    ])
    await legendItem(w, 'Due for a check').trigger('click')
    expect(companyRows(w)).toEqual([['Charlie', 'Due for a check']])
    expect(w.find('.result-line').text()).toContain('1 company')
    expect(w.find('.clear-filters').exists()).toBe(true)
    await legendItem(w, 'Due for a check').trigger('click')
    expect(companyRows(w)).toHaveLength(5)
    await legendItem(w, 'Failed').trigger('click')
    await w.find('.clear-filters').trigger('click')
    expect(companyRows(w)).toHaveLength(5)
    expect(legendItem(w, 'All').attributes('aria-pressed')).toBe('true')
  })

  it('a failed or not-found row shows its reason as a second line under the badge', () => {
    const w = sample()
    const delta = w.find('tr[data-bucket="failed"] td.status-cell')
    expect(delta.find('.ui-badge').text()).toBe('Failed')
    expect(delta.find('.status-note').text()).toBe('the site blocks automated access')
    const echo = w.find('tr[data-bucket="not_found"] td.status-cell')
    expect(echo.find('.ui-badge').text()).toBe('No job board found')
    expect(echo.find('.status-note').text()).toContain('no careers site found')
    expect(w.find('tr[data-bucket="checked"] .status-note').exists()).toBe(false)   // a good row says nothing more
  })

  it('has no source select, view toggle, number tiles, A-Z strip or card rows', async () => {
    const many = Array.from({ length: 30 }, (_, i) => ok(`${String.fromCharCode(65 + (i % 6))}Co${i}`, { source: i % 2 ? 'your list' : 'watchlist' }))
    const w = mountTable(healthOf(many))
    expect(w.findAll('select')).toHaveLength(0)                                    // no Source / Sort selects
    expect(w.text()).not.toContain('Watchlist and your list')
    for (const gone of ['.view-list', '.view-watched', '.tile', '.jump', '.jump-letter', '.letter', '.dir', '.co', 'a.health-csv']) {
      expect(w.find(gone).exists(), gone).toBe(false)
    }
    expect(w.findAll('.chip').filter(c => c.text() === 'your list')).toHaveLength(0)
    expect(w.findAll('tbody tr')).toHaveLength(30)
  })
})

describe('Companies: the tab around the table', () => {
  beforeEach(() => {
    resetSeenJobs()
    window.localStorage.clear()
  })
  afterEach(() => vi.unstubAllGlobals())

  async function mountTab(options) {
    vi.stubGlobal('fetch', fakeApi(options).fetch)
    const w = mount(Companies, { props: { run: 'all', jobs: [] } })
    await flushPromises()
    return w
  }

  it('the drop zone is the first-run page only (nothing watched, no list); the overlay shows over any page', async () => {
    const first = await mountTab({ health: healthOf([]) })
    expect(first.find('button.drop').exists()).toBe(true)
    expect(first.find('.empty-title').text()).toBe('No list yet.')
    first.unmount()

    const watching = await mountTab({ health: healthOf([ok('Grab')]) })
    expect(watching.find('button.drop').exists()).toBe(false)
    expect(watching.find('.empty-title').exists()).toBe(false)
    expect(watching.find('.funnel').text()).toMatch(/^1\s*watched/)               // no list: the sentence starts at "watched"

    // ... and a file dragged over the tab shows the overlay; leaving hides it.
    expect(watching.find('.drop-overlay').exists()).toBe(false)
    await watching.find('section.companies-tab').trigger('dragenter', { dataTransfer: { types: ['Files'] } })
    expect(watching.find('.drop-overlay').text()).toBe('Drop to replace your list')
    expect(watching.find('.drop-overlay').attributes('data-drop')).toBe('over')
    await watching.find('section.companies-tab').trigger('dragleave')
    expect(watching.find('.drop-overlay').exists()).toBe(false)
  })
})
