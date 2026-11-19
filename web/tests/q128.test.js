// Q-128 pins (the live-app polish): the Applications chip's count, and the words "Your details".
// Pure functions plus one static sweep of web/src. No network, no mount, no server.
// The server half (store.not_answered_counts, the doctor, the scope sentence, the three counts agreeing)
// is tests/test_q128.py.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { refusalMessage, rowState } from '../src/attempts.js'
import { applySteps } from '../src/connections.js'

const stopped = (extra = {}) => ({
  job_id: 'job1', status: 'to_apply',
  last_attempt: { kind: 'needs_input', reason_code: 'unanswerable_required', text: '', hint: '', ...extra },
})

describe('Q-128: the chip says how many questions had no answer, from the list alone', () => {
  it('3 -> "Stopped: 3 questions had no answer"', () => {
    const s = rowState(stopped({ not_answered: 3 }))
    expect(s.label).toBe('Stopped: 3 questions had no answer')
    expect(s.filled).toBe(true)
  })

  it('1 -> "Stopped: 1 question had no answer" (singular)', () => {
    expect(rowState(stopped({ not_answered: 1 })).label).toBe('Stopped: 1 question had no answer')
  })

  it('0 keeps the old sentence', () => {
    expect(rowState(stopped({ not_answered: 0 })).label).toBe('Stopped: a question had no answer')
  })

  it('a missing key (an older server) keeps the old sentence', () => {
    expect(rowState(stopped()).label).toBe('Stopped: a question had no answer')
  })

  it('a junk value (null, text, negative) never prints a count', () => {
    for (const bad of [null, undefined, 'x', -2, NaN]) {
      expect(rowState(stopped({ not_answered: bad })).label).toBe('Stopped: a question had no answer')
    }
  })

  it('the count belongs to a strict stop only: other stops keep their own words', () => {
    const s = rowState({ job_id: 'j', status: 'to_apply',
      last_attempt: { kind: 'needs_input', reason_code: 'owner_fact_missing', not_answered: 4, text: '', hint: '' } })
    expect(s.label).not.toMatch(/question/)
  })

  it('a stop that is ready to try again says so, whatever the count', () => {
    const s = rowState(stopped({ not_answered: 3, ready_to_retry: true }))
    expect(s.ready).toBe(true)
    expect(s.label).not.toMatch(/had no answer/)
  })
})

describe('Q-128: "Your details" in the strings the owner sees', () => {
  it('a refused enqueue for an incomplete profile says "Finish your details first."', () => {
    expect(refusalMessage({ detail: 'profile_incomplete' })).toBe('Finish your details first.')
  })

  it('the setup checklist step is "Fill in your details"', () => {
    for (const applicant of [{ missing: [] }, { missing: ['contact.email'] }, null]) {
      const step = applySteps({ connections: null, applicant }).steps.find(s => s.id === 'details')
      expect(step.label).toBe('Fill in your details')
    }
  })
})

// ---- the sweep ----
// No string the owner can read in web/src says "Application details" / "application details". Names of
// components and files (ApplicationDetails.vue, the `ApplicationDetails` identifier, test titles) have no
// space and so never match. ALLOWED, and why:
//   * comments (`//`, `/* */`, `<!-- -->`, a `*` continuation): the developer reads them, not the owner;
//   * the log-line match in Profile.vue (`SKIP_MODEL_DOWN`): a string compared with a SERVER log line
//     ("application details check skipped: ...", written by the profile job), never shown on a screen.
const SRC = resolve(process.cwd(), 'src')
const ALLOWED_LITERALS = ["application details check skipped: the AI model isn't running"]

function walk(dir) {
  return readdirSync(dir).flatMap(name => {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) return name === 'static' ? [] : walk(p)   // `static` = the built bundle
    return /\.(vue|js)$/.test(name) ? [p] : []
  })
}

function shownOccurrences(file) {
  const out = []
  readFileSync(file, 'utf8').split(/\r?\n/).forEach((line, i) => {
    const hit = /application details?/i.exec(line)
    if (!hit) return
    const t = line.trim()
    if (/^(\/\/|\/\*|\*|<!--)/.test(t)) return                        // a whole-line comment
    const cut = line.search(/\s\/\/\s/)                                // a trailing `// comment`
    if (cut !== -1 && hit.index > cut) return
    if (ALLOWED_LITERALS.some(a => line.includes(a))) return
    out.push(`${relative(SRC, file)}:${i + 1}: ${t}`)
  })
  return out
}

describe('Q-128: no user-visible "Application details" in web/src', () => {
  it('the sweep reads the real tree (it would be vacuous on an empty one)', () => {
    const files = walk(SRC)
    expect(files.length).toBeGreaterThan(40)
    expect(files.some(f => f.endsWith('ApplyQueuePanel.vue'))).toBe(true)
    expect(files.some(f => f.endsWith('Inbox.vue'))).toBe(true)
    expect(files.some(f => f.endsWith('ResumeRefresh.vue'))).toBe(true)
  })

  it('no template text or string literal says "Application details" / "application details"', () => {
    const found = walk(SRC).flatMap(shownOccurrences)
    expect(found).toEqual([])
  })

  it('the sweep itself sees a shown one (a planted line is caught, a comment and a log match are not)', () => {
    // the rules, applied to three sample lines
    const sees = line => {
      const hit = /application details?/i.exec(line)
      if (!hit) return false
      const t = line.trim()
      if (/^(\/\/|\/\*|\*|<!--)/.test(t)) return false
      const cut = line.search(/\s\/\/\s/)
      if (cut !== -1 && hit.index > cut) return false
      return !ALLOWED_LITERALS.some(a => line.includes(a))
    }
    expect(sees("  label: 'Application details',")).toBe(true)
    expect(sees('  <p>Fix your application details first.</p>')).toBe(true)
    expect(sees('  // the old Application details page')).toBe(false)
    expect(sees("  const x = 1 // was Application details")).toBe(false)
    expect(sees(`  l.includes("application details check skipped: the AI model isn't running")`)).toBe(false)
  })
})
