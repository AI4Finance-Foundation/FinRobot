import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { QueryClient, dehydrate } from '@tanstack/react-query'
import {
  reportExportQueries,
  prepareReportExport,
  missingExportBlocksMessage,
} from './reportExportQueries'

// BUG-20260602-028: the exported HTML renders <ReportChapters> against a frozen,
// refetch-disabled cache, so the export must seed EVERY chapter read model
// before dehydrating — otherwise the offline file is missing whatever the user
// hadn't scrolled into view. These tests pin that the export path prefetches the
// exact chapter query keys into the cache even when it starts COLD.

const TICKER = 'AAPL'

// queryKey + URL each chapter hook actually uses (kept in sync with the chapters).
const EXPECTED = [
  {
    id: 'valuation',
    key: ['valuation-aggregate', TICKER],
    url: `/api/valuation/aggregate/${TICKER}`,
  },
  { id: 'historical', key: ['historical', TICKER], url: `/api/data/${TICKER}/historical` },
  {
    id: 'earnings',
    key: ['earnings-calls', TICKER],
    url: `/api/data/${TICKER}/earnings-calls?limit=8`,
  },
  { id: 'price', key: ['ticker-price', TICKER], url: `/api/data/${TICKER}/price` },
  { id: 'financials', key: ['ticker-financials', TICKER], url: `/api/data/${TICKER}/financials` },
] as const

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

describe('reportExportQueries — read-model registry', () => {
  it('lists every chapter read model with the chapter hook key + url', () => {
    const queries = reportExportQueries(TICKER)
    expect(queries.map((q) => q.id)).toEqual(EXPECTED.map((e) => e.id))
    for (const e of EXPECTED) {
      const q = queries.find((x) => x.id === e.id)
      expect(q?.queryKey).toEqual(e.key)
    }
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

  it('reports which blocks failed without aborting the export', async () => {
    const fetchMock = vi.mocked(globalThis.fetch)
    // Earnings + valuation endpoints fail; the rest succeed.
    fetchMock.mockImplementation((input) => {
      const url = String(input)
      if (url.includes('earnings-calls') || url.includes('valuation/aggregate')) {
        return Promise.resolve(new Response('upstream down', { status: 502 }))
      }
      return Promise.resolve(jsonResponse({ url }))
    })

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const missing = await prepareReportExport(qc, TICKER)

    expect(missing.sort()).toEqual(['earnings', 'valuation'])

    // The surviving blocks are still seeded for the export.
    const snapshot = dehydrate(qc)
    const seededKeys = snapshot.queries.map((q) => JSON.stringify(q.queryKey))
    expect(seededKeys).toContain(JSON.stringify(['historical', TICKER]))
    expect(seededKeys).toContain(JSON.stringify(['ticker-price', TICKER]))
    expect(seededKeys).toContain(JSON.stringify(['ticker-financials', TICKER]))
  })
})

describe('missingExportBlocksMessage', () => {
  it('names the missing sections per locale', () => {
    const zh = missingExportBlocksMessage(['earnings', 'valuation'], 'zh')
    expect(zh).toContain('缺失')
    expect(zh).toContain('财报电话会逐字稿')
    const en = missingExportBlocksMessage(['price'], 'en')
    expect(en).toContain('Missing')
    expect(en).toContain('current price')
  })
})
