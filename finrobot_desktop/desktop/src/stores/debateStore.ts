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
// One debate state per (ticker, artifact). Evidence is extracted from the
// specific artifact's structured outputs (see engine/debate/evidence.py), so
// two reports for the same ticker yield DIFFERENT debates and must NOT share
// state — keying by ticker alone would make report B silently show report A's
// verdict and evidence. Starting a new debate for the same (ticker, artifact)
// closes its prior SSE connection before opening a new one.
//
// Module-level EventSource registry mirrors the pattern in runStreamStore:
// EventSource instances are not serialisable, so they live outside the store
// state itself. Keyed by the same composite debate key.

import { create } from 'zustand'
import { BASE_URL } from '../api/client'
import { fetchWithTimeout } from '../api/fetch'
import { withCapabilityToken } from '../api/capability'

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

// ── Per-(ticker, artifact) debate state ──────────────────────────────────────

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
  reset: (ticker: string, artifactId: string) => void
}

// Composite key: a debate is uniquely identified by (ticker, artifact), not by
// ticker alone. The same ticker can have multiple equity_research reports and
// each gets its own debate with its own evidence set.
function debateKey(ticker: string, artifactId: string): string {
  return `${ticker}::${artifactId}`
}

// ── Module-level EventSource registry ────────────────────────────────────────

const sources = new Map<string, EventSource>()
const sseErrorCounts = new Map<string, number>()
const sseSuccessStreaks = new Map<string, number>()
const SSE_ERROR_LIMIT = 8
// Errors are only forgiven after the stream proves stable again. Resetting the
// counter on ANY successful event let a flapping connection ([error, event,
// error, event…]) dodge SSE_ERROR_LIMIT forever — the debate hung in endless
// reconnect cycles instead of failing over to the retry UI (BUG-044).
const SSE_STABLE_SUCCESSES = 3

function noteSseSuccess(key: string): void {
  const streak = (sseSuccessStreaks.get(key) ?? 0) + 1
  sseSuccessStreaks.set(key, streak)
  if (streak >= SSE_STABLE_SUCCESSES) sseErrorCounts.delete(key)
}

function closeAndForget(key: string): void {
  const es = sources.get(key)
  if (es) {
    es.close()
    sources.delete(key)
  }
  sseErrorCounts.delete(key)
  sseSuccessStreaks.delete(key)
}

// ── Store ─────────────────────────────────────────────────────────────────────

export const useDebateStore = create<DebateStoreState>((set, get) => {
  function patch(key: string, update: Partial<DebateState>): void {
    set((s) => {
      const cur = s.debates[key]
      if (!cur) return s
      return { debates: { ...s.debates, [key]: { ...cur, ...update } } }
    })
  }

  async function attachSse(runId: string, key: string): Promise<void> {
    closeAndForget(key)
    // EventSource cannot set an Authorization header → capability token rides
    // as ?token= (no-op in browser dev). Mirrors runStreamStore.attachSse.
    const url = await withCapabilityToken(`${BASE_URL}/api/runs/${runId}/events`)
    const es = new EventSource(url)
    sources.set(key, es)

    es.addEventListener('debate.evidence', (e) => {
      noteSseSuccess(key)
      const data = JSON.parse((e as MessageEvent).data) as DebateEvidenceEvent
      const evidenceMap: Record<string, DebateEvidenceItem> = {}
      for (const item of data.items) {
        evidenceMap[item.evidence_id] = item
      }
      patch(key, {
        evidence: evidenceMap,
        current_price: data.current_price,
        reliable: data.reliable,
      })
    })

    es.addEventListener('debate.point', (e) => {
      noteSseSuccess(key)
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
      const cur = get().debates[key]
      if (!cur) return
      if (point.side === 'bull') {
        patch(key, { bull: [...cur.bull, point] })
      } else {
        patch(key, { bear: [...cur.bear, point] })
      }
    })

    es.addEventListener('debate.verdict', (e) => {
      noteSseSuccess(key)
      const data = JSON.parse((e as MessageEvent).data) as DebateVerdict & {
        event: string
        run_id: string
      }
      patch(key, {
        verdict: {
          call: data.call,
          conviction: data.conviction,
          swing_factor: data.swing_factor,
          change_my_mind: data.change_my_mind,
        },
      })
    })

    es.addEventListener('run.completed', () => {
      patch(key, { status: 'completed' })
      closeAndForget(key)
    })

    es.addEventListener('run.failed', (e) => {
      const data = JSON.parse((e as MessageEvent).data) as { error?: string }
      patch(key, {
        status: 'failed',
        error: data.error || '投委会辩论失败，请重试',
      })
      closeAndForget(key)
    })

    es.onerror = () => {
      const cur = get().debates[key]
      if (!cur) {
        closeAndForget(key)
        return
      }
      if (cur.status !== 'running') {
        closeAndForget(key)
        return
      }
      sseSuccessStreaks.delete(key)
      const count = (sseErrorCounts.get(key) ?? 0) + 1
      sseErrorCounts.set(key, count)
      if (count >= SSE_ERROR_LIMIT) {
        patch(key, {
          status: 'failed',
          error: `SSE 连接中断（连续 ${SSE_ERROR_LIMIT} 次错误）。请检查后端服务后重试。`,
        })
        closeAndForget(key)
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

      const key = debateKey(ticker, artifactId)
      set((s) => ({
        debates: {
          ...s.debates,
          [key]: {
            ...INITIAL_DEBATE_STATE,
            runId: run_id,
            artifactId,
            status: 'running',
          },
        },
      }))

      await attachSse(run_id, key)
    },

    reset: (ticker, artifactId) => {
      const key = debateKey(ticker, artifactId)
      closeAndForget(key)
      set((s) => {
        const next = { ...s.debates }
        delete next[key]
        return { debates: next }
      })
    },
  }
})

// ── Selectors ─────────────────────────────────────────────────────────────────

// artifactId may be null before the report is known — no debate can exist for
// a null artifact, so return null and let the page show its start/warning state.
export const selectDebate = (ticker: string, artifactId: string | null) => (s: DebateStoreState) =>
  artifactId ? (s.debates[debateKey(ticker, artifactId)] ?? null) : null
