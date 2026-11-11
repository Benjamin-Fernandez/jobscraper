// Q-100 T1-0 pins for web/src/connections.js (design §2.1, §2.2, §4.2, §4.4):
// state -> chip tone and words, code -> copy (one check per code in the sample
// response), the attention count (the 2-failure rule, the model's need_now), and
// the "Apply for me" steps. Pure functions: no mount, no network.
import { describe, expect, it } from 'vitest'
import {
  COPY, STATES, applySteps, attentionCount, attentionItems, chipText, chipTone, codeCopy,
} from '../src/connections.js'
import sample from './fixtures/connections.sample.json'
import { pinZone } from './helpers.js'

pinZone()   // the Gmail "trying again at" time is shown in local time

const NOW = Date.parse('2026-11-11T09:12:00Z')
const variant = name => {
  const v = sample.variants[name]
  if (!v) throw new Error(`no fixture variant ${name}`)
  return v.item ?? v.employer_account
}
const copyOf = (name, ctx = {}) => codeCopy(variant(name), { now: NOW, ...ctx })
// A response with only the model item swapped for a variant (same id).
const withModel = name => ({ ...sample, items: sample.items.map(i => (i.kind === 'model' ? variant(name) : i)) })
const resp = (...items) => ({ items })

describe('chipTone', () => {
  it.each(STATES)('%s keeps its own tone', state => {
    expect(chipTone(state)).toBe(state)
  })
  it('there are six states', () => expect(STATES).toHaveLength(6))
  it('an unknown or missing state is drawn neutral', () => {
    expect(chipTone('bogus')).toBe('neutral')
    expect(chipTone(undefined)).toBe('neutral')
    expect(chipTone('')).toBe('neutral')
  })
})

describe('chipText: every state has words (colour is never the only cue)', () => {
  it('names each state', () => {
    expect(chipText({ state: 'connected', kind: 'gmail', code: 'ok' })).toBe('Connected')
    expect(chipText({ state: 'attention', kind: 'gmail', code: 'consent' })).toBe('Needs attention')
    expect(chipText({ state: 'paused', code: 'switched_off' })).toBe('Paused')
    expect(chipText({ state: 'checking', code: 'probing' })).toBe('Checking…')
  })
  it('not set up reads Optional for an optional item, else Not set up', () => {
    expect(chipText({ state: 'not_set_up', optional: true })).toBe('Optional')
    expect(chipText({ state: 'not_set_up', optional: false })).toBe('Not set up')
    expect(chipText({ state: 'not_set_up' })).toBe('Not set up')
  })
  it('the Edge profile reads Ready, or In use while an application holds it', () => {
    expect(chipText({ state: 'connected', kind: 'edge', code: 'ok' })).toBe('Ready')
    expect(chipText({ state: 'connected', kind: 'edge', code: 'in_use' })).toBe('In use')
  })
  it('a neutral item says why by its code', () => {
    expect(chipText({ state: 'neutral', code: 'unreachable' })).toBe('Not running')
    expect(chipText({ state: 'neutral', code: 'not_running' })).toBe('Not running')
    expect(chipText({ state: 'neutral', code: 'model_missing' })).toBe('Model not downloaded')
    expect(chipText({ state: 'neutral', code: 'unconfirmed' })).toBe('Not confirmed')
    expect(chipText({ state: 'neutral', code: 'check_failed' })).toBe("Couldn't check")
    expect(chipText({ state: 'neutral', code: 'something_new' })).toBe("Couldn't check")
  })
  it('an unknown, missing or null item never renders blank', () => {
    expect(chipText({ state: 'bogus' })).toBe("Couldn't check")
    expect(chipText({})).toBe("Couldn't check")
    expect(chipText(null)).toBe("Couldn't check")
    expect(chipText(undefined)).toBe("Couldn't check")
  })
  it('every item, employer row and variant of the sample has words, and attention says so', () => {
    const all = [...sample.items, ...sample.employer_accounts,
      ...Object.values(sample.variants).map(v => v.item ?? v.employer_account)]
    for (const item of all) {
      expect(chipText(item), item.id).toMatch(/\S/)
      expect(STATES, item.id).toContain(chipTone(item.state))
      if (item.state === 'attention') expect(chipText(item), item.id).toBe('Needs attention')
    }
  })
})

describe('codeCopy: the line under a chip, one check per code of the sample response', () => {
  it('Gmail: the server\'s own message wins for a sync code', () => {
    for (const name of ['gmail_paused_login_refused', 'gmail_paused_app_password_required',
      'gmail_paused_web_login_required', 'gmail_paused_not_set_up', 'gmail_error_stale', 'gmail_backoff_never_ok']) {
      const item = variant(name)
      expect(item.message, name).toBeTruthy()
      expect(copyOf(name), name).toBe(item.message)
    }
  })
  it('Gmail: the codes the client words itself', () => {
    expect(copyOf('gmail_switched_off')).toMatch(/switched off/)
    expect(copyOf('gmail_consent')).toMatch(/confirm/)
    expect(copyOf('gmail_ok_timer_off')).toMatch(/Automatic checks are off.*Check now/)
    expect(copyOf('gmail_none')).toMatch(/^Optional\. Connect Gmail/)
    expect(copyOf('gmail_ok_timer_running')).toBeNull()
  })
  it('Gmail: a retry says when it will try again (local time), or "soon" with no time', () => {
    expect(copyOf('gmail_error_recent')).toBe("The last check couldn't reach Gmail. Trying again at 11 Nov 17:30.")
    expect(copyOf('gmail_backoff_recent')).toBe("The last check couldn't reach Gmail. Trying again at 11 Nov 18:12.")
    const noTime = { ...variant('gmail_error_recent'), retry_after: null }
    expect(codeCopy(noTime, { now: NOW })).toBe("The last check couldn't reach Gmail. Trying again soon.")
  })
  it('Gmail: an attention row with no code copy and no message says how stale it is', () => {
    const stale = { kind: 'gmail', state: 'attention', code: 'brand_new', message: null, last_ok_at: '2026-11-09T09:00:00' }
    expect(codeCopy(stale, { now: NOW })).toMatch(/hasn't been checked since 9 Nov.*Check now/)
    const never = { ...stale, last_ok_at: null }
    expect(codeCopy(never, { now: NOW })).toBe("Gmail hasn't been checked yet. Check now to see why.")
    const fresh = { ...stale, last_ok_at: '2026-11-11T08:00:00' }
    expect(codeCopy(fresh, { now: NOW })).toBeNull()
  })
  it('application mailbox: the address is named when a password is missing', () => {
    expect(copyOf('apply_mailbox_ok')).toMatch(/verification codes/)
    expect(copyOf('apply_mailbox_unset')).toMatch(/^Optional\./)
    expect(copyOf('apply_mailbox_backup_unset')).toMatch(/^Optional\./)
    expect(copyOf('apply_mailbox_no_password')).toBe(
      `No app password is saved for ${variant('apply_mailbox_no_password').facts.username}. Sites that email a code will stop at that step.`)
    const noAddress = { kind: 'apply_mailbox', state: 'attention', code: 'no_password', facts: {} }
    expect(codeCopy(noAddress)).toMatch(/for this mailbox\./)
  })
  it('employer rows (no kind, an ats) have words for every failing code, none for ok and verified', () => {
    expect(copyOf('employer_created_ok')).toBeNull()
    expect(copyOf('employer_verified')).toBeNull()
    expect(copyOf('employer_signin_failed')).toMatch(/^Sign-in failed\. JobScraper won't try again/)
    expect(copyOf('employer_exists_no_password')).toMatch(/already exists.*doesn't have its password/)
    expect(copyOf('employer_password_missing')).toMatch(/missing from Windows Credential Manager/)
    expect(copyOf('employer_creating')).toMatch(/^Not confirmed\./)
    expect(copyOf('employer_unknown')).toMatch(/^Not confirmed\./)
  })
  it('employer accounts summary: the empty text only when there are none', () => {
    expect(copyOf('employer_summary_none')).toBe(COPY.employerEmpty)
    expect(copyOf('employer_summary_worst')).toBeNull()
  })
  it('Edge profile', () => {
    expect(copyOf('edge_missing')).toBe(COPY.browserNote)
    expect(copyOf('edge_ok')).toMatch(/used only by JobScraper/)
    expect(copyOf('edge_in_use_job')).toMatch(/In use by an application/)
    expect(copyOf('edge_in_use_lockfile')).toMatch(/In use by an application/)
  })
  it('Local AI: each code', () => {
    expect(copyOf('model_ai_off_enable_llm')).toMatch(/off in config\.yaml/)
    expect(copyOf('model_ai_off_backend')).toMatch(/off in config\.yaml/)
    expect(copyOf('model_misconfigured')).toMatch(/budget\.backend to ollama or off/)
    expect(copyOf('model_probing')).toBe('Checking the local AI…')
    const model = variant('model_ok').facts.model
    expect(copyOf('model_ok')).toBe(`${model} runs on this PC.`)
    expect(codeCopy({ ...variant('model_ok'), facts: { ...variant('model_ok').facts, local: false } }))
      .toBe(`${model} through Ollama (not on this PC).`)
  })
  it('Local AI: an unreachable Ollama names what is waiting only when it matters', () => {
    expect(copyOf('model_unreachable_need_now', { what: '3 emails' })).toBe(
      "Ollama isn't running, and 3 emails is waiting for it. Start Ollama, then check again.")
    expect(copyOf('model_unreachable_need_now')).toMatch(/and a task is waiting/)
    expect(copyOf('model_unreachable_idle', { what: '3 emails' })).toBe("Ollama isn't running. Nothing needs it right now.")
  })
  it('Local AI: a missing model gives the pull command for that model', () => {
    const model = variant('model_missing_need_now').facts.model
    for (const name of ['model_missing_need_now', 'model_missing_idle']) {
      expect(copyOf(name), name).toBe(`The model ${model} isn't downloaded. Run \`ollama pull ${model}\`, then check again.`)
    }
  })
  it('check_failed has the one shared line, for any kind', () => {
    for (const kind of ['gmail', 'apply_mailbox', 'edge', 'model', 'employer_accounts']) {
      expect(codeCopy({ kind, state: 'neutral', code: 'check_failed' }), kind).toBe(COPY.checkFailed)
    }
  })
  it('null and unknown codes give null (the chip alone), an unknown kind falls back to its message', () => {
    expect(codeCopy(null)).toBeNull()
    expect(codeCopy(undefined)).toBeNull()
    expect(codeCopy({ kind: 'model', code: 'brand_new', facts: {} })).toBeNull()
    expect(codeCopy({ kind: 'edge', code: 'brand_new' })).toBeNull()
    expect(codeCopy({ kind: 'other', code: 'x', message: 'Words from the server.' })).toBe('Words from the server.')
    expect(codeCopy({ kind: 'other', code: 'x' })).toBeNull()
  })
  it('every code in the sample is handled without throwing, and no copy is blank text', () => {
    const all = [...sample.items, ...sample.employer_accounts,
      ...Object.values(sample.variants).map(v => v.item ?? v.employer_account)]
    for (const item of all) {
      const text = codeCopy(item, { now: NOW })
      expect(text === null || /\S/.test(text), item.id + '/' + item.code).toBe(true)
    }
  })
})

describe('attentionCount (§2.2)', () => {
  it('counts the items in attention: the sample\'s own count', () => {
    expect(attentionCount(sample)).toBe(sample.attention)
    expect(attentionItems(sample).every(i => i.state === 'attention')).toBe(true)
  })
  it('nothing for a failed load, a missing list or a list that is not a list', () => {
    expect(attentionCount(null)).toBe(0)
    expect(attentionCount(undefined)).toBe(0)
    expect(attentionCount({})).toBe(0)
    expect(attentionCount({ items: 'x' })).toBe(0)
    expect(attentionCount({ items: [] })).toBe(0)
    // a failed load is never a count, whatever the load before it said
    expect(attentionCount(null, resp({ id: 'a', code: 'check_failed' }))).toBe(0)
  })
  it('paused, neutral, not set up and connected items do not count', () => {
    expect(attentionCount(resp(
      { id: 'a', state: 'paused' }, { id: 'b', state: 'neutral' }, { id: 'c', state: 'not_set_up' },
      { id: 'd', state: 'connected' }, { id: 'e', state: 'checking' },
    ))).toBe(0)
  })

  describe('a check that failed counts only on two loads in a row', () => {
    const failed = { id: 'gmail:3', kind: 'gmail', state: 'neutral', code: 'check_failed' }
    it('once is a blip: not counted', () => {
      expect(attentionCount(resp(failed))).toBe(0)
      expect(attentionCount(resp(failed), null)).toBe(0)
    })
    it('the same item failing again on the next load is counted', () => {
      expect(attentionCount(resp(failed), resp(failed))).toBe(1)
      expect(attentionItems(resp(failed), resp(failed)).map(i => i.id)).toEqual(['gmail:3'])
    })
    it('the earlier failure must be that same item', () => {
      expect(attentionCount(resp(failed), resp({ ...failed, id: 'gmail:4' }))).toBe(0)
    })
    it('the earlier load must have been a failure, not just a different answer', () => {
      expect(attentionCount(resp(failed), resp({ ...failed, state: 'connected', code: 'ok' }))).toBe(0)
      expect(attentionCount(resp(failed), resp({ ...failed, state: 'attention', code: 'network' }))).toBe(0)
      expect(attentionCount(resp(failed), resp())).toBe(0)
      expect(attentionCount(resp(failed), {})).toBe(0)
    })
    it('a different code this load is judged by its own state', () => {
      expect(attentionCount(resp({ ...failed, code: 'ok', state: 'connected' }), resp(failed))).toBe(0)
    })
    it('adds to the items already in attention', () => {
      const bad = { id: 'x', state: 'attention', code: 'consent' }
      expect(attentionCount(resp(failed, bad), resp(failed))).toBe(2)
      expect(attentionCount(resp(failed, bad))).toBe(1)
    })
  })

  describe('an Ollama that is down counts only when something is waiting (facts.need_now)', () => {
    it('unreachable / model_missing with need_now true: counted', () => {
      for (const name of ['model_unreachable_need_now', 'model_missing_need_now', 'need_now_a_job_running',
        'need_now_b_attempt_in_flight', 'need_now_c_model_unavailable_recent', 'need_now_d_pending_model']) {
        expect(attentionCount(resp(variant(name))), name).toBe(1)
      }
    })
    it('unreachable / model_missing with need_now false: not counted', () => {
      for (const name of ['model_unreachable_idle', 'model_missing_idle', 'need_now_a_mailtest_does_not_count',
        'need_now_c_model_unavailable_old']) {
        expect(attentionCount(resp(variant(name))), name).toBe(0)
      }
    })
    it('the client double-checks the server: state attention but need_now false is not counted', () => {
      for (const code of ['unreachable', 'model_missing']) {
        expect(attentionCount(resp({ id: 'model', kind: 'model', state: 'attention', code, facts: { need_now: false } })), code).toBe(0)
      }
    })
    it('and the other way: need_now true counts even if the state lagged behind', () => {
      expect(attentionCount(resp({ id: 'model', kind: 'model', state: 'neutral', code: 'unreachable', facts: { need_now: true } }))).toBe(1)
    })
    it('without a boolean need_now the server\'s state decides', () => {
      expect(attentionCount(resp({ id: 'model', kind: 'model', state: 'attention', code: 'unreachable', facts: {} }))).toBe(1)
      expect(attentionCount(resp({ id: 'model', kind: 'model', state: 'neutral', code: 'unreachable', facts: {} }))).toBe(0)
    })
    it('other model codes follow their state (misconfigured counts, ai_off and ok do not)', () => {
      expect(attentionCount(resp(variant('model_misconfigured')))).toBe(1)
      expect(attentionCount(resp(variant('model_ai_off_backend')))).toBe(0)
      expect(attentionCount(resp(variant('model_ok')))).toBe(0)
    })
    it('need_now on the whole sample: swapping the model item moves the count by exactly one', () => {
      expect(attentionCount(withModel('model_unreachable_idle'))).toBe(sample.attention)
      expect(attentionCount(withModel('model_unreachable_need_now'))).toBe(sample.attention + 1)
    })
    it('need_now is only read for a model item', () => {
      expect(attentionCount(resp({ id: 'g', kind: 'gmail', state: 'attention', code: 'unreachable', facts: { need_now: false } }))).toBe(1)
    })
  })
})

describe('applySteps: "Apply for me" (§4.2)', () => {
  const ready = { missing: [], completeness: { filled: 10, needed: 10 }, form: null }
  const byId = (r, id) => r.steps.find(s => s.id === id)

  it('the steps, in order, with only details and the local AI required', () => {
    const r = applySteps({ connections: sample, applicant: ready })
    expect(r.steps.map(s => [s.id, s.required])).toEqual([
      ['details', true], ['model', true], ['mailbox', false], ['gmail', false],
    ])
    expect(r.note).toMatch(/created the first time an application runs/)
  })
  it('everything ready: 2 of 2, not all failed', () => {
    const r = applySteps({ connections: sample, applicant: ready })
    expect([r.done, r.total, r.allFailed]).toEqual([2, 2, false])
    expect(r.steps.every(s => s.status === 'done' && s.done)).toBe(true)
  })
  it('missing details: todo, with how many are missing', () => {
    const r = applySteps({ connections: sample, applicant: { missing: ['a', 'b', 'c'] } })
    expect(byId(r, 'details')).toMatchObject({ status: 'todo', done: false, hint: '3 missing' })
    expect([r.done, r.total]).toEqual([1, 2])
  })
  it('counts required steps only: optional steps never move "n of m"', () => {
    const noOptional = { ...sample, items: sample.items.filter(i => i.kind === 'model') }
    const r = applySteps({ connections: noOptional, applicant: ready })
    expect(byId(r, 'mailbox').done).toBe(false)
    expect(byId(r, 'gmail').done).toBe(false)
    expect([r.done, r.total]).toEqual([2, 2])
    const onlyOptional = { items: sample.items.filter(i => i.kind !== 'model') }
    const r2 = applySteps({ connections: onlyOptional, applicant: { missing: ['a'] } })
    expect(byId(r2, 'mailbox').done).toBe(true)
    expect(byId(r2, 'gmail').done).toBe(true)
    expect([r2.done, r2.total]).toEqual([0, 1])   // the model could not be checked, details are todo
  })
  it('the local AI step: connected is done; switched off in settings is done; a down Ollama is todo', () => {
    expect(byId(applySteps({ connections: withModel('model_ok'), applicant: ready }), 'model'))
      .toMatchObject({ status: 'done', hint: 'Connected' })
    expect(byId(applySteps({ connections: withModel('model_ai_off_backend'), applicant: ready }), 'model'))
      .toMatchObject({ status: 'done', hint: 'Off in settings' })
    const down = byId(applySteps({ connections: withModel('model_unreachable_need_now'), applicant: ready }), 'model')
    expect(down).toMatchObject({ status: 'todo', done: false })
    expect(down.hint).toMatch(/Ollama isn't running/)
    const r = applySteps({ connections: withModel('model_misconfigured'), applicant: ready })
    expect(byId(r, 'model').status).toBe('todo')
    expect([r.done, r.total]).toEqual([1, 2])
  })
  it('a check still running is neither done nor counted', () => {
    const r = applySteps({ connections: withModel('model_probing'), applicant: ready })
    expect(byId(r, 'model')).toMatchObject({ status: 'checking', done: false, hint: 'Checking…' })
    expect([r.done, r.total, r.allFailed]).toEqual([1, 1, false])
  })
  it('a step that could not be checked is unknown and not counted', () => {
    const noModel = { ...sample, items: sample.items.filter(i => i.kind !== 'model') }
    const r = applySteps({ connections: noModel, applicant: ready })
    expect(byId(r, 'model')).toMatchObject({ status: 'unknown', done: false, hint: "Couldn't check" })
    expect([r.done, r.total, r.allFailed]).toEqual([1, 1, false])
    const r2 = applySteps({ connections: sample, applicant: null })
    expect(byId(r2, 'details')).toMatchObject({ status: 'unknown', done: false })
    expect([r2.done, r2.total, r2.allFailed]).toEqual([1, 1, false])
  })
  it('allFailed: no required step could be checked', () => {
    for (const args of [undefined, {}, { connections: null, applicant: null }, { connections: {}, applicant: {} },
      { connections: { items: [] }, applicant: null }]) {
      const r = applySteps(args)
      expect([r.done, r.total, r.allFailed], JSON.stringify(args)).toEqual([0, 0, true])
      expect(r.steps.filter(s => s.required).every(s => s.status === 'unknown')).toBe(true)
    }
  })
  it('allFailed is false as soon as one required step was checked', () => {
    expect(applySteps({ connections: null, applicant: ready }).allFailed).toBe(false)
    expect(applySteps({ connections: sample, applicant: null }).allFailed).toBe(false)
  })
  it('the optional mailbox and Gmail steps: done when connected, todo when not, unknown without a response', () => {
    const none = { items: [variant('apply_mailbox_unset'), { ...variant('gmail_none'), kind: 'gmail' }, variant('model_ok')] }
    const r = applySteps({ connections: none, applicant: ready })
    expect(byId(r, 'mailbox')).toMatchObject({ status: 'todo', done: false })
    expect(byId(r, 'gmail')).toMatchObject({ status: 'todo', done: false })
    const r2 = applySteps({ connections: null, applicant: ready })
    expect(byId(r2, 'mailbox').status).toBe('unknown')
    expect(byId(r2, 'gmail').status).toBe('unknown')
  })
  it('every step links to a place and has a call to action', () => {
    const r = applySteps({ connections: sample, applicant: ready })
    for (const s of r.steps) {
      expect(s.href, s.id).toMatch(/^#\/(profile|settings)\//)
      expect(s.cta, s.id).toMatch(/\S/)
      expect(s.label, s.id).toMatch(/\S/)
    }
  })
})
