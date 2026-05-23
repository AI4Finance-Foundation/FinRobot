// Ticker workspace hero — cosmic redesign (spec §3.2).
//
// 2026-05-22: SplineHero removed from this surface. The 3D AI Analyst
// belongs on /stocks landing only — at the ticker workspace level it was
// (a) duplicating GPU load with the landing backdrop on every nav, and
// (b) competing for attention with the actual financial numbers the user
// came here to read. Single-column layout now; the breadcrumb / symbol /
// price block uses the full hero width.
//
// PipelineProgressPanel takes over the "current status" duty.

import { Link } from 'react-router-dom'
import { useTickerPrice } from '../hooks/useTickerData'
import { useV5ArtifactTimeline } from '../hooks/useV5Artifacts'
import { useRunStreamStore, selectRunByTicker } from '../stores/runStreamStore'
import { useToastStore } from '../stores/toastStore'

// 1 ticker = 1 跑 = 1 份全量 artifact (FinRobot parity 10 章 + 桌面增强).
// dcf / lbo / ddm / comps / ic-memo / earnings 6 个旧 pipeline 后端保留给 SDK
// + `/api/compute/*`，UI 永远不暴露 — 它们的能力都已折进 research。
const PRIMARY_PIPELINE = 'research'

// 旧 artifact 兼容映射：用户历史上跑过的 dcf/lbo/etc artifact 还在 store 里，
// "重跑" 按钮需要把它们映射回 research（因为这些独立 pipeline 已不可达）。
const ARTIFACT_TYPE_TO_PIPELINE: Record<string, string> = {
  equity_research: 'research',
  research: 'research',
  ic_memo: 'research',
  'ic-memo': 'research',
  earnings_analysis: 'research',
  earnings: 'research',
  dcf: 'research',
  lbo: 'research',
  ddm: 'research',
  comps: 'research',
}

const TAGLINES = [
  '确定性计算 · LLM 叙事',
  'NUMBER FIRST · NARRATIVE SECOND',
  '每一个数字 · 都能追溯到函数调用',
  'AI ANALYST · 持续工作中',
] as const

function RefreshIcon({ size = 13 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10" />
      <polyline points="1 20 1 14 7 14" />
      <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  )
}

interface Props {
  ticker: string
}

export function TickerHero({ ticker }: Props): React.ReactElement {
  const { data: price } = useTickerPrice(ticker)

  const runState = useRunStreamStore(selectRunByTicker(ticker))
  const startRun = useRunStreamStore((s) => s.startRun)
  const addToast = useToastStore((s) => s.addToast)
  const { data: artifactTimeline } = useV5ArtifactTimeline(ticker)
  const lastArtifactType = artifactTimeline?.[0]?.type
  const fallbackPipeline = lastArtifactType
    ? ARTIFACT_TYPE_TO_PIPELINE[lastArtifactType] ?? 'research'
    : 'research'
  const lastPipeline = runState?.pipelineType ?? fallbackPipeline
  const rerunBusy = runState?.status === 'running'

  async function handleRerun(): Promise<void> {
    if (rerunBusy) return
    try {
      const runId = await startRun(lastPipeline, ticker)
      addToast({
        type: 'success',
        title: `${ticker} ${lastPipeline} 已重跑`,
        description: `run_id: ${runId.slice(0, 12)} · 顶部进度面板会逐步更新`,
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      addToast({ type: 'error', title: `${ticker} 重跑失败`, description: msg })
    }
  }

  // Primary CTA — one-click full equity research. There is no longer any
  // chevron / secondary menu: 1 ticker = 1 跑 = 1 份 research artifact 含全量
  // (DCF + Comps + Catalysts + Risks + Sensitivity + Earnings + Peers …).
  async function handleLaunchPrimary(): Promise<void> {
    if (rerunBusy) return
    try {
      const runId = await startRun(PRIMARY_PIPELINE, ticker)
      addToast({
        type: 'success',
        title: `${ticker} AI 完整研报已启动`,
        description: `run_id: ${runId.slice(0, 12)} · 顶部进度面板会逐步更新`,
      })
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      addToast({
        type: 'error',
        title: `${ticker} 启动分析失败`,
        description:
          msg.includes('Failed to fetch') || msg.includes('NetworkError')
            ? '后端未响应 — 检查 sidecar 是否启动（StatusBar 应显示「已连接」）'
            : msg,
      })
    }
  }

  const current = price?.current_price
  const changePct = price?.change_pct
  const changeAbs = price?.change ?? undefined
  const isUp = typeof changePct === 'number' && changePct >= 0

  return (
    <header
      data-testid="ticker-hero"
      style={{
        position: 'relative',
        padding: '32px 32px 24px',
        background: 'linear-gradient(180deg, rgba(15,15,34,0.4) 0%, transparent 100%)',
        borderBottom: '1px solid var(--border-faint)',
      }}
    >
      <div
        style={{
          maxWidth: 1280,
          margin: '0 auto',
          minWidth: 0,
        }}
      >
        {/* Single-column hero — Spline 3D moved to /stocks landing only */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24, minWidth: 0 }}>
          <Breadcrumb ticker={ticker} />

          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 16, flexWrap: 'wrap' }}>
              <span
                style={{
                  fontFamily: 'var(--font-display)',
                  fontSize: 80,
                  letterSpacing: 6,
                  color: 'var(--text-primary)',
                  lineHeight: 1,
                  textShadow: '0 0 30px rgba(59,130,246,0.35)',
                }}
              >
                {ticker}
              </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 12,
                  color: 'var(--text-muted)',
                  padding: '4px 10px',
                  border: '1px solid var(--border-soft)',
                  borderRadius: 6,
                  letterSpacing: '0.08em',
                }}
              >
                <span className="cosmic-pulse-dot" style={{ marginRight: 6 }} />
                LIVE · {formatExchange(price?.exchange)}
              </span>
            </div>
            <MorphTagline />
          </div>

          {/* Price block */}
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 18, flexWrap: 'wrap' }}>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 56,
                fontWeight: 500,
                letterSpacing: '-1px',
                color: 'var(--text-primary)',
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {typeof current === 'number' ? `$${current.toFixed(2)}` : '—'}
            </span>
            {typeof changePct === 'number' && (
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  fontFamily: 'var(--font-mono)',
                  fontSize: 17,
                  color: isUp ? 'var(--success)' : 'var(--danger)',
                  padding: '6px 12px',
                  background: isUp ? 'rgba(22,163,74,0.12)' : 'rgba(220,38,38,0.12)',
                  border: `1px solid ${isUp ? 'rgba(22,163,74,0.32)' : 'rgba(220,38,38,0.32)'}`,
                  borderRadius: 8,
                  boxShadow: `0 0 16px ${isUp ? 'var(--success-glow)' : 'var(--danger-glow)'}`,
                  fontVariantNumeric: 'tabular-nums',
                }}
              >
                {isUp ? '↑' : '↓'}{' '}
                {typeof changeAbs === 'number' && (
                  <>
                    {isUp ? '+' : ''}
                    {changeAbs.toFixed(2)} ·{' '}
                  </>
                )}
                {isUp ? '+' : ''}
                {changePct.toFixed(2)}%
              </span>
            )}
          </div>

          {/* Actions — single primary button. 1 ticker = 1 跑 = 1 份 research
              artifact (含 FinRobot 8 章 + 桌面增强：DCF/Comps/Catalysts/
              Risks/Sensitivity/Earnings/Peers …). No secondary menu. */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 4 }}>
            <button
              type="button"
              data-testid="run-analysis-trigger"
              className="btn-shimmer"
              onClick={() => handleLaunchPrimary()}
              disabled={rerunBusy}
              title={rerunBusy ? '当前还有分析在跑' : '一键跑完整研报（10 章 + 全部估值方法 + 桌面增强）'}
              style={{
                opacity: rerunBusy ? 0.5 : 1,
                cursor: rerunBusy ? 'not-allowed' : 'pointer',
              }}
            >
              运行完整分析
            </button>

            <button
              type="button"
              data-testid="rerun-latest"
              onClick={handleRerun}
              disabled={rerunBusy}
              style={{ ...ghostBtnStyle(false), opacity: rerunBusy ? 0.45 : 1, cursor: rerunBusy ? 'not-allowed' : 'pointer' }}
              title={rerunBusy ? '当前还有分析在跑' : '重跑最新研报'}
            >
              <RefreshIcon size={13} /> {rerunBusy ? '正在跑' : '重跑研报'}
            </button>
          </div>
        </div>

      </div>
    </header>
  )
}

// ── Breadcrumb ─────────────────────────────────────────────────────────────
function Breadcrumb({ ticker }: { ticker: string }): React.ReactElement {
  const linkStyle: React.CSSProperties = { color: 'inherit', textDecoration: 'none' }
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        color: 'var(--text-muted)',
        letterSpacing: '0.06em',
        textTransform: 'uppercase',
      }}
    >
      <Link to="/stocks" style={linkStyle}>
        FINAGENT
      </Link>
      <span style={{ color: 'var(--text-dim)' }}>›</span>
      <Link to="/stocks" style={linkStyle}>
        Stocks
      </Link>
      <span style={{ color: 'var(--text-dim)' }}>›</span>
      <span style={{ color: 'var(--accent-cyan)' }}>{ticker}</span>
    </div>
  )
}

// ── Morph tagline (4-phrase cycle) ────────────────────────────────────────
function MorphTagline(): React.ReactElement {
  return (
    <div
      aria-hidden
      style={{
        position: 'relative',
        height: 28,
        marginTop: 12,
        maxWidth: 560,
        overflow: 'hidden',
        fontFamily: 'var(--font-display)',
        fontSize: 15,
        letterSpacing: 1.6,
        color: 'var(--accent-cyan)',
        textShadow: '0 0 12px rgba(34,211,238,0.5)',
      }}
    >
      {TAGLINES.map((t, i) => (
        <span
          key={t}
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            animation: `cosmic-morph 12s ease-in-out infinite`,
            animationDelay: `${i * 3}s`,
            opacity: 0,
          }}
        >
          {t}
        </span>
      ))}
    </div>
  )
}

/**
 * yfinance returns "NasdaqGS" / "NYQ" / "AMEX" raw codes — pretty-print
 * them for the LIVE pill. Falls back to a generic "美股" so non-US tickers
 * (which we don't really support yet) don't show a confusing code.
 */
function formatExchange(raw: string | null | undefined): string {
  if (!raw) return '美股'
  const lower = raw.toLowerCase()
  if (lower.includes('nasdaq') || lower === 'nms' || lower === 'ngm' || lower === 'ncm') return 'NASDAQ'
  if (lower.includes('nyse') || lower === 'nyq' || lower === 'nys') return 'NYSE'
  if (lower.includes('amex') || lower === 'pcx' || lower === 'ase') return 'AMEX'
  if (lower.includes('otc')) return 'OTC'
  return raw.toUpperCase()
}

function ghostBtnStyle(highlighted: boolean): React.CSSProperties {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 8,
    padding: '11px 18px',
    background: highlighted ? 'rgba(245,158,11,0.10)' : 'rgba(15,15,34,0.6)',
    color: highlighted ? '#F59E0B' : 'var(--text-secondary)',
    border: `1px solid ${highlighted ? 'rgba(245,158,11,0.32)' : 'var(--border-soft)'}`,
    borderRadius: 10,
    fontFamily: 'var(--font-mono)',
    fontSize: 12,
    cursor: 'pointer',
    transition: 'all 0.2s',
  }
}

