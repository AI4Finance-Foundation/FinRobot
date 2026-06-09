import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { QueryClient, dehydrate } from '@tanstack/react-query'
import {
  reportExportQueries,
  prepareReportExport,
  missingExportBlocksMessage,
} from './reportExportQueries'

// BUG-20260602-028: the exported HTML renders <ReportChapters> against a frozen,
// refetch-disabled cache, so the export must seed every STILL-LIVE chapter read
// model before dehydrating — otherwise the offline file is missing whatever the
// user hadn't scrolled into view. The valuation/price/beta surfaces AND the
// multi-year financial-trend charts are now FROZEN (rendered from the persisted
// artifact, no live hooks), so only the earnings-call transcript chapter remains
// to prefetch.

const TICKER = 'AAPL'

// queryKey + URL each chapter hook actually uses (kept in sync with the chapters).
const EXPECTED = [
  {
    id: 'earnings',
    key: ['earnings-calls', TICKER],
    url: `/api/data/${TICKER}/earnings-calls?limit=8`,
  },
] as const

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

describe('reportExportQueries — read-model registry', () => {
  it('lists every still-live chapter read model with the chapter hook key + url', () => {
    const queries = reportExportQueries(TICKER)
    expect(queries.map((q) => q.id)).toEqual(EXPECTED.map((e) => e.id))
    for (const e of EXPECTED) {
      const q = queries.find((x) => x.id === e.id)
      expect(q?.queryKey).toEqual(e.key)
    }
  })

  it('does NOT prefetch the now-frozen valuation / price / historical surfaces', () => {
    const ids = reportExportQueries(TICKER).map((q) => String(q.id))
    expect(ids).not.toContain('valuation')
    expect(ids).not.toContain('price')
    expect(ids).not.toContain('financials')
    // historical financial-trend charts are now frozen into the artifact too.
    expect(ids).not.toContain('historical')
  })
})

describe('prepareReportExport — deterministic export seeding (BUG-028)', () => {
  beforeEach(() => {
    vi.spyOn(globalThis, 'fetch')
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('prefetches ALL required keys from a COLD cache before dehydrate', async () => {
    const fetchMock = vi.mocked(globalThis.fetch)
    // Echo the requested path so we can assert each block landed in the cache.
    fetchMock.mockImplementation((input) => Promise.resolve(jsonResponse({ url: String(input) })))

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const missing = await prepareReportExport(qc, TICKER)

    // Nothing failed → every block present.
    expect(missing).toEqual([])

    // Every chapter endpoint was actually hit.
    const calledUrls = fetchMock.mock.calls.map((c) => String(c[0]))
    for (const e of EXPECTED) {
      expect(calledUrls.some((u) => u.endsWith(e.url))).toBe(true)
    }

    // The dehydrated snapshot — what gets inlined into the HTML — carries the
    // data for every chapter key, even though the cache started empty.
    const snapshot = dehydrate(qc)
    for (const e of EXPECTED) {
      const entry = snapshot.queries.find(
        (q) => JSON.stringify(q.queryKey) === JSON.stringify(e.key),
      )
      expect(entry, `missing cache entry for ${e.id}`).toBeTruthy()
      expect((entry?.state.data as { url?: string })?.url).toContain(e.url.split('?')[0])
    }
  })

  it('reports a failed block without aborting (throwing) the export', async () => {
    const fetchMock = vi.mocked(globalThis.fetch)
    // The earnings endpoint (the sole remaining live prefetch) fails upstream.
    fetchMock.mockImplementation((input) => {
      const url = String(input)
      if (url.includes('earnings-calls')) {
        return Promise.resolve(new Response('upstream down', { status: 502 }))
      }
      return Promise.resolve(jsonResponse({ url }))
    })

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    // A failed block is REPORTED (returned), not thrown — the export proceeds and
    // the caller warns precisely which section will be missing.
    const missing = await prepareReportExport(qc, TICKER)

    expect(missing).toEqual(['earnings'])
  })
})

describe('missingExportBlocksMessage', () => {
  it('names the missing sections per locale', () => {
    const zh = missingExportBlocksMessage(['earnings'], 'zh')
    expect(zh).toContain('缺失')
    expect(zh).toContain('财报电话会逐字稿')
    const en = missingExportBlocksMessage(['earnings'], 'en')
    expect(en).toContain('Missing')
    expect(en).toContain('earnings call transcripts')
  })
})
