// ArtifactDetailPage — single artifact deep-dive route.
//
// Mounted at `/stocks/:ticker/runs/:artifactId`. Renders the full Artifact
// payload (outputs.structured + assumptions + inputs.raw_data summary +
// warnings + compute_version + meta) in cosmic-card panels so the user
// can audit every number a past pipeline run produced.
//
// Why this exists: MyResearchFeed cards used to be unclickable — once a
// run finished the user could only re-read the 200-char headline. This
// page is the "open the actual research" surface.

import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useArtifactDetail, useV5ArtifactTimeline } from '../hooks/useV5Artifacts'
import { ArtifactDiff } from '../components/ArtifactDiff'
import type { ArtifactSummaryV5 } from '../types/v5'

interface ArtifactInputs {
  data_source?: string
  data_fetched_at?: string
  raw_data?: Record<string, unknown>
}

interface ArtifactAssumptions {
  parameters?: Record<string, unknown>
  assumption_provenance?: Record<string, unknown>
}

interface ArtifactComputeVersion {
  version?: string
  git_commit?: string
  formula_id?: string
  formula_warnings?: string[]
}

interface ArtifactOutputs {
  structured?: Record<string, unknown>
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
  const { data, isLoading, isError, error } = useArtifactDetail(artifactId)
  const { data: timeline } = useV5ArtifactTimeline(symbol)
  const [compareB, setCompareB] = useState<ArtifactSummaryV5 | null>(null)

  if (!artifactId) {
    return <EmptyPanel title="缺少 artifact 编号" body="访问路径不完整 · 回工作区重新选择研报。" />
  }

  if (isLoading) {
    return (
      <div style={pagePadding}>
        <BackNav ticker={symbol} />
        <Skeleton />
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div style={pagePadding}>
        <BackNav ticker={symbol} />
        <EmptyPanel
          title="加载失败"
          body={error?.message ?? '后端未返回 artifact · 检查 server 是否启动。'}
        />
      </div>
    )
  }

  const inputs = data.inputs as ArtifactInputs
  const assumptions = data.assumptions as ArtifactAssumptions
  const outputs = data.outputs as ArtifactOutputs
  const meta = data.meta as ArtifactMeta
  const compute_version = (data as unknown as { compute_version?: ArtifactComputeVersion })
    .compute_version

  const structuredEntries = Object.entries(outputs.structured ?? {})
  const assumptionEntries = Object.entries(assumptions.parameters ?? {})
  const inputEntries = Object.entries(inputs.raw_data ?? {})

  return (
    <div style={pagePadding}>
      <BackNav ticker={symbol} />

      <header
        className="cosmic-card"
        style={{ marginBottom: 24, padding: '24px 28px' }}
      >
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            letterSpacing: '0.12em',
            color: 'var(--accent-cyan)',
            textTransform: 'uppercase',
            marginBottom: 6,
          }}
        >
          ARTIFACT · {data.type}
        </div>
        <h1
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 28,
            letterSpacing: 2.5,
            color: 'var(--text-primary)',
            marginBottom: 12,
          }}
        >
          {symbol} · {chineseLabel(data.type)}
        </h1>
        <p
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: 13,
            color: 'var(--text-secondary)',
            margin: 0,
            lineHeight: 1.55,
          }}
        >
          {data.headline}
        </p>
        <MetaBar created={meta.created_at} source={meta.source} version={compute_version} />
        <CompareVersionPicker
          currentId={artifactId}
          currentType={data.type}
          timeline={timeline ?? []}
          onPick={setCompareB}
        />
      </header>

      {compareB && data && (
        <ArtifactDiff
          artifactA={{
            id: artifactId,
            created_at: (meta.created_at as string) ?? compareB.created_at,
            headline: data.headline,
            type: data.type,
          }}
          artifactB={{
            id: compareB.id,
            created_at: compareB.created_at,
            headline: compareB.headline,
            type: compareB.type,
          }}
          onClose={() => setCompareB(null)}
        />
      )}

      {/* Summary text */}
      {outputs.summary_text && (
        <Panel index="01" title="一句话总结">
          <pre style={preTextStyle}>{outputs.summary_text}</pre>
        </Panel>
      )}

      {/* Per-pipeline structured outputs */}
      {structuredEntries.length > 0 && (
        <Panel index="02" title="数字结果（pipeline 输出）">
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {structuredEntries.map(([key, val]) => (
              <StructuredBlock key={key} sectionKey={key} payload={val} />
            ))}
          </div>
        </Panel>
      )}

      {/* Assumptions */}
      {assumptionEntries.length > 0 && (
        <Panel index="03" title="假设参数">
          <KvGrid entries={assumptionEntries} />
        </Panel>
      )}

      {/* Warnings */}
      {(outputs.warnings && outputs.warnings.length > 0) ||
      (compute_version?.formula_warnings && compute_version.formula_warnings.length > 0) ? (
        <Panel index="04" title="警告 / 简化说明" tone="warning">
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {(outputs.warnings ?? []).map((w, i) => (
              <li key={`o-${i}`} style={warningLi}>
                {w}
              </li>
            ))}
            {(compute_version?.formula_warnings ?? []).map((w, i) => (
              <li key={`f-${i}`} style={warningLi}>
                {w}
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}

      {/* Raw input summary */}
      {inputEntries.length > 0 && (
        <Panel
          index="05"
          title={`原始数据 · ${inputs.data_source ?? '?'}`}
          subtitle={
            inputs.data_fetched_at
              ? `抓取于 ${new Date(inputs.data_fetched_at).toLocaleString('zh-CN')}`
              : undefined
          }
          collapsible
        >
          <RawDataPreview data={inputs.raw_data ?? {}} />
        </Panel>
      )}

      {/* Open the workspace view of this ticker again */}
      <div
        style={{
          marginTop: 32,
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 16,
        }}
      >
        <Link
          to={`/stocks/${symbol}`}
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            color: 'var(--primary)',
            textDecoration: 'none',
          }}
        >
          ← 回 {symbol} 工作区
        </Link>
        <button
          type="button"
          onClick={() => navigate(-1)}
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            color: 'var(--text-muted)',
            background: 'transparent',
            border: '1px solid var(--border-soft)',
            borderRadius: 8,
            padding: '6px 12px',
            cursor: 'pointer',
          }}
        >
          上一页
        </button>
      </div>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────

function BackNav({ ticker }: { ticker: string }): React.ReactElement {
  return (
    <nav
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        color: 'var(--text-muted)',
        letterSpacing: '0.08em',
        textTransform: 'uppercase',
        marginBottom: 18,
      }}
    >
      <Link to="/stocks" style={{ color: 'inherit', textDecoration: 'none' }}>
        FINAGENT
      </Link>
      <span style={{ color: 'var(--text-dim)' }}>›</span>
      <Link to="/stocks" style={{ color: 'inherit', textDecoration: 'none' }}>
        Stocks
      </Link>
      <span style={{ color: 'var(--text-dim)' }}>›</span>
      <Link to={`/stocks/${ticker}`} style={{ color: 'inherit', textDecoration: 'none' }}>
        {ticker}
      </Link>
      <span style={{ color: 'var(--text-dim)' }}>›</span>
      <span style={{ color: 'var(--accent-cyan)' }}>历史研报</span>
    </nav>
  )
}

function CompareVersionPicker({
  currentId,
  currentType,
  timeline,
  onPick,
}: {
  currentId: string
  currentType: string
  timeline: ArtifactSummaryV5[]
  onPick: (a: ArtifactSummaryV5) => void
}): React.ReactElement | null {
  const [open, setOpen] = useState(false)
  // Only artifacts of the same type can diff cleanly — the differ guard
  // refuses mismatched types anyway. Hide entries that are the current one.
  const comparable = timeline.filter(
    (a) => a.id !== currentId && a.type === currentType,
  )
  if (comparable.length === 0) return null

  return (
    <div style={{ marginTop: 14, position: 'relative', display: 'inline-block' }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--primary)',
          background: 'var(--primary-soft)',
          border: '1px solid var(--border-glow)',
          borderRadius: 6,
          padding: '6px 12px',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          cursor: 'pointer',
        }}
      >
        ↹ 对比历史版本 ({comparable.length})
      </button>
      {open && (
        <div
          style={{
            position: 'absolute',
            top: 'calc(100% + 6px)',
            left: 0,
            minWidth: 280,
            maxWidth: 360,
            background: 'rgba(15,15,34,0.96)',
            backdropFilter: 'blur(16px)',
            border: '1px solid var(--border-glow)',
            borderRadius: 'var(--radius-md)',
            padding: 6,
            zIndex: 60,
            boxShadow: 'var(--shadow-lg)',
          }}
        >
          {comparable.slice(0, 10).map((a) => (
            <button
              key={a.id}
              type="button"
              onClick={() => {
                onPick(a)
                setOpen(false)
              }}
              style={{
                display: 'block',
                width: '100%',
                textAlign: 'left',
                padding: '8px 10px',
                background: 'transparent',
                border: 'none',
                color: 'var(--text-secondary)',
                fontFamily: 'var(--font-body)',
                fontSize: 12,
                cursor: 'pointer',
                borderRadius: 'var(--radius-sm)',
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'var(--primary-soft)'
                e.currentTarget.style.color = 'var(--text-primary)'
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'transparent'
                e.currentTarget.style.color = 'var(--text-secondary)'
              }}
            >
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: 10,
                  color: 'var(--text-muted)',
                  letterSpacing: '0.06em',
                  marginBottom: 2,
                }}
              >
                {new Date(a.created_at).toLocaleString('zh-CN', {
                  month: 'short',
                  day: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </div>
              <div
                style={{
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {a.headline}
              </div>
            </button>
          ))}
          {comparable.length > 10 && (
            <div
              style={{
                padding: '6px 10px',
                fontSize: 11,
                color: 'var(--text-muted)',
                borderTop: '1px solid var(--border-faint)',
              }}
            >
              … 仅显示最近 10 条
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function MetaBar({
  created,
  source,
  version,
}: {
  created?: string
  source?: string
  version?: ArtifactComputeVersion
}): React.ReactElement {
  return (
    <div
      style={{
        marginTop: 14,
        display: 'flex',
        gap: 18,
        flexWrap: 'wrap',
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        color: 'var(--text-muted)',
      }}
    >
      {created && <span>🕐 {new Date(created).toLocaleString('zh-CN')}</span>}
      {source && <span>📡 {source}</span>}
      {version?.version && <span>v{version.version}</span>}
      {version?.formula_id && <span>{version.formula_id}</span>}
      {version?.git_commit && <span>commit {version.git_commit.slice(0, 7)}</span>}
    </div>
  )
}

function Panel({
  index,
  title,
  subtitle,
  children,
  tone,
  collapsible,
}: {
  index: string
  title: string
  subtitle?: string
  children: React.ReactNode
  tone?: 'warning'
  collapsible?: boolean
}): React.ReactElement {
  return (
    <section
      className="cosmic-card"
      style={{
        marginBottom: 20,
        padding: '20px 24px',
        borderColor: tone === 'warning' ? 'rgba(217,119,6,0.32)' : undefined,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14 }}>
        <span
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 11,
            letterSpacing: 2.5,
            color: tone === 'warning' ? '#F59E0B' : 'var(--accent-cyan)',
            padding: '3px 8px',
            border: `1px solid ${tone === 'warning' ? 'rgba(217,119,6,0.4)' : 'rgba(34,211,238,0.4)'}`,
            borderRadius: 4,
          }}
        >
          {index}
        </span>
        <h2
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 16,
            letterSpacing: 2,
            color: 'var(--text-primary)',
            margin: 0,
          }}
        >
          {title}
        </h2>
        {subtitle && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--text-muted)',
              marginLeft: 'auto',
            }}
          >
            {subtitle}
          </span>
        )}
      </div>
      {collapsible ? <details><summary style={{ cursor: 'pointer', color: 'var(--text-muted)', fontSize: 12, marginBottom: 8 }}>展开</summary>{children}</details> : children}
    </section>
  )
}

function StructuredBlock({
  sectionKey,
  payload,
}: {
  sectionKey: string
  payload: unknown
}): React.ReactElement {
  const label = STRUCTURED_LABELS[sectionKey] ?? sectionKey
  if (payload === null || payload === undefined) return <></>

  if (typeof payload === 'object' && !Array.isArray(payload)) {
    const entries = Object.entries(payload as Record<string, unknown>)
    return (
      <div>
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-muted)',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            marginBottom: 8,
          }}
        >
          {label}
        </div>
        <KvGrid entries={entries} />
      </div>
    )
  }
  return (
    <pre style={preTextStyle}>{JSON.stringify(payload, null, 2)}</pre>
  )
}

function KvGrid({
  entries,
}: {
  entries: [string, unknown][]
}): React.ReactElement {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(160px, max-content) 1fr',
        gap: '6px 18px',
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
      }}
    >
      {entries.map(([k, v]) => (
        <KvRow key={k} k={k} v={v} />
      ))}
    </div>
  )
}

function KvRow({ k, v }: { k: string; v: unknown }): React.ReactElement {
  const isPrimitive =
    v === null ||
    typeof v === 'string' ||
    typeof v === 'number' ||
    typeof v === 'boolean'
  return (
    <>
      <div style={{ color: 'var(--text-muted)' }}>{k}</div>
      <div style={{ color: 'var(--text-primary)', wordBreak: 'break-word' }}>
        {isPrimitive ? (
          formatPrimitive(v)
        ) : (
          <details>
            <summary
              style={{
                cursor: 'pointer',
                color: 'var(--text-secondary)',
                fontSize: 11,
              }}
            >
              {Array.isArray(v)
                ? `array(${(v as unknown[]).length})`
                : `object(${Object.keys(v as object).length} keys)`}
            </summary>
            <pre style={{ ...preTextStyle, marginTop: 6 }}>
              {JSON.stringify(v, null, 2)}
            </pre>
          </details>
        )}
      </div>
    </>
  )
}

function RawDataPreview({ data }: { data: Record<string, unknown> }): React.ReactElement {
  const entries = Object.entries(data).slice(0, 80)
  return <KvGrid entries={entries} />
}

function Skeleton(): React.ReactElement {
  return (
    <div>
      {[200, 320, 280].map((h, i) => (
        <div
          key={i}
          style={{
            height: h,
            borderRadius: 16,
            marginBottom: 16,
            background:
              'linear-gradient(110deg, rgba(15,15,34,0.6) 25%, rgba(34,211,238,0.05) 50%, rgba(15,15,34,0.6) 75%)',
            backgroundSize: '200% 100%',
            animation: 'cosmic-shimmer 2s linear infinite',
            border: '1px solid var(--border-faint)',
          }}
        />
      ))}
    </div>
  )
}

function EmptyPanel({ title, body }: { title: string; body: string }): React.ReactElement {
  return (
    <div className="cosmic-card" style={{ padding: 40, textAlign: 'center' }}>
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 18,
          letterSpacing: 2,
          color: 'var(--text-primary)',
          marginBottom: 10,
        }}
      >
        {title}
      </div>
      <div style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--text-muted)' }}>
        {body}
      </div>
    </div>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────

const STRUCTURED_LABELS: Record<string, string> = {
  financial_modeling: '财务建模 / DCF 结果',
  peer_analysis: '同业对比',
  thesis: '研报论点',
  catalyst_analysis: '催化剂分析',
  dcf_calc: 'DCF 计算',
  ddm_calc: 'DDM 计算',
  lbo_calc: 'LBO 计算',
}

function chineseLabel(type: string): string {
  return (
    {
      equity_research: 'AI 完整研报',
      ic_memo: '投委备忘',
      earnings_analysis: '财报电话会分析',
      dcf: 'DCF 估值',
      lbo: 'LBO 估值',
      ddm: 'DDM 股息折现',
      comps: '同业对标',
      peer_research: '跨股同业研究',
    }[type] ?? type
  )
}

function formatPrimitive(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') {
    if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(2)}B`
    if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(2)}M`
    if (Math.abs(v) < 1 && Math.abs(v) > 0) return v.toFixed(4)
    return v.toLocaleString('en-US', { maximumFractionDigits: 4 })
  }
  return String(v)
}

const pagePadding: React.CSSProperties = {
  position: 'relative',
  zIndex: 1,
  maxWidth: 1280,
  margin: '0 auto',
  padding: '32px 32px 96px',
}

const preTextStyle: React.CSSProperties = {
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  fontFamily: 'var(--font-mono)',
  fontSize: 11,
  lineHeight: 1.55,
  color: 'var(--text-secondary)',
  background: 'rgba(10,10,24,0.5)',
  border: '1px solid var(--border-faint)',
  borderRadius: 8,
  padding: '10px 14px',
  margin: 0,
}

const warningLi: React.CSSProperties = {
  fontFamily: 'var(--font-body)',
  fontSize: 12,
  color: 'var(--text-secondary)',
  lineHeight: 1.55,
  marginBottom: 6,
}
