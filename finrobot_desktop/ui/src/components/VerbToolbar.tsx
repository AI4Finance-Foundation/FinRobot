/**
 * VerbToolbar — minimal action bar for the Stocks page.
 *
 * After the 2026-05 simplification this bar only carries two buttons:
 *   - 一键全面分析 (hero, primary action)
 *   - 问 AI (right side)
 *
 * Per-tool actions (DCF / LBO / DDM / Comps / Earnings / IC Memo / Catalysts)
 * moved into their respective tabs to remove the "verb input vs noun view"
 * cognitive split — see /memory/feedback_product_direction.md.
 */

import { useEffect, useState } from 'react'

interface VerbToolbarProps {
  ticker: string
  onAskAi?: () => void
  onFullAnalysis?: () => void
  fullAnalysisRunning?: boolean
  /** Unix ms of last successful run completion. Drives the rerun-label timestamp. */
  lastRunAt?: number | null
}

function Spinner() {
  return (
    <svg
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      aria-hidden="true"
      style={{ animation: 'spin 0.8s linear infinite' }}
    >
      <circle cx="6" cy="6" r="4" stroke="currentColor" strokeWidth="2" strokeDasharray="20 8" />
    </svg>
  )
}

/** Human-friendly "2 分钟前" — recomputed every 30s so the label doesn't stale. */
function useRelativeTime(epochMs: number | null | undefined): string {
  const [, force] = useState(0)
  useEffect(() => {
    if (!epochMs) return
    const id = window.setInterval(() => force((n) => n + 1), 30_000)
    return () => window.clearInterval(id)
  }, [epochMs])

  if (!epochMs) return ''
  const diffSec = Math.max(0, Math.floor((Date.now() - epochMs) / 1000))
  if (diffSec < 60)        return `${diffSec} 秒前`
  if (diffSec < 3600)      return `${Math.floor(diffSec / 60)} 分钟前`
  if (diffSec < 86_400)    return `${Math.floor(diffSec / 3600)} 小时前`
  return `${Math.floor(diffSec / 86_400)} 天前`
}

export default function VerbToolbar({
  ticker,
  onAskAi,
  onFullAnalysis,
  fullAnalysisRunning,
  lastRunAt,
}: VerbToolbarProps) {
  const rel = useRelativeTime(lastRunAt)

  const heroLabel = fullAnalysisRunning
    ? '分析中...'
    : lastRunAt
      ? `⟳ 重新分析 · ${rel}`
      : '⚡ 一键全面分析'

  return (
    <div
      className="verb-toolbar"
      role="toolbar"
      aria-label="Analysis tools"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        padding: '8px 0',
        flexWrap: 'wrap',
      }}
    >
      <button
        onClick={() => onFullAnalysis?.()}
        disabled={!ticker || fullAnalysisRunning}
        title="跑 research + DCF + 同业 + 财报 四个分析（约 30-60 秒）"
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          padding: '7px 18px',
          fontSize: '0.87rem',
          fontWeight: 700,
          borderRadius: 'var(--r-sm)',
          border: '1px solid var(--accent)',
          background: fullAnalysisRunning ? 'var(--accent-dim)' : 'var(--accent)',
          color: fullAnalysisRunning ? 'var(--accent)' : '#000',
          cursor: !ticker || fullAnalysisRunning ? 'not-allowed' : 'pointer',
          opacity: !ticker ? 0.45 : 1,
          transition: 'background 0.15s, color 0.15s',
          whiteSpace: 'nowrap',
          letterSpacing: '0.02em',
        }}
      >
        {fullAnalysisRunning && <Spinner />}
        {heroLabel}
      </button>

      <div style={{ flex: 1 }} />

      <button
        onClick={() => onAskAi?.()}
        disabled={!ticker}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 5,
          padding: '6px 16px',
          fontSize: '0.87rem',
          fontWeight: 600,
          borderRadius: 'var(--r-sm)',
          border: 'none',
          background: 'var(--accent)',
          color: '#fff',
          cursor: !ticker ? 'not-allowed' : 'pointer',
          opacity: !ticker ? 0.45 : 1,
          transition: 'background 0.15s',
          whiteSpace: 'nowrap',
        }}
        title="向 FinAgent 提问关于这只股票的任何问题"
      >
        问 AI
      </button>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}
