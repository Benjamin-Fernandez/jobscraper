// Q-121 lane P (D-229): the three consent SWITCHES in Your details -> Consents and declarations, as the
// page's pure helpers (detailSections.js) read them. Off by default; a switch that is off is a decision,
// never "missing", never "needed"; the section summary is unchanged until one is on. The server marks
// the three items `default_off: true` (tests/test_q121_switches.py pins that). Made-up data. No network.
import { describe, expect, it } from 'vitest'
import { detailsNeeded, sectionState, sectionSummary, statusLine } from '../src/detailSections.js'

const item = (path, label, flags = {}) => ({
  path, label, kind: 'bool', options: [], help: '', sub: [], required: false, recommended: false, sensitive: false, ...flags,
})
const OLD = [
  item('consents.privacy_consent', 'I consent to employers processing my application data'),
  item('consents.data_retention_consent', 'Employers may keep my data for future roles'),
  item('consents.talent_pool_opt_in', 'Add me to talent pools'),
  item('consents.certify_true', 'I certify the information I give is true and complete'),
]
const SWITCHES = [
  item('consents.group_sharing', 'Employers may share my application within their own group of companies', { default_off: true, help: 'When off, JobScraper stops any application whose form requires it.' }),
  item('consents.third_party_sharing', 'Employers may share my details with other companies', { default_off: true }),
  item('consents.background_checks', 'Employers may run background, reference and record checks', { default_off: true }),
]
const FORM = [
  { id: 'consents', title: 'Consents', note: '', items: [...OLD, ...SWITCHES] },
  { id: 'declarations', title: 'Declarations', note: '', items: [item('declarations.pep', 'Are you a politically exposed person?')] },
]
const SECTION = { id: 'consents_declarations', title: 'Consents and declarations', paths: [...OLD, ...SWITCHES].map(i => i.path).concat('declarations.pep') }
const OLD_ON = { privacy_consent: true, data_retention_consent: true, talent_pool_opt_in: true, certify_true: true }
const summary = consents => sectionSummary(SECTION, { consents }, FORM)

describe('P4: the section summary with the switches', () => {
  it('four given and every switch off (unset or false) reads exactly as before', () => {
    expect(summary({ ...OLD_ON })).toBe('Consents given')
    expect(summary({ ...OLD_ON, group_sharing: false, third_party_sharing: false, background_checks: false })).toBe('Consents given')
    expect(summary({ ...OLD_ON, talent_pool_opt_in: false })).toBe('3 of 4 consents given')
    expect(summary({})).not.toMatch(/switch|sharing|checks/i)
  })

  it('one on adds a clause, three on say they are agreed, and the four-consent count never moves', () => {
    const one = summary({ ...OLD_ON, background_checks: true })
    expect(one).toContain('Consents given')
    expect(one).toContain('1 of 3 sharing and check switches on')
    const two = summary({ ...OLD_ON, group_sharing: true, third_party_sharing: true })
    expect(two).toContain('2 of 3 sharing and check switches on')
    const all = summary({ ...OLD_ON, group_sharing: true, third_party_sharing: true, background_checks: true })
    expect(all).toContain('Consents given')
    expect(all).toContain('sharing and checks agreed')
    expect(all).not.toMatch(/of 4/)
  })

  it('a switch on does not turn "No consents given" into a count of five or seven', () => {
    const s = summary({ group_sharing: true })
    expect(s).toContain('No consents given')
    expect(s).not.toMatch(/of 7|of 5/)
  })
})

describe('P4: a switch that is off is never missing, needed or "to fill"', () => {
  const ctx = (over = {}) => ({ form: FORM, profile: { consents: { ...OLD_ON } }, missing: [], neededBy: {}, errors: [], ...over })

  it('the section reads Complete with all three off, and the status line is ready', () => {
    const s = sectionState(SECTION, ctx())
    expect(s.needed).toBe(0)
    expect(s.status).not.toBe('needed')
    expect(s.toFill).toBe(0)
    expect(s.text).toBe('Complete')
    const line = statusLine({ form: FORM, needed: detailsNeeded([], {}, FORM) })
    expect(line.ready).toBe(true)
    expect(line.count).toBe(0)
  })

  it('what the server does not send as needed never appears; a real missing item still does', () => {
    // the server leaves default-off switches out of `needed_by` and `missing` (tests/test_q121_switches.py)
    expect(detailsNeeded([], {}, FORM)).toEqual([])
    const s = sectionState(SECTION, ctx({ missing: ['consents.privacy_consent'], profile: {} }))
    expect(s.status).toBe('needed')
    expect(s.needed).toBe(1)
  })

  it('an item the server marks default_off with an unset value is not a gap even if flagged recommended-free', () => {
    const s = sectionState(SECTION, ctx({ profile: { consents: { ...OLD_ON, group_sharing: false } } }))
    expect(s.status).toBe('complete')
  })
})
