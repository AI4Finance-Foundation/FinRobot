// ArtifactDetailPage — single artifact deep-dive route, mounted at
// `/stocks/:ticker/runs/:artifactId`.
//
// Renders the artifact as a 13-chapter investment-bank-grade long-scroll
// research report in a three-column desktop layout:
//   - sticky top toolbar  (price overlay · version switcher · diff · re-run)
//   - left sticky TOC     (13 chapters with scroll-spy active highlight)
//   - center scroll area  (chapters 01–13, each a structured Section)
//   - right sticky rail   (Version Timeline + live DCF What-if Editor)
//
// The 13 chapters are split into per-file components under
// pages/artifact-detail/chapters/. They consume artifact.outputs.structured
// (thesis / financial_modeling / peer_analysis / catalyst_analysis) plus
// inputs.raw_data for the audit dump.

import { useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useArtifactDetail, useV5ArtifactTimeline } from '../hooks/useV5Artifacts'
import { useNavMemoryStore } from '../stores/navMemoryStore'
import { useToastStore } from '../stores/toastStore'
import { ArtifactDiff } from '../components/ArtifactDiff'
import type { ArtifactSummaryV5 } from '../types/v5'
import { useI18n } from '../i18n'
import { mapErrorToUserMessage } from '../utils/errorMessage'

import { ReportToolbar } from './artifact-detail/shell/ReportToolbar'
import { ReportTOC } from './artifact-detail/shell/ReportTOC'
import { ReportRightRail } from './artifact-detail/shell/ReportRightRail'
import { ReportStatusBar } from './artifact-detail/shell/ReportStatusBar'
import { ReportChapters } from './artifact-detail/ReportChapters'
import { deriveReportData } from './artifact-detail/reportData'
import { allChapterLabels } from './artifact-detail/chapters/labels'

export function ArtifactDetailPage(): React.ReactElement {
  const { ticker, artifactId } = useParams<{ ticker: string; artifactId: string }>()
  const symbol = (ticker || '').toUpperCase()
  const location = useLocation()
  const navigate = useNavigate()
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
    return (
      <CenterMessage title={t('report.load.missingId')} body={t('report.load.missingIdBody')} />
    )
  }

  if (isLoading) {
    return (
      <div style={{ padding: 48, color: 'var(--text-muted)' }}>
        <p style={{ fontFamily: 'var(--font-mono)' }}>{t('report.load.loading')}</p>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <CenterMessage
        title={t('report.load.failed')}
        body={mapErrorToUserMessage(error) || t('report.load.failedBody')}
      />
    )
  }

  // Chapter data + the values the surrounding chrome needs (toolbar target
  // price + version label, right-rail WACC, diff headline). deriveReportData is
  // the single source of truth shared with the standalone export viewer.
  const { thesis, dcf, outputs, createdAt, versionLabel } = deriveReportData(
    data,
    timeline ?? [],
    locale,
  )

  // Pre-compute diff partner candidate: the most recent prior artifact of the
  // same type, surfaced by the Diff button. ArtifactDiff handles its own UI.
  function openDiff(): void {
    if (!data) return
    const list = (timeline ?? []).filter((a) => a.type === data.type && a.id !== artifactId)
    if (list.length === 0) {
      addToast({
        type: 'info',
        title: t('report.diff.noPartner'),
        description: t('report.diff.noPartnerBody', { ticker: symbol }),
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
        {/* Sticky must live HERE, not on ReportToolbar's root: a sticky element
            only travels within its parent's box, and the toolbar's own root is
            this grid item whose parent is the (tall) report grid. Putting it on
            an inner wrapper that hugs the toolbar gives it zero travel room. */}
        <div
          style={{
            gridColumn: '1 / -1',
            position: 'sticky',
            top: 0,
            zIndex: 30,
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
            onOpenIcDebate={
              data.type === 'equity_research'
                ? () => navigate(`/ic/${symbol}?artifact_id=${artifactId}`)
                : undefined
            }
          />
        </div>

        <ReportTOC
          entries={allChapterLabels(locale).map((c) => ({ id: c.id, num: c.num, title: c.title }))}
        />

        <ReportChapters artifact={data} timeline={timeline ?? []} />

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
