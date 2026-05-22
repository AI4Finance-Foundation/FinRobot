// v5 HERO 当前判断 (spec §6.1).
//
// Visual weight emphasis per the revised spec: target $X · 距 +Y% as the
// dominant 38px number (preventing the misread "AI 今天赚 X%"). Day-over-day
// price action becomes a small dated footnote, never the lead.

import { useLatestArtifact } from '../../hooks/useV5Artifacts'
import { useTickerPrice } from '../../hooks/useTickerData'
import { downloadShareCard } from '../../utils/shareCard'
import { useToastStore } from '../../stores/toastStore'
import { BASE_URL } from '../../api/client'

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 24,
  margin: '12px 0',
  background: 'var(--bg-card, #fff)',
}

interface HeroVerdictProps {
  ticker: string
}

export function HeroVerdict({ ticker }: HeroVerdictProps): React.ReactElement {
  const { latest } = useLatestArtifact(ticker, 'equity_research')
  const { data: priceData } = useTickerPrice(ticker)

  const target = latest?.target_price ?? null
  const entry = latest?.entry_price ?? null
  const current = priceData?.current_price ?? null
  const signal = latest?.signal ?? null

  // Pre-pipeline (cold) state — single CTA pointing to the run dropdown.
  if (!latest || target === null || entry === null) {
    return (
      <section id="sec-now" style={SECTION_STYLE}>
        <div style={{ fontSize: 14, color: 'var(--text-faint)' }}>
          🎯 当前判断 — 待 AI 完整研报
        </div>
        <p style={{ marginTop: 8, color: 'var(--text-soft)', fontSize: 13 }}>
          跑一次 AI 完整研报后，这里展示信号灯 / 目标价 / 当时 vs 现在的价格对比。
        </p>
      </section>
    )
  }

  const distancePct =
    current !== null && target > 0 ? ((target - current) / current) * 100 : null
  const sinceEntryPct =
    current !== null && entry > 0 ? ((current - entry) / entry) * 100 : null
  const daysSince = ageDays(latest.created_at)

  return (
    <section id="sec-now" style={SECTION_STYLE}>
      <header style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <SignalDot signal={signal} />
        <span style={{ fontSize: 14, fontWeight: 600 }}>🎯 当前判断</span>
        <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
          @ {daysSince} 天前 · 自报告以来{' '}
          {sinceEntryPct !== null
            ? `${sinceEntryPct >= 0 ? '↑' : '↓'} ${Math.abs(sinceEntryPct).toFixed(1)}%`
            : '—'}
        </span>
      </header>

      <div style={{ fontSize: 38, fontWeight: 700, letterSpacing: -0.5 }}>
        目标 ${target.toFixed(2)}
        {distancePct !== null && (
          <span
            style={{
              marginLeft: 12,
              fontSize: 22,
              color: distancePct >= 0 ? 'var(--green, #10B981)' : 'var(--red, #EF4444)',
              fontWeight: 600,
            }}
          >
            · 距 {distancePct >= 0 ? '+' : ''}
            {distancePct.toFixed(1)}%
          </span>
        )}
      </div>

      <p style={{ marginTop: 8, color: 'var(--text-mid)', fontSize: 13, lineHeight: 1.55 }}>
        {(latest.headline || '').slice(0, 80)}
      </p>

      <p
        style={{
          marginTop: 12,
          fontSize: 11,
          color: 'var(--text-faint)',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        当时股价 ${entry.toFixed(2)}
        {current !== null && ` → 当前 $${current.toFixed(2)}`}
      </p>

      <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
        <button
          type="button"
          data-testid="hero-share-card"
          onClick={() =>
            downloadShareCard({
              artifact: latest,
              currentPrice: current,
              daysSinceEntry: daysSince,
            })
          }
          style={{
            fontSize: 11.5,
            padding: '6px 12px',
            borderRadius: 6,
            border: '1px solid var(--border)',
            background: 'transparent',
            color: 'var(--text-soft)',
            cursor: 'pointer',
          }}
        >
          📤 分享图
        </button>
        <button
          type="button"
          data-testid="hero-pdf-download"
          onClick={async () => {
            const addToast = useToastStore.getState().addToast
            try {
              const resp = await fetch(`${BASE_URL}/api/exports/pdf/${latest.id}`, {
                method: 'POST',
              })
              if (!resp.ok) {
                if (resp.status === 501) {
                  addToast({
                    type: 'info',
                    title: 'PDF 导出未启用',
                    description: '后端需安装 weasyprint 才能生成 PDF · 暂用分享图替代',
                  })
                  return
                }
                throw new Error(`HTTP ${resp.status}`)
              }
              const blob = await resp.blob()
              const url = URL.createObjectURL(blob)
              const a = document.createElement('a')
              a.href = url
              a.download = `${ticker}_${latest.id}.pdf`
              document.body.appendChild(a)
              a.click()
              a.remove()
              URL.revokeObjectURL(url)
              addToast({ type: 'success', title: 'PDF 已下载', description: a.download })
            } catch (err) {
              const msg = err instanceof Error ? err.message : String(err)
              addToast({ type: 'error', title: 'PDF 导出失败', description: msg })
            }
          }}
          style={{
            fontSize: 11.5,
            padding: '6px 12px',
            borderRadius: 6,
            border: '1px solid var(--border)',
            background: 'transparent',
            color: 'var(--text-soft)',
            cursor: 'pointer',
          }}
        >
          📥 PDF
        </button>
      </div>
    </section>
  )
}

function SignalDot({ signal }: { signal: 'hit' | 'watching' | 'failed' | null }) {
  const color =
    signal === 'hit'
      ? '#10B981'
      : signal === 'failed'
        ? '#EF4444'
        : signal === 'watching'
          ? '#F59E0B'
          : 'var(--text-faint)'
  return (
    <span
      data-testid="hero-signal-dot"
      data-signal={signal ?? 'none'}
      style={{
        width: 14,
        height: 14,
        borderRadius: '50%',
        background: color,
        display: 'inline-block',
        boxShadow: `0 0 0 4px ${color}22`,
      }}
    />
  )
}

function ageDays(isoDate: string): number {
  const d = new Date(isoDate)
  return Math.max(0, Math.round((Date.now() - d.getTime()) / (24 * 3600 * 1000)))
}
