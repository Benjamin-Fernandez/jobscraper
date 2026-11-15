// Q-127 pin 7 (design B.4, B.8): section summaries, completeness and the status line as PURE functions
// of detailSections.js, including "{n} entries · {first title}". Made-up people only. No Vue, no network.
import { describe, expect, it } from 'vitest'
import {
  NOTHING_YET, applyAgainText, detailsNeeded, neededByText, newlyReady, sectionState, sectionSummary,
  statusLine, waitingNoticeText, withoutExtraErrors,
} from '../src/detailSections.js'

const item = (path, label, kind, flags = {}, extra = {}) => ({
  path, label, kind, options: [], help: '', sub: [], required: false, recommended: false, sensitive: false, ...flags, ...extra,
})
const FORM = [
  { id: 'contact', title: 'Contact', note: '', items: [
    item('contact.email', 'Email for applications', 'email', { required: true }),
    item('contact.city', 'City', 'text', { required: true }),
    item('contact.postal_code', 'Postal code', 'digits', { recommended: true }),
  ] },
  { id: 'education', title: 'Education', note: '', items: [item('education', 'Education', 'entries', { required: true })] },
  { id: 'experience', title: 'Experience', note: '', items: [item('experience', 'Experience', 'entries')] },
  { id: 'pay', title: 'Pay', note: '', items: [item('pay.expected_salary', 'Expected salary', 'salary', { required: true })] },
]
const sec = (id, paths) => ({ id, title: id, paths })
const CONTACT = sec('contact', ['contact.email', 'contact.city', 'contact.postal_code'])
const EDUCATION = sec('education', ['education'])
const EXPERIENCE = sec('experience', ['experience'])

describe('Q-127 pin 7: section summaries', () => {
  it('an empty or missing section says "Nothing filled yet"', () => {
    expect(NOTHING_YET).toBe('Nothing filled yet')
    expect(sectionSummary(CONTACT, {}, FORM)).toBe(NOTHING_YET)
    expect(sectionSummary(null, {}, FORM)).toBe(NOTHING_YET)
    expect(sectionSummary(EDUCATION, { education: [] }, FORM)).toBe(NOTHING_YET)
  })

  it('entries read "{n} entries · {first title}", singular for one', () => {
    const edu = { education: [{ degree: 'BSc Computing', institution: 'Example University' }, { institution: 'Northwind College' }] }
    expect(sectionSummary(EDUCATION, edu, FORM)).toBe('2 entries · BSc Computing')
    expect(sectionSummary(EDUCATION, { education: [{ institution: 'Example University' }] }, FORM)).toBe('1 entry · Example University')
    const exp = { experience: [{ title: 'Analyst', employer: 'Acme Trading' }, { title: 'Intern', employer: 'Northwind' }, { title: 'Tutor' }] }
    expect(sectionSummary(EXPERIENCE, exp, FORM)).toBe('3 entries · Analyst')
  })

  it('a blank or from-resume-only entry is not counted', () => {
    const edu = { education: [{ degree: '', institution: '' }, { from_resume: true }, { degree: 'MSc Data', institution: '' }] }
    expect(sectionSummary(EDUCATION, edu, FORM)).toBe('1 entry · MSc Data')
  })

  it('contact joins the filled parts with " · "', () => {
    const p = { contact: { email: 'sam.sample@example.com', phone_country_code: '+65', phone_number: '81234567' } }
    expect(sectionSummary(CONTACT, p, FORM)).toBe('sam.sample@example.com · +65 81234567')
  })

  it('the summary never contains an employer wording, a question label or a saved answer', () => {
    const p = { education: [{ degree: 'BSc', institution: 'Example University' }],
      extra: { why_example_co: { title: 'Why Example Co?', value: 'Because', labels: ['why example co'] } } }
    for (const s of [CONTACT, EDUCATION, EXPERIENCE]) {
      const text = sectionSummary(s, p, FORM)
      expect(text).not.toMatch(/why example co|because/i)
    }
  })
})

describe('Q-127 pin 7: completeness and the status line', () => {
  const ctx = (over = {}) => ({ form: FORM, profile: {}, missing: [], neededBy: {}, errors: [], ...over })

  it('Needed when a required item is empty, "{n} to fill" for recommended ones, otherwise Complete', () => {
    const needed = sectionState(CONTACT, ctx({ missing: ['contact.email'] }))
    expect([needed.status, needed.text, needed.tone, needed.needed]).toEqual(['needed', 'Needed', 'warn', 1])
    const fill = sectionState(CONTACT, ctx({ profile: { contact: { email: 'a@example.com', city: 'Singapore' } } }))
    expect([fill.status, fill.text, fill.toFill]).toEqual(['fill', '1 to fill', 1])
    const done = sectionState(CONTACT, ctx({ profile: { contact: { email: 'a@example.com', city: 'Singapore', postal_code: '000001' } } }))
    expect([done.status, done.text, done.tone]).toEqual(['complete', 'Complete', 'ok'])
  })

  it('a waiting application makes its section Needed, and the count reads "Needed by n applications"', () => {
    const s = sectionState(CONTACT, ctx({ neededBy: { 'contact.city': 3 } }))
    expect(s.status).toBe('needed')
    expect(neededByText(3)).toBe('Needed by 3 applications')
    expect(neededByText(1)).toBe('Needed by 1 application')
  })

  it('errors on a section\'s paths read "Fix n" and an error elsewhere does not', () => {
    const s = sectionState(CONTACT, ctx({ errors: [{ path: 'contact.email', message: 'bad' }, { path: 'education[0].degree', message: 'x' }] }))
    expect([s.fix, s.fixText]).toEqual([1, 'Fix 1'])
    expect(sectionState(EDUCATION, ctx()).fixText).toBe('')
  })

  it('detailsNeeded counts a field once, not the field and its sub-path (the shell badge)', () => {
    expect(detailsNeeded(['contact.city', 'contact.email'], { 'contact.city': 2 })).toEqual(['contact.city', 'contact.email'])
    expect(detailsNeeded(['pay.expected_salary'], { 'pay.expected_salary.amount': 2 }, FORM)).toHaveLength(1)
  })

  it('the status line: ready, or what auto-apply waits for, never a question or an employer', () => {
    expect(statusLine({ form: FORM, needed: [] })).toMatchObject({ ready: true, count: 0, badge: 'Ready for auto-apply', text: 'Your required details are filled in.' })
    const s = statusLine({ form: FORM, needed: ['contact.email', 'contact.city'], waiting: [{ job_id: 'a', ready: false }, { job_id: 'b', ready: true }] })
    expect(s.badge).toBe('2 details needed')
    expect(s.text).toBe('Auto-apply waits until these are filled: Email for applications, City.')
    expect(s.waitingText).toBe('1 application is waiting for a detail below.')
    expect(statusLine({ form: FORM, needed: ['contact.city'], waiting: [{ ready: false }, { ready: false }] }).waitingText)
      .toBe('2 applications are waiting for a detail below.')
    expect(statusLine({ form: FORM, needed: [], extraErrors: 2 }).attentionText)
      .toBe('A saved answer needs attention. Open Settings → Apply → Answers you corrected.')
    expect(statusLine({ form: FORM, needed: [] }).attentionText).toBe('')
  })

  it('an extra.* error is never kept for the page (M4)', () => {
    const errs = [{ path: 'extra.why_example_co.value', message: 'must be a number' }, { path: 'contact.email', message: 'bad' }, { path: 'extra', message: 'x' }]
    expect(withoutExtraErrors(errs).map(e => e.path)).toEqual(['contact.email'])
  })

  it('the waiting notice and the Apply again button read as designed; only newly ready roles count', () => {
    expect(waitingNoticeText(1)).toBe('Saved. 1 application was waiting for this.')
    expect(waitingNoticeText(4)).toBe('Saved. 4 applications were waiting for this.')
    expect(applyAgainText(1)).toBe('Apply again to 1 application')
    expect(applyAgainText(4)).toBe('Apply again to 4 applications')
    const before = [{ job_id: 'a', ready: false, paths: ['contact.city'] }, { job_id: 'b', ready: true, paths: ['contact.city'] }]
    const after = [
      { job_id: 'a', ready: true, paths: ['contact.city'] }, { job_id: 'b', ready: true, paths: ['contact.city'] },
      { job_id: 'c', ready: true, paths: ['education[0].grade'] }, { job_id: 'd', ready: false, paths: ['contact.city'] },
    ]
    expect(newlyReady(CONTACT, before, after).map(w => w.job_id)).toEqual(['a'])
  })
})
