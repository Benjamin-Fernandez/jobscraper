// Q-100 T1-0 pins for web/src/components/StateChip.vue (design §2.1): the chip says
// its state in words (colour is never the only cue), always has an accessible name,
// and is a button or a link only when asked to be.
import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import StateChip from '../src/components/StateChip.vue'
import { STATES, chipText } from '../src/connections.js'
import sample from './fixtures/connections.sample.json'

const chip = props => mount(StateChip, { props })

describe('StateChip: words, tone, accessible name', () => {
  it('shows the words for the item\'s state, with the tone as data', () => {
    const w = chip({ item: { state: 'attention', code: 'consent', kind: 'gmail' } })
    expect(w.text()).toBe('Needs attention')
    expect(w.attributes('data-tone')).toBe('attention')
    expect(w.classes()).toContain('state-chip')
  })
  it('every state renders text, a tone and an aria-label (not colour only)', () => {
    for (const state of STATES) {
      const w = chip({ state })
      expect(w.text(), state).toMatch(/\S/)
      expect(w.attributes('data-tone'), state).toBe(state)
      expect(w.attributes('aria-label'), state).toBe(w.text())
    }
  })
  it('every item of the sample response renders its words and an aria-label', () => {
    for (const item of [...sample.items, ...sample.employer_accounts]) {
      const w = chip({ item })
      expect(w.text(), item.id).toBe(chipText(item))
      expect(w.attributes('aria-label'), item.id).toBeTruthy()
    }
  })
  it('the parts work without an item, and they win over the item', () => {
    expect(chip({ state: 'not_set_up', optional: true }).text()).toBe('Optional')
    expect(chip({ state: 'connected', kind: 'edge', code: 'in_use' }).text()).toBe('In use')
    expect(chip({ item: { state: 'connected', code: 'ok' }, state: 'paused' }).text()).toBe('Paused')
  })
  it('explicit text replaces the default words, in the label too', () => {
    const w = chip({ state: 'attention', text: 'Failed' })
    expect(w.text()).toBe('Failed')
    expect(w.attributes('aria-label')).toBe('Failed')
  })
  it('a label names what the chip is about', () => {
    const w = chip({ item: { state: 'connected', code: 'ok' }, label: 'Local AI' })
    expect(w.text()).toBe('Connected')
    expect(w.attributes('aria-label')).toBe('Local AI: Connected')
  })
  it('no state at all still renders words and a name, drawn neutral', () => {
    for (const props of [{}, { item: {} }, { state: 'bogus' }]) {
      const w = chip(props)
      expect(w.text()).toBe("Couldn't check")
      expect(w.attributes('aria-label')).toBe("Couldn't check")
      expect(w.attributes('data-tone')).toBe('neutral')
    }
  })
})

describe('StateChip: not clickable unless asked', () => {
  it('the default is a plain span (role img), no is-action class, no href, no type', () => {
    const w = chip({ state: 'connected' })
    expect(w.element.tagName).toBe('SPAN')
    expect(w.attributes('role')).toBe('img')
    expect(w.classes()).not.toContain('is-action')
    expect(w.attributes('href')).toBeUndefined()
    expect(w.attributes('type')).toBeUndefined()
  })
  it('action makes a button with the is-action class and type=button', () => {
    const w = chip({ state: 'attention', action: true })
    expect(w.element.tagName).toBe('BUTTON')
    expect(w.classes()).toContain('is-action')
    expect(w.attributes('type')).toBe('button')
    expect(w.attributes('role')).toBeUndefined()
    expect(w.attributes('aria-label')).toBe('Needs attention')
  })
  it('a button emits click', async () => {
    const w = chip({ state: 'attention', action: true })
    await w.trigger('click')
    await w.trigger('click')
    expect(w.emitted('click')).toHaveLength(2)
  })
  it('a plain chip still names itself but is not a control', async () => {
    const w = chip({ state: 'connected' })
    expect(w.attributes('aria-label')).toBe('Connected')
    expect(w.element.tagName).not.toBe('BUTTON')
  })
  it('href makes a link with the is-action class, and the link wins over action', () => {
    const w = chip({ item: { state: 'attention', code: 'consent' }, href: '#/settings/accounts/model', action: true })
    expect(w.element.tagName).toBe('A')
    expect(w.attributes('href')).toBe('#/settings/accounts/model')
    expect(w.classes()).toContain('is-action')
    expect(w.attributes('type')).toBeUndefined()
    expect(w.attributes('aria-label')).toBe('Needs attention')
  })
})
