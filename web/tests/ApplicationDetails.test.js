// WP-Q0 oracles for Profile -> Application details (questions_design.md 3.3, 9.1, 10.1-10.3; WP-W5).
//
// Skip-clean: `web/src/components/ApplicationDetails.vue` does not exist until lane U builds it. The suite
// is `describe.skip` while the file is absent (import.meta.glob finds nothing), so `npx vitest run` stays
// green and the tests start running the moment the component lands. Same convention as h1.test.js's it.skip.
//
// ASSUMED component contract (change `mountDetails` / the fake if lane U decides otherwise):
//   * `mount(ApplicationDetails)` with no props; on mount it GETs `api/applicant` (QD 9.1) and
//     `api/questions?status=open` (QD 9.2, the Questions card is mounted inside it, WP-Q4); the test
//     answers both from JSON payloads. No router, no other tab.
//   * "Save details" is a <button> whose text is exactly the copy of QD 10.2; it PUTs `api/applicant` with
//     {profile, etag}; 409 / 422 answers produce the QD 10.2 copy somewhere in the component's text.
//   * Copy is asserted on the component's rendered text (`wrapper.text()`), not on markup.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'

const loaders = import.meta.glob('../src/components/ApplicationDetails.vue')
const PRESENT = Object.keys(loaders).length > 0
const suite = PRESENT ? describe : describe.skip

// ---- payloads (QD 9.1 shapes; synthetic, no personal data)

const item = (path, label, kind, flags = {}, extra = {}) => ({
  path, label, kind, options: [], help: '', sub: [], required: false, recommended: false, sensitive: false,
  ...flags, ...extra,
})

const FORM = [
  { id: 'contact', title: 'Contact', note: '', items: [
    item('contact.email', 'Email for applications', 'email', { required: true, sensitive: true },
      { help: 'Used for every application and site account.' }),
    item('contact.postal_code', 'Postal code', 'digits', { recommended: true, sensitive: true }),
    item('contact.city', 'City', 'text', { required: true }),
  ] },
  { id: 'availability', title: 'Availability', note: '', items: [
    item('availability.earliest_start_date', 'Earliest start date', 'date', { required: true }),
  ] },
]

function payload(over = {}) {
  return {
    profile: { contact: { email: '', postal_code: '000001', city: '' }, availability: { earliest_start_date: '' } },
    etag: 'aaaaaaaaaaaaaaaa',
    errors: [],
    missing: ['contact.email', 'contact.city', 'availability.earliest_start_date'],
    completeness: { filled: 12, needed: 26 },
    from_resume: [],
    sensitive: ['contact.email', 'contact.postal_code'],
    form: FORM,
    file: { exists: true, has_comments: false, error: '' },
    ...over,
  }
}

const EMPTY_QUESTIONS = { mode: 'dry_run', groups: [], ready: [], waiting: [], busy: false }

function reply(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: { 200: 'OK', 204: 'No Content', 404: 'Not Found', 409: 'Conflict', 422: 'Unprocessable Entity' }[status] ?? 'Error',
    json: async () => JSON.parse(JSON.stringify(body ?? {})),
  }
}

// A fake of the two endpoints, recording every call. `put` decides the PUT answer.
function fakeServer({ applicant = payload(), questions = EMPTY_QUESTIONS, put = null } = {}) {
  const calls = []
  const state = { applicant }
  const fetch = vi.fn(async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase()
    const path = String(url).replace(/^\/?/, '')
    const body = init.body ? JSON.parse(init.body) : undefined
    calls.push({ method, url: path, body })
    if (path === 'api/applicant' && method === 'GET') return reply(state.applicant)
    if (path === 'api/applicant' && method === 'PUT') {
      const r = put ? put(body, state) : { status: 200, body: { ...state.applicant, profile: body.profile, etag: 'bbbbbbbbbbbbbbbb' } }
      if (r.status === 200) state.applicant = r.body
      return reply(r.body, r.status)
    }
    if (path.startsWith('api/questions') && method === 'GET') return reply(questions)
    return reply({ detail: 'Not Found' }, 404)
  })
  return { fetch, calls, state }
}

let server
async function mountDetails(opts) {
  const Details = (await loaders['../src/components/ApplicationDetails.vue']()).default
  server = fakeServer(opts)
  vi.stubGlobal('fetch', server.fetch)
  // attachTo: jsdom only submits a <form> that is connected to the document, and "Save details" is the
  // form's submit button (a real browser always has it connected)
  const wrapper = mount(Details, { attachTo: document.body })
  await flushPromises()
  return wrapper
}

const button = (wrapper, text) => wrapper.findAll('button').find(b => b.text().trim() === text)
const countOf = (text, re) => (text.match(re) || []).length

beforeEach(() => { window.localStorage.clear() })
afterEach(() => { vi.unstubAllGlobals() })
enableAutoUnmount(afterEach)

if (!PRESENT) {
  // visible in the run output: why this file runs nothing yet
  // eslint-disable-next-line no-console
  console.log('[ApplicationDetails.test] skipped: web/src/components/ApplicationDetails.vue is not built yet (WP-W5)')
}

suite('Needed before auto-apply', () => {
  it('lists each missing field by its form label, with a Fill in link, under the QD 10.2 heading', async () => {
    const w = await mountDetails()
    const text = w.text()
    expect(text).toContain('Needed before auto-apply')
    expect(text).toContain("Auto-apply won't start until these are filled in.")
    for (const label of ['Email for applications', 'City', 'Earliest start date']) expect(text).toContain(label)
    expect(w.findAll('a, button').filter(e => e.text().trim() === 'Fill in')).toHaveLength(3)
  })

  it('is hidden when nothing is missing', async () => {
    const w = await mountDetails({ applicant: payload({ missing: [] }) })
    expect(w.text()).not.toContain('Needed before auto-apply')
    expect(w.text()).toContain('Email for applications')      // the form itself is still there
  })
})

suite('field tags and the meter', () => {
  it('tags a required empty field "Needed" and a sensitive one "Private: never sent to the AI"', async () => {
    const w = await mountDetails()
    const text = w.text()
    // "Needed" on email, city and start date (the heading says "Needed before auto-apply": not counted).
    // wrapper.text() joins sibling elements with no space ("Email for applicationsNeededPrivate: ..."),
    // so no \b word boundaries here.
    expect(countOf(text, /Needed(?! before)/g)).toBeGreaterThanOrEqual(3)
    expect(countOf(text, /Private: never sent to the AI/g)).toBeGreaterThanOrEqual(2)   // email and postal code
  })

  it('does not tag a required field that is filled', async () => {
    const filled = payload({
      profile: { contact: { email: 'a@example.com', postal_code: '000001', city: 'Singapore' },
        availability: { earliest_start_date: '2026-02-02' } },
      missing: [],
    })
    const w = await mountDetails({ applicant: filled })
    expect(countOf(w.text(), /Needed(?! before)/g)).toBe(0)
  })

  it('marks a value that came from the resume', async () => {
    const w = await mountDetails({ applicant: payload({ from_resume: ['contact.city'] }) })
    expect(w.text()).toContain('From your resume, please check')
  })

  it('shows the meter as "<filled> of <needed> details filled"', async () => {
    const w = await mountDetails()
    expect(w.text()).toContain('12 of 26 details filled')
  })
})

suite('saving', () => {
  it('PUTs {profile, etag} from the Save details bar and says Saved.', async () => {
    const w = await mountDetails()
    const save = button(w, 'Save details')
    expect(save, 'a "Save details" button').toBeTruthy()
    await save.trigger('click')
    await flushPromises()
    const puts = server.calls.filter(c => c.method === 'PUT' && c.url === 'api/applicant')
    expect(puts).toHaveLength(1)
    expect(puts[0].body.etag).toBe('aaaaaaaaaaaaaaaa')
    expect(puts[0].body.profile.contact.postal_code).toBe('000001')
    expect(w.text()).toContain('Saved.')
  })

  it('a 422 shows the QD 10.2 sentence and the message beside the field, and keeps the edits', async () => {
    const w = await mountDetails({
      put: () => ({ status: 422, body: { detail: 'invalid', errors: [{ path: 'contact.postal_code', message: 'must be 6 digits' }] } }),
    })
    await button(w, 'Save details').trigger('click')
    await flushPromises()
    const text = w.text()
    expect(text).toContain("Some details need fixing. They're marked below.")
    expect(text).toContain('must be 6 digits')
    expect(text).not.toContain('Saved.')
    // the inline message is tied to its input for screen readers (QD 10.3)
    const input = w.find('[aria-describedby]')
    expect(input.exists()).toBe(true)
  })

  it('a 409 "changed" explains why and offers Reload, which fetches the file again', async () => {
    const w = await mountDetails({ put: () => ({ status: 409, body: { detail: 'changed' } }) })
    await button(w, 'Save details').trigger('click')
    await flushPromises()
    expect(w.text()).toContain(
      'This file changed since you opened it, in another tab or by hand. Reload to get the latest, then make your change again.')
    const reload = button(w, 'Reload')
    expect(reload, 'a Reload button').toBeTruthy()
    const before = server.calls.filter(c => c.method === 'GET' && c.url === 'api/applicant').length
    await reload.trigger('click')
    await flushPromises()
    expect(server.calls.filter(c => c.method === 'GET' && c.url === 'api/applicant').length).toBe(before + 1)
  })

  it('an unreadable file says so and never offers a save over it', async () => {
    const w = await mountDetails({
      applicant: payload({ profile: {}, file: { exists: true, has_comments: false, error: 'cannot read applicant.yaml: ScannerError' } }),
    })
    expect(w.text()).toContain("JobScraper can't read data/applicant.yaml (cannot read applicant.yaml: ScannerError)")
    expect(w.text()).toContain('Fix the file by hand. Nothing will be saved over it until then.')
    const save = button(w, 'Save details')
    expect(!save || save.attributes('disabled') !== undefined).toBe(true)
  })

  it('shows the comments note only when the file has comments', async () => {
    const note = 'Saving rewrites applicant.yaml without its comments. A copy with the comments is kept as applicant.commented-backup.yaml.'
    const withComments = await mountDetails({ applicant: payload({ file: { exists: true, has_comments: true, error: '' } }) })
    expect(withComments.text()).toContain(note)
    const without = await mountDetails()
    expect(without.text()).not.toContain('applicant.commented-backup.yaml')
  })
})

suite('answers the owner gave (group 15) and other keys (group 16)', () => {
  it('lists each `extra` entry with a Remove button and confirms before removing', async () => {
    const withExtra = payload({
      profile: {
        contact: { email: 'a@example.com', postal_code: '000001', city: 'Singapore' },
        availability: { earliest_start_date: '2026-02-02' },
        extra: { visa_status: { title: 'Visa status', description: '', kind: 'choice', sensitive: false,
          labels: ['what is your visa status'], value: null, picks: ['citizen'], seen: ['citizen', 'pr'] } },
      },
      missing: [],
    })
    const w = await mountDetails({ applicant: withExtra })
    expect(w.text()).toContain('Answers you gave to application questions')
    expect(w.text()).toContain('Visa status')
    const remove = button(w, 'Remove')
    expect(remove, 'a Remove button').toBeTruthy()
    await remove.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('Remove this answer? Applications that ask it will stop and ask you again.')
    expect(button(w, 'Keep it'), 'a Keep it button').toBeTruthy()
    expect(button(w, 'Remove answer'), 'a Remove answer button').toBeTruthy()
  })

  it('hides group 15 when there are no answers', async () => {
    const w = await mountDetails()
    expect(w.text()).not.toContain('Answers you gave to application questions')
  })
})
