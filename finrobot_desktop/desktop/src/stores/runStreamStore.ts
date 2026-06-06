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
import { withCapabilityToken } from '../api/capability'
import { fetchWithTimeout } from '../api/fetch'
import { FetchHttpError } from '../utils/errorMessage'
import { useUiPrefs } from '../i18n'

export interface RunStep {
  name: string
  status: 'pending' | 'running' | 'completed' | 'retrying' | 'degraded'
  duration_s?: number
  /** Validation error when the step FINISHED but failed validation after all
   * retries (a non-critical degrade). status is 'degraded', rendered amber —
   * not a green ✓ on a step that actually failed (BUG-058). */
  degradeReason?: string
  /** Wall-clock ms when this step entered running — drives the live elapsed
   * counter so a long step (SEC fetches can take 60-90s) reads as alive, not
   * frozen. */
  startedAt?: number
  /** Current retry attempt (from step.retry SSE). Shown as "重试中 n/3" so a
   * step working through a transient 429 doesn't look hung. */
  attempt?: number
}

export type RunStatus = 'running' | 'completed' | 'failed'

/** The backend SSE event vocabulary both stream paths listen for. Pinned by
 *  tests/audit/test_sse_event_contract.py against routes/runs.py. */
type RunEventName =
  | 'run.started'
  | 'step.started'
  | 'step.completed'
  | 'step.retry'
  | 'artifact.ready'
  | 'run.completed'
  | 'run.failed'

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
  /** The artifact THIS run produced, from the run.completed / artifact.ready
   * SSE event. The completion CTA navigates to this id instead of guessing the
   * latest equity_research for the ticker — which opens the wrong report on a
   * same-ticker re-run or a non-research (DCF/LBO/comps/earnings) pipeline.
   * null until the completion event lands (or if the run produced no artifact). */
  artifactId: string | null
  /** The artifact's real type (dcf / lbo / comps / equity_research / …), so the
   * UI can route to the right viewer regardless of pipeline. null until known. */
  artifactType: string | null
}

interface RunStreamState {
  runs: Record<string, RunState>
  startRun: (pipelineType: string, ticker: string, sourceArtifactId?: string) => Promise<string>
  dismiss: (ticker: string) => void
  clear: (ticker: string) => void
  /** Store-level dedupe for a run's terminal (completed/failed) side-effects
   *  (success toast + the 3 query invalidations). Returns true exactly ONCE per
   *  runId — the first caller to claim it — and false forever after. The
   *  consuming view (StockWorkspace) is route-mounted, so a component-level
   *  useRef resets on every navigate-away/back and re-fires the toast +
   *  invalidations against the still-resident completed run (BUG-085). Moving
   *  the dedupe key to this module-level Set makes the effect idempotent across
   *  remounts. */
  markTerminalNotified: (runId: string) => boolean
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
  // Mirror equity_research.py create_*_pipeline().steps EXACTLY (order + count).
  // Backend reports total_steps=8 on run.started; a stale 6-entry list here made
  // the panel render "0/6" and silently drop the step.started events for steps
  // 7-8 (ownership / technical), so two real steps never showed.
  research: [
    'data_collection',
    'catalyst_analysis',
    'peer_analysis',
    'financial_modeling',
    'ownership_governance_analysis',
    'technical_analysis',
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
  // Backend is the source of truth for step COUNT (total_steps). When our
  // hardcoded list disagrees, ALWAYS build an array of length totalSteps:
  // use a known label where we have one, and a `Step N` placeholder for the
  // rest. Never slice down to the shorter list — that silently drops the
  // backend's extra steps (the historical 6-vs-8 research bug). The real
  // names still arrive via step.* events and overwrite these.
  return Array.from({ length: totalSteps }, (_, i) => known?.[i] ?? `Step ${i + 1}`)
}

/** Replace the step at 0-based `index`, growing the array with `Step N`
 * placeholders if the event's index lands beyond the current length. A
 * backend that emits more steps than `run.started` implied (or than our
 * placeholder array covers) must still render every step — never drop one. */
function setStepAt(steps: RunStep[], index: number, next: RunStep): RunStep[] {
  const out = steps.slice()
  for (let i = out.length; i <= index; i++) {
    out[i] = { name: `Step ${i + 1}`, status: 'pending' }
  }
  out[index] = next
  return out
}

// ── Module-level EventSource registry (not in store: not serialisable) ──────

const sources = new Map<string, EventSource>()

// Per-ticker onerror counts. Resets to 0 on any successful event.
// After SSE_ERROR_LIMIT consecutive errors with status still 'running',
// we force-fail the run so the UI doesn't spin indefinitely.
const SSE_ERROR_LIMIT = 8
const sseErrorCounts = new Map<string, number>()

// Module-level dedupe for terminal-run side-effects (BUG-085). A completed run
// stays resident in `runs` for the badge/history; its consuming view is
// route-mounted, so without a dedupe key that outlives the component the
// success toast + query invalidations re-fire on every navigate-back. Keyed by
// runId (a re-run gets a fresh runId, so its effect fires once again — correct).
const notifiedTerminal = new Set<string>()

function closeAndForget(ticker: string): void {
  const es = sources.get(ticker)
  if (es) {
    es.close()
    sources.delete(ticker)
  }
  sseErrorCounts.delete(ticker)
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

  // ── Per-event reducer for the single-run stream (/api/runs/{id}/events) ───
  //
  // `data` is the raw SSE event object. Returns true when the event is terminal
  // (completed/failed) so the caller can tear down the connection.
  // Returns true when the event is terminal (completed/failed) so the caller
  // can decide whether to tear down a dedicated connection.
  function reduceRunEvent(
    ticker: string,
    eventName: string,
    data: Record<string, unknown>,
  ): { terminal: boolean } {
    switch (eventName) {
      case 'run.started': {
        sseErrorCounts.set(ticker, 0)
        const totalSteps = (data.total_steps as number) || 4
        const cur = get().runs[ticker]
        const pipelineType = cur?.pipelineType ?? 'research'
        const names = stepNamesForPipeline(pipelineType, totalSteps)
        patch(ticker, { steps: names.map((name) => ({ name, status: 'pending' as const })) })
        return { terminal: false }
      }
      case 'step.started': {
        sseErrorCounts.set(ticker, 0)
        const cur = get().runs[ticker]
        if (!cur) return { terminal: false }
        const step = data.step as number
        const startIdx = step - 1
        const prev = cur.steps[startIdx]
        patch(ticker, {
          steps: setStepAt(cur.steps, startIdx, {
            ...(prev ?? { status: 'pending' }),
            name: data.name as string,
            status: 'running',
            startedAt: Date.now(),
            attempt: undefined,
          }),
          progress: Math.max(0, (step - 1) / (data.total as number)),
        })
        return { terminal: false }
      }
      case 'step.completed': {
        const cur = get().runs[ticker]
        if (!cur) return { terminal: false }
        const step = data.step as number
        const doneIdx = step - 1
        const prevDone = cur.steps[doneIdx]
        // A degraded step finished but failed validation after all retries
        // (non-critical). Render amber, not a green ✓ (BUG-058).
        const degraded = data.degraded === true
        patch(ticker, {
          steps: setStepAt(cur.steps, doneIdx, {
            ...(prevDone ?? { status: 'pending' }),
            name: data.name as string,
            status: degraded ? 'degraded' : 'completed',
            duration_s: data.duration_s as number,
            degradeReason: degraded ? ((data.error as string | null) ?? undefined) : undefined,
          }),
          progress: step / (data.total as number),
        })
        return { terminal: false }
      }
      case 'step.retry': {
        const cur = get().runs[ticker]
        if (!cur) return { terminal: false }
        const retryIdx = (data.step as number) - 1
        const prevRetry = cur.steps[retryIdx]
        patch(ticker, {
          steps: setStepAt(cur.steps, retryIdx, {
            ...(prevRetry ?? { status: 'pending' }),
            name: data.name as string,
            status: 'retrying',
            attempt: data.attempt as number,
          }),
        })
        return { terminal: false }
      }
      case 'artifact.ready': {
        sseErrorCounts.set(ticker, 0)
        // artifact_id is optional (back-compat with pre-field stored events);
        // only stamp identity when present so we never clobber a real id with null.
        const update: Partial<RunState> = {}
        if (data.artifact_id) update.artifactId = data.artifact_id as string
        if (data.artifact_type) update.artifactType = data.artifact_type as string
        if (Object.keys(update).length > 0) patch(ticker, update)
        return { terminal: false }
      }
      case 'run.completed': {
        sseErrorCounts.set(ticker, 0)
        const update: Partial<RunState> = { status: 'completed', progress: 1 }
        // Prefer the completion event's identity; artifact.ready may already have
        // set it. Both optional for back-compat — keep any prior value if absent.
        if (data.artifact_id) update.artifactId = data.artifact_id as string
        if (data.artifact_type) update.artifactType = data.artifact_type as string
        patch(ticker, update)
        return { terminal: true }
      }
      case 'run.failed': {
        patch(ticker, {
          status: 'failed',
          error: (data.error as string) || 'Pipeline failed',
        })
        return { terminal: true }
      }
      default:
        return { terminal: false }
    }
  }

  async function attachSse(runId: string, ticker: string): Promise<void> {
    closeAndForget(ticker)
    // EventSource cannot set an Authorization header, so the capability token
    // rides as ?token= (the backend accepts it there for SSE). No-op in browser dev.
    const url = await withCapabilityToken(`${BASE_URL}/api/runs/${runId}/events`)
    const es = new EventSource(url)
    sources.set(ticker, es)

    // Explicit per-event `addEventListener('<name>', …)` calls (not a loop) so
    // the SSE-contract audit (tests/audit/test_sse_event_contract.py) can
    // statically pin that the frontend listens for every backend event. Each
    // forwards to the shared reducer; terminal events tear down this dedicated
    // connection. `single` binds the ticker + closes on terminal.
    const single = (name: RunEventName) => (e: Event) => {
      const data = JSON.parse((e as MessageEvent).data)
      const { terminal } = reduceRunEvent(ticker, name, data)
      if (terminal) closeAndForget(ticker)
    }
    es.addEventListener('run.started', single('run.started'))
    es.addEventListener('step.started', single('step.started'))
    es.addEventListener('step.completed', single('step.completed'))
    es.addEventListener('step.retry', single('step.retry'))
    es.addEventListener('artifact.ready', single('artifact.ready'))
    es.addEventListener('run.completed', single('run.completed'))
    es.addEventListener('run.failed', single('run.failed'))

    es.onerror = () => {
      const cur = get().runs[ticker]
      if (!cur) {
        closeAndForget(ticker)
        return
      }
      // If the run already completed or failed, clean up the stale connection.
      if (cur.status !== 'running') {
        closeAndForget(ticker)
        return
      }
      // Run is still marked 'running'. Browser EventSource auto-reconnects
      // (with Last-Event-ID) on transient network errors, so we tolerate a few
      // consecutive errors before giving up. Once we hit SSE_ERROR_LIMIT with
      // no recovery, the run_id is likely invalid or the backend is down —
      // force-fail so the UI shows an actionable error instead of a frozen
      // progress bar.
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
    runs: {},

    startRun: async (pipelineType, ticker, sourceArtifactId) => {
      const resp = await fetchWithTimeout(
        `${BASE_URL}/api/runs`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          // Generate the report's prose in the current UI language. The backend
          // stamps this onto artifact.meta.language; the detail view then renders
          // the body in this language regardless of later UI-locale switches.
          // source_artifact_id (set on re-run) records the version lineage so the
          // diff view can default to comparing against the version re-run from.
          body: JSON.stringify({
            pipeline_type: pipelineType,
            ticker,
            language: useUiPrefs.getState().locale,
            ...(sourceArtifactId ? { source_artifact_id: sourceArtifactId } : {}),
          }),
        },
        5_000,
      )
      if (!resp.ok) {
        // Prefer the backend's human-readable `detail` (e.g. the 503 from
        // BUG-056's startup_error gate carries an actionable message). When it's
        // absent, throw a typed FetchHttpError so mapErrorToUserMessage renders
        // a friendly localised string instead of leaking "Run creation failed
        // (500)" to the toast (BUG-027).
        const body = (await resp.json().catch(() => ({}))) as { detail?: string }
        const detail = typeof body.detail === 'string' ? body.detail.trim() : ''
        if (detail) throw new Error(detail)
        throw new FetchHttpError(resp.status, resp.statusText)
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
            artifactId: null,
            artifactType: null,
          },
        },
      }))

      await attachSse(run_id, ticker)
      return run_id
    },

    dismiss: (ticker) => {
      patch(ticker, { dismissed: true })
    },

    clear: (ticker) => {
      closeAndForget(ticker)
      const runId = get().runs[ticker]?.runId
      if (runId) notifiedTerminal.delete(runId)
      set((s) => {
        const next = { ...s.runs }
        delete next[ticker]
        return { runs: next }
      })
    },

    markTerminalNotified: (runId) => {
      if (notifiedTerminal.has(runId)) return false
      notifiedTerminal.add(runId)
      return true
    },
  }
})

// ── Selectors ───────────────────────────────────────────────────────────────

export const selectRunByTicker = (ticker: string) => (s: RunStreamState) => s.runs[ticker]

export const selectActiveRunCount = (s: RunStreamState): number =>
  Object.values(s.runs).filter((r) => r.status === 'running').length
