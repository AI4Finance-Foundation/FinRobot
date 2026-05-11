import { useAppStore } from '../stores/appStore'
import { useHistoricalData } from '../hooks/useHistoricalData'
import AssumptionsEditor from '../components/AssumptionsEditor'
import ValuationCard from '../components/ValuationCard'
import ScenarioCompare from '../components/ScenarioCompare'
import MonteCarloSection from '../components/MonteCarloSection'
import {
  SensitivityHeatmap,
  WaterfallChart,
  FootballField,
  EpsPeChart,
  EpsSurpriseChart,
} from '../components/charts'
import {
  sensitivityGridToHeatmapRows,
  dcfResultToWaterfallData,
  dcfSensitivityToFootballData,
  historicalToEpsPeData,
  earningsToSurpriseChartData,
} from '../utils/chartAdapters'

export default function ValuationTab() {
  useHistoricalData() // ensure historical data is loaded for EpsPe

  const dcfResult = useAppStore((s) => s.dcfResult)
  const currentPrice = useAppStore((s) => s.currentPrice)
  const sensitivityData = useAppStore((s) => s.sensitivityData)
  const historicalMetrics = useAppStore((s) => s.historicalMetrics)
  const earningsResult = useAppStore((s) => s.earningsResult)
  const scenarioResults = useAppStore((s) => s.scenarioResults)

  const showScenarioCompare =
    [scenarioResults.base, scenarioResults.bull, scenarioResults.bear].filter(Boolean).length >= 2

  return (
    <div className="tab-content valuation-tab">
      {/* DCF Workspace */}
      <section className="chart-section">
        <h3 className="section-title">DCF Workspace</h3>
        {dcfResult ? (
          <>
            <div className="chart-grid-2col">
              <AssumptionsEditor />
              <ValuationCard dcfResult={dcfResult} currentPrice={currentPrice} />
            </div>
            {sensitivityData && (
              <SensitivityHeatmap
                data={sensitivityGridToHeatmapRows(sensitivityData)}
                title="Sensitivity (WACC × TGR)"
              />
            )}
            <WaterfallChart data={dcfResultToWaterfallData(dcfResult)} title="DCF Bridge" />
          </>
        ) : (
          <div className="empty-state-card">
            <p>Run DCF Analysis to view valuation workspace</p>
          </div>
        )}
      </section>

      {/* Comprehensive Valuation */}
      <section className="chart-section">
        <h3 className="section-title">Comprehensive Valuation</h3>
        {dcfResult && sensitivityData && (
          <FootballField
            data={dcfSensitivityToFootballData(dcfResult, sensitivityData)}
            title="Valuation Range"
          />
        )}
        {showScenarioCompare && <ScenarioCompare />}
        <MonteCarloSection />

        {/* EPS / PE historical — from /historical endpoint */}
        {historicalMetrics && historicalMetrics.price_data_available && (
          <EpsPeChart
            data={historicalToEpsPeData(historicalMetrics)}
            title="Historical EPS & P/E"
          />
        )}

        {/* EPS Surprise — from earnings pipeline */}
        {earningsResult?.surprises && earningsResult.surprises.length > 0 && (
          <EpsSurpriseChart
            data={earningsToSurpriseChartData(earningsResult.surprises)}
            title="EPS Surprises"
          />
        )}
      </section>
    </div>
  )
}
