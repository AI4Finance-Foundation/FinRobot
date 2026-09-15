// Tiny no-dependency markdown renderer for chat bubbles.
// Covers the cases we actually see streaming from the agent: bold, italic,
// inline code, code blocks, ordered/unordered lists, headings up to ###, and
// [text](url) links. Anything we don't recognise renders as plain text so
// unknown markdown is never displayed as broken HTML.

import { type ReactNode } from 'react'

interface MarkdownLiteProps {
  text: string
  className?: string
  style?: React.CSSProperties
}

export function MarkdownLite({ text, className, style }: MarkdownLiteProps) {
  const blocks = parseBlocks(text)
  return (
    <div className={className} style={{ whiteSpace: 'pre-wrap', ...style }}>
      {blocks.map((block, i) => renderBlock(block, i))}
    </div>
  )
}

// ── Block parsing ────────────────────────────────────────────────────────────

type Block =
  | { kind: 'p'; text: string }
  | { kind: 'h'; level: 1 | 2 | 3; text: string }
  | { kind: 'ul'; items: string[] }
  | { kind: 'ol'; items: string[] }
  | { kind: 'code'; text: string }
  | { kind: 'blank' }

function parseBlocks(input: string): Block[] {
  const lines = input.split('\n')
  const blocks: Block[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]

    if (line.trim() === '') {
      blocks.push({ kind: 'blank' })
      i += 1
      continue
    }

    // Fenced code block
    if (line.startsWith('```')) {
      const buf: string[] = []
      i += 1
      while (i < lines.length && !lines[i].startsWith('```')) {
        buf.push(lines[i])
        i += 1
      }
      i += 1 // closing fence
      blocks.push({ kind: 'code', text: buf.join('\n') })
      continue
    }

    // Heading
    const heading = line.match(/^(#{1,3})\s+(.*)$/)
    if (heading) {
      const level = heading[1].length as 1 | 2 | 3
      blocks.push({ kind: 'h', level, text: heading[2] })
      i += 1
      continue
    }

    // Unordered list (-, *, +)
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*+]\s+/, ''))
        i += 1
      }
      blocks.push({ kind: 'ul', items })
      continue
    }

    // Ordered list (1. 2. 3.)
    if (/^\s*\d+\.\s+/.test(line)) {
      const items: string[] = []
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+\.\s+/, ''))
        i += 1
      }
      blocks.push({ kind: 'ol', items })
      continue
    }

    // Regular paragraph — collect contiguous non-empty lines
    const buf: string[] = [line]
    i += 1
    while (
      i < lines.length &&
      lines[i].trim() !== '' &&
      !lines[i].startsWith('```') &&
      !/^#{1,3}\s/.test(lines[i]) &&
      !/^\s*[-*+]\s/.test(lines[i]) &&
      !/^\s*\d+\.\s/.test(lines[i])
    ) {
      buf.push(lines[i])
      i += 1
    }
    blocks.push({ kind: 'p', text: buf.join('\n') })
  }
  return blocks
}

function renderBlock(block: Block, key: number): ReactNode {
  switch (block.kind) {
    case 'blank':
      return <div key={key} style={{ height: 4 }} />
    case 'p':
      return (
        <p key={key} style={{ margin: '0 0 6px', lineHeight: 1.55 }}>
          {renderInline(block.text)}
        </p>
      )
    case 'h':
      return (
        <strong
          key={key}
          style={{
            display: 'block',
            fontSize: block.level === 1 ? '0.95rem' : '0.88rem',
            margin: '6px 0 4px',
            color: 'var(--text-primary)',
          }}
        >
          {renderInline(block.text)}
        </strong>
      )
    case 'ul':
      return (
        <ul key={key} style={{ margin: '4px 0 6px', paddingLeft: 18, lineHeight: 1.5 }}>
          {block.items.map((it, idx) => (
            <li key={idx}>{renderInline(it)}</li>
          ))}
        </ul>
      )
    case 'ol':
      return (
        <ol key={key} style={{ margin: '4px 0 6px', paddingLeft: 20, lineHeight: 1.5 }}>
          {block.items.map((it, idx) => (
            <li key={idx}>{renderInline(it)}</li>
          ))}
        </ol>
      )
    case 'code':
      return (
        <pre
          key={key}
          style={{
            margin: '6px 0',
            padding: '8px 10px',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 4,
            fontSize: '0.78rem',
            fontFamily: 'var(--font-mono)',
            overflowX: 'auto',
          }}
        >
          {block.text}
        </pre>
      )
  }
}

// ── Inline parsing — [text](url), **bold**, *italic*, `code` ────────────────

// Order matters: the link alternative ([text](url)) comes first so its brackets
// aren't half-eaten by the emphasis patterns; bold (** **) before italic (* *)
// so the italic regex doesn't swallow the bold markers.
const INLINE_TOKEN = /(\[[^\]\n]+\]\([^)\n]+\)|\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\n]+\*|_[^_\n]+_)/g

const LINK_TOKEN = /^\[([^\]]+)\]\(([^)]+)\)$/

function renderInline(text: string): ReactNode[] {
  const out: ReactNode[] = []
  let lastIdx = 0
  let m: RegExpExecArray | null
  INLINE_TOKEN.lastIndex = 0
  while ((m = INLINE_TOKEN.exec(text))) {
    if (m.index > lastIdx) {
      out.push(text.slice(lastIdx, m.index))
    }
    const tok = m[0]
    const link = tok.match(LINK_TOKEN)
    if (link) {
      const [, label, url] = link
      if (/^https?:\/\//i.test(url)) {
        // Real external link — same target/rel pattern the report chapters use.
        out.push(
          <a
            key={out.length}
            href={url}
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: 'var(--info)' }}
          >
            {label}
          </a>,
        )
      } else {
        // Internal ref (sandbox://… artifact link, anchors) — not a navigable
        // URL. Show the label as styled text so the raw [text](url) syntax never
        // leaks, without emitting a dead anchor.
        out.push(
          <span key={out.length} style={{ color: 'var(--info)' }}>
            {label}
          </span>,
        )
      }
    } else if (tok.startsWith('**') && tok.endsWith('**')) {
      out.push(<strong key={out.length}>{tok.slice(2, -2)}</strong>)
    } else if (tok.startsWith('`') && tok.endsWith('`')) {
      out.push(
        <code
          key={out.length}
          style={{
            padding: '1px 4px',
            background: 'var(--surface)',
            border: '1px solid var(--border)',
            borderRadius: 3,
            fontSize: '0.85em',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {tok.slice(1, -1)}
        </code>,
      )
    } else if (
      (tok.startsWith('*') && tok.endsWith('*')) ||
      (tok.startsWith('_') && tok.endsWith('_'))
    ) {
      out.push(<em key={out.length}>{tok.slice(1, -1)}</em>)
    } else {
      out.push(tok)
    }
    lastIdx = m.index + tok.length
  }
  if (lastIdx < text.length) out.push(text.slice(lastIdx))
  return out
}
