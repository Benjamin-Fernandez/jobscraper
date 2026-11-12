// Q-44 / Q-73 pins, vitest side (R10; the Python side is tests/test_q44_refresh.py):
// the resume summary card (no folders anywhere in the default view), the job log
// under a collapsed Details, and "Update your application details" (ResumeRefresh):
// default ticks, the Save count, the POST body, the saved line and its link, Not now,
// the unavailable / stale / empty copy, and a quiet panel on a server without the route.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import Profile from '../src/tabs/Profile.vue'
import { POLL_MS, resetSeenJobs } from '../src/composables/useJob.js'
import { skillLabel } from '../src/applicantForm.js'
import { fakeApi, pinZone } from './helpers.js'
import skillCases from '../../tests/fixtures/skill_labels.json'

pinZone()

let api

function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
  return api
}

const SKIP_LINE = "application details check skipped: the AI model isn't running"
const RUNNING = { id: 5, kind: 'profile', state: 'running', started_at: '2026-09-24T08:10:00', log: [] }

const exp = (employer, title, start = '2024-05', end = '2024-08') => ({ employer, title, start, end, location: '', description: '', from_resume: true })
const PLAN = () => ({
  state: 'ready', source_name: 'resume.pdf', created_at: '2026-11-07T00:00:00', resume_hash: 'sha256:r1', etag: 'e1',
  changes: [
    { id: 'experience:remove:example pte ltd|software engineering intern', list: 'experience', op: 'remove', index: 0,
      before: exp('Example Pte Ltd', 'Software Engineering Intern'), after: null, reason: 'template',
      note: 'Example entry from the template', default: true },
    { id: 'experience:add:acme|intern', list: 'experience', op: 'add', index: 1, before: null,
      after: exp('Acme', 'Intern'), note: '', default: true },
    { id: 'experience:update:beta|analyst', list: 'experience', op: 'update', index: 2,
      before: exp('Beta', 'Analyst', '2023-01', '2023-06'), after: exp('Beta', 'Analyst', '2023-01', null), note: '', default: true },
    { id: 'education:add:nus|bsc', list: 'education', op: 'add', index: 0, before: null,
      after: { institution: 'NUS', degree: 'BSc', start: null, end: null, from_resume: true },
      note: 'Dates not understood ("2021 – 2025"). Add them after saving. Resume says: Honours', default: false },
    { id: 'education:remove:old u|old degree', list: 'education', op: 'remove', index: 1,
      before: { institution: 'Old U', degree: 'Old degree', start: '2010-01', end: '2012-01' }, after: null,
      reason: 'not_on_resume', note: 'No longer on your resume', default: true },
    { id: 'experience:kept:mine|tutor', list: 'experience', op: 'kept', index: 3,
      before: exp('Mine', 'Tutor'), after: null, note: '', default: false },
    { id: 'skills:add', list: 'skills', op: 'add', index: null, before: ['Python'], after: ['Python', 'Go', 'Rust'],
      note: '', default: true },
  ],
  skills: { add: ['Go', 'Rust'], not_on_resume: ['Docker', 'Terraform'] },
})

beforeEach(() => {
  resetSeenJobs()
  window.localStorage.clear()
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  useApi()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})
enableAutoUnmount(afterEach)

async function mountProfile(options) {
  if (options) useApi(options)
  const w = mount(Profile, { attachTo: document.body })
  await flushPromises()
  return w
}
async function pollOnce() {
  await vi.advanceTimersByTimeAsync(POLL_MS)
  await flushPromises()
}
const panel = w => w.find('.resume-refresh')
const checks = w => w.findAll('.rr-check')
const refreshGets = () => api.calls.filter(c => c.url === 'api/applicant/refresh' && c.method === 'GET')
const refreshPosts = () => api.calls.filter(c => c.url === 'api/applicant/refresh' && c.method === 'POST')

// ------------------------------------------------------------------ Q-73: the card

describe('the summary card (Q-73)', () => {
  it('says what the resume gave in plain lines, with no folder or path anywhere', async () => {
    const w = await mountProfile()
    const card = w.find('.resume-card')
    expect(card.find('.ui-card-title').text()).toBe('From your resume')
    expect(card.find('.read-line').text()).toBe('read 24 Sep 18:05')           // no file name (Q-118 LE)
    expect(card.find('.experience').text()).toBe('Experience1 year')            // dt + dd
    expect(card.find('.graduation').text()).toBe('Graduation2025')
    expect(card.find('.experience dt').text()).toBe('Experience')
    expect(card.find('.experience dd').text()).toBe('1 year')
    // the counts moved to their own cards: the skills count is a number in the Skills card
    expect(w.find('.skills-card .skill-count').text()).toBe('3')
    expect(card.find('.skill-count').exists()).toBe(false)
    expect(w.find('.title-count').exists()).toBe(false)
    expect(card.text()).not.toMatch(/[\\/]/)
    expect(card.find('.version').text()).toBe('2')
    expect(card.find('.parsed-by').text()).toBe('qwen3:14b')
    expect(card.find('.summary').text()).toContain('cloud and backend internships')
  })

  it('experience and graduation: under a year, years, and nothing when unknown', async () => {
    for (const [years, want] of [[0, 'Less than a year'], [3, '3 years']]) {
      const w = await mountProfile({ profile: { ...fakeApi().server.profile, years_experience: years } })
      expect(w.find('.experience dt').text()).toBe('Experience')
      expect(w.find('.experience dd').text()).toBe(want)
      w.unmount()
    }
    const w = await mountProfile({ profile: { ...fakeApi().server.profile, years_experience: null, graduation: null } })
    expect(w.find('.experience').exists()).toBe(false)
    expect(w.find('.graduation').exists()).toBe(false)
  })

  // Q-118 LE: "and 3 more" became a toggle that names the total and stays after it opens.
  it('shows the first 12 skills; "Show all 15" shows the rest, "Show fewer" folds them again', async () => {
    const skills = Array.from({ length: 15 }, (_, i) => `skill${i}`)
    const w = await mountProfile({ profile: { ...fakeApi().server.profile, skills } })
    expect(w.find('.skill-count').text()).toBe('15')
    expect(w.findAll('.skills li')).toHaveLength(12)
    expect(w.find('.more-skills').text()).toBe('Show all 15')
    expect(w.find('.more-skills').attributes('aria-expanded')).toBe('false')
    await w.find('.more-skills').trigger('click')
    expect(w.findAll('.skills li')).toHaveLength(15)
    expect(w.find('.more-skills').text()).toBe('Show fewer')
    expect(w.find('.more-skills').attributes('aria-expanded')).toBe('true')
    await w.find('.more-skills').trigger('click')
    expect(w.findAll('.skills li')).toHaveLength(12)
  })

  // The "job titles" count is the title editor's now (its own card); the resume card has
  // no skills or titles line, so this pins the singular forms that remain.
  it('singular wording', async () => {
    const w = await mountProfile({ profile: { ...fakeApi().server.profile, skills: ['go'], target_titles: ['dev'], years_experience: 1 } })
    expect(w.find('.skill-count').text()).toBe('1')
    expect(w.find('.experience dd').text()).toBe('1 year')
    expect(w.find('.more-skills').exists()).toBe(false)           // nothing to expand
  })
})

describe('the job log sits under Details (Q-73)', () => {
  const log = w => w.find('details.job-details')

  it('is collapsed after a successful run, with the new note above it', async () => {
    const w = await mountProfile({ job: RUNNING })
    expect(w.find('.reading').text()).toBe('Reading your resume…')
    api.log('extracting text')
    api.finishJob()
    await pollOnce()
    expect(log(w).exists()).toBe(true)
    expect(log(w).attributes('open')).toBeUndefined()
    expect(log(w).find('summary').text()).toBe('Details')
    expect(w.find('.reading').exists()).toBe(false)
    expect(w.find('.notice.ok').text()).toBe('Resume read: 3 skills, 2 job titles.')
  })

  it('is open after a failure, with the error sentence above it', async () => {
    const w = await mountProfile({ job: RUNNING })
    api.log('boom')
    api.finishJob({ exit_code: 1 })
    await pollOnce()
    expect(log(w).attributes('open')).toBeDefined()
    expect(w.find('.notice.error').text()).toContain('The profile refresh failed')
    expect(w.find('.notice.ok').exists()).toBe(false)
  })

  it('"Profile refreshed." stays only when the server then reports no profile', async () => {
    const w = await mountProfile({ job: RUNNING })
    api.finishJob()
    api.server.profile = { ...api.server.profile, present: false }
    await pollOnce()
    expect(w.find('.notice.ok').text()).toBe('Profile refreshed.')
  })
})

// ------------------------------------------------------------------ R10: the panel

describe('Update your application details (R10)', () => {
  it('lists each change with its label, entry and before -> after; kept rows have no checkbox', async () => {
    const w = await mountProfile({ refresh: PLAN() })
    expect(panel(w).find('h3').text()).toBe('Update your application details')
    expect(panel(w).find('.rr-intro').text()).toContain('Entries you edited yourself are never changed')
    const row = id => panel(w).find(`.rr-check[data-id="${id}"]`).element.closest('.rr-row')
    const part = (r, cls) => r.querySelector(cls)?.textContent.trim()
    const rm = row('experience:remove:example pte ltd|software engineering intern')
    expect(part(rm, '.rr-op')).toBe('Remove: example from the template')
    expect(part(rm, '.rr-list-name')).toBe('· Experience')
    expect(part(rm, '.rr-entry')).toBe('Example Pte Ltd · Software Engineering Intern · May 2024 – Aug 2024')
    expect(rm.querySelector('.rr-note')).toBeNull()            // a remove's note repeats its label
    const add = row('experience:add:acme|intern')
    expect(part(add, '.rr-op')).toBe('Add')
    expect(part(add, '.rr-entry')).toBe('Acme · Intern · May 2024 – Aug 2024')
    const upd = row('experience:update:beta|analyst')
    expect(part(upd, '.rr-op')).toBe('Update')
    expect(part(upd, '.rr-before')).toBe('Beta · Analyst · Jan 2023 – Jun 2023')
    expect(part(upd, '.rr-after')).toBe('Beta · Analyst · Jan 2023 – Present')
    expect(part(upd, '.rr-arrow')).toContain('becomes')
    const gone = row('education:remove:old u|old degree')
    expect(part(gone, '.rr-op')).toBe('Remove: no longer on your resume')
    expect(part(gone, '.rr-list-name')).toBe('· Education')
    expect(part(gone, '.rr-entry')).toBe('Old U · Old degree · Jan 2010 – Jan 2012')
    const edu = row('education:add:nus|bsc')
    expect(part(edu, '.rr-entry')).toBe('NUS · BSc')            // no dates: none invented
    expect(part(edu, '.rr-note')).toContain('Dates not understood ("2021 – 2025")')
    expect(part(edu, '.rr-note')).toContain('Resume says: Honours')
    const kept = panel(w).find('.rr-kept')
    expect(kept.text()).toContain('Kept: you edited this')
    expect(kept.text()).toContain('Mine · Tutor')
    expect(kept.find('input').exists()).toBe(false)
    const skillsRow = panel(w).find('.rr-skills')
    expect(skillsRow.find('label').text()).toBe('Add 2 skills from your resume:')
    expect(skillsRow.findAll('.rr-chips li').map(li => li.text())).toEqual(['Go', 'Rust'])
    expect(skillsRow.find('.rr-more-skills').exists()).toBe(false)
    expect(panel(w).find('.rr-details').text()).toContain('Not on your resume, so not added: Docker, Terraform')
  })

  it('the template skills row says Replace', async () => {
    const plan = PLAN()
    plan.changes.find(c => c.id === 'skills:add').op = 'replace'
    plan.changes.find(c => c.id === 'skills:add').id = 'skills:replace'
    const w = await mountProfile({ refresh: plan })
    const row = panel(w).find('.rr-skills')
    expect(row.find('label').text()).toBe('Replace the example skills with 2 skills from your resume:')
    expect(row.findAll('.rr-chips li').map(li => li.text())).toEqual(['Go', 'Rust'])
  })

  it('a long skills list shows 12 chips and an "and N more" toggle that expands and collapses', async () => {
    const plan = PLAN()
    plan.skills.add = Array.from({ length: 30 }, (_, i) => `Skill${i + 1}`)
    const w = await mountProfile({ refresh: plan })
    const row = panel(w).find('.rr-skills')
    expect(row.find('label').text()).toBe('Add 30 skills from your resume:')
    expect(row.findAll('.rr-chips li')).toHaveLength(12)
    const toggle = row.find('.rr-more-skills')
    expect(toggle.text()).toBe('and 18 more')
    expect(toggle.attributes('aria-expanded')).toBe('false')
    // the toggle is not inside the label, so it never flips the checkbox
    expect(row.find('label .rr-more-skills').exists()).toBe(false)
    const before = row.find('input').element.checked
    await toggle.trigger('click')
    expect(row.findAll('.rr-chips li')).toHaveLength(30)
    expect(row.find('.rr-more-skills').text()).toBe('Show fewer')
    expect(row.find('input').element.checked).toBe(before)
    await row.find('.rr-more-skills').trigger('click')
    expect(row.findAll('.rr-chips li')).toHaveLength(12)
  })

  it('ticks what the server says is on by default, and the Save button counts the ticks', async () => {
    const w = await mountProfile({ refresh: PLAN() })
    const state = Object.fromEntries(checks(w).map(c => [c.attributes('data-id'), c.element.checked]))
    expect(state).toEqual({
      'experience:remove:example pte ltd|software engineering intern': true,
      'experience:add:acme|intern': true,
      'experience:update:beta|analyst': true,
      'education:add:nus|bsc': false,                      // dates not understood: not ticked
      'education:remove:old u|old degree': true,
      'skills:add': true,
    })
    expect(w.find('.rr-save').text()).toBe('Save 5 changes')
    await checks(w)[3].setValue(true)
    expect(w.find('.rr-save').text()).toBe('Save 6 changes')
    for (const c of checks(w)) await c.setValue(false)
    expect(w.find('.rr-save').text()).toBe('Save 0 changes')
    expect(w.find('.rr-save').attributes('disabled')).toBeDefined()
    await checks(w)[0].setValue(true)
    expect(w.find('.rr-save').text()).toBe('Save 1 change')
  })

  it('saving posts {etag, accept} with exactly the ticked ids, then says what happened', async () => {
    const w = await mountProfile({ refresh: PLAN() })
    api.server.refreshAfter = { state: 'ready', source_name: 'resume.pdf', resume_hash: 'sha256:r1', etag: 'etag-after', changes: [], skills: { add: [], not_on_resume: [] } }
    await checks(w)[1].setValue(false)                      // un-tick the Add
    await w.find('.rr-save').trigger('click')
    await flushPromises()
    expect(refreshPosts()).toHaveLength(1)
    const body = JSON.parse(refreshPosts()[0].body)
    expect(body.etag).toBe('e1')
    expect(body.accept.sort()).toEqual([
      'education:remove:old u|old degree',
      'experience:remove:example pte ltd|software engineering intern',
      'experience:update:beta|analyst',
      'skills:add',
    ].sort())
    expect(w.find('.rr-saved').text()).toContain('Saved 4 changes. Check them in Application details.')
    expect(w.find('.rr-saved').attributes('role')).toBe('status')
    expect(w.find('.rr-list').exists()).toBe(false)
  })

  it('"Application details" in the saved line opens that view', async () => {
    const w = await mountProfile({ refresh: PLAN() })
    api.server.refreshAfter = { ...PLAN(), changes: [] }
    await w.find('.rr-save').trigger('click')
    await flushPromises()
    expect(w.find('.view-details').attributes('aria-selected')).toBe('false')
    await w.find('.rr-go').trigger('click')
    await flushPromises()
    expect(w.find('.view-details').attributes('aria-selected')).toBe('true')
    expect(panel(w).exists()).toBe(false)                   // the resume view is gone
  })

  it('Not now hides it until the next resume (remembered by its hash)', async () => {
    const w = await mountProfile({ refresh: PLAN() })
    await w.find('.rr-not-now').trigger('click')
    expect(panel(w).exists()).toBe(false)
    expect(window.localStorage.getItem('profile.refresh.dismissed')).toBe('sha256:r1')
    w.unmount()
    const again = await mountProfile({ refresh: PLAN() })                 // same resume: still hidden
    expect(panel(again).exists()).toBe(false)
    again.unmount()
    const next = PLAN()
    next.resume_hash = 'sha256:r2'                                        // a new resume: it comes back
    const fresh = await mountProfile({ refresh: next })
    expect(panel(fresh).exists()).toBe(true)
  })

  it('a conflict says to reload, and Reload asks again', async () => {
    const w = await mountProfile({ refresh: PLAN() })
    api.server.refreshPost = { status: 409, detail: 'changed' }
    await w.find('.rr-save').trigger('click')
    await flushPromises()
    expect(w.find('.rr-conflict').text()).toContain('Your details changed in another window. Reload to see the latest.')
    const before = refreshGets().length
    await w.find('.rr-reload').trigger('click')
    await flushPromises()
    expect(refreshGets().length).toBe(before + 1)
  })

  it('a stale answer to Save turns the panel into the older-resume sentence', async () => {
    const w = await mountProfile({ refresh: PLAN() })
    api.server.refreshPost = { status: 409, detail: 'stale' }
    await w.find('.rr-save').trigger('click')
    await flushPromises()
    expect(w.find('.rr-stale').text()).toContain('This was checked against an older resume')
  })

  it('a server that rejects the save says nothing was saved', async () => {
    const w = await mountProfile({ refresh: PLAN() })
    api.server.refreshPost = { status: 500, detail: 'disk full' }
    await w.find('.rr-save').trigger('click')
    await flushPromises()
    expect(w.find('.rr-problem').text()).toContain("Couldn't save these changes")
    expect(w.find('.rr-save').attributes('disabled')).toBeUndefined()
  })

  it('says so when nothing differs', async () => {
    const w = await mountProfile({ refresh: { ...PLAN(), changes: [], skills: { add: [], not_on_resume: [] } } })
    expect(w.find('.rr-empty').text()).toBe('Your application details match your resume.')
    expect(w.find('.rr-save').exists()).toBe(false)
  })

  it('says to re-read when the proposals are for an older resume, naming the button as built', async () => {
    const w = await mountProfile({ refresh: { state: 'stale' } })
    expect(w.find('.rr-stale').text()).toContain('Choose "Re-read resume" to check again.')
    // ... and that button exists with exactly that name
    expect(w.find('button.refresh').text()).toBe('Re-read resume')
  })

  it('is absent for none, no_profile and unreadable, and quiet on a server without the route (404)', async () => {
    for (const refresh of [{ state: 'none' }, { state: 'no_profile' }, { state: 'unreadable' }, null]) {
      const w = await mountProfile({ refresh })
      expect(panel(w).exists(), JSON.stringify(refresh)).toBe(false)
      expect(w.find('.notice.error').exists()).toBe(false)
      w.unmount()
    }
  })

  it('says the model is not running when the profile job logged the skip line', async () => {
    const w = await mountProfile({ job: RUNNING, refresh: null })
    api.log(SKIP_LINE)
    api.finishJob()
    await pollOnce()
    expect(w.find('.rr-unavailable').text()).toContain("the AI model isn't running")
    expect(w.find('.rr-unavailable').text()).toContain('Start Ollama')
    expect(w.find('.rr-unavailable').text()).toContain('choose "Re-read resume"')   // the button's name (Q-118 LE2)
  })

  it('does not say that when the check ran', async () => {
    const w = await mountProfile({ job: RUNNING, refresh: null })
    api.log('application details check: 2 changes to review')
    api.finishJob()
    await pollOnce()
    expect(w.find('.rr-unavailable').exists()).toBe(false)
  })

  it('looks again after each profile job', async () => {
    const w = await mountProfile({ job: RUNNING, refresh: { state: 'none' } })
    expect(panel(w).exists()).toBe(false)
    const before = refreshGets().length
    api.server.refresh = PLAN()
    api.finishJob()
    await pollOnce()
    expect(refreshGets().length).toBeGreaterThan(before)
    expect(panel(w).exists()).toBe(true)
  })
})

// ------------------------------------------------------------------ R5: shared skill labels

describe('skillLabel shares its cases with the Python twin (R5)', () => {
  it('every case in tests/fixtures/skill_labels.json', () => {
    expect(skillCases.cases.length).toBeGreaterThanOrEqual(8)
    for (const [raw, want] of skillCases.cases) expect(skillLabel(raw), raw).toBe(want)
  })
})
