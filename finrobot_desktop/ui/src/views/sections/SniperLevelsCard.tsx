// v5 §6.x 阻力位 / 支撑位 — deterministic entry/exit price levels from
// DCF target + 3-month historical prices. Designed for retail readers who
// want concrete actionable numbers (理想买点 / 止损 / 止盈 / 风报比) without
// having to interpret a DCF model themselves.
//
// All numbers come from finagent.engine.compute.sniper.calculate_sniper_points —
// no LLM rounding, no vibes. The UI just renders the price-axis layout.

import { useSniperPoints } from '../../hooks/useComputeQuery'
import { useTickerPrice } from '../../hooks/useTickerData'
import type { SniperPoints } from '../../hooks/useComputeQuery'

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card, #fff)',
}

interface SniperLevelsCardProps {
  ticker: string
}

function isCompleteSniper(d: unknown): d is SniperPoints {
  if (!d || typeof d !== 'object') return false
  const o = d as Record<string, unknown>
  return (
    typeof o.ideal_buy === 'number' &&
    typeof o.secondary_buy === 'number' &&
    typeof o.stop_loss === 'number' &&
    typeof o.take_profit === 'number'
  )
}

export function SniperLevelsCard({
  ticker,
}: SniperLevelsCardProps): React.ReactElement {
  const { data, isLoading, isError } = useSniperPoints(ticker)
  const { data: priceData } = useTickerPrice(ticker)
  const currentPrice = priceData?.current_price ?? null
  const validPoints = isCompleteSniper(data) ? data : null

  return (
    <section id="sec-sniper" style={SECTION_STYLE}>
      <header style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>🎯 阻力位 / 支撑位</h2>
        <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
          基于 DCF 目标 + 过去 3 个月价格区间
        </span>
      </header>

      {isLoading && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>计算中…</p>
      )}
      {isError && (
        <p style={{ fontSize: 12, color: 'var(--red, #EF4444)' }}>买卖点计算失败</p>
      )}
      {!validPoints && !isLoading && !isError && (
        <p style={{ fontSize: 12.5, color: 'var(--text-soft)' }}>
          需要 DCF 目标价（跑「AI 完整研报」后产生）和过去 90 天价格才能算阻力位。
        </p>
      )}
      {validPoints && <SniperBody points={validPoints} currentPrice={currentPrice} />}
    </section>
  )
}

function SniperBody({
  points,
  currentPrice,
}: {
  points: SniperPoints
  currentPrice: number | null
}): React.ReactElement {
  const cards: { label: string; value: number; sub?: string; color: string; testId: string }[] = [
    {
      label: '理想买点',
      value: points.ideal_buy,
      sub: `安全边际 ${(points.safety_margin * 100).toFixed(0)}%`,
      color: '#10B981',
      testId: 'sniper-ideal-buy',
    },
    {
      label: '二次买点',
      value: points.secondary_buy,
      sub: '20 日支撑',
      color: '#34D399',
      testId: 'sniper-secondary-buy',
    },
    {
      label: '止损位',
      value: points.stop_loss,
      sub: '波动调整下沿',
      color: '#EF4444',
      testId: 'sniper-stop-loss',
    },
    {
      label: '止盈位',
      value: points.take_profit,
      sub: 'DCF 目标',
      color: '#F59E0B',
      testId: 'sniper-take-profit',
    },
  ]
  return (
    <>
      <PriceRuler points={points} currentPrice={currentPrice} />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
          gap: 10,
          marginTop: 16,
        }}
      >
        {cards.map((c) => (
          <div
            key={c.label}
            data-testid={c.testId}
            style={{
              border: '1px solid var(--border)',
              borderRadius: 8,
              padding: '10px 12px',
              background: 'var(--bg-2, transparent)',
            }}
          >
            <div style={{ fontSize: 11, color: 'var(--text-faint)' }}>{c.label}</div>
            <div
              style={{
                marginTop: 2,
                fontSize: 18,
                fontWeight: 700,
                color: c.color,
                fontFamily: "'JetBrains Mono', monospace",
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              ${c.value.toFixed(2)}
            </div>
            {c.sub && (
              <div style={{ marginTop: 2, fontSize: 10.5, color: 'var(--text-faint)' }}>
                {c.sub}
              </div>
            )}
          </div>
        ))}
      </div>
      <div
        style={{
          marginTop: 14,
          padding: '8px 12px',
          border: '1px solid var(--border-soft)',
          borderRadius: 6,
          fontSize: 11.5,
          color: 'var(--text-soft)',
          display: 'flex',
          gap: 18,
          flexWrap: 'wrap',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        <span>
          风报比{' '}
          <strong
            data-testid="sniper-risk-reward"
            style={{
              color: points.risk_reward_ratio >= 2 ? '#10B981' : 'var(--text)',
              fontWeight: 700,
            }}
          >
            {points.risk_reward_ratio.toFixed(2)}
          </strong>
        </span>
        <span>建议仓位 {points.position_size_pct.toFixed(1)}%</span>
        <span>支撑 ${points.support_level.toFixed(2)}</span>
        <span>阻力 ${points.resistance_level.toFixed(2)}</span>
      </div>
    </>
  )
}

function PriceRuler({
  points,
  currentPrice,
}: {
  points: SniperPoints
  currentPrice: number | null
}): React.ReactElement {
  const all = [
    points.stop_loss,
    points.ideal_buy,
    points.secondary_buy,
    points.take_profit,
    points.support_level,
    points.resistance_level,
    ...(currentPrice ? [currentPrice] : []),
  ]
  const min = Math.min(...all)
  const max = Math.max(...all)
  const range = max - min || 1
  const pct = (v: number) => `${((v - min) / range) * 100}%`

  const markers = [
    { v: points.stop_loss, label: '止损', color: '#EF4444', above: false },
    { v: points.ideal_buy, label: '理想买', color: '#10B981', above: false },
    { v: points.secondary_buy, label: '二次买', color: '#34D399', above: true },
    { v: points.take_profit, label: '止盈', color: '#F59E0B', above: true },
  ]

  return (
    <div style={{ position: 'relative', height: 84, marginTop: 12 }}>
      {/* Range track */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          right: 0,
          top: 38,
          height: 6,
          borderRadius: 3,
          background:
            'linear-gradient(to right, rgba(239,68,68,0.35), rgba(245,158,11,0.35), rgba(16,185,129,0.45))',
        }}
      />
      {/* Markers */}
      {markers.map((m) => (
        <div
          key={m.label}
          style={{
            position: 'absolute',
            left: pct(m.v),
            top: 30,
            transform: 'translateX(-50%)',
            textAlign: 'center',
            fontSize: 10,
            color: m.color,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          <div
            style={{
              width: 2,
              height: 22,
              background: m.color,
              margin: '0 auto',
            }}
          />
          <div style={{ marginTop: m.above ? -38 : 4, position: 'relative', top: m.above ? -28 : 0 }}>
            {m.label}
            <div style={{ color: 'var(--text-soft)' }}>${m.v.toFixed(2)}</div>
          </div>
        </div>
      ))}
      {/* Current price marker (large) */}
      {currentPrice !== null && (
        <div
          data-testid="sniper-current-marker"
          style={{
            position: 'absolute',
            left: pct(currentPrice),
            top: 26,
            transform: 'translateX(-50%)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
          }}
        >
          <div
            style={{
              width: 12,
              height: 12,
              borderRadius: 6,
              background: '#3B82F6',
              boxShadow: '0 0 0 3px rgba(59,130,246,0.25)',
            }}
          />
          <div
            style={{
              marginTop: 4,
              fontSize: 10.5,
              color: '#3B82F6',
              fontWeight: 600,
            }}
          >
            现价 ${currentPrice.toFixed(2)}
          </div>
        </div>
      )}
    </div>
  )
}
