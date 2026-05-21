// v5 Stock Workspace — the single-page ticker view that replaces the old
// 8-tab layout (spec §3). Owns nothing of its own; assembles the sticky
// hero, anchor nav, and a long vertical list of <section> slots whose
// concrete content comes from PR9–PR15.
//
// During the v5 rollout we mount this at /stock/:ticker (singular) while
// /stocks/:ticker keeps the legacy multi-tab StocksPage until PR15 is
// merged. That parallel keeps the existing pages working without forcing
// a flag-day cutover; users following old links land on the legacy view
// and follow links from the new artifact components land here.

import { useParams } from 'react-router-dom'
import { TickerHero } from './TickerHero'
import { AnchorNav } from './AnchorNav'
import { PipelineProgressPanel } from './PipelineProgressPanel'

const PLACEHOLDER_SECTION_STYLE: React.CSSProperties = {
  border: '1px dashed var(--border-soft)',
  borderRadius: 8,
  padding: 24,
  margin: '12px 0',
  color: 'var(--text-faint)',
  fontSize: 13,
  background: 'var(--bg-card, #fff)',
}

interface PlaceholderProps {
  id: string
  title: string
  body: string
}

function SectionPlaceholder({ id, title, body }: PlaceholderProps): React.ReactElement {
  return (
    <section id={id} style={PLACEHOLDER_SECTION_STYLE}>
      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)', marginBottom: 4 }}>
        {title}
      </div>
      <div>{body}</div>
    </section>
  )
}

export function StockWorkspace(): React.ReactElement {
  const { ticker } = useParams<{ ticker: string }>()
  const symbol = (ticker || '').toUpperCase()

  if (!symbol) {
    return (
      <div style={{ padding: 48, color: 'var(--text-faint)' }}>
        缺少 ticker — 请通过搜索或自选股进入。
      </div>
    )
  }

  return (
    <div data-testid="stock-workspace" style={{ minHeight: '100vh' }}>
      <TickerHero ticker={symbol} />
      <AnchorNav />
      <main
        style={{
          maxWidth: 960,
          margin: '0 auto',
          padding: '12px 24px 96px',
        }}
      >
        <PipelineProgressPanel ticker={symbol} />
        {/*
          The section list below mirrors spec §6's IA. Until PR9–PR15 wire
          real components in, each slot shows a "coming in PR X" placeholder
          that's still clickable from the anchor nav, so design + IA review
          can happen against the actual scroll behaviour.
        */}
        <SectionPlaceholder
          id="sec-now"
          title="🎯 当前判断"
          body="HERO 卡片 — PR9 实施。需要 latest equity_research artifact 的 signal / target / 当时-现在价。"
        />
        <SectionPlaceholder
          id="sec-catalyst"
          title="🔥 催化剂"
          body="6 类催化剂 top 4 卡片 — PR10。复用现有 /api/data/{ticker}/catalysts endpoint。"
        />
        <SectionPlaceholder
          id="sec-risk"
          title="⚠️ 风险因素"
          body="2×2 风险 grid — PR10。来源 thesis step 的 risks 字段。"
        />
        <SectionPlaceholder
          id="sec-football"
          title="🏟️ 估值范围 (Football Field)"
          body="4 valuation + 2 multiple 横向 box plot — PR11 (ADR-C)。"
        />
        <SectionPlaceholder
          id="sec-sensitivity"
          title="📉 敏感性分析"
          body="DCF 5×5 热力图 — PR12。来源 /api/compute/dcf-sensitivity。"
        />
        <SectionPlaceholder
          id="sec-band"
          title="📊 历史估值带"
          body="EV/EBITDA + P/FCF 时间序列 + 分位带 — PR12。后端 PR3 已就位。"
        />
        <SectionPlaceholder
          id="sec-data"
          title="📊 数据快照"
          body="4 card 市值 / PE / 7d mini chart / 下次财报 — PR9 / 既有组件改造。"
        />
        <SectionPlaceholder
          id="sec-financials"
          title="💰 财务报表"
          body="4 季度营收 / 毛利率 / 净利润 / YoY — PR13 (FinancialsTab 拆分)。"
        />
        <SectionPlaceholder
          id="sec-performance"
          title="📈 走势分析"
          body="YTD / 波动率 / 夏普 / 距 52w 高 — PR13 (PerformanceTab 拆分)。"
        />
        <SectionPlaceholder
          id="sec-peers"
          title="🏢 同业对标"
          body="5 行表格（NVDA + 4 peer）— PR13 (PeersTab 拆分)。"
        />
        <SectionPlaceholder
          id="sec-news"
          title="📰 新闻动态"
          body="最近 12 条 + 情绪 dot — PR14 (NewsTab 改造)。"
        />
        <SectionPlaceholder
          id="sec-sentiment"
          title="👥 散户情绪"
          body="adanos provider 数据 — PR14。后端 PR4b 已就位 /api/sentiment/{ticker}。"
        />
        <SectionPlaceholder
          id="sec-earnings"
          title="🎙️ 财报电话会"
          body="下次电话会 + 上次要点 — PR14 (EarningsCallPanel 改造)。"
        />
        <SectionPlaceholder
          id="sec-research"
          title="📚 我的研究"
          body="ArtifactSummary feed + 命中率 banner + sparkline — PR15。后端 PR1 已就位 signal 字段。"
        />
      </main>
    </div>
  )
}
