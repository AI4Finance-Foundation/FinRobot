// debateStore — Zustand store for the IC (Investment Committee) Debate pipeline.
//
// Kept deliberately separate from runStreamStore:
//   1. runStreamStore keys runs by ticker and shows a badge on the Sidebar
//      /stocks icon. Debate runs are a different product surface (/ic/*) and
//      should NOT inflate that badge or pollute the pipeline-step view.
//   2. The debate SSE event schema (debate.evidence / debate.point /
//      debate.verdict) is entirely different from the research pipeline's
//      step.started / step.completed events. Mixing them would require every
//      consumer to branch on event type.
//
// One debate state per ticker. Starting a new debate for a ticker closes the
// prior SSE connection before opening a new one.
//
// Module-level EventSource registry mirrors the pattern in runStreamStore:
// EventSource instances are not serialisable, so they live outside the store
// state itself.

import { create } from 'zustand'
import { BASE_URL } from '../api/client'
import { fetchWithTimeout } from '../api/fetch'

// ── Event shapes (from POST /api/debate response + SSE stream) ───────────────

export interface DebateEvidenceItem {
  evidence_id: string
  label: string
  value: number | string
  unit?: string
  formula_id?: string
}

export interface DebateEvidenceEvent {
  event: 'debate.evidence'
  run_id: string
  ticker: string
  current_price: number | null
  reliable: boolean
  items: DebateEvidenceItem[]
}

export interface DebatePoint {
  side: 'bull' | 'bear'
  claim: string
  evidence_ids: string[]
  verified: boolean
  reason: string
}

export interface DebateVerdict {
  call: 'BUY' | 'HOLD' | 'SELL' | 'REVIEW'
  conviction: number | null
  swing_factor: string
  change_my_mind: string
}

// ── Per-ticker debate state ───────────────────────────────────────────────────

export type DebateStatus = 'idle' | 'running' | 'completed' | 'failed'

export interface DebateState {
  /** run_id from POST /api/debate — needed to subscribe to SSE. */
  runId: string | null
  /** The artifact that triggered this debate. */
  artifactId: string | null
  /** evidence_id → item mapping. Built from the first debate.evidence event. */
  evidence: Record<string, DebateEvidenceItem>
  /** Price at debate time (from debate.evidence). */
  current_price: number | null
  /** Whether the underlying data is considered reliable by the backend. */
  reliable: boolean
  bull: DebatePoint[]
  bear: DebatePoint[]
  verdict: DebateVerdict | null
  status: DebateStatus
  error: string | null
}

const INITIAL_DEBATE_STATE: Omit<DebateState, 'runId' | 'artifactId'> = {
  evidence: {},
  current_price: null,
  reliable: true,
  bull: [],
  bear: [],
  verdict: null,
  status: 'idle',
  error: null,
}

// ── Store state interface ─────────────────────────────────────────────────────

interface DebateStoreState {
  debates: Record<string, DebateState>
  startDebate: (ticker: string, artifactId: string) => Promise<void>
  reset: (ticker: string) => void
}

// ── Module-level EventSource registry ────────────────────────────────────────

const sources = new Map<string, EventSource>()
const sseErrorCounts = new Map<string, number>()
const SSE_ERROR_LIMIT = 8

function closeAndForget(ticker: string): void {
  const es = sources.get(ticker)
  if (es) {
    es.close()
    sources.delete(ticker)
  }
  sseErrorCounts.delete(ticker)
}

// ── Store ─────────────────────────────────────────────────────────────────────

export const useDebateStore = create<DebateStoreState>((set, get) => {
  function patch(ticker: string, update: Partial<DebateState>): void {
    set((s) => {
      const cur = s.debates[ticker]
      if (!cur) return s
      return { debates: { ...s.debates, [ticker]: { ...cur, ...update } } }
    })
  }

  function attachSse(runId: string, ticker: string): void {
    closeAndForget(ticker)
    const es = new EventSource(`${BASE_URL}/api/runs/${runId}/events`)
    sources.set(ticker, es)

    es.addEventListener('debate.evidence', (e) => {
      sseErrorCounts.set(ticker, 0)
      const data = JSON.parse((e as MessageEvent).data) as DebateEvidenceEvent
      const evidenceMap: Record<string, DebateEvidenceItem> = {}
      for (const item of data.items) {
        evidenceMap[item.evidence_id] = item
      }
      patch(ticker, {
        evidence: evidenceMap,
        current_price: data.current_price,
        reliable: data.reliable,
      })
    })

    es.addEventListener('debate.point', (e) => {
      sseErrorCounts.set(ticker, 0)
      const data = JSON.parse((e as MessageEvent).data) as DebatePoint & {
        event: string
        run_id: string
      }
      const point: DebatePoint = {
        side: data.side,
        claim: data.claim,
        evidence_ids: data.evidence_ids,
        verified: data.verified,
        reason: data.reason,
      }
      const cur = get().debates[ticker]
      if (!cur) return
      if (point.side === 'bull') {
        patch(ticker, { bull: [...cur.bull, point] })
      } else {
        patch(ticker, { bear: [...cur.bear, point] })
      }
    })

    es.addEventListener('debate.verdict', (e) => {
      sseErrorCounts.set(ticker, 0)
      const data = JSON.parse((e as MessageEvent).data) as DebateVerdict & {
        event: string
        run_id: string
      }
      patch(ticker, {
        verdict: {
          call: data.call,
          conviction: data.conviction,
          swing_factor: data.swing_factor,
          change_my_mind: data.change_my_mind,
        },
      })
    })

    es.addEventListener('run.completed', () => {
      sseErrorCounts.set(ticker, 0)
      patch(ticker, { status: 'completed' })
      closeAndForget(ticker)
    })

    es.addEventListener('run.failed', (e) => {
      const data = JSON.parse((e as MessageEvent).data) as { error?: string }
      patch(ticker, {
        status: 'failed',
        error: data.error || '投委会辩论失败，请重试',
      })
      closeAndForget(ticker)
    })

    es.onerror = () => {
      const cur = get().debates[ticker]
      if (!cur) {
        closeAndForget(ticker)
        return
      }
      if (cur.status !== 'running') {
        closeAndForget(ticker)
        return
      }
      const count = (sseErrorCounts.get(ticker) ?? 0) + 1
      sseErrorCounts.set(ticker, count)
      if (count >= SSE_ERROR_LIMIT) {
        patch(ticker, {
          status: 'failed',
          error: `SSE 连接中断（连续 ${SSE_ERROR_LIMIT} 次错误）。请检查后端服务后重试。`,
        })
        closeAndForget(ticker)
      }
    }
  }

  return {
    debates: {},

    startDebate: async (ticker, artifactId) => {
      const resp = await fetchWithTimeout(
        `${BASE_URL}/api/debate`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ticker, artifact_id: artifactId }),
        },
        8_000,
      )
      if (!resp.ok) {
        const body = (await resp.json().catch(() => ({}))) as { detail?: string }
        const msg = body.detail || `Debate creation failed (${resp.status})`
        throw new Error(msg)
      }
      const { run_id }: { run_id: string } = await resp.json()

      set((s) => ({
        debates: {
          ...s.debates,
          [ticker]: {
            ...INITIAL_DEBATE_STATE,
            runId: run_id,
            artifactId,
            status: 'running',
          },
        },
      }))

      attachSse(run_id, ticker)
    },

    reset: (ticker) => {
      closeAndForget(ticker)
      set((s) => {
        const next = { ...s.debates }
        delete next[ticker]
        return { debates: next }
      })
    },
  }
})

// ── Selectors ─────────────────────────────────────────────────────────────────

export const selectDebate = (ticker: string) => (s: DebateStoreState) => s.debates[ticker] ?? null
