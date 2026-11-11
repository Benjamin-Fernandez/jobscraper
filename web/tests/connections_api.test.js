// Q-100 T1-0 pins for web/src/connections_api.js (design §3, §4.3): an absent route
// (404 or 405) answers null so a screen hides the row; any other failure throws the
// same ApiError as api.js; and no call sends or carries a secret (D-191).
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/api.js'
import {
  checkModel, getApplicantSummary, getApplySettings, getApplyStatus, getConnections, putApplySettings,
} from '../src/connections_api.js'
import sample from './fixtures/connections.sample.json'

afterEach(() => vi.unstubAllGlobals())

// A fetch that answers `status` with `body` and records each call.
function stubFetch(status = 200, body = {}) {
  const calls = []
  const fetch = vi.fn(async (url, init = {}) => {
    calls.push({ url, method: init.method ?? 'GET', body: init.body, headers: init.headers })
    return {
      ok: status >= 200 && status < 300,
      status,
      statusText: { 200: 'OK', 202: 'Accepted', 404: 'Not Found', 405: 'Method Not Allowed', 422: 'Unprocessable Entity', 500: 'Internal Server Error' }[status] ?? '',
      json: async () => body,
    }
  })
  vi.stubGlobal('fetch', fetch)
  return calls
}

const CALLS = {
  getConnections: () => getConnections(),
  checkModel: () => checkModel(),
  getApplyStatus: () => getApplyStatus(),
  getApplySettings: () => getApplySettings(),
  putApplySettings: () => putApplySettings({ mode: 'auto' }),
  getApplicantSummary: () => getApplicantSummary(),
}

describe('absent routes answer null', () => {
  for (const status of [404, 405]) {
    for (const [name, call] of Object.entries(CALLS)) {
      it(`${name}: a ${status} is "this feature is absent"`, async () => {
        stubFetch(status, { detail: 'Not Found' })
        await expect(call()).resolves.toBeNull()
      })
    }
  }
})

describe('any other failure throws ApiError', () => {
  for (const [name, call] of Object.entries(CALLS)) {
    it(`${name}: a 500 throws, with its status`, async () => {
      stubFetch(500, { detail: 'boom' })
      const err = await call().then(() => null, e => e)
      expect(err).toBeInstanceOf(ApiError)
      expect(err.status).toBe(500)
      expect(err.detail).toBe('boom')
    })
  }
  it('a 422 from the settings save carries its detail for "Couldn\'t save: ..."', async () => {
    stubFetch(422, { detail: 'max_per_day must be at least 1' })
    const err = await putApplySettings({ max_per_day: 0 }).then(() => null, e => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(422)
    expect(err.detail).toBe('max_per_day must be at least 1')
  })
  it('a network failure throws; it is not an absent route', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    await expect(getConnections()).rejects.toThrow('Failed to fetch')
  })
})

describe('the requests', () => {
  it('each call hits its route with its method', async () => {
    const calls = stubFetch(200, {})
    await getConnections()
    await checkModel()
    await getApplyStatus()
    await getApplySettings()
    await putApplySettings({ mode: 'dry_run' })
    await getApplicantSummary()
    expect(calls.map(c => [c.method, c.url])).toEqual([
      ['GET', 'api/connections'],
      ['POST', 'api/connections/model/check'],
      ['GET', 'api/apply/status'],
      ['GET', 'api/apply/settings'],
      ['PUT', 'api/apply/settings'],
      ['GET', 'api/applicant'],
    ])
  })
  it('a 200 answer is passed through as the server sent it', async () => {
    stubFetch(200, sample)
    expect(await getConnections()).toEqual(sample)
  })
  it('a 202 from the model check is an answer, not an error', async () => {
    stubFetch(202, { started: true })
    await expect(checkModel()).resolves.toEqual({ started: true })
  })
  it('the settings save sends JSON with exactly the fields it was given', async () => {
    const calls = stubFetch(200, { mode: 'auto' })
    await putApplySettings({ mode: 'auto', max_per_day: 5 })
    expect(calls[0].headers).toEqual({ 'Content-Type': 'application/json' })
    expect(JSON.parse(calls[0].body)).toEqual({ mode: 'auto', max_per_day: 5 })
  })
  it('reads and the model check send no body', async () => {
    const calls = stubFetch(200, {})
    await getConnections()
    await checkModel()
    await getApplyStatus()
    expect(calls.every(c => c.body === undefined)).toBe(true)
  })
})

describe('getApplicantSummary keeps only what setup needs', () => {
  it('drops the profile and its etag, whatever the server sends', async () => {
    stubFetch(200, {
      missing: ['personal.phone'], completeness: { filled: 3, needed: 4 }, form: { fields: [] },
      profile: { personal: { phone: '+65 0000 0000' } }, etag: 'abc', password: 'x',
    })
    const out = await getApplicantSummary()
    expect(Object.keys(out).sort()).toEqual(['completeness', 'form', 'missing'])
    expect(out.missing).toEqual(['personal.phone'])
  })
  it('a server without the pieces gets safe defaults', async () => {
    stubFetch(200, {})
    expect(await getApplicantSummary()).toEqual({ missing: [], completeness: null, form: null })
    stubFetch(200, { missing: 'not a list' })
    expect((await getApplicantSummary()).missing).toEqual([])
  })
})

// ---- no secret on the wire (D-191) ----

const SECRET_KEY = /password|passwd|secret|token|credential/i
// `has_password` is a yes/no flag ("is one stored?"), never the password itself: it
// is allowed only while its value is a boolean.
function secretKeys(value, path = '$') {
  const found = []
  if (Array.isArray(value)) {
    value.forEach((v, i) => found.push(...secretKeys(v, `${path}[${i}]`)))
  } else if (value && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) {
      if (SECRET_KEY.test(k) && !(k === 'has_password' && typeof v === 'boolean')) found.push(`${path}.${k}`)
      found.push(...secretKeys(v, `${path}.${k}`))
    }
  }
  return found
}

// `variants` is fixture bookkeeping, not part of the contract: its keys are case
// names such as `apply_mailbox_no_password`, so scan the contract part and the
// payload inside each variant, not the case names.
const { variants, ...contract } = sample

describe('no secret in a request or a response', () => {
  it('the sample response has no key named like a password, secret or token (has_password flags excepted)', () => {
    expect(secretKeys(contract)).toEqual([])
    expect(Object.keys(variants).length).toBeGreaterThan(40)
    for (const [name, v] of Object.entries(variants)) {
      expect(secretKeys(v.item ?? v.employer_account), name).toEqual([])
      expect(secretKeys(v.expect), name).toEqual([])
    }
  })
  it('the scan itself would catch one', () => {
    expect(secretKeys({ items: [{ facts: { password: 'x' } }] })).toEqual(['$.items[0].facts.password'])
    expect(secretKeys({ a: { api_token: 't' }, b: [{ client_secret: 's' }] })).toEqual(['$.a.api_token', '$.b[0].client_secret'])
    expect(secretKeys({ has_password: 'hunter2' })).toEqual(['$.has_password'])
    expect(secretKeys({ has_password: true })).toEqual([])
  })
  it('has_password is only ever a boolean in the sample', () => {
    const flags = []
    JSON.stringify(sample, (k, v) => { if (k === 'has_password') flags.push(v); return v })
    expect(flags.length).toBeGreaterThan(0)
    expect(flags.every(v => typeof v === 'boolean')).toBe(true)
  })
  it('no call sends a body that carries a secret key, and every response a screen gets is clean', async () => {
    const calls = stubFetch(200, contract)
    const answers = [
      await getConnections(), await checkModel(), await getApplyStatus(), await getApplySettings(),
      await putApplySettings({ mode: 'auto', max_per_day: 5, compose_enabled: false }), await getApplicantSummary(),
    ]
    for (const c of calls) {
      if (c.body !== undefined) expect(secretKeys(JSON.parse(c.body)), c.url).toEqual([])
    }
    expect(secretKeys(answers)).toEqual([])
  })
})
