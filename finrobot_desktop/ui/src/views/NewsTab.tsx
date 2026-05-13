/**
 * NewsTab — 新闻 tab.
 *
 * Aggregates:
 *  - NewsFeed (existing component — live news + sentiment)
 *  - CatalystPanel (existing component — structured catalyst events)
 *  - EarningsCallPanel (existing component — FMP earnings call transcripts)
 *
 * Individual sections degrade gracefully when their respective endpoints fail.
 */

import { useAppStore } from '../stores/appStore'
import NewsFeed from '../components/NewsFeed'
import CatalystPanel from '../components/CatalystPanel'
import EarningsCallPanel from '../components/EarningsCallPanel'
import { useCatalysts } from '../hooks/useCatalysts'

export default function NewsTab() {
  const ticker = useAppStore((s) => s.ticker)
  const catalysts = useAppStore((s) => s.catalysts)
  const catalystsLoading = useAppStore((s) => s.catalystsLoading)

  // Ensure catalysts are loaded for this ticker
  useCatalysts()

  if (!ticker) {
    return (
      <div className="tab-content news-tab">
        <div className="empty-state-card">
          <p>Select a ticker to view news and catalysts</p>
        </div>
      </div>
    )
  }

  return (
    <div className="tab-content news-tab">
      {/* News feed */}
      <section className="chart-section">
        <NewsFeed />
      </section>

      {/* Catalyst events */}
      <section className="chart-section">
        <CatalystPanel catalysts={catalysts ?? []} loading={catalystsLoading} />
      </section>

      {/* Earnings call transcripts */}
      <section className="chart-section">
        <EarningsCallPanel />
      </section>
    </div>
  )
}
