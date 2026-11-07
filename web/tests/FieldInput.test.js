// Q-70 D5 (N6): a `bool` FieldInput with no value says "Not set" instead of passing for "No".
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import FieldInput from '../src/components/FieldInput.vue'

const bool = modelValue => mount(FieldInput, { props: { kind: 'bool', id: 'f-flag', modelValue } })

describe('FieldInput bool', () => {
  it('renders "Not set" for a null value and leaves the label readable to screen readers', () => {
    const w = bool(null)
    expect(w.text()).toBe('Not set')
    expect(w.find('input').element.checked).toBe(false)
    expect(w.find('span').attributes('aria-hidden')).toBeUndefined()
  })

  it('renders "Not set" for an undefined value too (a key the file does not have)', () => {
    expect(mount(FieldInput, { props: { kind: 'bool', id: 'f-flag' } }).text()).toBe('Not set')
  })

  it('renders "Yes" for true and "No" for false, both hidden from screen readers (the switch state says it)', () => {
    const yes = bool(true)
    expect(yes.text()).toBe('Yes')
    expect(yes.find('span').attributes('aria-hidden')).toBe('true')
    const no = bool(false)
    expect(no.text()).toBe('No')
    expect(no.find('span').attributes('aria-hidden')).toBe('true')
  })

  it('toggling an unset switch emits true', async () => {
    const w = bool(null)
    await w.find('input').setValue(true)
    expect(w.emitted('update:modelValue')?.[0]).toEqual([true])
  })
})

// Q-71: the Expected salary field showed no inputs when its value was missing.
const salary = (props = {}) => mount(FieldInput, { props: { kind: 'salary', id: 'f-pay', nullable: false, ...props } })
const AMOUNT = { amount: 3500, currency: 'SGD', period: 'monthly' }

describe('FieldInput salary (required, Q-71)', () => {
  for (const [name, props] of [['null', { modelValue: null }], ['undefined', {}]]) {
    it(`shows Amount, Currency, Period and Negotiable when the value is ${name}`, () => {
      const w = salary(props)
      expect(w.find('.salary-grid').exists()).toBe(true)
      expect(w.find('#f-pay').attributes('type')).toBe('number')
      expect(w.find('label[for="f-pay"]').text()).toBe('Amount')
      expect(w.find('#f-pay-currency').element.value).toBe('SGD')
      expect(w.find('#f-pay-period').element.value).toBe('monthly')
      const negotiable = w.findAll('label.check').find(l => l.text() === 'Negotiable')
      expect(negotiable, 'a Negotiable checkbox').toBeTruthy()
      expect(negotiable.find('input').element.checked).toBe(false)
      expect(w.text()).not.toContain("I don't have one")       // only a nullable salary offers that
    })

    it(`typing an amount into a ${name} value emits the amount with SGD and monthly`, async () => {
      const w = salary(props)
      await w.find('#f-pay').setValue('3500')
      expect(w.emitted('update:modelValue')).toEqual([[{ amount: 3500, currency: 'SGD', period: 'monthly' }]])
    })
  }

  it('an untouched field emits nothing, so it stays unset ("Needed")', async () => {
    const w = salary({ modelValue: null })
    await w.vm.$nextTick()
    expect(w.emitted('update:modelValue')).toBeUndefined()
  })

  it('keeps the other parts when one changes, and ticking Negotiable adds negotiable', async () => {
    const w = salary({ modelValue: AMOUNT })
    await w.find('#f-pay-period').setValue('annual')
    expect(w.emitted('update:modelValue').at(-1)).toEqual([{ ...AMOUNT, period: 'annual' }])
    await w.find('.check input').setValue(true)
    expect(w.emitted('update:modelValue').at(-1)).toEqual([{ ...AMOUNT, negotiable: true }])
  })
})

describe('FieldInput salary (nullable, e.g. current salary)', () => {
  for (const [name, props] of [['null', { modelValue: null }], ['undefined', {}]]) {
    it(`with ${name} says "I don't have one" and shows no inputs; unticking brings them back`, async () => {
      const w = salary({ nullable: true, ...props })
      const none = w.find('label.check input')
      expect(w.text()).toContain("I don't have one")
      expect(none.element.checked).toBe(true)
      expect(w.find('.salary-grid').exists()).toBe(false)
      expect(w.find('#f-pay').exists()).toBe(false)

      await none.setValue(false)
      expect(w.emitted('update:modelValue')).toEqual([[{ amount: null, currency: 'SGD', period: 'monthly' }]])
    })
  }

  it('with a value shows the inputs and unticked box; ticking it emits null', async () => {
    const w = salary({ nullable: true, modelValue: AMOUNT })
    expect(w.find('.salary-grid').exists()).toBe(true)
    expect(w.find('label.check input').element.checked).toBe(false)
    expect(w.find('#f-pay').element.value).toBe('3500')
    await w.find('label.check input').setValue(true)
    expect(w.emitted('update:modelValue')).toEqual([[null]])
  })

  it('has no Negotiable checkbox (only the expected salary negotiates)', () => {
    const w = salary({ nullable: true, modelValue: AMOUNT })
    expect(w.findAll('label.check').map(l => l.text())).toEqual(["I don't have one"])
  })
})
