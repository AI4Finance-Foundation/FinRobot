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
import { HeroVerdict } from './sections/HeroVerdict'
import { DataSnapshot } from './sections/DataSnapshot'
import { CatalystGrid } from './sections/CatalystGrid'
import { RiskGrid } from './sections/RiskGrid'
import { FootballField } from './sections/FootballField'
import { SensitivityHeatmap } from './sections/SensitivityHeatmap'
import { HistoricalBandChart } from './sections/HistoricalBandChart'
import { FinancialsSection } from './sections/FinancialsSection'
import { PerformanceSection } from './sections/PerformanceSection'
import { PeersSection } from './sections/PeersSection'
import { NewsList } from './sections/NewsList'
import { SentimentCard } from './sections/SentimentCard'
import { MyResearchFeed } from './sections/MyResearchFeed'

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
        {/* v5 sections in spec §6 order. PR13 (FinancialsSection /
            PerformanceSection / PeersSection) lives in the legacy view
            tabs the user is independently modifying — they'll fold into
            this workspace once those refactors land. */}
        <HeroVerdict ticker={symbol} />
        <CatalystGrid ticker={symbol} />
        <RiskGrid ticker={symbol} />
        <FootballField ticker={symbol} />
        <SensitivityHeatmap ticker={symbol} />
        <HistoricalBandChart ticker={symbol} />
        <DataSnapshot ticker={symbol} />
        <FinancialsSection ticker={symbol} />
        <PerformanceSection ticker={symbol} />
        <PeersSection ticker={symbol} />
        <NewsList ticker={symbol} />
        <SentimentCard ticker={symbol} />
        <SectionPlaceholder
          id="sec-earnings"
          title="🎙️ 财报电话会"
          body="下次电话会 + 上次要点 — PR14 子任务（EarningsCallPanel 用户 in-flight 改造完后接入）。"
        />
        <MyResearchFeed ticker={symbol} />
      </main>
    </div>
  )
}
