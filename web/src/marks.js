// What a company's monogram shows (CompanyMark.vue), kept apart from the
// component so it is easy to test.

// "Standard Chartered" -> "SC", "GovTech" -> "GT", "OKX" -> "OK", "Grab" -> "G",
// "Futu / Moomoo" -> "FM", "" -> "?".
export function initials(name = '') {
  const words = String(name).split(/[^\p{L}\p{N}]+/u).filter(Boolean)
  if (!words.length) return '?'
  if (words.length > 1) return (words[0][0] + words[1][0]).toUpperCase()
  const word = words[0]
  const caps = word.match(/\p{Lu}/gu) ?? []
  if (word === word.toUpperCase()) return word.slice(0, 2).toUpperCase()
  if (caps.length >= 2) return (caps[0] + caps[1]).toUpperCase()
  return word[0].toUpperCase()
}

// A stable hue (0-359) from the name, so a company keeps its colour everywhere
// and between visits. FNV-1a: tiny, and spreads similar names apart.
export function hue(name = '') {
  let h = 0x811c9dc5
  for (const ch of String(name).toLowerCase()) {
    h ^= ch.codePointAt(0)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h % 360
}
