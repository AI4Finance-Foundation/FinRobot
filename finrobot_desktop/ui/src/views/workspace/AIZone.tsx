// Right column of the workspace dashboard. Surfaces the AI research
// state for a ticker — either cold (no equity_research artifact yet,
// big CTA to run one) or hot (most-recent verdict card + 12-chapter
// preview grid + version timeline).
//
// Does NOT render the chapter contents themselves — clicking a chapter
// or "Open full report" navigates to /stocks/:ticker/runs/:artifactId
// which is where the 12-chapter long-scroll lives.

import { useNavigate } from 'react-router-dom'
import { useLatestArtifact, useV5ArtifactTimeline } from '../../hooks/useV5Artifacts'
import { useRunStreamStore, selectRunByTicker } from '../../stores/runStreamStore'
import { useToastStore } from '../../stores/toastStore'
import { PipelineProgressPanel } from '../PipelineProgressPanel'

interface AIZoneProps {
  ticker: string
}

const CHAPTERS = [
  { num: '00', name: 'Cover' },
  { num: '01', name: 'Investment Thesis' },
  { num: '02', name: 'Company Overview' },
  { num: '03', name: 'Financial Analysis' },
  { num: '04', name: 'Valuation' },
  { num: '05', name: 'News & Events' },
  { num: '06', name: 'Sensitivity' },
  { num: '07', name: 'Catalysts' },
  { num: '08', name: 'Technical' },
  { num: '09', name: 'Competitive' },
  { num: '10', name: 'Financial Data' },
  { num: '11', name: 'Disclaimer' },
] as const

const CHAPTER_ID_MAP: Record<string, string> = {
  '00': 'cover',
  '01': 'thesis',
  '02': 'overview',
  '03': 'financial',
  '04': 'valuation',
  '05': 'news',
  '06': 'sensitivity',
  '07': 'catalysts',
  '08': 'technical',
  '09': 'competitive',
  '10': 'data',
  '11': 'disclaimer',
}

export function AIZone({ ticker }: AIZoneProps): React.ReactElement {
  const navigate = useNavigate()
  const { latest } = useLatestArtifact(ticker, 'equity_research')
  const { data: timeline } = useV5ArtifactTimeline(ticker)
  const startRun = useRunStreamStore((s) => s.startRun)
  const runState = useRunStreamStore(selectRunByTicker(ticker))
  const addToast = useToastStore((s) => s.addToast)

  const sameTypeTimeline = (timeline ?? []).filter((a) => a.type === 'equity_research')
  const isRunning = runState?.status === 'running'

  async function launchResearch(): Promise<void> {
    if (isRunning) {
      addToast({
        type: 'info',
        title: `${ticker} 已有 ${runState?.pipelineType} 跑在进行中`,
        description: '等当前 run 结束再起新的',
      })
      return
    }
    try {
      const runId = await startRun('research', ticker)
      addToast({
        type: 'success',
        title: `${ticker} 研报已启动`,
        description: `run_id: ${runId.slice(0, 12)} · ~60s 完成后在此处刷新`,
      })
    } catch (err) {
      addToast({
        type: 'error',
        title: '启动研报失败',
        description: err instanceof Error ? err.message : String(err),
      })
    }
  }

  // Three states share this column:
  //   running  → progress panel only (cold/hot would be misleading)
  //   has artifact → hot card stack
  //   neither  → cold CTA
  // After the run completes, PipelineProgressPanel keeps showing its
  // "完成 · 总耗时 Xs" header (with → 打开研报 / ✕ dismiss buttons) UNTIL
  // the user dismisses it; the hot card renders below it in the meantime
  // so the analyst sees the new verdict immediately.
  const showProgress = !!runState && !runState.dismissed

  return (
    <section data-testid="ai-zone">
      <ZoneHeader hasArtifact={!!latest} versionsCount={sameTypeTimeline.length} />
      <p style={zoneDesc}>
        research pipeline 跑出来的 artifact · 含 8 LLM agents 叙事 + DCF / Comps / Peers 确定性计算。
      </p>

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
      ) : !isRunning && !latest ? (
        <ColdState ticker={ticker} isRunning={isRunning} onLaunch={launchResearch} />
      ) : null}
    </section>
  )
}

function ZoneHeader({
  hasArtifact,
  versionsCount,
}: {
  hasArtifact: boolean
  versionsCount: number
}): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'baseline',
        gap: 12,
        marginBottom: 14,
        paddingBottom: 8,
        borderBottom: '1px solid rgba(139, 92, 246, 0.3)',
      }}
    >
      <span
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 16,
          letterSpacing: '2px',
          color: 'var(--secondary)',
          textShadow: '0 0 12px rgba(139, 92, 246, 0.4)',
        }}
      >
        🤖 AI 研报
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
        {hasArtifact ? `当前 v · 共 ${versionsCount} 份` : '未跑过'}
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
  onLaunch,
}: {
  ticker: string
  isRunning: boolean
  onLaunch: () => void
}): React.ReactElement {
  return (
    <div
      data-testid="ai-zone-cold"
      style={{
        background: 'rgba(15, 15, 34, 0.3)',
        border: '1px dashed rgba(139, 92, 246, 0.2)',
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
        还未为 {ticker} 生成研报
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
        跑一次 <strong style={{ color: 'var(--accent-cyan)' }}>research</strong> pipeline 即生成 12 章节投行级研报：
        投资论点 · 公司概览 · 财务分析 · 估值（DCF + Comps + DDM + LBO）· 新闻 · 敏感度 · 催化剂 · 技术分析 · 同业对标 · 财务数据
      </p>
      <button
        type="button"
        data-testid="run-analysis-trigger"
        onClick={onLaunch}
        disabled={isRunning}
        style={{
          padding: '17px 32px',
          background: 'linear-gradient(135deg, var(--secondary) 0%, var(--primary) 100%)',
          border: 'none',
          borderRadius: 10,
          color: 'white',
          fontFamily: 'var(--font-mono)',
          fontSize: 14,
          fontWeight: 600,
          letterSpacing: '0.04em',
          cursor: isRunning ? 'not-allowed' : 'pointer',
          opacity: isRunning ? 0.5 : 1,
          boxShadow: '0 0 22px rgba(139, 92, 246, 0.4)',
        }}
      >
        {isRunning ? '正在跑 …' : '▶ 立即跑 AI 研报（~60s）'}
      </button>
      <p
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-dim)',
          marginTop: 14,
        }}
      >
        artifact 一旦生成不可变 · 重跑追加新版本，不覆盖旧版
      </p>
    </div>
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
  const verdict = readVerdict(latest)
  const target = latest.target_price ?? null
  const verdictTone =
    verdict === 'BUY'
      ? { bg: 'rgba(22, 163, 74, 0.18)', fg: 'var(--success)', glow: 'rgba(22, 163, 74, 0.3)' }
      : verdict === 'SELL'
        ? { bg: 'rgba(220, 38, 38, 0.18)', fg: 'var(--danger)', glow: 'rgba(220, 38, 38, 0.3)' }
        : { bg: 'rgba(217, 119, 6, 0.18)', fg: 'var(--warning)', glow: 'rgba(217, 119, 6, 0.3)' }

  return (
    <>
      {/* Latest report card */}
      <div
        data-testid="ai-zone-latest"
        style={{
          background: 'linear-gradient(160deg, rgba(139, 92, 246, 0.06), rgba(15, 15, 34, 0.4))',
          border: '1px solid rgba(139, 92, 246, 0.28)',
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
            📄 最新研报
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
              style={{
                fontFamily: 'var(--font-display)',
                fontSize: 28,
                letterSpacing: '4px',
                padding: '4px 20px',
                background: verdictTone.bg,
                color: verdictTone.fg,
                border: `1.5px solid ${verdictTone.fg}`,
                borderRadius: 8,
                boxShadow: `0 0 18px ${verdictTone.glow}`,
              }}
            >
              {verdict}
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

        {latest.headline && (
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
        )}

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button
            type="button"
            data-testid="open-latest-report"
            onClick={() => onOpen(latest.id)}
            style={{
              padding: '11px 18px',
              background: 'linear-gradient(135deg, var(--secondary) 0%, var(--primary) 100%)',
              border: 'none',
              borderRadius: 8,
              color: 'white',
              fontFamily: 'var(--font-mono)',
              fontSize: 12.5,
              fontWeight: 600,
              cursor: 'pointer',
              letterSpacing: '0.04em',
              boxShadow: '0 0 16px rgba(139, 92, 246, 0.35)',
            }}
          >
            → 打开完整 12 章研报
          </button>
          <button
            type="button"
            onClick={onRerun}
            disabled={isRunning}
            style={ghostBtn(isRunning)}
          >
            {isRunning ? '正在跑 …' : '↻ 重跑'}
          </button>
        </div>
      </div>

      {/* Chapter mini-grid */}
      <div
        data-testid="ai-zone-chapters"
        style={{
          background: 'linear-gradient(160deg, rgba(139, 92, 246, 0.06), rgba(15, 15, 34, 0.4))',
          border: '1px solid rgba(139, 92, 246, 0.28)',
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
            📑 12 章节快速跳转
          </span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
          {CHAPTERS.map((c) => (
            <button
              key={c.num}
              type="button"
              onClick={() => navigate(`/stocks/${ticker}/runs/${latest.id}#${CHAPTER_ID_MAP[c.num]}`)}
              style={{
                textAlign: 'left',
                padding: 10,
                background: 'rgba(15, 15, 34, 0.5)',
                border: '1px solid var(--border-faint)',
                borderRadius: 6,
                cursor: 'pointer',
                transition: 'all 0.18s',
                color: 'inherit',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = 'var(--secondary)'
                e.currentTarget.style.background = 'rgba(139, 92, 246, 0.08)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = 'var(--border-faint)'
                e.currentTarget.style.background = 'rgba(15, 15, 34, 0.5)'
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
                {c.name}
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
            background: 'linear-gradient(160deg, rgba(139, 92, 246, 0.06), rgba(15, 15, 34, 0.4))',
            border: '1px solid rgba(139, 92, 246, 0.28)',
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
              ⏱ 历史版本 · {timeline.length} 份
            </span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {timeline.slice(0, 5).map((a) => {
              const current = a.id === latest.id
              const v = readVerdict(a)
              const tone = v === 'BUY' ? 'buy' : v === 'SELL' ? 'sell' : 'hold'
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
                    background: current ? 'rgba(139, 92, 246, 0.08)' : 'rgba(15, 15, 34, 0.5)',
                    border: 'none',
                    borderLeft: `2px solid ${current ? 'var(--secondary)' : 'var(--border-soft)'}`,
                    borderRadius: '0 6px 6px 0',
                    cursor: 'pointer',
                    fontFamily: 'var(--font-mono)',
                    fontSize: 11.5,
                    textAlign: 'left',
                    color: 'var(--text-primary)',
                  }}
                >
                  <span style={{ fontWeight: 600 }}>{current ? 'current' : ''}</span>
                  <VerdictPill tone={tone}>{v ?? '—'}</VerdictPill>
                  <span style={{ color: 'var(--text-secondary)' }}>
                    {a.target_price !== null && a.target_price !== undefined
                      ? `$${a.target_price.toFixed(0)}`
                      : '—'}
                  </span>
                  <span style={{ color: 'var(--text-dim)', fontSize: 10.5 }}>
                    {new Date(a.created_at).toLocaleString('zh-CN', {
                      month: '2-digit',
                      day: '2-digit',
                    })}{' '}
                    · {ageLabel(a.created_at)}
                  </span>
                  <span style={{ color: 'var(--secondary)', textDecoration: 'underline' }}>
                    打开 →
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
  tone,
  children,
}: {
  tone: 'buy' | 'sell' | 'hold'
  children: React.ReactNode
}): React.ReactElement {
  const colors = {
    buy: { bg: 'rgba(22, 163, 74, 0.18)', fg: 'var(--success)' },
    sell: { bg: 'rgba(220, 38, 38, 0.18)', fg: 'var(--danger)' },
    hold: { bg: 'rgba(217, 119, 6, 0.18)', fg: 'var(--warning)' },
  }
  const c = colors[tone]
  return (
    <span
      style={{
        fontSize: 10,
        padding: '1px 6px',
        borderRadius: 3,
        background: c.bg,
        color: c.fg,
        textAlign: 'center',
      }}
    >
      {children}
    </span>
  )
}

function readVerdict(
  a: { verdict?: string | null } | null,
): 'BUY' | 'HOLD' | 'SELL' | null {
  // Backend populates `verdict` from summary_extractor.extract_verdict
  // which pulls thesis.recommendation and normalises to BUY/HOLD/SELL.
  // None for artifacts without a thesis (peer_research / ad_hoc) — caller
  // should fall back to showing "—" rather than fabricating a verdict.
  // DO NOT read `signal` here — that's the realised-vs-target outcome
  // (hit / watching / failed), which is a different concept entirely.
  if (!a?.verdict) return null
  const v = a.verdict.toUpperCase()
  return v === 'BUY' || v === 'HOLD' || v === 'SELL' ? v : null
}

function ageLabel(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime()
  const minutes = Math.round(ms / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.round(hours / 24)
  return `${days} 天前`
}

function ghostBtn(disabled: boolean): React.CSSProperties {
  return {
    padding: '11px 18px',
    background: 'rgba(15, 15, 34, 0.6)',
    border: '1px solid var(--border-soft)',
    borderRadius: 8,
    color: 'var(--text-secondary)',
    fontFamily: 'var(--font-mono)',
    fontSize: 12,
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.45 : 1,
  }
}
