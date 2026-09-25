import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import Runs from '../src/tabs/Runs.vue'
import App from '../src/App.vue'
import { POLL_MS, resetSeenJobs } from '../src/composables/useJob.js'
import { fakeApi, runsFrom, setHash } from './helpers.js'

let api

function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
  return api
}

beforeEach(() => {
  resetSeenJobs()
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  useApi()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
enableAutoUnmount(afterEach)

async function mountRuns(props = {}) {
  const wrapper = mount(Runs, { props: { runs: runsFrom(), ...props } })
  await flushPromises()
  return wrapper
}

async function tick(times = 1) {
  for (let i = 0; i < times; i++) {
    await vi.advanceTimersByTimeAsync(POLL_MS)
    await flushPromises()
  }
}

const polls = () => api.count(/^api\/jobs\/current/)
const posts = url => api.calls.filter(c => c.method === 'POST' && c.url === url)

async function start(wrapper) {
  await wrapper.find('form.start').trigger('submit')
  await flushPromises()
}

describe('Runs tab: starting a run', () => {
  it('prefills companies from the saved setting and starts a run with it', async () => {
    const wrapper = await mountRuns()
    expect(wrapper.find('#run-batch').element.value).toBe('10')
    expect(wrapper.find('#run-batch-hint').text()).toContain('10 of 224')

    await start(wrapper)
    expect(posts('api/jobs/run')).toHaveLength(1)
    expect(JSON.parse(posts('api/jobs/run')[0].body)).toEqual({ batch_size: 10 })
  })

  it('sends the dry-run toggle and a changed company count', async () => {
    const wrapper = await mountRuns()
    await wrapper.find('#run-batch').setValue('25')
    await wrapper.find('input[type="checkbox"]').setValue(true)
    expect(wrapper.find('button.start-run').text()).toBe('Start dry run')
    await start(wrapper)
    expect(JSON.parse(posts('api/jobs/run')[0].body)).toEqual({ batch_size: 25, dry_run: true })
  })

  it('blocks an out-of-range company count in the form', async () => {
    const wrapper = await mountRuns()
    for (const bad of ['0', '-1', '225', '2.5']) {
      await wrapper.find('#run-batch').setValue(bad)
      expect(wrapper.find('button.start-run').attributes('disabled'), bad).toBeDefined()
      expect(wrapper.find('#run-batch').attributes('aria-invalid')).toBe('true')
      await start(wrapper)
    }
    expect(posts('api/jobs/run')).toHaveLength(0)
  })

  it('a 409 says a job is already running and shows that job', async () => {
    const wrapper = await mountRuns()
    // Someone else (the CLI, another browser tab) started a job meanwhile.
    api.server.job = { id: 99, kind: 'profile', state: 'running', started_at: '2026-09-25T09:00:00', finished_at: null, exit_code: null, log: ['parsing resume'] }
    await start(wrapper)

    expect(wrapper.find('[role="alert"]').text()).toMatch(/a job is already running/i)
    expect(wrapper.find('.job-status').attributes('data-state')).toBe('running')
    expect(wrapper.find('.log').text()).toContain('parsing resume')
    expect(wrapper.find('button.start-run').attributes('disabled')).toBeDefined()
    expect(wrapper.find('button.cancel').text()).toBe('Cancel profile refresh')
  })
})

describe('Runs tab: watching a run', () => {
  it('polls while running and shows log lines as they arrive', async () => {
    const wrapper = await mountRuns()
    await start(wrapper)
    expect(wrapper.find('.job-status').attributes('data-state')).toBe('running')
    const before = polls()

    api.log('run 13: 10 companies due')
    await tick()
    expect(polls()).toBe(before + 1)
    expect(wrapper.find('.log').text()).toContain('run 13: 10 companies due')

    api.log('  -> OKX: 12 postings, 3 new')
    await tick()
    expect(wrapper.find('.log').text().split('\n')).toEqual(['run 13: 10 companies due', '  -> OKX: 12 postings, 3 new'])
  })

  it('stops polling when the run ends and asks the shell to reload', async () => {
    const wrapper = await mountRuns()
    await start(wrapper)
    api.finishJob()
    await tick()
    expect(wrapper.find('.job-status').attributes('data-state')).toBe('succeeded')
    expect(wrapper.find('.summary').text()).toMatch(/^Run finished/)
    expect(wrapper.emitted('changed')).toEqual([[{ runs: true }]])

    const after = polls()
    await tick(4)
    expect(polls()).toBe(after)
  })

  it('does not poll while nothing is running', async () => {
    const wrapper = await mountRuns()
    expect(wrapper.find('.summary').text()).toContain('Nothing has run')
    await tick(5)
    expect(polls()).toBe(1)
  })

  it('stops polling when the tab is closed', async () => {
    const wrapper = await mountRuns()
    await start(wrapper)
    await tick()
    wrapper.unmount()
    const at = polls()
    await tick(4)
    expect(polls()).toBe(at)
  })

  it('a run that ended while the tab was closed still reloads the shell once', async () => {
    const first = await mountRuns()
    await start(first)
    first.unmount()
    api.finishJob()

    const second = await mountRuns()
    expect(second.emitted('changed')).toEqual([[{ runs: true }]])
    const third = await mountRuns()
    expect(third.emitted('changed')).toBeUndefined()
  })

  it('cancel terminates the job and polling stops', async () => {
    const wrapper = await mountRuns()
    await start(wrapper)
    await wrapper.find('button.cancel').trigger('click')
    await flushPromises()

    expect(posts('api/jobs/cancel')).toHaveLength(1)
    expect(wrapper.find('.job-status').attributes('data-state')).toBe('failed')
    expect(wrapper.find('.summary').text()).toContain('exit -15')
    expect(wrapper.find('button.cancel').exists()).toBe(false)
    const at = polls()
    await tick(3)
    expect(polls()).toBe(at)
  })
})

describe('Runs tab: jobs it cannot control', () => {
  it('a job left running across a web restart says it cannot be cancelled here', async () => {
    useApi({ job: { id: 3, kind: 'run', state: 'running', started_at: '2026-09-25T08:00:00', log: ['run 13: 10 companies due'] } })
    api.server.orphaned = true
    const wrapper = await mountRuns()
    await wrapper.find('button.cancel').trigger('click')
    await flushPromises()

    const alert = wrapper.find('[role="alert"]').text()
    expect(alert).toContain('cannot be cancelled from here')
    expect(alert).toContain('restarted')
    expect(wrapper.find('.job-status').attributes('data-state')).toBe('running')
  })

  it('a 409 on cancel after the job ended just says nothing is running', async () => {
    const wrapper = await mountRuns()
    await start(wrapper)
    api.finishJob()
    await wrapper.find('button.cancel').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toBe('Nothing is running any more.')
  })

  it('with no company enabled yet, the form defers to the server', async () => {
    useApi({ settings: { batch_size: 10, batch_size_default: 10, enabled_companies: 0, cycle_days: 14, runs_per_day_needed: 0 } })
    const wrapper = await mountRuns()
    expect(wrapper.find('#run-batch-hint').text()).toContain('No companies are enabled yet')
    expect(wrapper.find('button.start-run').attributes('disabled')).toBeUndefined()
  })
})

describe('Runs tab: history', () => {
  it('lists date, companies, postings, accepted and status per run', async () => {
    const runs = [
      { run_no: 12, finished_at: '2026-09-23T14:30:00', status: 'ok', accepted: 3, stats: { companies_due: 10, postings_seen: 412 } },
      { run_no: 11, finished_at: null, started_at: '2026-09-21T09:00:00', status: 'failed', accepted: 0 },
    ]
    const wrapper = await mountRuns({ runs })
    const cells = r => wrapper.findAll(`tr[data-run="${r}"] td`).map(td => td.text())
    expect(cells(12)).toEqual(['12', '23 Sep', '10', '412', '3', 'ok'])
    expect(cells(11)).toEqual(['11', '21 Sep', '—', '—', '0', 'failed'])
  })

  it('says so when there are no runs yet', async () => {
    const wrapper = await mountRuns({ runs: [] })
    expect(wrapper.text()).toContain('No runs yet')
  })

  it('without the M11 routes, says so readably and still shows the history', async () => {
    useApi({ m11: false })
    const wrapper = await mountRuns()
    const alerts = wrapper.findAll('[role="alert"]').map(a => a.text()).join(' ')
    expect(alerts).toContain('404')
    expect(alerts).toContain('does not offer that yet')
    expect(alerts).not.toContain('Not Found - Not Found')
    expect(wrapper.findAll('tr[data-run]')).toHaveLength(2)
  })
})

describe('Runs tab inside the app', () => {
  it('a finished run refreshes the run list, and the Inbox moves to the new run', async () => {
    setHash('#/runs')
    const wrapper = mount(App)
    await flushPromises()
    await flushPromises()
    expect(wrapper.findAll('tr[data-run]').map(r => r.attributes('data-run'))).toEqual(['12', '11'])

    await start(wrapper)
    api.log('working')
    await tick()
    api.finishJob()
    await tick()

    expect(api.count(/^api\/runs$/)).toBe(2)
    expect(wrapper.findAll('tr[data-run]').map(r => r.attributes('data-run'))).toEqual(['13', '12', '11'])
    expect(api.calls.some(c => c.url === 'api/shortlist?run=13')).toBe(true)
  })
})
