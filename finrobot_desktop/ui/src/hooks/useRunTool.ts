/**
 * useRunTool — mutation hook for verb-toolbar actions.
 *
 * Each tool button calls this hook with its toolName.
 * Routing logic:
 *   - dcf, lbo, comps → POST /api/compute/{tool}  (deterministic, no LLM)
 *   - catalysts        → POST /api/runs (pipeline_type=research)
 *   - ic-memo          → POST /api/runs (pipeline_type=ic-memo)
 *   - ask-ai           → no-op here; handled by RightChatPanel
 *
 * On success the tool jumps to the appropriate tab and shows a toast.
 */

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { useStocksStore, type ToolName } from '../stores/stocksStore'
import { useToastStore } from '../stores/toastStore'

// ── Tool → tab mapping ────────────────────────────────────────────────────────

const TOOL_TAB_MAP: Record<ToolName, import('../stores/stocksStore').StocksTab> = {
  dcf:        'valuation',
  lbo:        'valuation',
  comps:      'peers',
  catalysts:  'news',
  'ic-memo':  'history',
  'ask-ai':   'valuation', // unused — ask-ai short-circuits before fetch
}

// ── Default assumptions for direct compute endpoints ─────────────────────────

const DEFAULT_COMPUTE_BODY: Record<string, unknown> = {
  // DCF — will be merged with ticker-derived data server-side
  risk_free_rate: 0.043,
  beta: 1.1,
  equity_risk_premium: 0.055,
  cost_of_debt: 0.05,
  tax_rate: 0.21,
  debt_ratio: 0.3,
  terminal_growth_rate: 0.025,
  revenue_growth_rates: [0.10, 0.10, 0.08, 0.07, 0.06],
  ebitda_margin: 0.20,
  capex_pct_revenue: 0.05,
  nwc_pct_revenue: 0.02,
  shares_outstanding: 1,
  net_debt: 0,
  revenue_base: 1,
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

function humanReadable(err: unknown): string {
  if (err instanceof ToolRunError) {
    if (err.status === 503) return 'Backend unavailable — is the server running?'
    if (err.status === 422) return `Invalid inputs for ${err.tool}`
    if (err.status === 501) return `${err.tool} is not yet supported`
    return `${err.tool} failed (${err.status})`
  }
  if (err instanceof Error) {
    if (err.name === 'AbortError') return 'Request cancelled'
    return err.message
  }
  return 'Unknown error'
}

// ── Hook ──────────────────────────────────────────────────────────────────────

interface UseRunToolOptions {
  /** Ticker to run the tool on */
  ticker: string
  /** Called when the tool run succeeds */
  onSuccess?: (tool: ToolName) => void
}

export function useRunTool({ ticker, onSuccess }: UseRunToolOptions) {
  const { startTool, finishTool, setActiveTab } = useStocksStore()
  const addToast = useToastStore((s) => s.addToast)
  const queryClient = useQueryClient()

  return useMutation<void, ToolRunError | Error, ToolName>({
    mutationFn: async (toolName: ToolName) => {
      if (toolName === 'ask-ai') {
        // ask-ai is handled entirely by RightChatPanel — just a no-op here
        return
      }

      startTool(toolName)

      try {
        let resp: Response

        if (toolName === 'dcf') {
          // Need financial data first to get revenue_base etc.
          // Call /api/data/{ticker}/financials then /api/compute/dcf
          const finResp = await fetch(`${BASE_URL}/api/data/${ticker}/financials`)
          let body = { ...DEFAULT_COMPUTE_BODY }

          if (finResp.ok) {
            const fin = (await finResp.json()) as Record<string, unknown>
            const income = (fin.income ?? {}) as Record<string, unknown>
            const market = (fin.market ?? {}) as Record<string, unknown>
            const revenue = (income.revenue as number | undefined) ?? 1
            const netDebt = ((fin.total_debt as number | undefined) ?? 0) - ((fin.total_cash as number | undefined) ?? 0)
            const shares = (market.shares_outstanding as number | undefined) ?? 1

            body = {
              ...body,
              revenue_base: revenue,
              net_debt: netDebt,
              shares_outstanding: shares,
            }
          }

          resp = await fetch(`${BASE_URL}/api/compute/dcf`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          })
        } else if (toolName === 'lbo') {
          // Need financials for ebitda_base
          const finResp = await fetch(`${BASE_URL}/api/data/${ticker}/financials`)
          let ebitdaBase = 1_000_000_000

          if (finResp.ok) {
            const fin = (await finResp.json()) as Record<string, unknown>
            const income = (fin.income ?? {}) as Record<string, unknown>
            ebitdaBase = (income.ebitda as number | undefined) ?? 1_000_000_000
          }

          resp = await fetch(`${BASE_URL}/api/compute/lbo`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              ebitda_base: ebitdaBase,
              revenue_base: ebitdaBase * 5,
              revenue_growth_rates: [0.05, 0.05, 0.04, 0.04, 0.03],
              ebitda_margin: 0.20,
              entry_multiple: 8.0,
              exit_multiple: 8.0,
              debt_pct_ev: 0.60,
              interest_rate: 0.07,
              mandatory_amort_pct: 0.05,
              projection_years: 5,
              tax_rate: 0.21,
              capex_pct_revenue: 0.04,
              nwc_pct_revenue: 0.02,
              da_pct_revenue: 0.03,
            }),
          })
        } else if (toolName === 'comps') {
          // POST /api/runs with pipeline_type=comps
          resp = await fetch(`${BASE_URL}/api/runs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pipeline_type: 'comps', ticker }),
          })
        } else if (toolName === 'catalysts') {
          // GET /api/data/{ticker}/catalysts — just refetch via query
          await queryClient.refetchQueries({ queryKey: ['ticker-catalysts', ticker] })
          return
        } else if (toolName === 'ic-memo') {
          resp = await fetch(`${BASE_URL}/api/runs`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pipeline_type: 'ic-memo', ticker }),
          })
        } else {
          throw new Error(`Unknown tool: ${String(toolName)}`)
        }

        if (!resp.ok) {
          const body = await resp.text().catch(() => '')
          throw new ToolRunError(toolName, resp.status, body)
        }
      } finally {
        finishTool(toolName)
      }
    },

    onSuccess: (_data, toolName) => {
      const tab = TOOL_TAB_MAP[toolName]
      if (tab) setActiveTab(tab)

      // Invalidate artifact cache so history tab refreshes
      void queryClient.invalidateQueries({ queryKey: ['ticker-artifacts', ticker] })

      addToast({
        type: 'success',
        title: `${toolName.toUpperCase()} complete`,
        description: `${ticker} analysis saved to Library`,
      })

      onSuccess?.(toolName)
    },

    onError: (err, toolName) => {
      finishTool(toolName)
      addToast({
        type: 'error',
        title: `${toolName} failed`,
        description: humanReadable(err),
      })
    },
  })
}
