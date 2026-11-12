// The UI pass after M17: quick sizes for a run (30, 50, 100, 200, All, or any
// number), the watched companies as a searchable A-Z directory with every
// failure and its cause, a searchable "Your list", run durations, and "/" to
// search.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import App from '../src/App.vue'
import Companies from '../src/tabs/Companies.vue'
import Runs from '../src/tabs/Runs.vue'
import Settings from '../src/tabs/Settings.vue'
import CountPicker from '../src/components/CountPicker.vue'
import WatchedCompanies from '../src/components/WatchedCompanies.vue'
import { requestCompanyFilter } from '../src/companyFilter.js'
import { resetSeenJobs } from '../src/composables/useJob.js'
import { ago, duration } from '../src/format.js'
import { companyRows, fakeApi, healthOf, legendItem, runsFrom, setHash, utcStamp } from './helpers.js'

let api
function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
  return api
}

beforeEach(() => {
  resetSeenJobs()
  window.localStorage.clear()
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  useApi()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
enableAutoUnmount(afterEach)

const posts = url => api.calls.filter(c => c.method === 'POST' && c.url === url)

// ---------------------------------------------------------------- CountPicker

describe('CountPicker', () => {
  function picker(props = {}) {
    return mount(CountPicker, { props: { inputId: 'n', modelValue: 10, max: 150, ...props } })
  }
  const last = w => w.emitted('update:modelValue').at(-1)[0]

  it('offers 30, 50, 100, 200 and All; a size over the enabled count cannot be picked', () => {
    const w = picker()
    expect(w.findAll('.preset').map(b => b.text())).toEqual(['30', '50', '100', '200', 'All150'])
    expect(w.find('[data-preset="200"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-preset="200"]').attributes('title')).toBe('Only 150 companies are enabled')
    expect(w.find('[data-preset="100"]').attributes('disabled')).toBeUndefined()
  })

  it('a preset sets the value, All sets every enabled company', async () => {
    const w = picker()
    await w.find('[data-preset="50"]').trigger('click')
    expect(last(w)).toBe(50)
    await w.find('[data-preset="all"]').trigger('click')
    expect(last(w)).toBe(150)
  })

  it('typing a preset\'s number lights that preset; All lights for the maximum', async () => {
    expect(picker({ modelValue: 100 }).find('[data-preset="100"]').attributes('aria-pressed')).toBe('true')
    const all = picker({ modelValue: 150 })
    expect(all.find('[data-preset="all"]').attributes('aria-pressed')).toBe('true')
    const custom = picker({ modelValue: 42 })
    expect(custom.findAll('.preset[aria-pressed="true"]')).toHaveLength(0)
    await custom.find('#n').setValue('77')
    expect(last(custom)).toBe(77)
    await custom.find('#n').setValue('')
    expect(last(custom)).toBe('')
  })
})

// ---------------------------------------------------------------- Runs

describe('Runs: choosing how many companies', () => {
  async function mountRuns(props = {}) {
    const w = mount(Runs, { props: { runs: runsFrom(), ...props } })
    await flushPromises()
    return w
  }

  it('starts a run with a preset, or with All', async () => {
    const w = await mountRuns()
    await w.find('[data-preset="30"]').trigger('click')
    await w.find('form.start').trigger('submit')
    await flushPromises()
    expect(JSON.parse(posts('api/jobs/run')[0].body)).toEqual({ batch_size: 30 })
  })

  it('All sends every enabled company', async () => {
    const w = await mountRuns()
    await w.find('[data-preset="all"]').trigger('click')
    // Q-118 LC: All lights its segment, the field (Custom only) goes away, and
    // the button carries the count.
    expect(w.find('[data-preset="all"]').attributes('aria-pressed')).toBe('true')
    expect(w.find('[data-preset="all"]').attributes('aria-label')).toBe('All 224 companies')
    expect(w.find('#run-batch').exists()).toBe(false)
    expect(w.find('button.start-run').text()).toBe('Check all 224 companies')
    await w.find('form.start').trigger('submit')
    await flushPromises()
    expect(JSON.parse(posts('api/jobs/run')[0].body)).toEqual({ batch_size: 224 })
  })

  it('estimates how long a run takes from recent runs', async () => {
    const runs = [
      { run_no: 3, started_at: '2026-09-23T14:00:00', finished_at: '2026-09-23T14:10:00', status: 'ok', accepted: 1, stats: { companies_due: 100 } },
      { run_no: 2, started_at: '2026-09-22T14:00:00', finished_at: '2026-09-22T14:01:00', status: 'aborted_unhealthy', accepted: 0, stats: { companies_due: 0 } },
    ]
    const w = await mountRuns({ runs })
    // 600 s for 100 companies = 6 s each; 10 companies -> 1 min.
    // Q-118 LC: the estimate sits in the count's hint.
    expect(w.find('#run-batch-hint').text()).toContain('10 of 224 companies · about 1 min.')
    await w.find('[data-preset="200"]').trigger('click')
    expect(w.find('#run-batch-hint').text()).toContain('200 of 224 companies · about 20 min.')
  })

  it('says when the last run finished and what it found', async () => {
    const w = await mountRuns()
    expect(w.find('.last-run').text()).toMatch(/^Last run .+ ago|^Last run yesterday/)
    expect(w.find('.last-run').text()).toContain('match')
  })
})

describe('Settings: the same quick sizes', () => {
  it('a preset saves at once from the open row, like a typed number saved with Enter', async () => {
    setHash('#/settings/search')   // Q-100: the quick sizes are in the Search view
    const w = mount(Settings)
    await flushPromises()
    await w.find('#setting-batch-size .setting-main').trigger('click')   // Q-116: the picker is in the opened row
    await flushPromises()
    await w.find('[data-preset="50"]').trigger('click')                   // no form, no Save button
    await flushPromises()
    const puts = api.calls.filter(c => c.method === 'PUT' && c.url === 'api/settings')
    expect(puts.map(c => JSON.parse(c.body))).toEqual([{ batch_size: 50 }])
  })
})

// ---------------------------------------------------------------- watched companies

function health() {
  const row = (company, state, fields = {}) => ({
    company, state, reason: '', kind: '', paused: false, open_roles: state === 'ok' ? 5 : null,
    job_board: 'greenhouse', careers_url: `https://${company.toLowerCase().replace(/\W/g, '')}.example/careers`,
    last_scan: '2026-10-20 10:00', last_success: '2026-10-20 10:00', failures_in_a_row: 0, error: '',
    source: 'watchlist', ...fields,
  })
  const items = [
    row('Grab', 'ok', { open_roles: 40 }),
    row('adyen', 'ok', { open_roles: 250, job_board: 'lever' }),
    row('Akamai', 'failed', { kind: 'blocked', paused: true, reason: 'the site blocks automated access; paused after repeated failures, retried later', error: 'HTTP 403 for https://www.akamai.com/careers', failures_in_a_row: 4, last_success: '' }),
    row('BitMEX', 'failed', { kind: 'gone', reason: 'the careers page no longer exists', error: 'HTTP 404', failures_in_a_row: 1 }),
    row('Garena', 'failed', { kind: 'transient', reason: 'a temporary error (timeout or server error) - retried on the next scan', error: 'ReadTimeout' }),
    row('Zalando', 'ok', { source: 'your list' }),
  ]
  return { total: items.length, counts: { ok: 3, failed: 3, not_scanned: 0 }, items }
}

describe('Watched companies', () => {
  function watched(props = {}) {
    return mount(WatchedCompanies, { props: { health: health(), ...props } })
  }
  const names = w => w.findAll('.companies-table .co-name').map(n => n.text())

  // Q-118 LD: one table, no letter headings; the default sort is Company A-Z (case ignored).
  it('lists every company A-Z, ignoring case, in one table', () => {
    const w = watched()
    expect(names(w)).toEqual(['adyen', 'Akamai', 'BitMEX', 'Garena', 'Grab', 'Zalando'])
    expect(w.find('th[aria-sort="ascending"]').text()).toBe('Company')
    expect(w.find('.letter').exists()).toBe(false)
    expect(w.find('.result-line').text()).toContain('6 companies')
  })

  it('searches by name, job board or reason', async () => {
    const w = watched()
    await w.find('input.company-search').setValue('gra')
    expect(names(w)).toEqual(['Grab'])
    await w.find('input.company-search').setValue('LEVER')
    expect(names(w)).toEqual(['adyen'])
    expect(w.find('tbody tr td[data-label="Job board"]').text()).toBe('Lever')
    await w.find('input.company-search').setValue('blocks')
    expect(names(w)).toEqual(['Akamai'])
    await w.find('input.company-search').setValue('nothing like it')
    expect(w.find('.empty-title').text()).toBe('No companies match.')
    await w.find('.empty button.link').trigger('click')
    expect(names(w)).toHaveLength(6)
  })

  it('the Failed legend shows only failures, each saying why, grouped by cause', async () => {
    const w = watched()
    await legendItem(w, 'Failed').trigger('click')
    expect(names(w)).toEqual(['Akamai', 'BitMEX', 'Garena'])
    // The reason is the second line of the status cell (it replaced the per-row details).
    expect(w.findAll('tr[data-bucket="failed"] .status-note').map(n => n.text())).toEqual([
      'the site blocks automated access; paused after repeated failures, retried later',
      'the careers page no longer exists',
      'a temporary error (timeout or server error) - retried on the next scan',
    ])
    // ... and the facts that sat in the opened details are the badge's title.
    expect(w.find('tr[data-bucket="failed"] .ui-badge').attributes('title'))
      .toBe('4 failures in a row · never worked · error: HTTP 403 for https://www.akamai.com/careers')

    expect(w.findAll('.cause').map(c => c.findAll('span').map(s => s.text()).join(' ')))
      .toEqual(['Every cause 3', 'Blocks automated access 1', 'Careers page gone 1', 'Temporary error 1'])
    await w.find('.cause[data-cause="gone"]').trigger('click')
    expect(names(w)).toEqual(['BitMEX'])
    expect(w.find('.cause-fix').text()).toContain('update careers_url in config/watchlist.yaml')
  })

  it('starts on Failed when asked (the Runs tab\'s failed count)', () => {
    const w = watched({ initialState: 'failed' })
    expect(names(w)).toEqual(['Akamai', 'BitMEX', 'Garena'])
  })

  // Q-118 LD: the sort select is the Open roles header (biggest first, unknown last either way).
  // The "filter by source" half of this pin is gone by design (the select was removed);
  // q118-companies.test.js pins its absence. The CSV link moved to the tab's More menu (m17.test.js).
  it('sorts by open roles from the column header', async () => {
    const w = watched()
    const roles = () => w.findAll('th.ui-th').find(th => th.text() === 'Open roles')
    await roles().find('button').trigger('click')
    expect(roles().attributes('aria-sort')).toBe('descending')
    expect(names(w)).toEqual(['adyen', 'Grab', 'Zalando', 'Akamai', 'BitMEX', 'Garena'])
    await roles().find('button').trigger('click')
    expect(roles().attributes('aria-sort')).toBe('ascending')
    expect(names(w)).toEqual(['Zalando', 'Grab', 'adyen', 'Akamai', 'BitMEX', 'Garena'])
  })

  it('says so when the companies cannot be read, and retries', async () => {
    const w = watched({ health: null, error: 'boom' })
    expect(w.find('[role="alert"]').text()).toContain('boom')
    await w.find('[role="alert"] button').trigger('click')
    expect(w.emitted('retry')).toHaveLength(1)
  })
})

describe('Companies tab', () => {
  // Q-118 LD: no two views and no remembered view: the tab always opens on the one table.
  it('opens on the one table with the failed count in its legend, and ignores the old remembered view', async () => {
    window.localStorage.setItem('jobscraper.companies.view', 'list')    // the key the toggle used to write
    useApi({ health: health() })
    const w = mount(Companies, { props: { run: 'all', jobs: [] } })
    await flushPromises()
    expect(w.find('.watched').exists()).toBe(true)
    expect(w.find('.companies-table').exists()).toBe(true)
    expect(legendItem(w, 'Failed').find('.ui-progress-n').text()).toBe('3')
    expect(legendItem(w, 'All').attributes('aria-pressed')).toBe('true')
  })

  it('a request from the Runs tab opens the Failed list whatever was last used', async () => {
    window.localStorage.setItem('jobscraper.companies.view', 'list')
    useApi({ health: health() })
    requestCompanyFilter('failed')
    const w = mount(Companies, { props: { run: 'all', jobs: [] } })
    await flushPromises()
    expect(legendItem(w, 'Failed').attributes('aria-pressed')).toBe('true')
    expect(companyRows(w).map(r => r[0])).toEqual(['Akamai', 'BitMEX', 'Garena'])
  })

  it('your list can be searched and shown A-Z', async () => {
    useApi({
      companies: [
        { name: 'Zalando', status: 'found' }, { name: 'Grab', status: 'failed', detail: 'no careers site found' },
        { name: 'Adyen', status: 'pending' },
      ],
      health: healthOf([{ company: 'Zalando', state: 'ok', reason: '', open_roles: 5, last_scan: utcStamp(1) }]),
    })
    const w = mount(Companies, { props: { run: 'all', jobs: [] } })
    await flushPromises()
    const listNames = () => companyRows(w).map(r => r[0])
    expect(listNames()).toEqual(['Adyen', 'Grab', 'Zalando'])                // A-Z by default
    await w.find('th[aria-sort] button').trigger('click')                   // Company header flips it
    expect(listNames()).toEqual(['Zalando', 'Grab', 'Adyen'])
    await w.find('input.company-search').setValue('careers site')           // the reason is searched too
    expect(listNames()).toEqual(['Grab'])
    await w.find('input.company-search').setValue('xyz')
    expect(w.find('.empty-title').text()).toBe('No companies match.')
  })
})

// ---------------------------------------------------------------- shell + format

describe('"/" focuses the search', () => {
  it('jumps to the open tab\'s search box, but not while typing elsewhere', async () => {
    setHash('#/inbox')
    const w = mount(App, { attachTo: document.body })
    await flushPromises()
    await vi.dynamicImportSettled?.()
    await flushPromises()
    const box = document.querySelector('.panel input[type="search"]')
    expect(box).toBeTruthy()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true }))
    expect(document.activeElement).toBe(box)
    w.unmount()
  })
})

describe('format', () => {
  it('duration and ago', () => {
    expect(duration(45)).toBe('45 s')
    expect(duration(960)).toBe('16 min')
    expect(duration(3900)).toBe('1 h 5 min')
    expect(duration(null)).toBe('')
    const now = Date.parse('2026-10-23T12:00:00Z')
    expect(ago('2026-10-23T11:59:30', now)).toBe('just now')
    expect(ago('2026-10-23T11:30:00', now)).toBe('30 min ago')
    expect(ago('2026-10-23T09:00:00', now)).toBe('3 h ago')
    expect(ago('2026-10-22T09:00:00', now)).toBe('yesterday')
    expect(ago('2026-10-20T09:00:00', now)).toBe('3 days ago')
  })
})
