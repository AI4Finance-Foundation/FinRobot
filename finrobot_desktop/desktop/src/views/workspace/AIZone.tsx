// Right column of the workspace dashboard. Surfaces the AI research
// state for a ticker — either cold (no equity_research artifact yet,
// big CTA to run one) or hot (most-recent verdict card + 13-chapter
// preview grid + version timeline).
//
// Does NOT render the chapter contents themselves — clicking a chapter
// or "Open full report" navigates to /stocks/:ticker/runs/:artifactId
// which is where the 13-chapter long-scroll lives.

import { useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useLatestArtifact, useV5ArtifactTimeline } from '../../hooks/useV5Artifacts'
import { useTickerPrice } from '../../hooks/useTickerData'
import { useRunStreamStore, selectRunByTicker } from '../../stores/runStreamStore'
import { useToastStore } from '../../stores/toastStore'
import { useHealth, type HealthState } from '../../hooks/useHealth'
import { PipelineProgressPanel } from '../PipelineProgressPanel'
import { verdictLabel, verdictTone } from '../../utils/verdict'
import { formatDate } from '../../utils/format'
import { mapErrorToUserMessage } from '../../utils/errorMessage'
import { useI18n, tSync, type Locale } from '../../i18n'
import type { ArtifactSummaryV5 } from '../../types/v5'
import { ArchivedPill } from '../../components/ArchivedPill'
import { ValuationInstruments, VALUATION_TYPES, blockedCtaLabel } from './ValuationInstruments'
import { SETTINGS_ALLOWED } from '../../config/deployment'
import { artifactTypeLabel } from './artifactLabels'

// Display label per non-research artifact type (dcf / lbo / comps / …). Kept
// inline (not in .po) per the VersionDiffBanner precedent — these are short,
// stable model names. Mirror of CompactArtifactViewer's TYPE_LABEL so the
// workspace and the detail page name the same artifact identically.
// One-word stance shown under the big verdict glyph (design prototype's
// "裁决 · 中性持有"). Inline EN per the ARTIFACT_TYPE_LABEL precedent.
const VERDICT_DESC: Record<string, string> = {
  BUY: 'Bullish',
  HOLD: 'Neutral',
  SELL: 'Bearish',
  WITHHELD: 'Withheld',
}

// Friendly, actionable copy for each preflight failure (BUG-027) — what's
// wrong + that Settings is where to fix it. Inline literals per the
// VersionDiffBanner precedent.
type PreflightReason = 'offline' | 'needsModel' | 'config' | 'providers' | null

function preflightDescription(reason: PreflightReason, locale: Locale): string {
  const zh = locale === 'zh'
  // Hosted: every branch below ends in "go to Settings", a page this viewer
  // has no door to — the deployment's keys are shared and administrator-owned.
  // One honest sentence beats four instructions they cannot follow. The
  // distinction between the reasons is diagnostic detail for whoever can
  // actually act on it, and that is the administrator's build.
  if (!SETTINGS_ALLOWED) {
    return zh
      ? 'AI 分析暂不可用。本部署的模型与数据源由管理员统一配置,价格 / 财务 / 估值数字不受影响,可照常查看。'
      : 'AI analysis is unavailable right now. This deployment’s model and data sources are configured centrally by an administrator; prices, financials and valuation numbers are unaffected.'
  }
  switch (reason) {
    case 'offline':
      return zh
        ? '后端服务未连接。请确认 finrobot serve 正在运行后重试。'
        : 'Backend is offline. Make sure finrobot serve is running, then retry.'
    case 'needsModel':
      return zh
        ? '还没配置 AI 模型。研报与 AI 分析需要一个模型;价格 / 财务 / 估值数字无需配置即可查看。去设置选一个模型并填好 key。'
        : 'No AI model configured yet. Reports and AI analysis need one; prices / financials / valuation numbers work without any key. Pick a model in Settings and add its key.'
    case 'config':
      return zh
        ? '后端配置有误(LLM / 数据源密钥)。请到设置补全后重试。'
        : 'Backend config error (LLM / data-source keys). Fix it in Settings, then retry.'
    case 'providers':
      return zh
        ? '尚未配置任何数据源(FMP / yfinance)。请到设置添加数据源密钥。'
        : 'No data provider configured (FMP / yfinance). Add a key in Settings.'
    default:
      return zh ? '请到设置检查后端配置。' : 'Check the backend config in Settings.'
  }
}

interface AIZoneProps {
  ticker: string
}

export function AIZone({ ticker }: AIZoneProps): React.ReactElement {
  const navigate = useNavigate()
  const { locale, t } = useI18n()
  const {
    latest,
    isLoading: artifactLoading,
    isError: artifactError,
    error: artifactErr,
    refetch: artifactRefetch,
    // limit 200 + includeSignals=false == the timeline query below, so both
    // subscribe to the SAME react-query key → one request, one truncation
    // caliber (was a second default-50 fetch whose "latest" could disagree with
    // the 200-row list). includeSignals=false because this preview never renders
    // the hit/watching/failed lamp (see "DO NOT read signal" below) — skipping
    // it drops a synchronous live-quote fetch off the critical path so the report
    // history paints from the local DB instantly instead of waiting on market
    // data. The lamp lives only on the report detail page's version rail.
  } = useLatestArtifact(ticker, 'equity_research', 200, false)
  const {
    data: timeline,
    isLoading: timelineLoading,
    isError: timelineError,
    refetch: timelineRefetch,
    // limit 200 to match the report page / Coverage Inspector ceiling so this
    // preview reads from the same cached "full history" page rather than its own
    // truncated default-50 slice for the same ticker (BUG-056). includeSignals=
    // false — see the useLatestArtifact note above; the preview doesn't use it.
  } = useV5ArtifactTimeline(ticker, 200, false)
  const startRun = useRunStreamStore((s) => s.startRun)
  const runState = useRunStreamStore(selectRunByTicker(ticker))
  const dismissRun = useRunStreamStore((s) => s.dismiss)
  const addToast = useToastStore((s) => s.addToast)
  // Preflight signal (BUG-027): the backend's honest health/config snapshot.
  // Used to gate the "run report" CTA — no point letting the user fire a run
  // that the backend will 503/500 because it has no LLM/data provider or a
  // boot-time config error. `isPlaceholderData` is true while the very first
  // probe is in flight (useHealth seeds OFFLINE as placeholderData); we must NOT
  // block on that seed or every cold load would flash "去设置" before the real
  // health lands. Only a RESOLVED bad health blocks.
  const { data: healthData, isPlaceholderData: healthPlaceholder } = useHealth()
  const health = healthPlaceholder ? null : healthData
  // "Still plausibly booting" = the very first health probe is in flight (health
  // null) OR the probe explicitly reports the sidecar as starting (within the
  // boot grace). ONLY during this window do we suppress the red error state for a
  // failed query and fall to the neutral loading state. A backend that is
  // CONFIRMED offline (post-grace / crashed mid-session) is NOT booting — its
  // errored query must still surface the red error + Retry affordance, never a
  // perpetual "checking…" skeleton with no way out.
  const backendBooting = health == null || health.level === 'starting'
  // Live quote for the verdict card's TargetGauge "now" tick. NOT a new fetch:
  // StockWorkspace / TickerHero / MarketDataZone already run this exact query
  // (key ['ticker-price', ticker]); React Query dedupes us onto their cached
  // result. The artifact only carries entry_price (its creation-time anchor),
  // so this is the only honest CURRENT price in scope. Degrades to entry_price
  // when the live quote is absent (cold / provider outage).
  const { data: priceData } = useTickerPrice(ticker)
  // The gauge compares this price against the artifact's USD target/entry (the
  // normalize→USD invariant). The /price live quote is the canonical PRICE, which
  // is NEVER FX-normalized — for a foreign LOCAL listing (2330.TW) it is in the
  // exchange currency (TWD), so feeding it to a USD gauge would compute a garbage
  // cross-currency gap (the bug fixed backend-side in coverage/dashboard/valuation;
  // here the gap is computed in-browser). The client can't run FX, so on a non-USD
  // quote we drop the live price and let the gauge degrade to the USD entry_price
  // anchor — abstain, never mix. Absent tag ⇒ USD (the US-majority no-op).
  const liveQuoteCurrency = (priceData?.quote_currency ?? 'USD').toUpperCase()
  const livePrice = liveQuoteCurrency === 'USD' ? (priceData?.current_price ?? null) : null
  // True only when the live quote was genuinely absent (cold / outage), distinct
  // from dropped-as-cross-currency (foreign listing) — the note copy differs.
  const liveQuoteForeign = liveQuoteCurrency !== 'USD' && priceData?.current_price != null

  const sameTypeTimeline = (timeline ?? []).filter((a) => a.type === 'equity_research')
  // BUG-040: all NON-equity_research artifacts (dcf / lbo / comps / earnings /
  // ic_memo / …). The landing recent strip counts ALL artifact types, so a
  // ticker that only has these must NOT fall through to the cold "run research"
  // empty state — that buries reachable model results. Surface them in their
  // own labelled section, newest first.
  const otherArtifacts = (timeline ?? []).filter((a) => a.type !== 'equity_research')
  const hasOtherArtifacts = otherArtifacts.length > 0
  // The four standalone valuations now render as reading cards in
  // ValuationInstruments (each with its own version chain); keep only the OTHER
  // model artifacts (earnings / ic_memo / peer_research / ad_hoc) in the side
  // list so a valuation run is never shown twice.
  const sideArtifacts = otherArtifacts.filter(
    (a) => !(VALUATION_TYPES as readonly string[]).includes(a.type),
  )
  const isRunning = runState?.status === 'running'

  // ── Auto-advance into the report on a watched completion (UX-002) ─────────
  // The first wow is "search → read a 13-chapter report"; making the user hunt
  // for an "open" button after the run finishes blunts it. When a research run
  // the user is WATCHING here transitions running→completed, drill straight into
  // its report. Guarded so we never yank a user who merely lands on a workspace
  // that already has a stale completed run: prevStatus must have been 'running'
  // (a fresh transition), and each artifact advances at most once. Non-research
  // results (DCF/LBO/…) keep their in-panel CTA and are not auto-opened.
  const prevRunStatus = useRef<string | undefined>(undefined)
  const autoAdvancedId = useRef<string | null>(null)
  useEffect(() => {
    const prev = prevRunStatus.current
    if (
      prev === 'running' &&
      runState?.status === 'completed' &&
      runState.artifactType === 'equity_research' &&
      runState.artifactId &&
      !runState.dismissed &&
      autoAdvancedId.current !== runState.artifactId
    ) {
      autoAdvancedId.current = runState.artifactId
      // Mark the run seen so returning to the workspace doesn't re-show the
      // completion banner's redundant "open report" button.
      dismissRun(ticker)
      navigate(`/stocks/${ticker}/runs/${runState.artifactId}`)
    }
    prevRunStatus.current = runState?.status
  }, [
    runState?.status,
    runState?.artifactId,
    runState?.artifactType,
    runState?.dismissed,
    ticker,
    navigate,
    dismissRun,
  ])

  // ── Run preflight (BUG-027) ───────────────────────────────────────────────
  // Block the report CTA when a key precondition is known-bad, so the user gets
  // an actionable "去设置" affordance instead of a raw "Run creation failed
  // (500)" toast after the POST. Only block on signals we're CONFIDENT about:
  //   - backend offline (reachability probe failed)
  //   - boot-time config error (startup_error → /api/runs returns 503, BUG-056)
  //   - no data provider configured at all (no FMP/yfinance → pipeline can't run)
  // We do NOT block on `degraded` alone (quotes still warming is transient) nor
  // on a market-data card outage (a yfinance hiccup shouldn't lock research).
  // `undefined` health (still loading) never blocks — don't punish a cold load.
  const preflightBlocked =
    health != null &&
    (!health.backendReachable ||
      !health.modelConfigured ||
      health.startupError != null ||
      health.availableProviders.length === 0)
  // Order matters: offline first, then the first-run "no model" case (the most
  // common fresh-install block — and the only one that's NOT an error), then
  // hard config errors, then missing data providers.
  const preflightReason: PreflightReason =
    health == null
      ? null
      : !health.backendReachable
        ? 'offline'
        : !health.modelConfigured
          ? 'needsModel'
          : health.startupError != null
            ? 'config'
            : health.availableProviders.length === 0
              ? 'providers'
              : null
  // A completed run whose artifact is NOT equity_research (DCF/LBO/comps/
  // earnings/…). Its result lives behind the PipelineProgressPanel's CTA
  // (run.artifactId), so we must not fall through to ColdState and bury it.
  const nonResearchResult =
    runState?.status === 'completed' &&
    !runState.dismissed &&
    !!runState.artifactId &&
    runState.artifactType !== 'equity_research'

  // Show the error state when both queries failed, the run is not active (a
  // running pipeline masks stale query errors), AND the sidecar is not still
  // booting. A failed fetch during the boot window (health null / level
  // 'starting') is "not up yet" → neutral loading, no red flash. But a query
  // error once the backend is CONFIRMED offline (post-grace / crashed) must
  // surface the red error + Retry — never a perpetual "checking…" skeleton.
  // Loading while !latest no longer falls into ColdState (that lied "No report
  // generated" + armed a redundant run before the local DB answered) — it
  // renders LoadingState until the history query returns.
  const isError = (artifactError || timelineError) && !isRunning && !backendBooting

  function handleRetry(): void {
    void artifactRefetch()
    void timelineRefetch()
  }

  // Shared launch path for every pipeline — the full 13-chapter report AND the
  // standalone single-method valuations. Guards: a per-ticker run already active
  // → info toast (startRun locks one run per ticker); a known-bad precondition
  // (BUG-027) → route to Settings instead of POSTing a doomed 503/500 run. The
  // caller supplies its own success copy.
  async function launchPipeline(
    pipelineType: string,
    successTitle: string,
    successDesc: string,
  ): Promise<void> {
    // Fresh store read, not the render-scope `isRunning`: a double-click's
    // second event can fire before React re-renders the disabled button. The
    // first click's occupation is written synchronously by startRun (before
    // its POST even leaves), so this read closes the POST round-trip window
    // that used to let both clicks through. startRun's own lock is the final
    // backstop — it reuses the in-flight promise instead of double-POSTing.
    if (useRunStreamStore.getState().runs[ticker]?.status === 'running') {
      addToast({
        type: 'info',
        title: t('workspace.ai.toast.alreadyRunning', { ticker }),
        description: t('workspace.ai.toast.alreadyRunningDesc'),
      })
      return
    }
    if (preflightBlocked) {
      addToast({
        type: 'error',
        title: locale === 'zh' ? '无法启动' : 'Can’t start',
        description: preflightDescription(preflightReason, locale),
      })
      navigate('/settings')
      return
    }
    try {
      await startRun(pipelineType, ticker)
      addToast({ type: 'success', title: successTitle, description: successDesc })
    } catch (err) {
      addToast({
        type: 'error',
        title: t('workspace.ai.toast.launchFailed'),
        description: mapErrorToUserMessage(err),
      })
    }
  }

  async function launchResearch(): Promise<void> {
    await launchPipeline(
      'research',
      t('workspace.ai.toast.launched', { ticker }),
      t('workspace.ai.toast.launchedDesc'),
    )
  }

  // Standalone single-method valuation (dcf / ddm / lbo / comps): a focused tool
  // run that lands its own artifact + detail page, no 13-chapter report needed.
  // The artifact type == pipeline type for these four, so artifactTypeLabel()
  // names the toast identically to the timeline row it will produce.
  async function launchMethod(pipelineType: string): Promise<void> {
    const label = artifactTypeLabel(pipelineType, locale)
    await launchPipeline(
      pipelineType,
      locale === 'zh' ? `${label} · 已启动` : `${label} · started`,
      locale === 'zh' ? `正在为 ${ticker} 运行 ${label}` : `Running ${label} for ${ticker}`,
    )
  }

  // Five states for the AI column:
  //   error    → reachable backend returned 5xx — actionable error + retry
  //   running  → progress panel only (cold/hot would be misleading)
  //   has artifact → hot card stack
  //   loading  → history query still in flight / sidecar still booting →
  //              neutral LoadingState (NO "no report" claim, NO run trigger)
  //   cold     → query RESOLVED and genuinely zero artifacts → ColdState + CTA
  // After the run completes, PipelineProgressPanel keeps showing its
  // "完成 · 总耗时 Xs" header (→ 打开研报 / ✕ dismiss) until dismissed.
  // Only a RESEARCH run owns the top progress panel. An instrument run
  // (dcf/ddm/lbo/comps) shows its progress INSIDE its ValuationInstruments card,
  // never up here — so a focused valuation never hijacks the flagship column.
  const showProgress = !!runState && !runState.dismissed && runState.pipelineType === 'research'
  // The history query has actually come back (settled, no error). ONLY then do
  // we know whether reports exist — and only then may we show the affirmative
  // "No report · Run now" terminal. Before this we render LoadingState: showing
  // ColdState during the cold-start window both lied ("No report generated")
  // and armed a redundant ~60s generation the user could fire before the local
  // SQLite read (single-digit ms once the sidecar is up) had even returned.
  const reportHistoryResolved =
    !artifactLoading && !timelineLoading && !artifactError && !timelineError

  if (isError) {
    return (
      <section data-testid="ai-zone">
        <ZoneHeader hasArtifact={false} versionsCount={0} />
        <div
          data-testid="ai-zone-error"
          style={{
            background: 'color-mix(in srgb, var(--danger) 6%, transparent)',
            border: '1px solid color-mix(in srgb, var(--danger) 22%, transparent)',
            borderRadius: 'var(--radius-md)',
            padding: '24px 20px',
            textAlign: 'center',
          }}
        >
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
              color: 'var(--danger)',
              marginBottom: 8,
            }}
          >
            {t('workspace.ai.error.title')}
          </div>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10.5,
              color: 'var(--text-dim)',
              marginBottom: 14,
            }}
          >
            {artifactErr ? mapErrorToUserMessage(artifactErr) : t('workspace.ai.error.hint')}
          </div>
          <button
            type="button"
            data-testid="ai-zone-retry"
            onClick={handleRetry}
            style={{
              padding: '8px 18px',
              background: 'var(--negative-bg)',
              border: '1px solid var(--danger)',
              borderRadius: 6,
              color: 'var(--danger)',
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              cursor: 'pointer',
              letterSpacing: '0.04em',
            }}
          >
            {t('workspace.ai.retry')}
          </button>
        </div>
      </section>
    )
  }

  return (
    <section data-testid="ai-zone">
      <ZoneHeader
        hasArtifact={!!latest}
        versionsCount={sameTypeTimeline.length}
        loading={!latest && !reportHistoryResolved}
      />
      <p style={zoneDesc}>{t('workspace.ai.zoneDesc')}</p>

      {showProgress && <PipelineProgressPanel ticker={ticker} />}

      {latest ? (
        // Render the verdict/report card whenever a latest artifact exists —
        // INCLUDING mid-run, so a re-run shows the progress panel (above) over
        // the still-readable prior report (the design's running state). The
        // rerun button self-disables while running.
        <HotState
          latest={latest}
          timeline={sameTypeTimeline}
          isRunning={isRunning}
          livePrice={livePrice}
          liveQuoteForeign={liveQuoteForeign}
          onRerun={launchResearch}
          onOpen={(id) => navigate(`/stocks/${ticker}/runs/${id}`)}
        />
      ) : !isRunning && !latest && hasOtherArtifacts ? (
        // BUG-040: ticker has model artifacts (DCF/LBO/comps/…) but no full
        // equity_research report. Don't pretend it's empty — surface those
        // artifacts (reachable via the detail page's type router, BUG-039) plus
        // a slimmer prompt to run a full report. The cold "还没跑 AI 研报"
        // empty state is reserved for tickers with genuinely zero artifacts.
        <NoReportYetState
          ticker={ticker}
          preflightBlocked={preflightBlocked}
          preflightReason={preflightReason}
          isRunning={isRunning}
          onLaunch={launchResearch}
        />
      ) : !isRunning && !latest && !nonResearchResult && !reportHistoryResolved ? (
        // History query still in flight (or the sidecar is still booting). We do
        // NOT yet know whether reports exist — show a neutral, non-actionable
        // loading state. Never the "No report · Run now" terminal here: that
        // lied before the local DB answered and armed a redundant generation.
        <LoadingState />
      ) : !isRunning && !latest && !nonResearchResult ? (
        // Query RESOLVED and genuinely empty. Don't drop a just-finished
        // non-research run (DCF/LBO/comps/earnings) into ColdState's "run
        // research" prompt — that buries the result the user just produced; the
        // PipelineProgressPanel above keeps its "open" CTA. Only show ColdState
        // when there's genuinely nothing.
        <ColdState
          ticker={ticker}
          isRunning={isRunning}
          preflightBlocked={preflightBlocked}
          preflightReason={preflightReason}
          health={health ?? null}
          onLaunch={launchResearch}
        />
      ) : null}

      {/* Standalone valuation launcher + model-artifact list — paired SIDE BY
          SIDE per the design (left = run a single method, right = artifacts this
          ticker already has). When only the launcher shows (cold ticker, no
          artifacts) it spans full width. Stays mounted during a research run —
          the flagship progress panel appears ABOVE, and the instruments lock
          their launch buttons themselves (ValuationInstruments lockOthers)
          while keeping the latest readings visible. */}
      {(reportHistoryResolved || sideArtifacts.length > 0) && (
        <div
          data-testid="ai-zone-tools-row"
          style={{
            display: 'grid',
            gridTemplateColumns:
              reportHistoryResolved && sideArtifacts.length > 0 ? '1fr 1fr' : '1fr',
            gap: 12,
            alignItems: 'start',
            marginTop: 14,
          }}
        >
          {/* Second run entry: the four single-method valuations as live
              instruments — each shows its latest reading + version, and runs IN
              PLACE (inline progress in its own card), so a focused valuation
              never hijacks the flagship's top progress panel. Shown once the
              history query settles — incl. the cold state, so a fresh ticker can
              run one method without first producing an artifact. */}
          {reportHistoryResolved && (
            <ValuationInstruments
              timeline={timeline ?? []}
              runState={runState ?? null}
              preflightBlocked={preflightBlocked}
              preflightReason={preflightReason}
              locale={locale}
              livePrice={livePrice}
              onLaunch={launchMethod}
              onOpen={(id) => navigate(`/stocks/${ticker}/runs/${id}`)}
            />
          )}

          {/* BUG-040: remaining non-valuation model artifacts (earnings /
              ic_memo / peer_research / ad_hoc). The four valuations are excluded
              (they render as instrument cards on the left); these still surface
              so their landing-strip counts stay reachable. */}
          {sideArtifacts.length > 0 && (
            <OtherArtifacts
              artifacts={sideArtifacts}
              locale={locale}
              onOpen={(id) => navigate(`/stocks/${ticker}/runs/${id}`)}
            />
          )}
        </div>
      )}
    </section>
  )
}

// Shown when the ticker has model artifacts but no full equity_research report
// (BUG-040). Replaces the misleading "还没跑 AI 研报" cold state — the user DOES
// have research here, just not a 13-chapter report. The OtherArtifacts list
// below this surfaces the actual artifacts; this card only nudges toward a full
// report and routes broken-config users to Settings.
function NoReportYetState({
  ticker,
  preflightBlocked,
  preflightReason,
  isRunning,
  onLaunch,
}: {
  ticker: string
  preflightBlocked: boolean
  preflightReason: PreflightReason
  isRunning: boolean
  onLaunch: () => void
}): React.ReactElement {
  const { locale } = useI18n()
  const zh = locale === 'zh'
  return (
    <div
      data-testid="ai-zone-no-report"
      style={{
        background: 'var(--bg-card-faint)',
        border: '1px dashed var(--border-soft)',
        borderRadius: 'var(--radius-md)',
        padding: '20px 22px',
        marginBottom: 14,
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 15,
          letterSpacing: '1px',
          color: 'var(--text-primary)',
          marginBottom: 8,
        }}
      >
        {zh ? `${ticker} 还没有完整 AI 研报` : `No full AI report for ${ticker} yet`}
      </div>
      <p
        style={{
          fontSize: 12.5,
          color: 'var(--text-muted)',
          lineHeight: 1.6,
          marginBottom: 14,
        }}
      >
        {zh
          ? '该标的已有下方的模型产物。要生成 13 章完整研报,跑一次 AI 分析。'
          : 'This ticker already has the model artifacts below. Run an AI analysis for the full 13-chapter report.'}
      </p>
      <RunCta
        preflightBlocked={preflightBlocked}
        preflightReason={preflightReason}
        isRunning={isRunning}
        onLaunch={onLaunch}
        compact
      />
    </div>
  )
}

// The non-research artifact timeline (BUG-040). DCF / LBO / comps / earnings /
// ic_memo rows, newest first, each routing to the artifact detail type router.
function OtherArtifacts({
  artifacts,
  locale,
  onOpen,
}: {
  artifacts: ArtifactSummaryV5[]
  locale: Locale
  onOpen: (id: string) => void
}): React.ReactElement {
  const zh = locale === 'zh'
  const sorted = [...artifacts].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  )
  return (
    <div
      data-testid="ai-zone-other-artifacts"
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-lg)',
        padding: '16px',
        // Top spacing is owned by the side-by-side tools-row wrapper.
        height: '100%',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--text-muted)',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
          }}
        >
          {zh ? '模型产物与工具运行' : 'Model Artifacts & Tool Runs'}
        </span>
        <span
          style={{
            marginLeft: 'auto',
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: 'var(--text-muted)',
          }}
        >
          {sorted.length}
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {sorted.map((a) => {
          const v = readVerdict(a)
          return (
            <button
              key={a.id}
              type="button"
              data-testid={`other-artifact-${a.type}`}
              onClick={() => onOpen(a.id)}
              style={{
                display: 'grid',
                gridTemplateColumns: '120px 60px 70px 1fr auto',
                gap: 10,
                alignItems: 'center',
                padding: '8px 10px',
                background: 'var(--bg-card-translucent)',
                border: 'none',
                borderLeft: '2px solid var(--border-soft)',
                borderRadius: '0 6px 6px 0',
                cursor: 'pointer',
                fontFamily: 'var(--font-mono)',
                fontSize: 11.5,
                textAlign: 'left',
                color: 'var(--text-primary)',
              }}
            >
              <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                {artifactTypeLabel(a.type, locale)}
              </span>
              {v ? <VerdictPill verdict={v} /> : <span />}
              <span style={{ color: 'var(--text-secondary)' }}>
                {a.target_price !== null && a.target_price !== undefined
                  ? `$${a.target_price.toFixed(2)}`
                  : '—'}
              </span>
              <span style={{ color: 'var(--text-dim)', fontSize: 10.5 }}>
                {formatDate(a.created_at, locale, 'short')} · {ageLabel(a.created_at)}
                {a.primary_provider ? ` · ${a.primary_provider}` : ''}
              </span>
              <span
                style={{ color: 'var(--text-dim)', display: 'inline-flex', alignItems: 'center' }}
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
                  <path
                    d="M9 6 L15 12 L9 18"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

function ZoneHeader({
  hasArtifact,
  versionsCount,
  loading,
}: {
  hasArtifact: boolean
  versionsCount: number
  loading?: boolean
}): React.ReactElement {
  const { t } = useI18n()
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 11,
        marginBottom: 14,
        paddingBottom: 10,
        borderBottom: '1px solid var(--border-faint)',
      }}
    >
      <span
        style={{
          width: 3,
          height: 15,
          borderRadius: 2,
          background: 'var(--primary)',
          boxShadow: '0 0 8px color-mix(in srgb, var(--primary) 60%, transparent)',
        }}
      />
      <span
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 16,
          fontWeight: 600,
          letterSpacing: '1.5px',
          color: 'var(--text-primary)',
        }}
      >
        {t('workspace.ai.zoneTitle')}
      </span>
      <span
        style={{
          marginLeft: 'auto',
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-muted)',
          letterSpacing: '0.08em',
        }}
      >
        {loading
          ? '···'
          : hasArtifact
            ? t('workspace.ai.reportCount', { n: versionsCount })
            : t('workspace.ai.neverRun')}
      </span>
    </div>
  )
}

const zoneDesc: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  color: 'var(--text-muted)',
  marginBottom: 14,
  lineHeight: 1.55,
}

// Readout-tile styles for the hero instrument's Now / Target / Implied-Return
// trio. `edge` tints the hairline in the directional hue (target + implied).
function readoutTile(edge?: string): React.CSSProperties {
  return {
    background: 'var(--bg-elevated)',
    border: `1px solid ${edge ? `color-mix(in srgb, ${edge} 26%, transparent)` : 'var(--border-faint)'}`,
    borderRadius: 'var(--radius-md)',
    padding: '13px 15px',
    display: 'flex',
    flexDirection: 'column',
    gap: 7,
  }
}
const readoutKey: React.CSSProperties = {
  fontFamily: 'var(--font-body)',
  fontSize: 10,
  fontWeight: 500,
  letterSpacing: '0.1em',
  textTransform: 'uppercase',
  color: 'var(--text-muted)',
}
const readoutVal: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 22,
  fontWeight: 600,
  color: 'var(--text-primary)',
  fontVariantNumeric: 'tabular-nums',
  lineHeight: 1,
}

// Shown while the report-history query is still in flight (or the sidecar is
// still booting). Deliberately NON-actionable — no "No report" headline, no run
// trigger: claiming "no report" before the local SQLite read has answered both
// lies and invites a redundant ~60s generation. Once the query resolves this
// flips to HotState (reports exist) or ColdState (genuinely none). Static
// skeleton only — no animation (persistent-state UI rule).
function LoadingState(): React.ReactElement {
  const { t } = useI18n()
  return (
    <div
      data-testid="ai-zone-loading"
      style={{
        background: 'var(--bg-card-faint)',
        border: '1px dashed var(--border-soft)',
        borderRadius: 'var(--radius-md)',
        padding: '36px 24px',
        textAlign: 'center',
      }}
    >
      <div style={{ fontSize: 40, opacity: 0.3, marginBottom: 14 }}>🤖</div>
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11.5,
          color: 'var(--text-muted)',
          letterSpacing: '0.06em',
          marginBottom: 18,
        }}
      >
        {t('workspace.ai.cold.checking')}
      </div>
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 9,
          maxWidth: 300,
          margin: '0 auto',
        }}
      >
        {[1, 0.7, 0.45].map((w, i) => (
          <div
            key={i}
            style={{
              height: 9,
              width: `${w * 100}%`,
              borderRadius: 4,
              background: 'var(--border-soft)',
              opacity: 0.5 - i * 0.12,
            }}
          />
        ))}
      </div>
    </div>
  )
}

function ColdState({
  ticker,
  isRunning,
  preflightBlocked,
  preflightReason,
  health,
  onLaunch,
}: {
  ticker: string
  isRunning: boolean
  preflightBlocked: boolean
  preflightReason: PreflightReason
  /** Resolved backend health (null while the first probe is in flight). Drives
   *  the real preflight checklist — never a hardcoded model name or source count. */
  health: HealthState | null
  onLaunch: () => void
}): React.ReactElement {
  const { t } = useI18n()
  return (
    <div
      data-testid="ai-zone-cold"
      style={{
        background: 'var(--bg-card-faint)',
        border: '1px dashed var(--border-soft)',
        borderRadius: 'var(--radius-md)',
        padding: '36px 24px',
        textAlign: 'center',
      }}
    >
      <div style={{ fontSize: 40, opacity: 0.5, marginBottom: 12 }}>🤖</div>
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 18,
          letterSpacing: '2px',
          color: 'var(--text-primary)',
          marginBottom: 10,
        }}
      >
        {t('workspace.ai.cold.title', { ticker })}
      </div>
      <p
        style={{
          fontSize: 13,
          color: 'var(--text-muted)',
          lineHeight: 1.65,
          maxWidth: 420,
          margin: '0 auto 18px',
        }}
      >
        {t('workspace.ai.cold.descPrefix')}{' '}
        <strong style={{ color: 'var(--accent-cyan)' }}>{t('workspace.ai.cold.descBold')}</strong>
        {t('workspace.ai.cold.descSuffix')}
      </p>
      <div style={{ display: 'flex', justifyContent: 'center' }}>
        <RunCta
          preflightBlocked={preflightBlocked}
          preflightReason={preflightReason}
          isRunning={isRunning}
          onLaunch={onLaunch}
        />
      </div>
      <PreflightChecklist health={health} preflightBlocked={preflightBlocked} />
      <p
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-dim)',
          marginTop: 14,
        }}
      >
        {t('workspace.ai.cold.immutableNote')}
      </p>
    </div>
  )
}

// Real preflight indicator under the cold-state CTA, fed entirely by useHealth —
// NEVER a hardcoded "GPT" / "5 sources". Three honest signals:
//   • Preflight passed       — green check, only when nothing is blocking a run.
//   • AI model configured    — green when health.modelConfigured; otherwise a
//                              NEUTRAL muted hint ("No AI model yet · Settings"),
//                              never a red error (an unconfigured model is a
//                              normal not-yet-done state, not a failure).
//   • N data sources online  — N = health.availableProviders.length (real count).
// While health is still loading (null) the checklist renders nothing rather than
// flashing a guess.
function PreflightChecklist({
  health,
  preflightBlocked,
}: {
  health: HealthState | null
  preflightBlocked: boolean
}): React.ReactElement | null {
  const { t, locale } = useI18n()
  if (!health) return null
  const modelOk = health.modelConfigured
  const providerCount = health.availableProviders.length

  return (
    <div
      data-testid="ai-zone-preflight"
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        justifyContent: 'center',
        alignItems: 'center',
        gap: 14,
        marginTop: 16,
        fontFamily: 'var(--font-mono)',
        fontSize: 10.5,
        letterSpacing: '0.04em',
      }}
    >
      {/* Preflight passed — only when a run is genuinely unblocked. */}
      {!preflightBlocked && (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          <span style={{ color: 'var(--success)' }}>✓</span>
          <span style={{ color: 'var(--text-secondary)' }}>
            {t('workspace.ai.cold.preflight.passed')}
          </span>
        </span>
      )}
      {/* AI model: green check when configured, neutral muted hint otherwise
          (NOT red — unconfigured is a normal pre-setup state). */}
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        {modelOk ? (
          <>
            <span style={{ color: 'var(--success)' }}>✓</span>
            <span style={{ color: 'var(--text-secondary)' }}>
              {t('workspace.ai.cold.preflight.modelConfigured')}
            </span>
          </>
        ) : (
          <>
            <span style={{ color: 'var(--text-dim)' }}>○</span>
            <span style={{ color: 'var(--text-muted)' }}>
              {/* The translated string ends in "open Settings", which is only
                  true where the viewer has that door. */}
              {SETTINGS_ALLOWED
                ? t('workspace.ai.cold.preflight.modelPending')
                : locale === 'zh'
                  ? 'AI 模型未就绪'
                  : 'AI model not ready'}
            </span>
          </>
        )}
      </span>
      {/* Real data-source count (0 reads as the honest "0 online", not hidden). */}
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
        <span style={{ color: providerCount > 0 ? 'var(--success)' : 'var(--text-dim)' }}>
          {providerCount > 0 ? '✓' : '○'}
        </span>
        <span style={{ color: 'var(--text-secondary)' }}>
          {t('workspace.ai.cold.preflight.dataSources', { n: providerCount })}
        </span>
      </span>
    </div>
  )
}

// The primary "run report" CTA, shared by ColdState and NoReportYetState.
// BUG-027: when a preflight precondition is known-bad the button becomes a
// "去设置" link instead of a run trigger — so the user never fires a run the
// backend will reject with a raw HTTP error. `compact` shrinks it for the
// inline NoReportYet card vs the big hero cold state.
function RunCta({
  preflightBlocked,
  preflightReason,
  isRunning,
  onLaunch,
  compact,
}: {
  preflightBlocked: boolean
  preflightReason: PreflightReason
  isRunning: boolean
  onLaunch: () => void
  compact?: boolean
}): React.ReactElement {
  const { locale, t } = useI18n()
  const navigate = useNavigate()
  const zh = locale === 'zh'
  const pad = compact ? '11px 20px' : '17px 32px'
  const fontSize = compact ? 12.5 : 14

  if (preflightBlocked) {
    const label = blockedCtaLabel(preflightReason, zh)
    return (
      <button
        type="button"
        data-testid="run-analysis-blocked"
        disabled={!SETTINGS_ALLOWED}
        onClick={SETTINGS_ALLOWED ? () => navigate('/settings') : undefined}
        style={{
          padding: pad,
          background: 'var(--warning-soft)',
          border: '1px solid var(--warning)',
          borderRadius: 10,
          color: 'var(--warning)',
          fontFamily: 'var(--font-mono)',
          fontSize,
          fontWeight: 600,
          letterSpacing: '0.04em',
          cursor: SETTINGS_ALLOWED ? 'pointer' : 'default',
        }}
      >
        {label}
      </button>
    )
  }

  return (
    <button
      type="button"
      data-testid="run-analysis-trigger"
      onClick={onLaunch}
      disabled={isRunning}
      style={{
        padding: pad,
        background: 'linear-gradient(135deg, var(--secondary) 0%, var(--primary) 100%)',
        border: 'none',
        borderRadius: 10,
        color: 'var(--text-on-primary)',
        fontFamily: 'var(--font-mono)',
        fontSize,
        fontWeight: 600,
        letterSpacing: '0.04em',
        cursor: isRunning ? 'not-allowed' : 'pointer',
        opacity: isRunning ? 0.5 : 1,
        boxShadow: '0 0 22px var(--secondary-glow)',
      }}
    >
      {isRunning ? t('workspace.ai.running') : t('workspace.ai.cold.launchBtn')}
    </button>
  )
}

function HotState({
  latest,
  timeline,
  isRunning,
  livePrice,
  liveQuoteForeign,
  onRerun,
  onOpen,
}: {
  latest: NonNullable<ReturnType<typeof useLatestArtifact>['latest']>
  timeline: ReturnType<typeof useV5ArtifactTimeline>['data']
  isRunning: boolean
  livePrice: number | null
  liveQuoteForeign: boolean
  onRerun: () => void
  onOpen: (id: string) => void
}): React.ReactElement {
  const { locale, t } = useI18n()
  const verdict = readVerdict(latest)
  const target = latest.target_price ?? null
  // The verdict hue is bound to the directional call (涨绿跌红); the legacy
  // WITHHELD token falls through verdictTone to a neutral slate. The badge hue is
  // NEVER modulated by anything other than the directional call.
  const tone = verdictTone(verdict)
  // Brighter verdict hue for the instrument's signal text/badge (the --card-*-fg
  // variants read crisper at large sizes than base --success/--warning/--danger).
  // Neutral slate for WITHHELD. The hue is STILL bound only to the directional call.
  const signalFg =
    verdict === 'BUY'
      ? 'var(--card-buy-fg)'
      : verdict === 'HOLD'
        ? 'var(--card-hold-fg)'
        : verdict === 'SELL'
          ? 'var(--card-sell-fg)'
          : 'var(--text-secondary)'
  // Withheld POINT target — gate on target===null (verdict-independent). The
  // directional rating still stands; only the precise number is honestly held.
  const targetWithheld = verdict !== null && target === null
  // The gauge's "now" anchor. PREFER the live quote (dedupe-shared from the
  // workspace's price query); fall back to the artifact's entry_price, which is
  // the price AT CREATION — a degraded anchor (it mislabels the gap direction if
  // the price has since moved). The artifact summary carries no per-number source
  // for target_price (only `id`), so the gauge value is plain but still honest;
  // we hand SourcedNumber the artifact_id so the popover still deep-links to the
  // report that produced this target.
  const gaugePrice = livePrice ?? latest.entry_price ?? null
  const gaugeUsingEntry = livePrice == null && latest.entry_price != null
  // vN for the verdict-block header — total versions, latest = newest.
  const versionNum = timeline?.length || 1

  return (
    <>
      {/* Latest report card — the design's "hero report card": ONE flex row of an
          integrated verdict panel (left, full-height, tinted, border-right), a
          flexible target+gauge middle, and an action panel (right, border-left);
          a tagline foot sits below a border-top. overflow:hidden clips the side
          panels to the card's radius so they read as integrated wings, not boxes. */}
      <div
        data-testid="ai-zone-latest"
        style={{
          position: 'relative',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-xl)',
          background: 'var(--bg-card)',
          overflow: 'hidden',
          boxShadow: '0 16px 50px rgba(0, 0, 0, 0.4)',
          marginBottom: 14,
        }}
      >
        {/* signal rail — a thin gradient in the verdict hue along the top edge. */}
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: 2,
            background: `linear-gradient(90deg, transparent, ${signalFg} 30%, ${signalFg} 70%, transparent)`,
            opacity: 0.65,
          }}
        />

        {/* identity (eyebrow + tagline) on the left, the verdict SIGNAL badge on
            the right. The ticker itself lives in the workspace hero above, so the
            card leads with the report's recency + share-card line, not the symbol. */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 18,
            padding: '22px 26px 18px',
            borderBottom: '1px solid var(--border-faint)',
          }}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 9, minWidth: 0 }}>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10.5,
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
                color: 'var(--text-muted)',
              }}
            >
              {t('workspace.ai.versionCurrent')} · v{versionNum} · {ageLabel(latest.created_at)}
            </span>
            {latest.tagline ? (
              <p
                style={{
                  fontSize: 13,
                  color: 'var(--accent-cyan)',
                  fontStyle: 'italic',
                  lineHeight: 1.45,
                  margin: 0,
                  maxWidth: 460,
                  textShadow: '0 0 10px var(--accent-cyan-glow-soft)',
                }}
              >
                "{latest.tagline}"
              </p>
            ) : latest.headline ? (
              <p
                style={{
                  fontSize: 12.5,
                  color: 'var(--text-secondary)',
                  lineHeight: 1.5,
                  margin: 0,
                  maxWidth: 460,
                }}
              >
                {latest.headline.slice(0, 160)}
                {latest.headline.length > 160 ? '…' : ''}
              </p>
            ) : null}
          </div>

          {/* verdict SIGNAL block — always present (the test + product both expect
              a verdict surface on a hot card); the badge itself only renders when a
              directional call exists, else a neutral "no rating" for a thesis-less
              artifact. */}
          <div
            data-testid="ai-zone-verdict-block"
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-end',
              gap: 6,
              flexShrink: 0,
            }}
          >
            {verdict ? (
              <>
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: 10,
                    letterSpacing: '0.12em',
                    textTransform: 'uppercase',
                    color: 'var(--text-muted)',
                  }}
                >
                  {t('workspace.ai.hot.verdictLabel')} · {VERDICT_DESC[verdict] ?? ''}
                </span>
                <span
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 10,
                    padding: '8px 16px',
                    borderRadius: 'var(--radius-pill)',
                    background: tone.bg,
                    border: `1px solid ${tone.border}`,
                    boxShadow: `0 0 22px color-mix(in srgb, ${signalFg} 22%, transparent)`,
                  }}
                >
                  <span
                    style={{
                      width: 9,
                      height: 9,
                      borderRadius: 2,
                      background: signalFg,
                      boxShadow: `0 0 8px color-mix(in srgb, ${signalFg} 70%, transparent)`,
                    }}
                  />
                  <span
                    data-testid="ai-zone-verdict"
                    data-verdict={verdict}
                    style={{
                      fontFamily: 'var(--font-display)',
                      fontSize: verdictLabel(verdict).length > 5 ? 14 : 17,
                      fontWeight: 700,
                      letterSpacing: '2px',
                      color: signalFg,
                    }}
                  >
                    {verdictLabel(verdict)}
                  </span>
                </span>
              </>
            ) : (
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  letterSpacing: '0.06em',
                  textTransform: 'uppercase',
                  color: 'var(--text-dim)',
                }}
              >
                No rating
              </span>
            )}
          </div>
        </div>

        {/* readout tiles + the machined now→target gauge (the chosen "data
            instrument" hero), else the honest withheld note. */}
        <div style={{ padding: '24px 26px 22px' }}>
          {target !== null && gaugePrice !== null && gaugePrice > 0 ? (
            (() => {
              const now = gaugePrice
              const tgt = target
              const up = tgt >= now
              const dir = up ? 'var(--card-buy-fg)' : 'var(--card-sell-fg)'
              const pctMove = ((tgt - now) / now) * 100
              // Instrument scale: a nicely-rounded domain that contains [now, tgt]
              // with ~55% head-room each side, divided into ~7 nice-number ticks.
              const lo = Math.min(now, tgt)
              const hi = Math.max(now, tgt)
              const g = hi - lo || hi * 0.1
              const raw = (hi + g * 0.55 - (lo - g * 0.55)) / 7 || 1
              const e = Math.floor(Math.log10(raw))
              const b = Math.pow(10, e)
              const f = raw / b
              const stp = (f < 1.5 ? 1 : f < 3 ? 2 : f < 7 ? 5 : 10) * b
              const dMin = Math.max(0, Math.floor((lo - g * 0.55) / stp) * stp)
              const dMax = Math.ceil((hi + g * 0.55) / stp) * stp
              const X0 = 70
              const X1 = 694
              const xOf = (v: number) => X0 + ((v - dMin) / (dMax - dMin || 1)) * (X1 - X0)
              const pctOf = (v: number) => ((v - dMin) / (dMax - dMin || 1)) * 100
              const clamp = (x: number) => Math.max(X0 + 6, Math.min(X1 - 6, x))
              const ticks: number[] = []
              for (let v = dMin; v <= dMax + stp * 0.001; v += stp) ticks.push(v)
              const nowX = xOf(now)
              const tgtX = xOf(tgt)
              const fLo = Math.min(nowX, tgtX)
              const fHi = Math.max(nowX, tgtX)
              return (
                <>
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '1fr 1fr 1fr',
                      gap: 12,
                      marginBottom: 18,
                    }}
                  >
                    <div style={readoutTile()}>
                      <span style={readoutKey}>{gaugeUsingEntry ? 'At Report' : 'Now · Spot'}</span>
                      <span style={readoutVal}>
                        <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>$</span>
                        {now.toFixed(2)}
                      </span>
                    </div>
                    <div style={readoutTile(dir)}>
                      <span style={readoutKey}>{t('workspace.ai.hot.target12mo')}</span>
                      <span style={{ ...readoutVal, color: dir }}>
                        <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>$</span>
                        {tgt.toFixed(2)}
                      </span>
                    </div>
                    <div style={readoutTile(dir)}>
                      <span style={readoutKey}>Implied Return</span>
                      <span
                        data-testid="ai-zone-target-upside"
                        style={{
                          ...readoutVal,
                          fontSize: 18,
                          color: dir,
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 5,
                        }}
                      >
                        {up ? '▲ +' : '▼ '}
                        {Math.abs(pctMove).toFixed(1)}%
                      </span>
                    </div>
                  </div>
                  {/* the machined instrument: a calibrated scale with NOW + TARGET
                      markers and a delta read. Self-contained pixel math; values in
                      scope and honest. Colours are tokens only (fill/stroke opacity
                      gives the tints — no hardcoded rgba). */}
                  <div data-testid="ai-zone-target-gauge" style={{ minWidth: 0 }}>
                    <svg
                      viewBox="0 0 764 132"
                      style={{ width: '100%', height: 'auto', display: 'block' }}
                    >
                      <rect
                        x={X0}
                        y={64}
                        width={X1 - X0}
                        height={12}
                        rx={6}
                        fill="var(--bg-elevated)"
                        stroke="var(--border-soft)"
                        strokeWidth={1}
                      />
                      <rect
                        x={fLo}
                        y={64}
                        width={fHi - fLo}
                        height={12}
                        rx={6}
                        fill={dir}
                        fillOpacity={0.24}
                      />
                      {ticks.map((v, i) => (
                        <g key={i}>
                          <line
                            x1={xOf(v)}
                            y1={50}
                            x2={xOf(v)}
                            y2={60}
                            stroke="var(--text-dim)"
                            strokeWidth={1.4}
                            strokeLinecap="round"
                          />
                          <text
                            x={xOf(v)}
                            y={44}
                            fill="var(--text-dim)"
                            textAnchor="middle"
                            style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}
                          >
                            {v.toFixed(0)}
                          </text>
                        </g>
                      ))}
                      {/* TARGET marker (the signal) */}
                      <line
                        data-testid="ai-zone-gauge-target"
                        data-pct={pctOf(tgt).toFixed(2)}
                        x1={tgtX}
                        y1={62}
                        x2={tgtX}
                        y2={106}
                        stroke={dir}
                        strokeWidth={2.4}
                        strokeLinecap="round"
                      />
                      <circle
                        cx={tgtX}
                        cy={70}
                        r={6.5}
                        fill="var(--bg-card)"
                        stroke={dir}
                        strokeWidth={2.4}
                      />
                      <circle cx={tgtX} cy={70} r={2.4} fill={dir} />
                      <g transform={`translate(${clamp(tgtX)},108)`}>
                        <rect
                          x={-46}
                          y={0}
                          width={92}
                          height={20}
                          rx={5}
                          fill={dir}
                          fillOpacity={0.12}
                          stroke={dir}
                          strokeOpacity={0.4}
                        />
                        <text
                          x={0}
                          y={13.5}
                          fill={dir}
                          textAnchor="middle"
                          style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: 10.5,
                            fontWeight: 600,
                          }}
                        >
                          TGT {tgt.toFixed(2)}
                        </text>
                      </g>
                      {/* NOW marker (neutral) */}
                      <line
                        data-testid="ai-zone-gauge-now"
                        data-pct={pctOf(now).toFixed(2)}
                        x1={nowX}
                        y1={24}
                        x2={nowX}
                        y2={78}
                        stroke="var(--text-muted)"
                        strokeWidth={1.4}
                        strokeLinecap="round"
                        strokeDasharray="2.5 3"
                      />
                      <path
                        d={`M${nowX} 56 L${nowX + 6} 64 L${nowX} 72 L${nowX - 6} 64 Z`}
                        fill="var(--text-secondary)"
                        stroke="var(--bg-card)"
                        strokeWidth={1}
                      />
                      <g transform={`translate(${clamp(nowX)},16)`}>
                        <rect
                          x={-44}
                          y={-2}
                          width={88}
                          height={20}
                          rx={5}
                          fill="var(--bg-elevated)"
                          stroke="var(--border-soft)"
                        />
                        <text
                          x={0}
                          y={11.5}
                          fill="var(--text-primary)"
                          textAnchor="middle"
                          style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: 10.5,
                            fontWeight: 600,
                          }}
                        >
                          NOW {now.toFixed(2)}
                        </text>
                      </g>
                      {/* delta bracket between the two markers */}
                      <line x1={fLo} y1={92} x2={fHi} y2={92} stroke={dir} strokeOpacity={0.4} />
                      <line x1={fLo} y1={89} x2={fLo} y2={95} stroke={dir} strokeOpacity={0.4} />
                      <line x1={fHi} y1={89} x2={fHi} y2={95} stroke={dir} strokeOpacity={0.4} />
                      <g transform={`translate(${(fLo + fHi) / 2},92)`}>
                        <rect x={-46} y={-9} width={92} height={18} rx={4} fill="var(--bg-card)" />
                        <text
                          x={0}
                          y={4}
                          fill={dir}
                          textAnchor="middle"
                          style={{
                            fontFamily: 'var(--font-mono)',
                            fontSize: 10.5,
                            fontWeight: 700,
                          }}
                        >
                          {up ? '+' : '−'}${Math.abs(tgt - now).toFixed(2)}
                        </text>
                      </g>
                    </svg>
                    {gaugeUsingEntry && (
                      <p
                        style={{
                          fontFamily: 'var(--font-mono)',
                          fontSize: 9,
                          color: 'var(--text-dim)',
                          marginTop: 6,
                        }}
                      >
                        {liveQuoteForeign
                          ? 'vs price at creation (live quote is in a foreign currency)'
                          : 'vs price at creation (live quote unavailable)'}
                      </p>
                    )}
                  </div>
                </>
              )
            })()
          ) : target !== null ? (
            /* Target exists but no current-price anchor — show the number, omit the
               gauge honestly (degrade = omit, never fabricate a "now"). */
            <div style={{ ...readoutTile(), display: 'inline-flex', minWidth: 200 }}>
              <span style={readoutKey}>{t('workspace.ai.hot.target12mo')}</span>
              <span style={readoutVal}>
                <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>$</span>
                {target.toFixed(2)}
              </span>
            </div>
          ) : targetWithheld ? (
            /* The POINT target was honestly withheld (target_price null) while the
               directional rating still stands — voice it, never a silent gap. */
            <button
              type="button"
              data-testid="ai-zone-target-withheld"
              onClick={() => onOpen(latest.id)}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                background: 'var(--neutral-soft)',
                border: '1px solid var(--neutral-edge)',
                borderRadius: 'var(--radius-md)',
                padding: '12px 14px',
                cursor: 'pointer',
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                lineHeight: 1.5,
                color: 'var(--text-secondary)',
              }}
            >
              {t('hotState.targetWithheld')}
            </button>
          ) : (
            /* Neither a verdict NOR a target number exists (a thesis-less
               artifact). Reaching here means target===null && verdict===null, so
               every branch above declined. Voice a neutral "not yet analyzed"
               line instead of leaving the card's mid-section blank — a normal
               not-run-yet state, NOT an error (no --danger red). */
            <div
              data-testid="ai-zone-not-analyzed"
              style={{
                background: 'var(--neutral-soft)',
                border: '1px solid var(--neutral-edge)',
                borderRadius: 'var(--radius-md)',
                padding: '12px 14px',
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                lineHeight: 1.5,
                color: 'var(--text-muted)',
              }}
            >
              {t('workspace.ai.hot.notAnalyzed')}
            </div>
          )}
        </div>

        {/* actions — a solid blue primary (open report) + a clean ghost (rerun);
            no gradient pill, no decorative arrows. */}
        <div style={{ display: 'flex', gap: 12, padding: '0 26px 24px' }}>
          <button
            type="button"
            data-testid="open-latest-report"
            onClick={() => onOpen(latest.id)}
            style={{
              flex: 1,
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 9,
              padding: '13px 20px',
              background: 'var(--primary)',
              border: '1px solid transparent',
              borderRadius: 'var(--radius-md)',
              color: 'var(--text-on-primary)',
              fontFamily: 'var(--font-body)',
              fontSize: 13,
              fontWeight: 600,
              letterSpacing: '0.01em',
              cursor: 'pointer',
              boxShadow: '0 6px 18px color-mix(in srgb, var(--primary) 22%, transparent)',
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
              <rect
                x="5"
                y="3"
                width="14"
                height="18"
                rx="2.5"
                stroke="currentColor"
                strokeWidth="1.7"
              />
              <path
                d="M9 8 H15 M9 12 H15 M9 16 H13"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinecap="round"
              />
            </svg>
            {t('workspace.ai.hot.openFull')}
          </button>
          <button
            type="button"
            onClick={onRerun}
            disabled={isRunning}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
              padding: '13px 18px',
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border-soft)',
              borderRadius: 'var(--radius-md)',
              color: 'var(--text-secondary)',
              fontFamily: 'var(--font-body)',
              fontSize: 13,
              fontWeight: 600,
              cursor: isRunning ? 'not-allowed' : 'pointer',
              opacity: isRunning ? 0.5 : 1,
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path
                d="M20 7 A8 8 0 1 0 21 13"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinecap="round"
              />
              <path
                d="M20 3 V7.5 H15.5"
                stroke="currentColor"
                strokeWidth="1.7"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            {isRunning ? t('workspace.ai.running') : t('workspace.ai.hot.rerun')}
          </button>
        </div>
      </div>

      {/* Version timeline */}
      {timeline && timeline.length > 0 && (
        <div
          data-testid="ai-zone-timeline"
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-lg)',
            overflow: 'hidden',
          }}
        >
          <div
            style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '15px 18px 11px' }}
          >
            <span
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 11.5,
                fontWeight: 600,
                color: 'var(--text-muted)',
                letterSpacing: '0.14em',
                textTransform: 'uppercase',
              }}
            >
              {t('workspace.ai.hot.history', { n: timeline.length })}
            </span>
          </div>
          {/* One-line verdict-coloured version rail (slice B, approved D-hybrid
              mock): collapse the stacked rows into compact chips so the report's
              version chain reads as a single glance at thesis drift (BUY→HOLD→…)
              without eating the column. Each chip = verdict-hued dot + vN +
              (current) "now"; the verdict word + provider + date live in the
              title tooltip and an sr-only span (a11y + the WITHHELD-stays-neutral
              contract). Click opens that version. */}
          <div
            data-testid="ai-zone-timeline-rail"
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              alignItems: 'center',
              gap: 6,
              padding: '2px 16px 16px',
            }}
          >
            {timeline.slice(0, 8).map((a, i) => {
              const current = a.id === latest.id
              const v = readVerdict(a)
              // Bright verdict hue per version (its directional call); neutral for
              // a thesis-less / WITHHELD artifact — never borrow the amber HOLD hue.
              const sig =
                v === 'BUY'
                  ? 'var(--card-buy-fg)'
                  : v === 'HOLD'
                    ? 'var(--card-hold-fg)'
                    : v === 'SELL'
                      ? 'var(--card-sell-fg)'
                      : 'var(--text-muted)'
              const vNum = Math.max(1, timeline.length - i)
              return (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => onOpen(a.id)}
                  title={`${verdictLabel(v)} · v${vNum} · ${formatDate(a.created_at, locale, 'short')} · ${ageLabel(a.created_at)}${a.primary_provider ? ` · ${a.primary_provider}` : ''}`}
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '4px 10px',
                    borderRadius: 999,
                    border: current
                      ? `1px solid color-mix(in srgb, ${sig} 45%, transparent)`
                      : '1px solid var(--border-faint)',
                    background: current
                      ? `color-mix(in srgb, ${sig} 12%, transparent)`
                      : 'var(--bg-elevated)',
                    boxShadow: current
                      ? `0 0 10px color-mix(in srgb, ${sig} 28%, transparent)`
                      : 'none',
                    cursor: 'pointer',
                    color: 'var(--text-primary)',
                    // Dim retired (stale-archived) versions (BUG-055).
                    opacity: a.archived ? 0.5 : 1,
                  }}
                >
                  <span
                    style={{
                      width: 6,
                      height: 6,
                      borderRadius: 3,
                      background: sig,
                      boxShadow: `0 0 6px color-mix(in srgb, ${sig} 55%, transparent)`,
                      flexShrink: 0,
                    }}
                  />
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: 11,
                      fontWeight: 600,
                      color: current ? sig : 'var(--text-secondary)',
                    }}
                  >
                    v{vNum}
                  </span>
                  {current && (
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: 9,
                        letterSpacing: '0.06em',
                        color: 'var(--text-dim)',
                        textTransform: 'uppercase',
                      }}
                    >
                      {t('workspace.ai.versionNow')}
                    </span>
                  )}
                  {a.archived && <ArchivedPill />}
                  <span
                    data-testid="ai-zone-timeline-verdict"
                    data-verdict={v ?? 'NONE'}
                    style={{
                      color: sig,
                      position: 'absolute',
                      width: 1,
                      height: 1,
                      padding: 0,
                      margin: -1,
                      overflow: 'hidden',
                      clip: 'rect(0 0 0 0)',
                      whiteSpace: 'nowrap',
                      border: 0,
                    }}
                  >
                    {verdictLabel(v)}
                  </span>
                </button>
              )
            })}
          </div>
        </div>
      )}
    </>
  )
}

function VerdictPill({
  verdict,
}: {
  verdict: 'BUY' | 'HOLD' | 'SELL' | 'WITHHELD' | null
}): React.ReactElement {
  const c = verdict
    ? verdictTone(verdict)
    : { bg: 'var(--neutral-soft)', fg: 'var(--text-muted)', border: 'var(--border-soft)' }
  return (
    <span
      data-testid="workspace-verdict-pill"
      data-verdict={verdict ?? 'NONE'}
      style={{
        fontSize: 10,
        padding: '1px 6px',
        borderRadius: 3,
        background: c.bg,
        color: c.fg,
        border: `1px solid ${c.border}`,
        textAlign: 'center',
      }}
    >
      {verdictLabel(verdict)}
    </span>
  )
}

function readVerdict(
  a: { verdict?: string | null } | null,
): 'BUY' | 'HOLD' | 'SELL' | 'WITHHELD' | null {
  // Backend populates `verdict` from summary_extractor.extract_verdict, which
  // pulls thesis.recommendation and normalises to BUY/HOLD/SELL. The verdict is
  // ALWAYS directional now (the REVIEW state is deleted); a legacy artifact that
  // stored recommendation==="REVIEW" is mapped to the neutral "WITHHELD" display
  // token by the backend, which we render as a neutral slate (never "REVIEW").
  // None for artifacts without a thesis (peer_research / ad_hoc) — caller should
  // fall back to showing "—" rather than fabricating a verdict.
  // DO NOT read `signal` here — that's the realised-vs-target outcome
  // (hit / watching / failed), which is a different concept entirely.
  if (!a?.verdict) return null
  const v = a.verdict.toUpperCase()
  if (v === 'BUY' || v === 'HOLD' || v === 'SELL' || v === 'WITHHELD') return v
  // Defensive: a raw legacy "REVIEW" that bypassed the backend mapping still
  // renders as the neutral WITHHELD token, never the forbidden string.
  if (v === 'REVIEW') return 'WITHHELD'
  return null
}

function ageLabel(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(ms / 60_000)
  if (minutes < 1) return tSync('workspace.ai.age.justNow')
  if (minutes < 60) return tSync('workspace.ai.age.minAgo', { n: minutes })
  const hours = Math.round(minutes / 60)
  if (hours < 24) return tSync('workspace.ai.age.hAgo', { n: hours })
  const days = Math.round(hours / 24)
  return tSync('workspace.ai.age.dAgo', { n: days })
}
