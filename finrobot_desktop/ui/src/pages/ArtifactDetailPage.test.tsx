import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render } from '@testing-library/react'
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
vi.mock('./artifact-detail/shell/ReportToolbar', () => ({ ReportToolbar: () => null }))
vi.mock('./artifact-detail/shell/ReportTOC', () => ({ ReportTOC: () => null }))
vi.mock('./artifact-detail/shell/ReportRightRail', () => ({ ReportRightRail: () => null }))
vi.mock('./artifact-detail/shell/ReportStatusBar', () => ({ ReportStatusBar: () => null }))
vi.mock('./artifact-detail/ReportChapters', () => ({ ReportChapters: () => null }))
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
