/**
 * useRunTool — mutation hook for verb-toolbar actions.
 *
 * Each tool button calls this hook with its toolName.
 * Routing logic:
 *   - dcf, lbo, comps → POST /api/compute/{tool}  (deterministic, no LLM)
 *   - catalysts        → POST /api/runs (pipeline_type=research)
 *   - ic-memo          → POST /api/runs (pipeline_type=ic-memo)
 *   - ddm              → POST /api/runs (pipeline_type=ddm)
 *   - earnings         → POST /api/runs (pipeline_type=earnings)
 *   - ask-ai           → no-op here; handled by RightChatPanel
 *
 * On success the tool jumps to the appropriate tab and shows a toast.
 * For DCF/LBO the parsed result is written back to the appStore so the
 * Valuation tab renders immediately. For runs-based tools we poll the run
 * status briefly before invalidating the artifact list.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { useStocksStore, type ToolName } from '../stores/stocksStore'
import { useToastStore } from '../stores/toastStore'
import {
  useAppStore,
  type DCFResult,
  type DcfReverseResult,
  type DcfSeedResponse,
  type LBOResult,
  type CompsResult,
  type EarningsResult,
  type ICMemoResult,
} from '../stores/appStore'
import { useI18n } from '../i18n'

// ── Tool → tab mapping ────────────────────────────────────────────────────────

const TOOL_TAB_MAP: Record<ToolName, import('../stores/stocksStore').StocksTab> = {
  research:   'overview',
  dcf:        'valuation',
  lbo:        'valuation',
  comps:      'comps',
  catalysts:  'news',
  'ic-memo':  'history',
  ddm:        'valuation',
  earnings:   'financials',
  'ask-ai':   'overview',
}

// ── Error helper ─────────────────────────────────────────────────────────────

export class ToolRunError extends Error {
  constructor(
    public readonly tool: ToolName,
    public readonly status: number,
    public readonly body: string,
  ) {
    super(`${tool} failed (HTTP ${status}): ${body}`)
    this.name = 'ToolRunError'
  }
}

// ── Result discriminator ─────────────────────────────────────────────────────

interface RunDetailPayload {
  status: string
  pipeline_type: string
  result?: { text?: string; structured?: Record<string, unknown> } | null
  steps?: Record<string, string> | null
}

type RunResult =
  | {
      kind: 'dcf'
      result: DCFResult
      ticker: string
      reverseGrowth: DcfReverseResult | null
      reverseWacc: DcfReverseResult | null
    }
  | { kind: 'lbo'; result: LBOResult; ticker: string }
  | { kind: 'run'; runId: string; ticker: string; timedOut: boolean; pipelineType: string; detail: RunDetailPayload | null }
  | { kind: 'noop' }

// ── Hook ──────────────────────────────────────────────────────────────────────

interface UseRunToolOptions {
  ticker: string
  onSuccess?: (tool: ToolName) => void
}

export function useRunTool({ ticker, onSuccess }: UseRunToolOptions) {
  const { startTool, finishTool, setActiveTab } = useStocksStore()
  const addToast = useToastStore((s) => s.addToast)
  const queryClient = useQueryClient()
  const setDcfResult = useAppStore((s) => s.setDcfResult)
  const setDcfReverse = useAppStore((s) => s.setDcfReverse)
  const setLboResult = useAppStore((s) => s.setLboResult)
  const setCompsResult = useAppStore((s) => s.setCompsResult)
  const setEarningsResult = useAppStore((s) => s.setEarningsResult)
  const setIcMemoResult = useAppStore((s) => s.setIcMemoResult)
  const { t } = useI18n()

  return useMutation<RunResult, ToolRunError | Error, ToolName>({
    mutationFn: async (toolName: ToolName): Promise<RunResult> => {
      if (toolName === 'ask-ai') return { kind: 'noop' }

      // Capture the ticker at dispatch time. If the user switches tickers
      // mid-flight, the captured value lets us drop stale writes in onSuccess.
      const tickerAtDispatch = ticker
      if (!tickerAtDispatch) {
        throw new Error('Ticker is required to run this tool')
      }

      startTool(toolName)

      try {
        if (toolName === 'dcf') {
          // Single authoritative entry: backend pulls financials, historical,
          // and runs seed_dcf_inputs → calculate_dcf in one shot. Replaces
          // the legacy hardcoded path (removed in Phase D1) where every
          // company shared the same 20% EBITDA / 5% capex assumptions.
          const resp = await fetch(`${BASE_URL}/api/compute/dcf-seed`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              ticker: tickerAtDispatch,
              include_reverse: true,
            }),
          })
          if (!resp.ok) {
            throw new ToolRunError('dcf', resp.status, await resp.text().catch(() => ''))
          }
          const seed = (await resp.json()) as DcfSeedResponse
          return {
            kind: 'dcf',
            result: seed.result,
            ticker: tickerAtDispatch,
            reverseGrowth: seed.reverse_growth,
            reverseWacc: seed.reverse_wacc,
          }
        }

        if (toolName === 'lbo') {
          // Single authoritative entry: backend pulls financials, historical,
          // and runs seed_lbo_inputs → calculate_lbo in one shot. Replaces
          // the legacy hardcoded path where every company shared the same
          // 5% growth / 20% EBITDA / 8× entry assumptions (CLAUDE.md
          // architecture red-line #5; mirrors the DCF dcf-seed contract).
          const resp = await fetch(`${BASE_URL}/api/compute/lbo-seed`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ticker: tickerAtDispatch }),
          })
          if (!resp.ok) {
            throw new ToolRunError('lbo', resp.status, await resp.text().catch(() => ''))
          }
          const seed = (await resp.json()) as { result: LBOResult }
          return { kind: 'lbo', result: seed.result, ticker: tickerAtDispatch }
        }

        if (toolName === 'comps' || toolName === 'ic-memo' || toolName === 'ddm' || toolName === 'earnings') {
          // DDM pre-check: only suitable for bank/financial stocks
          if (toolName === 'ddm') {
            const finCheck = await fetch(`${BASE_URL}/api/data/${tickerAtDispatch}/financials`)
            if (finCheck.ok) {
              const finData = (await finCheck.json()) as Record<string, unknown>
              const market = (finData.market ?? {}) as Record<string, unknown>
              const sector = (market.sector as string) ?? ''
              const industry = (market.industry as string) ?? ''
              const isBank = ['Financial Services', 'Financials'].includes(sector)
                && industry.toLowerCase().includes('bank')
              const isBankIndustry = [
                'Banks—Diversified', 'Banks—Regional', 'Banks - Diversified',
                'Banks - Regional', 'Savings & Cooperative Banks',
              ].includes(industry)
              if (!isBank && !isBankIndustry) {
                throw new Error(
                  `DDM 不适用于 ${tickerAtDispatch}（${sector} / ${industry}）。` +
                  `DDM 是股息折现模型，专为银行和高分红金融股设计。` +
                  `请使用 DCF 或 LBO 进行估值。`
                )
              }
            }
          }

          const pipeline = toolName
          const resp = await fetch(`${BASE_URL}/api/runs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pipeline_type: pipeline, ticker: tickerAtDispatch }),
          })
          if (!resp.ok) {
            throw new ToolRunError(toolName, resp.status, await resp.text().catch(() => ''))
          }
          const { run_id } = (await resp.json()) as { run_id: string }
          // Poll up to ~60s (12 × 5s).
          let completed = false
          for (let i = 0; i < 12; i += 1) {
            await new Promise((r) => setTimeout(r, 5000))
            const statusResp = await fetch(`${BASE_URL}/api/runs/${run_id}`)
            if (!statusResp.ok) continue
            const detail = (await statusResp.json()) as { status?: string }
            if (detail.status === 'completed' || detail.status === 'complete') {
              completed = true
              break
            }
            if (detail.status === 'failed' || detail.status === 'error') {
              throw new ToolRunError(toolName, 500, 'Pipeline failed')
            }
          }
          // Fetch the full result with structured data
          let detail: RunDetailPayload | null = null
          if (completed) {
            const fullResp = await fetch(`${BASE_URL}/api/runs/${run_id}`)
            if (fullResp.ok) {
              detail = (await fullResp.json()) as RunDetailPayload
            }
          }
          return { kind: 'run', runId: run_id, ticker: tickerAtDispatch, timedOut: !completed, pipelineType: pipeline, detail }
        }

        if (toolName === 'catalysts') {
          await queryClient.refetchQueries({ queryKey: ['ticker-catalysts', tickerAtDispatch] })
          return { kind: 'noop' }
        }

        throw new Error(`Unknown tool: ${String(toolName)}`)
      } finally {
        finishTool(toolName)
      }
    },

    onSuccess: (data, toolName) => {
      // Drop stale writes: if the user navigated to a different ticker while
      // the request was in flight, the result no longer matches the page
      // they're looking at — keep the toast as a heads-up but don't mutate
      // the global appStore slots.
      const tickerInResult = data.kind === 'noop' ? null : data.ticker
      const isFresh = tickerInResult === null || tickerInResult === ticker

      if (isFresh) {
        if (data.kind === 'dcf') {
          setDcfResult(data.result, 'standalone')
          setDcfReverse(data.reverseGrowth, data.reverseWacc)
        } else if (data.kind === 'lbo') {
          setLboResult(data.result)
        } else if (data.kind === 'run' && data.detail?.result?.structured) {
          const structured = data.detail.result.structured
          const steps = data.detail.steps ?? {}
          const pt = data.pipelineType

          if (pt === 'comps') {
            const comps = (structured.statistical_bench ?? structured.peer_comps) as CompsResult | undefined
            if (comps) setCompsResult(comps)
          } else if (pt === 'earnings') {
            const earnings = structured.earnings_data as EarningsResult | undefined
            if (earnings) setEarningsResult(earnings)
          } else if (pt === 'ic-memo') {
            const financialAnalysis = structured.financial_analysis as Record<string, unknown> | undefined
            let irr: number | null = null
            if (financialAnalysis?.lbo_result && typeof financialAnalysis.lbo_result === 'object') {
              irr = (financialAnalysis.lbo_result as Record<string, unknown>).irr as number | null
            }
            let verdict = 'INVEST'
            const recText = steps.recommendation ?? ''
            if (recText.includes('[CODE GATE') || recText.toUpperCase().includes('PASS')) {
              verdict = 'PASS'
            } else if (recText.toUpperCase().includes('HOLD')) {
              verdict = 'HOLD'
            }
            const icMemo: ICMemoResult = {
              situation_overview: steps.situation_overview ?? '',
              financial_summary: steps.financial_analysis ?? '',
              investment_thesis: steps.investment_thesis ?? '',
              risk_factors: steps.risk_factors ?? '',
              recommendation: { verdict, irr, rationale: recText },
            }
            setIcMemoResult(icMemo)
          } else if (pt === 'ddm') {
            // DDM results go to valuation — structured may contain dcf-like output
            const dcfCalc = (structured.dcf_calc ?? Object.values(structured)[0]) as DCFResult | undefined
            if (dcfCalc) setDcfResult(dcfCalc, 'standalone')
          }
        }
        const tab = TOOL_TAB_MAP[toolName]
        if (tab) setActiveTab(tab)
      }

      void queryClient.invalidateQueries({
        queryKey: ['ticker-artifacts', tickerInResult ?? ticker],
      })

      if (toolName !== 'ask-ai') {
        // For runs-based pipelines (comps/ic-memo) the polling may have
        // timed out before completion; the run is still going server-side.
        if (data.kind === 'run' && data.timedOut) {
          addToast({
            type: 'info',
            title: t('tool.toast.success', { tool: toolName.toUpperCase() }),
            description: t('tool.error.unknown'),
          })
        } else {
          addToast({
            type: 'success',
            title: t('tool.toast.success', { tool: toolName.toUpperCase() }),
          })
        }
      }

      onSuccess?.(toolName)
    },

    onError: (err, toolName) => {
      finishTool(toolName)
      addToast({
        type: 'error',
        title: t('tool.toast.failure', { tool: toolName.toUpperCase() }),
        description: humanReadableError(err, t),
      })
    },
  })
}

function humanReadableError(
  err: unknown,
  t: (key: string, params?: Record<string, string | number>) => string,
): string {
  if (err instanceof ToolRunError) {
    if (err.status === 503) return t('tool.error.unavailable')
    if (err.status === 422) return t('tool.error.invalid', { tool: err.tool })
    if (err.status === 501) return t('tool.error.unsupported', { tool: err.tool })
    return t('tool.error.generic', { tool: err.tool, status: err.status })
  }
  if (err instanceof Error) {
    if (err.name === 'AbortError') return t('tool.error.cancelled')
    return err.message
  }
  return t('tool.error.unknown')
}
