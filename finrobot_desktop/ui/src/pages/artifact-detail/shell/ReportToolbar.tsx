// Sticky top toolbar for the 12-chapter research report view.
// Lives at the top of ArtifactDetailPage and surfaces:
//   - breadcrumb path back through /stocks → ticker → this report
//   - live price chip + distance-to-target overlay (artifact thesis × live)
//   - version select (jumps to a sibling artifact of the same ticker/type)
//   - secondary actions: Diff vs prior, What-if (P4.2 placeholder), PDF, Re-run

import { useNavigate } from 'react-router-dom'
import { useTickerPrice } from '../../../hooks/useTickerData'
import { useRunStreamStore } from '../../../stores/runStreamStore'
import { useToastStore } from '../../../stores/toastStore'
import { BASE_URL } from '../../../api/client'
import type { ArtifactSummaryV5 } from '../../../types/v5'

interface ReportToolbarProps {
  ticker: string
  artifactId: string
  reportType: string
  reportVersionLabel: string  // e.g. "v3 · 2026-05-23"
  targetPrice: number | null
  timeline: ArtifactSummaryV5[]
  onOpenDiff: () => void
}

export function ReportToolbar({
  ticker,
  artifactId,
  reportType,
  reportVersionLabel,
  targetPrice,
  timeline,
  onOpenDiff,
}: ReportToolbarProps): React.ReactElement {
  const navigate = useNavigate()
  const { data: priceData } = useTickerPrice(ticker)
  const startRun = useRunStreamStore((s) => s.startRun)
  const addToast = useToastStore((s) => s.addToast)

  const livePrice = priceData?.current_price ?? null
  const changePct = priceData?.change_pct ?? null
  const isUp = typeof changePct === 'number' && changePct >= 0
  const distancePct =
    livePrice !== null && targetPrice !== null && livePrice > 0
      ? ((targetPrice - livePrice) / livePrice) * 100
      : null

  async function handleRerun(): Promise<void> {
    try {
      const runId = await startRun('research', ticker)
      addToast({
        type: 'success',
        title: `${ticker} 重跑研报已启动`,
        description: `run_id: ${runId.slice(0, 12)} · 完成后在工作区抽屉中看 v 历史`,
      })
      navigate(`/stocks/${ticker}`)
    } catch (err) {
      addToast({
        type: 'error',
        title: '启动重跑失败',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  async function handlePdf(): Promise<void> {
    try {
      const resp = await fetch(`${BASE_URL}/api/exports/pdf/${artifactId}`, { method: 'POST' })
      if (resp.status === 501) {
        addToast({
          type: 'info',
          title: 'PDF 导出未启用',
          description: '后端缺 weasyprint 依赖 · 暂走分享图',
        })
        return
      }
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${ticker}_${artifactId.slice(0, 12)}.pdf`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      addToast({ type: 'success', title: 'PDF 已下载', description: a.download })
    } catch (err) {
      addToast({
        type: 'error',
        title: 'PDF 导出失败',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  function handleVersionChange(targetArtifactId: string): void {
    if (targetArtifactId && targetArtifactId !== artifactId) {
      navigate(`/stocks/${ticker}/runs/${targetArtifactId}`)
    }
  }

  return (
    <div
      data-testid="report-toolbar"
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 30,
        display: 'grid',
        gridTemplateColumns: '1fr auto auto',
        alignItems: 'center',
        gap: 20,
        padding: '14px 24px',
        margin: '0 -24px 16px',
        background: 'rgba(10, 10, 24, 0.88)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        borderBottom: '1px solid var(--border-soft)',
      }}
    >
      {/* Breadcrumb */}
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          letterSpacing: '0.06em',
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
        }}
      >
        FINAGENT <Sep /> STOCKS <Sep />
        <span style={{ color: 'var(--accent-cyan)' }}>{ticker}</span> <Sep /> RESEARCH <Sep />
        <span style={{ color: 'var(--secondary)' }}>{reportVersionLabel}</span>
      </div>

      {/* Live price + distance to target */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontFamily: 'var(--font-mono)' }}>
        <span
          style={{
            fontSize: 17,
            color: 'var(--text-primary)',
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          {typeof livePrice === 'number' ? `$${livePrice.toFixed(2)}` : '—'}
        </span>
        {typeof changePct === 'number' && (
          <span
            style={{
              fontSize: 12,
              padding: '3px 8px',
              borderRadius: 5,
              background: isUp ? 'rgba(22,163,74,0.14)' : 'rgba(220,38,38,0.14)',
              color: isUp ? 'var(--success)' : 'var(--danger)',
              border: `1px solid ${isUp ? 'rgba(22,163,74,0.32)' : 'rgba(220,38,38,0.32)'}`,
            }}
          >
            {isUp ? '↑' : '↓'} {Math.abs(changePct).toFixed(2)}%
          </span>
        )}
        {distancePct !== null && (
          <span
            style={{
              fontSize: 12,
              padding: '3px 8px',
              borderRadius: 5,
              color: 'var(--secondary)',
              background: 'var(--secondary-soft)',
              border: '1px solid var(--secondary)',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            距目标 {distancePct >= 0 ? '+' : ''}
            {distancePct.toFixed(1)}%
          </span>
        )}
      </div>

      {/* Action group */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {timeline.length > 1 && (
          <select
            data-testid="version-select"
            value={artifactId}
            onChange={(e) => handleVersionChange(e.target.value)}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              padding: '5px 10px',
              borderRadius: 6,
              background: 'var(--bg-card)',
              color: 'var(--secondary)',
              border: '1px solid var(--secondary)',
              cursor: 'pointer',
            }}
          >
            {timeline
              .filter((a) => a.type === reportType)
              .map((a) => (
                <option key={a.id} value={a.id} style={{ background: 'var(--bg-card)' }}>
                  {a.id === artifactId ? '当前 · ' : ''}
                  {new Date(a.created_at).toLocaleString('zh-CN', {
                    month: '2-digit',
                    day: '2-digit',
                  })}
                  {' · '}
                  {(a.signal ?? 'pending').toUpperCase()}
                </option>
              ))}
          </select>
        )}
        <ToolbarButton onClick={onOpenDiff}>↹ Diff</ToolbarButton>
        <ToolbarButton disabled title="P4.2 — 可编辑假设重算（待落地）">
          ✏️ What-if
        </ToolbarButton>
        <ToolbarButton onClick={handlePdf}>📤 PDF</ToolbarButton>
        <ToolbarButton onClick={handleRerun} primary>
          ↻ Re-run
        </ToolbarButton>
      </div>
    </div>
  )
}

function Sep(): React.ReactElement {
  return <span style={{ color: 'var(--text-dim)', margin: '0 6px' }}>›</span>
}

function ToolbarButton({
  children,
  onClick,
  disabled,
  primary,
  title,
}: {
  children: React.ReactNode
  onClick?: () => void
  disabled?: boolean
  primary?: boolean
  title?: string
}): React.ReactElement {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        padding: '6px 11px',
        borderRadius: 6,
        border: primary ? 'none' : '1px solid var(--border-soft)',
        background: primary
          ? 'linear-gradient(135deg, var(--secondary) 0%, var(--primary) 100%)'
          : 'transparent',
        color: primary ? 'white' : 'var(--text-secondary)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        letterSpacing: '0.04em',
        transition: 'all 0.18s',
      }}
    >
      {children}
    </button>
  )
}
