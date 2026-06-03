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
