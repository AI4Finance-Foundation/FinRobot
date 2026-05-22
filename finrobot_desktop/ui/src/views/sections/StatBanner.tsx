// v5 §7.3 statistics banner. Renders three display states per spec:
//   N_total < 3                                → hide entire banner
//   N_total ≥ 3 and N_closed < 3               → "X 份 · K 已结案 · 样本不足"
//   N_total ≥ 3 and N_closed ≥ 3               → full hit rate + excess return
//
// Plus a small honesty disclaimer (selection-bias note flagged by the
// PR1 finance auditor → BACKLOG v2 calibration item, surfaced as a sentence
// here so users see it from day 1).

import type { ArtifactSummaryV5, Signal } from '../../types/v5'
import { HitRateSparkline } from './HitRateSparkline'

interface StatBannerProps {
  ticker: string
  artifacts: ArtifactSummaryV5[]
}

export function StatBanner({ ticker, artifacts }: StatBannerProps): React.ReactElement | null {
  // Normalise undefined → null up front so downstream filters can rely on a
  // narrow shape (backend may omit `signal` for legacy artifacts).
  const signals: (Signal | null)[] = artifacts.map((a) => a.signal ?? null)
  const nTotal = signals.filter((s) => s !== null).length
  if (nTotal < 3) return null

  const nClosed = signals.filter((s) => s === 'hit' || s === 'failed').length
  const nHit = signals.filter((s) => s === 'hit').length

  const insufficient = nClosed < 3

  return (
    <div
      data-testid="stat-banner"
      style={{
        border: '1px solid var(--border)',
        borderRadius: 10,
        padding: 16,
        margin: '12px 0',
        background: 'rgba(16, 185, 129, 0.04)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          gap: 10,
          flexWrap: 'wrap',
        }}
      >
        {insufficient ? (
          <span style={{ fontSize: 14, fontWeight: 600 }}>
            {nTotal} 份分析 · {nClosed} 份已结案 · 样本不足（≥3 才统计命中率）
          </span>
        ) : (
          <>
            <span style={{ fontSize: 28, fontWeight: 700, color: 'var(--success)' }}>
              命中率 {Math.round((nHit / nClosed) * 100)}%
            </span>
            <span style={{ fontSize: 13, color: 'var(--text-soft)' }}>
              · {nHit}/{nClosed} 次（{nTotal} 份分析，{nTotal - nClosed} 份观察中）
            </span>
          </>
        )}
        <HitRateSparkline signals={signals} />
      </div>
      <p style={{ marginTop: 6, fontSize: 11, color: 'var(--text-faint)' }}>
        命中率分母 = 已结案样本（hit + failed）· watching 不参与统计 ·
        样本由你选择 · 反映你的选股偏好 + 模型质量综合，不等于策略 alpha · ticker {ticker}
      </p>
    </div>
  )
}
