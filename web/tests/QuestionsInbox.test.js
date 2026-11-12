// WP-Q0 oracles for "Questions from applications" (questions_design.md 9.2, 10.1-10.3; WP-Q4).
//
// Skip-clean: `web/src/components/QuestionsInbox.vue` does not exist until lane U builds it. The suite is
// `describe.skip` while the file is absent (import.meta.glob finds nothing); `npx vitest run` stays green and
// the tests start running when the component lands. Same convention as h1.test.js's it.skip.
//
// ASSUMED component contract (change `mountInbox` / the fake if lane U decides otherwise):
//   * `mount(QuestionsInbox)` with no props; on mount it GETs `api/questions?status=open` (QD 9.2) and, for
//     the etag it must send back, `api/applicant`. It POSTs `api/questions/answer`, `api/questions/<key>/dismiss`
//     and `api/questions/retry`. (Inside ApplicationDetails it may take the etag from its parent; the test
//     answers `api/applicant` either way.)
//   * "Save answer" / "I'll answer this one by hand" / "Retry <n> applications" are <button>s with the QD 10.2
//     text; a choice variant is a <select>; yes/no are two radio inputs; the scope control is a <select>.
//   * Toasts go through web/src/toast.js (`toast.current.message`).
//   * Copy is asserted on `wrapper.text()` / the toast, not on markup.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { dismissToast, toast } from '../src/toast.js'

const loaders = import.meta.glob('../src/components/QuestionsInbox.vue')
const PRESENT = Object.keys(loaders).length > 0
const suite = PRESENT ? describe : describe.skip

// ---- payloads (QD 9.2 shapes; synthetic employer text only)

const group = (over = {}) => ({
  key: 'visa_status', title: 'Visa status', description: '', kind: 'choice', sensitive: false,
  target_path: '', status: 'open', named_by: 'rule', reason: 'no_rule',
  labels: ['What is your visa status?'], employers: ['Shopee', 'Grab'], waiting: 2,
  first_seen_at: '2026-11-02T10:00:00', last_seen_at: '2026-11-02T10:00:00',
  variants: [{ question_id: 11, label: 'What is your visa status?',
    options: [{ label: 'Citizen', norm: 'citizen' }, { label: 'PR', norm: 'pr' }, { label: 'Others', norm: 'others' }] }],
  ...over,
})

const questions = (groups, over = {}) => ({
  mode: 'dry_run', groups, ready: [], waiting: [], busy: false, ...over,
})

const APPLICANT = { profile: {}, etag: 'aaaaaaaaaaaaaaaa', errors: [], missing: [], completeness: { filled: 1, needed: 2 },
  from_resume: [], sensitive: [], form: [], file: { exists: true, has_comments: false, error: '' } }

function reply(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: { 200: 'OK', 202: 'Accepted', 204: 'No Content', 404: 'Not Found', 409: 'Conflict', 422: 'Unprocessable Entity' }[status] ?? 'Error',
    json: async () => JSON.parse(JSON.stringify(body ?? {})),
  }
}

function fakeServer(payload, { answer = null, retry = null } = {}) {
  const calls = []
  const fetch = vi.fn(async (url, init = {}) => {
    const method = (init.method || 'GET').toUpperCase()
    const path = String(url).replace(/^\/?/, '')
    const body = init.body ? JSON.parse(init.body) : undefined
    calls.push({ method, url: path, body })
    if (path.startsWith('api/questions?') && method === 'GET') return reply(payload)
    if (path === 'api/applicant' && method === 'GET') return reply(APPLICANT)
    if (path === 'api/questions/answer') return answer ? reply(...answer(body)) : reply({ answered: [11], ready: [], etag: 'bbbbbbbbbbbbbbbb' })
    if (path === 'api/questions/retry') return retry ? reply(...retry(body)) : reply({ job: { id: 'j1', kind: 'apply', state: 'running' } }, 202)
    if (/^api\/questions\/[^/]+\/dismiss$/.test(path)) return reply({}, 204)
    return reply({ detail: 'Not Found' }, 404)
  })
  return { fetch, calls }
}

let server
async function mountInbox(payload, opts) {
  const Inbox = (await loaders['../src/components/QuestionsInbox.vue']()).default
  server = fakeServer(payload, opts)
  vi.stubGlobal('fetch', server.fetch)
  const wrapper = mount(Inbox)
  await flushPromises()
  return wrapper
}

const button = (wrapper, text) => wrapper.findAll('button').find(b => b.text().trim() === text)
const startsWith = (wrapper, text) => wrapper.findAll('button').find(b => b.text().trim().startsWith(text))
const answers = () => server.calls.filter(c => c.method === 'POST' && c.url === 'api/questions/answer')

beforeEach(() => { dismissToast() })
afterEach(() => { vi.unstubAllGlobals(); dismissToast() })
enableAutoUnmount(afterEach)

if (!PRESENT) {
  // eslint-disable-next-line no-console
  console.log('[QuestionsInbox.test] skipped: web/src/components/QuestionsInbox.vue is not built yet (WP-Q4)')
}

suite('the card', () => {
  it('shows the heading, the intro and a meta line naming the employers and the applications waiting', async () => {
    const w = await mountInbox(questions([group()]))
    const text = w.text()
    expect(text).toContain('Questions from applications')
    expect(text).toContain("Employers asked these, and JobScraper had no answer it could back up. Answer once and it's used on every application that asks.")
    expect(text).toContain('Asked by Shopee, Grab · 2 applications waiting')
  })

  it('says "1 application waiting" for one, and drops the second part for none', async () => {
    const one = await mountInbox(questions([group({ waiting: 1 })]))
    expect(one.text()).toContain('Asked by Shopee, Grab · 1 application waiting')
    const none = await mountInbox(questions([group({ waiting: 0 })]))
    expect(none.text()).toContain('Asked by Shopee, Grab')
    expect(none.text()).not.toContain('waiting')
  })

  it('lists every verbatim label of the group under "Also asked as"', async () => {
    const g = group({ labels: ['What is your visa status?', 'Current work pass type'] })
    const w = await mountInbox(questions([g]))
    expect(w.text()).toContain('Also asked as')
    expect(w.text()).toContain('“What is your visa status?”')
    expect(w.text()).toContain('“Current work pass type”')
  })

  it('shows the reason as a chip with the QD 10.2 wording', async () => {
    const chips = {
      no_rule: 'Not in your profile',
      ungrounded: "The AI's answer couldn't be checked against your details",
      profile_gap: 'Missing from your profile',
      no_option_fits: "Your saved answer isn't one of this form's options",
      attestation_unclear: "A declaration JobScraper couldn't classify",
      conflict: 'Your work rights differ between the countries asked',
    }
    for (const [reason, copy] of Object.entries(chips)) {
      const w = await mountInbox(questions([group({ reason })]))
      expect(w.text(), reason).toContain(copy)
    }
  })

  it('tags a sensitive question "Private: never sent to the AI" in words, not colour alone', async () => {
    const w = await mountInbox(questions([group({ sensitive: true })]))
    expect(w.text()).toContain('Private: never sent to the AI')
    const plain = await mountInbox(questions([group({ sensitive: false })]))
    expect(plain.text()).not.toContain('Private: never sent to the AI')
  })

  it('a profile-gap question says it is a profile field and where the answer is saved', async () => {
    const g = group({ key: 'availability.notice_period_days', title: 'Notice period, in days', kind: 'number',
      target_path: 'availability.notice_period_days', named_by: 'profile', reason: 'profile_gap', variants: [
        { question_id: 21, label: 'Notice period', options: [] }], labels: ['Notice period'] })
    const w = await mountInbox(questions([g]))
    expect(w.text()).toContain("This is your profile's Notice period, in days. Your answer is saved there.")
  })
})

suite('widgets', () => {
  it('a choice group has one picker per option set, labelled with the employer', async () => {
    const g = group({ variants: [
      { question_id: 11, label: 'What is your visa status?', options: [{ label: 'Citizen', norm: 'citizen' }, { label: 'PR', norm: 'pr' }] },
      { question_id: 12, label: 'Current work pass type', options: [{ label: 'EP', norm: 'ep' }, { label: 'S Pass', norm: 's pass' }] },
    ], labels: ['What is your visa status?', 'Current work pass type'] })
    const w = await mountInbox(questions([g]))
    const selects = w.findAll('select').filter(s => s.findAll('option').some(o => ['Citizen', 'EP'].includes(o.text().trim())))
    expect(selects).toHaveLength(2)
    expect(selects[0].findAll('option').map(o => o.text().trim())).toEqual(expect.arrayContaining(['Citizen', 'PR']))
    expect(selects[1].findAll('option').map(o => o.text().trim())).toEqual(expect.arrayContaining(['EP', 'S Pass']))
  })

  it('a yes/no group is two radio buttons, Yes and No', async () => {
    const g = group({ key: 'has_driving_licence', title: 'Driving licence', kind: 'yes_no', labels: ['Do you hold a valid driving licence?'],
      variants: [{ question_id: 31, label: 'Do you hold a valid driving licence?', options: [] }] })
    const w = await mountInbox(questions([g]))
    const radios = w.findAll('input[type="radio"]')
    expect(radios).toHaveLength(2)
    expect(w.text()).toContain('Yes')
    expect(w.text()).toContain('No')
  })

  it('the scope control offers All employers first, then each employer of the group', async () => {
    const w = await mountInbox(questions([group()]))
    expect(w.text()).toContain('Use this answer for:')
    const scope = w.findAll('select').find(s => s.findAll('option').some(o => o.text().trim() === 'All employers'))
    expect(scope, 'a scope select').toBeTruthy()
    expect(scope.findAll('option').map(o => o.text().trim())).toEqual(['All employers', 'Shopee', 'Grab'])
  })
})

suite('saving, dismissing, retrying', () => {
  it('Save answer POSTs the QD 9.2 shape: key, etag, picks keyed by question id (verbatim labels)', async () => {
    const w = await mountInbox(questions([group()]))
    const select = w.findAll('select').find(s => s.findAll('option').some(o => o.text().trim() === 'Citizen'))
    await select.setValue(select.findAll('option').find(o => o.text().trim() === 'Citizen').element.value)
    await button(w, 'Save answer').trigger('click')
    await flushPromises()
    expect(answers()).toHaveLength(1)
    const body = answers()[0].body
    expect(body.key).toBe('visa_status')
    expect(body.etag).toBe('aaaaaaaaaaaaaaaa')
    expect(body.picks).toEqual({ 11: ['Citizen'] })
    expect(body.employer == null).toBe(true)
    expect('value' in body).toBe(false)
    expect(toast.current?.message).toBe('Saved. JobScraper will use this answer from now on.')
  })

  it('a scoped answer sends the employer', async () => {
    const w = await mountInbox(questions([group()]))
    const scope = w.findAll('select').find(s => s.findAll('option').some(o => o.text().trim() === 'All employers'))
    await scope.setValue(scope.findAll('option').find(o => o.text().trim() === 'Shopee').element.value)
    const picker = w.findAll('select').find(s => s.findAll('option').some(o => o.text().trim() === 'PR'))
    await picker.setValue(picker.findAll('option').find(o => o.text().trim() === 'PR').element.value)
    await button(w, 'Save answer').trigger('click')
    await flushPromises()
    expect(answers()[0].body.employer).toBe('Shopee')
  })

  it('a text question sends `value`, not picks', async () => {
    const g = group({ key: 'favourite_language', title: 'Favourite language', kind: 'text',
      labels: ['What is your favourite programming language?'],
      variants: [{ question_id: 41, label: 'What is your favourite programming language?', options: [] }] })
    const w = await mountInbox(questions([g]))
    await w.find('textarea').setValue('Python')
    await button(w, 'Save answer').trigger('click')
    await flushPromises()
    const body = answers()[0].body
    expect(body.key).toBe('favourite_language')
    expect(body.value).toBe('Python')
    expect('picks' in body).toBe(false)
  })

  it('"I\'ll answer this one by hand" dismisses the group and says what happens next', async () => {
    const w = await mountInbox(questions([group()]))
    await button(w, "I'll answer this one by hand").trigger('click')
    await flushPromises()
    expect(server.calls.some(c => c.method === 'POST' && c.url === 'api/questions/visa_status/dismiss')).toBe(true)
    expect(toast.current?.message).toBe('Okay. Applications that ask this will stop there, so you can finish them by hand.')
  })

  it('a 422 keeps the card open and says what is wrong', async () => {
    const w = await mountInbox(questions([group()]), {
      answer: () => [{ detail: 'invalid', errors: [{ path: 'extra.visa_status.picks', message: 'pick one of the options' }] }, 422],
    })
    const select = w.findAll('select').find(s => s.findAll('option').some(o => o.text().trim() === 'Citizen'))
    await select.setValue(select.findAll('option').find(o => o.text().trim() === 'Citizen').element.value)
    await button(w, 'Save answer').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('pick one of the options')
    expect(w.text()).toContain('Visa status')
  })
})

suite('ready applications and the retry confirm', () => {
  const READY = [{ job_id: 'j1', attempt_id: 5, company: 'Shopee', title: 'Software Engineer' },
    { job_id: 'j2', attempt_id: 6, company: 'Grab', title: 'Data Engineer' }]

  // Q-120 U1: a retry adds the roles to the auto-apply queue; the 202 body says what happened.
  const QUEUED = () => [{ queued: [{ job_id: 'j1', position: 1 }, { job_id: 'j2', position: 2 }], started: false, mode: 'dry_run', refused: [] }, 202]

  it('shows the ready banner with a Retry button that posts the ready job ids, no confirm in dry run', async () => {
    const w = await mountInbox(questions([], { ready: READY, mode: 'dry_run' }), { retry: QUEUED })
    expect(w.text()).toContain('2 applications can go again now.')
    const retry = startsWith(w, 'Retry 2 applications')
    expect(retry, 'a Retry 2 applications button').toBeTruthy()
    await retry.trigger('click')
    await flushPromises()
    const post = server.calls.find(c => c.method === 'POST' && c.url === 'api/questions/retry')
    expect(post.body).toEqual({ job_ids: ['j1', 'j2'] })
    expect(w.text()).not.toContain('Send 2 applications now?')
    // QD 10.2: the outcome is a toast (toast.js), not inline text. Q-120: it says what the
    // queue did with them, never that the work has started when it has not.
    expect(toast.current?.message).toBe('Added 2 to the auto-apply queue.')
  })

  it('Q-70 D6 / Q-120: the retry toast links to the queue in Runs, and tells the queue to re-read', async () => {
    const heard = vi.fn()
    window.addEventListener('jobscraper:apply-queue', heard)
    try {
      const w = await mountInbox(questions([], { ready: READY, mode: 'dry_run' }), { retry: QUEUED })
      await startsWith(w, 'Retry 2 applications').trigger('click')
      await flushPromises()
      expect(toast.current?.link).toEqual({ label: 'See the queue', href: '#/runs' })
      expect(heard).toHaveBeenCalledTimes(1)
    } finally {
      window.removeEventListener('jobscraper:apply-queue', heard)
    }
  })

  it('in auto mode Retry asks first: "Send <n> applications now?", and Not now sends nothing', async () => {
    const w = await mountInbox(questions([], { ready: READY, mode: 'auto' }))
    await startsWith(w, 'Retry 2 applications').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('Send 2 applications now?')
    expect(w.text()).toContain('JobScraper fills them in and submits them in Edge.')
    expect(server.calls.some(c => c.url === 'api/questions/retry')).toBe(false)
    await button(w, 'Not now').trigger('click')
    await flushPromises()
    expect(server.calls.some(c => c.url === 'api/questions/retry')).toBe(false)
    await startsWith(w, 'Retry 2 applications').trigger('click')
    await flushPromises()
    await button(w, 'Send applications').trigger('click')
    await flushPromises()
    expect(server.calls.filter(c => c.url === 'api/questions/retry')).toHaveLength(1)
  })

  it('says "1 application can go again now." for one', async () => {
    const w = await mountInbox(questions([], { ready: [READY[0]] }))
    expect(w.text()).toContain('1 application can go again now.')
    expect(startsWith(w, 'Retry 1 application')).toBeTruthy()
  })

  // Q-120 U1 (D-205): the queue never blocks, so a busy server no longer disables Retry.
  // Any failure still says so; a 422 profile_incomplete points at the application details.
  it('a busy server leaves Retry enabled; a failure says the queue did not take them', async () => {
    const busy = await mountInbox(questions([], { ready: READY, busy: true }), { retry: QUEUED })
    expect(busy.text()).not.toContain('Another job is running')
    const retry = startsWith(busy, 'Retry 2 applications')
    expect(retry.attributes('disabled')).toBeUndefined()
    await retry.trigger('click')
    await flushPromises()
    expect(server.calls.filter(c => c.url === 'api/questions/retry')).toHaveLength(1)

    const w = await mountInbox(questions([], { ready: READY }), { retry: () => [{ detail: 'busy' }, 409] })
    await startsWith(w, 'Retry 2 applications').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('Could not add them to the auto-apply queue:')
    expect(w.text()).not.toContain('Another job is running')

    const incomplete = await mountInbox(questions([], { ready: READY }), { retry: () => [{ detail: 'profile_incomplete', missing: ['personal.phone'] }, 422] })
    await startsWith(incomplete, 'Retry 2 applications').trigger('click')
    await flushPromises()
    expect(incomplete.text()).toContain('Finish your application details first.')
  })
})

suite('empty and answered states', () => {
  it('shows the empty state when nothing is waiting', async () => {
    const w = await mountInbox(questions([]))
    expect(w.text()).toContain('Questions from applications')
    // two sentences in two paragraphs (title + hint); wrapper.text() joins them with no space
    const text = w.text()
    const title = text.indexOf('No questions waiting.')
    const hint = text.indexOf("When an application asks something JobScraper can't answer, it shows up here.")
    expect(title, 'the empty-state title').toBeGreaterThanOrEqual(0)
    expect(hint, 'the empty-state hint').toBeGreaterThan(title)
  })

  it('lists answered questions in a collapsible "Answered questions (<n>)" with Change answer', async () => {
    // the fake answers every `api/questions?...` GET with this one payload, whichever status is asked for,
    // so the answered group is served to the open list and to the answered list alike
    const answered = group({ status: 'answered', current: { value: null, picks: ['citizen'], by_employer: {} } })
    const w = await mountInbox(questions([answered]))
    expect(w.text()).toMatch(/Answered questions \(\d+\)/)
    expect(w.findAll('button').some(b => b.text().trim() === 'Change answer')).toBe(true)
  })
})

suite('Q-70 D7: loading shows the skeleton, not a text line', () => {
  it('while the questions load a .skeleton shows and "Loading questions" does not; both are gone after', async () => {
    const Inbox = (await loaders['../src/components/QuestionsInbox.vue']()).default
    let release
    const gate = new Promise(r => { release = r })
    server = fakeServer(questions([group()]))
    const inner = server.fetch.getMockImplementation()
    vi.stubGlobal('fetch', vi.fn(async (url, init) => {
      if (String(url).startsWith('api/questions?') || String(url).startsWith('/api/questions?')) await gate
      return inner(url, init)
    }))
    const w = mount(Inbox)
    await flushPromises()
    expect(w.find('.skeleton').exists()).toBe(true)
    expect(w.text()).not.toContain('Loading questions')
    release()
    await flushPromises()
    expect(w.find('.skeleton').exists()).toBe(false)
    expect(w.text()).toContain('Visa status')
  })
})
