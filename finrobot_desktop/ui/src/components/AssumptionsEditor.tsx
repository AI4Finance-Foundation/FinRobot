import { useEffect, useCallback } from 'react'
import { useDebounce } from 'use-debounce'
import { useAppStore } from '../stores/appStore'
import { useDcfCompute, useDcfSensitivity, useWaccCompute } from '../hooks/useCompute'
import type { DCFInputs, ScenarioKey } from '../stores/appStore'

interface SliderDef {
  key: keyof DCFInputs
  label: string
  min: number
  max: number
  step: number
  format: 'pct' | 'dec'
}

const WACC_SLIDERS: SliderDef[] = [
  { key: 'risk_free_rate', label: 'Risk-Free', min: 0, max: 0.15, step: 0.001, format: 'pct' },
  { key: 'beta', label: 'Beta', min: 0, max: 5, step: 0.01, format: 'dec' },
  { key: 'equity_risk_premium', label: 'ERP', min: 0, max: 0.15, step: 0.001, format: 'pct' },
  { key: 'cost_of_debt', label: 'Cost of Debt', min: 0, max: 0.20, step: 0.001, format: 'pct' },
  { key: 'debt_ratio', label: 'Debt Ratio', min: 0, max: 1, step: 0.01, format: 'pct' },
]

const GROWTH_SLIDERS: SliderDef[] = [
  { key: 'ebitda_margin', label: 'EBITDA Margin', min: 0, max: 1, step: 0.005, format: 'pct' },
  { key: 'terminal_growth_rate', label: 'Terminal', min: 0, max: 0.05, step: 0.001, format: 'pct' },
  { key: 'tax_rate', label: 'Tax Rate', min: 0, max: 1, step: 0.01, format: 'pct' },
  { key: 'capex_pct_revenue', label: 'Capex %', min: 0, max: 1, step: 0.005, format: 'pct' },
  { key: 'nwc_pct_revenue', label: 'NWC %', min: -0.20, max: 0.50, step: 0.005, format: 'pct' },
]

const SCENARIO_TABS: { key: ScenarioKey; label: string; color: string }[] = [
  { key: 'bull', label: 'Bull', color: 'var(--positive)' },
  { key: 'base', label: 'Base', color: 'var(--text-primary)' },
  { key: 'bear', label: 'Bear', color: 'var(--negative)' },
]

function fmtValue(val: number, format: 'pct' | 'dec'): string {
  if (format === 'pct') return `${(val * 100).toFixed(1)}%`
  return val.toFixed(2)
}

function buildSensitivityRanges(wacc: number, tg: number) {
  return {
    wacc_range: Array.from({ length: 7 }, (_, i) => Math.max(0, wacc - 0.03 + i * 0.01)),
    tg_range: Array.from({ length: 7 }, (_, i) => Math.max(0, tg - 0.015 + i * 0.005)),
  }
}

export default function AssumptionsEditor() {
  const {
    dcfInputs,
    originalDcfInputs,
    dcfResult,
    activeScenario,
    scenarios,
    setDcfInputs,
    setDcfResult,
    setSensitivityData,
    setPhase,
    setActiveScenario,
    setScenarioInputs,
    setScenarioResult,
    initScenarios,
  } = useAppStore()

  const dcfMut = useDcfCompute()
  const sensMut = useDcfSensitivity()
  const waccMut = useWaccCompute()

  const [debouncedInputs] = useDebounce(dcfInputs, 100)

  // Auto-initialize scenarios when DCF first completes
  useEffect(() => {
    if (dcfResult && originalDcfInputs && !scenarios.base) {
      initScenarios(originalDcfInputs, dcfResult)
    }
  }, [dcfResult, originalDcfInputs, scenarios.base, initScenarios])

  // Recompute on debounced input change
  useEffect(() => {
    if (!debouncedInputs || !dcfResult) return
    if (debouncedInputs === originalDcfInputs && dcfResult.inputs === originalDcfInputs) return

    setPhase('interactive')

    dcfMut.mutate(debouncedInputs, {
      onSuccess: (result) => {
        setDcfResult(result)
        setScenarioResult(activeScenario, result)
        const { wacc_range, tg_range } = buildSensitivityRanges(
          result.wacc,
          debouncedInputs.terminal_growth_rate
        )
        sensMut.mutate(
          { inputs: debouncedInputs, wacc_range, tg_range },
          { onSuccess: (data) => setSensitivityData(data) }
        )
      },
    })

    waccMut.mutate({
      risk_free_rate: debouncedInputs.risk_free_rate,
      beta: debouncedInputs.beta,
      equity_risk_premium: debouncedInputs.equity_risk_premium,
      cost_of_debt: debouncedInputs.cost_of_debt,
      tax_rate: debouncedInputs.tax_rate,
      debt_ratio: debouncedInputs.debt_ratio,
    })
  }, [debouncedInputs])

  const handleSlider = useCallback(
    (key: keyof DCFInputs, value: number) => {
      if (!dcfInputs) return
      const updated = { ...dcfInputs, [key]: value }
      setDcfInputs(updated)
      setScenarioInputs(activeScenario, updated)
    },
    [dcfInputs, setDcfInputs, activeScenario, setScenarioInputs]
  )

  const handleGrowthRate = useCallback(
    (index: number, value: string) => {
      if (!dcfInputs) return
      const rates = [...dcfInputs.revenue_growth_rates]
      rates[index] = parseFloat(value) / 100 || 0
      const updated = { ...dcfInputs, revenue_growth_rates: rates }
      setDcfInputs(updated)
      setScenarioInputs(activeScenario, updated)
    },
    [dcfInputs, setDcfInputs, activeScenario, setScenarioInputs]
  )

  const handleReset = useCallback(() => {
    if (originalDcfInputs) {
      setDcfInputs({ ...originalDcfInputs })
    }
  }, [originalDcfInputs, setDcfInputs])

  const handleScenarioSwitch = useCallback((key: ScenarioKey) => {
    setActiveScenario(key)
  }, [setActiveScenario])

  if (!dcfInputs) return null

  const waccDisplay = waccMut.data?.wacc ?? dcfResult?.wacc
  const hasScenarios = scenarios.base !== null

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">Assumptions</span>
        <button className="btn" onClick={handleReset} style={{ padding: '2px 10px', fontSize: '0.72rem' }}>
          Reset
        </button>
      </div>

      {/* Scenario Tabs */}
      {hasScenarios && (
        <div className="scenario-tabs">
          {SCENARIO_TABS.map((tab) => (
            <button
              key={tab.key}
              className={`scenario-tab${activeScenario === tab.key ? ' active' : ''}`}
              onClick={() => handleScenarioSwitch(tab.key)}
              style={{
                '--tab-color': tab.color,
              } as React.CSSProperties}
            >
              {tab.label}
            </button>
          ))}
        </div>
      )}

      <div className="card-body">
        {/* WACC Components */}
        <div className="section-label">WACC Components</div>
        {WACC_SLIDERS.map((s) => (
          <SliderRow
            key={s.key}
            def={s}
            value={dcfInputs[s.key] as number}
            onChange={(v) => handleSlider(s.key, v)}
            provenance={dcfInputs.assumption_provenance?.[s.key]}
          />
        ))}
        {waccDisplay != null && (
          <div className="assumption-row">
            <span className="assumption-label" style={{ color: 'var(--text-muted)' }}>
              {'\u2192'} WACC
            </span>
            <div style={{ flex: 1 }} />
            <span className="assumption-value" style={{ color: 'var(--accent)' }}>
              {(waccDisplay * 100).toFixed(2)}%
            </span>
          </div>
        )}

        {/* Growth & Margins */}
        <div className="section-label" style={{ marginTop: 'var(--sp-4)' }}>Growth & Margins</div>
        {GROWTH_SLIDERS.map((s) => (
          <SliderRow
            key={s.key}
            def={s}
            value={dcfInputs[s.key] as number}
            onChange={(v) => handleSlider(s.key, v)}
            provenance={dcfInputs.assumption_provenance?.[s.key]}
          />
        ))}

        {/* Revenue Growth Rates */}
        <div className="section-label" style={{ marginTop: 'var(--sp-4)' }}>
          Revenue Growth (per year)
        </div>
        {dcfInputs.assumption_provenance?.['revenue_growth_rates'] && (
          <span className="provenance-hint" title={dcfInputs.assumption_provenance['revenue_growth_rates']}>
            AI: {dcfInputs.assumption_provenance['revenue_growth_rates']}
          </span>
        )}
        <div style={{ display: 'flex', gap: 'var(--sp-2)', flexWrap: 'wrap' }}>
          {dcfInputs.revenue_growth_rates.map((rate, i) => (
            <div key={i} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
              <label style={{
                fontSize: '0.65rem',
                color: 'var(--text-muted)',
                marginBottom: '2px',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}>
                Y{i + 1}
              </label>
              <input
                type="text"
                className="ticker-input"
                style={{ width: '52px', textAlign: 'center', fontSize: '0.75rem' }}
                value={`${(rate * 100).toFixed(1)}%`}
                onChange={(e) => handleGrowthRate(i, e.target.value.replace('%', ''))}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function SliderRow({
  def,
  value,
  onChange,
  provenance,
}: {
  def: SliderDef
  value: number
  onChange: (v: number) => void
  provenance?: string
}) {
  return (
    <div>
      <div className="assumption-row">
        <span className="assumption-label">{def.label}</span>
        <input
          type="range"
          className="assumption-slider"
          min={def.min}
          max={def.max}
          step={def.step}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
        />
        <span className="assumption-value">
          {fmtValue(value, def.format)}
        </span>
      </div>
      {provenance && (
        <span className="provenance-hint" title={provenance}>
          AI: {provenance}
        </span>
      )}
    </div>
  )
}
