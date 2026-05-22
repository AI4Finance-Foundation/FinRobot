// v5 §6.x 综合评分 — 0-100 composite score with 4 sub-dimensions
// (fundamental / valuation / catalyst / sentiment). Drives the dominant
// signal lamp + sub-score bars so retail users see one number first, then
// the breakdown explaining why.
//
// All scoring is deterministic — the LLM never picks the number. The
// numbers themselves are computed by finagent.engine.compute.composite_score
// from typed inputs (P/E, gross margin, catalyst counts, DCF upside).

import { useCompositeScore } from '../../hooks/useComputeQuery'
import type { CompositeScore } from '../../hooks/useComputeQuery'


interface CompositeScoreCardProps {
  ticker: string
}

function isCompleteScore(d: unknown): d is CompositeScore {
  if (!d || typeof d !== 'object') return false
  const o = d as Record<string, unknown>
  return (
    typeof o.total === 'number' &&
    typeof o.fundamental === 'number' &&
    typeof o.valuation === 'number' &&
    typeof o.catalyst === 'number' &&
    typeof o.sentiment === 'number' &&
    typeof o.signal === 'string'
  )
}

export function CompositeScoreCard({
  ticker,
}: CompositeScoreCardProps): React.ReactElement {
  const { data, isLoading, isError } = useCompositeScore(ticker)
  const validScore = isCompleteScore(data) ? data : null

  return (
    <section id="sec-score" className="cosmic-card" style={{ margin: "12px 0" }}>
      <header style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>🧮 综合评分</h2>
        <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
          基本面 30% · 估值 30% · 催化 20% · 情绪 20%
        </span>
      </header>

      {isLoading && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>计算中…</p>
      )}
      {isError && (
        <p style={{ fontSize: 12, color: 'var(--danger)' }}>评分计算失败</p>
      )}
      {!validScore && !isLoading && !isError && (
        <p style={{ fontSize: 12.5, color: 'var(--text-soft)' }}>
          需要至少一个基本面字段（PE / 毛利率 / 催化剂 / DCF 目标价）才能给分。
          先跑一次 AI 完整研报。
        </p>
      )}
      {validScore && <ScoreBody score={validScore} />}
    </section>
  )
}

function ScoreBody({ score }: { score: CompositeScore }): React.ReactElement {
  const color = signalColor(score.signal)
  return (
    <div style={{ display: 'flex', gap: 24, alignItems: 'center', flexWrap: 'wrap' }}>
      <ScoreDial total={score.total} color={color} />
      <div style={{ flex: 1, minWidth: 280 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 10,
            marginBottom: 12,
          }}
        >
          <span
            data-testid="composite-signal"
            data-signal={score.signal}
            style={{
              fontSize: 16,
              fontWeight: 700,
              color,
              letterSpacing: 0.4,
            }}
          >
            {signalLabel(score.signal)}
          </span>
          <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
            {signalThresholdHint(score.signal)}
          </span>
        </div>
        <SubScoreBar label="基本面" value={score.fundamental} reason={score.breakdown?.fundamental} />
        <SubScoreBar label="估值" value={score.valuation} reason={score.breakdown?.valuation} />
        <SubScoreBar label="催化" value={score.catalyst} reason={score.breakdown?.catalyst} />
        <SubScoreBar label="情绪" value={score.sentiment} reason={score.breakdown?.sentiment} />
      </div>
    </div>
  )
}

function ScoreDial({ total, color }: { total: number; color: string }): React.ReactElement {
  // Pure-SVG donut so we don't pull in a gauge lib. r=44, circumference=276.46.
  const r = 44
  const c = 2 * Math.PI * r
  const offset = c * (1 - total / 100)
  return (
    <div style={{ position: 'relative', width: 120, height: 120 }}>
      <svg viewBox="0 0 120 120" style={{ width: '100%', height: '100%' }}>
        <circle
          cx={60}
          cy={60}
          r={r}
          stroke="var(--border)"
          strokeWidth={10}
          fill="none"
        />
        <circle
          cx={60}
          cy={60}
          r={r}
          stroke={color}
          strokeWidth={10}
          fill="none"
          strokeDasharray={c}
          strokeDashoffset={offset}
          transform="rotate(-90 60 60)"
          strokeLinecap="round"
          style={{ transition: 'stroke-dashoffset 600ms ease' }}
        />
        <text
          x={60}
          y={60}
          textAnchor="middle"
          dominantBaseline="central"
          style={{
            fontSize: 28,
            fontWeight: 700,
            fill: 'var(--text)',
            fontFamily: "'JetBrains Mono', monospace",
          }}
        >
          {total}
        </text>
        <text
          x={60}
          y={84}
          textAnchor="middle"
          style={{ fontSize: 10, fill: 'var(--text-faint)' }}
        >
          / 100
        </text>
      </svg>
    </div>
  )
}

function SubScoreBar({
  label,
  value,
  reason,
}: {
  label: string
  value: number
  reason?: string
}): React.ReactElement {
  const pct = Math.max(0, Math.min(100, value))
  return (
    <div style={{ marginBottom: 8 }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'baseline',
          justifyContent: 'space-between',
          fontSize: 11.5,
          marginBottom: 3,
        }}
      >
        <span style={{ color: 'var(--text-soft)' }}>{label}</span>
        <span
          style={{
            color: 'var(--text)',
            fontVariantNumeric: 'tabular-nums',
            fontWeight: 600,
          }}
        >
          {value}
        </span>
      </div>
      <div
        style={{
          height: 6,
          borderRadius: 3,
          background: 'var(--border)',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            width: `${pct}%`,
            height: '100%',
            background: barColor(value),
            transition: 'width 600ms ease',
          }}
        />
      </div>
      {reason && reason !== 'Insufficient data' && (
        <div
          style={{
            marginTop: 2,
            fontSize: 10.5,
            color: 'var(--text-faint)',
            lineHeight: 1.4,
          }}
        >
          {reason}
        </div>
      )}
    </div>
  )
}

function signalColor(signal: CompositeScore['signal']): string {
  switch (signal) {
    case 'STRONG_BUY':
      return 'var(--success)'
    case 'BUY':
      return 'var(--success)'
    case 'HOLD':
      return 'var(--warning)'
    case 'SELL':
      return 'var(--danger)'
    case 'STRONG_SELL':
      return 'var(--danger)'
  }
}

function signalLabel(signal: CompositeScore['signal']): string {
  return {
    STRONG_BUY: '强力买入',
    BUY: '买入',
    HOLD: '观望',
    SELL: '卖出',
    STRONG_SELL: '强力卖出',
  }[signal]
}

function signalThresholdHint(signal: CompositeScore['signal']): string {
  return {
    STRONG_BUY: '80+',
    BUY: '60–79',
    HOLD: '40–59',
    SELL: '20–39',
    STRONG_SELL: '<20',
  }[signal]
}

function barColor(value: number): string {
  if (value >= 70) return 'var(--success)'
  if (value >= 55) return 'var(--success)'
  if (value >= 40) return 'var(--warning)'
  if (value >= 25) return 'var(--danger)'
  return 'var(--danger)'
}
