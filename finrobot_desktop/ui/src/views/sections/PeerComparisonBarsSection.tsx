// v5 §6.x 同业倍数柱 — side-by-side EV/EBITDA & P/E bars across the peer
// set with the target company highlighted (chart-5 orange). Companion to
// the peer table; the table gives exact numbers, the chart gives the
// visual ranking at a glance.

import { useArtifactDetail, useLatestArtifact } from '../../hooks/useV5Artifacts'
import PeerComparisonChart from '../../components/charts/PeerComparisonChart'

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card)',
}

interface CompanyFinancials {
  ticker: string
  pe_ratio?: number | null
  ev_ebitda?: number | null
}

interface PeerComps {
  target?: CompanyFinancials
  peers?: CompanyFinancials[]
}

interface PeerComparisonBarsSectionProps {
  ticker: string
}

export function PeerComparisonBarsSection({
  ticker,
}: PeerComparisonBarsSectionProps): React.ReactElement {
  const comps = useLatestArtifact(ticker, 'comps').latest
  const equity = useLatestArtifact(ticker, 'equity_research').latest
  const source = comps ?? equity
  const { data: detail, isLoading } = useArtifactDetail(source?.id)

  const peerComps = extractPeerComps(detail?.outputs)
  const chartData = buildBarData(peerComps)

  return (
    <section id="sec-peer-bars" style={SECTION_STYLE}>
      <header style={{ marginBottom: 10 }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>📊 同业倍数对比</h2>
        <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
          EV/EBITDA · PE · 目标公司用橙色高亮
        </span>
      </header>

      {!source && (
        <p style={{ fontSize: 12.5, color: 'var(--text-soft)' }}>
          先跑同业对标。
        </p>
      )}
      {isLoading && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>加载中…</p>
      )}
      {!isLoading && source && chartData.length === 0 && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>同业未披露足够的倍数</p>
      )}
      {chartData.length > 0 && <PeerComparisonChart data={chartData} title="" />}
    </section>
  )
}

function extractPeerComps(
  outputs: Record<string, unknown> | undefined,
): PeerComps | undefined {
  if (!outputs) return undefined
  const structured = outputs.structured as Record<string, unknown> | undefined
  if (!structured) return undefined
  return (
    (structured.peer_analysis as PeerComps | undefined) ??
    ((structured as unknown as PeerComps).target
      ? (structured as unknown as PeerComps)
      : undefined)
  )
}

function buildBarData(
  comps: PeerComps | undefined,
): Record<string, number | string | boolean | null>[] {
  if (!comps?.target || !comps.peers?.length) return []
  const rows: Record<string, number | string | boolean | null>[] = []
  rows.push({
    ticker: comps.target.ticker,
    ev_ebitda: comps.target.ev_ebitda ?? null,
    pe_ratio: comps.target.pe_ratio ?? null,
    is_target: true,
  })
  for (const p of comps.peers) {
    rows.push({
      ticker: p.ticker,
      ev_ebitda: p.ev_ebitda ?? null,
      pe_ratio: p.pe_ratio ?? null,
      is_target: false,
    })
  }
  return rows
}
