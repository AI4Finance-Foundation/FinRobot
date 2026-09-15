import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'

// Recharts' ResponsiveContainer renders nothing in jsdom (zero measured size),
// so the radar polygons never reach the DOM — the title is the only real node
// (see the title-only tests below). To guard the TARGET-vs-peer visual emphasis
// we instead capture each <Radar>'s props via a light recharts mock and assert
// the subject series outranks the benchmark on stroke + fill. The mock keeps the
// other primitives as inert passthroughs so the component still renders.
// vi.mock is hoisted above imports, so the captured array must be hoisted too
// (vi.hoisted) for the factory to reference it.
const { radarProps } = vi.hoisted(() => ({
  radarProps: [] as Array<Record<string, unknown>>,
}))
vi.mock('recharts', () => {
  const Passthrough = ({ children }: { children?: ReactNode }) => <div>{children}</div>
  return {
    ResponsiveContainer: Passthrough,
    RadarChart: Passthrough,
    PolarGrid: () => null,
    PolarAngleAxis: () => null,
    PolarRadiusAxis: () => null,
    Legend: () => null,
    Tooltip: () => null,
    Radar: (props: Record<string, unknown>) => {
      radarProps.push(props)
      return null
    },
  }
})

import CompanyRadarChart from './CompanyRadarChart'

const num = (v: unknown): number => (typeof v === 'number' ? v : Number(v))

const SAMPLE_DATA = [
  { dimension: 'Growth', value: 85, benchmark: 70 },
  { dimension: 'Profitability', value: 72, benchmark: 65 },
  { dimension: 'Leverage', value: 60, benchmark: 55 },
  { dimension: 'Liquidity', value: 90, benchmark: 80 },
  { dimension: 'Valuation', value: 55, benchmark: 60 },
]

describe('CompanyRadarChart', () => {
  it('renders title', () => {
    render(<CompanyRadarChart data={SAMPLE_DATA} title="Company Radar" />)
    expect(screen.getByText('Company Radar')).toBeInTheDocument()
  })

  it('returns null for empty data', () => {
    const { container } = render(<CompanyRadarChart data={[]} title="Empty" />)
    expect(container.firstChild).toBeNull()
  })

  it('returns null for undefined data', () => {
    const { container } = render(
      <CompanyRadarChart
        data={undefined as unknown as Record<string, number | string | boolean | null>[]}
        title="Null"
      />,
    )
    expect(container.firstChild).toBeNull()
  })

  it('renders heading element', () => {
    render(<CompanyRadarChart data={SAMPLE_DATA} title="Company Radar" />)
    const heading = screen.getByText('Company Radar')
    expect(heading.tagName).toBe('SPAN')
  })

  it('emphasizes the target (value) series over the peer-median (benchmark) series', () => {
    radarProps.length = 0
    render(<CompanyRadarChart data={SAMPLE_DATA} title="Company Radar" />)

    const target = radarProps.find((p) => p.dataKey === 'value')
    const benchmark = radarProps.find((p) => p.dataKey === 'benchmark')
    expect(target).toBeDefined()
    expect(benchmark).toBeDefined()

    // The TARGET (subject) reads first: thicker stroke + denser fill than the
    // peer-median ring. compsResultToRadarData maps the target company → `value`,
    // so `value` is the hero; `benchmark` is the median pinned at 100.
    expect(num(target!.strokeWidth)).toBeGreaterThan(num(benchmark!.strokeWidth))
    expect(num(target!.fillOpacity)).toBeGreaterThan(num(benchmark!.fillOpacity))
    // The peer-median ring is demoted to a thin dashed reference outline.
    expect(benchmark!.strokeDasharray).toBeTruthy()
    // The hero is painted last so the median fill never occludes it.
    const targetIdx = radarProps.indexOf(target!)
    const benchmarkIdx = radarProps.indexOf(benchmark!)
    expect(targetIdx).toBeGreaterThan(benchmarkIdx)
  })
})
