# Terminal Redesign — Full Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite FinRobot Desktop frontend from light Apple-style to dark trading terminal aesthetic, make every feature real (connected to backend), add missing pages (Playground, Journal) and backend endpoints (market data, journal CRUD), add AI panel show/hide animation.

**Architecture:** Existing React 19 + Tauri frontend with Zustand stores + TanStack Query already connects to FastAPI backend via openapi-fetch. The backend has all compute/data/pipeline endpoints. We change the design system (CSS variables), restructure the app shell (sidebar replaces ActivityBar), add 2 new pages, and add 3 backend endpoints. No framework changes.

**Tech Stack:** React 19, TypeScript, Zustand, TanStack Query, Vite, Tailwind CSS (utility layer), CSS custom properties (design tokens), Python FastAPI, yfinance, SQLite

---

## File Structure

### New files
| Path | Purpose |
|------|---------|
| `ui/src/pages/PlaygroundPage.tsx` | What-If DCF playground with sliders + Monte Carlo |
| `ui/src/pages/JournalPage.tsx` | Decision journal timeline |
| `ui/src/layout/Sidebar.tsx` | Full sidebar (nav + watchlist), replaces icon-only ActivityBar |
| `finrobot/routes/market.py` | Market indices + sector ETF + earnings calendar endpoints |
| `finrobot/routes/journal.py` | Journal entry CRUD endpoints |
| `finrobot/engine/compute/market.py` | Market data fetching logic (yfinance batch) |
| `finrobot/models/journal.py` | Journal Pydantic models + SQLite persistence |

### Modified files
| Path | Change |
|------|--------|
| `ui/src/App.css` | Complete design token overhaul: dark terminal + light theme |
| `ui/src/layout/AppShell.tsx` | Grid: `200px 1fr 320px` with sidebar |
| `ui/src/layout/TitleBar.tsx` | Simplify, add theme toggle |
| `ui/src/layout/RightChatPanel.tsx` | CSS transition animation, context-aware chips |
| `ui/src/components/StatusBar.tsx` | Terminal-style status bar |
| `ui/src/router.tsx` | Add `/playground`, `/journal` routes |
| `ui/src/pages/DashboardPage.tsx` | Rewrite with real market data |
| `ui/src/stores/uiStore.ts` | Add `theme: 'dark' | 'light'` + `setTheme()` |
| `finrobot/server.py` | Mount market_router, journal_router |

---

## Phase 1: Design Foundation

### Task 1: Dark terminal CSS tokens + theme toggle state

**Files:**
- Modify: `ui/src/App.css` (lines 1-80)
- Modify: `ui/src/stores/uiStore.ts`

- [ ] **Step 1: Replace CSS custom properties in App.css**

Replace the `:root` block with dark terminal tokens. Add `[data-theme="light"]` block. Key changes:
```css
:root {
  --bg-0: #0C0C0C;  --bg-1: #0F0F0F;  --bg-2: #111111;  --bg-3: #161616;
  --border: #1A1A1A;  --border-hover: #2A2A2A;
  --text-1: #DDDDDD;  --text-2: #888888;  --text-3: #555555;  --text-4: #333333;
  --accent: #E2B93D;  --accent-dim: rgba(226,185,61,0.08);
  --up: #26A69A;  --dn: #EF5350;  --hold: #E2B93D;
  --font-ui: 'Inter', -apple-system, sans-serif;
  --font-mono: 'JetBrains Mono', monospace;
  --r: 6px;
  /* Map legacy aliases */
  --gold: var(--accent); --positive: var(--up); --negative: var(--dn);
  --base: var(--bg-0); --surface: var(--bg-1); --elevated: var(--bg-2);
  --text-primary: var(--text-1); --text-secondary: var(--text-2); --text-muted: var(--text-3);
}
[data-theme="light"] {
  --bg-0: #F2F1EC;  --bg-1: #FFFFFF;  --bg-2: #F7F6F2;  --bg-3: #EDECE8;
  --border: #D8D7D3;  --border-hover: #C5C4C0;
  --text-1: #1A1A1A;  --text-2: #666666;  --text-3: #999999;  --text-4: #BBBBBB;
  --accent: #B8960A;  --accent-dim: rgba(184,150,10,0.08);
}
```
Remove all `--shadow-*` variables (no shadows in terminal design). Remove `--r-lg: 12px` — everything uses 6px. Update `--r-sm: 6px; --r-md: 6px;`.

- [ ] **Step 2: Add theme state to uiStore**

Add to `UiStoreState`:
```typescript
theme: 'dark' | 'light'
setTheme: (t: 'dark' | 'light') => void
toggleTheme: () => void
```
In store creation, persist `theme`. On init + on change, set `document.documentElement.setAttribute('data-theme', theme)`.

- [ ] **Step 3: Update body/scrollbar styles in App.css**

```css
html, body { height: 100%; overflow: hidden; }
body { 
  font-family: var(--font-ui); color: var(--text-1); 
  background: var(--bg-0); -webkit-font-smoothing: antialiased; font-size: 13px;
}
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-hover); border-radius: 3px; }
```
Remove all box-shadow rules from `.card`, `.btn`, and other utility classes.

- [ ] **Step 4: Verify build**

Run: `cd ui && npm run build`
Expected: Build succeeds. Visual may look rough (wrong layout) but tokens compile.

- [ ] **Step 5: Commit**

```
feat(ui): dark terminal design tokens + theme toggle state
```

### Task 2: App shell layout — Sidebar replaces ActivityBar

**Files:**
- Create: `ui/src/layout/Sidebar.tsx`
- Modify: `ui/src/layout/AppShell.tsx`
- Modify: `ui/src/layout/ActivityBar.tsx` (deprecate or remove)
- Modify: `ui/src/App.css` (shell grid rules)

- [ ] **Step 1: Create Sidebar component**

`ui/src/layout/Sidebar.tsx` — Full sidebar with:
- Navigation section (6 items: Dashboard, Stocks, Playground, Journal, Library, Settings)
- Active item highlighted with `var(--accent)` + left 2px border
- Watchlist section reading from `useStocksStore().watchlist`
- Each watchlist item shows ticker + price from `useTickerPrice()` (existing hook)
- Add-ticker input at bottom
- Footer: "DELAYED 15M · YFINANCE+FMP"
- Background: `var(--sidebar-bg)` (add `--sidebar-bg: #0A0A0A` to `:root`, `--sidebar-bg: #141418` to light theme)

- [ ] **Step 2: Update AppShell grid**

Replace current `app-body` flex layout with CSS grid:
```css
.app-shell {
  display: grid;
  grid-template-columns: 200px 1fr 320px;
  grid-template-rows: 38px 1fr 22px;
  height: 100vh; overflow: hidden;
}
```
TitleBar spans full width. Sidebar in col 1. Main in col 2. Chat in col 3. StatusBar spans full width.

When AI panel is collapsed, grid becomes `200px 1fr 40px`.

- [ ] **Step 3: Update AppShell.tsx to use Sidebar**

Replace `<ActivityBar />` with `<Sidebar />`. Keep the `toggleAiPanel` keyboard shortcut.

- [ ] **Step 4: Verify nav works**

Run: `cd ui && npm run dev`
Open browser. Click each nav item → correct page loads. Watchlist shows tickers (if any added).

- [ ] **Step 5: Commit**

```
feat(ui): sidebar with nav + watchlist replaces ActivityBar
```

### Task 3: TitleBar — theme toggle + simplify

**Files:**
- Modify: `ui/src/layout/TitleBar.tsx`

- [ ] **Step 1: Replace TitleBar content**

Simplify to: macOS dots spacer + centered "FINAGENT TERMINAL" text + theme toggle button + AI toggle button.
Theme toggle: sun/moon icon, calls `useUiStore().toggleTheme()`.
Remove workspace picker (move to Settings if needed).

- [ ] **Step 2: Style TitleBar**

Background: `var(--sidebar-bg)`. Text: `var(--text-3)` mono 11px uppercase. Border-bottom: `1px solid var(--border)`.

- [ ] **Step 3: Commit**

```
feat(ui): simplified titlebar with theme toggle
```

### Task 4: StatusBar update

**Files:**
- Modify: `ui/src/components/StatusBar.tsx`

- [ ] **Step 1: Rewrite StatusBar**

Terminal-style: Left = green breathing dot + "CONNECTED". Center = "YFINANCE + FMP · 15M DELAY". Right = "FINAGENT v0.1.0 · {current ticker}".
Height: 22px. Background: `var(--sidebar-bg)`. Font: mono 10px.

- [ ] **Step 2: Commit**

```
feat(ui): terminal-style status bar
```

---

## Phase 2: Backend — Market Data Endpoints

### Task 5: Market indices + sector ETF endpoint

**Files:**
- Create: `finrobot/engine/compute/market.py`
- Create: `finrobot/routes/market.py`
- Modify: `finrobot/server.py` (mount router)

- [ ] **Step 1: Create market data fetcher**

`finrobot/engine/compute/market.py`:
```python
import yfinance as yf
from pydantic import BaseModel

class MarketIndex(BaseModel):
    symbol: str
    name: str
    price: float
    change: float
    change_pct: float
    
async def fetch_market_indices() -> list[MarketIndex]:
    """Fetch S&P500, NASDAQ, DOW, VIX, 10Y, Russell via yfinance."""
    symbols = {"^GSPC": "S&P 500", "^IXIC": "NASDAQ", "^DJI": "DOW 30",
               "^VIX": "VIX", "^TNX": "10Y UST", "^RUT": "RUSSELL"}
    # yfinance batch download, extract last close + change
    ...

async def fetch_sector_etfs() -> list[MarketIndex]:
    """Fetch 11 SPDR sector ETFs."""
    symbols = {"XLK": "Tech", "XLF": "Fin", "XLE": "Energy", ...}
    ...
```

- [ ] **Step 2: Create market routes**

`finrobot/routes/market.py`:
```python
router = APIRouter(prefix="/api/market", tags=["market"])

@router.get("/indices")  # → list[MarketIndex]
@router.get("/sectors")  # → list[MarketIndex]
@router.get("/earnings-calendar")  # → list[EarningsEvent] (FMP if key available, else empty)
```

- [ ] **Step 3: Mount router in server.py**

Add `app.include_router(market_router)` in `create_app()`.

- [ ] **Step 4: Test endpoints**

Run: `uv run python -m finrobot.cli serve` then `curl http://localhost:8321/api/market/indices`
Expected: JSON array of 6 market indices with real prices.

- [ ] **Step 5: Commit**

```
feat(api): market indices + sector ETF + earnings calendar endpoints
```

---

## Phase 3: Dashboard Rewrite

### Task 6: Dashboard with real market data

**Files:**
- Modify: `ui/src/pages/DashboardPage.tsx`

- [ ] **Step 1: Add hooks for market data**

Use React Query to fetch from new endpoints:
```typescript
const { data: indices } = useQuery({ queryKey: ['market-indices'], queryFn: () => fetch(`${BASE_URL}/api/market/indices`).then(r => r.json()), staleTime: 60_000 })
const { data: sectors } = useQuery({ queryKey: ['market-sectors'], queryFn: () => fetch(`${BASE_URL}/api/market/sectors`).then(r => r.json()), staleTime: 60_000 })
const { data: earnings } = useQuery({ queryKey: ['earnings-calendar'], queryFn: () => fetch(`${BASE_URL}/api/market/earnings-calendar`).then(r => r.json()), staleTime: 300_000 })
```

- [ ] **Step 2: Build MarketTickerBar component**

6-column grid showing each index: label (mono 9px uppercase), value (mono 16px bold), change (colored). All from real data. Show skeleton while loading.

- [ ] **Step 3: Build SectorStrip component**

11 colored blocks sorted by performance. Background opacity proportional to magnitude. Real data from `/api/market/sectors`.

- [ ] **Step 4: Build EarningsCalendar component**

List of upcoming earnings from FMP endpoint. Each item: day, ticker, company name, time (BMO/AMC). Highlight watchlist tickers with star.

- [ ] **Step 5: Build SignalsAlerts component**

Source from catalysts endpoint: for each watchlist ticker, fetch `/api/data/{ticker}/catalysts` and merge into a unified signal feed. Show channel tags (Desktop on, others from settings).

- [ ] **Step 6: Keep existing real components**

QuickActions (4 cards linking to real pages), WatchlistSection (from store), RecentAnalyses (from artifacts API).

- [ ] **Step 7: Remove footer text**

Delete the "FinRobot — open-source financial analysis" footer div.

- [ ] **Step 8: Verify everything loads with real data**

Run backend + frontend. Dashboard shows real market data, sector performance, earnings calendar. No placeholder "—" values.

- [ ] **Step 9: Commit**

```
feat(ui): dashboard rewrite with real market data
```

---

## Phase 4: Playground Page

### Task 7: Playground — slider-based DCF What-If

**Files:**
- Create: `ui/src/pages/PlaygroundPage.tsx`
- Modify: `ui/src/router.tsx`

- [ ] **Step 1: Add route**

In router.tsx: `{ path: "playground", element: <PlaygroundPage /> }`

- [ ] **Step 2: Build PlaygroundPage**

Layout: 2-column grid.
Left: 4 sliders (WACC, Terminal Growth, Gross Margin, Revenue Growth).
Right: DCF target price, upside/downside, EV, Bull/Base/Bear scenarios.

On slider change → call `POST /api/compute/dcf` with updated parameters. Use React Query mutation with `useMutation`. The endpoint already exists and returns full DCF result.

- [ ] **Step 3: Add sensitivity matrix**

On parameter change → call `POST /api/compute/dcf-sensitivity` with WACC range and TG range centered on current values. Render as colored table. Backend endpoint already exists.

- [ ] **Step 4: Add Monte Carlo section**

On parameter change → call `POST /api/compute/monte-carlo` with current parameters. Render histogram using Canvas. Backend endpoint already exists and returns `{ percentiles, distribution, ... }`.

- [ ] **Step 5: Handle no-ticker state**

If no ticker selected, show prompt to select one. Read from URL params or stocksStore.currentTicker.

- [ ] **Step 6: Verify all three panels update with real compute**

Drag sliders → prices update from real backend DCF. Sensitivity matrix from real backend. Monte Carlo from real backend.

- [ ] **Step 7: Commit**

```
feat(ui): playground page with real DCF/sensitivity/monte-carlo
```

---

## Phase 5: Journal Backend + Page

### Task 8: Journal backend — CRUD endpoints

**Files:**
- Create: `finrobot/models/journal.py`
- Create: `finrobot/routes/journal.py`
- Modify: `finrobot/server.py`

- [ ] **Step 1: Create journal model**

```python
class JournalEntry(BaseModel):
    id: str  # uuid
    ticker: str
    action: Literal["BUY", "SELL", "HOLD"]
    entry_price: float
    target_price: float | None
    thesis: str
    created_at: datetime
    notes: str | None = None
```

SQLite persistence in `~/.finrobot-desktop/journal.db`.

- [ ] **Step 2: Create CRUD endpoints**

```
POST   /api/journal          → create entry
GET    /api/journal          → list entries (newest first)
GET    /api/journal/{id}     → get single entry
PUT    /api/journal/{id}     → update entry
DELETE /api/journal/{id}     → delete entry
```

For each entry, also fetch current price from yfinance to compute P&L:
```python
entry.current_price = yf.Ticker(entry.ticker).fast_info.get("lastPrice")
entry.pnl_pct = (current - entry_price) / entry_price * 100
```

- [ ] **Step 3: Mount router**

- [ ] **Step 4: Test**

```bash
curl -X POST http://localhost:8321/api/journal -H 'Content-Type: application/json' \
  -d '{"ticker":"NVDA","action":"BUY","entry_price":135.40,"target_price":162.30,"thesis":"AI infra demand"}'
curl http://localhost:8321/api/journal
```

- [ ] **Step 5: Commit**

```
feat(api): journal CRUD endpoints with SQLite persistence
```

### Task 9: Journal page

**Files:**
- Create: `ui/src/pages/JournalPage.tsx`
- Modify: `ui/src/router.tsx`

- [ ] **Step 1: Add route**

`{ path: "journal", element: <JournalPage /> }`

- [ ] **Step 2: Build JournalPage**

Timeline layout. Each entry: date, ticker, action badge (BUY/SELL/HOLD), entry price, target vs current, thesis text, P&L result (live from backend).

"New Entry" button opens inline form (not modal — keep it simple).

Fetch from `GET /api/journal`. Post new entries to `POST /api/journal`.

- [ ] **Step 3: Verify**

Create an entry via the form. It appears in the timeline. P&L updates with real current price.

- [ ] **Step 4: Commit**

```
feat(ui): journal page with real CRUD + live P&L
```

---

## Phase 6: AI Panel Polish

### Task 10: Collapse/expand animation

**Files:**
- Modify: `ui/src/App.css` (AI panel transitions)
- Modify: `ui/src/layout/RightChatPanel.tsx`

- [ ] **Step 1: Add CSS transition**

```css
.ai-panel {
  transition: width 0.2s ease, opacity 0.15s ease;
  overflow: hidden;
}
.ai-panel.collapsed {
  width: 0 !important;
  opacity: 0;
  pointer-events: none;
}
```

When `aiPanelOpen` is false, apply `.collapsed` class instead of rendering IconColumn. The panel slides out smoothly.

- [ ] **Step 2: Update AppShell grid transition**

When panel collapses, the main content area expands smoothly:
```css
.app-shell {
  transition: grid-template-columns 0.2s ease;
}
```

- [ ] **Step 3: Add keyboard shortcut indicator**

Show "⌘L" hint near the collapsed edge so users know how to reopen.

- [ ] **Step 4: Commit**

```
feat(ui): smooth AI panel collapse/expand animation
```

### Task 11: Context-aware suggestion chips

**Files:**
- Modify: `ui/src/layout/RightChatPanel.tsx`

- [ ] **Step 1: Add chips data**

Different chips per current route:
```typescript
const CHIPS: Record<string, string[]> = {
  '/dashboard': ['今日市场概览', '本周 earnings 预览', 'Portfolio alpha'],
  '/stocks': ['DCF 假设解释', 'vs 竞争对手', 'Monte Carlo', '10-K RAG'],
  '/playground': ['解释 WACC', 'Bull case', 'Bear case'],
  '/journal': ['回测胜率', 'Alpha 统计', '最佳/最差决策'],
}
```

- [ ] **Step 2: Render chips in empty state and below input**

When message list is empty, show chips as clickable buttons that populate the input. Also show smaller chip row above input area always.

- [ ] **Step 3: Commit**

```
feat(ui): context-aware suggestion chips in AI panel
```

---

## Phase 7: Stock Detail + Settings Visual Polish

### Task 12: Stock detail visual refresh

**Files:**
- Modify: `ui/src/components/StockHeader.tsx`
- Modify: `ui/src/components/VerbToolbar.tsx`
- Modify: `ui/src/components/TabBar.tsx`
- Modify: Various view components

- [ ] **Step 1: Update StockHeader**

Large mono ticker + company name + industry. Right side: price + change (colored). Match demo aesthetic: `--bg-2` card with `--border`.

- [ ] **Step 2: Update VerbToolbar**

Gold primary button for "Full Analysis". Ghost buttons for DCF/Comps/Earnings/LBO/Backtest/Export.

- [ ] **Step 3: Update KPI cards**

Add `kpi-explain` line under each KPI (plain text explaining what the number means for retail investors). Add `src-tag` spans showing data source.

These explanation lines come from the backend — the compute results already include `source` fields. For the explanations, add a small helper that generates contextual one-liners from the data.

- [ ] **Step 4: Verify all stock detail tabs load real data**

Navigate to `/stocks/NVDA`. Click each tab. All data comes from real backend endpoints (already connected).

- [ ] **Step 5: Commit**

```
feat(ui): stock detail terminal visual refresh
```

### Task 13: Settings visual refresh

**Files:**
- Modify: `ui/src/components/SettingsView.tsx`

- [ ] **Step 1: Update Settings layout**

Match demo: sections for Data Sources (FMP required, Finnhub/SEC optional), LLM Provider (model dropdown + key), Notification Channels (checkboxes + webhook URLs), Appearance (theme radio).

The Settings page already connects to `GET/PUT /api/settings`. Just update the visual layout.

- [ ] **Step 2: Add theme section**

Radio buttons for Dark/Light that call `useUiStore().setTheme()`.

- [ ] **Step 3: Commit**

```
feat(ui): settings page terminal visual refresh
```

---

## Phase 8: Final Verification

### Task 14: End-to-end smoke test

- [ ] **Step 1: Start backend**

```bash
uv run python -m finrobot.cli serve
```

- [ ] **Step 2: Start frontend**

```bash
cd ui && npm run dev
```

- [ ] **Step 3: Walk through every page**

1. Dashboard: market indices load, sectors load, earnings calendar loads, signals show, recent analyses show
2. Stocks/NVDA: header shows real price, all tabs show real data, DCF computes real results
3. Playground: sliders update real DCF, sensitivity matrix from real compute, Monte Carlo from real compute
4. Journal: can create entry, entries persist, P&L shows real current price
5. Library: shows real artifacts from backend
6. Settings: API keys save correctly, theme toggle works
7. AI Panel: collapses/expands smoothly, chat works with real LLM, tool calls execute

- [ ] **Step 4: Verify no fake data**

Search codebase for "placeholder" and "Coming Soon" — remove any remaining instances.

- [ ] **Step 5: Build check**

```bash
cd ui && npm run build
```
Must succeed with no errors.
