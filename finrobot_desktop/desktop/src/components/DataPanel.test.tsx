import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import DataPanel, { DataCard } from './DataPanel'

describe('DataPanel', () => {
  it('renders title and children', () => {
    render(<DataPanel title="Charts"><div>Chart Here</div></DataPanel>)
    expect(screen.getByText('Charts')).toBeInTheDocument()
    expect(screen.getByText('Chart Here')).toBeInTheDocument()
  })
})

describe('DataCard', () => {
  it('renders with title', () => {
    render(<DataCard title="Revenue"><span>$100B</span></DataCard>)
    expect(screen.getByText('Revenue')).toBeInTheDocument()
    expect(screen.getByText('$100B')).toBeInTheDocument()
  })
})
