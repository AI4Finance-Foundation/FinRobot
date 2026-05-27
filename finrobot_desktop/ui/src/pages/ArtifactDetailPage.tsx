// ArtifactDetailPage — single artifact deep-dive route, mounted at
// `/stocks/:ticker/runs/:artifactId`.
//
// Renders the artifact as a 12-chapter investment-bank-grade long-scroll
// research report in a three-column desktop layout:
//   - sticky top toolbar  (price overlay · version switcher · diff · re-run)
//   - left sticky TOC     (12 chapters with scroll-spy active highlight)
//   - center scroll area  (chapters 00–11, each a structured Section)
//   - right sticky rail   (Version Timeline + live DCF What-if Editor)
//
// The 12 chapters are split into per-file components under
// pages/artifact-detail/chapters/. They consume artifact.outputs.structured
// (thesis / financial_modeling / peer_analysis / catalyst_analysis) plus
// inputs.raw_data for the audit dump.

import { useEffect, useState } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { useArtifactDetail, useV5ArtifactTimeline } from '../hooks/useV5Artifacts'
import { useNavMemoryStore } from '../stores/navMemoryStore'
import { useToastStore } from '../stores/toastStore'
import { ArtifactDiff } from '../components/ArtifactDiff'
import type { ArtifactSummaryV5 } from '../types/v5'
import { useI18n } from '../i18n'
import { formatDate } from '../utils/format'
import { mapErrorToUserMessage } from '../utils/errorMessage'

import { ReportToolbar } from './artifact-detail/shell/ReportToolbar'
import { ReportTOC } from './artifact-detail/shell/ReportTOC'
import { ReportRightRail } from './artifact-detail/shell/ReportRightRail'
import { ReportStatusBar } from './artifact-detail/shell/ReportStatusBar'
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
  TechnicalAnalysisShape,
  ThesisShape,
} from './artifact-detail/chapters'

import { allChapterLabels } from './artifact-detail/chapters/labels'

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
  const location = useLocation()
  const { data, isLoading, isError, error } = useArtifactDetail(artifactId)
  const { data: timeline } = useV5ArtifactTimeline(symbol)
  const { locale, t } = useI18n()
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

  // Sidebar restores this deep path when the user clicks 个股 after
  // detouring through /settings — see useNavMemoryStore.
  const setLastStocksPath = useNavMemoryStore((s) => s.setLastStocksPath)
  useEffect(() => {
    if (symbol) setLastStocksPath(location.pathname)
  }, [location.pathname, symbol, setLastStocksPath])

  if (!artifactId) {
    return <CenterMessage title="缺少研报编号" body="访问路径不完整，请回工作区重新选择研报。" />
  }

  if (isLoading) {
    return (
      <div style={{ padding: 48, color: 'var(--text-muted)' }}>
        <p style={{ fontFamily: 'var(--font-mono)' }}>加载研报中…</p>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <CenterMessage
        title="加载失败"
        body={mapErrorToUserMessage(error) || '无法加载研报，请稍后重试。'}
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
  const technical: TechnicalAnalysisShape | null =
    (structured.technical_analysis as TechnicalAnalysisShape | undefined) ?? null

  const createdAt = meta.created_at ?? null
  const computeVersionStr = compute_version?.version ?? null

  // Derive a human-friendly version number (v1/v2/v3) from the timeline.
  // Timeline arrives newest→oldest; oldest is v1, newest is v(N). If this
  // artifact isn't in the timeline (race condition during a fresh run),
  // fall back to N/A and keep totalVersions at 0 so the cover hides it.
  const sameTypeTimeline = (timeline ?? []).filter((a) => a.type === data.type)
  const totalVersions = sameTypeTimeline.length
  const idxFromEnd = sameTypeTimeline.findIndex((a) => a.id === artifactId)
  const versionNumber = idxFromEnd === -1 ? null : totalVersions - idxFromEnd
  const versionLabel =
    versionNumber !== null
      ? `v${versionNumber}${createdAt ? ` · ${formatDate(createdAt, locale, 'short')}` : ''}`
      : createdAt
        ? formatDate(createdAt, locale, 'short')
        : data.id.slice(0, 12)

  // Pre-compute diff partner candidate: the most recent prior artifact of the
  // same type, surfaced by the Diff button. ArtifactDiff handles its own UI.
  function openDiff(): void {
    if (!data) return
    const list = (timeline ?? []).filter((a) => a.type === data.type && a.id !== artifactId)
    if (list.length === 0) {
      addToast({
        type: 'info',
        title: '无可对比版本',
        description: `${symbol} 只有这一份研报 · 重新生成累积版本后即可对比`,
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
          gridTemplateColumns: '184px 1fr 268px',
          maxWidth: 1640,
          margin: '0 auto',
          gap: 18,
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

        <ReportTOC
          entries={allChapterLabels(locale).map((c) => ({ id: c.id, num: c.num, title: c.title }))}
        />

        <main style={{ minWidth: 0, padding: '12px 0 60px' }}>
          <ChapterCover
            ticker={symbol}
            thesis={thesis}
            createdAt={createdAt}
            artifactId={data.id}
            computeVersion={computeVersionStr}
            reportType={data.type}
            versionNumber={versionNumber}
            totalVersions={totalVersions}
          />
          <ChapterThesis thesis={thesis} />
          <ChapterCompanyOverview thesis={thesis} />
          <ChapterFinancialAnalysis ticker={symbol} dcf={dcf} rawData={inputs.raw_data ?? null} />
          <ChapterValuation dcf={dcf} thesis={thesis} ticker={symbol} />
          <ChapterNews thesis={thesis} />
          <ChapterSensitivity dcf={dcf} />
          <ChapterCatalysts catalysts={catalysts} thesis={thesis} />
          <ChapterTechnical ticker={symbol} technical={technical} />
          <ChapterCompetitive peers={peers} thesis={thesis} />
          <ChapterFinancialData
            rawData={inputs.raw_data ?? null}
            dataSource={inputs.data_source ?? null}
            fetchedAt={inputs.data_fetched_at ?? null}
            ticker={symbol}
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
                ⚠ {t('report.computeWarnings')}
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
        </main>

        <ReportRightRail
          ticker={symbol}
          currentArtifactId={artifactId}
          timeline={timeline ?? []}
          reportType={data.type}
          wacc={dcf?.wacc ?? null}
          terminalGrowth={dcf?.inputs?.terminal_growth_rate ?? null}
          originalImpliedPrice={dcf?.implied_price ?? null}
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

      <ReportStatusBar
        entries={allChapterLabels(locale).map((c) => ({ id: c.id, num: c.num, title: c.title }))}
      />
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
