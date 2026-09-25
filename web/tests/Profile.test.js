import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import Profile from '../src/tabs/Profile.vue'
import { POLL_MS, resetSeenJobs } from '../src/job.js'
import { DOCX, MB, fakeApi } from './helpers.js'

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

// Reading a Blob is real I/O in jsdom, not a microtask: let zero-delay timers
// and I/O callbacks run too, or an upload is still in flight when we look.
async function settle() {
  for (let i = 0; i < 10; i++) {
    await vi.advanceTimersByTimeAsync(0)
    await new Promise(r => setImmediate(r))
    await flushPromises()
  }
}

async function mountProfile() {
  const wrapper = mount(Profile)
  await flushPromises()
  return wrapper
}

function pdf(name = 'cv.pdf', extra = '') {
  return new File([`%PDF-1.7\n${extra}`], name, { type: 'application/pdf' })
}

// Browsers do not let a script set a file input's files; tests may.
async function pick(wrapper, file) {
  const input = wrapper.find('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
  await input.trigger('change')
  await settle()
}

async function drop(wrapper, file) {
  await wrapper.find('.drop').trigger('drop', { dataTransfer: { files: [file] } })
  await settle()
}

const uploads = () => api.calls.filter(c => c.url === 'api/resume')
const refreshes = () => api.calls.filter(c => c.url === 'api/jobs/profile' && c.method === 'POST')

describe('Profile tab: the current profile', () => {
  it('shows summary, skills, target titles, interests, version and source', async () => {
    const wrapper = await mountProfile()
    expect(wrapper.find('.version').text()).toBe('2')
    expect(wrapper.find('.source').text()).toBe('resume.pdf')
    expect(wrapper.find('.parsed').text()).toBe('24 Sep 10:05 UTC')
    expect(wrapper.find('.profile .summary').text()).toContain('cloud and backend internships')
    expect(wrapper.findAll('.skills li').map(l => l.text())).toEqual(['python', 'kubernetes', 'terraform'])
    expect(wrapper.findAll('.titles li').map(l => l.text())).toEqual(['software engineer', 'site reliability engineer'])
    expect(wrapper.findAll('.interests li').map(l => l.text())).toEqual(['infrastructure', 'fintech'])
  })

  it('with no derived profile yet, says what to do rather than showing an error', async () => {
    useApi({ profile: { present: false } })
    const wrapper = await mountProfile()
    expect(wrapper.text()).toContain('No profile yet')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('without the M11 routes, shows a readable error', async () => {
    useApi({ m11: false })
    const wrapper = await mountProfile()
    const alert = wrapper.find('[role="alert"]').text()
    expect(alert).toContain('404')
    expect(alert).toContain('does not offer that yet')
  })
})

describe('Profile tab: uploading a resume', () => {
  it('a PDF goes up as the raw body with its own type, then the refresh starts', async () => {
    const wrapper = await mountProfile()
    const file = pdf()
    await pick(wrapper, file)

    expect(uploads()).toHaveLength(1)
    const put = uploads()[0]
    expect(put.method).toBe('PUT')
    expect(put.headers['Content-Type']).toBe('application/pdf')
    expect(put.body).toBe(file)
    expect(put.body).not.toBeInstanceOf(FormData)

    expect(refreshes()).toHaveLength(1)
    expect(api.calls.indexOf(refreshes()[0])).toBeGreaterThan(api.calls.indexOf(put))
    expect(wrapper.find('.notice.ok').text()).toContain('Saved cv.pdf as resume.pdf')
    expect(wrapper.find('.job-status').attributes('data-state')).toBe('running')
  })

  it('shows the refresh progress and reloads the profile when it is done', async () => {
    const wrapper = await mountProfile()
    await pick(wrapper, pdf())
    api.log('extracting text', 'deriving profile v3')
    await vi.advanceTimersByTimeAsync(POLL_MS)
    await flushPromises()
    expect(wrapper.find('.log').text()).toContain('deriving profile v3')

    api.finishJob()
    await vi.advanceTimersByTimeAsync(POLL_MS)
    await flushPromises()
    expect(wrapper.find('.job-status').attributes('data-state')).toBe('succeeded')
    expect(wrapper.find('.version').text()).toBe('3')
    expect(wrapper.find('.notice.ok').text()).toBe('Profile refreshed.')
  })

  it('a dropped DOCX works too, typed by its extension when the browser gives none', async () => {
    const wrapper = await mountProfile()
    await drop(wrapper, new File(['PK\u0003\u0004docx'], 'cv.docx', { type: '' }))
    expect(uploads()).toHaveLength(1)
    expect(uploads()[0].headers['Content-Type']).toBe(DOCX)
    expect(refreshes()).toHaveLength(1)
  })

  it('a .txt is refused in the browser, before any upload', async () => {
    const wrapper = await mountProfile()
    await pick(wrapper, new File(['plain text resume'], 'cv.txt', { type: 'text/plain' }))
    expect(uploads()).toHaveLength(0)
    expect(refreshes()).toHaveLength(0)
    expect(wrapper.find('[role="alert"]').text()).toContain('cv.txt is not a PDF or DOCX file')
  })

  it('a file over 5 MB is refused in the browser', async () => {
    const wrapper = await mountProfile()
    await pick(wrapper, new File([new Uint8Array(5 * MB + 1)], 'big.pdf', { type: 'application/pdf' }))
    expect(uploads()).toHaveLength(0)
    expect(wrapper.find('[role="alert"]').text()).toContain('larger than 5 MB')
  })

  it('a server 415 (bad magic bytes) is shown in words and no refresh starts', async () => {
    const wrapper = await mountProfile()
    await pick(wrapper, new File(['not really a pdf'], 'fake.pdf', { type: 'application/pdf' }))
    expect(uploads()).toHaveLength(1)
    expect(refreshes()).toHaveLength(0)
    expect(wrapper.find('[role="alert"]').text()).toContain('not a readable PDF or DOCX')
  })

  it('a server 413 is shown in words', async () => {
    const real = api.fetch
    vi.stubGlobal('fetch', vi.fn(async (url, init) => (url === 'api/resume'
      ? { ok: false, status: 413, statusText: 'Payload Too Large', json: async () => ({ detail: 'too large' }) }
      : real(url, init))))
    const wrapper = await mountProfile()
    await pick(wrapper, pdf())
    expect(wrapper.find('[role="alert"]').text()).toBe('The server refused the file: it is larger than 5 MB.')
  })

  it('a busy server (409) keeps the upload and says to refresh later', async () => {
    const wrapper = await mountProfile()
    // A run started elsewhere (the CLI, another browser tab) after this tab looked.
    api.server.job = { id: 6, kind: 'run', state: 'running', started_at: '2026-09-25T09:05:00', finished_at: null, exit_code: null, log: [] }
    await pick(wrapper, pdf())
    expect(uploads()).toHaveLength(1)
    expect(api.server.resume.saved).toBe('resume.pdf')
    expect(wrapper.find('[role="alert"]').text()).toContain('A job is already running')
    expect(wrapper.find('.job-status').attributes('data-state')).toBe('running')
    expect(wrapper.find('input[type="file"]').attributes('disabled')).toBeDefined()
  })

  it('the drop zone and picker are disabled while a job runs', async () => {
    useApi({ job: { id: 5, kind: 'run', state: 'running', started_at: '2026-09-25T09:00:00', log: [] } })
    const wrapper = await mountProfile()
    expect(wrapper.find('input[type="file"]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('button.refresh').attributes('disabled')).toBeDefined()
    await drop(wrapper, pdf())
    expect(uploads()).toHaveLength(0)
  })

  it('the refresh button re-derives from the stored resume without an upload', async () => {
    const wrapper = await mountProfile()
    await wrapper.find('button.refresh').trigger('click')
    await flushPromises()
    expect(uploads()).toHaveLength(0)
    expect(refreshes()).toHaveLength(1)
    expect(wrapper.find('button.refresh').attributes('disabled')).toBeDefined()
  })
})
