import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// BUG-014: the artifact id is the real identity; the URL ticker is only
// routing context. Visiting /stocks/AAPL/runs/<NVDA-artifact-id> must
// canonicalize to /stocks/NVDA/runs/<id> so no AAPL chrome wraps NVDA chapters.

const navigateSpy = vi.fn()
const params = { ticker: 'AAPL', artifactId: 'art-nvda-1' }

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>()
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => params,
    useLocation: () => ({
      pathname: '/stocks/AAPL/runs/art-nvda-1',
      hash: '',
      search: '',
      state: null,
      key: 'x',
    }),
  }
})

const detail = {
  data: undefined as unknown,
  isLoading: false,
  isError: false,
  error: null as unknown,
}

vi.mock('../hooks/useV5Artifacts', () => ({
  useArtifactDetail: () => detail,
  useV5ArtifactTimeline: () => ({ data: [] }),
}))

// i18n + heavy shell/chapter children are irrelevant to the redirect logic.
vi.mock('../i18n', () => ({ useI18n: () => ({ locale: 'en', t: (k: string) => k }) }))
vi.mock('../stores/navMemoryStore', () => ({
  useNavMemoryStore: (sel: (s: { setLastStocksPath: () => void }) => unknown) =>
    sel({ setLastStocksPath: () => {} }),
}))
vi.mock('../stores/toastStore', () => ({
  useToastStore: (sel: (s: { addToast: () => void }) => unknown) => sel({ addToast: () => {} }),
}))
vi.mock('../api/client', () => ({ markArtifactViewed: vi.fn().mockResolvedValue(undefined) }))
vi.mock('../api/queryClient', () => ({ queryClient: { invalidateQueries: vi.fn() } }))
vi.mock('./artifact-detail/reportData', () => ({
  deriveReportData: () => ({ thesis: null, dcf: null, createdAt: null, versionLabel: 'v1' }),
}))
vi.mock('../components/VersionDiffBanner', () => ({ VersionDiffBanner: () => null }))
// Render identifiable sentinels (not null) so the type-branch test can assert
// which chrome / body actually mounts for equity_research vs a dcf artifact.
vi.mock('./artifact-detail/shell/ReportToolbar', () => ({
  ReportToolbar: () => <div data-testid="mock-toolbar" />,
}))
vi.mock('./artifact-detail/shell/ReportTOC', () => ({
  ReportTOC: () => <div data-testid="mock-toc" />,
}))
vi.mock('./artifact-detail/shell/ReportRightRail', () => ({
  ReportRightRail: () => <div data-testid="mock-right-rail" />,
}))
vi.mock('./artifact-detail/shell/ReportStatusBar', () => ({
  ReportStatusBar: () => <div data-testid="mock-status-bar" />,
}))
vi.mock('./artifact-detail/ReportChapters', () => ({
  ReportChapters: () => <div data-testid="mock-report-chapters" />,
}))
vi.mock('./artifact-detail/chapters/labels', () => ({ allChapterLabels: () => [] }))

import { ArtifactDetailPage } from './ArtifactDetailPage'

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <ArtifactDetailPage />
    </QueryClientProvider>,
  )
}

describe('ArtifactDetailPage ticker canonicalization (BUG-014)', () => {
  beforeEach(() => {
    navigateSpy.mockClear()
    params.ticker = 'AAPL'
    detail.data = undefined
    detail.isLoading = false
    detail.isError = false
  })

  it('redirects (replace) to the artifact ticker when the URL ticker mismatches', () => {
    detail.data = {
      id: 'art-nvda-1',
      ticker: 'NVDA',
      type: 'equity_research',
      created_at: '',
      outputs: {},
      inputs: {},
      assumptions: {},
      meta: {},
    }
    renderPage()
    expect(navigateSpy).toHaveBeenCalledWith('/stocks/NVDA/runs/art-nvda-1', { replace: true })
  })

  it('does not redirect when the URL ticker already matches the artifact', () => {
    params.ticker = 'NVDA'
    detail.data = {
      id: 'art-nvda-1',
      ticker: 'NVDA',
      type: 'equity_research',
      created_at: '',
      outputs: {},
      inputs: {},
      assumptions: {},
      meta: {},
    }
    renderPage()
    expect(navigateSpy).not.toHaveBeenCalled()
  })
})

// BUG-20260602-039: only equity_research gets the 13-chapter shell. A dcf (or
// any other) artifact must render the compact viewer — NOT the empty equity
// shell with its TOC / right-rail (IC debate, Ownership, What-if) / scroll-spy.
describe('ArtifactDetailPage type branch (BUG-039)', () => {
  beforeEach(() => {
    navigateSpy.mockClear()
    params.ticker = 'AAPL'
    params.artifactId = 'art-aapl-dcf'
    detail.data = undefined
    detail.isLoading = false
    detail.isError = false
  })

  it('renders the compact viewer (inputs + result) for a dcf artifact, not the 13-chapter shell', () => {
    params.ticker = 'AAPL'
    detail.data = {
      id: 'art-aapl-dcf',
      ticker: 'AAPL',
      type: 'dcf',
      created_at: '2026-06-01T00:00:00Z',
      outputs: {
        structured: { implied_price: 187.4, wacc: 0.082, enterprise_value: 3.1e12 },
        summary_text: 'DCF implied $187.40 / WACC 8.2%',
        warnings: [],
      },
      inputs: { data_source: 'FMP', data_fetched_at: '2026-06-01T00:00:00Z', raw_data: {} },
      assumptions: { parameters: { terminal_growth_rate: 0.025, tax_rate: 0.21 } },
      meta: { created_at: '2026-06-01T00:00:00Z', source: 'pipeline:dcf' },
    }

    renderPage()

    // Compact viewer mounts with the artifact's real numbers.
    expect(screen.getByTestId('compact-artifact-viewer')).toBeTruthy()
    expect(screen.getByText('DCF Implied Price')).toBeTruthy()
    expect(screen.getByText('$187.40')).toBeTruthy()
    // Inputs surfaced.
    expect(screen.getByText('Terminal Growth Rate')).toBeTruthy()
    // Audit trail surfaced.
    expect(screen.getByText('pipeline:dcf')).toBeTruthy()

    // The 13-chapter equity shell must be ABSENT.
    expect(screen.queryByTestId('mock-report-chapters')).toBeNull()
    expect(screen.queryByTestId('mock-toc')).toBeNull()
    expect(screen.queryByTestId('mock-right-rail')).toBeNull()
    expect(screen.queryByTestId('mock-status-bar')).toBeNull()
  })

  it('still renders the 13-chapter shell for equity_research', () => {
    params.ticker = 'AAPL'
    detail.data = {
      id: 'art-aapl-eq',
      ticker: 'AAPL',
      type: 'equity_research',
      created_at: '2026-06-01T00:00:00Z',
      outputs: {},
      inputs: {},
      assumptions: {},
      meta: {},
    }
    params.artifactId = 'art-aapl-eq'

    renderPage()

    expect(screen.getByTestId('mock-report-chapters')).toBeTruthy()
    expect(screen.getByTestId('mock-toc')).toBeTruthy()
    expect(screen.getByTestId('mock-right-rail')).toBeTruthy()
    expect(screen.queryByTestId('compact-artifact-viewer')).toBeNull()
  })
})
