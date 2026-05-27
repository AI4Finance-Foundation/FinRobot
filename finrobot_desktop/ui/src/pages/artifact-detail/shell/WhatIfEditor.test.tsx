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
  initialWacc?: number | null
  initialTg?: number | null
  originalImpliedPrice?: number | null
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <WhatIfEditor
        ticker="AAPL"
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
        inputs: { wacc: 0.1, terminal_growth_rate: 0.025 },
        result: { implied_price: 210.42, wacc: 0.1 },
        current_price: 175,
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
