import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
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

function renderBanner(props: { parentArtifactId?: string | null; timeline: ArtifactSummaryV5[] }) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <VersionDiffBanner
        currentId="art_cur"
        currentCreatedAt="2026-05-10T00:00:00Z"
        reportType="equity_research"
        parentArtifactId={props.parentArtifactId ?? null}
        timeline={props.timeline}
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
    await waitFor(() => expect(screen.getByText('$180.00')).toBeInTheDocument())
    // pct badge string comes pre-formatted from the backend, rendered verbatim
    expect(screen.getByText(/-7\.7%/)).toBeInTheDocument()
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
    const select = screen.getByRole('combobox') as HTMLSelectElement
    // Without the parent rule the newest other version would win; parent wins instead.
    expect(select.value).toBe('art_parent')
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
