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
            Price Chart
          </h3>
          <div className="chart-mode-toggle">
            <button
              className={`chart-mode-btn${chartMode === 'simple' ? ' active' : ''}`}
              onClick={() => setChartMode('simple')}
              aria-pressed={chartMode === 'simple'}
            >
              Simple
            </button>
            <button
              className={`chart-mode-btn${chartMode === 'technical' ? ' active' : ''}`}
              onClick={() => setChartMode('technical')}
              aria-pressed={chartMode === 'technical'}
            >
              Technical
            </button>
          </div>
        </div>

        {chartMode === 'simple' ? (
          <PriceChart title={`${ticker} Price History`} />
        ) : (
          <TechnicalAnalysisView />
        )}
      </section>

      {/* Relative performance vs SPY */}
      {performanceData && (
        <section className="chart-section">
          <h3 className="section-title">Relative Performance (vs SPY, normalized)</h3>
          <RelativePerformanceChart
            data={performanceData}
            title="Relative Performance"
          />
        </section>
      )}
    </div>
  )
}
