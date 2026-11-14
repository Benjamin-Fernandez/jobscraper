// Q-125: `experience[].also_known_as` is an entry sub-field of kind `list_text` (chips plus an add box).
// The form is metadata-driven: nothing in FieldInput names the field, so this pins the generic
// path with the shipped sub-field shape (tests/test_apply_employer_aka.py pins the shape itself).
// Made-up employer names only. No network.
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import FieldInput from '../src/components/FieldInput.vue'
import { otherKeys } from '../src/applicantForm.js'

const AKA = {
  path: 'also_known_as', label: 'Also known as', kind: 'list_text', options: [], sub: [], required: false,
  help: "Other names of this employer, such as the group or parent company. Used to answer 'Have you worked for us before?' truthfully.",
}
const SUB = [
  { path: 'employer', label: 'Employer', kind: 'text' },
  { path: 'title', label: 'Job title', kind: 'text' },
  AKA,
]
const mountJobs = (value, errors = {}) => mount(FieldInput, {
  props: { kind: 'entries', id: 'f-exp', path: 'experience', label: 'Experience', sub: SUB, entryLabel: 'Job', modelValue: value, errors },
})

describe('Q-125 experience entry: Also known as', () => {
  const jobs = [{ employer: 'Sample Analytics', title: 'Analyst', also_known_as: ['Northwind', 'NW Bank'] }]

  it('renders chips plus an add box under the label "Also known as"', () => {
    const w = mountJobs(jobs)
    const label = w.findAll('label').find(l => l.text() === 'Also known as')
    expect(label).toBeTruthy()
    const chips = w.findAll('.chips-input .chip').map(c => c.text())
    expect(chips).toEqual(['Northwind', 'NW Bank'])
    expect(w.find('.chips-input input').attributes('id')).toBe(label.attributes('for'))
    expect(w.text()).toContain('Have you worked for us before?')          // the help text
  })

  it('adding a name emits the entry with the extended list; a null value starts empty', async () => {
    const w = mountJobs([{ employer: 'Sample Analytics', title: 'Analyst', also_known_as: null }])
    expect(w.findAll('.chips-input .chip')).toHaveLength(0)
    const box = w.find('.chips-input input')
    await box.setValue('  Northwind   Group ')
    await box.trigger('keydown.enter')
    const out = w.emitted('update:modelValue').at(-1)[0]
    expect(out[0].also_known_as).toEqual(['Northwind Group'])
    expect(out[0].employer).toBe('Sample Analytics')
  })

  it('removing a chip emits the list without it', async () => {
    const w = mountJobs(jobs)
    await w.find('button[aria-label="Remove Northwind"]').trigger('click')
    expect(w.emitted('update:modelValue').at(-1)[0][0].also_known_as).toEqual(['NW Bank'])
  })

  it('shows the server error found at experience[i].also_known_as under that field only', () => {
    const w = mountJobs([jobs[0], { ...jobs[0], also_known_as: [] }],
      { 'experience[1].also_known_as': 'must be a list of company names' })
    const errs = w.findAll('.field-error').map(e => e.text())
    expect(errs).toEqual(['must be a list of company names'])
    const inputs = w.findAll('.chips-input input')
    expect(inputs[1].attributes('aria-describedby')).toContain('-err')
    expect(inputs[0].attributes('aria-describedby') || '').not.toContain('-err')
  })
})

describe('Q-125 "Other keys in your file"', () => {
  const FORM = [{ id: 'experience', title: 'Experience', items: [{ path: 'experience', label: 'Experience', kind: 'entries', sub: SUB }] }]

  it('does not list an empty or null also_known_as once the form carries the sub-field', () => {
    const profile = { experience: [
      { employer: 'Example Co', title: 'Intern', also_known_as: [] },
      { employer: 'Example Co', title: 'Intern', also_known_as: null },
    ] }
    expect(otherKeys(profile, FORM)).toEqual([])
  })

  // DEFECT (Q-125, LOW): `covered()` in src/applicantForm.js compares an entry sub-field's path with
  // the leaf path "also_known_as[0]", so every name of a filled list shows up under "Other keys in
  // your file". Stays red until `covered` strips the index suffix of a list sub-field.
  it('does not list the names of a filled also_known_as', () => {
    const profile = { experience: [
      { employer: 'Sample Analytics', title: 'Analyst', also_known_as: ['Northwind', 'NW Bank'] },
    ] }
    expect(otherKeys(profile, FORM)).toEqual([])
  })

  it('still lists a key the entry does not show', () => {
    const profile = { experience: [{ employer: 'Sample Analytics', also_known_as: [], mystery: 'x' }] }
    expect(otherKeys(profile, FORM).map(k => k.path)).toEqual(['experience[0].mystery'])
  })
})
