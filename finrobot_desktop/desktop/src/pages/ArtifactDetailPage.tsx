// ArtifactDetailPage — single artifact deep-dive route, mounted at
// `/stocks/:ticker/runs/:artifactId`.
//
// Renders the artifact as a 13-chapter investment-bank-grade long-scroll
// research report in a two-column desktop layout:
//   - sticky top toolbar  (price overlay · version switcher · diff · re-run)
//   - left sticky rail    (identity card + CONTENTS | VERSIONS tabs — scroll-spy
//                          TOC and Version Timeline merged into one flank)
//   - center scroll area  (chapters 01–13, each a structured Section)
//
// The 13 chapters are split into per-file components under
// pages/artifact-detail/chapters/. They consume artifact.outputs.structured
// (thesis / financial_modeling / peer_analysis / catalyst_analysis) plus
// inputs.raw_data for the audit dump.

import { useEffect, useRef } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { useArtifactDetail, useV5ArtifactTimeline } from '../hooks/useV5Artifacts'
import { useNavMemoryStore } from '../stores/navMemoryStore'
import { useToastStore } from '../stores/toastStore'
import { VersionDiffBanner } from '../components/VersionDiffBanner'
import { useI18n } from '../i18n'
import { mapErrorToUserMessage } from '../utils/errorMessage'
import { markArtifactViewed } from '../api/client'
import { queryClient } from '../api/queryClient'
import { saveTextFile } from '../lib/tauri'
import { reportFileStem } from '../lib/exportReport'
import { isEquityResearch } from '../lib/artifactKind'
import { missingExportBlocksMessage, type ReportExportBlockId } from '../export/reportExportQueries'

import { ReportToolbar } from './artifact-detail/shell/ReportToolbar'
import { ReportLeftRail } from './artifact-detail/shell/ReportLeftRail'
import { ReportChapters } from './artifact-detail/ReportChapters'
import { CompactArtifactViewer } from './artifact-detail/CompactArtifactViewer'
import { deriveReportData } from './artifact-detail/reportData'
import { allChapterLabels } from './artifact-detail/chapters/labels'

export function ArtifactDetailPage(): React.ReactElement {
  const { ticker, artifactId } = useParams<{ ticker: string; artifactId: string }>()
  const urlSymbol = (ticker || '').toUpperCase()
  const location = useLocation()
  const navigate = useNavigate()
  const { data, isLoading, isError, error } = useArtifactDetail(artifactId)

  // The artifact id is the real identity; the URL ticker is only routing
  // context. Visiting /stocks/AAPL/runs/<NVDA-artifact-id> must NOT render
  // AAPL chrome (price / timeline / IC path / export) around NVDA chapters —
  // that's a cross-contaminated report. The report BODY already keys off
  // artifact.ticker (reportData.ts), so once the artifact loads we treat its
  // ticker as the source of truth for ALL chrome too (BUG-014).
  const artifactSymbol = (data?.ticker ?? '').toUpperCase()
  const symbol = artifactSymbol || urlSymbol
  // limit 200 to match Coverage Inspector History's ceiling so a heavily-run
  // ticker's older versions stay reachable here too — this one timeline feeds
  // the toolbar version switcher, right-rail timeline, and diff candidates, all
  // of which would otherwise truncate at the backend default 50 (BUG-056).
  const { data: timeline } = useV5ArtifactTimeline(symbol, 200)
  const { locale, t } = useI18n()
  const addToast = useToastStore((s) => s.addToast)

  // Canonicalize the URL: if the loaded artifact's ticker disagrees with the
  // URL ticker, redirect (replace) to /stocks/<artifact-ticker>/runs/<id> so
  // the address bar, deep links, and nav memory all reflect the real subject.
  // Guarded to fire only on a genuine mismatch (no loop: after replace the URL
  // ticker equals artifactSymbol).
  useEffect(() => {
    if (!artifactSymbol || !artifactId) return
    if (artifactSymbol === urlSymbol) return
    navigate(`/stocks/${artifactSymbol}/runs/${artifactId}`, { replace: true })
  }, [artifactSymbol, urlSymbol, artifactId, navigate])

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

  // Mark the artifact as read once it resolves so the backend refreshes
  // last_viewed_at and the 30-day stale-archive task leaves it alone (BUG-029).
  // Fire-and-forget: a network blip must never block reading the report; a
  // 404/410 just means it's already gone. Guard by id so re-renders / hash
  // navigations don't re-POST, and so switching to a sibling version fires once
  // for the new id. On success we invalidate the timeline that surfaces archive
  // state so an un-archive shows up immediately.
  const loadedId = data?.id ?? null
  const viewedIdRef = useRef<string | null>(null)
  useEffect(() => {
    if (!loadedId) return
    if (viewedIdRef.current === loadedId) return
    viewedIdRef.current = loadedId
    markArtifactViewed(loadedId)
      .then(() => {
        void queryClient.invalidateQueries({ queryKey: ['v5-artifacts-timeline', symbol] })
      })
      .catch((err) => {
        console.error('[ArtifactDetailPage] markArtifactViewed failed', err)
      })
  }, [loadedId, symbol])

  if (!artifactId) {
    return (
      <CenterMessage title={t('report.load.missingId')} body={t('report.load.missingIdBody')} />
    )
  }

  // Full-screen loader ONLY on a genuine cold load (nothing to show yet). During
  // a version switch useArtifactDetail keeps serving the previous artifact via
  // placeholderData:keepPreviousData, so `data` stays populated and we keep the
  // report shell mounted — tearing it down here would unmount ReportLeftRail and
  // reset its tab/scroll-spy, bouncing the reader off the VERSIONS tab back to
  // CONTENTS on every switch (the f77ecd16 rail-merge regression).
  if (isLoading && !data) {
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

  const isResearch = isEquityResearch(data.type)

  // Chapter data + the values the surrounding chrome needs (toolbar target
  // price + version label, right-rail WACC, diff headline). deriveReportData is
  // the single source of truth shared with the standalone export viewer. For
  // non-research artifacts only `versionLabel`/`createdAt` are meaningful (the
  // 13-chapter shapes resolve to null) — the body renders via CompactArtifactViewer.
  const {
    thesis,
    valuationSynthesis,
    createdAt,
    versionLabel,
    snapshotPrice,
    snapshotAsOf,
    fairlyValued,
    quoteCurrency,
    inputs,
  } = deriveReportData(data, timeline ?? [], locale)

  // Company name for the left-rail identity card. raw_data is loosely typed
  // (provider payload), so guard the field rather than asserting a shape.
  const rawDataRecord = (inputs?.raw_data ?? null) as Record<string, unknown> | null
  const companyName =
    typeof rawDataRecord?.company_name === 'string' ? rawDataRecord.company_name : null

  const parentArtifactId =
    (data as unknown as { meta?: { parent_artifact_id?: string | null } }).meta
      ?.parent_artifact_id ?? null

  // Export the report as a self-contained interactive HTML. The viewer bundle is
  // multi-hundred-KB, so it's a lazy chunk pulled in only on click.
  //
  // The exported file renders <ReportChapters> against a DEHYDRATED query cache
  // with refetch disabled — so whatever isn't in the cache at click time would
  // be silently missing offline (football field, historical charts, earnings
  // call, technical KV). To make the file deterministic (same artifact ⇒ same
  // export), we explicitly prefetch every chapter read model into the cache
  // BEFORE dehydrating. A block that fails to prefetch doesn't abort the export;
  // we warn precisely which section will be missing (BUG-20260602-028).
  async function handleExportHtml(): Promise<void> {
    if (!data) return
    try {
      const { buildInteractiveReportHtml, prepareReportExport } = await import('../export/bundle')

      // Only the 13-chapter report pulls slow reference data (earnings calls)
      // that must be prefetched into the offline cache for a deterministic file.
      // A compact artifact (dcf / ddm / lbo / comps / …) renders purely from its
      // own persisted fields — no prefetch, and no "fetching charts / earnings"
      // toast (which would be a lie for a single-method export).
      let missing: ReportExportBlockId[] = []
      if (isResearch) {
        // Transient "preparing" toast — the prefetch + dehydrate can take a beat
        // on a cold cache, so the click gives immediate feedback instead of a
        // silent hang. Auto-dismisses; the result toast lands after.
        addToast({
          type: 'info',
          title: locale === 'zh' ? '正在准备研报数据…' : 'Preparing report data…',
          description:
            locale === 'zh'
              ? '正在准备图表 / 电话会 / 估值数据'
              : 'Fetching charts / earnings call / valuation data',
        })
        missing = await prepareReportExport(queryClient, symbol)
      }

      const html = buildInteractiveReportHtml({
        artifact: data,
        timeline: timeline ?? [],
        queryClient,
        locale,
        title: `${symbol} · ${versionLabel}`,
      })
      // Non-research exports prefix the stem with the artifact type so a DCF file
      // isn't named identically to the ticker's full report (same ticker + date).
      const stem = isResearch
        ? reportFileStem(symbol, versionLabel)
        : reportFileStem(symbol, `${data.type}_${versionLabel}`)
      const saved = await saveTextFile(`${stem}.html`, html, [
        { name: 'HTML', extensions: ['html'] },
      ])
      if (!saved) return
      if (missing.length > 0) {
        // Exported what we have; tell the user which sections are absent rather
        // than letting them discover a half-empty offline file later.
        addToast({
          type: 'info',
          title:
            locale === 'zh' ? '研报已导出（部分数据缺失）' : 'Report exported (some data missing)',
          description: missingExportBlocksMessage(missing, locale),
        })
      } else {
        addToast({ type: 'success', title: t('report.toolbar.exportHtmlDone') })
      }
    } catch (err) {
      addToast({
        type: 'error',
        title: t('report.toolbar.exportHtmlFailed'),
        description: mapErrorToUserMessage(err),
      })
    }
  }

  // ── Non-research artifacts: compact single-column viewer ──────────────────
  // No 13-chapter TOC, no Version Timeline rail, no
  // chapter scroll-spy status bar. Just the toolbar (type-aware) + the focused
  // compact body that shows the artifact's real inputs / result / audit trail.
  if (!isResearch) {
    return (
      <div data-testid="artifact-detail-page" style={{ position: 'relative', minHeight: '100vh' }}>
        <div
          style={{
            maxWidth: 940,
            margin: '0 auto',
            padding: '0 24px 80px',
          }}
        >
          <div style={{ position: 'sticky', top: 0, zIndex: 30 }}>
            <ReportToolbar
              ticker={symbol}
              artifactId={artifactId}
              reportType={data.type}
              targetPrice={null}
              targetLow={null}
              targetHigh={null}
              valuationWithheld={false}
              quoteCurrency={quoteCurrency}
              snapshotPrice={snapshotPrice}
              snapshotAsOf={snapshotAsOf}
              onExportHtml={handleExportHtml}
            />
          </div>
          <div style={{ minWidth: 0, paddingTop: 12 }}>
            <CompactArtifactViewer artifact={data} />
          </div>
        </div>
      </div>
    )
  }

  return (
    <div
      data-testid="artifact-detail-page"
      className="report-doc"
      style={{ position: 'relative', minHeight: '100vh' }}
    >
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '248px minmax(0, 1fr)',
          maxWidth: 1300,
          margin: '0 auto',
          gap: 36,
          padding: '0 24px 80px',
          alignItems: 'start',
        }}
      >
        {/* Full-width sticky top bar. Sticky lives on this grid-item wrapper (not
            the toolbar root) so its travel box is the tall report grid. */}
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
            targetPrice={thesis?.price_target ?? null}
            targetLow={valuationSynthesis?.target_low ?? null}
            targetHigh={valuationSynthesis?.target_high ?? null}
            valuationWithheld={valuationSynthesis?.valuation_withheld === true}
            quoteCurrency={quoteCurrency}
            snapshotPrice={snapshotPrice}
            snapshotAsOf={snapshotAsOf}
            onExportHtml={handleExportHtml}
          />
        </div>

        {/* Single left navigation flank — identity card + CONTENTS | VERSIONS
            tabs (table of contents + version timeline merged). Replaces the old
            left-TOC + right-timeline split that squeezed the reading column. */}
        <ReportLeftRail
          ticker={symbol}
          companyName={companyName}
          verdict={thesis?.recommendation ?? null}
          snapshotPrice={snapshotPrice}
          fairlyValued={fairlyValued}
          confidence={valuationSynthesis?.confidence ?? null}
          quoteCurrency={quoteCurrency}
          entries={allChapterLabels(locale).map((c) => ({ id: c.id, num: c.num, title: c.title }))}
          currentArtifactId={artifactId}
          timeline={timeline ?? []}
          reportType={data.type}
        />

        {/* Report body — reclaims the full width to the right. */}
        <div style={{ minWidth: 0, paddingTop: 12 }}>
          {/* Inline "what changed vs a prior version" banner — workstation
              affordance, NOT part of the export (which is just the research). */}
          <VersionDiffBanner
            currentId={artifactId}
            currentCreatedAt={createdAt ?? null}
            reportType={data.type}
            parentArtifactId={parentArtifactId}
            timeline={timeline ?? []}
            currentTargetRange={{
              low: valuationSynthesis?.target_low ?? null,
              high: valuationSynthesis?.target_high ?? null,
              currency: quoteCurrency,
            }}
            currentTargetWithheld={valuationSynthesis?.valuation_withheld === true}
          />
          <ReportChapters artifact={data} timeline={timeline ?? []} />
        </div>
      </div>
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
