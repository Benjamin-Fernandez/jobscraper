// Q-39 pins for Q-30 review finding F2 (docs/reviews/Q-30.md): `mergeEdits(before, draft, fromFile)` in
// web/src/applicantForm.js. The Profile form keeps the owner's unsaved edits when the Questions card rewrites
// the file, but only the leaves the owner changed. Merging whole sections wrote an old value of another leaf
// back over a profile-gap answer ("Save details" then lost the answer). Pure function, synthetic data.
import { describe, expect, it } from 'vitest'
import { mergeEdits } from '../src/applicantForm.js'

const copy = v => JSON.parse(JSON.stringify(v))

// Runs the merge and checks it neither changed an input nor aliases one in its result.
function merge(before, draft, fromFile) {
  const snap = [copy(before ?? null), copy(draft ?? null), copy(fromFile ?? null)]
  const out = mergeEdits(before, draft, fromFile)
  expect([copy(before ?? null), copy(draft ?? null), copy(fromFile ?? null)]).toEqual(snap)
  return out
}

describe('mergeEdits: only the leaves the owner changed come from the draft', () => {
  it('with no edits the result is the file, whatever changed in it meanwhile', () => {
    const before = { contact: { city: 'SG', address_line1: '' }, pay: { currency: 'SGD' } }
    const file = { contact: { city: 'SG', address_line1: '1 Road' }, pay: { currency: 'USD' }, extra: { k: { value: 'v' } } }
    expect(merge(before, copy(before), file)).toEqual(file)
  })

  it('takes the typed leaf from the draft and every other leaf from the file', () => {
    const before = { contact: { city: 'SG', address_line1: '', postal_code: '000001' } }
    const draft = { contact: { city: 'Typed City', address_line1: '', postal_code: '000001' } }
    const file = { contact: { city: 'SG', address_line1: '1 Road', postal_code: '000001' } }
    expect(merge(before, draft, file)).toEqual({ contact: { city: 'Typed City', address_line1: '1 Road', postal_code: '000001' } })
  })

  it('keeps a profile-gap answer the Questions card saved into a section the owner also edited (F2)', () => {
    // The card wrote contact.address_line1, a key the form had never held. Contact is edited here too.
    const before = { contact: { email: 'a@example.com', city: 'SG' } }
    const draft = { contact: { email: 'a@example.com', city: 'Typed City' } }
    const file = { contact: { email: 'a@example.com', city: 'SG', address_line1: '1 Road' } }
    const out = merge(before, draft, file)
    expect(out.contact.address_line1).toBe('1 Road')
    expect(out.contact.city).toBe('Typed City')
    // and a whole section the owner did not touch is simply the file's
    const withNew = merge({ ...before, pay: {} }, { ...draft, pay: {} }, { ...file, availability: { notice_period_days: 30 } })
    expect(withNew.availability).toEqual({ notice_period_days: 30 })
  })

  it('merges into a section the owner created from nothing when the file has one too', () => {
    const out = merge({}, { contact: { city: 'Typed City' } }, { contact: { address_line1: '1 Road' } })
    expect(out).toEqual({ contact: { address_line1: '1 Road', city: 'Typed City' } })
  })

  it('keeps a section the owner created when the file has none', () => {
    expect(merge({}, { links: { github: 'https://example.com/me' } }, {})).toEqual({ links: { github: 'https://example.com/me' } })
  })

  it('a leaf the owner cleared (key removed in the draft) is removed, the rest is the file', () => {
    const before = { identity: { preferred_name: 'Lex', pronouns: 'they/them' } }
    const draft = { identity: { pronouns: 'they/them' } }
    const file = { identity: { preferred_name: 'Lex', pronouns: 'they/them', title: 'Mx' } }
    expect(merge(before, draft, file)).toEqual({ identity: { pronouns: 'they/them', title: 'Mx' } })
  })

  it('tolerates a missing before, draft or file', () => {
    expect(mergeEdits(undefined, undefined, undefined)).toEqual({})
    expect(mergeEdits(undefined, undefined, { a: 1 })).toEqual({ a: 1 })
    expect(mergeEdits({}, { a: 2 }, undefined)).toEqual({ a: 2 })
  })

  it('returns a copy: changing the result does not reach the file object or the draft', () => {
    const file = { contact: { city: 'SG' }, languages: [{ language: 'English' }] }
    const draft = { contact: { city: 'Typed City' }, languages: [{ language: 'English' }] }
    const out = mergeEdits({ contact: { city: 'SG' }, languages: [{ language: 'English' }] }, draft, file)
    out.contact.city = 'Changed'
    out.languages[0].language = 'Changed'
    expect(file.contact.city).toBe('SG')
    expect(file.languages[0].language).toBe('English')
    expect(draft.contact.city).toBe('Typed City')
  })
})

describe('mergeEdits: the same leaf changed here and in the file', () => {
  it('the file wins: the answer just saved is the newer, deliberate one', () => {
    const before = { contact: { address_line1: '' } }
    const draft = { contact: { address_line1: 'Typed Street' } }
    const file = { contact: { address_line1: '1 Road' } }
    expect(merge(before, draft, file)).toEqual({ contact: { address_line1: '1 Road' } })
  })

  it('the file wins for a leaf the file removed while the owner edited it', () => {
    const before = { contact: { city: 'SG', address_line1: 'Old' } }
    const draft = { contact: { city: 'SG', address_line1: 'Typed Street' } }
    const file = { contact: { city: 'SG' } }
    expect(merge(before, draft, file)).toEqual({ contact: { city: 'SG' } })
  })

  it('the file wins when both made the same change (nothing to add)', () => {
    const before = { contact: { city: 'SG' } }
    expect(merge(before, { contact: { city: 'KL' } }, { contact: { city: 'KL' } })).toEqual({ contact: { city: 'KL' } })
  })
})

describe('mergeEdits: lists merge per entry', () => {
  const e0 = { institution: 'Example University', grade: '', from_resume: true }

  it('an edited entry field is the draft\'s, a file-side field of the same entry is the file\'s', () => {
    const before = { education: [e0] }
    const draft = { education: [{ ...e0, institution: 'Typed University' }] }
    const file = { education: [{ ...e0, grade: 'First Class' }] }
    expect(merge(before, draft, file)).toEqual({ education: [{ institution: 'Typed University', grade: 'First Class', from_resume: true }] })
  })

  it('an entry the owner appended is added after the file\'s entries', () => {
    const added = { institution: 'Added College', grade: '' }
    expect(merge({ education: [e0] }, { education: [e0, added] }, { education: [e0] })).toEqual({ education: [e0, added] })
    const fileAlsoGrew = { institution: 'File College', grade: '' }
    expect(merge({ education: [e0] }, { education: [e0, added] }, { education: [e0, fileAlsoGrew] }))
      .toEqual({ education: [e0, fileAlsoGrew, added] })
  })

  it('a list the owner shortened is taken whole when the file did not change it', () => {
    const [a, b, c] = ['a', 'b', 'c'].map(language => ({ language }))
    expect(merge({ languages: [a, b, c] }, { languages: [a, c] }, { languages: [a, b, c] })).toEqual({ languages: [a, c] })
  })

  it('a list the owner shortened loses to a file that changed it', () => {
    const [a, b, c] = ['a', 'b', 'c'].map(language => ({ language }))
    const d = { language: 'd' }
    expect(merge({ languages: [a, b, c] }, { languages: [a, c] }, { languages: [a, b, c, d] })).toEqual({ languages: [a, b, c, d] })
  })

  it('a list of plain strings merges per entry too: an appended string goes after the file\'s', () => {
    expect(merge({ tags: ['x'] }, { tags: ['x', 'y'] }, { tags: ['x'] })).toEqual({ tags: ['x', 'y'] })
    expect(merge({ tags: ['x'] }, { tags: ['x', 'y'] }, { tags: ['z'] })).toEqual({ tags: ['z', 'y'] })
  })
})

describe('mergeEdits: the `extra` answers', () => {
  const entry = value => ({ title: 'Favourite', kind: 'text', sensitive: false, value, labels: ['favourite'] })

  it('an answer edited here and a new answer that arrived from the file are both kept', () => {
    const before = { extra: { visa: entry('a') } }
    const draft = { extra: { visa: entry('typed') } }
    const file = { extra: { visa: entry('a'), fav: entry('new') } }
    const out = merge(before, draft, file)
    expect(out.extra.visa.value).toBe('typed')
    expect(out.extra.fav.value).toBe('new')
  })

  it('an answer removed here stays removed while the file\'s other answers are kept', () => {
    const before = { extra: { visa: entry('a'), fav: entry('b') } }
    const draft = { extra: { fav: entry('b') } }
    const file = { extra: { visa: entry('a'), fav: entry('b'), other: entry('c') } }
    expect(Object.keys(merge(before, draft, file).extra).sort()).toEqual(['fav', 'other'])
  })

  it('an employer-scoped pick set edited here merges below the entry', () => {
    const scoped = (global, shop) => ({ kind: 'choice', picks: [global], by_employer: { shopee: { picks: [shop] } } })
    const before = { extra: { visa: scoped('citizen', 'pr') } }
    const draft = { extra: { visa: scoped('citizen', 'others') } }
    const file = { extra: { visa: scoped('pr', 'pr') } }                 // the base pick changed in the file
    const out = merge(before, draft, file)
    expect(out.extra.visa.picks).toEqual(['pr'])
    expect(out.extra.visa.by_employer.shopee.picks).toEqual(['others'])
  })
})
