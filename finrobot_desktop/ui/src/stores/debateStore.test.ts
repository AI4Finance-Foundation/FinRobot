import { describe, it, expect, beforeEach } from 'vitest'
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
