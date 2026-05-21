// useComputeQuery — React-Query wrappers around /api/compute/* POST endpoints
// that derive their request body from already-fetched ticker data. The
// composite score / sniper levels / monte carlo sections need the data
// auto-fetched (not user-triggered), so we expose them as queries rather
// than the imperative mutation hooks in useCompute.ts.
//
// Each hook stays disabled until its required inputs are present — preventing
// 422 requests against half-loaded state and removing the need for guard
// rendering in every section.
//
// All three endpoints exist in finagent/routes/compute.py:
//   POST /api/compute/score       → CompositeScore
//   POST /api/compute/sniper      → SniperPoints
//   POST /api/compute/monte-carlo → MonteCarloResult

import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { useTickerPrice, useTickerFinancials, useTickerCatalysts } from './useTickerData'
import { useV5ArtifactTimeline, useArtifactDetail } from './useV5Artifacts'
import type { ArtifactSummaryV5 } from '../types/v5'
import type { MonteCarloResult, DCFInputs } from '../stores/appStore'

// ── Response types (mirror of backend pydantic models) ──────────────────────

export interface CompositeScore {
  total: number
  fundamental: number
  valuation: number
  catalyst: number
  sentiment: number
  signal: 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL'
  breakdown: Record<string, string>
}

export interface SniperPoints {
  ideal_buy: number
  secondary_buy: number
  stop_loss: number
  take_profit: number
  position_size_pct: number
  safety_margin: number
  support_level: number
  resistance_level: number
  risk_reward_ratio: number
}

// ── Helpers ─────────────────────────────────────────────────────────────────

async function postJson<TBody, TResp>(url: string, body: TBody): Promise<TResp> {
  const resp = await fetch(`${BASE_URL}${url}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!resp.ok) {
    const detail = await resp.text().catch(() => '')
    throw new Error(`${resp.status} ${detail.slice(0, 200)}`)
  }
  return (await resp.json()) as TResp
}

// ── useCompositeScore ───────────────────────────────────────────────────────

export function useCompositeScore(ticker: string) {
  const { data: priceData } = useTickerPrice(ticker)
  const { data: financials } = useTickerFinancials(ticker)
  const { data: catalysts } = useTickerCatalysts(ticker)
  const { data: timeline } = useV5ArtifactTimeline(ticker)

  const latestEquity = timeline?.find((a) => a.type === 'equity_research') ?? null
  const currentPrice = priceData?.current_price ?? null
  const targetPrice = latestEquity?.target_price ?? null
  const dcfUpsidePct =
    currentPrice !== null && targetPrice !== null && currentPrice > 0
      ? (targetPrice - currentPrice) / currentPrice
      : null

  const positive = (catalysts ?? []).filter((c) => c.sentiment === 'positive').length
  const negative = (catalysts ?? []).filter((c) => c.sentiment === 'negative').length

  const body = {
    pe_ratio: financials?.market?.pe_ratio ?? null,
    gross_margin: financials?.income?.gross_margin ?? null,
    positive_catalysts: positive,
    negative_catalysts: negative,
    dcf_upside_pct: dcfUpsidePct,
  }

  // Enabled once we have at least *some* fundamental signal — otherwise the
  // backend returns a neutral 50/50/50/50 and the section is just noise.
  const hasSignal =
    body.pe_ratio !== null ||
    body.gross_margin !== null ||
    body.dcf_upside_pct !== null ||
    positive + negative > 0

  return useQuery<CompositeScore, Error>({
    queryKey: ['composite-score', ticker, body],
    queryFn: () => postJson<typeof body, CompositeScore>('/api/compute/score', body),
    enabled: !!ticker && hasSignal,
    staleTime: 15 * 60_000,
    refetchOnMount: false,
  })
}

// ── useSniperPoints ─────────────────────────────────────────────────────────

interface PriceHistoryPoint {
  date?: string
  close?: number
}

interface PriceResponseShape {
  history?: PriceHistoryPoint[]
}

export function useSniperPoints(ticker: string) {
  const { data: priceData } = useTickerPrice(ticker)
  const { data: timeline } = useV5ArtifactTimeline(ticker)

  const latestEquity = timeline?.find((a) => a.type === 'equity_research') ?? null
  const dcfTarget = latestEquity?.target_price ?? null
  const currentPrice = priceData?.current_price ?? null

  // Pull 3-month price history for the support/resistance window. Sniper
  // backend wants positive floats — we filter null/undefined here so the
  // 422 never reaches the user.
  const { data: historyData } = useQuery<PriceResponseShape, Error>({
    queryKey: ['sniper-price-history', ticker],
    queryFn: async () => {
      const resp = await fetch(`${BASE_URL}/api/data/${ticker}/price?period=3mo`)
      if (!resp.ok) throw new Error(`${resp.status}`)
      return (await resp.json()) as PriceResponseShape
    },
    enabled: !!ticker && currentPrice !== null && dcfTarget !== null,
    staleTime: 60 * 60_000,
    refetchOnMount: false,
  })

  const historicalPrices: number[] = (historyData?.history ?? [])
    .map((p) => p.close)
    .filter((v): v is number => typeof v === 'number' && v > 0)

  const body = {
    ticker,
    current_price: currentPrice ?? 0,
    dcf_target: dcfTarget ?? 0,
    historical_prices: historicalPrices,
  }

  return useQuery<SniperPoints, Error>({
    queryKey: ['sniper-points', ticker, currentPrice, dcfTarget, historicalPrices.length],
    queryFn: () => postJson<typeof body, SniperPoints>('/api/compute/sniper', body),
    enabled:
      !!ticker &&
      currentPrice !== null &&
      currentPrice > 0 &&
      dcfTarget !== null &&
      dcfTarget > 0 &&
      historicalPrices.length >= 5,
    staleTime: 30 * 60_000,
    refetchOnMount: false,
  })
}

// ── useMonteCarloAuto ───────────────────────────────────────────────────────

// Walks artifact.outputs.structured looking for a DCFInputs blob. equity_research
// pipelines nest it under financial_modeling.dcf_result.inputs; standalone dcf
// pipelines put it at dcf_result.inputs. Returns null if no DCFInputs found.
function extractDcfInputs(outputs: Record<string, unknown> | undefined): DCFInputs | null {
  if (!outputs) return null
  const structured = outputs.structured as Record<string, unknown> | undefined
  if (!structured) return null

  // Direct paths to try in priority order.
  const candidates: Array<Record<string, unknown> | undefined> = [
    (structured.financial_modeling as Record<string, unknown> | undefined)?.dcf_result as
      | Record<string, unknown>
      | undefined,
    structured.dcf_result as Record<string, unknown> | undefined,
    structured.inputs as Record<string, unknown> | undefined,
  ]
  for (const c of candidates) {
    const inputs = c?.inputs ?? c
    if (
      inputs &&
      typeof inputs === 'object' &&
      'revenue_base' in inputs &&
      'revenue_growth_rates' in inputs &&
      'ebitda_margin' in inputs
    ) {
      return inputs as unknown as DCFInputs
    }
  }
  return null
}

function pickArtifactWithDcf(
  timeline: ArtifactSummaryV5[] | undefined,
): ArtifactSummaryV5 | null {
  if (!timeline) return null
  return (
    timeline.find((a) => a.type === 'dcf') ??
    timeline.find((a) => a.type === 'equity_research') ??
    null
  )
}

export function useMonteCarloAuto(ticker: string) {
  const { data: priceData } = useTickerPrice(ticker)
  const { data: timeline } = useV5ArtifactTimeline(ticker)
  const dcfArtifact = pickArtifactWithDcf(timeline)
  const { data: detail } = useArtifactDetail(dcfArtifact?.id)

  const currentPrice = priceData?.current_price ?? null
  const dcfInputs = extractDcfInputs(detail?.outputs)

  const body = {
    inputs: dcfInputs,
    current_price: currentPrice ?? 0,
    n_simulations: 5_000,
    n_bins: 40,
  }

  return useQuery<MonteCarloResult, Error>({
    queryKey: ['monte-carlo-auto', ticker, dcfArtifact?.id, currentPrice],
    queryFn: () =>
      postJson<typeof body, MonteCarloResult>('/api/compute/monte-carlo', body),
    enabled:
      !!ticker &&
      currentPrice !== null &&
      currentPrice > 0 &&
      dcfInputs !== null,
    staleTime: 60 * 60_000,
    refetchOnMount: false,
    retry: 0, // a failed monte-carlo is usually a math issue (e.g. WACC<=TGR);
    // retrying just delays the error toast — surface immediately.
  })
}
