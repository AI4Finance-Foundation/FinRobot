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
import { useRunStreamStore, selectRunByTicker } from '../../stores/runStreamStore'
import { useToastStore } from '../../stores/toastStore'
import { useHealth } from '../../hooks/useHealth'
import { PipelineProgressPanel } from '../PipelineProgressPanel'
import { verdictLabel, verdictTone } from '../../utils/verdict'
import { formatDate } from '../../utils/format'
import { mapErrorToUserMessage } from '../../utils/errorMessage'
import { useI18n, tSync, type Locale } from '../../i18n'
import { allChapterLabels } from '../../pages/artifact-detail/chapters/labels'
import type { ArtifactSummaryV5 } from '../../types/v5'
import { ArchivedPill } from '../../components/ArchivedPill'

// Display label per non-research artifact type (dcf / lbo / comps / …). Kept
// inline (not in .po) per the VersionDiffBanner precedent — these are short,
// stable model names. Mirror of CompactArtifactViewer's TYPE_LABEL so the
// workspace and the detail page name the same artifact identically.
const ARTIFACT_TYPE_LABEL: Record<string, { zh: string; en: string }> = {
  dcf: { zh: 'DCF 估值', en: 'DCF Valuation' },
  lbo: { zh: 'LBO 模型', en: 'LBO Model' },
  ddm: { zh: 'DDM 股利贴现', en: 'DDM Valuation' },
  comps: { zh: '可比公司', en: 'Comparable Companies' },
  earnings: { zh: '财报质量', en: 'Earnings Quality' },
  ic_memo: { zh: '投委会备忘录', en: 'IC Memo' },
  peer_research: { zh: '同业研究', en: 'Peer Research' },
  ad_hoc: { zh: '即席分析', en: 'Ad-hoc Analysis' },
}

function artifactTypeLabel(type: string, locale: Locale): string {
  const m = ARTIFACT_TYPE_LABEL[type]
  if (m) return locale === 'zh' ? m.zh : m.en
  return type
}

// Friendly, actionable copy for each preflight failure (BUG-027) — what's
// wrong + that Settings is where to fix it. Inline literals per the
// VersionDiffBanner precedent.
type PreflightReason = 'offline' | 'needsModel' | 'config' | 'providers' | null

function preflightDescription(reason: PreflightReason, locale: Locale): string {
  const zh = locale === 'zh'
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
    // limit 200 == the timeline query below, so both subscribe to the SAME
    // react-query key → one request, one truncation caliber (was a second
    // default-50 fetch whose "latest" could disagree with the 200-row list).
  } = useLatestArtifact(ticker, 'equity_research', 200)
  const {
    data: timeline,
    isLoading: timelineLoading,
    isError: timelineError,
    refetch: timelineRefetch,
    // limit 200 to match the report page / Coverage Inspector ceiling so this
    // preview reads from the same cached "full history" page rather than its own
    // truncated default-50 slice for the same ticker (BUG-056).
  } = useV5ArtifactTimeline(ticker, 200)
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

  const sameTypeTimeline = (timeline ?? []).filter((a) => a.type === 'equity_research')
  // BUG-040: all NON-equity_research artifacts (dcf / lbo / comps / earnings /
  // ic_memo / …). The landing recent strip counts ALL artifact types, so a
  // ticker that only has these must NOT fall through to the cold "run research"
  // empty state — that buries reachable model results. Surface them in their
  // own labelled section, newest first.
  const otherArtifacts = (timeline ?? []).filter((a) => a.type !== 'equity_research')
  const hasOtherArtifacts = otherArtifacts.length > 0
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

  // Show error state only when both queries failed AND the run is not active
  // (a running pipeline masks stale query errors — user knows data is being
  // fetched). Loading while !latest falls naturally into ColdState below so
  // run-analysis-trigger remains visible immediately on first render.
  const isError = (artifactError || timelineError) && !isRunning

  function handleRetry(): void {
    void artifactRefetch()
    void timelineRefetch()
  }

  async function launchResearch(): Promise<void> {
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
    // Preflight guard (BUG-027): never POST /api/runs when a precondition is
    // known-bad — the run would 503/500 and we'd leak a raw HTTP toast. Route
    // the user to Settings instead. (The CTA is also disabled, so this is a
    // belt-and-braces guard for any non-button caller like onRerun.)
    if (preflightBlocked) {
      addToast({
        type: 'error',
        title: locale === 'zh' ? '无法启动研报' : 'Can’t start the report',
        description: preflightDescription(preflightReason, locale),
      })
      navigate('/settings')
      return
    }
    try {
      await startRun('research', ticker)
      addToast({
        type: 'success',
        title: t('workspace.ai.toast.launched', { ticker }),
        description: t('workspace.ai.toast.launchedDesc'),
      })
    } catch (err) {
      addToast({
        type: 'error',
        title: t('workspace.ai.toast.launchFailed'),
        description: mapErrorToUserMessage(err),
      })
    }
  }

  // Four states for the AI column:
  //   error    → backend 5xx / network down — show actionable error + retry
  //   running  → progress panel only (cold/hot would be misleading)
  //   has artifact → hot card stack
  //   neither (including initial loading) → cold CTA
  //     loading: query still in-flight → ColdState with subtle indicator
  //     cold: genuinely no artifact yet → full ColdState with run trigger
  // After the run completes, PipelineProgressPanel keeps showing its
  // "完成 · 总耗时 Xs" header (→ 打开研报 / ✕ dismiss) until dismissed.
  const showProgress = !!runState && !runState.dismissed
  const isQuerying = (artifactLoading || timelineLoading) && !isRunning

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
      <ZoneHeader hasArtifact={!!latest} versionsCount={sameTypeTimeline.length} />
      <p style={zoneDesc}>{t('workspace.ai.zoneDesc')}</p>

      {showProgress && <PipelineProgressPanel ticker={ticker} />}

      {latest && !isRunning ? (
        <HotState
          ticker={ticker}
          latest={latest}
          timeline={sameTypeTimeline}
          isRunning={isRunning}
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
      ) : !isRunning && !latest && !nonResearchResult ? (
        // Don't drop a just-finished non-research run (DCF/LBO/comps/earnings)
        // into ColdState's "run research" prompt — that buries the result the
        // user just produced. The PipelineProgressPanel above stays visible
        // with its "open" CTA pointing at run.artifactId, so the result is
        // reachable. Only show ColdState when there's genuinely nothing.
        <ColdState
          ticker={ticker}
          isRunning={isRunning}
          isQuerying={isQuerying}
          preflightBlocked={preflightBlocked}
          preflightReason={preflightReason}
          onLaunch={launchResearch}
        />
      ) : null}

      {/* BUG-040: full model-artifact timeline (non-equity_research). Always
          rendered when present — whether or not a full report exists — so DCF /
          LBO / comps / earnings runs the landing strip counts are reachable
          from the workspace. Each row routes to the detail page's type router. */}
      {!isRunning && otherArtifacts.length > 0 && (
        <OtherArtifacts
          artifacts={otherArtifacts}
          locale={locale}
          onOpen={(id) => navigate(`/stocks/${ticker}/runs/${id}`)}
        />
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
        background: 'var(--gradient-card-cosmic)',
        border: '1px solid var(--secondary-strong)',
        borderRadius: 'var(--radius-md)',
        padding: '14px 16px',
        marginTop: 14,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--secondary)',
            letterSpacing: '0.08em',
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
              <span style={{ color: 'var(--secondary)', fontWeight: 600 }}>
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
              <span style={{ color: 'var(--secondary)', textDecoration: 'underline' }}>
                {zh ? '打开 →' : 'Open →'}
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
}: {
  hasArtifact: boolean
  versionsCount: number
}): React.ReactElement {
  const { t } = useI18n()
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'baseline',
        gap: 12,
        marginBottom: 14,
        paddingBottom: 8,
        borderBottom: '1px solid var(--secondary-edge)',
      }}
    >
      <span
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 16,
          letterSpacing: '2px',
          color: 'var(--secondary)',
          textShadow: '0 0 12px var(--secondary-glow)',
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
        {hasArtifact
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

function ColdState({
  ticker,
  isRunning,
  isQuerying,
  preflightBlocked,
  preflightReason,
  onLaunch,
}: {
  ticker: string
  isRunning: boolean
  isQuerying: boolean
  preflightBlocked: boolean
  preflightReason: PreflightReason
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
      {isQuerying && (
        <div
          data-testid="ai-zone-loading"
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10.5,
            color: 'var(--text-dim)',
            marginBottom: 10,
            letterSpacing: '0.04em',
          }}
        >
          {t('workspace.ai.cold.checking')}
        </div>
      )}
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
    const label =
      preflightReason === 'offline'
        ? zh
          ? '⚠ 后端未连接 · 重试数据源'
          : '⚠ Backend offline · retry data source'
        : zh
          ? '⚠ 去设置补全配置'
          : '⚠ Fix config in Settings'
    return (
      <button
        type="button"
        data-testid="run-analysis-blocked"
        onClick={() => navigate('/settings')}
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
          cursor: 'pointer',
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
  ticker,
  latest,
  timeline,
  isRunning,
  onRerun,
  onOpen,
}: {
  ticker: string
  latest: NonNullable<ReturnType<typeof useLatestArtifact>['latest']>
  timeline: ReturnType<typeof useV5ArtifactTimeline>['data']
  isRunning: boolean
  onRerun: () => void
  onOpen: (id: string) => void
}): React.ReactElement {
  const navigate = useNavigate()
  const { locale, t } = useI18n()
  const verdict = readVerdict(latest)
  const target = latest.target_price ?? null
  // The verdict hue is bound to the directional call (涨绿跌红); the legacy
  // WITHHELD token falls through verdictTone to a neutral slate. The badge hue is
  // NEVER modulated by anything other than the directional call.
  const tone = verdictTone(verdict)
  // Withheld POINT target — gate on target===null (verdict-independent). The
  // directional rating still stands; only the precise number is honestly held.
  const targetWithheld = verdict !== null && target === null

  return (
    <>
      {/* Latest report card */}
      <div
        data-testid="ai-zone-latest"
        style={{
          background: 'var(--gradient-card-cosmic)',
          border: '1px solid var(--secondary-strong)',
          borderRadius: 'var(--radius-md)',
          padding: '18px 20px',
          marginBottom: 14,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--secondary)',
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
            }}
          >
            {t('workspace.ai.hot.latestReport')}
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10,
              padding: '2px 7px',
              borderRadius: 3,
              background: 'var(--secondary-soft)',
              color: 'var(--secondary)',
            }}
          >
            current
          </span>
          <span
            style={{
              marginLeft: 'auto',
              fontFamily: 'var(--font-mono)',
              fontSize: 10.5,
              color: 'var(--text-muted)',
            }}
          >
            @ {ageLabel(latest.created_at)}
          </span>
        </div>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 16,
            marginBottom: 14,
            flexWrap: 'wrap',
          }}
        >
          {verdict && (
            <span
              data-testid="ai-zone-verdict"
              data-verdict={verdict}
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 28,
                letterSpacing: '4px',
                padding: '4px 20px',
                background: tone.bg,
                color: tone.fg,
                border: `1.5px solid ${tone.border}`,
                borderRadius: 8,
              }}
            >
              {verdictLabel(verdict)}
            </span>
          )}
          {target !== null && (
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10.5,
                  color: 'var(--text-muted)',
                  letterSpacing: '0.06em',
                  textTransform: 'uppercase',
                }}
              >
                12-Month Target
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 30,
                  fontWeight: 600,
                  color: 'var(--text-primary)',
                  fontVariantNumeric: 'tabular-nums',
                  lineHeight: 1.1,
                }}
              >
                ${target.toFixed(2)}
              </span>
            </div>
          )}
        </div>

        {/* The POINT target was honestly withheld (target_price null) while the
            directional rating still stands — gate on target===null, NOT on any
            verdict value. Voice the withholding instead of leaving a silent gap;
            this honesty is the product's point, not a defect. Neutral slate, the
            directional badge above keeps its 涨绿跌红 hue. */}
        {targetWithheld && (
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
              borderRadius: 'var(--radius-sm)',
              padding: '10px 12px',
              marginBottom: 14,
              cursor: 'pointer',
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
              lineHeight: 1.5,
              color: 'var(--text-secondary)',
            }}
          >
            {t('hotState.targetWithheld')}
          </button>
        )}

        {/* Prefer the real synthesis_agent tagline (≤60 char LLM-written
            share-card line) over the generic pipeline.format_summary
            preview that's stored in headline. tagline lands on
            ArtifactSummaryV5 via summary_extractor.extract_tagline. */}
        {latest.tagline ? (
          <p
            style={{
              fontSize: 14,
              color: 'var(--accent-cyan)',
              fontStyle: 'italic',
              lineHeight: 1.55,
              marginBottom: 14,
              textShadow: '0 0 10px var(--accent-cyan-glow-soft)',
            }}
          >
            "{latest.tagline}"
          </p>
        ) : latest.headline ? (
          <p
            style={{
              fontSize: 13,
              color: 'var(--text-secondary)',
              lineHeight: 1.6,
              marginBottom: 14,
            }}
          >
            {latest.headline.slice(0, 200)}
            {latest.headline.length > 200 ? '…' : ''}
          </p>
        ) : null}

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            type="button"
            data-testid="open-latest-report"
            onClick={() => onOpen(latest.id)}
            style={{
              padding: '11px 18px',
              background: 'linear-gradient(135deg, var(--secondary) 0%, var(--primary) 100%)',
              border: 'none',
              borderRadius: 'var(--radius-sm)',
              color: 'var(--text-on-primary)',
              fontFamily: 'var(--font-mono)',
              fontSize: 12.5,
              fontWeight: 600,
              cursor: 'pointer',
              letterSpacing: '0.04em',
              boxShadow: '0 0 16px var(--secondary-glow-soft)',
            }}
          >
            {t('workspace.ai.hot.openFull')}
          </button>
          <button type="button" onClick={onRerun} disabled={isRunning} style={ghostBtn(isRunning)}>
            {isRunning ? t('workspace.ai.running') : t('workspace.ai.hot.rerun')}
          </button>
        </div>
      </div>

      {/* Chapter mini-grid */}
      <div
        data-testid="ai-zone-chapters"
        style={{
          background: 'var(--gradient-card-cosmic)',
          border: '1px solid var(--secondary-strong)',
          borderRadius: 'var(--radius-md)',
          padding: '14px 16px',
          marginBottom: 14,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--secondary)',
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
            }}
          >
            {t('workspace.ai.hot.chapterJump')}
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
          {allChapterLabels(locale).map((c) => (
            <button
              key={c.id}
              type="button"
              onClick={() => navigate(`/stocks/${ticker}/runs/${latest.id}#${c.id}`)}
              style={{
                textAlign: 'left',
                padding: 10,
                background: 'var(--bg-card-translucent)',
                border: '1px solid var(--border-faint)',
                borderRadius: 6,
                cursor: 'pointer',
                transition: 'all 0.18s',
                color: 'inherit',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--secondary)'
                e.currentTarget.style.background = 'var(--secondary-hover)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--border-faint)'
                e.currentTarget.style.background = 'var(--bg-card-translucent)'
              }}
            >
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  color: 'var(--text-dim)',
                  letterSpacing: '0.06em',
                }}
              >
                {c.num}
              </div>
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 11,
                  color: 'var(--text-primary)',
                  marginTop: 2,
                }}
              >
                {c.title}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Version timeline */}
      {timeline && timeline.length > 0 && (
        <div
          data-testid="ai-zone-timeline"
          style={{
            background: 'var(--gradient-card-cosmic)',
            border: '1px solid var(--secondary-strong)',
            borderRadius: 'var(--radius-md)',
            padding: '14px 16px',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--secondary)',
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
              }}
            >
              {t('workspace.ai.hot.history', { n: timeline.length })}
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {timeline.slice(0, 5).map((a) => {
              const current = a.id === latest.id
              const v = readVerdict(a)
              return (
                <button
                  key={a.id}
                  type="button"
                  onClick={() => onOpen(a.id)}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '50px 60px 80px 1fr auto',
                    gap: 10,
                    alignItems: 'center',
                    padding: '8px 10px',
                    background: current ? 'var(--secondary-hover)' : 'var(--bg-card-translucent)',
                    border: 'none',
                    borderLeft: `2px solid ${current ? 'var(--secondary)' : 'var(--border-soft)'}`,
                    borderRadius: '0 6px 6px 0',
                    cursor: 'pointer',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11.5,
                    textAlign: 'left',
                    color: 'var(--text-primary)',
                    // Dim retired (stale-archived) versions (BUG-055).
                    opacity: a.archived ? 0.6 : 1,
                  }}
                >
                  <span style={{ fontWeight: 600 }}>{current ? 'current' : ''}</span>
                  <VerdictPill verdict={v} />
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
                    style={{
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'flex-end',
                    }}
                  >
                    {a.archived && <ArchivedPill />}
                    <span style={{ color: 'var(--secondary)', textDecoration: 'underline' }}>
                      {t('workspace.ai.hot.openArrow')}
                    </span>
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

function ghostBtn(disabled: boolean): React.CSSProperties {
  return {
    padding: '11px 18px',
    background: 'var(--bg-card-deep)',
    border: '1px solid var(--border-soft)',
    borderRadius: 8,
    color: 'var(--text-secondary)',
    fontFamily: 'var(--font-mono)',
    fontSize: 12,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.45 : 1,
  }
}
