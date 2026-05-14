// WatchlistPage — Phase 3: wraps StocksPage for a specific ticker.
// When ticker is provided from Tab payload, hands it off to StocksPage URL flow.

import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { StocksPage } from '../pages/StocksPage'
import { useStocksStore } from '../stores/stocksStore'

interface WatchlistPageProps {
  ticker?: string
}

export function WatchlistPage({ ticker }: WatchlistPageProps): React.ReactElement {
  const navigate = useNavigate()
  const setCurrentTicker = useStocksStore((s) => s.setCurrentTicker)

  useEffect(() => {
    if (ticker) {
      // Sync the URL so StocksPage picks up the ticker via useParams
      setCurrentTicker(ticker)
      navigate(`/stocks/${ticker}`, { replace: true })
    }
  // Only run when ticker changes; navigate is stable
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ticker])

  return <StocksPage />
}
