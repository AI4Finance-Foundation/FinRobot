import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import Layout from './Layout'

describe('Layout', () => {
  it('renders left panel content', () => {
    render(<Layout leftPanel={<div>Left Content</div>} rightPanel={null} />)
    expect(screen.getByText('Left Content')).toBeInTheDocument()
  })

  it('renders right panel when provided', () => {
    render(
      <Layout leftPanel={<div>Left</div>} rightPanel={<div>Right Content</div>} />
    )
    expect(screen.getByText('Right Content')).toBeInTheDocument()
  })

  it('hides right panel when null', () => {
    const { container } = render(<Layout leftPanel={<div>Left</div>} rightPanel={null} />)
    // Should only have one panel child in the flex container
    const panels = container.querySelectorAll('.flex-1.overflow-y-auto')
    expect(panels).toHaveLength(1)
  })

  it('shows progress bar when progress > 0', () => {
    render(
      <Layout leftPanel={<div>x</div>} rightPanel={null} progress={0.6} progressLabel="Step 3/5" />
    )
    expect(screen.getByText('Step 3/5')).toBeInTheDocument()
  })
})
