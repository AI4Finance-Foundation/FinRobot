import { useAppStore } from '../stores/appStore'
import { useMonteCarloCompute } from '../hooks/useCompute'
import MonteCarloChart from './charts/MonteCarloChart'

export default function MonteCarloSection() {
  const dcfInputs = useAppStore((s) => s.dcfInputs)
  const currentPrice = useAppStore((s) => s.currentPrice)
  const monteCarloResult = useAppStore((s) => s.monteCarloResult)
  const monteCarloLoading = useAppStore((s) => s.monteCarloLoading)
  const setMonteCarloResult = useAppStore((s) => s.setMonteCarloResult)
  const setMonteCarloLoading = useAppStore((s) => s.setMonteCarloLoading)

  const { mutate: runMonteCarlo } = useMonteCarloCompute()

  if (!dcfInputs) {
    return (
      <div className="empty-state-card">
        <p>Run DCF Analysis first to enable Monte Carlo simulation</p>
      </div>
    )
  }

  const handleRun = () => {
    if (!currentPrice) return
    setMonteCarloLoading(true)
    runMonteCarlo(
      { inputs: dcfInputs, current_price: currentPrice, n_simulations: 10000 },
      {
        onSuccess: (data) => {
          setMonteCarloResult(data)
          setMonteCarloLoading(false)
        },
        onError: () => setMonteCarloLoading(false),
      }
    )
  }

  if (monteCarloResult) {
    return <MonteCarloChart result={monteCarloResult} currentPrice={currentPrice} />
  }

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">Monte Carlo Simulation</span>
        <button className="btn-sm" onClick={handleRun} disabled={monteCarloLoading || !currentPrice}>
          {monteCarloLoading ? 'Running...' : 'Run (10K simulations)'}
        </button>
      </div>
      <div className="card-body">
        {monteCarloLoading && (
          <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            Running 10,000 simulations…
          </p>
        )}
      </div>
    </div>
  )
}
