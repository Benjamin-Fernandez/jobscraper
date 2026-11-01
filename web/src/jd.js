// The job description as a board serves it is plain text (M16): the employer's
// headings, bullets and paragraphs survive only as line breaks. This finds them
// again so the Inbox can draw real headings and lists (UX-1). The result is data
// - {type, text | items} blocks - rendered element by element, never as HTML.

// "- x", "* x", "• x", "1. x", "2) x"
const BULLET = /^(?:[-*•·▪◦‣–—]|\d{1,2}[.)])\s+(.+)$/
const HEADING_CHARS = 60
const HEADING_WORDS = 8

// Short, a label rather than a sentence: no closing full stop, comma or the like.
function headingLike(line) {
  return line.length <= HEADING_CHARS
    && !BULLET.test(line)
    && !/[.,;!?]$/.test(line)
    && line.split(/\s+/).length <= HEADING_WORDS
}

// 'About the role\nYou will...\n\n- a\n- b' ->
// [{type: 'heading', text}, {type: 'para', text}, {type: 'list', items}]
export function parseDescription(text) {
  const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n').map(l => l.trim())
  const blocks = []
  let para = []

  const endPara = () => {
    if (para.length) blocks.push({ type: 'para', text: para.join('\n') })
    para = []
  }
  const nextLine = i => lines.slice(i + 1).find(Boolean) ?? null

  lines.forEach((line, i) => {
    if (!line) {
      endPara()
      return
    }
    const bullet = BULLET.exec(line)
    if (bullet) {
      endPara()
      const last = blocks.at(-1)
      // Bullets split by blank lines are still one list.
      if (last?.type === 'list') last.items.push(bullet[1].trim())
      else blocks.push({ type: 'list', items: [bullet[1].trim()] })
      return
    }
    const next = nextLine(i)
    // A heading introduces something, and starts a block unless it says so
    // itself ("Requirements:") or a list follows it at once.
    if (next !== null && headingLike(line)
        && (!para.length || line.endsWith(':') || BULLET.test(next))) {
      endPara()
      blocks.push({ type: 'heading', text: line.replace(/:$/, '').trim() })
      return
    }
    para.push(line)
  })
  endPara()
  return blocks
}

const size = b => (b.type === 'list' ? b.items.join(' ').length : b.text.length)
const cutText = (text, room) => `${text.slice(0, room).replace(/\s+\S*$/, '')}…`

// The first `limit` characters' worth of blocks, the last one cut with "…".
// {blocks, cut}; when nothing needs cutting, the same blocks and cut: false.
export function previewBlocks(blocks, limit) {
  const out = []
  let used = 0
  for (const b of blocks) {
    if (used + size(b) <= limit) {
      out.push(b)
      used += size(b)
      continue
    }
    const room = limit - used
    if (b.type === 'para' && room > 0) out.push({ type: 'para', text: cutText(b.text, room) })
    if (b.type === 'list' && room > 0) {
      const items = []
      for (const item of b.items) {
        const left = room - items.join(' ').length
        if (item.length <= left) { items.push(item); continue }
        if (left > 0) items.push(cutText(item, left))
        break
      }
      if (items.length) out.push({ type: 'list', items })
    }
    // Never end on a heading with nothing under it.
    while (out.at(-1)?.type === 'heading') out.pop()
    const last = out.at(-1)
    if (last?.type === 'para' && !last.text.endsWith('…')) out[out.length - 1] = { ...last, text: `${last.text}…` }
    if (last?.type === 'list' && !last.items.at(-1).endsWith('…')) {
      out[out.length - 1] = { ...last, items: [...last.items.slice(0, -1), `${last.items.at(-1)}…`] }
    }
    return { blocks: out, cut: true }
  }
  return { blocks, cut: false }
}
