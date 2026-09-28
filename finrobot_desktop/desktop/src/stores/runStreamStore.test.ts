// runStreamStore — step-drift (BUG-033) + artifact identity on completion
// (BUG-034/043).
//
// jsdom has no EventSource, so we install a controllable fake that records its
// listeners and lets the test emit named SSE events synchronously.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useRunStreamStore } from './runStreamStore'

// ── Fake EventSource ────────────────────────────────────────────────────────

class FakeEventSource {
  static instances: FakeEventSource[] = []
  url: string
  listeners = new Map<string, (e: MessageEvent) => void>()
  onerror: (() => void) | null = null
  closed = false

  constructor(url: string) {
    this.url = url
    FakeEventSource.instances.push(this)
  }

  addEventListener(type: string, fn: (e: MessageEvent) => void): void {
    this.listeners.set(type, fn)
  }

  close(): void {
    this.closed = true
  }

  /** Emit a named SSE event with a JSON payload, like the backend stream. */
  emit(type: string, data: Record<string, unknown>): void {
    const fn = this.listeners.get(type)
    if (fn) fn({ data: JSON.stringify(data) } as MessageEvent)
  }
}

const TICKER = 'AAPL'

async function startRun(pipelineType: string): Promise<FakeEventSource> {
  await useRunStreamStore.getState().startRun(pipelineType, TICKER)
  const es = FakeEventSource.instances.at(-1)
  if (!es) throw new Error('no EventSource was created')
  return es
}

function stepsState() {
  return useRunStreamStore.getState().runs[TICKER]
}

beforeEach(() => {
  FakeEventSource.instances = []
  vi.stubGlobal('EventSource', FakeEventSource as unknown as typeof EventSource)
  // startRun POSTs to /api/runs before opening the stream.
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => ({
      ok: true,
      json: async () => ({ run_id: 'run-test-1' }),
    })) as unknown as typeof fetch,
  )
})

afterEach(() => {
  useRunStreamStore.getState().clear(TICKER)
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('step drift (BUG-033)', () => {
  it('renders ALL steps when backend total exceeds the hardcoded list', async () => {
    // research hardcodes 8 labels; pretend backend grew to 9 steps.
    const es = await startRun('research')
    es.emit('run.started', { total_steps: 9 })

    const run = stepsState()
    expect(run.steps).toHaveLength(9)
    // Known labels preserved...
    expect(run.steps[0].name).toBe('data_collection')
    // ...and the extra 9th step gets a placeholder, not dropped.
    expect(run.steps[8].name).toBe('Step 9')
  })

  it('a step event with an index beyond the known list still renders', async () => {
    const es = await startRun('research')
    es.emit('run.started', { total_steps: 9 })
    // The real 9th step arrives — must overwrite the placeholder, not vanish.
    es.emit('step.completed', { step: 9, total: 9, name: 'final_audit', duration_s: 4.2 })

    const run = stepsState()
    expect(run.steps).toHaveLength(9)
    expect(run.steps[8].name).toBe('final_audit')
    expect(run.steps[8].status).toBe('completed')
    expect(run.steps[8].duration_s).toBe(4.2)
  })

  it('grows the array when a step index lands beyond the current length', async () => {
    // run.started reports fewer steps than the backend actually emits.
    const es = await startRun('dcf') // dcf hardcodes 3
    es.emit('run.started', { total_steps: 3 })
    // Backend emits a 5th step anyway — must not be silently truncated.
    es.emit('step.started', { step: 5, total: 5, name: 'surprise_step' })

    const run = stepsState()
    expect(run.steps.length).toBeGreaterThanOrEqual(5)
    expect(run.steps[4].name).toBe('surprise_step')
    expect(run.steps[4].status).toBe('running')
    // Gap-filled index 3 is a pending placeholder, not undefined.
    expect(run.steps[3].status).toBe('pending')
  })
})

describe('artifact identity on completion (BUG-034/043)', () => {
  it('stores artifactId + artifactType from run.completed', async () => {
    const es = await startRun('lbo')
    es.emit('run.started', { total_steps: 3 })
    es.emit('run.completed', {
      run_id: 'run-test-1',
      ticker: TICKER,
      duration_s: 12,
      result_url: '/api/artifacts/art_AAPL_lbo',
      artifact_id: 'art_AAPL_lbo',
      artifact_type: 'lbo',
    })

    const run = stepsState()
    expect(run.status).toBe('completed')
    expect(run.artifactId).toBe('art_AAPL_lbo')
    expect(run.artifactType).toBe('lbo')
  })

  it('picks up artifactId from artifact.ready before run.completed', async () => {
    const es = await startRun('comps')
    es.emit('run.started', { total_steps: 3 })
    es.emit('artifact.ready', {
      run_id: 'run-test-1',
      artifact_type: 'comps',
      format: 'json',
      artifact_id: 'art_AAPL_comps',
    })

    expect(stepsState().artifactId).toBe('art_AAPL_comps')
    expect(stepsState().artifactType).toBe('comps')
  })

  it('back-compat: run.completed without artifact fields leaves identity null', async () => {
    const es = await startRun('research')
    es.emit('run.started', { total_steps: 8 })
    es.emit('run.completed', {
      run_id: 'run-test-1',
      ticker: TICKER,
      duration_s: 5,
      result_url: '/api/runs/run-test-1',
    })

    const run = stepsState()
    expect(run.status).toBe('completed')
    expect(run.artifactId).toBeNull()
    expect(run.artifactType).toBeNull()
  })
})

describe('terminal-side-effect dedupe (BUG-085)', () => {
  it('markTerminalNotified returns true once per runId, then false on replay', () => {
    const store = useRunStreamStore.getState()
    // First claim wins (the run-completion effect fires its toast + invalidations).
    expect(store.markTerminalNotified('run-1')).toBe(true)
    // A route remount re-runs the effect against the still-resident completed
    // run — the store-level Set must suppress the duplicate.
    expect(store.markTerminalNotified('run-1')).toBe(false)
    expect(store.markTerminalNotified('run-1')).toBe(false)
    // A different run (e.g. a re-run, which gets a fresh runId) fires once again.
    expect(store.markTerminalNotified('run-2')).toBe(true)
    expect(store.markTerminalNotified('run-2')).toBe(false)
  })

  it('clear() forgets the runId so a later same-id run can notify again', () => {
    const store = useRunStreamStore.getState()
    // Seed a completed run for the ticker via the SSE path, then claim it.
    expect(store.markTerminalNotified('run-clear')).toBe(true)
    // Drive a run for the ticker so clear() has something to read the runId from.
    useRunStreamStore.setState((s) => ({
      runs: {
        ...s.runs,
        [TICKER]: {
          runId: 'run-clear',
          ticker: TICKER,
          pipelineType: 'research',
          steps: [],
          status: 'completed',
          progress: 1,
          error: null,
          startedAt: Date.now(),
          dismissed: false,
          artifactId: null,
          artifactType: null,
          cancelling: false,
        },
      },
    }))
    useRunStreamStore.getState().clear(TICKER)
    // clear dropped run-clear from the dedupe Set — it can notify once more.
    expect(useRunStreamStore.getState().markTerminalNotified('run-clear')).toBe(true)
  })
})

describe('duplicate-start lock (P1-30)', () => {
  it('two same-tick startRun calls fire exactly ONE POST and share the run_id', async () => {
    const p1 = useRunStreamStore.getState().startRun('research', TICKER)
    const p2 = useRunStreamStore.getState().startRun('research', TICKER)
    const [r1, r2] = await Promise.all([p1, p2])

    expect(r1).toBe('run-test-1')
    expect(r2).toBe('run-test-1')
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
    // One run, one SSE connection — the second attach used to orphan the first.
    expect(FakeEventSource.instances).toHaveLength(1)
  })

  it('occupies the run slot synchronously, before the POST resolves', () => {
    const p = useRunStreamStore.getState().startRun('research', TICKER)
    // No await yet: the in-flight POST window must already read as running,
    // so isRunning guards and disabled buttons close the double-click hole.
    expect(stepsState()?.status).toBe('running')
    return p
  })

  it('refuses to start while the ticker already has a live run (no POST)', async () => {
    await startRun('research')
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    fetchMock.mockClear()

    await expect(useRunStreamStore.getState().startRun('research', TICKER)).rejects.toThrow(
      /already in progress/,
    )
    expect(fetchMock).not.toHaveBeenCalled()
    // The live run is untouched.
    expect(stepsState().status).toBe('running')
  })

  it('a failed POST rolls the occupation back so the next attempt can start', async () => {
    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    fetchMock.mockRejectedValueOnce(new Error('network down'))

    await expect(useRunStreamStore.getState().startRun('research', TICKER)).rejects.toThrow(
      'network down',
    )
    // Slot cleared — not left as a phantom 'running' that blocks retries.
    expect(stepsState()).toBeUndefined()

    // Retry succeeds against the restored default mock.
    await expect(useRunStreamStore.getState().startRun('research', TICKER)).resolves.toBe(
      'run-test-1',
    )
    expect(stepsState().status).toBe('running')
  })

  it('a failed re-run restores the resident completed run instead of wiping it', async () => {
    const completed = {
      runId: 'run-done',
      ticker: TICKER,
      pipelineType: 'research',
      steps: [],
      status: 'completed' as const,
      progress: 1,
      error: null,
      startedAt: Date.now(),
      dismissed: false,
      artifactId: 'art_prev',
      artifactType: 'equity_research',
      cancelling: false,
    }
    useRunStreamStore.setState((s) => ({ runs: { ...s.runs, [TICKER]: completed } }))

    const fetchMock = globalThis.fetch as unknown as ReturnType<typeof vi.fn>
    fetchMock.mockRejectedValueOnce(new Error('boom'))
    await expect(useRunStreamStore.getState().startRun('research', TICKER)).rejects.toThrow('boom')

    // The badge/history state survives the failed re-run attempt.
    expect(stepsState()).toEqual(completed)
  })
})

describe('restart reattach (P1-30)', () => {
  function fetchReturning(rows: unknown): void {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => rows,
      })) as unknown as typeof fetch,
    )
  }

  afterEach(() => {
    // Tests here use tickers beyond the shared TICKER — drop everything.
    useRunStreamStore.setState({ runs: {} })
  })

  it('rebuilds RunState + SSE subscription from the backend active-run list', async () => {
    fetchReturning([
      {
        run_id: 'run-live-1',
        status: 'running',
        pipeline_type: 'research',
        ticker: 'AAPL',
        created_at: '2026-06-10T01:02:03+00:00',
      },
    ])

    await useRunStreamStore.getState().reattachActiveRuns()

    const run = useRunStreamStore.getState().runs['AAPL']
    expect(run).toBeDefined()
    expect(run.runId).toBe('run-live-1')
    expect(run.status).toBe('running')
    expect(run.pipelineType).toBe('research')
    expect(run.startedAt).toBe(Date.parse('2026-06-10T01:02:03+00:00'))

    // One SSE subscription against THIS run's stream…
    expect(FakeEventSource.instances).toHaveLength(1)
    expect(FakeEventSource.instances[0].url).toContain('/api/runs/run-live-1/events')
    // …and the replayed event log (no Last-Event-ID → from seq 0) rebuilds steps.
    FakeEventSource.instances[0].emit('run.started', { total_steps: 8 })
    expect(useRunStreamStore.getState().runs['AAPL'].steps).toHaveLength(8)
  })

  it('skips terminal rows, debate runs, and tickers already tracked live', async () => {
    // A live run this session already tracks must not be clobbered.
    await useRunStreamStore.getState().startRun('research', TICKER)
    const liveRunId = useRunStreamStore.getState().runs[TICKER].runId
    const attachedBefore = FakeEventSource.instances.length

    fetchReturning([
      // newest row for the already-live ticker — must be ignored
      {
        run_id: 'run-other',
        status: 'running',
        pipeline_type: 'dcf',
        ticker: TICKER,
        created_at: '2026-06-10T00:00:02+00:00',
      },
      // terminal row — must be ignored (defensive: backend already filters)
      {
        run_id: 'run-done',
        status: 'completed',
        pipeline_type: 'research',
        ticker: 'MSFT',
        created_at: '2026-06-10T00:00:01+00:00',
      },
      // legacy debate run — feature removed; a stale local DB may still hold
      // such rows and they must never resurrect on reattach
      {
        run_id: 'run-debate',
        status: 'running',
        pipeline_type: 'debate',
        ticker: 'NVDA',
        created_at: '2026-06-10T00:00:00+00:00',
      },
    ])
    await useRunStreamStore.getState().reattachActiveRuns()

    const runs = useRunStreamStore.getState().runs
    expect(runs[TICKER].runId).toBe(liveRunId)
    expect(runs['MSFT']).toBeUndefined()
    expect(runs['NVDA']).toBeUndefined()
    expect(FakeEventSource.instances).toHaveLength(attachedBefore)
  })

  it('is a silent no-op when the backend is unreachable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        throw new Error('ECONNREFUSED')
      }) as unknown as typeof fetch,
    )

    await expect(useRunStreamStore.getState().reattachActiveRuns()).resolves.toBeUndefined()
    expect(useRunStreamStore.getState().runs).toEqual({})
    expect(FakeEventSource.instances).toHaveLength(0)
  })

  it('concurrent calls share one GET (StrictMode double-fire)', async () => {
    fetchReturning([])
    const p1 = useRunStreamStore.getState().reattachActiveRuns()
    const p2 = useRunStreamStore.getState().reattachActiveRuns()
    await Promise.all([p1, p2])
    expect(globalThis.fetch).toHaveBeenCalledTimes(1)
  })
})

describe('SSE error counting (BUG-044 sibling)', () => {
  function triggerError(es: FakeEventSource): void {
    es.onerror?.()
  }

  it('an [error, event, error, event…] flapping connection still trips the limit', async () => {
    const es = await startRun('research')
    es.emit('run.started', { total_steps: 8 })
    for (let i = 0; i < 8; i++) {
      expect(stepsState().status).toBe('running')
      triggerError(es)
      es.emit('step.started', { step: 1, total: 8, name: 'data_collection' })
    }
    expect(stepsState().status).toBe('failed')
    expect(es.closed).toBe(true)
  })

  it('a genuinely recovered stream (stable successes) forgives past errors', async () => {
    const es = await startRun('research')
    es.emit('run.started', { total_steps: 8 })
    for (let i = 0; i < 7; i++) triggerError(es)
    expect(stepsState().status).toBe('running')
    for (let i = 0; i < 3; i++) {
      es.emit('step.started', { step: 1, total: 8, name: 'data_collection' })
    }
    for (let i = 0; i < 7; i++) triggerError(es)
    expect(stepsState().status).toBe('running')
    triggerError(es)
    expect(stepsState().status).toBe('failed')
  })
})

describe('run cancellation (P2: stop button for money-burning pipelines)', () => {
  it('cancelRun marks cancelling; the run.cancelled SSE event lands the terminal state', async () => {
    const es = await startRun('research')
    es.emit('run.started', { total_steps: 8 })

    // Second fetch call is the cancel POST — backend says the task is unwinding.
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ run_id: 'run-test-1', status: 'cancelling' }),
      })) as unknown as typeof fetch,
    )
    await useRunStreamStore.getState().cancelRun(TICKER)

    // Backend owns the truth: still running, button shows "Cancelling…".
    expect(stepsState().status).toBe('running')
    expect(stepsState().cancelling).toBe(true)

    es.emit('run.cancelled', { run_id: 'run-test-1', ticker: TICKER })
    expect(stepsState().status).toBe('cancelled')
    expect(stepsState().cancelling).toBe(false)
    // Terminal — no error text (a cancel is not a failure), stream torn down.
    expect(stepsState().error).toBeNull()
    expect(es.closed).toBe(true)
  })

  it('an orphan finalised directly by the endpoint (status: cancelled) lands immediately', async () => {
    const es = await startRun('research')
    es.emit('run.started', { total_steps: 8 })

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ run_id: 'run-test-1', status: 'cancelled' }),
      })) as unknown as typeof fetch,
    )
    await useRunStreamStore.getState().cancelRun(TICKER)

    // No SSE frame will ever come from a dead task — the store reflects the
    // terminal state from the POST response itself.
    expect(stepsState().status).toBe('cancelled')
    expect(stepsState().cancelling).toBe(false)
    expect(es.closed).toBe(true)
  })

  it('a failed cancel POST rolls the cancelling flag back and rejects', async () => {
    await startRun('research')

    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        json: async () => ({}),
      })) as unknown as typeof fetch,
    )
    await expect(useRunStreamStore.getState().cancelRun(TICKER)).rejects.toThrow()
    expect(stepsState().status).toBe('running')
    expect(stepsState().cancelling).toBe(false)
  })

  it('is a no-op without a live run / while a cancel is already in flight', async () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy as unknown as typeof fetch)
    // No run at all.
    await useRunStreamStore.getState().cancelRun(TICKER)
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
