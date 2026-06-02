import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { QueryClientProvider, QueryClient } from '@tanstack/react-query'
import { WhatIfEditor } from './ReportRightRail'

vi.mock('../../../api/client', () => ({ BASE_URL: 'http://test' }))

// Real timers — @testing-library/react's waitFor polls with real setInterval,
// which deadlocks under vi.useFakeTimers. The debounce is 380ms so each test
// just waits a bit longer than that.
const DEBOUNCE_MS = 500

function renderEditor(props?: {
  artifactId?: string
  initialWacc?: number | null
  initialTg?: number | null
  originalImpliedPrice?: number | null
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  // key={artifactId} mirrors how ReportRightRail mounts the editor — switching
  // artifact remounts with fresh initial values (BUG-007).
  const artifactId = props?.artifactId ?? 'art_AAPL_eq'
  return render(
    <QueryClientProvider client={queryClient}>
      <WhatIfEditor
        key={artifactId}
        artifactId={artifactId}
        initialWacc={props?.initialWacc ?? 0.09}
        initialTg={props?.initialTg ?? 0.025}
        originalImpliedPrice={props?.originalImpliedPrice ?? 180.5}
      />
    </QueryClientProvider>,
  )
}

describe('WhatIfEditor', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        artifact_id: 'art_AAPL_eq',
        inputs: { wacc: 0.1, terminal_growth_rate: 0.025 },
        result: { implied_price: 210.42, wacc: 0.1 },
        base_implied_price: 180.5,
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders three sliders: WACC, Terminal Growth, Revenue Growth Scale', () => {
    renderEditor()
    expect(screen.getByTestId('whatif-slider-wacc')).toBeInTheDocument()
    expect(screen.getByTestId('whatif-slider-tg')).toBeInTheDocument()
    expect(screen.getByTestId('whatif-slider-growth')).toBeInTheDocument()
  })

  it('shows BASE price from props on initial render', () => {
    renderEditor({ originalImpliedPrice: 180.5 })
    expect(screen.getByTestId('whatif-base-price')).toHaveTextContent('$180.50')
  })

  it('starts with no NEW price until a slider moves', () => {
    renderEditor()
    expect(screen.getByTestId('whatif-new-price')).toHaveTextContent('—')
  })

  it('does not show reset button when all sliders at baseline', () => {
    renderEditor()
    expect(screen.queryByTestId('whatif-reset')).not.toBeInTheDocument()
  })

  it('replays the FROZEN artifact via the what-if endpoint, NOT the live dcf-seed reseed', async () => {
    renderEditor({ artifactId: 'art_2026_AAPL_equity_research', initialWacc: 0.09 })
    fireEvent.change(screen.getByTestId('whatif-slider-wacc'), { target: { value: '12.5' } })

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1), { timeout: DEBOUNCE_MS + 500 })
    const url = fetchMock.mock.calls[0][0] as string
    // Must hit the artifact-replay endpoint with the current artifact id …
    expect(url).toBe('http://test/api/compute/artifacts/art_2026_AAPL_equity_research/what-if/dcf')
    // … and MUST NOT hit the live reseed path that re-fetches financials/price.
    expect(url).not.toContain('/dcf-seed')
    // Body carries only slider overrides — no ticker, no live-data hints.
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect(body).not.toHaveProperty('ticker')
    expect(body.wacc_override).toBeCloseTo(0.125)
  })

  it('sends growth_scale_override=null when only WACC is dirty', async () => {
    renderEditor({ initialWacc: 0.09, initialTg: 0.025 })
    const waccSlider = screen.getByTestId('whatif-slider-wacc') as HTMLInputElement
    fireEvent.change(waccSlider, { target: { value: '12.5' } })

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1), { timeout: DEBOUNCE_MS + 500 })
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect(body.wacc_override).toBeCloseTo(0.125)
    expect(body.tg_override).toBeCloseTo(0.025)
    expect(body.growth_scale_override).toBeNull()
  })

  it('sends growth_scale_override as fraction when growth slider moves', async () => {
    renderEditor()
    const growthSlider = screen.getByTestId('whatif-slider-growth') as HTMLInputElement
    fireEvent.change(growthSlider, { target: { value: '20' } })

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1), { timeout: DEBOUNCE_MS + 500 })
    const body = JSON.parse(fetchMock.mock.calls[0][1].body as string)
    expect(body.growth_scale_override).toBeCloseTo(0.2)
  })

  it('shows reset button once any slider is dirty', () => {
    renderEditor()
    const growthSlider = screen.getByTestId('whatif-slider-growth') as HTMLInputElement
    fireEvent.change(growthSlider, { target: { value: '25' } })
    expect(screen.getByTestId('whatif-reset')).toBeInTheDocument()
  })

  it('renders side-by-side BASE → NEW after a successful recompute', async () => {
    renderEditor({ originalImpliedPrice: 180.5 })
    fireEvent.change(screen.getByTestId('whatif-slider-growth'), { target: { value: '15' } })

    await waitFor(
      () => expect(screen.getByTestId('whatif-new-price')).toHaveTextContent('$210.42'),
      { timeout: DEBOUNCE_MS + 1000 },
    )
    expect(screen.getByTestId('whatif-base-price')).toHaveTextContent('$180.50')
    expect(screen.getByTestId('whatif-delta')).toHaveTextContent('+16.6%')
  })

  it('reset restores all three sliders to baseline and clears dirty state', async () => {
    renderEditor({ initialWacc: 0.09, initialTg: 0.025 })
    fireEvent.change(screen.getByTestId('whatif-slider-growth'), { target: { value: '30' } })
    fireEvent.change(screen.getByTestId('whatif-slider-wacc'), { target: { value: '14' } })
    await waitFor(
      () => expect(screen.getByTestId('whatif-new-price')).toHaveTextContent('$210.42'),
      { timeout: DEBOUNCE_MS + 1000 },
    )

    fireEvent.click(screen.getByTestId('whatif-reset'))

    expect((screen.getByTestId('whatif-slider-growth') as HTMLInputElement).value).toBe('0')
    expect((screen.getByTestId('whatif-slider-wacc') as HTMLInputElement).value).toBe('9')
    expect(screen.queryByTestId('whatif-reset')).not.toBeInTheDocument()
  })

  it('resets sliders to the new artifact base when the report version changes (BUG-007)', () => {
    // Report A: WACC 9%, TG 2.5%.
    const { rerender } = renderEditor({
      artifactId: 'art_A',
      initialWacc: 0.09,
      initialTg: 0.025,
    })
    // Drag report A's WACC to 14% — leaves the editor dirty.
    fireEvent.change(screen.getByTestId('whatif-slider-wacc'), { target: { value: '14' } })
    expect((screen.getByTestId('whatif-slider-wacc') as HTMLInputElement).value).toBe('14')
    expect(screen.getByTestId('whatif-reset')).toBeInTheDocument()

    // Switch to report B (WACC 11%, TG 3%) — the key change remounts the editor,
    // so the sliders must show B's frozen assumptions, not A's dragged 14%.
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    })
    rerender(
      <QueryClientProvider client={queryClient}>
        <WhatIfEditor
          key="art_B"
          artifactId="art_B"
          initialWacc={0.11}
          initialTg={0.03}
          originalImpliedPrice={205}
        />
      </QueryClientProvider>,
    )

    expect((screen.getByTestId('whatif-slider-wacc') as HTMLInputElement).value).toBe('11')
    expect((screen.getByTestId('whatif-slider-tg') as HTMLInputElement).value).toBe('3')
    // Fresh base ⇒ not dirty ⇒ no reset button.
    expect(screen.queryByTestId('whatif-reset')).not.toBeInTheDocument()
    expect(screen.getByTestId('whatif-base-price')).toHaveTextContent('$205.00')
  })

  it('surfaces error UI on failed fetch', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: false,
      status: 422,
      text: async () => 'validation error',
    })
    renderEditor()
    fireEvent.change(screen.getByTestId('whatif-slider-growth'), { target: { value: '40' } })

    await waitFor(() => expect(screen.getByTestId('whatif-error')).toBeInTheDocument(), {
      timeout: DEBOUNCE_MS + 1000,
    })
  })
})
