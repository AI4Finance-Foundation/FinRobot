import { useAppStore } from '../stores/appStore'
import { fmtPrice, fmtPct } from '../utils/formatters'

export default function StockHeader() {
  const ticker = useAppStore((s) => s.ticker)
  const currentPrice = useAppStore((s) => s.currentPrice)
  const priceChange = useAppStore((s) => s.priceChange)
  const priceChangePct = useAppStore((s) => s.priceChangePct)

  if (!ticker) return null

  const changeColor = (priceChange ?? 0) >= 0 ? 'var(--green)' : 'var(--red)'

  return (
    <div className="stock-header">
      <div className="stock-header-left">
        <span className="stock-ticker">{ticker}</span>
        {currentPrice != null && (
          <span className="stock-price">{fmtPrice(currentPrice)}</span>
        )}
        {priceChange != null && priceChangePct != null && (
          <span className="stock-change" style={{ color: changeColor }}>
            {priceChange >= 0 ? '+' : ''}{priceChange.toFixed(2)} ({fmtPct(priceChangePct / 100)})
          </span>
        )}
      </div>
    </div>
  )
}
