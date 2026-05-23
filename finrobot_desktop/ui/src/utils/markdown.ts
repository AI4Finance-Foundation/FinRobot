/**
 * Lightweight markdown → React-safe HTML converter for inline display.
 * Handles: headings, bold, lists, horizontal rules, tables.
 * No external dependencies.
 */
export function markdownToHtml(text: string): string {
  if (!text) return ''
  const lines = text.split('\n')
  const out: string[] = []
  let inList = false
  let inTable = false

  const inline = (s: string) => s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')

  for (const line of lines) {
    const s = line.trim()

    if (!s) {
      if (inList) {
        out.push('</ul>')
        inList = false
      }
      if (inTable) {
        out.push('</tbody></table>')
        inTable = false
      }
      continue
    }

    // Horizontal rule
    if (/^-{3,}$/.test(s) || /^\*{3,}$/.test(s)) {
      if (inList) {
        out.push('</ul>')
        inList = false
      }
      if (inTable) {
        out.push('</tbody></table>')
        inTable = false
      }
      out.push('<hr class="md-hr">')
      continue
    }

    // Table
    if (s.startsWith('|') && s.endsWith('|')) {
      if (inList) {
        out.push('</ul>')
        inList = false
      }
      if (/^\|[\s\-:|]+\|$/.test(s)) continue // skip separator
      const cells = s
        .slice(1, -1)
        .split('|')
        .map((c) => c.trim())
      if (!inTable) {
        inTable = true
        out.push('<table class="md-table"><thead><tr>')
        cells.forEach((c) => out.push(`<th>${inline(c)}</th>`))
        out.push('</tr></thead><tbody>')
        continue
      }
      out.push('<tr>')
      cells.forEach((c) => out.push(`<td>${inline(c)}</td>`))
      out.push('</tr>')
      continue
    }

    if (inTable) {
      out.push('</tbody></table>')
      inTable = false
    }

    // Headings
    if (s.startsWith('# ')) {
      if (inList) {
        out.push('</ul>')
        inList = false
      }
      out.push(`<h3 class="md-h1">${inline(s.slice(2))}</h3>`)
      continue
    }
    if (s.startsWith('## ')) {
      if (inList) {
        out.push('</ul>')
        inList = false
      }
      out.push(`<h4 class="md-h2">${inline(s.slice(3))}</h4>`)
      continue
    }
    if (s.startsWith('### ')) {
      if (inList) {
        out.push('</ul>')
        inList = false
      }
      out.push(`<h5 class="md-h3">${inline(s.slice(4))}</h5>`)
      continue
    }

    // List
    if (s.startsWith('- ') || s.startsWith('* ')) {
      if (!inList) {
        out.push('<ul class="md-list">')
        inList = true
      }
      out.push(`<li>${inline(s.slice(2))}</li>`)
      continue
    }

    if (inList) {
      out.push('</ul>')
      inList = false
    }
    out.push(`<p>${inline(s)}</p>`)
  }

  if (inList) out.push('</ul>')
  if (inTable) out.push('</tbody></table>')
  return out.join('\n')
}
