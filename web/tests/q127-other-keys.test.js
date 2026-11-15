// Q-127 pin 21 (design B.4 "extra errors", B.8): "Other keys in your file" never lists `extra.*`.
// Saved answers (the `extra` block, written by "Use a different answer next time") live in
// Settings -> Apply -> Answers you corrected, never on the Profile page, so no `extra` leaf may
// appear in the disclosure, whatever its shape, scope, kind or validity. Made-up names only.
import { describe, expect, it } from 'vitest'
import { otherKeys } from '../src/applicantForm.js'

const FORM = [{ id: 'identity', title: 'Identity', items: [{ path: 'identity.first_name', label: 'First name', kind: 'text', sub: [] }] }]

describe('Q-127 Other keys never lists extra.*', () => {
  const entry = (over = {}) => ({
    title: 'Where would you like to work', description: '', kind: 'text', sensitive: false,
    labels: ['where would you like to work'], value: 'Remote', ...over,
  })

  it('lists none of a saved answer: its value, labels, scope or choice picks', () => {
    const profile = {
      identity: { first_name: 'Alex' },
      extra: {
        work_mode: entry({ employer: 'Example Co' }),
        notice: entry({ kind: 'number', value: 30, labels: ['how much notice do you need'] }),
        pick: entry({ kind: 'choice', value: null, picks: ['remote'], seen: ['remote', 'hybrid'] }),
        scoped: entry({ by_employer: { 'example co': { value: 'x' } } }),
        promoted: entry({ promoted: true, labels: [] }),
      },
    }
    expect(otherKeys(profile, FORM)).toEqual([])
  })

  it('lists none of an invalid saved answer named after an employer wording', () => {
    const profile = {
      identity: { first_name: 'Alex' },
      extra: { why_example_co: { kind: 'number', value: 'not a number', labels: [] } },
    }
    expect(otherKeys(profile, FORM)).toEqual([])
  })

  it('still lists an unknown key outside extra', () => {
    const profile = { identity: { first_name: 'Alex', mystery: 'x' }, extra: { work_mode: entry() } }
    expect(otherKeys(profile, FORM).map(k => k.path)).toEqual(['identity.mystery'])
  })
})
