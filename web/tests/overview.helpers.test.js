// Q-70 lane E: the pure rules behind the Overview tab (web/src/overview.js).
// The clock is always passed in, so nothing here depends on today's date.
// Spec: docs/architecture/ux/overview_design.md §3. (Named .helpers.test.js because
// "overview.test.js" and "Overview.test.js" are the same file on Windows.)
import { describe, expect, it } from 'vitest'
import {
  DAY_MS, FOLLOW_UP_SHOWN, HARD_RUN_FAILURES, STALE_RUN_DAYS, WINDOW_DAYS,
  followUps, lastRunState, nextUp, openStages, pastWeek, pipeline, responseRate,
} from '../src/overview.js'

const NOW = Date.parse('2026-09-29T12:00:00Z')
const iso = ms => new Date(ms).toISOString().slice(0, 19)
const daysAgo = (d, extraMs = 0) => iso(NOW - d * DAY_MS - extraMs)

// A row of GET /api/applications: events are [to_status, at] pairs, oldest first.
function row(job_id, status, events = [], extra = {}) {
  let from = null
  return {
    job_id, status, company: `Co ${job_id}`, role: `Role ${job_id}`,
    events: events.map(([to_status, at]) => {
      const e = { from_status: from, to_status, at }
      from = to_status
      return e
    }),
    ...extra,
  }
}

const VOCAB = ['to_apply', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn']

describe('openStages', () => {
  it('keeps config order and appends unknown open statuses', () => {
    expect(openStages(VOCAB)).toEqual(['to_apply', 'applied', 'interviewing', 'offer'])
    // Config order wins over any hardcoded order: assessment sits where config puts it.
    expect(openStages(['to_apply', 'applied', 'assessment', 'interviewing', 'offer', 'rejected', 'withdrawn']))
      .toEqual(['to_apply', 'applied', 'assessment', 'interviewing', 'offer'])
    // A row on a status the vocabulary lacks is appended, once, in first-seen order.
    const rows = [row('a', 'on_hold'), row('b', 'revisit'), row('c', 'on_hold'), row('d', 'applied')]
    expect(openStages(VOCAB, rows)).toEqual(['to_apply', 'applied', 'interviewing', 'offer', 'on_hold', 'revisit'])
  })

  it('never lists closed statuses, and falls back to the four stages when stats failed', () => {
    expect(openStages(VOCAB, [row('a', 'rejected'), row('b', 'withdrawn')])).not.toContain('rejected')
    expect(openStages([], [])).toEqual(['to_apply', 'applied', 'interviewing', 'offer'])
    expect(openStages(undefined, undefined)).toEqual(['to_apply', 'applied', 'interviewing', 'offer'])
    expect(openStages(['rejected', 'withdrawn'])).toEqual(['to_apply', 'applied', 'interviewing', 'offer'])
  })
})

describe('pipeline', () => {
  it('counts closed apart', () => {
    const rows = [
      row('a', 'to_apply'), row('b', 'applied'), row('c', 'applied'), row('d', 'interviewing'),
      row('e', 'rejected'), row('f', 'rejected'), row('g', 'withdrawn'),
    ]
    const p = pipeline(rows, VOCAB)
    expect(p.stages.map(s => [s.status, s.n])).toEqual([
      ['to_apply', 1], ['applied', 2], ['interviewing', 1], ['offer', 0],   // zero stays: the flow reads left to right
    ])
    expect(p.stages.map(s => s.label)).toEqual(['Saved', 'Applied', 'Interviewing', 'Offer'])
    expect(p.closed).toEqual({ n: 3, rejected: 2, withdrawn: 1 })
    expect(p.total).toBe(7)
  })

  it('copes with nothing at all', () => {
    expect(pipeline(null, VOCAB)).toEqual({
      stages: ['to_apply', 'applied', 'interviewing', 'offer'].map(status => expect.objectContaining({ status, n: 0 })),
      closed: { n: 0, rejected: 0, withdrawn: 0 }, total: 0,
    })
  })

  it('counts a status the vocabulary lacks, with a readable label', () => {
    const p = pipeline([row('a', 'on_hold')], VOCAB)
    expect(p.stages.at(-1)).toEqual({ status: 'on_hold', label: 'On hold', n: 1 })
  })
})

describe('responseRate', () => {
  const at = '2026-09-20T10:00:00'
  it('counts interview, offer and rejection after applying, not withdrawn or rejected from Saved', () => {
    const rows = [
      row('plain', 'applied', [['to_apply', at], ['applied', at]]),                         // sent, no reply
      row('talk', 'interviewing', [['to_apply', at], ['applied', at], ['interviewing', at]]),   // reply
      row('offer', 'offer', [['applied', at], ['interviewing', at], ['offer', at]]),           // reply
      row('declined', 'rejected', [['applied', at], ['rejected', at]]),                        // rejection after applying: a reply
      row('own', 'withdrawn', [['applied', at], ['withdrawn', at]]),                           // the owner's choice
      row('never', 'rejected', [['to_apply', at], ['rejected', at]]),                          // rejected from Saved: not applied
      row('saved', 'to_apply', [['to_apply', at]]),
    ]
    expect(responseRate(rows, VOCAB)).toEqual({ applied: 5, heard: 3, rate: 60 })
  })

  it('rounds to a whole percent', () => {
    const one = [row('a', 'interviewing', [['applied', 'x'], ['interviewing', 'x']]), row('b', 'applied', [['applied', 'x']]), row('c', 'applied', [['applied', 'x']])]
    expect(responseRate(one, VOCAB).rate).toBe(33)
    const two = [one[0], row('d', 'offer', [['applied', 'x'], ['offer', 'x']]), one[1]]
    expect(responseRate(two, VOCAB).rate).toBe(67)
  })

  it('a status past Applied counts as sent even with no events, and a rejection before the first apply is no reply', () => {
    expect(responseRate([row('a', 'interviewing')], VOCAB)).toEqual({ applied: 1, heard: 1, rate: 100 })
    const reopened = row('b', 'applied', [['to_apply', 'x'], ['rejected', 'x'], ['applied', 'x']])
    expect(responseRate([reopened], VOCAB)).toEqual({ applied: 1, heard: 0, rate: 0 })
  })

  it('treats stages after Applied from config as replies (an assessment stage)', () => {
    const vocab = ['to_apply', 'applied', 'assessment', 'interviewing', 'offer', 'rejected', 'withdrawn']
    expect(responseRate([row('a', 'assessment', [['applied', 'x'], ['assessment', 'x']]), row('b', 'applied', [['applied', 'x']])], vocab))
      .toEqual({ applied: 2, heard: 1, rate: 50 })
  })

  it('responseRate is null with no applications', () => {
    expect(responseRate([], VOCAB)).toEqual({ applied: 0, heard: 0, rate: null })
    expect(responseRate(null, VOCAB)).toEqual({ applied: 0, heard: 0, rate: null })
    expect(responseRate([row('s', 'to_apply', [['to_apply', 'x']]), row('r', 'rejected', [['to_apply', 'x'], ['rejected', 'x']])], VOCAB).rate).toBeNull()
    // A vocabulary without Applied cannot say who applied.
    expect(responseRate([row('a', 'offer')], ['to_apply', 'offer', 'rejected'])).toEqual({ applied: 0, heard: 0, rate: null })
  })
})

describe('pastWeek', () => {
  it('uses a rolling 7 days and skips dry runs', () => {
    expect(WINDOW_DAYS).toBe(7)
    const edge = iso(NOW - 7 * DAY_MS)
    const justOutside = iso(NOW - 7 * DAY_MS - 1000)
    const rows = [
      row('a', 'applied', [['to_apply', edge], ['applied', daysAgo(1)]]),
      row('b', 'interviewing', [['to_apply', justOutside], ['applied', daysAgo(10)], ['interviewing', daysAgo(2)]]),
      row('c', 'rejected', [['applied', daysAgo(3)], ['rejected', daysAgo(0)]]),
    ]
    const runs = [
      { run_no: 5, status: 'ok', accepted: 4, finished_at: daysAgo(1) },
      { run_no: 4, status: 'dry_run', accepted: 50, finished_at: daysAgo(1) },        // fetched nothing real
      { run_no: 3, status: 'ok', accepted: 9, finished_at: daysAgo(8) },              // outside the window
      { run_no: 2, status: 'ok', accepted: '3', finished_at: daysAgo(6) },            // a number as a string
      { run_no: 1, status: 'running', accepted: 99, finished_at: null },              // not finished
    ]
    expect(pastWeek(rows, runs, NOW)).toEqual({ found: 7, saved: 1, applied: 2, moved: 2 })
  })

  it('skips unreadable stamps, counts an undo as a change, and copes with nothing', () => {
    const rows = [row('a', 'to_apply', [['applied', daysAgo(2)], ['to_apply', daysAgo(1)]]), row('b', 'applied', [['applied', 'garbage'], ['applied', '']])]
    const runs = [{ status: 'ok', accepted: 2, finished_at: 'nope' }, { status: 'ok', accepted: 'many', finished_at: daysAgo(1) }]
    expect(pastWeek(rows, runs, NOW)).toEqual({ found: 0, saved: 1, applied: 1, moved: 0 })
    expect(pastWeek(null, undefined, NOW)).toEqual({ found: 0, saved: 0, applied: 0, moved: 0 })
    expect(pastWeek([{ job_id: 'x', status: 'applied' }], [], NOW).applied).toBe(0)   // no events key
  })
})

describe('followUps', () => {
  it('lists applied 14+ days, longest first', () => {
    const rows = [
      row('w13', 'applied', [['applied', daysAgo(13, 60000)]]),             // 13 days: not yet
      row('w14', 'applied', [['applied', daysAgo(14)]]),
      row('w30', 'applied', [['applied', daysAgo(30)]]),
      row('w14b', 'applied', [['applied', daysAgo(14, 3600000)]]),         // 14 days and a bit
      row('moved', 'interviewing', [['applied', daysAgo(40)], ['interviewing', daysAgo(1)]]),
      row('saved', 'to_apply', [['to_apply', daysAgo(50)]]),
      row('closed', 'rejected', [['applied', daysAgo(50)], ['rejected', daysAgo(20)]]),
      row('replied', 'applied', [['applied', daysAgo(40)], ['applied', daysAgo(2)]]),   // last event is recent
    ]
    expect(followUps(rows, NOW).map(f => [f.job_id, f.days])).toEqual([['w30', 30], ['w14', 14], ['w14b', 14]])
  })

  it('carries what the card prints, and breaks ties by job id', () => {
    const rows = [row('b', 'applied', [['applied', daysAgo(20)]]), row('a', 'applied', [['applied', daysAgo(20)]])]
    expect(followUps(rows, NOW)).toEqual([
      { job_id: 'a', company: 'Co a', role: 'Role a', days: 20 },
      { job_id: 'b', company: 'Co b', role: 'Role b', days: 20 },
    ])
    expect(followUps(null, NOW)).toEqual([])
    expect(FOLLOW_UP_SHOWN).toBe(3)
  })
})

describe('lastRunState', () => {
  const run = (status, finished, extra = {}) => ({ run_no: 1, status, finished_at: finished, accepted: 2, ...extra })

  it('is none, fresh, stale or failed', () => {
    expect(lastRunState([], NOW)).toEqual({ state: 'none', run: null, days: null })
    expect(lastRunState(null, NOW).state).toBe('none')

    const fresh = run('ok', daysAgo(2))
    expect(lastRunState([fresh], NOW)).toEqual({ state: 'fresh', run: fresh, days: 2 })

    expect(STALE_RUN_DAYS).toBe(7)
    expect(lastRunState([run('ok', daysAgo(6, 3600000))], NOW).state).toBe('fresh')     // 6 days and an hour
    const stale = run('ok', daysAgo(7))
    expect(lastRunState([stale], NOW)).toEqual({ state: 'stale', run: stale, days: 7 })

    const broke = run('failed', daysAgo(0, 60000))
    expect(lastRunState([broke], NOW)).toEqual({ state: 'failed', run: broke, days: 0 })
  })

  it('a hard failure is failed however recent or old; unreadable companies alone are not', () => {
    expect(HARD_RUN_FAILURES).toEqual(['failed', 'aborted_unhealthy'])
    expect(lastRunState([run('aborted_unhealthy', daysAgo(1))], NOW).state).toBe('failed')
    expect(lastRunState([run('failed', daysAgo(30))], NOW).state).toBe('failed')
    expect(lastRunState([run('ok', daysAgo(1), { stats: { companies_failed: 28 } })], NOW).state).toBe('fresh')
  })

  it('looks at the newest finished real run: dry and unfinished runs are skipped', () => {
    const real = run('ok', daysAgo(10))
    const runs = [run('running', null), run('dry_run', daysAgo(0, 60000)), real]
    expect(lastRunState(runs, NOW)).toEqual({ state: 'stale', run: real, days: 10 })
    expect(lastRunState([run('dry_run', daysAgo(1)), run('running', null)], NOW).state).toBe('none')
  })
})

describe('nextUp', () => {
  const fresh = { state: 'fresh' }
  const stale = { state: 'stale', days: 9 }
  const failed = { state: 'failed' }
  const due = [{ job_id: 'a' }, { job_id: 'b' }]

  it('orders questions, inbox, follow-up, run and hides the run card while a job runs', () => {
    const all = { newRoles: 5, questions: 2, followUps: due, run: stale, jobRunning: false }
    expect(nextUp(all)).toEqual([
      { id: 'questions', n: 2 }, { id: 'inbox', n: 5 }, { id: 'follow-up', n: 2 }, { id: 'run' },
    ])
    expect(nextUp({ ...all, jobRunning: true }).map(c => c.id)).toEqual(['questions', 'inbox', 'follow-up'])
    expect(nextUp({ ...all, run: failed }).at(-1)).toEqual({ id: 'run' })
    expect(nextUp({ ...all, run: failed, jobRunning: true }).map(c => c.id)).not.toContain('run')
  })

  it('lists only items with work', () => {
    expect(nextUp({ newRoles: 3, questions: 0, followUps: [], run: fresh })).toEqual([{ id: 'inbox', n: 3 }])
    expect(nextUp({ questions: 1 })).toEqual([{ id: 'questions', n: 1 }])
    expect(nextUp({ followUps: due }).map(c => c.id)).toEqual(['follow-up'])
    expect(nextUp({ run: stale }).map(c => c.id)).toEqual(['run'])
  })

  it('has no card for a run that never happened or a fresh one, and [] means caught up', () => {
    expect(nextUp({ newRoles: 0, questions: 0, followUps: [], run: { state: 'none' } })).toEqual([])
    expect(nextUp({ run: fresh })).toEqual([])
    expect(nextUp()).toEqual([])
  })
})
