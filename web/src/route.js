// The active tab - and, inside a tab, its view and one item - live in the URL hash:
// `#/<tab>[/<view>[/<item>]]` (Q-100 design §1), so refresh, back, forward and
// bookmarks all land on the same place. A hash needs no server route and no router
// dependency: the server only ever serves `/`.
//
//   #/inbox                         a tab
//   #/settings/accounts             a view of a tab (Settings has four)
//   #/settings/accounts/gmail:3     one item of a view: the card to scroll to
//
// Every hash the app wrote before views existed (`#/settings`, `#/profile`, ...)
// is still a valid tab hash, and `tabFromHash` keeps its old contract.
import { computed, getCurrentScope, onScopeDispose, ref } from 'vue'

// view and tab ids are word characters and hyphens; an item id may also carry a
// colon (`gmail:3`, `apply-mailbox:backup`). Anything else - `..`, spaces, a
// further segment - is not a route.
const HASH_RE = /^#\/([\w-]+)(?:\/([\w-]+)(?:\/([\w-]+(?::[\w-]+)?))?)?\/?$/

// '#/settings/accounts/gmail:3' -> { tab: 'settings', view: 'accounts', item: 'gmail:3' },
// or null when the hash is not a route at all. The tab is not checked here.
function split(hash) {
  const m = HASH_RE.exec(hash || '')
  return m ? { tab: m[1], view: m[2] ?? null, item: m[3] ?? null } : null
}

// A hash -> { tab, view, item }. `ids` are the known tab ids; an unknown tab, or a
// hash that is not a route, gives the first tab with no view and no item. The view
// and item are as written: whether the tab has that view is the tab's business
// (`useView`), so `#/settings/nonsense` still lands on Settings.
export function parseHash(hash, ids) {
  const parts = split(hash)
  if (!parts || !ids.includes(parts.tab)) return { tab: ids[0], view: null, item: null }
  return parts
}

// '#/runs' -> 'runs'; anything that is not a known tab id -> the fallback. Views
// and items are ignored: `#/settings/accounts` is the Settings tab.
export function tabFromHash(hash, ids, fallback = ids[0]) {
  const parts = split(hash)
  return parts && ids.includes(parts.tab) ? parts.tab : fallback
}

// The hash for a tab, a view of it, and an item of that view. An item without a
// view is dropped (it would read as the view).
export function hashFor(tab, view, item) {
  if (!view) return `#/${tab}`
  return item ? `#/${tab}/${view}/${item}` : `#/${tab}/${view}`
}

// ---- views inside a tab ----

const idOf = v => (typeof v === 'string' ? v : v?.id)

// Follow the hash for as long as the calling component (or effect scope) lives.
function onHash(handler) {
  window.addEventListener('hashchange', handler)
  if (getCurrentScope()) onScopeDispose(() => window.removeEventListener('hashchange', handler))
}

// Which view of tab `tabId` is open: a Ref<string> that reads `#/<tab>/<view>`,
// follows `hashchange`, and writes with `replaceState` (picking a view is not a
// page of its own, so back does not have to step over it). `views` is a list of
// ids or of `{id}` objects; `fallback` is the default view - the first one if not
// given.
//   - No view in the hash: the fallback, and the hash is left alone (the tab may
//     have a better remembered view to offer).
//   - An unknown view: the fallback, and the canonical hash is written.
//   - The hash names another tab (a kept-alive tab stays mounted while hidden):
//     the value does not change and the hash is never touched.
export function useView(tabId, views, fallback) {
  const ids = views.map(idOf)
  const dflt = ids.includes(fallback) ? fallback : ids[0]
  const view = ref(dflt)

  function currentHashParts() {
    const parts = split(window.location.hash)
    return parts && parts.tab === tabId ? parts : null
  }
  function sync() {
    const parts = currentHashParts()
    if (!parts) return
    if (parts.view === null) { view.value = dflt; return }
    if (ids.includes(parts.view)) { view.value = parts.view; return }
    view.value = dflt   // unknown view: the default, written canonically
    window.history.replaceState(window.history.state, '', hashFor(tabId, dflt))
  }
  sync()
  onHash(sync)

  // The Ref the caller sees: reading is `view`; assigning picks a view and writes
  // the hash (without the old view's item).
  return computed({
    get: () => view.value,
    set: next => {
      if (!ids.includes(next)) return
      view.value = next
      if (currentHashParts()) {
        window.history.replaceState(window.history.state, '', hashFor(tabId, next))
      }
    },
  })
}

// The item named in `#/<tab>/<view>/<item>` while `tabId` is the open tab, else
// null: a Ref<string|null> for the view that scrolls to (and focuses) that card.
export function useHashItem(tabId) {
  const item = ref(null)
  function sync() {
    const parts = split(window.location.hash)
    if (parts && parts.tab === tabId) item.value = parts.item
  }
  sync()
  onHash(sync)
  return item
}
