import { useState, useCallback } from 'react'
import { useAppStore } from '../stores/appStore'
import type { DCFInputs } from '../stores/appStore'
import { useHistoricalData } from '../hooks/useHistoricalData'
import { useRunTool } from '../hooks/useRunTool'
import { useStocksStore } from '../stores/stocksStore'
import { useI18n } from '../i18n'
import { useDcfCompute } from '../hooks/useCompute'
import AssumptionsEditor from '../components/AssumptionsEditor'
import ValuationCard from '../components/ValuationCard'
import ScenarioCompare from '../components/ScenarioCompare'
import MonteCarloSection from '../components/MonteCarloSection'
import LBOSummary from '../components/LBOSummary'
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

// ── ScenarioEditor ────────────────────────────────────────────────────────────
// Inline component — only shown when base DCF inputs are available.
// Lets users override the auto-derived bull/bear adjustments and
// recomputes both scenarios via /api/compute/dcf.

interface AdjustRow {
  label: string
  field: 'growthAdj' | 'marginAdj' | 'waccAdj'
  sign: string
  defaultValue: number
}

const ADJ_ROWS: AdjustRow[] = [
  { label: 'Growth adj.',  field: 'growthAdj',  sign: '±',  defaultValue: 20 },
  { label: 'Margin adj.',  field: 'marginAdj',  sign: '±',  defaultValue: 10 },
  { label: 'WACC adj.',    field: 'waccAdj',    sign: '±',  defaultValue: 1  },
]

/** Derive bull or bear DCFInputs from base using caller-supplied adjustments. */
function applyAdjustments(
  base: DCFInputs,
  direction: 'bull' | 'bear',
  growthAdj: number,
  marginAdj: number,
  waccAdj: number,
): DCFInputs {
  const mult = direction === 'bull' ? 1 : -1
  return {
    ...base,
    revenue_growth_rates: base.revenue_growth_rates.map(
      (r) => Math.max(0, r * (1 + mult * growthAdj / 100)),
    ),
    ebitda_margin: Math.max(0, Math.min(1, base.ebitda_margin * (1 + mult * marginAdj / 100))),
    risk_free_rate: Math.max(0, base.risk_free_rate - mult * waccAdj / 100),
  }
}

interface ScenarioEditorProps {
  baseInputs: DCFInputs
}

function ScenarioEditor({ baseInputs }: ScenarioEditorProps) {
  const [growthAdj, setGrowthAdj] = useState(20)
  const [marginAdj, setMarginAdj] = useState(10)
  const [waccAdj, setWaccAdj]    = useState(1)
  const [computing, setComputing] = useState(false)
  const [error, setError]         = useState<string | null>(null)

  const setScenarioInputs = useAppStore((s) => s.setScenarioInputs)
  const setScenarioResult  = useAppStore((s) => s.setScenarioResult)
  const dcfMutation = useDcfCompute()

  const handleCompute = useCallback(async () => {
    setComputing(true)
    setError(null)
    try {
      const bullInputs = applyAdjustments(baseInputs, 'bull', growthAdj, marginAdj, waccAdj)
      const bearInputs = applyAdjustments(baseInputs, 'bear', growthAdj, marginAdj, waccAdj)

      const [bullResult, bearResult] = await Promise.all([
        dcfMutation.mutateAsync(bullInputs),
        dcfMutation.mutateAsync(bearInputs),
      ])

      setScenarioInputs('bull', bullInputs)
      setScenarioInputs('bear', bearInputs)
      setScenarioResult('bull', bullResult)
      setScenarioResult('bear', bearResult)
    } catch {
      setError('计算情景失败，请确认后端服务已启动')
    } finally {
      setComputing(false)
    }
  }, [baseInputs, growthAdj, marginAdj, waccAdj, dcfMutation, setScenarioInputs, setScenarioResult])

  const setters: Record<AdjustRow['field'], (v: number) => void> = {
    growthAdj: setGrowthAdj,
    marginAdj: setMarginAdj,
    waccAdj:   setWaccAdj,
  }
  const values: Record<AdjustRow['field'], number> = { growthAdj, marginAdj, waccAdj }

  return (
    <div
      style={{
        background: 'var(--elevated)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 6,
        padding: '12px 16px',
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      <div
        style={{
          fontSize: '0.87rem',
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
        }}
      >
        Bull / Bear Adjustments
      </div>

      <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'flex-end' }}>
        {ADJ_ROWS.map((row) => (
          <label
            key={row.field}
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
              fontSize: '0.87rem',
              color: 'var(--text-secondary)',
            }}
          >
            <span>
              {row.sign}{row.label}
            </span>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <input
                type="number"
                value={values[row.field]}
                min={0}
                max={row.field === 'waccAdj' ? 10 : 50}
                step={row.field === 'waccAdj' ? 0.5 : 5}
                disabled={computing}
                onChange={(e) => {
                  const n = parseFloat(e.target.value)
                  if (!isNaN(n) && n >= 0) setters[row.field](n)
                }}
                style={{
                  width: 68,
                  padding: '4px 8px',
                  fontSize: '0.87rem',
                  fontFamily: 'var(--font-mono)',
                  border: '1px solid var(--border)',
                  borderRadius: 4,
                  background: 'var(--surface)',
                  color: 'var(--text-primary)',
                  outline: 'none',
                  textAlign: 'right',
                }}
              />
              <span style={{ fontSize: '0.87rem', color: 'var(--text-muted)' }}>%</span>
            </div>
          </label>
        ))}

        <button
          onClick={() => void handleCompute()}
          disabled={computing}
          style={{
            padding: '6px 14px',
            fontSize: '0.87rem',
            fontWeight: 500,
            border: '1px solid var(--accent)',
            borderRadius: 4,
            background: computing ? 'var(--border)' : 'var(--accent-dim)',
            color: 'var(--accent)',
            cursor: computing ? 'wait' : 'pointer',
            opacity: computing ? 0.6 : 1,
            whiteSpace: 'nowrap',
            alignSelf: 'flex-end',
          }}
        >
          {computing ? 'Computing…' : 'Recompute scenarios'}
        </button>
      </div>

      {error && (
        <div style={{ fontSize: '0.87rem', color: 'var(--negative)' }}>{error}</div>
      )}
    </div>
  )
}

export default function ValuationTab() {
  useHistoricalData() // ensure historical data is loaded for EpsPe

  const dcfResult = useAppStore((s) => s.dcfResult)
  const dcfInputs = useAppStore((s) => s.dcfInputs)
  const dcfSource = useAppStore((s) => s.dcfSource)
  const currentPrice = useAppStore((s) => s.currentPrice)
  const sensitivityData = useAppStore((s) => s.sensitivityData)
  const historicalMetrics = useAppStore((s) => s.historicalMetrics)
  const earningsResult = useAppStore((s) => s.earningsResult)
  const scenarioResults = useAppStore((s) => s.scenarioResults)
  const lboResult = useAppStore((s) => s.lboResult)
  const ticker = useStocksStore((s) => s.currentTicker)
  const { t } = useI18n()
  const { mutate, isPending } = useRunTool({ ticker })

  const showScenarioCompare =
    [scenarioResults.base, scenarioResults.bull, scenarioResults.bear].filter(Boolean).length >= 2

  return (
    <div className="tab-content valuation-tab">
      {/* DCF Workspace */}
      <section className="chart-section">
        <h3 className="section-title">{t('valuation.dcf.title')}</h3>
        {dcfResult && (
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.87rem', margin: '0 0 12px 0' }}>
            {dcfSource === 'research'
              ? t('valuation.source.research')
              : t('valuation.source.standalone')}
          </p>
        )}
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
          <div
            className="empty-state-card"
            style={{ display: 'flex', flexDirection: 'column', gap: 12, alignItems: 'center' }}
          >
            <p style={{ color: 'var(--text-secondary)' }}>{t('valuation.dcf.empty')}</p>
            <button
              onClick={() => mutate('dcf')}
              disabled={isPending || !ticker}
              style={{
                padding: '6px 16px',
                fontSize: '0.85rem',
                background: isPending ? 'var(--border)' : 'var(--accent-dim)',
                color: 'var(--accent)',
                border: '1px solid var(--accent)',
                borderRadius: 4,
                cursor: isPending ? 'wait' : 'pointer',
                opacity: isPending ? 0.6 : 1,
              }}
            >
              {isPending ? t('common.loading') : t('valuation.dcf.cta')}
            </button>
          </div>
        )}
      </section>

      {/* Comprehensive Valuation */}
      <section className="chart-section">
        <h3 className="section-title">{t('valuation.comp.title')}</h3>
        {dcfResult && sensitivityData && (
          <FootballField
            data={dcfSensitivityToFootballData(dcfResult, sensitivityData)}
            title="Valuation Range"
          />
        )}
        {/* Bull/Bear adjustment editor — only when base DCF inputs exist */}
        {dcfResult && dcfInputs && (
          <ScenarioEditor baseInputs={dcfInputs} />
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

      {/* LBO Analysis */}
      {lboResult && (
        <section className="chart-section">
          <h3 className="section-title">{t('valuation.lbo.title')}</h3>
          <LBOSummary result={lboResult} />
        </section>
      )}
    </div>
  )
}
