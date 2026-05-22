# Cosmic UI 整体改造 · Stage A · 基础壳

> 决策来源：2026-05-22 brainstorming session  
> 三段拆分：A 壳 → B 内容 → C 收尾。本文档只覆盖 Stage A。  
> Stage B/C 拆出独立 spec。

## 决策摘要

| 项 | 选择 |
|---|---|
| Watchlist 归属 | 右侧 RightChatPanel 上下 tab 拆分（上：Watchlist，下：AI 对话） |
| TitleBar 三色控件 | Tauri 原生 overlay（保持现状） |
| Spline 3D 机器人 | Hero 右 40% 主角位 |
| Landing 范围 | spec §2.2 全件（含 hit-rate 横幅 + 最近研究 + 热门 chip） |
| AnchorNav | 删除，section 导航搬到 CmdK |
| Custom Cursor | 全局默认开 + Settings 切换 |
| 后端补齐 | 与 Stage A 同 branch 一起干完 |

## 交付物

**后端**
- `finagent/engine/data/quote_batch.py` — 批量 yfinance helper
- `finagent/engine/aggregations/{hit_rate_overview,recent_research}.py` — 叶层纯函数 + 单测
- `finagent/routes/dashboard.py` — `/api/dashboard/hit-rate` + `/api/dashboard/recent-research` + integration test

**前端**
- `ui/src/App.css` — cosmic token 全量替换（保留 layout 类名，重定义颜色 / 加 glow / 加 Audiowide 字体引）
- `ui/src/lib/cursorCanvas.ts` + `components/CursorCanvas.tsx` — Bezier 12 弹簧拖尾
- `ui/src/components/{SplineHero,StarsDriftBG}.tsx`
- `ui/src/layout/RightChatPanel/{index,WatchlistTab,AiChatTab}.tsx` — 上下 tab 拆分
- `ui/src/layout/TitleBar.tsx` — brand-dot + halo ⌘K
- `ui/src/layout/Sidebar.tsx` — 砍到 64px slim icon-only
- `ui/src/layout/CmdKOverlay.tsx` — 加 section 导航 panel
- `ui/src/pages/landing/{StocksLandingHero,HitRateBanner,RecentResearchStrip,HotTickerChips}.tsx`
- `ui/src/hooks/{useDashboardHitRate,useDashboardRecentResearch}.ts`
- `ui/src/views/TickerHero.tsx` — 让出右 40% 给 SplineHero
- `ui/src/views/StockWorkspace.tsx` — 删 AnchorNav
- `ui/src/views/SettingsView.tsx` — 加桌面动效 toggle
- `ui/src/stores/uiStore.ts` — 加 `cursorTrailEnabled` persist 字段

**删除**
- `ui/src/views/AnchorNav.tsx`

## 验收

1. `pytest -q` 全过
2. `ruff check finagent tests` + `mypy finagent` 全过
3. `cd ui && npm run build && npm run test` 全过
4. 手测 golden path：
   - `/stocks` 看见 Hit-Rate 横幅 + 最近研究横滚（数据真的来自后端，不是 stub）
   - `/stocks/AAPL` 看见 Spline 机器人 + cosmic hero
   - 按 `⌘K` 弹出 section 导航面板
   - Settings 切换「桌面动效」cursor 拖尾立即生效
   - Watchlist 在右侧面板顶端 tab，AI 对话在下方 tab

## 范围 OUT

- 31 sections 内部 cosmic 化（Stage B）
- inline SVG 图表 neon glow 替换（Stage B）
- HeroVerdict 大徽章规范化（Stage B）
- AnchorNav 删除后残留 dead route / dead component 审计（Stage C）
