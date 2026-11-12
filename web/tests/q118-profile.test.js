// Q-118 LE pins (design section 6): the compact "From your resume" card, the chip cards for
// skills and job titles. The retargets of the older Profile tests are in Profile.test.js and
// q44-refresh.test.js.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import Profile from '../src/tabs/Profile.vue'
import { resetSeenJobs } from '../src/composables/useJob.js'
import { SUGGESTED, defaultTitles, fakeApi, pinZone } from './helpers.js'

pinZone()

let api
function useApi(options) {
  api = fakeApi(options)
  vi.stubGlobal('fetch', api.fetch)
  return api
}

beforeEach(() => {
  resetSeenJobs()
  window.localStorage.clear()
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
  useApi()
})
afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
enableAutoUnmount(afterEach)

async function mountProfile(options) {
  if (options) useApi(options)
  const w = mount(Profile, { attachTo: document.body })
  await flushPromises()
  return w
}

describe('Profile: the resume card', () => {
  it('with a resume there is no file name and no drop zone, but Replace and Re-read exist', async () => {
    const w = await mountProfile()
    const card = w.find('.resume-card')
    expect(card.text()).not.toContain('resume.pdf')                      // the stored file name is not shown
    expect(w.find('label.drop').exists()).toBe(false)                    // the big drop zone is gone
    expect(w.text()).not.toContain('Drop your resume here')
    expect(card.find('button.replace').text()).toBe('Replace resume')
    expect(card.find('button.refresh').text()).toBe('Re-read resume')
    expect(w.find('.empty-title').exists()).toBe(false)

    // Replace opens the file picker (the one hidden input), it does not upload by itself.
    const click = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(() => {})
    await card.find('button.replace').trigger('click')
    expect(click).toHaveBeenCalledTimes(1)
    expect(click.mock.contexts[0].type).toBe('file')
    expect(api.calls.filter(c => c.url === 'api/resume')).toHaveLength(0)
  })

  it('without a resume the drop zone is back (and takes a PDF); there is nothing to replace', async () => {
    const w = await mountProfile({ profile: { present: false } })
    expect(w.find('label.drop').exists()).toBe(true)
    expect(w.find('.drop-title').text()).toContain('Drop your resume here')
    expect(w.find('.empty-title').text()).toBe('No profile yet.')
    expect(w.find('button.replace').exists()).toBe(false)
    expect(w.find('button.refresh').text()).toBe('Re-read resume')
    expect(w.find('.skills-card').exists()).toBe(false)                  // nothing to list yet
    expect(w.find('.title-editor').classes()).toContain('span-12')       // the titles take the full row

    const file = new File(['%PDF-1.7\n'], 'cv.pdf', { type: 'application/pdf' })
    await w.find('label.drop').trigger('drop', { dataTransfer: { files: [file] } })
    for (let i = 0; i < 10; i++) {
      await vi.advanceTimersByTimeAsync(0)
      await new Promise(r => setImmediate(r))
      await flushPromises()
    }
    const puts = api.calls.filter(c => c.url === 'api/resume')
    expect(puts).toHaveLength(1)
    expect(puts[0].headers['Content-Type']).toBe('application/pdf')
  })

  it('"Show all N" skills and "Show more" of a long summary are buttons whose aria-expanded flips', async () => {
    const skills = Array.from({ length: 20 }, (_, i) => `skill${i}`)
    const summary = 'A computer science graduate with cloud and backend internships. '.repeat(4)
    const w = await mountProfile({ profile: { ...fakeApi().server.profile, skills, summary } })
    const more = () => w.find('button.more-skills')
    expect(more().text()).toBe('Show all 20')
    expect(more().attributes('aria-expanded')).toBe('false')
    await more().trigger('click')
    expect(more().text()).toBe('Show fewer')
    expect(more().attributes('aria-expanded')).toBe('true')
    expect(w.findAll('.skills li')).toHaveLength(20)

    const toggle = () => w.find('button.summary-toggle')
    expect(toggle().text()).toBe('Show more')
    expect(toggle().attributes('aria-expanded')).toBe('false')
    await toggle().trigger('click')
    expect(toggle().text()).toBe('Show less')
    expect(toggle().attributes('aria-expanded')).toBe('true')

    const short = await mountProfile({})                                // a one-line summary has nothing to expand
    expect(short.find('button.summary-toggle').exists()).toBe(false)
    expect(short.find('button.more-skills').exists()).toBe(false)
  })
})

describe('Profile: the job titles card', () => {
  it('titles are removable chips in one place only: there is no second list of them', async () => {
    const w = await mountProfile()
    expect(w.find('ul.titles').exists()).toBe(false)
    const chips = w.findAll('li.te-chip')
    expect(chips.map(c => c.text())).toEqual(['software engineer', 'site reliability engineer'])
    expect(chips.every(c => c.classes().includes('is-removable'))).toBe(true)
    // the same words are nowhere else in the list items of the tab
    expect(w.findAll('li').filter(li => li.text() === 'site reliability engineer')).toHaveLength(1)

    await w.find('button[aria-label="Remove site reliability engineer"]').trigger('click')
    await flushPromises()
    const put = api.calls.find(c => c.url === 'api/titles' && c.method === 'PUT')
    expect(JSON.parse(put.body)).toEqual({ titles: ['software engineer'] })
  })

  it('a recommended title is added with one click', async () => {
    const w = await mountProfile({ titles: { ...defaultTitles(), suggestions: JSON.parse(JSON.stringify(SUGGESTED)) } })
    expect(w.findAll('.te-suggestion .te-s-title').map(t => t.text())).toEqual(['platform engineer', 'data engineer'])
    await w.find('.te-suggestion').trigger('click')
    await flushPromises()
    const put = api.calls.find(c => c.url === 'api/titles' && c.method === 'PUT')
    expect(JSON.parse(put.body).titles).toEqual(['software engineer', 'site reliability engineer', 'platform engineer'])
    expect(w.findAll('li.te-chip').map(c => c.text())).toContain('platform engineer')
    expect(w.findAll('.te-suggestion .te-s-title').map(t => t.text())).toEqual(['data engineer'])   // taken ones leave the list
  })
})
