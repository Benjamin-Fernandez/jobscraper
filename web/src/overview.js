// Pure helpers behind the Overview tab (Q-70 wave 2, D-102/D-103; reshaped by Q-118 LA):
// the headline numbers, the pipeline counts, the response rate, the past seven days,
// who to follow up with, how the last run went, and what to put under "To do". No Vue
// and no clock of their own (`now` is passed in), so every rule is testable on its own
// and the tab stays markup. Design: docs/architecture/ux/overview_design.md §3 and
// docs/architecture/q118_ui_polish_design.md §2.
import { daysSince, isActive, lastAt, needsFollowUp } from './applications.js'
import { newRoleCount } from './badges.js'
import { utcMs } from './format.js'
import { CLOSED_STATUSES, stageOf, statusLabel } from './stages.js'

export const DAY_MS = 86400000
// "This week" is the rolling past 7 days, not a calendar week (O4).
export const WINDOW_DAYS = 7
// A run older than this is "stale": the widest common run cycle (O5).
export const STALE_RUN_DAYS = 7
export const FOLLOW_UP_SHOWN = 3
// The two run statuses that mean the run itself broke (not "some companies
// could not be read"); the Runs table colours its failed count by the same list.
export const HARD_RUN_FAILURES = ['failed', 'aborted_unhealthy']
// The key Profile.vue reads on mount to pick its view (O6).
export const PROFILE_VIEW_KEY = 'profile.view'

// Only for a stats call that failed. `to_apply` is no pipeline stage any more (D-207):
// a saved or queued role counts as "To apply" under Active, not in the bar.
const DEFAULT_STAGES = ['applied', 'interviewing', 'offer']

// The pipeline bar's stages, in order: the four stage tabs of the Applications tab
// (STAGE_TABS without All and Active). Each one links to `#/applications/<stage>`.
export const PIPELINE_STAGES = ['applied', 'interviewing', 'offer', 'rejected']

const list = v => (Array.isArray(v) ? v : [])
const eventsOf = row => list(row?.events)

// The open stages, in the order config gives them (M8-T2: never hardcoded here,
// the fallback is only for a stats call that failed). A status found on a row
// but missing from the vocabulary is appended so no application goes uncounted.
export function openStages(statuses = [], rows = []) {
  const base = list(statuses).filter(s => s && !CLOSED_STATUSES.includes(s))
  const out = base.length ? [...new Set(base)] : [...DEFAULT_STAGES]
  for (const row of list(rows)) {
    const s = row?.status
    if (s && !CLOSED_STATUSES.includes(s) && !out.includes(s)) out.push(s)
  }
  return out
}

// The pipeline as the Applications tabs count it (D-207): `stageOf` folds `assessment` into
// Interviewing and `withdrawn` into Rejected; a `to_apply` row (or a status config adds
// later) is in no stage, so it is counted apart in `toApply` and still in `total`.
// The same parts are also returned alone, for the legend notes.
export function pipeline(rows) {
  const all = list(rows)
  const count = test => all.filter(test).length
  return {
    segments: PIPELINE_STAGES.map(id => ({
      id, label: statusLabel(id), n: count(r => stageOf(r?.status) === id),
    })),
    toApply: count(r => r?.status === 'to_apply'),
    assessment: count(r => r?.status === 'assessment'),
    rejected: count(r => r?.status === 'rejected'),
    withdrawn: count(r => r?.status === 'withdrawn'),
    total: all.length,
  }
}

// The four headline numbers (KPI row): New roles in the Inbox, Active applications
// (everything not rejected or withdrawn, "To apply" included), Interviews (interviewing and
// assessment) with the offers beside them, and the response rate (`responseRate`).
export function kpis(rows, jobs, statuses) {
  const all = list(rows)
  const { segments } = pipeline(all)
  const n = id => segments.find(s => s.id === id)?.n ?? 0
  return {
    newRoles: newRoleCount(list(jobs)),
    active: all.filter(r => r && isActive(r)).length,
    interviews: n('interviewing'),
    offers: n('offer'),
    reply: responseRate(all, statuses),
  }
}

// Of the applications you sent, how many got any reply. A reply is an
// interview, an offer (any open stage after Applied) or a rejection after you
// applied; withdrawing is your choice, and a role rejected from Saved was
// never applied to.
export function responseRate(rows, statuses) {
  const stages = openStages(statuses, rows)
  const at = stages.indexOf('applied')
  if (at === -1) return { applied: 0, heard: 0, rate: null }
  const later = stages.slice(at + 1)
  const sent = new Set(['applied', ...later])
  let applied = 0
  let heard = 0
  for (const row of list(rows)) {
    const events = eventsOf(row)
    const first = events.findIndex(e => sent.has(e?.to_status))
    const isApplied = sent.has(row?.status) || first !== -1
    if (!isApplied) continue
    applied += 1
    const moved = later.includes(row.status) || events.some(e => later.includes(e?.to_status))
    const rejectedAfter = first !== -1 && events.slice(first + 1).some(e => e?.to_status === 'rejected')
    if (moved || rejectedAfter) heard += 1
  }
  return { applied, heard, rate: applied === 0 ? null : Math.round((heard / applied) * 100) }
}

// What happened in the rolling past 7 days. `saved` (shown as "To apply") and `applied`
// count status changes to those stages, `moved` every other change (an undo is a change
// too, D-101). `found` is what finished runs accepted, dry runs excluded.
export function pastWeek(rows, runs, now = Date.now()) {
  const since = now - WINDOW_DAYS * DAY_MS
  const week = { found: 0, saved: 0, applied: 0, moved: 0 }
  for (const row of list(rows)) {
    for (const e of eventsOf(row)) {
      const t = utcMs(e?.at)
      if (t === null || t < since) continue
      if (e.to_status === 'to_apply') week.saved += 1
      else if (e.to_status === 'applied') week.applied += 1
      else week.moved += 1
    }
  }
  for (const r of list(runs)) {
    const t = utcMs(r?.finished_at)
    if (t === null || t < since || r.status === 'dry_run') continue
    week.found += Number(r.accepted) || 0
  }
  return week
}

// Applications that went quiet after applying, longest wait first.
export function followUps(rows, now = Date.now()) {
  return list(rows)
    .filter(r => r && needsFollowUp(r, now))
    .map(r => ({ job_id: r.job_id, company: r.company, role: r.role, days: daysSince(lastAt(r), now) }))
    .sort((a, b) => b.days - a.days || String(a.job_id).localeCompare(String(b.job_id)))
}

// How the last real run went: 'none' | 'failed' | 'stale' | 'fresh'. Dry runs
// don't count (they fetch nothing new for the Inbox). Same pick as the Runs tab.
export function lastRunState(runs, now = Date.now()) {
  const run = list(runs).find(r => r?.finished_at && r.status !== 'dry_run') ?? null
  if (!run) return { state: 'none', run: null, days: null }
  const days = daysSince(run.finished_at, now)
  if (HARD_RUN_FAILURES.includes(run.status)) return { state: 'failed', run, days }
  if (days !== null && days >= STALE_RUN_DAYS) return { state: 'stale', run, days }
  return { state: 'fresh', run, days }
}

// The "To do" rows in the order the owner should do them, only those with
// work. [] means caught up. A run that never happened is the setup checklist's
// business, not a card.
export function nextUp({ newRoles = 0, questions = 0, followUps: due = [], run = null, jobRunning = false } = {}) {
  const out = []
  if (questions > 0) out.push({ id: 'questions', n: questions })
  if (newRoles > 0) out.push({ id: 'inbox', n: newRoles })
  const quiet = Array.isArray(due) ? due.length : Number(due) || 0
  if (quiet > 0) out.push({ id: 'follow-up', n: quiet })
  if ((run?.state === 'stale' || run?.state === 'failed') && !jobRunning) out.push({ id: 'run' })
  return out
}
