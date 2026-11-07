// Q-71 lane F (Profile -> Application details form), one block per audit item
// (docs/reviews/Q-71-details-form-audit.md). Fake server below; no network.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import ApplicationDetails from '../src/components/ApplicationDetails.vue'
import FieldInput from '../src/components/FieldInput.vue'
import { isFilled, newSkills, parseNumberText, pruneBlankEntries, remapErrors } from '../src/applicantForm.js'

// ---- payloads (synthetic data only)

const item = (path, label, kind, flags = {}, extra = {}) => ({
  path, label, kind, options: [], help: '', sub: [], required: false, recommended: false, sensitive: false,
  ...flags, ...extra,
})
const COUNTRIES = [{ value: 'SG', label: 'Singapore (SG)' }, { value: 'US', label: 'United States (US)' }]
const EDU = [
  { path: 'institution', label: 'School', kind: 'text' },
  { path: 'degree', label: 'Degree', kind: 'text' },
  { path: 'end', label: 'End', kind: 'text' },
]
const group = (id, title, items, extra = {}) => ({ id, title, note: '', items, sensitive: false, ...extra })

const FORM = [
  group('contact', 'Contact', [
    item('contact.email', 'Email for applications', 'email', { required: true, sensitive: true, autocomplete: 'email' }),
    item('contact.phone_country_code', 'Phone code', 'phone_cc', { autocomplete: 'tel-country-code' }),
    item('contact.city', 'City', 'text', { required: true }),
    item('contact.country', 'Country', 'country', { required: true, options: COUNTRIES, autocomplete: 'country' }),
  ]),
  group('links', 'Links', [item('links.linkedin', 'LinkedIn', 'url', { autocomplete: 'url' })]),
  group('education', 'Education', [item('education', 'Education', 'entries', { required: true, entry_label: 'School', sub: EDU })]),
  group('pay', 'Pay', [item('pay.expected_salary', 'Expected salary', 'salary', { required: true })]),
  group('skills', 'Skills', [item('skills', 'Skills', 'list_text')]),
  group('experience', 'Experience', [item('experience', 'Experience', 'entries', {
    entry_label: 'Job', sub: [{ path: 'company', label: 'Company', kind: 'text' }, { path: 'title', label: 'Job title', kind: 'text' }],
  })]),
  group('availability', 'Availability', [item('availability.earliest_start_date', 'Earliest start date', 'date')]),
  group('singapore_status', 'Singapore status', [
    item('singapore_status.race', 'Race', 'enum', {}, { options: [['indian', 'Indian'], ['other', 'Other']] }),
    item('singapore_status.race_other', 'Race (other)', 'text', {}, { show_when: { path: 'singapore_status.race', values: ['other'] } }),
  ]),
  group('declarations', 'Declarations', [
    item('declarations.shareholding_in_company', 'Do you hold shares in the company?', 'bool', {}, { control: 'yes_no' }),
    item('declarations.holdings', 'Holdings', 'list_text', {}, { show_when: { path: 'declarations.shareholding_in_company', values: [true] } }),
  ]),
  group('identity', 'Identity papers', [
    item('identity.date_of_birth', 'Date of birth', 'date', { sensitive: true }),
    item('identity.passport', 'Passport number', 'text', { sensitive: true }),
  ], { sensitive: true }),
  group('documents', 'Files', [
    item('documents.resume', 'Resume file', 'text'),
    item('documents.transcript', 'Transcript file', 'text'),
  ]),
]

const MISSING = ['contact.email', 'contact.city', 'pay.expected_salary']

function payload(over = {}) {
  return {
    profile: {
      contact: { email: '', city: '', country: 'SG', phone_country_code: '+65' },
      education: [{ institution: 'NUS', degree: 'BEng', end: '2026-05' }],
      pay: { expected_salary: null }, skills: ['Python'], singapore_status: { race: 'indian' },
      declarations: { shareholding_in_company: null }, availability: { earliest_start_date: '' },
    },
    etag: 'aaaaaaaaaaaaaaaa', errors: [], missing: MISSING, completeness: { filled: 3, needed: 6 },
    from_resume: [], sensitive: ['contact.email', 'identity.date_of_birth', 'identity.passport'],
    form: FORM, file: { exists: true, has_comments: false, error: '' },
    ...over,
  }
}
const withProfile = (patch, over = {}) => {
  const p = payload()
  Object.assign(p.profile, patch)
  return { ...p, ...over }
}

function reply(body, status = 200) {
  return {
    ok: status >= 200 && status < 300, status,
    statusText: { 200: 'OK', 404: 'Not Found', 409: 'Conflict', 422: 'Unprocessable Entity' }[status] ?? 'Error',
    json: async () => JSON.parse(JSON.stringify(body ?? {})),
  }
}

// check: (body) => {errors} | null (404). derived: GET api/profile body, or null (404).
function fakeServer({ applicant = payload(), put = null, check = null, derived = null } = {}) {
  const calls = []
  const fetch = vi.fn(async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase()
    const path = String(url).replace(/^\/?/, '')
    const body = init.body ? JSON.parse(init.body) : undefined
    calls.push({ method, url: path, body })
    if (path === 'api/applicant' && method === 'GET') return reply(applicant)
    if (path === 'api/applicant' && method === 'PUT') {
      const r = put ? put(body) : { status: 200, body: { ...applicant, profile: body.profile, etag: 'bbbbbbbbbbbbbbbb', missing: [] } }
      return reply(r.body, r.status)
    }
    if (path === 'api/applicant/check' && method === 'POST') {
      const r = check ? check(body) : null
      return r ? reply(r) : reply({ detail: 'Not Found' }, 404)
    }
    if (path === 'api/profile') return derived ? reply(derived) : reply({ detail: 'Not Found' }, 404)
    if (path.startsWith('api/questions')) return reply({ mode: 'dry_run', groups: [], ready: [], waiting: [], busy: false })
    return reply({ detail: 'Not Found' }, 404)
  })
  return { fetch, calls }
}

let server
async function mountDetails(opts = {}) {
  server = fakeServer(opts)
  vi.stubGlobal('fetch', server.fetch)
  const wrapper = mount(ApplicationDetails, { attachTo: document.body })
  await flushPromises()
  await flushPromises()
  return wrapper
}

const puts = () => server.calls.filter(c => c.method === 'PUT' && c.url === 'api/applicant')
const checks = () => server.calls.filter(c => c.url === 'api/applicant/check')
const button = (w, text) => w.findAll('button').find(b => b.text().replace(/\s+/g, ' ').trim() === text)
const field = (w, path) => w.find(`.field[data-path="${path}"]`)
const input = (w, path) => w.find(`#f-${path.replace(/[^a-z0-9]+/gi, '-')}-in`)
const save = async w => { await button(w, 'Save details').trigger('click'); await flushPromises() }

beforeEach(() => { window.localStorage.clear(); window.sessionStorage.clear() })
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals() })
enableAutoUnmount(afterEach)

// ---------------------------------------------------------------- Q71-02 country

describe('Q71-02 country is a list', () => {
  it('a country with options is a select that saves the code', async () => {
    const w = await mountDetails()
    const sel = input(w, 'contact.country')
    expect(sel.element.tagName).toBe('SELECT')
    expect(sel.findAll('option').map(o => o.text())).toEqual(['Choose…', 'Singapore (SG)', 'United States (US)'])
    expect(sel.element.value).toBe('SG')
    await sel.setValue('US')
    await save(w)
    expect(puts()).toHaveLength(1)
    expect(puts()[0].body.profile.contact.country).toBe('US')
  })

  it('without a list it is a code box with no maxlength and the hint', () => {
    const w = mount(FieldInput, { props: { kind: 'country', id: 'f-c', modelValue: 'sg' } })
    const box = w.find('#f-c')
    expect(box.element.tagName).toBe('INPUT')
    expect(box.attributes('maxlength')).toBeUndefined()
    expect(w.text()).toContain('2-letter code, e.g. SG for Singapore')
  })

  it('the work-rights map picks countries from a list, and a new row says "Choose a country"', async () => {
    const w = mount(FieldInput, {
      props: { kind: 'country_bool_map', id: 'f-m', modelValue: { default: false }, countryOptions: COUNTRIES },
    })
    await w.findAll('button').find(b => /add/i.test(b.text())).trigger('click')
    expect(w.text()).toContain('Choose a country')
    const sel = w.find('#f-m-code-0')
    expect(sel.element.tagName).toBe('SELECT')
    await sel.setValue('US')
    expect(w.text()).not.toContain('Choose a country')
    expect(w.emitted('update:modelValue').at(-1)).toEqual([{ US: false, default: false }])
  })

  it('warns, without blocking, when the country is not Singapore but the phone code is +65', async () => {
    const w = await mountDetails()
    expect(field(w, 'contact.country').text()).not.toContain('phone code')
    await input(w, 'contact.country').setValue('US')
    expect(field(w, 'contact.country').find('.field-warn').text()).toBe('Your country is United States, but your phone code is +65. Is that right?')
    await save(w)
    expect(puts()).toHaveLength(1)
  })
})

// ---------------------------------------------------------------- Q71-03 error summary

describe('Q71-03 error summary with Go to', () => {
  const invalid = () => ({
    status: 422,
    body: { detail: 'invalid', errors: [
      { path: 'contact.email', message: 'is not a valid email' },
      { path: 'education[0].degree', message: 'is required' },
    ] },
  })

  it('lists every error, focuses the banner, and each Go to focuses its field', async () => {
    const w = await mountDetails({ put: invalid })
    await input(w, 'contact.city').setValue('Singapore')
    await save(w)

    const banner = w.find('.banner.invalid')
    expect(banner.text()).toContain('2 details need fixing before you can save')
    const rows = banner.findAll('.summary-list li').map(li => li.text().replace(/\s+/g, ' '))
    expect(rows[0]).toContain('Email for applications: is not a valid email')
    expect(rows[1]).toContain('School 1 · Degree: is required')
    expect(document.activeElement).toBe(banner.element)

    const gos = banner.findAll('button.go')
    expect(gos).toHaveLength(2)
    await gos[0].trigger('click')
    expect(document.activeElement.id).toBe('f-contact-email-in')
    await gos[1].trigger('click')
    expect(document.activeElement.id).toBe('f-education-in-0-degree')
  })

  it('a field fixed on blur drops off the summary', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    const w = await mountDetails({
      put: invalid,
      check: body => ({ errors: body.profile.contact.email === 'a@b.co' ? [] : [{ path: 'contact.email', message: 'is not a valid email' }] }),
    })
    await input(w, 'contact.city').setValue('Singapore')
    await save(w)
    expect(w.findAll('.summary-list li')).toHaveLength(2)
    await input(w, 'contact.email').setValue('a@b.co')
    await field(w, 'contact.email').trigger('focusout')
    await vi.advanceTimersByTimeAsync(400)
    await flushPromises()
    expect(w.find('.banner').text()).toContain('1 detail needs fixing before you can save')
    expect(w.findAll('.summary-list li')).toHaveLength(1)
  })
})

// ---------------------------------------------------------------- Q71-04 blank entries

describe('Q71-04 blank entries are pruned', () => {
  it('Add school then Save sends no blank entry, and the row stays on screen', async () => {
    const w = await mountDetails()
    await button(w, 'Add school').trigger('click')
    await flushPromises()
    expect(w.findAll('.field[data-path="education"] fieldset.entry')).toHaveLength(2)
    await input(w, 'contact.city').setValue('Singapore')
    await save(w)
    expect(puts()).toHaveLength(1)
    expect(puts()[0].body.profile.education).toEqual([{ institution: 'NUS', degree: 'BEng', end: '2026-05' }])
  })

  it('pruneBlankEntries keeps resume entries and half-filled ones, and remapErrors maps paths back', () => {
    const profile = {
      education: [{ institution: '', degree: '', end: '' }, { institution: 'NUS', degree: '', end: '' }, { institution: '', from_resume: true }],
      languages: [{ language: '' }], skills: [],
    }
    const { profile: out, kept } = pruneBlankEntries(profile)
    expect(out.education).toEqual([{ institution: 'NUS', degree: '', end: '' }, { institution: '', from_resume: true }])
    expect(out.languages).toEqual([])
    expect(kept).toEqual({ education: [1, 2], languages: [] })
    expect(out.skills).toEqual([])
    expect(profile.education).toHaveLength(3)                       // the draft itself is untouched
    expect(remapErrors([{ path: 'education[0].degree', message: 'x' }, { path: 'contact.email', message: 'y' }], kept))
      .toEqual([{ path: 'education[1].degree', message: 'x' }, { path: 'contact.email', message: 'y' }])
  })
})
// ---------------------------------------------------------------- Q71-05 numbers as text

describe('Q71-05 numbers are text boxes that read "4,500"', () => {
  it('"4,500" in the expected salary saves 4500', async () => {
    const w = await mountDetails()
    const amount = input(w, 'pay.expected_salary')
    expect(amount.attributes('type')).toBe('text')
    await amount.setValue('4,500')
    expect(amount.element.value).toBe('4,500')                       // not rewritten under the cursor
    await save(w)
    expect(puts()[0].body.profile.pay.expected_salary).toEqual({ amount: 4500, currency: 'SGD', period: 'monthly' })
  })

  it('parseNumberText: separators and currency marks go, other text is kept as typed', () => {
    expect(parseNumberText('4,500')).toBe(4500)
    expect(parseNumberText('4 500')).toBe(4500)
    expect(parseNumberText('S$4500')).toBe(4500)
    expect(parseNumberText('$4,500')).toBe(4500)
    expect(parseNumberText('45k')).toBe('45k')
    expect(parseNumberText('')).toBeNull()
    expect(parseNumberText('   ')).toBeNull()
    expect(parseNumberText('4500.50')).toBe('4500.50')                    // whole numbers only by default
    expect(parseNumberText('4500.50', { decimals: true })).toBe(4500.5)
  })

  it('an int box emits 4500 for "4,500", the typed text for "45k"; a number box allows decimals', async () => {
    const int = mount(FieldInput, { props: { kind: 'int', id: 'f-i', modelValue: null } })
    await int.find('#f-i').setValue('4,500')
    await int.find('#f-i').setValue('45k')
    await int.find('#f-i').setValue('')
    expect(int.emitted('update:modelValue')).toEqual([[4500], ['45k'], [null]])
    const num = mount(FieldInput, { props: { kind: 'number', id: 'f-n', modelValue: null } })
    await num.find('#f-n').setValue('4500.50')
    expect(num.emitted('update:modelValue')).toEqual([[4500.5]])
  })
})

// ---------------------------------------------------------------- Q71-06 live Needed

describe('Q71-06 Needed clears as the owner types', () => {
  it('typing an amount removes Needed before saving; clearing it brings it back', async () => {
    const w = await mountDetails()
    expect(field(w, 'pay.expected_salary').find('.tag.needed').exists()).toBe(true)
    await input(w, 'pay.expected_salary').setValue('4200')
    expect(field(w, 'pay.expected_salary').find('.tag.needed').exists()).toBe(false)
    await input(w, 'pay.expected_salary').setValue('')
    expect(field(w, 'pay.expected_salary').find('.tag.needed').exists()).toBe(true)
    await input(w, 'contact.city').setValue('Singapore')
    expect(field(w, 'contact.city').find('.tag.needed').exists()).toBe(false)
    expect(puts()).toHaveLength(0)
  })

  it('isFilled mirrors the server: salary needs a whole amount above 0, education a complete entry, a consent a Yes', () => {
    const sal = { kind: 'salary', path: 'pay.expected_salary' }
    expect(isFilled(sal, { amount: 4200 })).toBe(true)
    expect(isFilled(sal, { amount: 0 })).toBe(false)
    expect(isFilled(sal, { amount: '4200' })).toBe(false)
    expect(isFilled(sal, {})).toBe(false)
    const edu = { kind: 'entries', path: 'education' }
    expect(isFilled(edu, [{ institution: 'NUS', degree: 'BEng', end: '' }])).toBe(false)
    expect(isFilled(edu, [{ institution: 'NUS', degree: 'BEng', end: '2026-05' }])).toBe(true)
    const consent = { kind: 'bool', path: 'consents.privacy_consent', required: true }
    expect(isFilled(consent, false)).toBe(false)
    expect(isFilled(consent, true)).toBe(true)
    expect(isFilled({ kind: 'list_text', path: 'skills' }, [])).toBe(false)
  })
})

// ---------------------------------------------------------------- Q71-07 / 11 entries

describe('Q71-07 an edited resume entry is the owner\'s now', () => {
  it('editing emits from_resume:false and the "please check" tag clears', async () => {
    const w = await mountDetails({
      applicant: withProfile(
        { education: [{ institution: 'NUS', degree: 'BEng', end: '2026-05', from_resume: true }] },
        { from_resume: ['education[0]'] },
      ),
    })
    const entry = field(w, 'education').find('fieldset.entry')
    expect(entry.find('.tag.resume').exists()).toBe(true)
    await w.find('#f-education-in-0-institution').setValue('NTU')
    expect(field(w, 'education').find('fieldset.entry .tag.resume').exists()).toBe(false)
    await input(w, 'contact.city').setValue('Singapore')
    await save(w)
    expect(puts()[0].body.profile.education[0]).toMatchObject({ institution: 'NTU', from_resume: false })
  })
})

describe('Q71-11 focus after Add', () => {
  it('Add school focuses the new entry\'s first field', async () => {
    const w = await mountDetails()
    await button(w, 'Add school').trigger('click')
    await flushPromises()
    expect(document.activeElement.id).toBe('f-education-in-1-institution')
  })
})

// ---------------------------------------------------------------- Q71-09 past date

describe('Q71-09 a start date in the past warns', () => {
  it('warns for a past date, not for a future one, and still saves', async () => {
    const w = await mountDetails()
    const warn = () => field(w, 'availability.earliest_start_date').find('.field-warn')
    expect(warn().exists()).toBe(false)
    await input(w, 'availability.earliest_start_date').setValue('2020-01-01')
    expect(warn().text()).toBe('This date has passed. Employers will read it as your start date.')
    await input(w, 'availability.earliest_start_date').setValue('2099-01-01')
    expect(warn().exists()).toBe(false)
    await input(w, 'availability.earliest_start_date').setValue('2020-01-01')
    await save(w)
    expect(puts()).toHaveLength(1)
  })
})

// ---------------------------------------------------------------- Q71-13 rail, Next needed

describe('Q71-13 section rail and Next needed', () => {
  it('lists every group with items, says what each needs, and jumps to the section', async () => {
    const w = await mountDetails()
    const links = w.findAll('nav[aria-label="Sections"] .rail-link')
    expect(links.map(l => l.attributes('data-section'))).toEqual(FORM.map(g => g.id))
    const byId = id => w.find(`nav[aria-label="Sections"] .rail-link[data-section="${id}"]`)
    expect(byId('contact').text()).toContain('2 needed')
    expect(byId('pay').text()).toContain('1 needed')
    expect(byId('education').find('.tag').exists()).toBe(false)
    expect(byId('education').text()).toContain('Nothing needed')
    expect(w.find('#g-contact').text()).toBe('Contact')
    expect(w.find('section[data-section="contact"] .section-tag').text()).toBe('2 needed')
    await byId('pay').trigger('click')
    expect(document.activeElement.id).toBe('g-pay')
  })

  it('a section with an error says "to fix" first', async () => {
    const w = await mountDetails({ put: () => ({ status: 422, body: { detail: 'invalid', errors: [{ path: 'contact.email', message: 'bad' }] } }) })
    await input(w, 'contact.city').setValue('Singapore')
    await save(w)
    expect(w.find('nav[aria-label="Sections"] .rail-link[data-section="contact"]').text()).toContain('1 to fix')
  })

  it('Next needed walks email, city, salary, then wraps', async () => {
    const w = await mountDetails()
    const next = () => w.find('button.next-needed')
    expect(next().text()).toBe('Next needed (3)')
    const order = []
    for (let i = 0; i < 4; i++) {
      await next().trigger('click')
      order.push(document.activeElement.id)
    }
    expect(order).toEqual(['f-contact-email-in', 'f-contact-city-in', 'f-pay-expected-salary-in', 'f-contact-email-in'])
    await input(w, 'contact.email').setValue('a@b.co')
    expect(next().text()).toBe('Next needed (2)')
  })
})

// ---------------------------------------------------------------- Q71-12 / 14 yes_no, show_when

describe('Q71-12 yes/no questions are radios', () => {
  it('control yes_no is a radiogroup named by its label, with "Not set"', async () => {
    const w = await mountDetails()
    const g = w.find('#f-declarations-shareholding-in-company-in')
    expect(g.attributes('role')).toBe('radiogroup')
    expect(g.attributes('aria-labelledby')).toBe('f-declarations-shareholding-in-company-label')
    expect(w.find('#f-declarations-shareholding-in-company-label').text()).toBe('Do you hold shares in the company?')
    expect(g.text()).toContain('Not set')
    expect(g.findAll('input[type="radio"]')).toHaveLength(2)
  })
})

describe('Q71-14 follow-up fields show only when they apply', () => {
  it('race "other" shows its box; indian hides it', async () => {
    const w = await mountDetails()
    expect(field(w, 'singapore_status.race_other').exists()).toBe(false)
    await input(w, 'singapore_status.race').setValue('other')
    expect(field(w, 'singapore_status.race_other').exists()).toBe(true)
    await input(w, 'singapore_status.race').setValue('indian')
    expect(field(w, 'singapore_status.race_other').exists()).toBe(false)
  })

  it('answering Yes shows Holdings', async () => {
    const w = await mountDetails()
    expect(field(w, 'declarations.holdings').exists()).toBe(false)
    await w.find('#f-declarations-shareholding-in-company-in input[type="radio"]').setValue(true)
    expect(field(w, 'declarations.holdings').exists()).toBe(true)
  })

  it('a follow-up that already holds a value stays visible, so a hidden value is never sent unseen', async () => {
    const w = await mountDetails({ applicant: withProfile({ singapore_status: { race: 'indian', race_other: 'Eurasian' } }) })
    expect(field(w, 'singapore_status.race_other').exists()).toBe(true)
    expect(input(w, 'singapore_status.race_other').element.value).toBe('Eurasian')
  })

  it('a follow-up with an error stays visible', async () => {
    const w = await mountDetails({
      applicant: withProfile({ singapore_status: { race: 'indian' } }, { errors: [{ path: 'singapore_status.race_other', message: 'bad' }] }),
    })
    expect(field(w, 'singapore_status.race_other').exists()).toBe(true)
  })
})

// ---------------------------------------------------------------- Q71-15 skills from the resume

describe('Q71-15 skills from the resume', () => {
  it('offers the resume skills not in the list yet and appends them', async () => {
    const w = await mountDetails({ derived: { present: true, skills: ['python', 'sql', 'machine learning'] } })
    const add = button(w, 'Add 2 skills from your resume')
    expect(add, 'the Add button').toBeTruthy()
    expect(field(w, 'skills').text()).toContain('SQL, Machine Learning')
    await add.trigger('click')
    await save(w)
    expect(puts()[0].body.profile.skills).toEqual(['Python', 'SQL', 'Machine Learning'])
  })

  it('is quiet when the profile call fails, and says Experience is not filled when it is empty', async () => {
    const w = await mountDetails()                                   // GET api/profile answers 404
    expect(w.text()).not.toContain('skills from your resume')
    expect(field(w, 'experience').text()).toContain("Experience isn't filled from your resume yet")
  })

  it('newSkills compares case-insensitively and labels all-lowercase tokens', () => {
    expect(newSkills(['python', 'SQL', 'sql', 'pytorch', 'PyTorch'], ['Python'])).toEqual(['SQL', 'Pytorch'])
  })
})

// ---------------------------------------------------------------- Q71-16 files

describe('Q71-16 which resume is in use', () => {
  const docs = (over = {}) => ({
    resume: { name: 'resume.pdf', size: 1000, modified: '2026-11-07T07:31:00+00:00' }, transcript: null, ...over,
  })

  it('names the file in use with its date, and sends go-view when "Upload in Resume and titles" is clicked', async () => {
    const w = await mountDetails({ applicant: payload({ documents_status: docs() }) })
    const line = field(w, 'documents.resume').find('.doc-line').text()
    expect(line).toContain('Using resume.pdf, uploaded 7 Nov 2026, 15:31')
    await field(w, 'documents.resume').find('button.upload').trigger('click')
    expect(w.emitted('go-view')).toEqual([['resume']])
  })

  it('says "No resume yet." and the Needed row offers the upload button', async () => {
    const w = await mountDetails({
      applicant: payload({ documents_status: docs({ resume: null }), missing: [...MISSING, 'documents.resume'] }),
    })
    expect(field(w, 'documents.resume').text()).toContain('No resume yet.')
    await w.find('.missing-list button.upload').trigger('click')
    expect(w.emitted('go-view')).toEqual([['resume']])
  })

  it('shows Found / Not found for a saved transcript path', async () => {
    const found = await mountDetails({
      applicant: withProfile({ documents: { transcript: 'transcript.pdf' } }, { documents_status: docs({ transcript: { name: 'transcript.pdf', size: 5, modified: '2026-11-07T07:31:00+00:00' } }) }),
    })
    expect(field(found, 'documents.transcript').find('.doc-found').text()).toBe('Found')
    const lost = await mountDetails({ applicant: withProfile({ documents: { transcript: 'transcript.pdf' } }, { documents_status: docs() }) })
    expect(field(lost, 'documents.transcript').find('.doc-found').text()).toBe('Not found')
  })

  it('without documents_status the form behaves as before: a plain path box', async () => {
    const w = await mountDetails()
    expect(field(w, 'documents.resume').find('.doc-status').exists()).toBe(false)
    expect(input(w, 'documents.resume').exists()).toBe(true)
  })
})

// ---------------------------------------------------------------- Q71-17 autocomplete

describe('Q71-17 autocomplete tokens', () => {
  it('passes the schema\'s token to the input; absent means off', async () => {
    const w = await mountDetails()
    expect(input(w, 'contact.email').attributes('autocomplete')).toBe('email')
    expect(input(w, 'contact.phone_country_code').attributes('autocomplete')).toBe('tel-country-code')
    expect(input(w, 'links.linkedin').attributes('autocomplete')).toBe('url')
    expect(input(w, 'contact.city').attributes('autocomplete')).toBe('off')
    expect(input(w, 'contact.country').attributes('autocomplete')).toBe('country')
  })
})

// ---------------------------------------------------------------- Q71-18 check on blur

describe('Q71-18 a field is checked when the owner leaves it', () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] }) })

  const leave = async (w, path) => {
    await field(w, path).trigger('focusout')
    await vi.advanceTimersByTimeAsync(400)
    await flushPromises()
  }

  it('shows the server\'s message under the field 400 ms after leaving it, with no banner', async () => {
    const w = await mountDetails({
      check: () => ({ errors: [{ path: 'contact.email', message: 'is not an email' }, { path: 'contact.city', message: 'untouched' }] }),
    })
    await input(w, 'contact.email').setValue('nope')
    await field(w, 'contact.email').trigger('focusout')
    await vi.advanceTimersByTimeAsync(300)
    expect(checks()).toHaveLength(0)                                 // not before 400 ms
    await vi.advanceTimersByTimeAsync(100)
    await flushPromises()
    expect(checks()).toHaveLength(1)
    expect(checks()[0].body.profile.contact.email).toBe('nope')
    expect(field(w, 'contact.email').find('.field-error').text()).toBe('is not an email')
    expect(field(w, 'contact.city').find('.field-error').exists()).toBe(false)   // only touched fields
    expect(w.find('.banner').exists()).toBe(false)
  })

  it('an untouched field is not checked on leaving', async () => {
    const w = await mountDetails({ check: () => ({ errors: [] }) })
    await leave(w, 'contact.city')
    expect(checks()).toHaveLength(0)
  })

  it('stops asking once the server has no check route', async () => {
    const w = await mountDetails()                                   // POST answers 404
    await input(w, 'contact.city').setValue('S')
    await leave(w, 'contact.city')
    await input(w, 'contact.city').setValue('Si')
    await leave(w, 'contact.city')
    expect(checks()).toHaveLength(1)
    expect(w.find('.field-error').exists()).toBe(false)
  })

  it('tidies on the way out: https:// on a link, +65 on a bare phone code, a trimmed email', async () => {
    const w = await mountDetails({ check: () => ({ errors: [] }) })
    await input(w, 'links.linkedin').setValue('linkedin.com/in/x')
    await leave(w, 'links.linkedin')
    expect(input(w, 'links.linkedin').element.value).toBe('https://linkedin.com/in/x')
    await input(w, 'contact.phone_country_code').setValue('65')
    await leave(w, 'contact.phone_country_code')
    expect(input(w, 'contact.phone_country_code').element.value).toBe('+65')
    await input(w, 'contact.email').setValue('  a@b.co ')
    await leave(w, 'contact.email')
    expect(input(w, 'contact.email').element.value).toBe('a@b.co')
  })
})

// ---------------------------------------------------------------- Q71-20 Private once

describe('Q71-20 "Private" is said once per section', () => {
  it('a fully private section has exactly one Private tag, and its fields carry the words for screen readers', async () => {
    const w = await mountDetails()
    const sec = w.find('section[data-section="identity"]')
    expect(sec.findAll('.tag.private')).toHaveLength(1)
    expect(sec.find('.tag.private').text()).toBe('Private: never sent to the AI')
    expect(sec.find('#f-identity-passport-private').text()).toBe('Private: never sent to the AI.')
    expect(input(w, 'identity.passport').attributes('aria-describedby')).toContain('f-identity-passport-private')
  })

  it('one private field among four is tagged on the field, not in the header', async () => {
    const w = await mountDetails()
    const tags = w.find('section[data-section="contact"]').findAll('.tag.private').map(t => t.text())
    expect(tags).toEqual(['Private'])
  })
})

// ---------------------------------------------------------------- 390px layout

describe('narrow layout: every grid track is minmax(0, 1fr)', () => {
  const src = readFileSync(resolve(process.cwd(), 'src/components/ApplicationDetails.vue'), 'utf8')
  const css = src.slice(src.indexOf('<style'))

  it('the details body, form and groups are single minmax(0, 1fr) columns below the wide breakpoint', () => {
    for (const sel of ['.app-details', '.details-body', '.the-form', '.group', '.field']) {
      const rule = new RegExp(`(^|\\n)${sel.replace('.', '\\.')}\\s*\\{[^}]*grid-template-columns:\\s*minmax\\(0,\\s*1fr\\)`)
      expect(css, `${sel} has a minmax(0, 1fr) column`).toMatch(rule)
    }
  })

  it('no track is a bare 1fr, which would grow to the widest field and push the page sideways', () => {
    const bare = [...css.matchAll(/grid-template-columns:\s*([^;]+);/g)].map(m => m[1])
      .filter(v => /(^|[\s,(])1fr/.test(v) && !/minmax\(/.test(v))
    expect(bare).toEqual([])
  })

  it('the rendered layout carries those classes', async () => {
    const w = await mountDetails()
    expect(w.find('.app-details .details-body.has-rail form.the-form').exists()).toBe(true)
    expect(w.find('.details-body > nav.details-rail').exists()).toBe(true)
  })
})