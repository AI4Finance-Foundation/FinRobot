# P8: Deep Fundamentals — Desktop Tab System + Chart Integration

**Date**: 2026-05-11
**Scope**: Scene 3 of the "FinRobot feature parity" initiative
**Goal**: Expose all existing backend chart/analysis capabilities to the Desktop UI via a tab-based layout

---

## Background

FinAgent backend has 18 chart types, 7 pipelines, and multiple analysis modules. The Desktop UI currently exposes only a subset through a monolithic `TickerWorkspace.tsx` (24.6 KB). This spec covers:

1. Refactoring TickerWorkspace into a tab system
2. Connecting all existing chart components to data sources
3. Adding 4 new frontend chart components for backend capabilities that lack a frontend
4. Surfacing text-based analysis (balance sheet, cash flow, competitor narrative) in relevant tabs

**Out of scope**: Technical analysis (candlestick/indicators), sentiment data sources, new backend capabilities. Those are Scene 1 and Scene 2, separate specs.

---

## Architecture

### Current State

```
TickerWorkspace (24.6 KB monolith)
├── Left Panel: pipeline selector + controls + FinancialsPanel
├── Right Panel: results (switches by pipelineType + phase)
└── All charts inline, pipeline-type-dependent rendering
```

### Target State

```
TickerWorkspace (slim orchestrator, <200 lines)
├── StockHeader              [ticker + company name + price + key metrics, fixed]
├── PipelineRunner           [fixed below header, always accessible from any tab]
├── TabBar                   [Overview | Financials | Valuation | Peers]
└── TabPanel
    ├── OverviewTab           (new file)
    ├── FinancialsTab         (new file)
    ├── ValuationTab          (new file)
    └── PeersTab              (new file)
```

### FinancialsPanel Disposition

`FinancialsPanel.tsx` currently lives in the left sidebar and displays key metrics (revenue, EBITDA, margins, market cap, P/E, debt, EV) from `/api/data/{ticker}/financials`.

**Decision**: Merge FinancialsPanel content into `StockHeader` (compact horizontal summary of key metrics: market cap, P/E, EV) and `FinancialsTab` (full financial breakdown as charts). Delete the standalone left-sidebar FinancialsPanel component. The left sidebar concept is replaced by the always-visible StockHeader + PipelineRunner above the tab system.

---

## Backend Prerequisites

Before any frontend work, the backend must expose data that currently does not exist in the API.

### P8-BE1: Historical Metrics Endpoint

`HistoricalMetrics` model already exists (`finagent/engine/models/financial.py:246-267`) with multi-year arrays for revenue, EPS, P/E, margins, etc. But it is NOT exposed via any API endpoint.

**New endpoint**: `GET /api/data/{ticker}/historical`

**Response model**: `HistoricalMetrics` (existing Pydantic model, no changes needed)

**Implementation**: Call the existing `extract_historical_metrics()` function (or build one) that pulls from `yfinance.Ticker(ticker).income_stmt` + `balance_sheet` + `cashflow` for 4-5 years of annual data.

**Why**: This single endpoint feeds RevenueEbitdaChart, MarginTrendChart, RevenueYoYChart, CashFlowChart, and EpsPeChart. Without it, the Financials and Valuation tabs are mostly empty.

**Fields consumed by frontend charts**:
- `years`, `revenue`, `ebitda`, `ebitda_margin` → RevenueEbitdaChart, RevenueYoYChart
- `gross_margin`, `ebitda_margin`, `operating_margin` → MarginTrendChart
- `eps`, `pe_ratio` → EpsPeChart
- `revenue_growth_yoy` → RevenueYoYChart

### P8-BE2: Cash Flow Statement Data

`HistoricalMetrics` does NOT have cash flow breakdown (operating/investing/financing). This data is needed for CashFlowChart.

**Option A (recommended)**: Extend `HistoricalMetrics` with 3 new fields:
```python
operating_cash_flow: list[float]
investing_cash_flow: list[float]
financing_cash_flow: list[float]
```

Populated from `yfinance.Ticker(ticker).cashflow` DataFrame rows: `Operating Cash Flow`, `Investing Cash Flow` (or `Cash Flow From Continuing Investing Activities`), `Financing Cash Flow` (or `Cash Flow From Continuing Financing Activities`).

**Why not a separate endpoint**: Cash flow data comes from the same yfinance call as income statement data. One endpoint, one fetch, one cache entry.

### P8-BE3: Quarterly Data Endpoint

**New endpoint**: `GET /api/data/{ticker}/quarterly`

**Response**:
```json
{
  "ticker": "AAPL",
  "quarters": [
    {
      "quarter": "2025-Q1",
      "revenue": 94836000000,
      "operating_income": 29200000000,
      "net_income": 23640000000,
      "operating_cash_flow": 28900000000
    }
  ]
}
```

**Implementation notes**:
- Use `yfinance.Ticker(ticker).quarterly_income_stmt` for revenue, operating_income, net_income
- Use `yfinance.Ticker(ticker).quarterly_cashflow` (note: attribute name is `quarterly_cashflow`, NOT `quarterly_cash_flow`) for operating_cash_flow
- **Do NOT include EBITDA**: yfinance `quarterly_income_stmt` does not have an EBITDA row. Computing it requires D&A from cash flow which is unreliable at quarterly granularity. Use `operating_income` instead — it's what yfinance reliably provides.

### P8-BE4: Price History — Use Existing Endpoint

**Do NOT create a new `/api/data/{ticker}/price-history` endpoint.**

The existing `GET /api/data/{ticker}/price` (`data.py:35-47`) already returns `history` array with `{ date, open, high, low, close, volume }` — exactly what `PriceChart.tsx` expects.

**Change needed**: Add optional query param `period` (default `1y`, options: `1m`, `3m`, `6m`, `1y`, `3y`, `5y`) to the existing endpoint. When `period` changes, frontend refetches.

### P8-BE5: Multi-Ticker Performance Endpoint

**New endpoint**: `GET /api/data/performance`

**Query params**:
- `tickers` (comma-separated, e.g., `AAPL,MSFT,GOOGL`)
- `benchmark` (default `SPY` — NOT `^GSPC`, because `^` is a special character that breaks Recharts `dataKey` string accessor)
- `period` (default `1y`)

**Response** — array-of-series format (NOT pivoted-object format):
```json
{
  "series": [
    { "ticker": "AAPL", "label": "AAPL", "data": [{ "date": "2025-05-12", "value": 112.3 }, ...] },
    { "ticker": "MSFT", "label": "MSFT", "data": [{ "date": "2025-05-12", "value": 108.7 }, ...] },
    { "ticker": "SPY", "label": "S&P 500", "data": [{ "date": "2025-05-12", "value": 104.1 }, ...] }
  ]
}
```

**Implementation**: `yfinance.download([tickers + benchmark], period=period)`, normalize each series to 100 at first date. Use `SPY` ETF instead of `^GSPC` index — same performance tracking, no special characters.

**Why array-of-series instead of pivoted object**: Avoids the `^GSPC` dataKey problem entirely. Frontend maps `series` to individual Recharts `<Line>` components. Each series has its own `label` for legend display.

---

## Component Inventory

### Already Exists in Frontend (migrate into tabs)

| Component | Current Location | Target Tab |
|---|---|---|
| `StockOverview.tsx` | TickerWorkspace inline | Merged into StockHeader |
| `PriceChart.tsx` | charts/ | OverviewTab |
| `ResearchSummary.tsx` | TickerWorkspace inline | OverviewTab |
| `WarningBanner.tsx` | TickerWorkspace inline | OverviewTab |
| `RevenueEbitdaChart.tsx` | charts/ | FinancialsTab |
| `MarginTrendChart.tsx` | charts/ | FinancialsTab |
| `AssumptionsEditor.tsx` | TickerWorkspace inline | ValuationTab |
| `ValuationCard.tsx` | TickerWorkspace inline | ValuationTab |
| `ScenarioCompare.tsx` | TickerWorkspace inline | ValuationTab |
| `SensitivityHeatmap.tsx` | charts/ | ValuationTab |
| `WaterfallChart.tsx` | charts/ | ValuationTab |
| `FootballField.tsx` | charts/ | ValuationTab |
| `MonteCarloChart.tsx` | charts/ | ValuationTab |
| `EpsPeChart.tsx` | charts/ (connect to historical endpoint) | ValuationTab |
| `EpsSurpriseChart.tsx` | charts/ (connect to earnings data) | ValuationTab |
| `CompsSummary.tsx` | TickerWorkspace inline | PeersTab |
| `PeerComparisonChart.tsx` | charts/ | PeersTab |
| `CompanyRadarChart.tsx` | charts/ | PeersTab |
| `FinancialsPanel.tsx` | Left sidebar | Deleted — content split into StockHeader + FinancialsTab |

### New Frontend Components to Build

| Component | Target Tab | Data Source |
|---|---|---|
| `CashFlowChart.tsx` | FinancialsTab | `GET /api/data/{ticker}/historical` → operating/investing/financing_cash_flow arrays |
| `QuarterlyComparisonChart.tsx` | FinancialsTab | `GET /api/data/{ticker}/quarterly` |
| `RevenueYoYChart.tsx` | FinancialsTab | `GET /api/data/{ticker}/historical` → revenue_growth_yoy array |
| `RelativePerformanceChart.tsx` | PeersTab | `GET /api/data/performance` |

### Conditional Components (show only when data available)

| Component | Condition | Reason |
|---|---|---|
| `RevenueSegmentsChart.tsx` | Segment data present in response | yfinance segment coverage is poor, FMP requires paid plan |
| `EpsSurpriseChart.tsx` | Earnings pipeline has been run AND surprise data exists | Needs FMP for reliable estimate data |

---

## Tab Designs

### OverviewTab

```
OverviewTab.tsx
├── PriceChart                  [uses existing /api/data/{ticker}/price with period param]
├── ResearchSummary             [research pipeline results from store]
└── WarningBanner               [data quality alerts from store]
```

- **Default landing tab** when user enters a ticker
- **PriceChart refactor required**: Currently `PriceChart.tsx` is a prop-fed component (`data: Record<string, ...>[]`) that filters client-side via `useMemo`. Must be refactored to self-fetching:
  - Add `useQuery({ queryKey: ['price', ticker, range], queryFn: ... })` inside PriceChart
  - Remove the `data` prop, component fetches its own data based on internal `range` state
  - On range change → React Query key changes → automatic refetch with per-range caching
  - `range='ALL'` maps to backend `period=max` (yfinance uses `"max"` for all-time, not `"ALL"`)
  - Period param mapping: `{ '1M': '1mo', '3M': '3mo', '6M': '6mo', '1Y': '1y', 'ALL': 'max' }`
- ResearchSummary: renders when research pipeline has been run, otherwise show empty state

### FinancialsTab

```
FinancialsTab.tsx
├── Trends Section
│   ├── RevenueEbitdaChart      [existing — data from /historical → years + revenue + ebitda]
│   ├── MarginTrendChart        [existing — data from /historical → margins arrays]
│   └── RevenueYoYChart         [NEW — bar chart from /historical → revenue_growth_yoy]
│
├── Structure Section
│   ├── CashFlowChart           [NEW — stacked bars from /historical → operating/investing/financing CF]
│   ├── QuarterlyComparisonChart[NEW — grouped bars from /quarterly endpoint]
│   └── RevenueSegmentsChart    [NEW — conditional, hidden if data unavailable]
│
└── Insights Section (collapsible)
    ├── BalanceSheetInsight      [parsed from researchResult.narrative]
    └── CashFlowInsight          [parsed from researchResult.narrative]
```

**Data source for all Trends + CashFlowChart**: Single `GET /api/data/{ticker}/historical` call, cached in store. One fetch populates 5 charts.

**Insights Section — handling the missing structured fields**:

`ResearchResult` has only `narrative: string` (free-text markdown), NOT structured `balance_sheet_analysis` / `cash_flow_analysis` fields. Rather than modifying the research pipeline's output structure (invasive change, risk of breaking existing behavior):

- Parse `researchResult.narrative` on the frontend for section headers (the LLM-generated narrative typically contains "## Balance Sheet" / "## Cash Flow" / similar markdown sections)
- Utility function: `extractNarrativeSection(narrative: string, sectionKeywords: string[]): string | null`
  - Searches for markdown headings matching keywords (e.g., `["balance sheet", "financial position"]`)
  - Returns the text under that heading until the next heading, or null if not found
- If section not found → hide the insight block (not an error, just means the research narrative didn't include that section)
- This is intentionally fragile — it's a best-effort extraction from free text. The empty state ("Run Research to view insights") is the primary experience; extracted insights are a bonus.

**New adapter functions in `chartAdapters.ts`**:
```typescript
historicalToRevenueEbitdaData(h: HistoricalMetrics): { year: string; revenue: number; ebitda: number }[]
historicalToMarginData(h: HistoricalMetrics): { year: string; gross_margin: number; ebitda_margin: number; operating_margin: number }[]
historicalToRevenueYoYData(h: HistoricalMetrics): { year: string; yoy_pct: number | null }[]
historicalToCashFlowData(h: HistoricalMetrics): { year: string; operating: number; investing: number; financing: number }[]
quarterlyToComparisonData(q: QuarterlyResponse): { quarter: string; revenue: number; operating_income: number; net_income: number }[]
```

Note: RevenueEbitdaChart and MarginTrendChart currently get data from DCF pipeline results via `dcfResultToRevenueEbitdaData()` / `dcfResultToMarginData()`. In the tab system, they should ALSO work without DCF — falling back to the `/historical` endpoint data. The adapter layer handles both sources.

### ValuationTab

```
ValuationTab.tsx
├── DCF Workspace (upper section)
│   ├── AssumptionsEditor       [parameter sliders]
│   ├── ValuationCard           [DCF result]
│   ├── SensitivityHeatmap      [WACC x TGR grid]
│   └── WaterfallChart          [DCF component breakdown]
│
└── Comprehensive Valuation (lower section)
    ├── FootballField           [multi-method range comparison]
    ├── ScenarioCompare         [Bull/Base/Bear]
    ├── MonteCarloSection       [Run button + result chart — see below]
    ├── EpsPeChart              [historical valuation levels]
    └── EpsSurpriseChart        [conditional — requires earnings data]
```

**MonteCarloChart integration**:

MonteCarloChart is NOT a passive chart — it has async trigger logic:
- "Run Monte Carlo" button triggers `useMonteCarloCompute` mutation (POST `/api/compute/monte-carlo`)
- Loading state while computation runs
- Result renders as distribution histogram

In the current TickerWorkspace, this logic lives at the workspace level. For the tab refactor:

- Create a `MonteCarloSection` wrapper component inside ValuationTab that encapsulates:
  - The "Run Monte Carlo (10K simulations)" button
  - The loading spinner
  - The `MonteCarloChart` result (when available)
- `MonteCarloSection` calls `useMonteCarloCompute` hook directly
- Reads `monteCarloResult` and `monteCarloLoading` from store
- This is self-contained within ValuationTab — no dependency on TickerWorkspace

**EpsPeChart data connection**:
- Data source: `GET /api/data/{ticker}/historical` → `eps: list[float]` + `pe_ratio: list[float | None]` + `years: list[int]`
- Adapter: `historicalToEpsPeData(h: HistoricalMetrics): { year: string; eps: number; pe_ratio: number | null }[]`
- If `HistoricalMetrics.price_data_available` is false, pe_ratio will be all null → hide EpsPeChart

**EpsSurpriseChart data connection**:
- Data source: `earningsResult.surprises` from Zustand store (populated when earnings pipeline runs)
- Adapter must match the component's expected interface (`EpsSurpriseChart.tsx:14-19`):
  ```typescript
  earningsToSurpriseChartData(surprises: EarningsSurprise[]): SurpriseDataPoint[]
  // Output: { quarter: string, eps_actual: number, eps_estimated: number, surprise_pct: number, direction: 'beat' | 'miss' | 'inline' }
  ```
- **CRITICAL — field name renames required**: The store's `EarningsSurprise` type uses `eps_surprise_pct` and `eps_direction` (prefixed with `eps_`), but the chart component expects `surprise_pct` and `direction` (no prefix). The adapter MUST explicitly rename these fields:
  - `eps_surprise_pct` → `surprise_pct`
  - `eps_direction` → `direction`
  - Do NOT spread the `EarningsSurprise` object directly — the field names differ between store and component interfaces
- `direction` derivation: `eps_surprise_pct > 2` → `'beat'`, `< -2` → `'miss'`, else `'inline'` (matches existing ±2% threshold in `compute/earnings.py`)
- If earnings pipeline has not been run → empty state card: "Run Earnings Analysis to view EPS surprises"

**DCF Workspace dependency**: Requires DCF pipeline to have been run. Show "Run DCF Analysis" prompt card if `dcfResult` is null.

### PeersTab

```
PeersTab.tsx
├── CompsTable (CompsSummary)   [full width, top position — core element]
│
├── Visualization Row (2-column)
│   ├── CompanyRadarChart       [left — multi-dimensional comparison]
│   └── PeerComparisonChart     [right — scatter distribution]
│
├── RelativePerformanceChart    [NEW — full width, multi-line, time range selector]
│
└── CompetitorNarrative         [collapsible, parsed from researchResult.narrative]
```

**CompsTable position**: at top, full width. This is what analysts look at first.

**RelativePerformanceChart**:
- Fetches `GET /api/data/performance?tickers={target},{peers}&benchmark=SPY&period=1y`
- Peer tickers come from `compsResult.peers` in store (available after comps pipeline)
- If comps not run → show only target ticker vs SPY (still useful)
- Time range selector: 1M | 3M | 6M | 1Y | 3Y — refetch on change
- Recharts implementation: one `<Line>` per series entry, `dataKey="value"`, colored from design system palette
- Adapter: `performanceToMultiLineData(response)` — transforms array-of-series into Recharts-compatible format

**CompetitorNarrative**: same `extractNarrativeSection()` approach as FinancialsTab insights. Keywords: `["competitive", "competitor", "peer", "positioning", "market position"]`.

---

## Global Behavior

### Tab Navigation

- State: `activeTab` added to Zustand store (`'overview' | 'financials' | 'valuation' | 'peers'`)
- Default: `'overview'`
- Tab switch does NOT trigger data refetch if data already loaded
- Tab switch to a tab with unloaded data → show skeleton → fetch → render

### Pipeline Completion Notification

- Pipeline finishes → Toast notification (using existing `Toast.tsx`): "{Pipeline name} complete — View in {Tab name}" (clickable)
- Click toast → `setActiveTab(targetTab)`
- **No auto-tab-switch.** User stays on current tab.
- Toast mapping:
  - research → "View in Overview" (also unlocks insights in Financials + Peers tabs)
  - dcf → "View in Valuation"
  - comps → "View in Peers"
  - earnings → "View in Valuation" (EPS surprise chart)
  - lbo/ic-memo → "View in Valuation"

### Empty States

Each tab section that depends on pipeline results shows a consistent empty state:
- Gray card, dashed border (`border: 1px dashed #252A37`)
- One-line explanation: "Run {pipeline name} to view {content description}"
- Action button that calls the corresponding pipeline run action from store
- Design system colors: text `#7A8299`, button uses `#60A5FA`

### Data Loading Strategy

| Data Type | When Loaded | Endpoint | Store Cache Key |
|---|---|---|---|
| Stock info + current price | On ticker entry (existing) | `GET /api/data/{ticker}/financials` | existing |
| Price history | PriceChart self-fetches per range | `GET /api/data/{ticker}/price?period={range}` (existing, add period param) | React Query `['price', ticker, range]` (component-level) |
| Historical metrics | On FinancialsTab mount OR ticker change while on tab | `GET /api/data/{ticker}/historical` (new) | `historicalMetrics` |
| Quarterly data | On FinancialsTab mount OR ticker change while on tab | `GET /api/data/{ticker}/quarterly` (new) | `quarterlyData` |
| Peer performance | On PeersTab mount OR ticker change while on tab | `GET /api/data/performance` (new) | `performanceData` |
| Pipeline results | On pipeline completion (existing) | SSE stream (existing) | existing per-pipeline fields |

### PriceChart Range Change Handling

After refactor, `PriceChart.tsx` self-fetches data (no longer prop-fed). Range changes:
- Internal `range` state triggers React Query refetch via `queryKey: ['price', ticker, range]`
- Range-to-period mapping: `{ '1M': '1mo', '3M': '3mo', '6M': '6mo', '1Y': '1y', 'ALL': 'max' }`
- React Query handles caching — switching back to a previously viewed range uses cache, no refetch
- This is component-local state, NOT in Zustand store
- On ticker change, `ticker` in query key changes → all cached ranges for old ticker are stale → automatic refetch

---

## TickerWorkspace Refactoring

Current TickerWorkspace.tsx (24.6 KB) will be split:

| New File | Responsibility | Approx Size |
|---|---|---|
| `TickerWorkspace.tsx` | Slim orchestrator: StockHeader + PipelineRunner + TabBar + TabPanel routing | <200 lines |
| `StockHeader.tsx` | Ticker + company name + price + change + key metrics (from FinancialsPanel) | ~100 lines |
| `views/OverviewTab.tsx` | PriceChart + ResearchSummary + WarningBanner | ~80 lines |
| `views/FinancialsTab.tsx` | Trends + Structure + Insights sections, fetches /historical + /quarterly | ~200 lines |
| `views/ValuationTab.tsx` | DCF Workspace + Comprehensive section + MonteCarloSection | ~250 lines |
| `views/PeersTab.tsx` | CompsTable + charts + RelativePerformance + narrative | ~180 lines |

**Migration strategy**: 
1. Extract StockHeader from StockOverview + FinancialsPanel top metrics
2. Build TabBar + TabPanel skeleton in TickerWorkspace
3. Move existing components into tab files one at a time
4. Delete FinancialsPanel after its content is absorbed
5. Add new charts + connect data sources
6. Wire up toast notifications + empty states

Logic currently in TickerWorkspace (phase management, pipeline type switching, data fetching) stays in the Zustand store + hooks. Tab components are pure rendering + their own data fetching hooks.

---

## Zustand Store Changes

Add to `useAppStore`:

```typescript
// Tab state
activeTab: 'overview' | 'financials' | 'valuation' | 'peers'
setActiveTab: (tab: ActiveTab) => void

// New data caches (per-ticker, invalidated on ticker change)
historicalMetrics: HistoricalMetrics | null
quarterlyData: QuarterlyData | null
performanceData: PerformanceData | null

// Loading states
historicalLoading: boolean
quarterlyLoading: boolean
performanceLoading: boolean

// Setter actions
setHistoricalMetrics: (data: HistoricalMetrics | null) => void
setQuarterlyData: (data: QuarterlyData | null) => void
setPerformanceData: (data: PerformanceData | null) => void
setHistoricalLoading: (loading: boolean) => void
setQuarterlyLoading: (loading: boolean) => void
setPerformanceLoading: (loading: boolean) => void
```

**`setTicker()` reset behavior**:
- Reset `historicalMetrics`, `quarterlyData`, `performanceData` to null
- Reset `activeTab` to `'overview'` — user enters new ticker → starts from Overview, not stale previous tab
- Reset all 3 loading flags to false

**Tab data re-fetch on ticker change**:
- Each tab component uses `useEffect` with `[ticker]` dependency to trigger data fetch
- This means: if user is already on FinancialsTab and changes ticker → the tab stays mounted → `useEffect` fires → re-fetches `/historical` and `/quarterly` for new ticker
- Do NOT rely solely on mount-based fetching — mount only triggers on first tab visit, `useEffect([ticker])` handles ticker changes within the same tab

**New TypeScript interfaces** (in `stores/appStore.ts` or a separate `types.ts`):

```typescript
interface HistoricalMetrics {
  years: number[]
  revenue: number[]
  revenue_growth_yoy: (number | null)[]
  ebitda: number[]
  ebitda_margin: number[]
  gross_margin: number[]
  operating_margin: number[]
  operating_income: number[]
  net_income: number[]
  eps: number[]
  pe_ratio: (number | null)[]
  operating_cash_flow: number[]
  investing_cash_flow: number[]
  financing_cash_flow: number[]
  cagr_revenue: number | null
  ticker: string
  price_data_available: boolean
}

interface QuarterlyData {
  ticker: string
  quarters: {
    quarter: string
    revenue: number
    operating_income: number
    net_income: number
    operating_cash_flow: number
  }[]
}

interface PerformanceData {
  series: {
    ticker: string
    label: string
    data: { date: string; value: number }[]
  }[]
}
```

---

## New Chart Adapter Functions

Add to existing `desktop/src/utils/chartAdapters.ts`:

```typescript
// FinancialsTab — all from HistoricalMetrics
export function historicalToRevenueEbitdaData(h: HistoricalMetrics): 
  { year: string; revenue: number; ebitda: number }[]

export function historicalToMarginData(h: HistoricalMetrics): 
  { year: string; gross_margin: number; ebitda_margin: number; operating_margin: number }[]

export function historicalToRevenueYoYData(h: HistoricalMetrics): 
  { year: string; yoy_pct: number | null }[]

export function historicalToCashFlowData(h: HistoricalMetrics): 
  { year: string; operating: number; investing: number; financing: number }[]

export function quarterlyToComparisonData(q: QuarterlyData): 
  { quarter: string; revenue: number; operating_income: number; net_income: number }[]

// ValuationTab
export function historicalToEpsPeData(h: HistoricalMetrics): 
  { year: string; eps: number; pe_ratio: number | null }[]

export function earningsToSurpriseChartData(surprises: EarningsSurprise[]): SurpriseDataPoint[]
// Must output: { quarter, eps_actual, eps_estimated, surprise_pct, direction }
// direction: surprise_pct > 2 → 'beat', < -2 → 'miss', else 'inline'

// PeersTab — NO pivoting. Use array-of-series directly.
// Each series rendered as a separate <Line> with dataKey="value".
// Do NOT pivot into { date, AAPL, MSFT, ... } — dot-tickers like BRK.B
// break Recharts' dataKey path resolution (treats . as nested access).
// Instead, RelativePerformanceChart maps perf.series to:
//   perf.series.map(s => <Line key={s.ticker} data={s.data} dataKey="value" name={s.label} />)
// No adapter function needed — the backend response is directly consumable.
```

**Important**: RevenueEbitdaChart and MarginTrendChart currently receive data from DCF pipeline results via `dcfResultToRevenueEbitdaData()`. Those adapters stay unchanged. In FinancialsTab, use the new `historicalTo*` adapters as the primary source. The tab renders from `/historical` data; the DCF result is NOT required.

---

## Design System Compliance

All new components follow existing patterns from `DESIGN-SYSTEM.md`:

- Card container: `className="card animate-in"`
- Chart colors: `#60A5FA` (primary), `#C9A84C` (accent), `#34D399` (green), `#F87171` (red)
- Background: `#1A1F2E`
- Text: `#E8ECF4` primary, `#7A8299` secondary
- Borders: `#252A37`
- Font: `'JetBrains Mono', monospace` for chart axes/tooltips
- Tooltip style: `{ backgroundColor: '#1A1F2E', border: '1px solid #252A37', borderRadius: 6, color: '#E8ECF4' }`
- Section headers: consistent with existing `card-header` / `card-title` classes
- Collapsible sections: `<details>` element or controlled state with CSS transition

---

## Dependency Audit

### New Frontend Dependencies: None

- Tab system: plain React state, no library
- All charts: Recharts (already installed)
- Data fetching: React Query + openapi-fetch (already installed)
- Narrative parsing: plain string operations, no library

### New Backend Dependencies: None

- All data from yfinance (already installed)
- Endpoints in existing FastAPI routes
- `HistoricalMetrics` model already defined

---

## Success Criteria

1. TickerWorkspace.tsx reduced from 24.6 KB to <200 lines
2. All 4 tabs render with correct content
3. 4 new chart components (CashFlowChart, QuarterlyComparisonChart, RevenueYoYChart, RelativePerformanceChart) display real data
4. PriceChart renders from existing `/price` endpoint with period support
5. EpsPeChart renders from `/historical` endpoint — multi-year EPS + P/E series
6. EpsSurpriseChart renders from earnings pipeline results with correct field names (eps_actual, eps_estimated, direction)
7. MonteCarloSection encapsulates its own Run button + loading state + chart within ValuationTab
8. FinancialsPanel deleted, content absorbed into StockHeader + FinancialsTab
9. Tab switch does not cause unnecessary data refetch
10. Empty states guide user to run appropriate pipeline
11. Toast notifications on pipeline completion with tab navigation
12. Conditional components (RevenueSegments, EpsSurprise) hidden when data unavailable
13. No regressions in existing pipeline flows (DCF, Comps, Research, LBO, etc.)

---

## Risk Register

| Risk | Mitigation |
|---|---|
| yfinance `cashflow` DataFrame row names vary by ticker (e.g., "Operating Cash Flow" vs "Cash Flow From Operations") | Backend normalizes row name lookup with fallback list |
| `extractNarrativeSection()` parsing is brittle — LLM narrative format varies | Accept fragility — insights are a bonus, empty state is the default |
| HistoricalMetrics has < 4 years of data for some tickers (e.g., recent IPOs) | Charts handle short arrays gracefully (render what's available) |
| Quarterly endpoint returns partial data for current quarter | Only return completed quarters, skip in-progress quarter |
| PriceChart range change triggers many API calls if user clicks rapidly | React Query deduplication + 300ms debounce on range button |

---

## Non-Goals (Explicitly Out of Scope)

- Candlestick charts / technical indicators → Scene 1
- Sentiment data sources → Scene 2
- News/catalyst views → Scene 2
- Drag-and-drop layout customization
- Tab reordering or custom tabs
- Modifying research pipeline output structure (use narrative parsing instead)
- Backend matplotlib chart rendering (Desktop uses Recharts exclusively)
