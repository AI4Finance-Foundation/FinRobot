/**
 * PlaygroundPage — real-time DCF "what-if" sandbox.
 *
 * Routes:
 *   /playground          → prompts for ticker input
 *   /playground/:ticker  → full playground with sliders
 *
 * All numbers come from real backend compute endpoints:
 *   POST /api/compute/dcf               → implied price, EV, equity value
 *   POST /api/compute/dcf-sensitivity   → WACC × TG price grid
 *   POST /api/compute/monte-carlo       → distribution histogram + percentiles
 *   GET  /api/data/{ticker}/price       → current market price
 *   GET  /api/data/{ticker}/financials  → seeded defaults for margin/growth
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { BASE_URL } from '../api/client'
import type { DCFInputs, DCFResult, SensitivityResult, MonteCarloResult } from '../stores/appStore'
import MonteCarloChart from '../components/charts/MonteCarloChart'
import { TermTip } from '../components/TermTip'

// ── Constants ─────────────────────────────────────────────────────────────────

// Simplified slider state for the playground (exposed controls only).
// All values are seeded from the /api/compute/dcf-seed response on mount —
// the static fallback below only applies before that fetch completes.
interface SliderState {
  wacc: number           // 0.07 – 0.15
  terminalGrowth: number // 0.01 – 0.05
  ebitdaMargin: number    // 0.02 – 0.70 (passes through directly to DCF inputs)
  revenueGrowth: number  // 0.05 – 0.50 (5Y CAGR applied uniformly)
}

// Pre-seed placeholder: the first render flashes through this before the
// /dcf-seed response lands. Values are intentionally generic — the seed
// fetch overrides them within a few hundred ms.
const DEFAULT_SLIDERS: SliderState = {
  wacc: 0.10,
  terminalGrowth: 0.025,
  ebitdaMargin: 0.30,
  revenueGrowth: 0.10,
}

// Scenario offsets
const BULL_DELTA = { wacc: -0.015, tg: +0.01, margin: +0.03, growth: +0.08 }
const BEAR_DELTA = { wacc: +0.015, tg: -0.01, margin: -0.05, growth: -0.10 }

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtPct(v: number, dp = 1) {
  return `${(v * 100).toFixed(dp)}%`
}

function fmtPrice(v: number | null | undefined) {
  if (v == null) return '—'
  return `$${v.toFixed(2)}`
}

function fmtLargeNum(v: number | null | undefined) {
  if (v == null) return '—'
  if (Math.abs(v) >= 1e12) return `$${(v / 1e12).toFixed(2)}T`
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`
  if (Math.abs(v) >= 1e6) return `$${(v / 1e6).toFixed(2)}M`
  return `$${v.toFixed(0)}`
}

function clamp(val: number, min: number, max: number) {
  return Math.max(min, Math.min(max, val))
}

/** Build DCFInputs by overlaying slider state onto the baseline DCFInputs
 * returned by /api/compute/dcf-seed.
 *
 * The baseline carries ticker-specific values for capex / D&A / NWC / tax /
 * beta / cost_of_debt / debt_ratio (all derived from filings or Damodaran
 * industry medians). Sliders only override the four user-facing axes:
 *
 *   WACC ←  back-solved through risk_free_rate so the aggregate matches the slider
 *   terminal_growth_rate
 *   ebitda_margin
 *   revenue_growth_rates (5-year flat at slider value)
 */
function buildDcfInputs(sliders: SliderState, baseline: DCFInputs): DCFInputs {
  // Solve for risk_free_rate that, given baseline's beta / ERP / debt / tax,
  // produces the slider's aggregate WACC:
  //   cost_of_equity = rfr + beta * erp
  //   WACC = ke*(1-d) + kd*(1-t)*d
  //   rfr  = (wacc - kd*(1-t)*d) / (1-d) - beta*erp
  const kd_after_tax = baseline.cost_of_debt * (1 - baseline.tax_rate) * baseline.debt_ratio
  const rfr = (sliders.wacc - kd_after_tax) / (1 - baseline.debt_ratio) - baseline.beta * baseline.equity_risk_premium

  return {
    ...baseline,
    revenue_growth_rates: Array.from({ length: 5 }, () => sliders.revenueGrowth),
    ebitda_margin: clamp(sliders.ebitdaMargin, 0.02, 0.70),
    risk_free_rate: Math.max(0.005, rfr),
    terminal_growth_rate: sliders.terminalGrowth,
  }
}

/** Build sensitivity ranges: 5 values centered on current wacc/tg */
function buildRanges(wacc: number, tg: number) {
  const wacc_range = Array.from({ length: 5 }, (_, i) => Math.max(0.04, wacc - 0.02 + i * 0.01))
  const tg_range = Array.from({ length: 5 }, (_, i) => Math.max(0.005, tg - 0.01 + i * 0.005))
  return { wacc_range, tg_range }
}

// ── Sub-components ────────────────────────────────────────────────────────────

interface SliderRowProps {
  label: string
  value: number
  min: number
  max: number
  step: number
  displayValue: string
  minLabel: string
  maxLabel: string
  onChange: (v: number) => void
}

function SliderRow({ label, value, min, max, step, displayValue, minLabel, maxLabel, onChange }: SliderRowProps) {
  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 9,
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          color: 'var(--text-muted)',
        }}>
          {label}
        </span>
        <span style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 13,
          fontWeight: 600,
          color: 'var(--accent)',
        }}>
          {displayValue}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ width: '100%' }}
      />
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 3 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-muted)' }}>{minLabel}</span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-muted)' }}>{maxLabel}</span>
      </div>
    </div>
  )
}

// ── Sensitivity table ─────────────────────────────────────────────────────────

interface SensitivityTableProps {
  data: SensitivityResult
  baseWacc: number
  baseTg: number
}

function SensitivityTable({ data, baseWacc, baseTg }: SensitivityTableProps) {
  // Find base cell (closest to current sliders)
  const closestWacc = data.wacc_values.reduce((a, b) =>
    Math.abs(a - baseWacc) <= Math.abs(b - baseWacc) ? a : b
  )
  const closestTg = data.tg_values.reduce((a, b) =>
    Math.abs(a - baseTg) <= Math.abs(b - baseTg) ? a : b
  )

  const allPrices = data.implied_prices.flat().filter((p): p is number => p != null)
  const minP = Math.min(...allPrices)
  const maxP = Math.max(...allPrices)
  const midP = (minP + maxP) / 2

  function cellColor(price: number | null, isBase: boolean): string {
    if (isBase) return 'var(--accent)'
    if (price == null) return 'var(--text-muted)'
    if (price >= midP) return `rgba(16, 185, 129, ${0.3 + 0.7 * (price - midP) / (maxP - midP + 0.001)})`
    return `rgba(239, 68, 68, ${0.3 + 0.7 * (midP - price) / (midP - minP + 0.001)})`
  }

  function textColor(price: number | null, isBase: boolean): string {
    if (isBase) return 'var(--bg-0)'
    if (price == null) return 'var(--text-muted)'
    return price >= midP ? 'var(--positive)' : 'var(--negative)'
  }

  const thStyle: React.CSSProperties = {
    fontFamily: 'var(--font-mono)',
    fontSize: 9,
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    color: 'var(--text-muted)',
    padding: '4px 8px',
    textAlign: 'center',
    fontWeight: 600,
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
        <thead>
          <tr>
            <th style={{ ...thStyle, textAlign: 'left' }}>
              <span style={{ color: 'var(--accent)' }}>
                <TermTip term="WACC">WACC</TermTip>
              </span>
              {' \\ '}
              <span style={{ color: 'var(--text-secondary)' }}>TGR</span>
            </th>
            {data.tg_values.map((tg) => (
              <th key={tg} style={thStyle}>{fmtPct(tg)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.wacc_values.map((wacc, wi) => (
            <tr key={wacc}>
              <td style={{
                ...thStyle,
                textAlign: 'left',
                color: 'var(--text-secondary)',
                borderRight: '1px solid var(--border)',
              }}>
                {fmtPct(wacc)}
              </td>
              {data.tg_values.map((tg, ti) => {
                const price = data.implied_prices[wi]?.[ti] ?? null
                const isBase = wacc === closestWacc && tg === closestTg
                return (
                  <td
                    key={tg}
                    style={{
                      padding: '5px 4px',
                      textAlign: 'center',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 10,
                      fontWeight: isBase ? 700 : 500,
                      background: cellColor(price, isBase),
                      color: textColor(price, isBase),
                      borderRadius: 3,
                    }}
                  >
                    {price != null ? `$${price.toFixed(0)}` : '—'}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Ticker prompt ─────────────────────────────────────────────────────────────

function TickerPrompt() {
  const [value, setValue] = useState('')
  const navigate = useNavigate()

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const upper = value.trim().toUpperCase()
    if (/^[A-Z0-9.\-]{1,12}$/.test(upper)) {
      navigate(`/playground/${upper}`)
    }
  }

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      height: '100%',
      gap: 24,
    }}>
      <div style={{ textAlign: 'center' }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 20, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>
          估值推演
        </div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
          输入股票代码，实时 DCF 情景建模
        </div>
      </div>
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <input
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value.toUpperCase())}
          placeholder="AAPL"
          maxLength={12}
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 16,
            fontWeight: 700,
            background: 'var(--bg-2)',
            border: '1px solid var(--border-hover)',
            borderRadius: 'var(--r-sm)',
            color: 'var(--text-primary)',
            padding: '8px 16px',
            outline: 'none',
            letterSpacing: '0.08em',
            width: 160,
            textTransform: 'uppercase',
          }}
        />
        <button
          type="submit"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            fontWeight: 600,
            background: 'var(--accent-dim)',
            border: '1px solid var(--accent)',
            borderRadius: 'var(--r-sm)',
            color: 'var(--accent)',
            padding: '8px 20px',
            cursor: 'pointer',
            letterSpacing: '0.06em',
          }}
        >
          开始分析
        </button>
      </form>
    </div>
  )
}

// ── Scenario box ──────────────────────────────────────────────────────────────

interface ScenarioBoxProps {
  label: string
  price: number | null
  loading: boolean
  color: string
  bgColor: string
}

function ScenarioBox({ label, price, loading, color, bgColor }: ScenarioBoxProps) {
  return (
    <div style={{
      background: bgColor,
      border: `1px solid ${color}33`,
      borderRadius: 'var(--r-sm)',
      padding: '10px 14px',
      flex: 1,
      minWidth: 80,
    }}>
      <div style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 9,
        textTransform: 'uppercase',
        letterSpacing: '0.1em',
        color,
        marginBottom: 4,
      }}>
        {label}
      </div>
      <div style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 16,
        fontWeight: 700,
        color: loading ? 'var(--text-muted)' : color,
      }}>
        {loading ? '...' : fmtPrice(price)}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function PlaygroundPage() {
  const { ticker } = useParams<{ ticker?: string }>()
  const navigate = useNavigate()

  // ── Slider state ──────────────────────────────────────────────────────────
  const [sliders, setSliders] = useState<SliderState>(DEFAULT_SLIDERS)

  // ── Baseline DCFInputs from /api/compute/dcf-seed ─────────────────────────
  // Every per-ticker assumption (capex / D&A / NWC / beta / tax / debt_ratio)
  // lands here from the backend. The slider state above only overrides four
  // user-facing axes via buildDcfInputs.
  const [seed, setSeed] = useState<DCFInputs | null>(null)

  const [currentPrice, setCurrentPrice] = useState<number | null>(null)
  const [priceLoading, setPriceLoading] = useState(false)
  const [seedLoading, setSeedLoading] = useState(false)
  const [initError, setInitError] = useState<string | null>(null)

  // ── Compute results ───────────────────────────────────────────────────────
  const [dcfResult, setDcfResult] = useState<DCFResult | null>(null)
  const [dcfLoading, setDcfLoading] = useState(false)
  const [dcfError, setDcfError] = useState<string | null>(null)

  const [sensResult, setSensResult] = useState<SensitivityResult | null>(null)
  const [sensLoading, setSensLoading] = useState(false)

  const [mcResult, setMcResult] = useState<MonteCarloResult | null>(null)
  const [mcLoading, setMcLoading] = useState(false)

  // Scenario results
  const [bullResult, setBullResult] = useState<DCFResult | null>(null)
  const [bearResult, setBearResult] = useState<DCFResult | null>(null)
  const [scenarioLoading, setScenarioLoading] = useState(false)

  // Reverse DCF — what growth / WACC is the current market price implying?
  const [reverseGrowth, setReverseGrowth] = useState<number | null>(null)
  const [reverseWacc, setReverseWacc] = useState<number | null>(null)
  const [reverseLoading, setReverseLoading] = useState(false)
  const [reverseMessage, setReverseMessage] = useState<string | null>(null)

  // ── Ticker input state (inline ticker change) ─────────────────────────────
  const [tickerInput, setTickerInput] = useState('')

  // ── AbortController refs ──────────────────────────────────────────────────
  const dcfAbortRef = useRef<AbortController | null>(null)
  const heavyAbortRef = useRef<AbortController | null>(null)

  // ── Debounce timers ───────────────────────────────────────────────────────
  const dcfTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const heavyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // ── Fetch price + financials on ticker mount ──────────────────────────────
  useEffect(() => {
    if (!ticker) return

    setInitError(null)
    setDcfResult(null)
    setSensResult(null)
    setMcResult(null)
    setBullResult(null)
    setBearResult(null)
    setSliders(DEFAULT_SLIDERS)

    const abortCtrl = new AbortController()
    const { signal } = abortCtrl

    async function fetchInit() {
      try {
        setPriceLoading(true)
        setSeedLoading(true)

        // Single round-trip: backend pulls financials + historical + runs
        // seed_dcf_inputs + calculate_dcf + reverse DCF. Replaces the legacy
        // path (removed in Phase D1) that fetched /api/data/.../financials
        // separately and used a hardcoded per-component table for capex /
        // NWC / beta / tax / debt ratio.
        const seedRes = await fetch(`${BASE_URL}/api/compute/dcf-seed`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticker, include_reverse: true }),
          signal,
        })

        if (!seedRes.ok) {
          setInitError(`Could not seed DCF for ${ticker} (HTTP ${seedRes.status})`)
          setPriceLoading(false)
          setSeedLoading(false)
          return
        }

        const seedData = await seedRes.json() as {
          inputs: DCFInputs
          result: DCFResult
          current_price: number | null
          reverse_growth: { implied_growth: number | null; message: string | null } | null
          reverse_wacc: { implied_wacc: number | null; message: string | null } | null
        }

        setSeed(seedData.inputs)
        setDcfResult(seedData.result)
        if (seedData.current_price != null) {
          setCurrentPrice(seedData.current_price)
        }
        setPriceLoading(false)

        // Hydrate sliders from the seeded baseline so what the user sees
        // matches what the backend just computed.
        const growth = seedData.inputs.revenue_growth_rates[0] ?? DEFAULT_SLIDERS.revenueGrowth
        setSliders({
          wacc: seedData.result.wacc,
          terminalGrowth: seedData.inputs.terminal_growth_rate,
          ebitdaMargin: clamp(seedData.inputs.ebitda_margin, 0.02, 0.70),
          revenueGrowth: growth,
        })

        // Reverse DCF — pre-populate "market is pricing in X%" panel.
        setReverseGrowth(seedData.reverse_growth?.implied_growth ?? null)
        setReverseWacc(seedData.reverse_wacc?.implied_wacc ?? null)
        setReverseMessage(seedData.reverse_growth?.message ?? seedData.reverse_wacc?.message ?? null)
        setSeedLoading(false)
      } catch (err) {
        if ((err as Error).name !== 'AbortError') {
          setInitError(`Init failed: ${(err as Error).message}`)
        }
        setPriceLoading(false)
        setSeedLoading(false)
      }
    }

    fetchInit()
    return () => abortCtrl.abort()
  }, [ticker])

  // ── Fire DCF on slider change (debounced 300ms) ───────────────────────────
  const fireDcf = useCallback((sl: SliderState, sd: typeof seed) => {
    if (!sd) return

    // Cancel previous
    dcfAbortRef.current?.abort()
    dcfAbortRef.current = new AbortController()
    const { signal } = dcfAbortRef.current

    const inputs = buildDcfInputs(sl, sd)
    setDcfLoading(true)
    setDcfError(null)

    fetch(`${BASE_URL}/api/compute/dcf`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(inputs),
      signal,
    })
      .then((res) => {
        if (!res.ok) throw new Error(`DCF ${res.status}`)
        return res.json() as Promise<DCFResult>
      })
      .then((data) => {
        setDcfResult(data)
        setDcfLoading(false)
      })
      .catch((err) => {
        if (err.name !== 'AbortError') {
          setDcfError(err.message)
          setDcfLoading(false)
        }
      })
  }, [])

  // ── Fire heavy calls (sensitivity + MC + scenarios) on slider change (500ms) ─
  const fireHeavy = useCallback((sl: SliderState, sd: typeof seed, cp: number | null) => {
    if (!sd) return

    heavyAbortRef.current?.abort()
    heavyAbortRef.current = new AbortController()
    const { signal } = heavyAbortRef.current

    const inputs = buildDcfInputs(sl, sd)
    const { wacc_range, tg_range } = buildRanges(sl.wacc, sl.terminalGrowth)

    // Sensitivity
    setSensLoading(true)
    fetch(`${BASE_URL}/api/compute/dcf-sensitivity`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ inputs, wacc_range, tg_range }),
      signal,
    })
      .then((res) => {
        if (!res.ok) throw new Error(`Sensitivity ${res.status}`)
        return res.json() as Promise<SensitivityResult>
      })
      .then((data) => { setSensResult(data); setSensLoading(false) })
      .catch((err) => { if (err.name !== 'AbortError') setSensLoading(false) })

    // Monte Carlo
    setMcLoading(true)
    fetch(`${BASE_URL}/api/compute/monte-carlo`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        inputs,
        current_price: cp ?? 100,
        n_simulations: 5000,
        n_bins: 40,
      }),
      signal,
    })
      .then((res) => {
        if (!res.ok) throw new Error(`MC ${res.status}`)
        return res.json() as Promise<MonteCarloResult>
      })
      .then((data) => { setMcResult(data); setMcLoading(false) })
      .catch((err) => { if (err.name !== 'AbortError') setMcLoading(false) })

    // Scenario DCFs (bull + bear)
    setScenarioLoading(true)

    function buildScenarioInputs(sl: SliderState, delta: typeof BULL_DELTA, sd: NonNullable<typeof seed>): DCFInputs {
      const adjusted: SliderState = {
        wacc: clamp(sl.wacc + delta.wacc, 0.04, 0.20),
        terminalGrowth: clamp(sl.terminalGrowth + delta.tg, 0.005, 0.08),
        ebitdaMargin: clamp(sl.ebitdaMargin + delta.margin, 0.02, 0.70),
        revenueGrowth: clamp(sl.revenueGrowth + delta.growth, 0.01, 0.80),
      }
      return buildDcfInputs(adjusted, sd)
    }

    const bullInputs = buildScenarioInputs(sl, BULL_DELTA, sd)
    const bearInputs = buildScenarioInputs(sl, BEAR_DELTA, sd)

    Promise.allSettled([
      fetch(`${BASE_URL}/api/compute/dcf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(bullInputs),
        signal,
      }).then((r) => r.ok ? r.json() as Promise<DCFResult> : Promise.reject(r.status)),
      fetch(`${BASE_URL}/api/compute/dcf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(bearInputs),
        signal,
      }).then((r) => r.ok ? r.json() as Promise<DCFResult> : Promise.reject(r.status)),
    ]).then(([bullRes, bearRes]) => {
      if (bullRes.status === 'fulfilled') setBullResult(bullRes.value)
      if (bearRes.status === 'fulfilled') setBearResult(bearRes.value)
      setScenarioLoading(false)
    }).catch(() => setScenarioLoading(false))

    // Reverse DCF — only runs when we have a real market price to invert.
    // Two calls in parallel: solve for implied growth, solve for implied WACC.
    if (cp != null) {
      setReverseLoading(true)
      setReverseMessage(null)
      Promise.allSettled([
        fetch(`${BASE_URL}/api/compute/dcf-reverse`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ inputs, target_price: cp, solve_for: 'growth' }),
          signal,
        }).then((r) => r.ok ? r.json() : Promise.reject(r.status)),
        fetch(`${BASE_URL}/api/compute/dcf-reverse`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ inputs, target_price: cp, solve_for: 'wacc' }),
          signal,
        }).then((r) => r.ok ? r.json() : Promise.reject(r.status)),
      ]).then(([gRes, wRes]) => {
        if (gRes.status === 'fulfilled') {
          setReverseGrowth(gRes.value.implied_growth)
          if (gRes.value.message) setReverseMessage(gRes.value.message)
        } else {
          setReverseGrowth(null)
        }
        if (wRes.status === 'fulfilled') {
          setReverseWacc(wRes.value.implied_wacc)
        } else {
          setReverseWacc(null)
        }
        setReverseLoading(false)
      }).catch(() => setReverseLoading(false))
    } else {
      setReverseGrowth(null)
      setReverseWacc(null)
      setReverseMessage(null)
    }
  }, [])

  // ── Debounced slider effect ───────────────────────────────────────────────
  useEffect(() => {
    if (!seed) return

    // Fast call: DCF 300ms
    if (dcfTimerRef.current) clearTimeout(dcfTimerRef.current)
    dcfTimerRef.current = setTimeout(() => fireDcf(sliders, seed), 300)

    // Heavy calls: 500ms
    if (heavyTimerRef.current) clearTimeout(heavyTimerRef.current)
    heavyTimerRef.current = setTimeout(() => fireHeavy(sliders, seed, currentPrice), 500)

    return () => {
      if (dcfTimerRef.current) clearTimeout(dcfTimerRef.current)
      if (heavyTimerRef.current) clearTimeout(heavyTimerRef.current)
    }
  }, [sliders, seed, currentPrice, fireDcf, fireHeavy])

  // ── No ticker: show prompt ────────────────────────────────────────────────
  if (!ticker) return <TickerPrompt />

  // ── Layout ────────────────────────────────────────────────────────────────

  const isLoading = seedLoading || priceLoading

  // Upside calculation
  const upside = dcfResult && currentPrice
    ? (dcfResult.implied_price - currentPrice) / currentPrice
    : null

  const upsideColor = upside == null
    ? 'var(--text-muted)'
    : upside >= 0 ? 'var(--positive)' : 'var(--negative)'

  const cardStyle: React.CSSProperties = {
    background: 'var(--bg-2)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--r-sm)',
    overflow: 'hidden',
  }

  const cardHeaderStyle: React.CSSProperties = {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '10px 16px',
    borderBottom: '1px solid var(--border)',
  }

  const cardTitleStyle: React.CSSProperties = {
    fontFamily: 'var(--font-mono)',
    fontSize: 9,
    textTransform: 'uppercase',
    letterSpacing: '0.1em',
    color: 'var(--text-muted)',
    fontWeight: 600,
  }

  const cardBodyStyle: React.CSSProperties = {
    padding: '16px',
  }

  const labelStyle: React.CSSProperties = {
    fontFamily: 'var(--font-mono)',
    fontSize: 9,
    textTransform: 'uppercase',
    letterSpacing: '0.1em',
    color: 'var(--text-muted)',
  }

  const metaRowStyle: React.CSSProperties = {
    display: 'flex',
    gap: 24,
    marginBottom: 8,
  }

  const metaItemStyle: React.CSSProperties = {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
  }

  const metaValueStyle: React.CSSProperties = {
    fontFamily: 'var(--font-mono)',
    fontSize: 12,
    fontWeight: 500,
    color: 'var(--text-secondary)',
  }

  return (
    <div style={{
      height: '100%',
      overflowY: 'auto',
      padding: '16px 20px 24px',
      display: 'flex',
      flexDirection: 'column',
      gap: 16,
    }}>
      {/* ── Header ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 16,
            fontWeight: 700,
            color: 'var(--text-primary)',
            letterSpacing: '-0.01em',
          }}>
            估值推演
          </div>
          <div style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-muted)',
            marginTop: 2,
          }}>
            {ticker} · 实时 DCF 情景建模
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {/* Inline ticker change */}
          <form
            onSubmit={(e) => {
              e.preventDefault()
              const upper = tickerInput.trim().toUpperCase()
              if (/^[A-Z0-9.\-]{1,12}$/.test(upper)) {
                navigate(`/playground/${upper}`)
                setTickerInput('')
              }
            }}
            style={{ display: 'flex', gap: 4 }}
          >
            <input
              value={tickerInput}
              onChange={(e) => setTickerInput(e.target.value.toUpperCase())}
              placeholder={ticker}
              maxLength={12}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                fontWeight: 700,
                background: 'var(--bg-3)',
                border: '1px solid var(--border-hover)',
                borderRadius: 'var(--r-sm)',
                color: 'var(--text-primary)',
                padding: '4px 10px',
                outline: 'none',
                letterSpacing: '0.06em',
                width: 100,
                textTransform: 'uppercase',
              }}
            />
            <button
              type="submit"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                background: 'transparent',
                border: '1px solid var(--border-hover)',
                borderRadius: 'var(--r-sm)',
                color: 'var(--text-muted)',
                padding: '4px 10px',
                cursor: 'pointer',
              }}
            >
              GO
            </button>
          </form>
          <button
            onClick={() => setSliders(DEFAULT_SLIDERS)}
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              background: 'transparent',
              border: '1px solid var(--border-hover)',
              borderRadius: 'var(--r-sm)',
              color: 'var(--text-muted)',
              padding: '4px 12px',
              cursor: 'pointer',
              letterSpacing: '0.04em',
            }}
          >
            重置
          </button>
        </div>
      </div>

      {/* ── Error / loading banner ── */}
      {initError && (
        <div style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--negative)',
          background: 'var(--negative-bg)',
          border: '1px solid var(--negative)',
          borderRadius: 'var(--r-sm)',
          padding: '6px 12px',
        }}>
          ⚠ {initError}
        </div>
      )}

      {isLoading && !seed && (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
          Loading financials for {ticker}...
        </div>
      )}

      {/* ── Main 2-column grid ── */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 1fr',
        gap: 16,
      }}>
        {/* ── Left: Sliders ── */}
        <div style={cardStyle}>
          <div style={cardHeaderStyle}>
            <span style={cardTitleStyle}>Assumptions</span>
            {dcfLoading && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--accent)', letterSpacing: '0.06em' }}>
                COMPUTING...
              </span>
            )}
          </div>
          <div style={cardBodyStyle}>
            <SliderRow
              label="WACC 加权资本成本"
              value={sliders.wacc}
              min={0.07}
              max={0.15}
              step={0.001}
              displayValue={fmtPct(sliders.wacc)}
              minLabel="7%"
              maxLabel="15%"
              onChange={(v) => setSliders((s) => ({ ...s, wacc: v }))}
            />
            <SliderRow
              label="永续增长率"
              value={sliders.terminalGrowth}
              min={0.01}
              max={0.05}
              step={0.001}
              displayValue={fmtPct(sliders.terminalGrowth)}
              minLabel="1%"
              maxLabel="5%"
              onChange={(v) => setSliders((s) => ({ ...s, terminalGrowth: v }))}
            />
            <SliderRow
              label="EBITDA 利润率"
              value={sliders.ebitdaMargin}
              min={0.02}
              max={0.70}
              step={0.005}
              displayValue={fmtPct(sliders.ebitdaMargin)}
              minLabel="2%"
              maxLabel="70%"
              onChange={(v) => setSliders((s) => ({ ...s, ebitdaMargin: v }))}
            />
            <SliderRow
              label="营收增速 (5Y CAGR)"
              value={sliders.revenueGrowth}
              min={0.05}
              max={0.50}
              step={0.005}
              displayValue={fmtPct(sliders.revenueGrowth)}
              minLabel="5%"
              maxLabel="50%"
              onChange={(v) => setSliders((s) => ({ ...s, revenueGrowth: v }))}
            />

            {/* Derived inputs display */}
            {seed && (
              <div style={{
                marginTop: 16,
                paddingTop: 12,
                borderTop: '1px solid var(--border)',
                display: 'flex',
                flexDirection: 'column',
                gap: 4,
              }}>
                <div style={{ ...labelStyle, marginBottom: 6 }}>财报取数</div>
                <div style={metaRowStyle}>
                  <div style={metaItemStyle}>
                    <span style={labelStyle}>基期营收</span>
                    <span style={metaValueStyle}>{fmtLargeNum(seed.revenue_base)}</span>
                  </div>
                  <div style={metaItemStyle}>
                    <span style={labelStyle}>总股本</span>
                    <span style={metaValueStyle}>{(seed.shares_outstanding / 1e6).toFixed(0)}M</span>
                  </div>
                  <div style={metaItemStyle}>
                    <span style={labelStyle}>净债务</span>
                    <span style={metaValueStyle}>{fmtLargeNum(seed.net_debt)}</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ── Right: Results ── */}
        <div style={cardStyle}>
          <div style={cardHeaderStyle}>
            <span style={cardTitleStyle}>结果</span>
            {currentPrice && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>
                当前市价 {fmtPrice(currentPrice)}
              </span>
            )}
          </div>
          <div style={cardBodyStyle}>
            {/* Implied price hero */}
            <div style={{ marginBottom: 20 }}>
              <div style={{ ...labelStyle, marginBottom: 6 }}>
                <TermTip term="DCF">DCF</TermTip> 目标价
              </div>
              <div style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 36,
                fontWeight: 700,
                color: dcfLoading ? 'var(--text-muted)' : 'var(--accent)',
                lineHeight: 1,
                letterSpacing: '-0.02em',
                marginBottom: 6,
              }}>
                {dcfLoading ? '...' : fmtPrice(dcfResult?.implied_price)}
              </div>
              {upside != null && (
                <div style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 13,
                  fontWeight: 600,
                  color: upsideColor,
                }}>
                  {upside >= 0 ? '+' : ''}{fmtPct(upside)} {upside >= 0 ? '上行空间' : '下行空间'}
                </div>
              )}
              {dcfError && (
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--negative)', marginTop: 4 }}>
                  {dcfError}
                </div>
              )}
            </div>

            {/* Reverse DCF — what is the market implying? */}
            {currentPrice != null && (
              <div style={{
                marginBottom: 20,
                padding: '12px 14px',
                background: 'var(--bg-2)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--r-md)',
              }}>
                <div style={{ ...labelStyle, marginBottom: 8, color: 'var(--text-secondary)' }}>
                  市场在赌什么？
                  <span style={{ marginLeft: 6, fontSize: 9, color: 'var(--text-muted)', textTransform: 'none', letterSpacing: 0 }}>
                    现价 {fmtPrice(currentPrice)} 反推
                  </span>
                </div>

                {reverseMessage ? (
                  <div style={{ fontSize: 11, color: 'var(--warning)', lineHeight: 1.5 }}>
                    {reverseMessage}
                  </div>
                ) : (
                  <div style={{ display: 'flex', gap: 18 }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ ...labelStyle, fontSize: 10, marginBottom: 4 }}>
                        隐含 5 年增长
                      </div>
                      <div style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 22,
                        fontWeight: 700,
                        color: reverseLoading ? 'var(--text-muted)'
                          : reverseGrowth == null ? 'var(--text-muted)'
                          : reverseGrowth > 0.20 ? 'var(--warning)'
                          : reverseGrowth < 0 ? 'var(--negative)'
                          : 'var(--accent)',
                        lineHeight: 1,
                      }}>
                        {reverseLoading ? '...' : reverseGrowth == null ? '—' : fmtPct(reverseGrowth)}
                      </div>
                    </div>
                    <div style={{ width: 1, background: 'var(--border)' }} />
                    <div style={{ flex: 1 }}>
                      <div style={{ ...labelStyle, fontSize: 10, marginBottom: 4 }}>
                        隐含折现率 (<TermTip term="WACC">WACC</TermTip>)
                      </div>
                      <div style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 22,
                        fontWeight: 700,
                        color: reverseLoading ? 'var(--text-muted)' : reverseWacc == null ? 'var(--text-muted)' : 'var(--accent)',
                        lineHeight: 1,
                      }}>
                        {reverseLoading ? '...' : reverseWacc == null ? '—' : fmtPct(reverseWacc)}
                      </div>
                    </div>
                  </div>
                )}

                <div style={{
                  marginTop: 10,
                  fontSize: 10,
                  color: 'var(--text-muted)',
                  lineHeight: 1.5,
                }}>
                  按当前模型反推：要让 DCF 算出 {fmtPrice(currentPrice)}，市场假设的增长 / 折现率必须是上面这两个数。看着不靠谱？说明市场和你的模型有分歧——也许是市场错了，也许是你的某个假设需要重审。
                </div>
              </div>
            )}

            {/* EV */}
            {dcfResult && (
              <div style={{ marginBottom: 20, display: 'flex', gap: 24 }}>
                <div style={metaItemStyle}>
                  <span style={labelStyle}>
                    企业价值 (<TermTip term="EV">EV</TermTip>)
                  </span>
                  <span style={{ ...metaValueStyle, fontSize: 13, color: 'var(--text-primary)' }}>
                    {fmtLargeNum(dcfResult.enterprise_value)}
                  </span>
                </div>
                <div style={metaItemStyle}>
                  <span style={labelStyle}>股权价值</span>
                  <span style={{ ...metaValueStyle, fontSize: 13, color: 'var(--text-primary)' }}>
                    {fmtLargeNum(dcfResult.equity_value)}
                  </span>
                </div>
                <div style={metaItemStyle}>
                  <span style={labelStyle}>
                    <TermTip term="WACC">WACC</TermTip>
                  </span>
                  <span style={{ ...metaValueStyle, fontSize: 13, color: 'var(--text-primary)' }}>
                    {fmtPct(dcfResult.wacc)}
                  </span>
                </div>
              </div>
            )}

            {/* Scenario boxes */}
            <div style={{ ...labelStyle, marginBottom: 8 }}>情景对比</div>
            <div style={{ display: 'flex', gap: 8 }}>
              <ScenarioBox
                label="乐观"
                price={bullResult?.implied_price ?? null}
                loading={scenarioLoading}
                color="var(--positive)"
                bgColor="var(--positive-bg)"
              />
              <ScenarioBox
                label="基准"
                price={dcfResult?.implied_price ?? null}
                loading={dcfLoading}
                color="var(--accent)"
                bgColor="var(--accent-dim)"
              />
              <ScenarioBox
                label="悲观"
                price={bearResult?.implied_price ?? null}
                loading={scenarioLoading}
                color="var(--negative)"
                bgColor="var(--negative-bg)"
              />
            </div>
          </div>
        </div>
      </div>

      {/* ── Bottom 2-column: Sensitivity + Monte Carlo ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* ── Sensitivity matrix ── */}
        <div style={cardStyle}>
          <div style={cardHeaderStyle}>
            <span style={cardTitleStyle}>敏感性矩阵</span>
            {sensLoading && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.06em' }}>
                COMPUTING...
              </span>
            )}
          </div>
          <div style={cardBodyStyle}>
            {sensResult ? (
              <>
                <div style={{ ...labelStyle, marginBottom: 8 }}>
                  Implied Price · WACC (rows) × Terminal Growth (cols)
                </div>
                <SensitivityTable
                  data={sensResult}
                  baseWacc={sliders.wacc}
                  baseTg={sliders.terminalGrowth}
                />
              </>
            ) : (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
                {!seed ? 'Waiting for financials...' : sensLoading ? 'Computing sensitivity...' : 'Move a slider to compute.'}
              </div>
            )}
          </div>
        </div>

        {/* ── Monte Carlo ── */}
        <div style={cardStyle}>
          <div style={cardHeaderStyle}>
            <span style={cardTitleStyle}>蒙特卡洛分布</span>
            {mcLoading && (
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--text-muted)', letterSpacing: '0.06em' }}>
                SIMULATING...
              </span>
            )}
          </div>
          <div style={cardBodyStyle}>
            {mcResult ? (
              <>
                <MonteCarloChart result={mcResult} currentPrice={currentPrice} />
                {/* Extra stats row */}
                <div style={{ display: 'flex', gap: 16, marginTop: 8, flexWrap: 'wrap' }}>
                  <div style={metaItemStyle}>
                    <span style={labelStyle}>Median</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-primary)', fontWeight: 600 }}>
                      {fmtPrice(mcResult.percentiles['50'])}
                    </span>
                  </div>
                  <div style={metaItemStyle}>
                    <span style={labelStyle}>5th Pct</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--negative)', fontWeight: 600 }}>
                      {fmtPrice(mcResult.percentiles['5'])}
                    </span>
                  </div>
                  <div style={metaItemStyle}>
                    <span style={labelStyle}>95th Pct</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--positive)', fontWeight: 600 }}>
                      {fmtPrice(mcResult.percentiles['95'])}
                    </span>
                  </div>
                  {currentPrice && (
                    <div style={metaItemStyle}>
                      <span style={labelStyle}>价格分位</span>
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--accent)', fontWeight: 600 }}>
                        {mcResult.current_price_percentile.toFixed(0)}th
                      </span>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
                {!seed ? 'Waiting for financials...' : mcLoading ? 'Running simulations...' : 'Move a slider to simulate.'}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
