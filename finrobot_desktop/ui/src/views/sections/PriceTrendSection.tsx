// v5 §6.x 股价走势 — wraps the existing PriceChart component (which
// self-fetches /api/data/{ticker}/price and provides 1M/3M/6M/1Y/ALL
// time-range tabs) in the section card frame so it lives at sec-price
// in the anchor nav.

import { useEffect } from 'react'
import { useAppStore } from '../../stores/appStore'
import PriceChart from '../../components/charts/PriceChart'

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card)',
}

interface PriceTrendSectionProps {
  ticker: string
}

export function PriceTrendSection({
  ticker,
}: PriceTrendSectionProps): React.ReactElement {
  const setTicker = useAppStore((s) => s.setTicker)
  const storeTicker = useAppStore((s) => s.ticker)

  // PriceChart reads its own ticker from appStore via useAppStore. The v5
  // StockWorkspace routes by URL param, so we have to mirror that into the
  // legacy store the chart depends on. Cheap effect, no re-render storm:
  // setTicker is a stable zustand setter.
  useEffect(() => {
    if (ticker && storeTicker !== ticker) {
      setTicker(ticker)
    }
  }, [ticker, storeTicker, setTicker])

  return (
    <section id="sec-price" style={SECTION_STYLE}>
      <header style={{ marginBottom: 10 }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>📈 股价走势</h2>
      </header>
      <PriceChart title="" />
    </section>
  )
}
