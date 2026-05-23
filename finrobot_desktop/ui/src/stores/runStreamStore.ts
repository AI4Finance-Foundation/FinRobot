// runStreamStore — global active pipeline runs, keyed by ticker.
//
// Why a store (not a component-local hook): the analysis pipeline takes 30-60s
// and users routinely navigate away ("决策日记" / "报告库") while it runs. If
// state lives in a React component, route changes unmount it and the SSE
// connection closes — the run keeps running on the backend but the UI loses
// track of it. Lifting state to a store makes route changes invisible to the
// run, and lets the Sidebar show an "active runs" badge across the whole app.
//
// EventSource instances are not serialisable, so they live in a module-level
// Map<ticker, EventSource> instead of in the store. The backend SSE endpoint
// (/api/runs/{id}/events) supports Last-Event-ID resume, so browser-native
// EventSource auto-reconnect will pick up where it left off on network
// hiccups — without any extra code here.
//
// Concurrency: one active run per ticker (Map keyed by ticker). Starting a run
// for a ticker that already has one closes the old SSE first.

import { create } from 'zustand'
import { BASE_URL } from '../api/client'

export interface RunStep {
  name: string
  status: 'pending' | 'running' | 'completed' | 'retrying'
  duration_s?: number
}

export type RunStatus = 'running' | 'completed' | 'failed'

export interface RunState {
  runId: string
  ticker: string
  pipelineType: string
  steps: RunStep[]
  status: RunStatus
  progress: number
  error: string | null
  startedAt: number
  /** User clicked "view report" (or otherwise acknowledged) — UI may hide the
   * progress overlay even though completed/failed state is still here for
   * the badge / history. */
  dismissed: boolean
}

interface RunStreamState {
  runs: Record<string, RunState>
  startRun: (pipelineType: string, ticker: string) => Promise<string>
  dismiss: (ticker: string) => void
  clear: (ticker: string) => void
}

// ── Pipeline → real step names ─────────────────────────────────────────────
//
// SSE `run.started` only carries `total_steps`, not the per-step names —
// those arrive lazily on each `step.started`. If we initialise the steps
// list with "Step 1 / Step 2 / …" placeholders, the PipelineProgressPanel
// renders garbage labels for every step that hasn't started yet (user got
// 数据收集 ✓ + 催化剂识别 ⟳ + Step 3 / Step 4 / Step 5 / Step 6 ⏳).
//
// Mirror the actual pipeline registry here so the names show up even
// before the SSE for each step lands. Backend remains the source of
// truth — incoming step.started / step.completed events still overwrite
// the name field, so a pipeline rename on the backend won't silently
// diverge (it just briefly shows the stale name until the first event).
const PIPELINE_STEP_NAMES: Record<string, string[]> = {
  research: [
    'data_collection',
    'catalyst_analysis',
    'peer_analysis',
    'financial_modeling',
    'thesis',
    'report',
  ],
  'ic-memo': ['data_collection', 'financial_analysis', 'memo_drafting', 'report'],
  earnings: ['data_collection', 'earnings_extraction', 'thesis', 'report'],
  dcf: ['data_collection', 'financial_modeling', 'report'],
  lbo: ['data_collection', 'lbo_modeling', 'report'],
  ddm: ['data_collection', 'ddm_modeling', 'report'],
  comps: ['data_collection', 'peer_analysis', 'report'],
}

function stepNamesForPipeline(pipelineType: string, totalSteps: number): string[] {
  const known = PIPELINE_STEP_NAMES[pipelineType]
  if (known && known.length === totalSteps) return known
  if (known) return known.slice(0, totalSteps)
  // Unknown pipeline OR backend reported a different step count than we
  // hardcoded — fall back to numeric placeholders so we don't fabricate
  // wrong names. SSE events will overwrite as they land.
  return Array.from({ length: totalSteps }, (_, i) => `Step ${i + 1}`)
}

// ── Module-level EventSource registry (not in store: not serialisable) ──────

const sources = new Map<string, EventSource>()

function closeAndForget(ticker: string): void {
  const es = sources.get(ticker)
  if (es) {
    es.close()
    sources.delete(ticker)
  }
}

// ── Store ───────────────────────────────────────────────────────────────────

export const useRunStreamStore = create<RunStreamState>((set, get) => {
  function patch(ticker: string, update: Partial<RunState>): void {
    set((s) => {
      const cur = s.runs[ticker]
      if (!cur) return s
      return { runs: { ...s.runs, [ticker]: { ...cur, ...update } } }
    })
  }

  function attachSse(runId: string, ticker: string): void {
    closeAndForget(ticker)
    const es = new EventSource(`${BASE_URL}/api/runs/${runId}/events`)
    sources.set(ticker, es)

    es.addEventListener('run.started', (e) => {
      const data = JSON.parse((e as MessageEvent).data)
      const totalSteps = data.total_steps || 4
      const cur = get().runs[ticker]
      const pipelineType = cur?.pipelineType ?? 'research'
      const names = stepNamesForPipeline(pipelineType, totalSteps)
      patch(ticker, {
        steps: names.map((name) => ({ name, status: 'pending' as const })),
      })
    })

    es.addEventListener('step.started', (e) => {
      const data = JSON.parse((e as MessageEvent).data)
      const cur = get().runs[ticker]
      if (!cur) return
      patch(ticker, {
        steps: cur.steps.map((s, i) =>
          i === data.step - 1 ? { ...s, name: data.name, status: 'running' } : s,
        ),
        progress: Math.max(0, (data.step - 1) / data.total),
      })
    })

    es.addEventListener('step.completed', (e) => {
      const data = JSON.parse((e as MessageEvent).data)
      const cur = get().runs[ticker]
      if (!cur) return
      patch(ticker, {
        steps: cur.steps.map((s, i) =>
          i === data.step - 1
            ? { ...s, name: data.name, status: 'completed', duration_s: data.duration_s }
            : s,
        ),
        progress: data.step / data.total,
      })
    })

    es.addEventListener('step.retry', (e) => {
      const data = JSON.parse((e as MessageEvent).data)
      const cur = get().runs[ticker]
      if (!cur) return
      patch(ticker, {
        steps: cur.steps.map((s, i) =>
          i === data.step - 1 ? { ...s, name: data.name, status: 'retrying' } : s,
        ),
      })
    })

    es.addEventListener('run.completed', () => {
      patch(ticker, { status: 'completed', progress: 1 })
      closeAndForget(ticker)
    })

    es.addEventListener('run.failed', (e) => {
      const data = JSON.parse((e as MessageEvent).data)
      patch(ticker, { status: 'failed', error: data.error || 'Pipeline failed' })
      closeAndForget(ticker)
    })

    es.onerror = () => {
      // Browser EventSource handles reconnect itself (with Last-Event-ID, since
      // the backend assigns id: <seq> per event). We only need to clean up if
      // the run is already finished — otherwise let it retry silently.
      const cur = get().runs[ticker]
      if (cur && cur.status !== 'running') {
        closeAndForget(ticker)
      }
    }
  }

  return {
    runs: {},

    startRun: async (pipelineType, ticker) => {
      const resp = await fetch(`${BASE_URL}/api/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pipeline_type: pipelineType, ticker }),
      })
      if (!resp.ok) {
        const body = await resp.json().catch(() => ({}))
        const msg = body.detail || `Run creation failed (${resp.status})`
        throw new Error(msg)
      }
      const { run_id }: { run_id: string } = await resp.json()

      set((s) => ({
        runs: {
          ...s.runs,
          [ticker]: {
            runId: run_id,
            ticker,
            pipelineType,
            steps: [],
            status: 'running',
            progress: 0,
            error: null,
            startedAt: Date.now(),
            dismissed: false,
          },
        },
      }))

      attachSse(run_id, ticker)
      return run_id
    },

    dismiss: (ticker) => {
      patch(ticker, { dismissed: true })
    },

    clear: (ticker) => {
      closeAndForget(ticker)
      set((s) => {
        const next = { ...s.runs }
        delete next[ticker]
        return { runs: next }
      })
    },
  }
})

// ── Selectors ───────────────────────────────────────────────────────────────

export const selectRunByTicker = (ticker: string) => (s: RunStreamState) => s.runs[ticker]

export const selectActiveRunCount = (s: RunStreamState): number =>
  Object.values(s.runs).filter((r) => r.status === 'running').length
