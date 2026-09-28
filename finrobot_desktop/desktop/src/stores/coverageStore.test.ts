import { describe, it, expect, beforeEach } from 'vitest'
import { useCoverageStore } from './coverageStore'

function reset() {
  useCoverageStore.setState({
    selectedGroupId: null,
    density: 'comfort',
  })
}

describe('coverageStore', () => {
  beforeEach(reset)

  it('stores the selected group id', () => {
    useCoverageStore.getState().setSelectedGroup('cov_1')
    expect(useCoverageStore.getState().selectedGroupId).toBe('cov_1')
  })

  it('setDensity flips comfort / compact', () => {
    expect(useCoverageStore.getState().density).toBe('comfort')
    useCoverageStore.getState().setDensity('compact')
    expect(useCoverageStore.getState().density).toBe('compact')
  })
})
