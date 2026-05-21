// v5 §12.1 share-card generator. 1080×1080 PNG (dark theme for feed contrast)
// built via OffscreenCanvas. Falls back to in-DOM <canvas> for browsers without
// OffscreenCanvas (older Safari).
//
// Per ADR-D the Noto Sans CJK font bundle is deferred — we render with the
// system stack first (PingFang SC on macOS, Microsoft YaHei on Windows). If
// glyphs ever go missing we can revisit by bundling a 600KB woff2 subset.
//
// Public surface is one function:
//   buildShareCardPng(opts) -> Promise<Blob>
// Caller then downloads via the standard <a download> dance.

import type { ArtifactSummaryV5 } from '../types/v5'

const W = 1080
const H = 1080
const PAD = 64
const FONT_STACK =
  '-apple-system, "PingFang SC", "SF Pro Display", "Microsoft YaHei", "Inter", sans-serif'

export interface ShareCardInput {
  artifact: ArtifactSummaryV5
  currentPrice: number | null
  daysSinceEntry: number
}

export async function buildShareCardPng(input: ShareCardInput): Promise<Blob> {
  const canvas = createCanvas(W, H)
  const ctx = canvas.getContext('2d') as CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null
  if (!ctx) {
    throw new Error('canvas 2D context unavailable')
  }
  draw(ctx as CanvasRenderingContext2D, input)
  return canvasToBlob(canvas)
}

function draw(ctx: CanvasRenderingContext2D, { artifact, currentPrice, daysSinceEntry }: ShareCardInput): void {
  // Background
  ctx.fillStyle = '#0F1419'
  ctx.fillRect(0, 0, W, H)

  // Signal dot
  const signalColor = colorFor(artifact.signal)
  ctx.fillStyle = signalColor
  ctx.beginPath()
  ctx.arc(PAD + 32, PAD + 32, 32, 0, Math.PI * 2)
  ctx.fill()

  // Ticker (96px bold)
  ctx.fillStyle = '#FFFFFF'
  ctx.font = `700 96px ${FONT_STACK}`
  ctx.textBaseline = 'top'
  ctx.fillText(artifact.ticker ?? '—', PAD, PAD + 96)

  // Company / source (24px grey)
  ctx.fillStyle = '#6B7280'
  ctx.font = `400 22px ${FONT_STACK}`
  ctx.fillText(typeLabel(artifact.type), PAD, PAD + 96 + 110)

  // Divider
  ctx.strokeStyle = '#1F2937'
  ctx.lineWidth = 2
  ctx.beginPath()
  ctx.moveTo(PAD, PAD + 260)
  ctx.lineTo(W - PAD, PAD + 260)
  ctx.stroke()

  // Main number: gain since entry (when computable), else target distance.
  const entry = artifact.entry_price
  const target = artifact.target_price
  let bigText = '—'
  let bigColor = '#6B7280'
  let smallLine = ''
  if (entry !== null && currentPrice !== null && entry > 0) {
    const pct = ((currentPrice - entry) / entry) * 100
    bigText = `${pct >= 0 ? '↑' : '↓'} ${Math.abs(pct).toFixed(1)}%`
    bigColor = pct >= 0 ? '#10B981' : '#EF4444'
    smallLine =
      target !== null
        ? `目标 $${target.toFixed(2)} · 当时 $${entry.toFixed(2)} → $${currentPrice.toFixed(2)}`
        : `当时 $${entry.toFixed(2)} → $${currentPrice.toFixed(2)}`
  } else if (target !== null) {
    bigText = `目标 $${target.toFixed(2)}`
    smallLine = '尚未达成'
  }

  ctx.fillStyle = bigColor
  ctx.font = `700 160px ${FONT_STACK}`
  ctx.fillText(bigText, PAD, PAD + 300)

  // Status line
  ctx.fillStyle = '#FFFFFF'
  ctx.font = `500 32px ${FONT_STACK}`
  const statusText = `${signalLabel(artifact.signal)} · ${Math.max(1, daysSinceEntry)} 天`
  ctx.fillText(statusText, PAD, PAD + 500)

  // Detail line
  if (smallLine) {
    ctx.fillStyle = '#9CA3AF'
    ctx.font = `400 24px ${FONT_STACK}`
    ctx.fillText(smallLine, PAD, PAD + 555)
  }

  // Divider 2
  ctx.strokeStyle = '#1F2937'
  ctx.beginPath()
  ctx.moveTo(PAD, PAD + 640)
  ctx.lineTo(W - PAD, PAD + 640)
  ctx.stroke()

  // Headline (max 2 lines, 30 chars each)
  ctx.fillStyle = '#D1D5DB'
  ctx.font = `500 30px ${FONT_STACK}`
  drawWrappedText(ctx, `“${(artifact.headline || '').trim()}”`, PAD, PAD + 680, W - PAD * 2, 40)

  // Footer
  ctx.fillStyle = '#6B7280'
  ctx.font = `400 20px ${FONT_STACK}`
  ctx.fillText(`FinAgent · ${formatDate(artifact.created_at)}`, PAD, H - PAD - 32)
}

// ---------------------------------------------------------------------------

function drawWrappedText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  lineHeight: number,
  maxLines = 3,
): void {
  // Naive word-break; for CJK we split per-char so the algorithm degrades
  // gracefully without hyphenation.
  const chars = Array.from(text)
  let line = ''
  let cy = y
  let lines = 0
  for (const ch of chars) {
    const trial = line + ch
    if (ctx.measureText(trial).width > maxWidth && line !== '') {
      ctx.fillText(line, x, cy)
      line = ch
      cy += lineHeight
      lines += 1
      if (lines >= maxLines - 1) {
        // Last line — keep accumulating but truncate with ellipsis at end.
        for (const more of chars.slice(chars.indexOf(ch) + 1)) {
          if (ctx.measureText(line + more + '…').width > maxWidth) break
          line += more
        }
        line += '…'
        break
      }
    } else {
      line = trial
    }
  }
  if (line) ctx.fillText(line, x, cy)
}

function colorFor(signal: ArtifactSummaryV5['signal']): string {
  if (signal === 'hit') return '#10B981'
  if (signal === 'failed') return '#EF4444'
  if (signal === 'watching') return '#F59E0B'
  return '#374151'
}

function signalLabel(signal: ArtifactSummaryV5['signal']): string {
  if (signal === 'hit') return '命中'
  if (signal === 'failed') return '失败'
  if (signal === 'watching') return '观察中'
  return '待结案'
}

function typeLabel(type: ArtifactSummaryV5['type']): string {
  const labels: Partial<Record<ArtifactSummaryV5['type'], string>> = {
    equity_research: 'AI 完整研报',
    dcf: 'DCF 估值',
    ic_memo: '投委备忘',
    earnings: '财报分析',
    earnings_analysis: '财报分析',
    lbo: 'LBO 估值',
    ddm: '股息折现',
    comps: '同业对标',
    playground_snapshot: '手调假设',
    ad_hoc: '快速分析',
    peer_research: '同业研究',
  }
  return labels[type] ?? String(type)
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso)
    return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
  } catch {
    return iso
  }
}

// ---------------------------------------------------------------------------
// Canvas creation + Blob conversion (OffscreenCanvas-first with fallback)
// ---------------------------------------------------------------------------

type AnyCanvas = HTMLCanvasElement | OffscreenCanvas

function createCanvas(w: number, h: number): AnyCanvas {
  if (typeof OffscreenCanvas !== 'undefined') {
    return new OffscreenCanvas(w, h)
  }
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  return c
}

async function canvasToBlob(canvas: AnyCanvas): Promise<Blob> {
  if ('convertToBlob' in canvas) {
    return canvas.convertToBlob({ type: 'image/png' })
  }
  return await new Promise<Blob>((resolve, reject) => {
    ;(canvas as HTMLCanvasElement).toBlob((blob) => {
      if (blob) resolve(blob)
      else reject(new Error('canvas.toBlob returned null'))
    }, 'image/png')
  })
}

// ---------------------------------------------------------------------------
// Browser download helper — exported so the Hero / MyResearch components
// can wire a button without re-implementing the URL.createObjectURL dance.
// ---------------------------------------------------------------------------

export async function downloadShareCard(input: ShareCardInput, filenamePrefix = 'finagent'): Promise<void> {
  const blob = await buildShareCardPng(input)
  const url = URL.createObjectURL(blob)
  const ticker = input.artifact.ticker ?? 'cross'
  const date = (input.artifact.created_at ?? '').slice(0, 10)
  const a = document.createElement('a')
  a.href = url
  a.download = `${filenamePrefix}_${ticker}_${date}.png`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
