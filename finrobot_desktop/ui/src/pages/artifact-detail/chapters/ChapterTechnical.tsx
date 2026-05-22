// Chapter 08 — Technical & Advanced Analysis. Live price chip pulled
// from the realtime hook, paired with the warning that deep technical
// payloads (Monte Carlo distribution, sniper levels) are computed
// on-demand via /api/compute/* rather than baked into the artifact.

import { Chapter, KvGrid, SubChapter } from './ChapterBase'
import { useTickerPrice, useTickerFinancials } from '../../../hooks/useTickerData'

export function ChapterTechnical({ ticker }: { ticker: string }): React.ReactElement {
  const { data: price } = useTickerPrice(ticker)
  const { data: fin } = useTickerFinancials(ticker)
  const current = price?.current_price ?? null
  const changePct = price?.change_pct ?? null
  const high52 = fin?.market?.price_52w_high ?? null
  const low52 = fin?.market?.price_52w_low ?? null
  const beta = fin?.market?.beta ?? null
  const range52Position =
    current !== null && high52 !== null && low52 !== null && high52 > low52
      ? ((current - low52) / (high52 - low52)) * 100
      : null

  const cells = [
    current !== null && {
      label: 'Current Price',
      value: `$${current.toFixed(2)}`,
      tone: typeof changePct === 'number' && changePct >= 0 ? ('up' as const) : ('down' as const),
      delta:
        typeof changePct === 'number'
          ? `${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}%`
          : undefined,
    },
    low52 !== null && { label: '52W Low', value: `$${low52.toFixed(2)}` },
    high52 !== null && { label: '52W High', value: `$${high52.toFixed(2)}` },
    range52Position !== null && {
      label: '52W Position',
      value: `${range52Position.toFixed(0)}%`,
      delta: range52Position >= 80 ? 'near high' : range52Position <= 20 ? 'near low' : 'mid-range',
    },
    beta !== null && { label: 'Beta (5Y)', value: beta.toFixed(2), delta: 'vs SPX' },
  ].filter((c): c is { label: string; value: string; delta?: string; tone?: 'up' | 'down' } => c !== false)

  return (
    <Chapter
      id="technical"
      num="08"
      title="Technical &amp; Advanced Analysis"
      sub="Price Action · Levels · Quant Overlays"
    >
      {cells.length > 0 ? (
        <KvGrid cells={cells} columns={4} />
      ) : (
        <p style={mutedNote}>价格数据未就绪 — 检查 server 是否启动 + ticker 是否有效</p>
      )}

      <SubChapter heading="Quant Overlays">
        <p
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: 13,
            lineHeight: 1.7,
            color: 'var(--text-secondary)',
          }}
        >
          Monte Carlo simulation, support / resistance levels (sniper), and historical valuation
          bands are computed on-demand via{' '}
          <code style={{ color: 'var(--accent-cyan)', fontSize: 12 }}>/api/compute/monte-carlo</code>
          , <code style={{ color: 'var(--accent-cyan)', fontSize: 12 }}>/api/compute/sniper</code>,
          and{' '}
          <code style={{ color: 'var(--accent-cyan)', fontSize: 12 }}>
            /api/valuation/historical-bands
          </code>
          . Run them from the workspace's interactive overlay (P4 — desktop augmentation).
        </p>
      </SubChapter>
    </Chapter>
  )
}

const mutedNote: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  color: 'var(--text-muted)',
  padding: '14px 18px',
  background: 'rgba(15, 15, 34, 0.5)',
  border: '1px dashed var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
}
