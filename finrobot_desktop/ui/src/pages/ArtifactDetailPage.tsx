// ArtifactDetailPage — single artifact deep-dive route, mounted at
// `/stocks/:ticker/runs/:artifactId`.
//
// Renders the artifact as a FinRobot-parity 12-chapter long-scroll
// research report in a three-column desktop layout:
//   - sticky top toolbar  (price overlay · version switcher · diff · pdf · re-run)
//   - left sticky TOC     (12 chapters with scroll-spy active highlight)
//   - center scroll area  (chapters 00–11, each a structured Section)
//   - right sticky rail   (Version Timeline + What-if Editor placeholders)
//
// The 12 chapters are split into per-file components under
// pages/artifact-detail/chapters/. They consume artifact.outputs.structured
// (thesis / financial_modeling / peer_analysis / catalyst_analysis) plus
// inputs.raw_data for the audit dump.

import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useArtifactDetail, useV5ArtifactTimeline } from '../hooks/useV5Artifacts'
import { useAppStore } from '../stores/appStore'
import { useToastStore } from '../stores/toastStore'
import { ArtifactDiff } from '../components/ArtifactDiff'
import type { ArtifactSummaryV5 } from '../types/v5'

import { ReportToolbar } from './artifact-detail/shell/ReportToolbar'
import { ReportTOC } from './artifact-detail/shell/ReportTOC'
import type { TOCEntry } from './artifact-detail/shell/ReportTOC'
import { ReportRightRail } from './artifact-detail/shell/ReportRightRail'
import {
  ChapterCover,
  ChapterThesis,
  ChapterCompanyOverview,
  ChapterFinancialAnalysis,
  ChapterValuation,
  ChapterNews,
  ChapterSensitivity,
  ChapterCatalysts,
  ChapterTechnical,
  ChapterCompetitive,
  ChapterFinancialData,
  ChapterDisclaimer,
} from './artifact-detail/chapters'
import type {
  ArtifactStructured,
  CatalystAnalysisShape,
  DcfShape,
  PeerCompsShape,
  ThesisShape,
} from './artifact-detail/chapters'

const TOC: TOCEntry[] = [
  { id: 'cover', num: '00', title: 'Cover' },
  { id: 'thesis', num: '01', title: 'Investment Thesis' },
  { id: 'overview', num: '02', title: 'Company Overview' },
  { id: 'financial', num: '03', title: 'Financial Analysis' },
  { id: 'valuation', num: '04', title: 'Valuation Analysis' },
  { id: 'news', num: '05', title: 'Recent News & Events' },
  { id: 'sensitivity', num: '06', title: 'Sensitivity Analysis' },
  { id: 'catalysts', num: '07', title: 'Key Catalysts' },
  { id: 'technical', num: '08', title: 'Technical & Advanced' },
  { id: 'competitive', num: '09', title: 'Competitive Landscape' },
  { id: 'data', num: '10', title: 'Financial Data' },
  { id: 'disclaimer', num: '11', title: 'Disclaimer' },
]

interface ArtifactInputs {
  data_source?: string
  data_fetched_at?: string
  raw_data?: Record<string, unknown>
}

interface ArtifactComputeVersion {
  version?: string
  git_commit?: string
  formula_id?: string
  formula_warnings?: string[]
}

interface ArtifactOutputs {
  structured?: ArtifactStructured
  summary_text?: string
  warnings?: string[]
}

interface ArtifactMeta {
  created_at?: string
  source?: string
  user_id?: string
}

export function ArtifactDetailPage(): React.ReactElement {
  const { ticker, artifactId } = useParams<{ ticker: string; artifactId: string }>()
  const symbol = (ticker || '').toUpperCase()
  const navigate = useNavigate()
  const location = useLocation()
  const { data, isLoading, isError, error } = useArtifactDetail(artifactId)
  const { data: timeline } = useV5ArtifactTimeline(symbol)
  const [diffPartner, setDiffPartner] = useState<ArtifactSummaryV5 | null>(null)
  const addToast = useToastStore((s) => s.addToast)

  // React Router v6 doesn't auto-scroll to #hash on navigate; chapter
  // mini-grid in AIZone links here with /stocks/X/runs/id#thesis etc.
  // Manually scrollIntoView once the artifact resolves AND on subsequent
  // hash changes. Wait one tick so the target <section id> has mounted.
  useEffect(() => {
    if (!location.hash) return
    if (isLoading) return
    const id = decodeURIComponent(location.hash.slice(1))
    if (!id) return
    requestAnimationFrame(() => {
      const el = document.getElementById(id)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    })
  }, [location.hash, isLoading])

  // Mirror URL ticker into appStore so any hook that reads from there
  // (useHistoricalData / useQuarterlyData / etc) works when the user
  // lands directly on the report URL.
  const setStoreTicker = useAppStore((s) => s.setTicker)
  const storeTicker = useAppStore((s) => s.ticker)
  useEffect(() => {
    if (symbol && storeTicker !== symbol) {
      setStoreTicker(symbol)
    }
  }, [symbol, storeTicker, setStoreTicker])

  if (!artifactId) {
    return <CenterMessage title="缺少 artifact 编号" body="访问路径不完整 · 回工作区重新选择研报。" />
  }

  if (isLoading) {
    return (
      <div style={{ padding: 48, color: 'var(--text-muted)' }}>
        <p style={{ fontFamily: 'var(--font-mono)' }}>Loading artifact {artifactId.slice(0, 12)}…</p>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <CenterMessage
        title="加载失败"
        body={error?.message ?? '后端未返回 artifact · 检查 server 是否启动。'}
      />
    )
  }

  const inputs = data.inputs as ArtifactInputs
  const outputs = data.outputs as ArtifactOutputs
  const meta = data.meta as ArtifactMeta
  const compute_version = (data as unknown as { compute_version?: ArtifactComputeVersion })
    .compute_version

  const structured = outputs.structured ?? {}
  const thesis: ThesisShape | null = (structured.thesis as ThesisShape | undefined) ?? null
  const dcf: DcfShape | null = (structured.financial_modeling as DcfShape | undefined) ?? null
  const peers: PeerCompsShape | null =
    (structured.peer_analysis as PeerCompsShape | undefined) ?? null
  const catalysts: CatalystAnalysisShape | null =
    (structured.catalyst_analysis as CatalystAnalysisShape | undefined) ?? null

  const createdAt = meta.created_at ?? null
  const versionLabel = createdAt
    ? new Date(createdAt).toLocaleDateString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
      })
    : data.id.slice(0, 12)
  const computeVersionStr = compute_version?.version ?? null

  // Pre-compute diff partner candidate: the most recent prior artifact of the
  // same type, surfaced by the Diff button. ArtifactDiff handles its own UI.
  function openDiff(): void {
    if (!data) return
    const list = (timeline ?? []).filter((a) => a.type === data.type && a.id !== artifactId)
    if (list.length === 0) {
      addToast({
        type: 'info',
        title: '无可对比版本',
        description: `${symbol} 只有一份 ${data.type} 研报 · 重跑 research 累积版本后即可 diff`,
      })
      return
    }
    setDiffPartner(list[0])
  }

  return (
    <div data-testid="artifact-detail-page" style={{ position: 'relative', minHeight: '100vh' }}>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '240px 1fr 280px',
          maxWidth: 1480,
          margin: '0 auto',
          gap: 24,
          padding: '0 24px 80px',
          alignItems: 'start',
        }}
      >
        <div
          style={{
            gridColumn: '1 / -1',
            paddingTop: 16,
          }}
        >
          <ReportToolbar
            ticker={symbol}
            artifactId={artifactId}
            reportType={data.type}
            reportVersionLabel={versionLabel}
            targetPrice={thesis?.price_target ?? null}
            timeline={timeline ?? []}
            onOpenDiff={openDiff}
          />
        </div>

        <ReportTOC entries={TOC} />

        <main style={{ minWidth: 0, padding: '12px 0 60px' }}>
          <ChapterCover
            ticker={symbol}
            thesis={thesis}
            createdAt={createdAt}
            artifactId={data.id}
            computeVersion={computeVersionStr}
            reportType={data.type}
          />
          <ChapterThesis thesis={thesis} />
          <ChapterCompanyOverview thesis={thesis} />
          <ChapterFinancialAnalysis dcf={dcf} rawData={inputs.raw_data ?? null} />
          <ChapterValuation dcf={dcf} thesis={thesis} />
          <ChapterNews thesis={thesis} />
          <ChapterSensitivity dcf={dcf} />
          <ChapterCatalysts catalysts={catalysts} thesis={thesis} />
          <ChapterTechnical ticker={symbol} />
          <ChapterCompetitive peers={peers} thesis={thesis} />
          <ChapterFinancialData
            rawData={inputs.raw_data ?? null}
            dataSource={inputs.data_source ?? null}
            fetchedAt={inputs.data_fetched_at ?? null}
          />
          <ChapterDisclaimer
            artifactId={data.id}
            createdAt={createdAt}
            computeVersion={computeVersionStr}
          />

          {(outputs.warnings && outputs.warnings.length > 0) ||
          (compute_version?.formula_warnings && compute_version.formula_warnings.length > 0) ? (
            <section
              data-testid="report-warnings"
              style={{
                margin: '32px 0',
                padding: '14px 18px',
                background: 'rgba(217, 119, 6, 0.06)',
                border: '1px solid rgba(217, 119, 6, 0.32)',
                borderRadius: 'var(--radius-sm)',
                fontSize: 12,
                color: 'var(--warning)',
              }}
            >
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10.5,
                  letterSpacing: '0.08em',
                  marginBottom: 6,
                }}
              >
                ⚠ COMPUTE WARNINGS
              </div>
              <ul style={{ margin: 0, paddingLeft: 18 }}>
                {(outputs.warnings ?? []).map((w, i) => (
                  <li key={`o-${i}`} style={{ marginBottom: 4 }}>
                    {w}
                  </li>
                ))}
                {(compute_version?.formula_warnings ?? []).map((w, i) => (
                  <li key={`f-${i}`} style={{ marginBottom: 4 }}>
                    {w}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <div
            style={{
              marginTop: 40,
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              gap: 16,
            }}
          >
            <button
              type="button"
              onClick={() => navigate(`/stocks/${symbol}`)}
              style={navBtnStyle}
            >
              ← 回 {symbol} 工作区
            </button>
            <button
              type="button"
              onClick={() => {
                // navigate(-1) jumps out of the SPA entirely when the user
                // landed here from a bookmark / direct link / fresh tab
                // (no history stack). Fall back to landing in that case.
                if (window.history.length > 1) {
                  navigate(-1)
                } else {
                  navigate('/stocks')
                }
              }}
              style={navBtnStyle}
            >
              上一页
            </button>
          </div>
        </main>

        <ReportRightRail
          ticker={symbol}
          currentArtifactId={artifactId}
          timeline={timeline ?? []}
          reportType={data.type}
          wacc={dcf?.wacc ?? null}
          terminalGrowth={dcf?.inputs?.terminal_growth_rate ?? null}
        />
      </div>

      {diffPartner && (
        <ArtifactDiff
          artifactA={{
            id: artifactId,
            created_at: createdAt ?? diffPartner.created_at,
            headline: (outputs.summary_text ?? '').slice(0, 220),
            type: data.type,
          }}
          artifactB={{
            id: diffPartner.id,
            created_at: diffPartner.created_at,
            headline: diffPartner.headline,
            type: diffPartner.type,
          }}
          onClose={() => setDiffPartner(null)}
        />
      )}
    </div>
  )
}

function CenterMessage({ title, body }: { title: string; body: string }): React.ReactElement {
  return (
    <div style={{ padding: 48, maxWidth: 720, margin: '40px auto' }}>
      <h2
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 22,
          letterSpacing: 2,
          color: 'var(--text-primary)',
          marginBottom: 8,
        }}
      >
        {title}
      </h2>
      <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>{body}</p>
    </div>
  )
}

const navBtnStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
  color: 'var(--text-muted)',
  background: 'transparent',
  border: '1px solid var(--border-soft)',
  borderRadius: 8,
  padding: '8px 14px',
  cursor: 'pointer',
}
