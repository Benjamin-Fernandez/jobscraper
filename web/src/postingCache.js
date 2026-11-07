// The job descriptions fetched so far, one entry per job id (M16, Q-76).
// Module-level so the Inbox's detail and the Applications tab's detail share
// them: opening the same role in either tab never fetches it twice. An entry is
// {state: 'loading' | 'ok' | 'error', text, error}; the Map is reactive, so a
// component reading `postingEntry(id)` re-renders when the fetch lands.
import { reactive } from 'vue'
import { describeError, getPosting } from './api.js'

const cache = reactive(new Map())
let generation = 0      // bumps on clear, so a fetch that lands afterwards is dropped
let users = 0           // JobDetail components alive (the tabs are kept alive, so the app's stay)

// The cache lives while a detail is on screen or kept alive. When the last one is
// gone it is dropped - next tick, because a keyed swap unmounts the old detail
// just before it mounts the new one.
export function holdPostings() {
  users += 1
}
export function releasePostings() {
  users -= 1
  if (users <= 0) Promise.resolve().then(() => { if (users <= 0) clearPostingCache() })
}

// The entry now, or null when the role has not been asked for.
export function postingEntry(id) {
  return id ? cache.get(id) ?? null : null
}

// Fetch a role's description unless it is already here (or on its way). A failed
// fetch is kept too, as it was in the Inbox, so a dead posting is not asked for
// again on every selection.
export async function loadPosting(id) {
  if (!cache.has(id)) {
    const gen = generation
    cache.set(id, { state: 'loading', text: '' })
    let entry
    try {
      const posting = await getPosting(id)
      entry = { state: 'ok', text: posting.description || '' }
    } catch (e) {
      entry = { state: 'error', text: '', error: describeError(e) }
    }
    if (gen === generation) cache.set(id, entry)
    return entry
  }
  return cache.get(id)
}

// Forget everything (tests; a data reload that should refetch).
export function clearPostingCache() {
  generation += 1
  cache.clear()
}
