// The active tab lives in the URL hash (`#/inbox`, `#/runs`, ...), so refresh,
// back, forward and bookmarks all land on the same tab. A hash needs no server
// route and no router dependency: the server only ever serves `/`.

// '#/runs' -> 'runs'; anything that is not a known tab id -> the fallback.
export function tabFromHash(hash, ids, fallback = ids[0]) {
  const m = /^#\/([\w-]+)\/?$/.exec(hash || '')
  return m && ids.includes(m[1]) ? m[1] : fallback
}

export function hashFor(id) {
  return `#/${id}`
}
