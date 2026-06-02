import { describe, it, expect, beforeEach } from 'vitest'
import { useCoverageStore } from './coverageStore'

function reset() {
  useCoverageStore.setState({ selectedGroupId: null, selectedTickers: [] })
}

describe('coverageStore', () => {
  beforeEach(reset)

  it('selecting a group clears the ticker selection', () => {
    useCoverageStore.getState().setSelected(['AAPL', 'MSFT'])
    useCoverageStore.getState().setSelectedGroup('cov_1')
    expect(useCoverageStore.getState().selectedGroupId).toBe('cov_1')
    expect(useCoverageStore.getState().selectedTickers).toEqual([])
  })

  it('toggleTicker adds then removes', () => {
    const { toggleTicker } = useCoverageStore.getState()
    toggleTicker('AAPL')
    expect(useCoverageStore.getState().selectedTickers).toEqual(['AAPL'])
    toggleTicker('MSFT')
    expect(useCoverageStore.getState().selectedTickers).toEqual(['AAPL', 'MSFT'])
    toggleTicker('AAPL')
    expect(useCoverageStore.getState().selectedTickers).toEqual(['MSFT'])
  })

  it('setSelected dedupes', () => {
    useCoverageStore.getState().setSelected(['AAPL', 'AAPL', 'MSFT'])
    expect(useCoverageStore.getState().selectedTickers).toEqual(['AAPL', 'MSFT'])
  })

  it('clearSelection empties selection but keeps the group', () => {
    useCoverageStore.getState().setSelectedGroup('cov_1')
    useCoverageStore.getState().setSelected(['AAPL'])
    useCoverageStore.getState().clearSelection()
    expect(useCoverageStore.getState().selectedTickers).toEqual([])
    expect(useCoverageStore.getState().selectedGroupId).toBe('cov_1')
  })
})
