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
