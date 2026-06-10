import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { useDebateStore, selectDebate, type DebateState } from './debateStore'

// Regression lock for the (ticker, artifact) composite key. A debate's evidence
// is extracted from a SPECIFIC artifact's structured outputs, so the same ticker
// with two different reports must yield two independent debates. Keying by ticker
// alone made report B silently render report A's verdict and evidence.

function seed(partial: Partial<DebateState>): DebateState {
  return {
    runId: 'run_x',
    artifactId: null,
    evidence: {},
    current_price: null,
    reliable: true,
    bull: [],
    bear: [],
    verdict: null,
    status: 'completed',
    error: null,
    ...partial,
  }
}

describe('debateStore composite key', () => {
  beforeEach(() => {
    useDebateStore.setState({ debates: {} })
  })

  it('keeps debates for the same ticker but different artifacts independent', () => {
    const debateA = seed({
      artifactId: 'art_a',
      verdict: { call: 'BUY', conviction: 8, swing_factor: 'a', change_my_mind: 'a' },
    })
    const debateB = seed({
      artifactId: 'art_b',
      verdict: { call: 'SELL', conviction: 3, swing_factor: 'b', change_my_mind: 'b' },
    })
    useDebateStore.setState({
      debates: { 'AAPL::art_a': debateA, 'AAPL::art_b': debateB },
    })

    const state = useDebateStore.getState()
    // Report B must surface B's own verdict, never A's.
    expect(selectDebate('AAPL', 'art_a')(state)?.verdict?.call).toBe('BUY')
    expect(selectDebate('AAPL', 'art_b')(state)?.verdict?.call).toBe('SELL')
  })

  it('returns null for an unknown artifact even when the ticker has a debate', () => {
    useDebateStore.setState({ debates: { 'AAPL::art_a': seed({ artifactId: 'art_a' }) } })
    const state = useDebateStore.getState()
    expect(selectDebate('AAPL', 'art_unknown')(state)).toBeNull()
  })

  it('returns null when artifactId is null (no debate can exist yet)', () => {
    useDebateStore.setState({ debates: { 'AAPL::art_a': seed({ artifactId: 'art_a' }) } })
    expect(selectDebate('AAPL', null)(useDebateStore.getState())).toBeNull()
  })

  it('reset removes only the targeted (ticker, artifact), leaving siblings intact', () => {
    useDebateStore.setState({
      debates: {
        'AAPL::art_a': seed({ artifactId: 'art_a' }),
        'AAPL::art_b': seed({ artifactId: 'art_b' }),
      },
    })

    useDebateStore.getState().reset('AAPL', 'art_a')

    const state = useDebateStore.getState()
    expect(selectDebate('AAPL', 'art_a')(state)).toBeNull()
    expect(selectDebate('AAPL', 'art_b')(state)).not.toBeNull()
  })
})

// ── SSE error counting (BUG-044) ─────────────────────────────────────────────
//
// jsdom has no EventSource — install a controllable fake (mirrors
// runStreamStore.test.ts) that lets the test alternate named events with
// connection errors. The regression locked here: a flapping connection
// ([error, event, error, event…]) must still trip SSE_ERROR_LIMIT — resetting
// the counter on ANY successful event let it evade the limit forever.

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

  emit(type: string, data: Record<string, unknown>): void {
    const fn = this.listeners.get(type)
    if (fn) fn({ data: JSON.stringify(data) } as MessageEvent)
  }

  triggerError(): void {
    this.onerror?.()
  }
}

const SSE_ERROR_LIMIT = 8
const POINT = {
  event: 'debate.point',
  run_id: 'run-d-1',
  side: 'bull',
  claim: 'margin expands',
  evidence_ids: [],
  verified: true,
  reason: '',
}

async function startDebateWithFakeSse(): Promise<FakeEventSource> {
  await useDebateStore.getState().startDebate('AAPL', 'art_sse')
  const es = FakeEventSource.instances.at(-1)
  if (!es) throw new Error('no EventSource was created')
  return es
}

function debateStatus(): string | undefined {
  return selectDebate('AAPL', 'art_sse')(useDebateStore.getState())?.status
}

describe('SSE error counting (BUG-044)', () => {
  beforeEach(() => {
    useDebateStore.setState({ debates: {} })
    FakeEventSource.instances = []
    vi.stubGlobal('EventSource', FakeEventSource as unknown as typeof EventSource)
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        json: async () => ({ run_id: 'run-d-1' }),
      })) as unknown as typeof fetch,
    )
  })

  afterEach(() => {
    useDebateStore.getState().reset('AAPL', 'art_sse')
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('an [error, event, error, event…] flapping connection still trips the limit', async () => {
    const es = await startDebateWithFakeSse()
    for (let i = 0; i < SSE_ERROR_LIMIT; i++) {
      expect(debateStatus()).toBe('running')
      es.triggerError()
      es.emit('debate.point', POINT)
    }
    expect(debateStatus()).toBe('failed')
    expect(es.closed).toBe(true)
  })

  it('consecutive errors with no events fail at the limit (baseline preserved)', async () => {
    const es = await startDebateWithFakeSse()
    for (let i = 0; i < SSE_ERROR_LIMIT; i++) {
      es.triggerError()
    }
    expect(debateStatus()).toBe('failed')
    expect(es.closed).toBe(true)
  })

  it('a genuinely recovered stream (stable successes) forgives past errors', async () => {
    const es = await startDebateWithFakeSse()
    // 7 errors — one short of the limit.
    for (let i = 0; i < SSE_ERROR_LIMIT - 1; i++) es.triggerError()
    expect(debateStatus()).toBe('running')
    // Stream stabilises: enough consecutive successes to forgive the past.
    for (let i = 0; i < 3; i++) es.emit('debate.point', POINT)
    // A fresh burst below the limit must NOT fail (counter was forgiven)…
    for (let i = 0; i < SSE_ERROR_LIMIT - 1; i++) es.triggerError()
    expect(debateStatus()).toBe('running')
    // …but the counter is still live: one more error reaches the limit.
    es.triggerError()
    expect(debateStatus()).toBe('failed')
  })
})
