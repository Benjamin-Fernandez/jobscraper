// T5 oracles for one Questions-inbox card (Q-35; review Q-30 F3, LF §12.2; WP-Q5 compose_needed chip).
//
//   * a choice card that opened with a saved pick and is cleared sends `picks: { <id>: [] }`, so the
//     server drops that variant's pick; an untouched empty variant is not sent at all;
//   * a multi card cleared the same way sends [] too;
//   * the reason chip says what the reason code means (compose_needed included), and is hidden
//     when the owner is changing a saved answer;
//   * a sensitive card shows the private tag.
// Synthetic employers and labels only. Verify: cd web; npx vitest run QuestionCard
import { afterEach, describe, expect, it } from 'vitest'
import { enableAutoUnmount, mount } from '@vue/test-utils'
import QuestionCard from '../src/components/QuestionCard.vue'

enableAutoUnmount(afterEach)

const OPTS_A = [{ label: 'Citizen', norm: 'citizen' }, { label: 'PR', norm: 'pr' }, { label: 'Others', norm: 'others' }]
const OPTS_B = [{ label: 'Singapore Citizen', norm: 'singapore citizen' }, { label: 'Other', norm: 'other' }]

const group = (over = {}) => ({
  key: 'visa_status', title: 'Visa status', description: '', kind: 'choice', sensitive: false,
  target_path: '', status: 'open', reason: 'no_rule', labels: ['What is your visa status?'],
  employers: ['Example Employer', 'Sample Corp'], waiting: 1,
  variants: [
    { question_id: 11, label: 'What is your visa status?', options: OPTS_A, employers: ['Example Employer'] },
    { question_id: 12, label: 'Residency', options: OPTS_B, employers: ['Sample Corp'] },
  ],
  ...over,
})

const saved = body => body.emitted('save')?.at(-1)?.[0]

describe('QuestionCard: clearing a saved variant', () => {
  it('a cleared choice variant sends [] and an untouched empty one is not sent', async () => {
    const w = mount(QuestionCard, {
      props: { group: group({ status: 'answered', current: { value: null, picks: ['citizen'] } }), answered: true },
    })
    const selects = w.findAll('select').filter(s => s.attributes('id')?.includes('-pick-'))
    expect(selects.length).toBe(2)
    expect(selects[0].element.value).toBe('Citizen')
    await selects[0].setValue('')                    // clear the saved pick
    await selects[1].setValue('Other')               // and answer the other option set
    await w.find('button.q-save').trigger('click')
    expect(saved(w)).toEqual({ key: 'visa_status', picks: { 11: [], 12: ['Other'] } })
  })

  it('an untouched empty variant is left out of the body', async () => {
    const w = mount(QuestionCard, { props: { group: group() } })
    const selects = w.findAll('select').filter(s => s.attributes('id')?.includes('-pick-'))
    await selects[0].setValue('PR')
    await w.find('button.q-save').trigger('click')
    expect(saved(w).picks).toEqual({ 11: ['PR'] })
  })

  it('a multi card cleared of its saved picks sends []', async () => {
    const g = group({ kind: 'multi', status: 'answered', current: { value: null, picks: ['pr', 'other'] } })
    const w = mount(QuestionCard, { props: { group: g, answered: true } })
    const boxes = w.findAll('input[type="checkbox"]')
    const checked = boxes.filter(b => b.element.checked)
    expect(checked.length).toBe(2)
    await checked[0].setValue(false)                 // variant 11 loses its only pick
    await w.find('button.q-save').trigger('click')
    const body = saved(w)
    expect(body.picks[11]).toEqual([])
    expect(body.picks[12]).toEqual(['Other'])
  })
})

describe('QuestionCard: the reason chip', () => {
  it('compose_needed says the text cannot be written yet', () => {
    const w = mount(QuestionCard, { props: { group: group({
      key: 'compose', title: 'Why do you want to join?', kind: 'text', reason: 'compose_needed',
      variants: [{ question_id: 51, label: 'Why do you want to join?', options: [] }] }) } })
    const chip = w.find('.q-reason')
    expect(chip.exists()).toBe(true)
    expect(chip.text()).toMatch(/cover letter or motivation text/i)
    expect(chip.text()).not.toBe('compose_needed')
  })

  it('compose_needed shows the exact chip text and, with no note, the generic hint (WP-K2, LF section 19.6)', () => {
    const w = mount(QuestionCard, { props: { group: group({ reason: 'compose_needed' }) } })
    expect(w.find('.q-reason').text()).toBe('Needs a cover letter or motivation text written for this job')
    expect(w.find('.q-hint').text()).toBe('Write it here for this posting.')
  })

  it.each([
    ['compose_needed: off', /^Write it here for this posting\. Automatic cover letters are off \(apply\.compose in config\.yaml\)\.$/],
    ['compose_needed: failed check', /didn't pass its fact check/i],
    ['compose_needed: no master', /Run the resume tailor once/i],
    ['compose_needed: something new', /^Write it here for this posting\.$/],
  ])('the compose_needed note %j picks its hint', (note, text) => {
    const w = mount(QuestionCard, { props: { group: group({ reason: 'compose_needed', note }) } })
    expect(w.find('.q-hint').text()).toMatch(text)
  })

  it('no hint for another reason, nor while editing a saved answer', () => {
    expect(mount(QuestionCard, { props: { group: group({ reason: 'no_rule', note: 'compose_needed: off' }) } })
      .find('.q-hint').exists()).toBe(false)
    expect(mount(QuestionCard, { props: { group: group({ reason: 'compose_needed' }), answered: true } })
      .find('.q-hint').exists()).toBe(false)
  })

  it.each([
    ['no_rule', /not in your profile/i],
    ['ungrounded', /couldn't be checked/i],
    ['profile_gap', /missing from your profile/i],
    ['no_option_fits', /isn't one of this form's options/i],
    ['attestation_unclear', /declaration/i],
    ['conflict', /work rights differ/i],
  ])('%s has a plain-language chip', (code, text) => {
    const w = mount(QuestionCard, { props: { group: group({ reason: code }) } })
    expect(w.find('.q-reason').text()).toMatch(text)
  })

  it('the variant reason is used when the group has none, and the chip hides while editing a saved answer', () => {
    const g = group({ reason: undefined, variants: [{ ...group().variants[0], reason: 'compose_needed' }] })
    expect(mount(QuestionCard, { props: { group: g } }).find('.q-reason').text()).toMatch(/cover letter/i)
    expect(mount(QuestionCard, { props: { group: g, answered: true } }).find('.q-reason').exists()).toBe(false)
  })

  it('an unknown reason code shows no chip rather than the raw code', () => {
    const w = mount(QuestionCard, { props: { group: group({ reason: 'not_a_reason' }) } })
    expect(w.find('.q-reason').exists()).toBe(false)
    expect(w.text()).not.toContain('not_a_reason')
  })

  it('a sensitive card carries the private tag', () => {
    const w = mount(QuestionCard, { props: { group: group({ sensitive: true }) } })
    expect(w.find('.tag.private').text()).toMatch(/never sent to the AI/i)
  })
})
