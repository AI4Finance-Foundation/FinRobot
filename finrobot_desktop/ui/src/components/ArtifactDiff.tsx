/**
 * ArtifactDiff — field-level diff modal between two Artifact versions.
 *
 * Renders a table of FieldDiff items returned by GET /api/artifacts/{a}/diff/{b}.
 * Numeric changes are colour-coded (green = increase, red = decrease).
 * Nested paths can be expanded/collapsed.
 * String diffs highlight changed characters.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { fetchWithTimeout, HEAVY_API_TIMEOUT_MS } from '../api/fetch'
import { useI18n } from '../i18n'
import { formatDate } from '../utils/format'
import { FetchHttpError } from '../utils/errorMessage'

// ── Types ──────────────────────────────────────────────────────────────────

interface FieldDiff {
  path: string
  old: unknown
  new: unknown
  kind: 'added' | 'removed' | 'changed'
  abs_change: number | null
  pct_change: number | null
}

export interface ArtifactDiffProps {
  artifactA: { id: string; created_at: string; headline: string; type: string }
  artifactB: { id: string; created_at: string; headline: string; type: string }
  onClose: () => void
}

// ── Helpers ────────────────────────────────────────────────────────────────

function fmtValue(val: unknown, path: string): string {
  if (val === null || val === undefined) return '—'
  if (typeof val === 'boolean') return val ? 'true' : 'false'
  if (typeof val === 'number') {
    // Heuristics for numeric formatting by path suffix
    const p = path.toLowerCase()
    if (
      p.includes('pct') ||
      p.includes('rate') ||
      p.includes('margin') ||
      p.includes('wacc') ||
      p.includes('growth')
    ) {
      return `${(val * 100).toFixed(2)}%`
    }
    if (
      p.includes('price') ||
      p.includes('value') ||
      p.includes('equity') ||
      p.includes('ev') ||
      p.includes('revenue') ||
      p.includes('ebitda')
    ) {
      const abs = Math.abs(val)
      const sign = val < 0 ? '-' : ''
      if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`
      if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`
      if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`
      return `${sign}$${abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
    }
    // Generic number: use thousands separator
    if (Number.isInteger(val) && Math.abs(val) >= 1000) {
      return val.toLocaleString('en-US')
    }
    return val.toFixed(4).replace(/\.?0+$/, '')
  }
  if (typeof val === 'string') return val
  if (Array.isArray(val)) return `[${val.length} items]`
  if (typeof val === 'object') return `{${Object.keys(val as object).length} fields}`
  return String(val)
}

function fmtPctChange(pct: number | null): string {
  if (pct === null) return ''
  const sign = pct >= 0 ? '+' : ''
  return `${sign}${(pct * 100).toFixed(1)}%`
}

/** Truncate a long path for display, full path on hover. */
function TruncatedPath({ path }: { path: string }) {
  const MAX = 50
  if (path.length <= MAX) {
    return (
      <code
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.75rem',
          color: 'var(--text-secondary)',
        }}
      >
        {path}
      </code>
    )
  }
  const display = '…' + path.slice(-(MAX - 1))
  return (
    <code
      title={path}
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: '0.75rem',
        color: 'var(--text-secondary)',
        cursor: 'help',
      }}
    >
      {display}
    </code>
  )
}

// ── Simple string diff highlighting ───────────────────────────────────────

function StringDiff({ oldVal, newVal }: { oldVal: string; newVal: string }) {
  if (oldVal === newVal) return <span style={{ color: 'var(--text-primary)' }}>{newVal}</span>
  // For short strings, just show both; for long ones, let the table do it
  return (
    <span>
      <span style={{ color: 'var(--negative)', textDecoration: 'line-through', marginRight: 6 }}>
        {oldVal}
      </span>
      <span style={{ color: 'var(--positive)' }}>{newVal}</span>
    </span>
  )
}

// ── Row component ──────────────────────────────────────────────────────────

function DiffRow({ diff }: { diff: FieldDiff }) {
  const isNumeric = typeof diff.old === 'number' || typeof diff.new === 'number'
  const increased = diff.abs_change !== null && diff.abs_change > 0
  const decreased = diff.abs_change !== null && diff.abs_change < 0

  const changeColor = increased
    ? 'var(--positive)'
    : decreased
      ? 'var(--negative)'
      : 'var(--text-secondary)'

  const kindBadgeStyle: React.CSSProperties = {
    fontSize: '0.65rem',
    padding: '1px 5px',
    borderRadius: 3,
    fontWeight: 600,
    letterSpacing: '0.03em',
    textTransform: 'uppercase',
    backgroundColor:
      diff.kind === 'added'
        ? 'rgba(52,211,153,0.15)'
        : diff.kind === 'removed'
          ? 'rgba(248,113,113,0.15)'
          : 'rgba(96,165,250,0.15)',
    color:
      diff.kind === 'added'
        ? 'var(--positive)'
        : diff.kind === 'removed'
          ? 'var(--negative)'
          : 'var(--info)',
  }

  return (
    <tr style={{ borderBottom: '1px solid var(--border-subtle)' }}>
      <td style={{ padding: '8px 12px', verticalAlign: 'middle' }}>
        <TruncatedPath path={diff.path} />
      </td>
      <td
        style={{
          padding: '8px 12px',
          verticalAlign: 'middle',
          color: 'var(--text-muted)',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.8rem',
        }}
      >
        {diff.kind === 'added' ? '—' : fmtValue(diff.old, diff.path)}
      </td>
      <td
        style={{
          padding: '8px 12px',
          verticalAlign: 'middle',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.8rem',
        }}
      >
        {diff.kind === 'removed' ? (
          <span style={{ color: 'var(--negative)' }}>—</span>
        ) : typeof diff.old === 'string' && typeof diff.new === 'string' ? (
          <StringDiff oldVal={diff.old} newVal={diff.new as string} />
        ) : (
          <span
            style={{
              color: isNumeric
                ? increased
                  ? 'var(--positive)'
                  : decreased
                    ? 'var(--negative)'
                    : 'var(--text-primary)'
                : 'var(--text-primary)',
            }}
          >
            {fmtValue(diff.new, diff.path)}
          </span>
        )}
      </td>
      <td
        style={{
          padding: '8px 12px',
          verticalAlign: 'middle',
          textAlign: 'right',
          fontFamily: 'var(--font-mono)',
          fontSize: '0.75rem',
        }}
      >
        {diff.pct_change !== null ? (
          <span style={{ color: changeColor, fontWeight: 600 }}>
            {fmtPctChange(diff.pct_change)}
          </span>
        ) : diff.kind !== 'changed' ? (
          <span style={kindBadgeStyle}>{diff.kind}</span>
        ) : null}
      </td>
    </tr>
  )
}

// ── Section grouping ───────────────────────────────────────────────────────

function groupBySection(diffs: FieldDiff[]): Map<string, FieldDiff[]> {
  const map = new Map<string, FieldDiff[]>()
  for (const d of diffs) {
    const section = (d.path ?? '').split('.')[0] ?? 'other'
    const existing = map.get(section) ?? []
    existing.push(d)
    map.set(section, existing)
  }
  return map
}

// ── Main component ─────────────────────────────────────────────────────────

export function ArtifactDiff({ artifactA, artifactB, onClose }: ArtifactDiffProps) {
  const { locale } = useI18n()
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set())

  // Type mismatch guard
  const typeMismatch = artifactA.type !== artifactB.type

  const { data, isLoading, error } = useQuery<FieldDiff[]>({
    queryKey: ['artifact-diff', artifactA.id, artifactB.id],
    queryFn: async () => {
      const resp = await fetchWithTimeout(
        `${BASE_URL}/api/artifacts/${artifactA.id}/diff/${artifactB.id}`,
        {},
        HEAVY_API_TIMEOUT_MS,
      )
      if (!resp.ok) throw new FetchHttpError(resp.status, resp.statusText)
      return resp.json() as Promise<FieldDiff[]>
    },
    enabled: !typeMismatch,
    staleTime: 60 * 1000,
  })

  const toggleSection = (section: string) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev)
      if (next.has(section)) next.delete(section)
      else next.add(section)
      return next
    })
  }

  const fmtDate = (iso: string) => formatDate(iso, locale, 'datetime')

  const overlayStyle: React.CSSProperties = {
    position: 'fixed',
    inset: 0,
    backgroundColor: 'rgba(0,0,0,0.6)',
    zIndex: 1000,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '24px',
  }

  const dialogStyle: React.CSSProperties = {
    background: 'var(--elevated)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--r-lg)',
    boxShadow: 'var(--shadow-lg)',
    width: '100%',
    maxWidth: '860px',
    maxHeight: '80vh',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  }

  return (
    <div
      style={overlayStyle}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div style={dialogStyle} role="dialog" aria-modal="true" aria-label="研报差异">
        {/* Header */}
        <div
          style={{
            padding: '16px 20px',
            borderBottom: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: 16,
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div
              style={{
                fontSize: '0.75rem',
                color: 'var(--text-muted)',
                marginBottom: 8,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              字段级差异
            </div>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
              <div
                style={{
                  background: 'var(--surface)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--r-sm)',
                  padding: '4px 10px',
                }}
              >
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', display: 'block' }}>
                  v1（旧）
                </span>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-primary)' }}>
                  {artifactA.headline}
                </span>
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', display: 'block' }}>
                  {fmtDate(artifactA.created_at)}
                </span>
              </div>
              <svg
                width="16"
                height="16"
                viewBox="0 0 16 16"
                fill="none"
                style={{ color: 'var(--text-muted)', flexShrink: 0 }}
              >
                <path
                  d="M3 8h10M9 4l4 4-4 4"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
              <div
                style={{
                  background: 'var(--surface)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--r-sm)',
                  padding: '4px 10px',
                }}
              >
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', display: 'block' }}>
                  v2（新）
                </span>
                <span style={{ fontSize: '0.85rem', color: 'var(--text-primary)' }}>
                  {artifactB.headline}
                </span>
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', display: 'block' }}>
                  {fmtDate(artifactB.created_at)}
                </span>
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="关闭差异"
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              padding: 4,
              borderRadius: 'var(--r-sm)',
              lineHeight: 1,
            }}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
              <path
                d="M4 4l8 8M12 4l-8 8"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflow: 'auto' }}>
          {typeMismatch && (
            <div style={{ padding: 32, textAlign: 'center' }}>
              <div style={{ fontSize: '2rem', marginBottom: 12 }}>⚠</div>
              <div style={{ color: 'var(--warning)', fontWeight: 600, marginBottom: 8 }}>
                无法对比：研报类型不一致
              </div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                {artifactA.type.toUpperCase()} vs {artifactB.type.toUpperCase()} —
                仅支持同类型研报之间的对比。
              </div>
              <button
                onClick={onClose}
                style={{
                  marginTop: 16,
                  padding: '8px 20px',
                  background: 'var(--surface)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--r-md)',
                  color: 'var(--text-primary)',
                  cursor: 'pointer',
                }}
              >
                关闭
              </button>
            </div>
          )}

          {!typeMismatch && isLoading && (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
              <div style={{ marginBottom: 8 }}>正在加载差异…</div>
            </div>
          )}

          {!typeMismatch && error && (
            <div style={{ padding: 32, textAlign: 'center', color: 'var(--negative)' }}>
              加载差异失败，请确认两份记录都存在。
            </div>
          )}

          {!typeMismatch && data && data.length === 0 && (
            <div style={{ padding: 40, textAlign: 'center' }}>
              <div style={{ fontSize: '1.5rem', marginBottom: 8 }}>✓</div>
              <div style={{ color: 'var(--positive)', fontWeight: 600 }}>两份研报完全一致</div>
              <div style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginTop: 4 }}>
                假设和输出全部相同。
              </div>
            </div>
          )}

          {!typeMismatch &&
            data &&
            data.length > 0 &&
            (() => {
              const grouped = groupBySection(data)
              return (
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                  <thead>
                    <tr
                      style={{
                        background: 'var(--surface)',
                        position: 'sticky',
                        top: 0,
                        zIndex: 1,
                      }}
                    >
                      <th
                        style={{
                          padding: '8px 12px',
                          textAlign: 'left',
                          fontSize: '0.72rem',
                          color: 'var(--text-muted)',
                          fontWeight: 600,
                          textTransform: 'uppercase',
                          letterSpacing: '0.05em',
                          borderBottom: '1px solid var(--border)',
                        }}
                      >
                        字段
                      </th>
                      <th
                        style={{
                          padding: '8px 12px',
                          textAlign: 'left',
                          fontSize: '0.72rem',
                          color: 'var(--text-muted)',
                          fontWeight: 600,
                          textTransform: 'uppercase',
                          letterSpacing: '0.05em',
                          borderBottom: '1px solid var(--border)',
                        }}
                      >
                        v1 (旧)
                      </th>
                      <th
                        style={{
                          padding: '8px 12px',
                          textAlign: 'left',
                          fontSize: '0.72rem',
                          color: 'var(--text-muted)',
                          fontWeight: 600,
                          textTransform: 'uppercase',
                          letterSpacing: '0.05em',
                          borderBottom: '1px solid var(--border)',
                        }}
                      >
                        v2 (新)
                      </th>
                      <th
                        style={{
                          padding: '8px 12px',
                          textAlign: 'right',
                          fontSize: '0.72rem',
                          color: 'var(--text-muted)',
                          fontWeight: 600,
                          textTransform: 'uppercase',
                          letterSpacing: '0.05em',
                          borderBottom: '1px solid var(--border)',
                        }}
                      >
                        变化
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {Array.from(grouped.entries()).map(([section, diffs]) => {
                      const collapsed = collapsedSections.has(section)
                      return (
                        <>
                          <tr
                            key={`section-${section}`}
                            style={{ background: 'var(--surface)', cursor: 'pointer' }}
                            onClick={() => toggleSection(section)}
                          >
                            <td
                              colSpan={4}
                              style={{
                                padding: '6px 12px',
                                fontSize: '0.75rem',
                                fontWeight: 700,
                                color: 'var(--accent)',
                                textTransform: 'uppercase',
                                letterSpacing: '0.08em',
                                userSelect: 'none',
                              }}
                            >
                              <span
                                style={{
                                  marginRight: 6,
                                  display: 'inline-block',
                                  transform: collapsed ? 'rotate(-90deg)' : 'rotate(0)',
                                  transition: 'transform 0.15s',
                                }}
                              >
                                ▼
                              </span>
                              {section}{' '}
                              <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>
                                ({diffs.length})
                              </span>
                            </td>
                          </tr>
                          {!collapsed &&
                            diffs.map((diff) => <DiffRow key={diff.path} diff={diff} />)}
                        </>
                      )
                    })}
                  </tbody>
                </table>
              )
            })()}
        </div>

        {/* Footer */}
        {!typeMismatch && data && data.length > 0 && (
          <div
            style={{
              padding: '10px 20px',
              borderTop: '1px solid var(--border)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              {data.length} field{data.length !== 1 ? 's' : ''} changed
            </span>
            <button
              onClick={onClose}
              style={{
                padding: '6px 16px',
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--r-md)',
                color: 'var(--text-primary)',
                cursor: 'pointer',
                fontSize: '0.85rem',
              }}
            >
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
