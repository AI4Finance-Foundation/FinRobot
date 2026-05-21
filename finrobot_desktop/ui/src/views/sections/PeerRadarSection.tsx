// v5 §6.x 同业雷达 — 6-dimension radar comparing target company vs the
// median of the peer set on profitability / valuation / efficiency axes.
// Built on the comps or equity_research artifact's peer_analysis blob.

import { useArtifactDetail, useLatestArtifact } from '../../hooks/useV5Artifacts'
import CompanyRadarChart from '../../components/charts/CompanyRadarChart'

const SECTION_STYLE: React.CSSProperties = {
  border: '1px solid var(--border)',
  borderRadius: 12,
  padding: 20,
  margin: '12px 0',
  background: 'var(--bg-card, #fff)',
}

interface CompanyFinancials {
  ticker: string
  gross_margin?: number | null
  operating_margin?: number | null
  pe_ratio?: number | null
  ev_ebitda?: number | null
  ev_revenue?: number | null
  net_income?: number | null
  revenue?: number | null
}

interface PeerComps {
  target?: CompanyFinancials
  peers?: CompanyFinancials[]
  median_ev_ebitda?: number | null
  median_pe?: number | null
}

interface PeerRadarSectionProps {
  ticker: string
}

export function PeerRadarSection({
  ticker,
}: PeerRadarSectionProps): React.ReactElement {
  const comps = useLatestArtifact(ticker, 'comps').latest
  const equity = useLatestArtifact(ticker, 'equity_research').latest
  const source = comps ?? equity
  const { data: detail, isLoading } = useArtifactDetail(source?.id)

  const peerComps = extractPeerComps(detail?.outputs)
  const chartData = buildRadarData(peerComps)

  return (
    <section id="sec-peer-radar" style={SECTION_STYLE}>
      <header style={{ marginBottom: 10 }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>🕸️ 同业雷达</h2>
        <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>
          目标公司 vs 同业中位数 · 数值已 0–100 标准化
        </span>
      </header>

      {!source && (
        <p style={{ fontSize: 12.5, color: 'var(--text-soft)' }}>
          跑「单独同业对标」或「AI 完整研报」后展示雷达对比。
        </p>
      )}
      {isLoading && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>加载中…</p>
      )}
      {!isLoading && source && chartData.length === 0 && (
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>同业数据不足以画雷达</p>
      )}
      {chartData.length > 0 && <CompanyRadarChart data={chartData} title="" />}
    </section>
  )
}

function extractPeerComps(
  outputs: Record<string, unknown> | undefined,
): PeerComps | undefined {
  if (!outputs) return undefined
  const structured = outputs.structured as Record<string, unknown> | undefined
  if (!structured) return undefined
  // equity_research wraps under peer_analysis; comps puts it at root
  const candidate =
    (structured.peer_analysis as PeerComps | undefined) ??
    ((structured as unknown as PeerComps).target ? (structured as unknown as PeerComps) : undefined)
  return candidate
}

// Radar wants each dimension on a 0–100 scale where higher = better.
// For valuation (PE / EV-EBITDA) we invert so "cheap" still reads as
// "outward" on the radar. Median-of-peers anchors at 50 by definition.
function buildRadarData(
  comps: PeerComps | undefined,
): Record<string, number | string | boolean | null>[] {
  if (!comps?.target || !comps.peers?.length) return []

  const target = comps.target
  const peers = comps.peers
  const dims: {
    key: keyof CompanyFinancials
    label: string
    inverted: boolean
  }[] = [
    { key: 'gross_margin', label: '毛利率', inverted: false },
    { key: 'operating_margin', label: '营业利润率', inverted: false },
    { key: 'pe_ratio', label: 'PE (低=好)', inverted: true },
    { key: 'ev_ebitda', label: 'EV/EBITDA (低=好)', inverted: true },
    { key: 'ev_revenue', label: 'EV/Rev (低=好)', inverted: true },
    { key: 'net_income', label: '净利润规模', inverted: false },
  ]

  const out: Record<string, number | string | boolean | null>[] = []
  for (const d of dims) {
    const targetVal = numOrNull(target[d.key])
    const peerVals = peers
      .map((p) => numOrNull(p[d.key]))
      .filter((v): v is number => v !== null)
    if (targetVal === null || peerVals.length === 0) continue

    const median = peerVals.sort((a, b) => a - b)[Math.floor(peerVals.length / 2)]
    const allVals = [targetVal, ...peerVals]
    const min = Math.min(...allVals)
    const max = Math.max(...allVals)
    const range = max - min || 1

    let tNorm = ((targetVal - min) / range) * 100
    let mNorm = ((median - min) / range) * 100
    if (d.inverted) {
      tNorm = 100 - tNorm
      mNorm = 100 - mNorm
    }
    out.push({
      dimension: d.label,
      value: Math.round(tNorm),
      benchmark: Math.round(mNorm),
    })
  }
  return out
}

function numOrNull(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null
}
