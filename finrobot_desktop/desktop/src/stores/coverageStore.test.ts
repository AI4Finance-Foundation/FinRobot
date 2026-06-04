import { describe, it, expect, beforeEach } from 'vitest'
import { useCoverageStore } from './coverageStore'

function reset() {
  useCoverageStore.setState({
    selectedGroupId: null,
    sortByGroup: {},
    density: 'comfort',
  })
}

describe('coverageStore', () => {
  beforeEach(reset)

  it('stores the selected group id', () => {
    useCoverageStore.getState().setSelectedGroup('cov_1')
    expect(useCoverageStore.getState().selectedGroupId).toBe('cov_1')
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
