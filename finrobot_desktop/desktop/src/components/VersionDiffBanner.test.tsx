import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClientProvider, QueryClient } from '@tanstack/react-query'
import { VersionDiffBanner } from './VersionDiffBanner'
import type { ArtifactSummaryV5 } from '../types/v5'

vi.mock('../api/client', () => ({ BASE_URL: 'http://test' }))

function summary(id: string, created_at: string, verdict?: string): ArtifactSummaryV5 {
  return {
    id,
    ticker: 'AAPL',
    cross_tickers: [],
    type: 'equity_research',
    created_at,
    headline: id,
    source: 'pipeline:equity_research',
    archived: false,
    verdict: verdict ?? null,
  } as ArtifactSummaryV5
}

const DELTA = {
  a_id: 'art_old',
  b_id: 'art_cur',
  a_label: 'v1',
  b_label: 'v2',
  report_type: 'equity_research',
  identical: false,
  material_change: true,
  conclusion: [
    {
      key: 'target_price',
      label_zh: '目标价',
      label_en: 'Target price',
      old_value: 195,
      new_value: 180,
      formatted_old: '$195.00',
      formatted_new: '$180.00',
      pct_change: -0.077,
      formatted_pct_change: '-7.7%',
      direction: 'down',
      sentiment: 'negative',
      comparable: true,
      caliber_note: null,
      is_user_override: false,
      contribution: null,
      formatted_contribution: null,
    },
  ],
  attribution: {
    available: true,
    disabled_reason: null,
    items: [],
    total_change: -15,
    formatted_total: '-$15.00',
    residual: 0,
    formatted_residual: '$0.00',
    summary_zh: '目标价下调主因 WACC 上升',
    summary_en: 'Target cut, mainly WACC',
  },
  drivers: [],
  comparability: [],
  data_footnote: {
    a_source: 'yfinance',
    b_source: 'yfinance',
    a_fetched_at: '2026-05-01T00:00:00Z',
    b_fetched_at: '2026-05-10T00:00:00Z',
    currency: 'USD',
    currency_assumed: true,
  },
}

function renderBanner(props: {
  parentArtifactId?: string | null
  timeline: ArtifactSummaryV5[]
  currentTargetRange?: { low: number | null; high: number | null; currency: string } | null
  currentTargetWithheld?: boolean
}) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <VersionDiffBanner
        currentId="art_cur"
        currentCreatedAt="2026-05-10T00:00:00Z"
        reportType="equity_research"
        parentArtifactId={props.parentArtifactId ?? null}
        timeline={props.timeline}
        currentTargetRange={props.currentTargetRange}
        currentTargetWithheld={props.currentTargetWithheld}
      />
    </QueryClientProvider>,
  )
}

describe('VersionDiffBanner', () => {
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => DELTA })
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('renders nothing when there is no prior same-type version', () => {
    renderBanner({ timeline: [summary('art_cur', '2026-05-10T00:00:00Z')] })
    expect(screen.queryByTestId('version-diff-banner')).toBeNull()
  })

  it('renders the conclusion with backend-formatted values', async () => {
    renderBanner({
      timeline: [
        summary('art_cur', '2026-05-10T00:00:00Z'),
        summary('art_old', '2026-05-01T00:00:00Z', 'HOLD'),
      ],
    })
    expect(screen.getByTestId('version-diff-banner')).toBeInTheDocument()
    // Card is collapsed by default — open it to reveal the conclusion.
    fireEvent.click(screen.getByTestId('version-diff-toggle'))
    await waitFor(() => expect(screen.getByText('$180.00')).toBeInTheDocument())
    // pct badge string comes pre-formatted from the backend, rendered verbatim
    expect(screen.getByText(/-7\.7%/)).toBeInTheDocument()
  })

  it('renders target range instead of a blank target-price diff when the point target is withheld', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ...DELTA,
        conclusion: [
          {
            ...DELTA.conclusion[0],
            old_value: null,
            new_value: null,
            formatted_old: '—',
            formatted_new: '—',
            pct_change: null,
            formatted_pct_change: null,
            direction: 'flat',
            sentiment: 'neutral',
          },
        ],
      }),
    })

    renderBanner({
      timeline: [
        summary('art_cur', '2026-05-10T00:00:00Z'),
        summary('art_old', '2026-05-01T00:00:00Z', 'HOLD'),
      ],
      currentTargetRange: { low: 188.12, high: 1414.52, currency: 'USD' },
      currentTargetWithheld: true,
    })

    fireEvent.click(screen.getByTestId('version-diff-toggle'))
    await waitFor(() => expect(screen.getByTestId('diff-target-range')).toBeInTheDocument())
    expect(screen.getByText('Target range')).toBeInTheDocument()
    expect(screen.getByText(/\$188\.12.*\$1,414\.52/)).toBeInTheDocument()
    expect(screen.getByText('· Point target withheld')).toBeInTheDocument()
    expect(screen.queryByText('Target price')).not.toBeInTheDocument()
  })

  it('renders peer-set comparability flags from the backend', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ...DELTA,
        comparability: [
          {
            kind: 'peer_set',
            message_zh: '同业集合变更：MRVL→TSM；comps_pe 中值变化 -29.5%。',
            message_en: 'Peer set changed: MRVL->TSM; comps_pe mid moved -29.5%.',
            blocks_attribution: false,
          },
        ],
      }),
    })
    renderBanner({
      timeline: [
        summary('art_cur', '2026-05-10T00:00:00Z'),
        summary('art_old', '2026-05-01T00:00:00Z', 'HOLD'),
      ],
    })

    fireEvent.click(screen.getByTestId('version-diff-toggle'))
    await waitFor(() => expect(screen.getByText(/Peer set changed: MRVL->TSM/)).toBeInTheDocument())
  })

  it('renders method-set comparability flags (the real driver of a blended-target move)', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ...DELTA,
        comparability: [
          {
            kind: 'method_set',
            message_zh: '估值方法集变更（新增 EV/EBITDA）：目标价是多方法加权混合……',
            message_en:
              'Valuation method set changed (added EV/EBITDA): the target is a multi-method weighted blend …',
            blocks_attribution: false,
          },
        ],
      }),
    })
    renderBanner({
      timeline: [
        summary('art_cur', '2026-05-10T00:00:00Z'),
        summary('art_old', '2026-05-01T00:00:00Z', 'HOLD'),
      ],
    })

    fireEvent.click(screen.getByTestId('version-diff-toggle'))
    await waitFor(() =>
      expect(screen.getByText(/method set changed \(added EV\/EBITDA\)/i)).toBeInTheDocument(),
    )
  })

  it('shows the "no material change" note for a drift-only re-run', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ ...DELTA, identical: false, material_change: false }),
    })
    renderBanner({
      timeline: [
        summary('art_cur', '2026-05-10T00:00:00Z'),
        summary('art_old', '2026-05-01T00:00:00Z', 'HOLD'),
      ],
    })

    fireEvent.click(screen.getByTestId('version-diff-toggle'))
    await waitFor(() => expect(screen.getByTestId('version-diff-immaterial')).toBeInTheDocument())
    expect(screen.getByText(/No material change/i)).toBeInTheDocument()
  })

  it('hides the "no material change" note when the change is material', async () => {
    // DELTA carries material_change: true (a -7.7% target move).
    renderBanner({
      timeline: [
        summary('art_cur', '2026-05-10T00:00:00Z'),
        summary('art_old', '2026-05-01T00:00:00Z', 'HOLD'),
      ],
    })
    fireEvent.click(screen.getByTestId('version-diff-toggle'))
    await waitFor(() => expect(screen.getByText('$180.00')).toBeInTheDocument())
    expect(screen.queryByTestId('version-diff-immaterial')).not.toBeInTheDocument()
  })

  it('defaults the base to parent_artifact_id when it is among candidates', () => {
    renderBanner({
      parentArtifactId: 'art_parent',
      timeline: [
        summary('art_cur', '2026-05-10T00:00:00Z'),
        summary('art_newer_other', '2026-05-09T00:00:00Z'),
        summary('art_parent', '2026-04-01T00:00:00Z'),
      ],
    })
    fireEvent.click(screen.getByTestId('version-diff-toggle'))
    const select = screen.getByRole('combobox') as HTMLSelectElement
    // Without the parent rule the newest other version would win; parent wins instead.
    expect(select.value).toBe('art_parent')
  })

  it('resets the diff base when navigating to a different artifact (no stale base)', () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    // Report A: current art_a, default base art_a_parent.
    const { rerender } = render(
      <QueryClientProvider client={queryClient}>
        <VersionDiffBanner
          currentId="art_a"
          currentCreatedAt="2026-05-10T00:00:00Z"
          reportType="equity_research"
          parentArtifactId="art_a_parent"
          timeline={[
            summary('art_a', '2026-05-10T00:00:00Z'),
            summary('art_a_parent', '2026-04-01T00:00:00Z'),
          ]}
        />
      </QueryClientProvider>,
    )
    // Card is collapsed by default — open it once; `open` persists across the
    // re-render (same component instance) so the select stays visible for B too.
    fireEvent.click(screen.getByTestId('version-diff-toggle'))
    let select = screen.getByRole('combobox') as HTMLSelectElement
    expect(select.value).toBe('art_a_parent')

    // Navigate to report B (same component position is reused): current art_b,
    // whose only candidate / default base is art_b_parent. The base must follow
    // B, not stay stuck on art_a_parent (which isn't even a B candidate).
    rerender(
      <QueryClientProvider client={queryClient}>
        <VersionDiffBanner
          currentId="art_b"
          currentCreatedAt="2026-05-20T00:00:00Z"
          reportType="equity_research"
          parentArtifactId="art_b_parent"
          timeline={[
            summary('art_b', '2026-05-20T00:00:00Z'),
            summary('art_b_parent', '2026-05-15T00:00:00Z'),
          ]}
        />
      </QueryClientProvider>,
    )
    select = screen.getByRole('combobox') as HTMLSelectElement
    expect(select.value).toBe('art_b_parent')
  })

  it('requests diff with older artifact as base (a) and current as compare (b)', async () => {
    renderBanner({
      timeline: [
        summary('art_cur', '2026-05-10T00:00:00Z'),
        summary('art_old', '2026-05-01T00:00:00Z'),
      ],
    })
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    const url = fetchMock.mock.calls[0][0] as string
    // older (art_old) is base a, current (art_cur) is compare b
    expect(url).toContain('/api/artifacts/art_old/diff/art_cur')
  })
})
