// Q-118 L0 pins: the seven web/src/ui/ primitives (design sections 1 and 8) and the
// `.ui-check` contract. Each pin reads the DOM and ARIA the design names.
import { afterEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import Segmented from '../src/ui/Segmented.vue'
import Switch from '../src/ui/Switch.vue'
import MenuButton from '../src/ui/MenuButton.vue'
import MoveMenu from '../src/ui/MoveMenu.vue'
import KpiCard from '../src/ui/KpiCard.vue'
import ProgressSegments from '../src/ui/ProgressSegments.vue'
import SortHeader from '../src/ui/SortHeader.vue'
import Runs from '../src/tabs/Runs.vue'
import { STAGE_TABS, stageOf, statusLabel } from '../src/stages.js'
import { fakeApi } from './helpers.js'

enableAutoUnmount(afterEach)
afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = '' })

// A v-model that follows its own emits, as a parent would.
function withModel(Comp, props) {
  const w = mount(Comp, {
    props: { ...props, 'onUpdate:modelValue': v => w.setProps({ modelValue: v }) },
    attachTo: document.body,
  })
  return w
}

describe('Segmented', () => {
  it('is a radiogroup with a roving tabindex; arrows, Home and End move and select', async () => {
    const options = [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }, { value: 'c', label: 'C', disabled: true }, { value: 'd', label: 'D' }]
    const w = withModel(Segmented, { modelValue: 'a', options, label: 'Sort' })
    expect(w.attributes('role')).toBe('radiogroup')
    expect(w.attributes('aria-label')).toBe('Sort')
    const radios = () => w.findAll('button[role="radio"]')
    expect(radios().map(r => r.attributes('tabindex'))).toEqual(['0', '-1', '-1', '-1'])
    expect(radios().map(r => r.attributes('aria-checked'))).toEqual(['true', 'false', 'false', 'false'])
    radios()[0].element.focus()
    await radios()[0].trigger('keydown', { key: 'ArrowRight' })
    expect(w.emitted('update:modelValue').at(-1)).toEqual(['b'])
    expect(radios()[1].attributes('tabindex')).toBe('0')
    expect(document.activeElement).toBe(radios()[1].element)
    await radios()[1].trigger('keydown', { key: 'ArrowRight' })        // C is disabled: skipped
    expect(w.emitted('update:modelValue').at(-1)).toEqual(['d'])
    await radios()[3].trigger('keydown', { key: 'Home' })
    expect(w.emitted('update:modelValue').at(-1)).toEqual(['a'])
    await radios()[0].trigger('keydown', { key: 'End' })
    expect(w.emitted('update:modelValue').at(-1)).toEqual(['d'])
  })
})

describe('Switch', () => {
  it('is role=switch named by its label, aria-checked follows the value, a click flips it', async () => {
    const w = withModel(Switch, { modelValue: false, label: 'Dry run', description: 'Fetch and report; save nothing.' })
    expect(w.attributes('role')).toBe('switch')
    expect(w.attributes('aria-checked')).toBe('false')
    expect(document.getElementById(w.attributes('aria-labelledby')).textContent).toBe('Dry run')
    expect(document.getElementById(w.attributes('aria-describedby')).textContent).toBe('Fetch and report; save nothing.')
    await w.trigger('click')
    expect(w.emitted('update:modelValue')).toEqual([[true]])
    expect(w.attributes('aria-checked')).toBe('true')
    await w.setProps({ busy: true })
    await w.trigger('click')                                          // busy: ignored
    expect(w.emitted('update:modelValue')).toHaveLength(1)
  })
})

describe('MenuButton', () => {
  const items = [{ id: 'note', label: 'Add note' }, { id: 'details', label: 'Show details' }, { id: 'remove', label: 'Remove', danger: true }]

  it('renders the menu inline; Esc closes it and returns focus to the trigger', async () => {
    const w = mount(MenuButton, { props: { label: 'More actions for SRE at Flowdesk', items }, attachTo: document.body })
    const trigger = w.find('button.ui-menu-trigger')
    expect(trigger.attributes('aria-haspopup')).toBe('menu')
    expect(trigger.attributes('aria-expanded')).toBe('false')
    expect(w.find('[role="menu"]').exists()).toBe(false)
    await trigger.trigger('click')
    await flushPromises()
    const menu = w.find('[role="menu"]')
    expect(menu.exists()).toBe(true)
    expect(w.element.contains(menu.element)).toBe(true)              // inline, not teleported
    expect(trigger.attributes('aria-controls')).toBe(menu.attributes('id'))
    expect(document.activeElement.textContent.trim()).toBe('Add note')
    await menu.trigger('keydown', { key: 'Escape' })
    await flushPromises()
    expect(w.find('[role="menu"]').exists()).toBe(false)
    expect(document.activeElement).toBe(trigger.element)
    expect(w.emitted('select')).toBeUndefined()
  })

  it('an outside click closes it; a pick emits select once and returns focus', async () => {
    const w = mount(MenuButton, { props: { label: 'More', items }, attachTo: document.body })
    const trigger = w.find('button.ui-menu-trigger')
    await trigger.trigger('click')
    await flushPromises()
    document.body.click()
    await flushPromises()
    expect(w.find('[role="menu"]').exists()).toBe(false)
    await trigger.trigger('keydown', { key: 'ArrowUp' })            // opens on the last item
    await flushPromises()
    expect(document.activeElement.textContent.trim()).toBe('Remove')
    await w.find('[role="menu"]').trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(w.emitted('select')).toEqual([['remove']])
    expect(document.activeElement).toBe(trigger.element)
  })
})

describe('MoveMenu', () => {
  it('is named "Move {name}, now {Stage}", headed Move to, the current stage checked and disabled', async () => {
    const w = mount(MoveMenu, { props: { status: 'interviewing', name: 'SRE at Flowdesk' }, attachTo: document.body })
    const trigger = w.find('.ui-move-trigger')
    expect(trigger.attributes('aria-label')).toBe('Move SRE at Flowdesk, now Interviewing')
    expect(trigger.find('.pill[data-status="interviewing"]').text()).toBe('Interviewing')
    await trigger.trigger('click')
    await flushPromises()
    expect(w.find('.ui-menu-heading').text()).toBe('Move to')
    const radios = w.findAll('[role="menuitemradio"]')
    expect(radios.map(r => r.text().trim())).toEqual(['Applied', 'Interviewing', 'Offer', 'Rejected'])
    const current = radios[1]
    expect(current.attributes('aria-checked')).toBe('true')
    expect(current.attributes('disabled')).toBeDefined()
    expect(current.attributes('aria-disabled')).toBe('true')
    await current.trigger('click')
    expect(w.emitted('move')).toBeUndefined()
    await radios[2].trigger('click')
    expect(w.emitted('move')).toEqual([['offer']])
  })

  it('a disabled menu keeps the trigger focusable and says why', async () => {
    const w = mount(MoveMenu, { props: { status: 'to_apply', name: 'SRE at Flowdesk', disabled: true, disabledReason: 'JobScraper is applying to this role. Stop it in Runs first.' }, attachTo: document.body })
    const trigger = w.find('.ui-move-trigger')
    expect(trigger.attributes('disabled')).toBeUndefined()
    expect(trigger.attributes('aria-disabled')).toBe('true')
    expect(document.getElementById(trigger.attributes('aria-describedby')).textContent).toContain('Stop it in Runs first.')
    expect(trigger.find('.pill').text()).toBe('To apply')
    await trigger.trigger('click')
    expect(w.find('[role="menu"]').exists()).toBe(false)
  })
})

describe('KpiCard, ProgressSegments, SortHeader', () => {
  it('KpiCard is a link named "{label}: {value}, {caption}" when it has an href, else a div', () => {
    const link = mount(KpiCard, { props: { label: 'Applied', value: 31, caption: 'this month', hint: 'Roles you sent', href: '#/applications/applied' } })
    expect(link.element.tagName).toBe('A')
    expect(link.attributes('href')).toBe('#/applications/applied')
    expect(link.attributes('aria-label')).toBe('Applied: 31, this month')
    expect(link.find('.ui-kpi-value').text()).toBe('31')
    const plain = mount(KpiCard, { props: { label: 'Applied', value: null } })
    expect(plain.element.tagName).toBe('DIV')
    expect(plain.find('.ui-kpi-value').exists()).toBe(false)
  })

  it('ProgressSegments: link mode names each link; filter mode toggles aria-pressed; the bar is hidden', async () => {
    const segments = [
      { id: 'applied', label: 'Applied', n: 3, tone: 'applied', href: '#/applications/applied' },
      { id: 'offer', label: 'Offer', n: 0, tone: 'offer', href: '#/applications/offer' },
    ]
    const link = mount(ProgressSegments, { props: { segments, label: 'Pipeline' } })
    expect(link.find('.ui-progress').attributes('aria-hidden')).toBe('true')
    expect(link.findAll('.ui-progress-seg')).toHaveLength(1)             // n = 0 is not drawn
    expect(link.findAll('a.ui-progress-item').map(a => [a.attributes('href'), a.attributes('aria-label')]))
      .toEqual([['#/applications/applied', 'Applied, 3'], ['#/applications/offer', 'Offer, 0']])
    const filter = withModel(ProgressSegments, { segments, label: 'Pipeline', mode: 'filter', modelValue: '', allLabel: 'All' })
    const items = () => filter.findAll('button.ui-progress-item')
    expect(items().map(b => b.attributes('aria-pressed'))).toEqual(['true', 'false', 'false'])
    expect(items()[0].text()).toContain('3')                            // All = the sum
    await items()[1].trigger('click')
    expect(items().map(b => b.attributes('aria-pressed'))).toEqual(['false', 'true', 'false'])
    await items()[1].trigger('click')                                   // again: back to all
    expect(filter.emitted('update:modelValue').at(-1)).toEqual([''])
  })

  it('SortHeader sets aria-sort on the th and emits its column', async () => {
    const row = sort => mount({
      components: { SortHeader },
      props: ['sort'],
      template: '<table><thead><tr><SortHeader label="Open roles" column="open" :sort="sort" numeric @sort="c => $emit(\'picked\', c)" /></tr></thead></table>',
    }, { props: { sort } })
    expect(row({ key: 'open', dir: 'asc' }).find('th').attributes('aria-sort')).toBe('ascending')
    expect(row({ key: 'open', dir: 'desc' }).find('th').attributes('aria-sort')).toBe('descending')
    const other = row({ key: 'name', dir: 'asc' })
    expect(other.find('th').attributes('aria-sort')).toBe('none')
    expect(other.find('th').attributes('scope')).toBe('col')
    await other.find('button.ui-th-sort').trigger('click')
    expect(other.emitted('picked')).toEqual([['open']])
  })
})

describe('stages and .ui-check', () => {
  it('STAGE_TABS order, stageOf and the "To apply" word', () => {
    expect(STAGE_TABS).toEqual(['all', 'active', 'applied', 'interviewing', 'offer', 'rejected'])
    expect(stageOf('assessment')).toBe('interviewing')
    expect(stageOf('withdrawn')).toBe('rejected')
    expect(stageOf('to_apply')).toBe(null)
    expect(statusLabel('to_apply')).toBe('To apply')
  })

  it('.ui-check keeps a real checkbox inside its label (Runs history)', async () => {
    vi.stubGlobal('fetch', fakeApi().fetch)
    const runs = [{ run_no: 5, started_at: '2026-09-23T14:00:00', finished_at: '2026-09-23T14:10:00', status: 'ok', accepted: 2 }]
    const w = mount(Runs, { props: { runs } })
    await flushPromises()
    const label = w.find('tr[data-run="5"] label.ui-check')
    const box = label.find('input[type="checkbox"]')
    expect(box.exists()).toBe(true)
    expect(label.find('.ui-check-box').attributes('aria-hidden')).toBe('true')
    expect(label.text()).toBe('Select run 5')
    await box.setValue(true)
    expect(box.element.checked).toBe(true)
    expect(w.find('tr[data-run="5"]').attributes('aria-selected')).toBe('true')
  })
})
