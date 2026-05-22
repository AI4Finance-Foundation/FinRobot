// v5 §6.x 蒙特卡洛公允价值分布 — N=5000 simulated DCF runs perturbing
// growth / margin / WACC / terminal growth assumptions and showing the
// resulting price distribution. Designed to communicate uncertainty
// honestly: a single DCF point estimate hides assumption sensitivity that
// a histogram makes obvious.

import { useMonteCarloAuto } from '../../hooks/useComputeQuery'
import { useTickerPrice } from '../../hooks/useTickerData'
import MonteCarloChart from '../../components/charts/MonteCarloChart'
import type { MonteCarloResult } from '../../stores/appStore'

function isCompleteMC(d: unknown): d is MonteCarloResult {
  if (!d || typeof d !== 'object') return false
  const o = d as Record<string, unknown>
  return (
    Array.isArray(o.histogram_bins) &&
    Array.isArray(o.histogram_counts) &&
    typeof o.mean === 'number' &&
    !!o.percentiles
  )
}


interface MonteCarloSectionProps {
  ticker: string
}

export function MonteCarloSection({
  ticker,
}: MonteCarloSectionProps): React.ReactElement {
  const { data, isLoading, isError, error } = useMonteCarloAuto(ticker)
  const { data: priceData } = useTickerPrice(ticker)
  const currentPrice = priceData?.current_price ?? null
  const validResult = isCompleteMC(data) ? data : null

  return (
    <section id="sec-monte-carlo" className="cosmic-card" style={{ margin: "12px 0" }}>
      <header style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>🎲 蒙特卡洛公允价值分布</h2>
        <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
          扰动假设跑 5000 次 DCF，看现价落在哪个百分位
        </span>
      </header>

      {isLoading && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>模拟中…（5000 次仿真，约 100ms）</p>
      )}
      {isError && (
        <p style={{ fontSize: 12, color: 'var(--danger)' }}>
          模拟失败 — {String(error?.message ?? '').slice(0, 140)}
        </p>
      )}
      {!validResult && !isLoading && !isError && (
        <p style={{ fontSize: 12.5, color: 'var(--text-soft)' }}>
          需要 DCF 假设（跑「AI 完整研报」或「DCF」后产生）才能跑蒙特卡洛。
        </p>
      )}
      {validResult && <MonteCarloChart result={validResult} currentPrice={currentPrice} />}
    </section>
  )
}
