import { useAppStore } from '../stores/appStore'
import type { ScenarioKey, DCFResult } from '../stores/appStore'

const SCENARIO_META: Record<ScenarioKey, { label: string; colorClass: string }> = {
  bull: { label: 'Bull', colorClass: 'scenario-bull' },
  base: { label: 'Base', colorClass: 'scenario-base' },
  bear: { label: 'Bear', colorClass: 'scenario-bear' },
}

export default function ScenarioCompare() {
  const { scenarioResults, scenarios, currentPrice } = useAppStore()

  // Only render when at least 2 scenarios have results
  const filled = (['bull', 'base', 'bear'] as ScenarioKey[]).filter(
    (k) => scenarioResults[k] !== null
  )
  if (filled.length < 2) return null

  return (
    <div className="scenario-compare animate-in">
      <div className="scenario-compare-header">
        <span className="card-title">情景对比</span>
        {currentPrice != null && (
          <span className="scenario-current-price">
            当前 ${currentPrice.toFixed(2)}
          </span>
        )}
      </div>
      <div className="scenario-compare-grid">
        {(['bull', 'base', 'bear'] as ScenarioKey[]).map((key) => {
          const result = scenarioResults[key]
          const inputs = scenarios[key]
          if (!result) return <EmptyScenarioCard key={key} scenarioKey={key} />
          return (
            <ScenarioCard
              key={key}
              scenarioKey={key}
              result={result}
              growthRate={inputs?.revenue_growth_rates[0]}
              ebitdaMargin={inputs?.ebitda_margin}
              wacc={result.wacc}
              currentPrice={currentPrice}
            />
          )
        })}
      </div>
    </div>
  )
}

function ScenarioCard({
  scenarioKey,
  result,
  growthRate,
  ebitdaMargin,
  wacc,
  currentPrice,
}: {
  scenarioKey: ScenarioKey
  result: DCFResult
  growthRate: number | undefined
  ebitdaMargin: number | undefined
  wacc: number
  currentPrice: number | null
}) {
  const meta = SCENARIO_META[scenarioKey]
  const upside =
    currentPrice && currentPrice > 0
      ? ((result.implied_price - currentPrice) / currentPrice) * 100
      : null

  return (
    <div className={`scenario-card ${meta.colorClass}`}>
      <div className="scenario-card-label">{meta.label}</div>
      <div className="scenario-card-price">
        ${result.implied_price.toFixed(2)}
      </div>
      {upside !== null && (
        <div className={`scenario-card-upside ${upside >= 0 ? 'positive' : 'negative'}`}>
          {upside >= 0 ? '+' : ''}{upside.toFixed(1)}%
        </div>
      )}
      <div className="scenario-card-assumptions">
        {growthRate != null && (
          <div className="scenario-assumption">
            <span>第 1 年增速</span>
            <span>{(growthRate * 100).toFixed(1)}%</span>
          </div>
        )}
        {ebitdaMargin != null && (
          <div className="scenario-assumption">
            <span>利润率</span>
            <span>{(ebitdaMargin * 100).toFixed(1)}%</span>
          </div>
        )}
        <div className="scenario-assumption">
          <span>WACC</span>
          <span>{(wacc * 100).toFixed(2)}%</span>
        </div>
      </div>
    </div>
  )
}

function EmptyScenarioCard({ scenarioKey }: { scenarioKey: ScenarioKey }) {
  const meta = SCENARIO_META[scenarioKey]
  return (
    <div className={`scenario-card scenario-card--empty ${meta.colorClass}`}>
      <div className="scenario-card-label">{meta.label}</div>
      <div className="scenario-card-price" style={{ color: 'var(--text-muted)' }}>
        --
      </div>
      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 'var(--sp-2)' }}>
        Adjust assumptions to compute
      </div>
    </div>
  )
}
