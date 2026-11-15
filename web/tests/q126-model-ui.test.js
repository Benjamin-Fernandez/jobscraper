// Q-126 U1 pins (D-214, D-217; ollama_autostart_design.md §4.1, §4.3, §4.5): the queue
// panel's calm "Starting the local AI model" row, the Local AI card lines and attention
// count, and the auto-start switch. No live server: fetch is a fake router. The owner's
// Resume is the only way a model pause lifts (R1): the panel has no timer that does it.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import ApplyQueuePanel from '../src/components/ApplyQueuePanel.vue'
import panelSource from '../src/components/ApplyQueuePanel.vue?raw'
import ConnectionsHub from '../src/components/ConnectionsHub.vue'
import { attentionCount, codeCopy } from '../src/connections.js'
import sample from './fixtures/connections.sample.json'
import { cloneSample, routeFetch } from './q100Fake.js'
import { setHash } from './helpers.js'

enableAutoUnmount(afterEach)
beforeEach(() => { setHash('') })
afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
  setHash('')
})

// ---------------------------------------------------------------- the queue panel

const view = (over = {}) => ({ paused: null, now: null, slot: 'apply', run_pending: false, waiting: [], recent: [], model: null, ...over })
const STARTING = { state: 'starting', since: new Date(Date.now() - 12000).toISOString().slice(0, 19) }
const PAUSE = {
  reason: 'model_start_failed', since: '2026-11-15T08:00:00',
  text: "JobScraper tried to start Ollama, but it didn't start (no answer after 60 seconds). The queue is paused. Nothing was sent.",
  hint: 'Open Ollama from the Start menu, then resume.',
}

async function mountPanel(body, extra = {}) {
  const r = routeFetch({ 'GET apply/queue': () => body, ...extra })
  const w = mount(ApplyQueuePanel, { attachTo: document.body })
  await flushPromises()
  return { w, r }
}

describe('Runs: the queue panel while the model starts', () => {
  it('shows one calm row, with no banner, no Stop and no Resume', async () => {
    const { w } = await mountPanel(view({ model: STARTING, waiting: [{ job_id: 'q1', company: 'Example Co', role: 'Analyst', mode: 'auto', position: 1, enqueued_at: '2026-11-15T08:00:00', source: 'inbox', note: null }] }))
    const row = w.find('.aq-live[aria-live="polite"] li.aq-model')
    expect(row.exists()).toBe(true)
    expect(row.attributes('data-state')).toBe('starting')
    expect(row.text()).toContain('Starting the local AI model…')
    expect(row.find('.aq-elapsed').exists()).toBe(true)
    expect(w.find('.aq-paused').exists()).toBe(false)
    expect(w.find('.aq-resume').exists()).toBe(false)
    expect(w.find('button.aq-stop').exists()).toBe(false)               // no attempt exists yet
    expect(w.find('button.aq-pause').exists()).toBe(true)               // Pause still works
  })

  it('the loading state says the first load can take a minute', async () => {
    const { w } = await mountPanel(view({ model: { state: 'loading', since: STARTING.since } }))
    const row = w.find('li.aq-model')
    expect(row.attributes('data-state')).toBe('loading')
    expect(row.text()).toContain('Loading the model…')
    expect(row.text()).toContain('The first load can take a minute.')
  })

  it('another state word, or no model, draws no row', async () => {
    for (const model of [null, { state: 'ready', since: STARTING.since }, { state: 'weird', since: STARTING.since }]) {
      const { w } = await mountPanel(view({ model }))
      expect(w.find('li.aq-model').exists(), JSON.stringify(model)).toBe(false)
      w.unmount()
    }
  })

  it('a stored pause beats the starting row and keeps Resume (an owner Pause during the wait)', async () => {
    const { w } = await mountPanel(view({ model: STARTING, paused: { reason: 'owner', text: 'You paused the queue.', hint: 'Resume it to go on.', since: '2026-11-15T08:00:00' } }))
    expect(w.find('li.aq-model').exists()).toBe(false)
    expect(w.find('.aq-paused').exists()).toBe(true)
    expect(w.find('button.aq-resume').exists()).toBe(true)
  })

  it('a model pause shows the server text and hint as given, with the Resume button', async () => {
    const { w } = await mountPanel(view({ slot: 'free', paused: PAUSE }))
    expect(w.find('.aq-paused-text').text()).toBe(PAUSE.text)
    expect(w.find('.aq-paused-hint').text()).toBe(PAUSE.hint)
    expect(w.find('button.aq-resume').exists()).toBe(true)
    expect(w.find('li.aq-model').exists()).toBe(false)
  })
})

describe('Runs: nothing in the browser lifts a model pause by itself (R1)', () => {
  it('ten minutes of polling never posts a resume', async () => {
    vi.useFakeTimers()
    const { r } = await mountPanel(view({ slot: 'free', paused: PAUSE }))
    await vi.advanceTimersByTimeAsync(10 * 60 * 1000)
    await flushPromises()
    expect(r.of('POST', 'apply/queue/resume')).toHaveLength(0)
    expect(r.calls.filter(c => c.method !== 'GET')).toHaveLength(0)     // it only reads
    expect(r.of('GET', 'apply/queue').length).toBeGreaterThan(1)        // and it did poll
  })

  it('structurally: only the Resume button reaches resumeApplyQueue; no timer path does', () => {
    const uses = panelSource.match(/resumeApplyQueue/g) || []
    expect(uses).toHaveLength(2)                                        // the import and the one `resume` action
    expect(panelSource).toMatch(/const resume = \(\) => run\('resume', resumeApplyQueue/)
    const at = panelSource.indexOf('function poll()')
    const poll = at < 0 ? '' : panelSource.slice(at, at + 700)
    expect(poll.length).toBeGreaterThan(100)
    expect(poll.toLowerCase()).not.toContain('resume')
    for (const line of panelSource.split('\n').filter(l => /setInterval\(|setTimeout\(/.test(l))) {
      expect(line.toLowerCase(), line).not.toContain('resume')
    }
    expect(panelSource).not.toMatch(/watch\([^)]*paused[^)]*\)[^\n]*resume/i)
  })
})

// ---------------------------------------------------------------- the Local AI card

const modelItem = (over = {}, facts = {}) => ({
  id: 'model', kind: 'model', state: 'neutral', code: 'unreachable', optional: false,
  facts: { backend: 'ollama', model: 'example-model:8b', local: true, need_now: true, need_reason: 'application',
    pending_mail: 0, autostart: true, autostart_here: true, installed: true, ...facts },
  ...over,
})
const only = item => ({ items: [item] })

describe('Local AI card: lines and attention count', () => {
  it('not running with autostart: a calm line and no attention, even when a task waits', () => {
    const item = modelItem()
    expect(codeCopy(item)).toBe("Ollama isn't running. JobScraper starts it when a task needs it.")
    expect(attentionCount(only(item))).toBe(0)
  })

  it('a stored pause is attention and shows the server message', () => {
    const message = `${PAUSE.text} ${PAUSE.hint}`
    const item = modelItem({ state: 'attention', message })
    expect(codeCopy(item)).toBe(message)
    expect(attentionCount(only(item))).toBe(1)
  })

  it('installed: false says so, and still needs attention when a task waits', () => {
    const item = modelItem({ state: 'attention' }, { installed: false })
    expect(codeCopy(item)).toBe("Ollama isn't installed. Install it from ollama.com to use the local AI.")
    expect(attentionCount(only(item))).toBe(1)
  })

  it('without the facts (an older server, a dev copy, switched off) the old words stay', () => {
    expect(codeCopy(modelItem({ state: 'attention' }, { autostart: false }), { what: 'an application' }))
      .toBe("Ollama isn't running, and an application is waiting for it. Start Ollama, then check again.")
    expect(codeCopy(modelItem({}, { autostart_here: false, need_now: false })))
      .toBe("Ollama isn't running. Nothing needs it right now.")
    const old = modelItem()
    delete old.facts.autostart
    delete old.facts.autostart_here
    delete old.facts.installed
    expect(codeCopy({ ...old, state: 'neutral' })).toBe("Ollama isn't running. Nothing needs it right now.")
  })
})

// ---------------------------------------------------------------- the switch

const SWITCH = 'Start the local AI model when it is needed'

async function hub(facts = {}, routes = {}) {
  const connections = cloneSample(sample)
  const i = connections.items.findIndex(x => x.kind === 'model')
  connections.items[i] = { ...connections.items[i], ...modelItem({}, facts), id: connections.items[i].id }
  const r = routeFetch(routes)
  const w = mount(ConnectionsHub, { props: { connections }, attachTo: document.body })
  await flushPromises()
  return { w, r }
}
const sw = w => w.find('.hub-switch [role="switch"]')

describe('Local AI card: the auto-start switch', () => {
  it('shows the label and the current value', async () => {
    const { w } = await hub()
    const row = w.find('.hub-switch')
    expect(row.text()).toContain(SWITCH)
    expect(sw(w).attributes('aria-checked')).toBe('true')
  })

  it('saves on change with {enabled}, says Saved, and asks the page to reload', async () => {
    const { w, r } = await hub({}, { 'PUT connections/model/autostart': body => ({ enabled: body.enabled, default: true }) })
    await sw(w).trigger('click')
    await flushPromises()
    expect(r.of('PUT', 'connections/model/autostart').map(c => c.body)).toEqual([{ enabled: false }])
    expect(sw(w).attributes('aria-checked')).toBe('false')
    expect(w.find('.hub-switch .setting-saved').text()).toContain('Saved')
    expect(w.emitted('reload')).toBeTruthy()
  })

  it('a failed save shows the error words and leaves the switch as it was', async () => {
    const { w } = await hub({}, { 'PUT connections/model/autostart': [422, { detail: 'invalid', errors: [{ field: 'enabled', message: 'Start the local AI model must be true or false' }] }] })
    await sw(w).trigger('click')
    await flushPromises()
    expect(w.find('.hub-switch [role="alert"]').text()).toContain("Couldn't save:")
    expect(sw(w).attributes('aria-checked')).toBe('true')
    expect(w.emitted('reload')).toBeFalsy()
  })

  it('is a static row, not a switch, where auto-start is not allowed (a dev copy)', async () => {
    const { w } = await hub({ autostart_here: false })
    expect(sw(w).exists()).toBe(false)
    expect(w.find('.hub-switch').text()).toContain(SWITCH)
    expect(w.find('.hub-switch').text()).toContain('Not in this copy of JobScraper.')
  })

  it('is absent when the server sends no `autostart` fact', async () => {
    const { w } = await hub({ autostart: undefined })
    expect(w.find('.hub-switch').exists()).toBe(false)
  })
})
