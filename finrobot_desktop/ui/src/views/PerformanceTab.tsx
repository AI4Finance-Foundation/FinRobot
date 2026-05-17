/**
 * PerformanceTab — 走势 tab.
 *
 * Reuses existing chart components:
 *   - PriceChart (simple or technical toggle)
 *   - RelativePerformanceChart (vs SPY)
 *   - TechnicalIndicators
 */

import { useState } from 'react'
import { useAppStore } from '../stores/appStore'
import PriceChart from '../components/charts/PriceChart'
import TechnicalAnalysisView from '../components/charts/TechnicalAnalysisView'
import { usePerformanceData } from '../hooks/usePerformanceData'
import { RelativePerformanceChart } from '../components/charts'

type ChartMode = 'simple' | 'technical'

export default function PerformanceTab() {
  const ticker = useAppStore((s) => s.ticker)
  const performanceData = useAppStore((s) => s.performanceData)

  const [chartMode, setChartMode] = useState<ChartMode>('simple')

  // Load relative performance data (SPY comparison)
  usePerformanceData([])

  return (
    <div className="tab-content performance-tab">
      {/* Price chart with mode toggle */}
      <section className="chart-section">
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 'var(--sp-3)',
          }}
        >
          <h3 className="section-title" style={{ marginBottom: 0 }}>
            价格走势
          </h3>
          <div className="chart-mode-toggle">
            <button
              className={`chart-mode-btn${chartMode === 'simple' ? ' active' : ''}`}
              onClick={() => setChartMode('simple')}
              aria-pressed={chartMode === 'simple'}
            >
              简明
            </button>
            <button
              className={`chart-mode-btn${chartMode === 'technical' ? ' active' : ''}`}
              onClick={() => setChartMode('technical')}
              aria-pressed={chartMode === 'technical'}
            >
              技术
            </button>
          </div>
        </div>

        {chartMode === 'simple' ? (
          <PriceChart title={`${ticker} 历史价格`} />
        ) : (
          <TechnicalAnalysisView />
        )}
      </section>

      {/* Relative performance vs SPY */}
      {performanceData && (
        <section className="chart-section">
          <h3 className="section-title">相对走势（vs SPY，归一化）</h3>
          <RelativePerformanceChart
            data={performanceData}
            title="相对走势"
          />
        </section>
      )}
    </div>
  )
}
