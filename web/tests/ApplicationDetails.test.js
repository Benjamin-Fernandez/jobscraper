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
    // Q-127 T0: the page is a list of collapsed sections, one open at a time. The server sends ONE
    // section holding every form item and mountDetails() opens it; grouping is pinned in q127-profile.test.js.
    const withSections = a => ({ ...a, sections: [{ id: 'all', title: 'All details', paths: (a.form || []).flatMap(g => g.items.map(i => i.path)) }] })
    if (path === 'api/applicant' && method === 'GET') return reply(withSections(state.applicant))
    if (path === 'api/applicant' && method === 'PUT') {
      const r = put ? put(body, state) : { status: 200, body: { ...state.applicant, profile: body.profile, etag: 'bbbbbbbbbbbbbbbb' } }
      if (r.status === 200) state.applicant = r.body
      return reply(r.status === 200 ? withSections(r.body) : r.body, r.status)
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
  const row = wrapper.find('#ds-all-button')
  if (row.exists()) { await row.trigger('click'); await flushPromises() }       // open the one section
  return wrapper
}

const button = (wrapper, text) => wrapper.findAll('button').find(b => b.text().trim() === text)
const countOf = (text, re) => (text.match(re) || []).length

beforeEach(() => { window.localStorage.clear(); window.sessionStorage.clear() })
afterEach(() => { vi.unstubAllGlobals() })
enableAutoUnmount(afterEach)

if (!PRESENT) {
  // visible in the run output: why this file runs nothing yet
  // eslint-disable-next-line no-console
  console.log('[ApplicationDetails.test] skipped: web/src/components/ApplicationDetails.vue is not built yet (WP-W5)')
}

suite('Needed before auto-apply', () => {
  // RETIRED (Q-127 T0): lists each missing field by its form label... : the Needed list is the status card now (q127-profile.test.js: status card, Fill in)

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

  // RETIRED (Q-127 T0): shows the meter as... : there is no meter; the status card says what auto-apply waits for (q127-profile.test.js)

})

suite('saving', () => {
  // RETIRED (Q-127 T0): PUTs {profile, etag} from the Save details bar... : the page-wide Save details bar is a per-section Save section (q127-profile.test.js: section save)

  it('a 422 shows the QD 10.2 sentence and the message beside the field, and keeps the edits', async () => {
    const w = await mountDetails({
      put: () => ({ status: 422, body: { detail: 'invalid', errors: [{ path: 'contact.postal_code', message: 'must be 6 digits' }] } }),
    })
    await w.find('#f-contact-city-in').setValue('Singapore')
    await w.find('.ds-save').trigger('click')
    await flushPromises()
    const text = w.text()
    expect(text).toContain('1 detail needs fixing before you can save')
    expect(text).toContain('Postal code: must be 6 digits')
    expect(text).toContain('must be 6 digits')
    expect(text).not.toContain('Saved.')
    // the inline message is tied to its input for screen readers (QD 10.3)
    const input = w.find('[aria-describedby]')
    expect(input.exists()).toBe(true)
  })

  it('a 409 "changed" explains why and offers Reload, which fetches the file again', async () => {
    const w = await mountDetails({ put: () => ({ status: 409, body: { detail: 'changed' } }) })
    await w.find('#f-contact-city-in').setValue('Singapore')
    await w.find('.ds-save').trigger('click')
    await flushPromises()
    expect(w.text()).toContain(
      'This file changed since you opened it, in another tab or by hand. Reload to take in the latest. What you typed here is kept.')
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
    expect(w.find('.ds-save').exists()).toBe(false)             // no section opens, so no save is offered
  })

  it('shows the comments note only when the file has comments', async () => {
    const note = 'Saving tidies your details file and removes its notes. A copy with your notes is kept.'
    const withComments = await mountDetails({ applicant: payload({ file: { exists: true, has_comments: true, error: '' } }) })
    expect(withComments.text()).toContain(note)
    const without = await mountDetails()
    expect(without.text()).not.toContain('applicant.commented-backup.yaml')
  })
})

suite('answers the owner gave (group 15) and other keys (group 16)', () => {
  // RETIRED (Q-127 T0): lists each `extra` entry with a Remove button... : the saved answers moved to Settings -> Answers you corrected (q127-saved-answers.test.js: list, Forget)

  it('hides group 15 when there are no answers', async () => {
    const w = await mountDetails()
    expect(w.text()).not.toContain('Answers you gave to application questions')
  })
})

// ---- Q-39 / Q-30 F2: unsaved edits survive a Questions-card save, per leaf ----
// The Questions card (QuestionsInbox) rewrites the file and emits `saved`; the form then reloads, takes the
// new etag and keeps only the leaves the owner changed (`mergeEdits`). The card's own POST is out of scope
// here (QuestionsInbox.test.js): the test changes what the fake GET returns and emits the card's `saved`.

const FORM_F2 = [
  { id: 'contact', title: 'Contact', note: '', items: [
    item('contact.email', 'Email for applications', 'email', { required: true, sensitive: true }),
    item('contact.city', 'City', 'text', { required: true }),
    item('contact.address_line1', 'Address line 1', 'text', { required: true }),
  ] },
]
const PROFILE_F2 = { contact: { email: 'a@example.com', city: 'SG' } }
const ETAG_FILE = 'cccccccccccccccc'

function f2Payload(profile, over = {}) {
  return payload({ profile, form: FORM_F2, missing: [], ...over })
}

const putsOf = () => server.calls.filter(c => c.method === 'PUT' && c.url === 'api/applicant')
const getsOf = () => server.calls.filter(c => c.method === 'GET' && c.url === 'api/applicant')

// The Questions card saved something: the file now holds `profile` under a new etag.
async function cardSaved(w, profile) {
  server.state.applicant = f2Payload(profile, { etag: ETAG_FILE })
  w.findComponent(QuestionsInbox).vm.$emit('saved', { etag: ETAG_FILE })
  await flushPromises()
}

// RETIRED (Q-127 T0): the suite 'F2: a Questions-card save keeps the owner...' went with the Questions card and the extra-answer Remove buttons.

// RETIRED (Q-127 T0): the suite 'F2: removing an answer says what else it saves...' went with the Questions card and the extra-answer Remove buttons.

// ---- Q-70 lane D (D-100): the unsaved form survives leaving the tab (sessionStorage), Discard, the 409 Reload ----
// Fake data only. The draft key is `jobscraper.applicant.draft`; the stored shape is {etag, base, draft}.

const DRAFT_KEY = 'jobscraper.applicant.draft'
const PROFILE_D = { contact: { email: 'alex.tan@example.com', city: 'Singapore' } }
const cityIn = w => w.find('#f-contact-city-in')
const emailIn = w => w.find('#f-contact-email-in')
const storedDraft = () => JSON.parse(window.sessionStorage.getItem(DRAFT_KEY))

suite('Q-70 D1: the draft survives leaving the Profile tab', () => {
  it('(a) an edit survives unmount + remount, shows the restored note, and Discard them goes back to the file', async () => {
    const w = await mountDetails({ applicant: f2Payload(PROFILE_D) })
    expect(w.find('.restored').exists()).toBe(false)
    await cityIn(w).setValue('Typed City')
    expect(storedDraft().draft.contact.city).toBe('Typed City')
    expect(storedDraft().etag).toBe('aaaaaaaaaaaaaaaa')
    w.unmount()

    const again = await mountDetails({ applicant: f2Payload(PROFILE_D) })
    expect(cityIn(again).element.value).toBe('Typed City')
    expect(again.find('.restored').exists()).toBe(true)
    expect(again.text()).toContain('Your unsaved changes are back.')
    expect(again.text()).toContain('Unsaved changes')

    await button(again, 'Discard them').trigger('click')
    await flushPromises()
    expect(cityIn(again).element.value).toBe('Singapore')
    expect(again.find('.restored').exists()).toBe(false)
    expect(window.sessionStorage.getItem(DRAFT_KEY)).toBeNull()
    expect(again.text()).not.toContain('Unsaved changes')
  })

  it('the draft lives in sessionStorage only, never localStorage (D-100)', async () => {
    const w = await mountDetails({ applicant: f2Payload(PROFILE_D) })
    await cityIn(w).setValue('Typed City')
    expect(window.sessionStorage.getItem(DRAFT_KEY)).not.toBeNull()
    expect(window.localStorage.getItem(DRAFT_KEY)).toBeNull()
    expect(window.localStorage.length).toBe(0)
  })

  it("typing the file's own value back removes the stored draft (it equals the file again)", async () => {
    const w = await mountDetails({ applicant: f2Payload(PROFILE_D) })
    await cityIn(w).setValue('Typed City')
    expect(window.sessionStorage.getItem(DRAFT_KEY)).not.toBeNull()
    await cityIn(w).setValue('Singapore')
    expect(window.sessionStorage.getItem(DRAFT_KEY)).toBeNull()
  })

  it('(b) a draft stored against an older etag merges per leaf into the newer file', async () => {
    window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify({
      etag: 'oldoldoldoldoldo',
      base: { contact: { email: 'alex.tan@example.com', city: 'Singapore' } },
      draft: { contact: { email: 'alex.tan@example.com', city: 'Typed City' } },
    }))
    const newer = f2Payload({ contact: { email: 'alex.new@example.com', city: 'Singapore' } }, { etag: ETAG_FILE })
    const w = await mountDetails({ applicant: newer })
    expect(cityIn(w).element.value).toBe('Typed City')                  // the leaf the owner changed
    expect(emailIn(w).element.value).toBe('alex.new@example.com')      // the leaf the file changed
    expect(w.find('.restored').exists()).toBe(true)
    await w.find('.ds-save').trigger('click')
    await flushPromises()
    expect(putsOf()).toHaveLength(1)
    expect(putsOf()[0].body.etag).toBe(ETAG_FILE)
    expect(putsOf()[0].body.profile.contact).toMatchObject({ email: 'alex.new@example.com', city: 'Typed City' })
  })

  it('a corrupt stored draft is ignored: the form shows the file and nothing is "restored"', async () => {
    window.sessionStorage.setItem(DRAFT_KEY, '{not json')
    const w = await mountDetails({ applicant: f2Payload(PROFILE_D) })
    expect(cityIn(w).element.value).toBe('Singapore')
    expect(w.find('.restored').exists()).toBe(false)
  })
})

suite('Q-70 D2/D3: unsaved marker, Saved. note, Discard changes, Save enabled state', () => {
  it('(c) after a save the next edit shows "Unsaved changes"', async () => {
    const w = await mountDetails({ applicant: f2Payload(PROFILE_D) })
    await cityIn(w).setValue('Typed City')
    await w.find('.ds-save').trigger('click')
    await flushPromises()
    expect(putsOf()).toHaveLength(1)
    expect(w.text()).not.toContain('Unsaved changes')
    const row = w.find('#ds-all-button')
    if (row.attributes('aria-expanded') !== 'true') { await row.trigger('click'); await flushPromises() }
    await cityIn(w).setValue('Another City')
    expect(w.text()).toContain('Unsaved changes')
  })

  it('(d) Save section is disabled until an edit; Cancel puts the file value back and closes the section', async () => {
    const w = await mountDetails({ applicant: f2Payload(PROFILE_D) })
    expect(w.find('.ds-save').attributes('disabled')).toBeDefined()
    await cityIn(w).setValue('Typed City')
    expect(w.find('.ds-save').attributes('disabled')).toBeUndefined()
    await w.find('.ds-cancel').trigger('click')
    await flushPromises()
    expect(w.find('.ds-save').exists()).toBe(false)
    expect(window.sessionStorage.getItem(DRAFT_KEY)).toBeNull()
    await w.find('#ds-all-button').trigger('click')
    await flushPromises()
    expect(cityIn(w).element.value).toBe('Singapore')
    expect(w.text()).not.toContain('Unsaved changes')
  })

  it('(d) Save details stays enabled when applicant.yaml does not exist yet, so it can be created', async () => {
    const w = await mountDetails({ applicant: f2Payload({}, { file: { exists: false, has_comments: false, error: '' } }) })
    expect(w.text()).toContain('Nothing saved yet. Your details stay on this computer.')
    expect(w.find('.ds-save').attributes('disabled')).toBeUndefined()
    await w.find('.ds-save').trigger('click')
    await flushPromises()
    expect(putsOf()).toHaveLength(1)
  })
})

suite('Q-70 D4: a 409 "changed" Reload keeps what was typed', () => {
  it("(e) Reload keeps the typed city, takes the file's newer email, and clears the conflict banner", async () => {
    const w = await mountDetails({
      applicant: f2Payload(PROFILE_D),
      put: () => ({ status: 409, body: { detail: 'changed' } }),
    })
    await cityIn(w).setValue('Typed City')
    await w.find('.ds-save').trigger('click')
    await flushPromises()
    expect(w.find('.conflict').exists()).toBe(true)
    expect(w.text()).toContain('What you typed here is kept.')

    // meanwhile the file changed by hand: a new email, a new etag
    server.state.applicant = f2Payload({ contact: { email: 'alex.new@example.com', city: 'Singapore' } }, { etag: ETAG_FILE })
    await button(w, 'Reload').trigger('click')
    await flushPromises()
    expect(w.find('.conflict').exists()).toBe(false)
    expect(cityIn(w).element.value).toBe('Typed City')
    expect(emailIn(w).element.value).toBe('alex.new@example.com')
    expect(w.text()).toContain('Unsaved changes')
  })

  it('an unreadable-file conflict still just reloads the file', async () => {
    const w = await mountDetails({
      applicant: f2Payload(PROFILE_D),
      put: () => ({ status: 409, body: { detail: 'unreadable' } }),
    })
    await cityIn(w).setValue('Typed City')
    await w.find('.ds-save').trigger('click')
    await flushPromises()
    expect(w.text()).toContain("JobScraper can't read data/applicant.yaml")
    const before = getsOf().length
    await button(w, 'Reload').trigger('click')
    await flushPromises()
    expect(getsOf().length).toBe(before + 1)
  })
})

suite('Q-70 D1: the beforeunload guard', () => {
  const fire = () => {
    const ev = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(ev)
    return ev
  }

  it('(f) is cancelled only while there are unsaved edits, and not after unmount', async () => {
    const w = await mountDetails({ applicant: f2Payload(PROFILE_D) })
    expect(fire().defaultPrevented).toBe(false)               // clean form: leave freely
    await cityIn(w).setValue('Typed City')
    expect(fire().defaultPrevented).toBe(true)                // dirty: ask first
    await w.find('.ds-cancel').trigger('click')
    await flushPromises()
    expect(fire().defaultPrevented).toBe(false)               // clean again
    await w.find('#ds-all-button').trigger('click')
    await flushPromises()
    await cityIn(w).setValue('Typed City')
    expect(fire().defaultPrevented).toBe(true)
    w.unmount()
    expect(fire().defaultPrevented).toBe(false)               // listener removed
  })
})

// Q-71: a profile with no pay.expected_salary used to render the field with no inputs at all.
const SALARY_FORM = [
  { id: 'pay', title: 'Pay', note: '', items: [
    item('pay.expected_salary', 'Expected salary', 'salary', { required: true }),
  ] },
]
const salaryPayload = profile => payload({
  profile, form: SALARY_FORM, missing: ['pay.expected_salary'], sensitive: [], completeness: { filled: 0, needed: 1 },
})

suite('Expected salary (Q-71)', () => {
  for (const [name, profile] of [['missing', { pay: {} }], ['absent with no pay section', {}], ['null', { pay: { expected_salary: null } }]]) {
    it(`shows the Amount input when pay.expected_salary is ${name}, and Save PUTs the amount`, async () => {
      const w = await mountDetails({ applicant: salaryPayload(profile) })
      const amount = w.find('#f-pay-expected-salary-in')
      expect(amount.exists(), 'the Amount input').toBe(true)
      expect(w.find('label[for="f-pay-expected-salary-in"]').text()).toBe('Amount')
      expect(w.find('#f-pay-expected-salary-in-currency').element.value).toBe('SGD')
      expect(w.find('#f-pay-expected-salary-in-period').element.value).toBe('monthly')
      expect(w.find('.ds-save').attributes('disabled')).toBeDefined()    // nothing changed yet
      // Untouched: nothing was written for the salary.
      expect(w.text()).toContain('Needed')

      await amount.setValue('4200')
      expect(w.find('.ds-save').attributes('disabled')).toBeUndefined()
      await w.find('.ds-save').trigger('click')
      await flushPromises()
      const puts = server.calls.filter(c => c.method === 'PUT' && c.url === 'api/applicant')
      expect(puts).toHaveLength(1)
      expect(puts[0].body.profile.pay.expected_salary).toEqual({ amount: 4200, currency: 'SGD', period: 'monthly' })
    })
  }

  it('an untouched missing salary is not written on the way through', async () => {
    const w = await mountDetails({ applicant: salaryPayload({ pay: {} }) })
    expect(w.find('#f-pay-expected-salary-in').element.value).toBe('')
    expect(w.find('.ds-save').attributes('disabled')).toBeDefined()    // untouched: nothing to save
    const puts = server.calls.filter(c => c.method === 'PUT' && c.url === 'api/applicant')
    expect(puts.every(p => !p.body.profile.pay?.expected_salary)).toBe(true)
  })
})
