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

describe('trackExistingRun — Coverage batch runs (no re-POST)', () => {
  it('attaches the SSE stream for an already-created run id', () => {
    // The Coverage batch endpoint creates the run and returns its id; tracking
    // it must open /api/runs/:id/events WITHOUT a second POST. Regression: cards
    // launched from Coverage stalled because no SSE was ever opened.
    useRunStreamStore.getState().trackExistingRun('run-cov-9', TICKER, 'research')

    const es = FakeEventSource.instances.at(-1)
    expect(es).toBeTruthy()
    expect(es!.url).toContain('/api/runs/run-cov-9/events')
    expect(stepsState().status).toBe('running')
    expect(stepsState().runId).toBe('run-cov-9')
  })

  it('completion flows through to the store so the desk can refresh', () => {
    useRunStreamStore.getState().trackExistingRun('run-cov-9', TICKER, 'dcf')
    const es = FakeEventSource.instances.at(-1)!
    es.emit('run.completed', { run_id: 'run-cov-9', ticker: TICKER, artifact_id: 'art_x' })

    expect(stepsState().status).toBe('completed')
    expect(stepsState().artifactId).toBe('art_x')
  })
})

describe('trackBatchRuns — aggregated SSE for Coverage batch (BUG-031)', () => {
  const batch = [
    { runId: 'run-a', ticker: 'AAPL' },
    { runId: 'run-b', ticker: 'MSFT' },
    { runId: 'run-c', ticker: 'NVDA' },
  ]

  function getRun(ticker: string) {
    return useRunStreamStore.getState().runs[ticker]
  }

  afterEach(() => {
    for (const { ticker } of batch) useRunStreamStore.getState().clear(ticker)
  })

  it('opens exactly ONE EventSource for the whole batch (not one per run)', () => {
    FakeEventSource.instances = []
    useRunStreamStore.getState().trackBatchRuns(batch, 'research')

    expect(FakeEventSource.instances).toHaveLength(1)
    const es = FakeEventSource.instances[0]
    // The aggregated route carries all ids as a comma-separated query param.
    expect(es.url).toContain('/api/runs/events?ids=')
    expect(decodeURIComponent(es.url)).toContain('run-a,run-b,run-c')
    // Every ticker is seeded 'running' so all cards paint at once.
    for (const { ticker } of batch) expect(getRun(ticker).status).toBe('running')
  })

  it('routes a tagged frame to the right ticker via its reducer', () => {
    FakeEventSource.instances = []
    useRunStreamStore.getState().trackBatchRuns(batch, 'dcf')
    const es = FakeEventSource.instances[0]

    // Aggregated frame shape: { run_id, ticker, event: <inner event> }.
    es.emit('run.started', {
      run_id: 'run-b',
      ticker: 'MSFT',
      event: { event: 'run.started', total_steps: 3 },
    })
    es.emit('step.completed', {
      run_id: 'run-b',
      ticker: 'MSFT',
      event: { event: 'step.completed', step: 1, total: 3, name: 'data_collection', duration_s: 2 },
    })

    // MSFT advanced; the others are untouched.
    expect(getRun('MSFT').steps[0].name).toBe('data_collection')
    expect(getRun('MSFT').steps[0].status).toBe('completed')
    expect(getRun('AAPL').steps).toHaveLength(0)
  })

  it('closes the single connection only after EVERY run is terminal', () => {
    FakeEventSource.instances = []
    useRunStreamStore.getState().trackBatchRuns(batch, 'research')
    const es = FakeEventSource.instances[0]

    const complete = (runId: string, ticker: string) =>
      es.emit('run.completed', {
        run_id: runId,
        ticker,
        event: { event: 'run.completed', run_id: runId, ticker, artifact_id: `art_${ticker}` },
      })

    complete('run-a', 'AAPL')
    complete('run-b', 'MSFT')
    // Two of three done — the shared stream must stay open for NVDA.
    expect(es.closed).toBe(false)
    expect(getRun('AAPL').status).toBe('completed')

    complete('run-c', 'NVDA')
    // All terminal now — the aggregated connection is torn down.
    expect(es.closed).toBe(true)
    expect(getRun('NVDA').artifactId).toBe('art_NVDA')
  })

  it('closeBatchStream() tears down the connection (unmount teardown)', () => {
    FakeEventSource.instances = []
    useRunStreamStore.getState().trackBatchRuns(batch, 'research')
    const es = FakeEventSource.instances[0]

    expect(es.closed).toBe(false)
    useRunStreamStore.getState().closeBatchStream()
    expect(es.closed).toBe(true)
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
        },
      },
    }))
    useRunStreamStore.getState().clear(TICKER)
    // clear dropped run-clear from the dedupe Set — it can notify once more.
    expect(useRunStreamStore.getState().markTerminalNotified('run-clear')).toBe(true)
  })
})
