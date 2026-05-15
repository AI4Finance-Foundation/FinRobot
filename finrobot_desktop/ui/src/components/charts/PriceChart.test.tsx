import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import PriceChart from './PriceChart'

// appStore reads ticker from zustand — provide an empty string so PriceChart
// knows not to self-fetch (enabled: !!ticker && !data)
vi.mock('../../stores/appStore', () => ({
  useAppStore: () => '',
}))

// Wrap renders in a QueryClientProvider (PriceChart uses useQuery internally)
function withQuery(ui: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>)
}

// Dates within the last year (relative to test run) so 1Y filter doesn't strip them
const today = new Date()
function daysAgo(n: number): string {
  const d = new Date(today)
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

const SAMPLE_DATA = [
  { date: daysAgo(90), close: 185.5, volume: 45_000_000 },
  { date: daysAgo(60), close: 187.2, volume: 38_000_000 },
  { date: daysAgo(30), close: 184.8, volume: 42_000_000 },
]

describe('PriceChart', () => {
  it('renders title', () => {
    withQuery(<PriceChart data={SAMPLE_DATA} title="Price & Volume" />)
    expect(screen.getByText('Price & Volume')).toBeInTheDocument()
  })

  it('returns null for empty data', () => {
    const { container } = withQuery(<PriceChart data={[]} title="Empty" />)
    expect(container.firstChild).toBeNull()
  })

  it('renders all five time range buttons', () => {
    withQuery(<PriceChart data={SAMPLE_DATA} title="Price History" />)
    for (const label of ['1M', '3M', '6M', '1Y', 'ALL']) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('defaults to 1Y active', () => {
    withQuery(<PriceChart data={SAMPLE_DATA} title="Price History" />)
    const btn = screen.getByText('1Y').closest('button')
    expect(btn?.className).toContain('active')
  })

  it('switches active button on click', () => {
    withQuery(<PriceChart data={SAMPLE_DATA} title="Price History" />)
    const btn3M = screen.getByText('3M').closest('button')!
    fireEvent.click(btn3M)
    expect(btn3M.className).toContain('active')
    const btn1Y = screen.getByText('1Y').closest('button')!
    expect(btn1Y.className).not.toContain('active')
  })

  it('renders chart title as SPAN', () => {
    withQuery(<PriceChart data={SAMPLE_DATA} title="Price & Volume" />)
    const heading = screen.getByText('Price & Volume')
    expect(heading.tagName).toBe('SPAN')
  })
})
