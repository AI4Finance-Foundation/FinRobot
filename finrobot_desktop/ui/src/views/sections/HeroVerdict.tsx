// v5 HERO 当前判断 (spec §6.1).
//
// Visual weight emphasis per the revised spec: target $X · 距 +Y% as the
// dominant 38px number (preventing the misread "AI 今天赚 X%"). Day-over-day
// price action becomes a small dated footnote, never the lead.

import { useLatestArtifact, useArtifactDetail } from '../../hooks/useV5Artifacts'
import { useTickerPrice } from '../../hooks/useTickerData'
import { downloadShareCard } from '../../utils/shareCard'
import { useToastStore } from '../../stores/toastStore'
import { BASE_URL } from '../../api/client'

interface HeroVerdictProps {
  ticker: string
}

interface ThesisDetail {
  tagline?: string
  key_takeaways?: string[]
  valuation_overview?: string
  competitor_analysis?: string
  news_summary?: string
}

export function HeroVerdict({ ticker }: HeroVerdictProps): React.ReactElement {
  const { latest } = useLatestArtifact(ticker, 'equity_research')
  const { data: priceData } = useTickerPrice(ticker)
  const { data: artifact } = useArtifactDetail(latest?.id)

  const target = latest?.target_price ?? null
  const entry = latest?.entry_price ?? null
  const current = priceData?.current_price ?? null
  const signal = latest?.signal ?? null

  // FinRobot parity narrative fields live on the full artifact only —
  // ArtifactSummary doesn't carry them. Pull them off the cached detail.
  const thesis = ((artifact?.outputs as { structured?: { thesis?: unknown } } | undefined)
    ?.structured?.thesis ?? null) as ThesisDetail | null
  const tagline = typeof thesis?.tagline === 'string' ? thesis.tagline : null
  const takeaways = Array.isArray(thesis?.key_takeaways)
    ? thesis!.key_takeaways!.filter((s): s is string => typeof s === 'string')
    : []

  // Pre-pipeline (cold) state — single CTA pointing to the run dropdown.
  if (!latest || target === null || entry === null) {
    return (
      <section id="sec-now" className="cosmic-card" style={{ margin: '12px 0' }}>
        <div style={{ fontSize: 14, color: 'var(--text-muted)' }}>
          🎯 当前判断 — 待 AI 完整研报
        </div>
        <p style={{ marginTop: 8, color: 'var(--text-secondary)', fontSize: 13 }}>
          跑一次 AI 完整研报后，这里展示 BUY/HOLD/SELL 大徽章 / 目标价 / 当时 vs 现在的价格对比。
        </p>
      </section>
    )
  }

  // Derive BUY/HOLD/SELL from the artifact thesis if available — falls back
  // to the signal lamp colour when the LLM didn't emit a verdict yet.
  const verdict = readVerdict(thesis)

  const distancePct =
    current !== null && target > 0 ? ((target - current) / current) * 100 : null
  const sinceEntryPct =
    current !== null && entry > 0 ? ((current - entry) / entry) * 100 : null
  const daysSince = ageDays(latest.created_at)

  return (
    <section id="sec-now" className="cosmic-card" style={{ margin: '12px 0' }}>
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          marginBottom: 18,
          flexWrap: 'wrap',
        }}
      >
        {verdict ? (
          <span
            className={`cosmic-badge cosmic-badge-${verdict.toLowerCase()}`}
            data-testid="hero-verdict-badge"
            aria-label={`${verdict} verdict`}
          >
            {verdict}
          </span>
        ) : (
          <SignalDot signal={signal} />
        )}
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 14,
            letterSpacing: 2.5,
            color: 'var(--text-primary)',
          }}
        >
          当前判断
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-muted)',
            letterSpacing: '0.06em',
          }}
        >
          @ {daysSince} 天前 · 自报告以来{' '}
          {sinceEntryPct !== null
            ? `${sinceEntryPct >= 0 ? '↑' : '↓'} ${Math.abs(sinceEntryPct).toFixed(1)}%`
            : '—'}
        </span>
      </header>

      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 38,
          fontWeight: 600,
          letterSpacing: -0.5,
          color: 'var(--text-primary)',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        目标 ${target.toFixed(2)}
        {distancePct !== null && (
          <span
            style={{
              marginLeft: 14,
              fontSize: 22,
              color: distancePct >= 0 ? 'var(--success)' : 'var(--danger)',
              fontWeight: 600,
              textShadow:
                distancePct >= 0
                  ? '0 0 16px var(--success-glow)'
                  : '0 0 16px var(--danger-glow)',
            }}
          >
            · 距 {distancePct >= 0 ? '+' : ''}
            {distancePct.toFixed(1)}%
          </span>
        )}
      </div>

      {tagline ? (
        <p
          style={{
            marginTop: 10,
            color: 'var(--accent-cyan)',
            fontSize: 14,
            lineHeight: 1.55,
            fontFamily: 'var(--font-body)',
            fontWeight: 500,
            textShadow: '0 0 12px rgba(34,211,238,0.25)',
          }}
        >
          “{tagline}”
        </p>
      ) : (
        <p style={{ marginTop: 8, color: 'var(--text-mid)', fontSize: 13, lineHeight: 1.55 }}>
          {(latest.headline || '').slice(0, 80)}
        </p>
      )}

      {takeaways.length > 0 && (
        <ul
          style={{
            marginTop: 12,
            paddingLeft: 22,
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
            color: 'var(--text-secondary)',
            fontSize: 12.5,
            lineHeight: 1.5,
          }}
        >
          {takeaways.slice(0, 5).map((t, i) => (
            <li key={i}>{t}</li>
          ))}
        </ul>
      )}

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

function readVerdict(
  thesis: ThesisDetail | null,
): 'BUY' | 'HOLD' | 'SELL' | null {
  const raw = (thesis as unknown as { recommendation?: string } | null)?.recommendation
  if (!raw || typeof raw !== 'string') return null
  const norm = raw.trim().toUpperCase()
  return norm === 'BUY' || norm === 'HOLD' || norm === 'SELL' ? norm : null
}

function SignalDot({ signal }: { signal: 'hit' | 'watching' | 'failed' | null }) {
  const color =
    signal === 'hit'
      ? 'var(--success)'
      : signal === 'failed'
        ? 'var(--danger)'
        : signal === 'watching'
          ? 'var(--warning)'
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
