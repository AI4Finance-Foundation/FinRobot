import { describe, it, expect, beforeEach } from 'vitest'
import { useCoverageStore } from './coverageStore'

function reset() {
  useCoverageStore.setState({
    selectedGroupId: null,
    selectedTickers: [],
    focusedTicker: null,
    sortByGroup: {},
    density: 'comfort',
  })
}

describe('coverageStore', () => {
  beforeEach(reset)

  it('selecting a group clears BOTH the selection and the inspector focus', () => {
    useCoverageStore.getState().setSelected(['AAPL', 'MSFT'])
    useCoverageStore.getState().setFocusedTicker('AAPL')
    useCoverageStore.getState().setSelectedGroup('cov_1')
    expect(useCoverageStore.getState().selectedGroupId).toBe('cov_1')
    expect(useCoverageStore.getState().selectedTickers).toEqual([])
    expect(useCoverageStore.getState().focusedTicker).toBeNull()
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

  it('focus and selection are independent — focusing never selects', () => {
    useCoverageStore.getState().setSelected(['AAPL'])
    useCoverageStore.getState().setFocusedTicker('MSFT')
    expect(useCoverageStore.getState().focusedTicker).toBe('MSFT')
    expect(useCoverageStore.getState().selectedTickers).toEqual(['AAPL'])
    // …and toggling selection leaves focus put.
    useCoverageStore.getState().toggleTicker('NVDA')
    expect(useCoverageStore.getState().focusedTicker).toBe('MSFT')
  })

  it('clearSelection empties selection but keeps the group and focus', () => {
    useCoverageStore.getState().setSelectedGroup('cov_1')
    useCoverageStore.getState().setSelected(['AAPL'])
    useCoverageStore.getState().setFocusedTicker('AAPL')
    useCoverageStore.getState().clearSelection()
    expect(useCoverageStore.getState().selectedTickers).toEqual([])
    expect(useCoverageStore.getState().selectedGroupId).toBe('cov_1')
    expect(useCoverageStore.getState().focusedTicker).toBe('AAPL')
  })

  it('setSort stores per group; null clears it', () => {
    useCoverageStore.getState().setSort('cov_1', { key: 'pe', dir: 'desc' })
    expect(useCoverageStore.getState().sortByGroup['cov_1']).toEqual({ key: 'pe', dir: 'desc' })
    useCoverageStore.getState().setSort('cov_1', null)
    expect(useCoverageStore.getState().sortByGroup['cov_1']).toBeUndefined()
  })

  it('setDensity flips comfort / compact', () => {
    expect(useCoverageStore.getState().density).toBe('comfort')
    useCoverageStore.getState().setDensity('compact')
    expect(useCoverageStore.getState().density).toBe('compact')
  })
})
