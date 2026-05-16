/**
 * HistoryTab — artifact timeline for the current ticker.
 *
 * Shows all analysis runs for the ticker (DCF, LBO, Comps, …) in reverse
 * chronological order.  Each row has:
 *   - Type badge + created_at
 *   - "Open" button → navigates to /library/:ticker with artifact selected
 *   - "Diff" checkbox → selects two artifacts for side-by-side comparison
 *
 * Error: 404 (artifact deleted) is handled with a user-visible message.
 */

import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'
import { useToastStore } from '../stores/toastStore'

// ── Types ─────────────────────────────────────────────────────────────────────

interface ArtifactSummary {
  id: string
  ticker: string
  type: string
  created_at: string
  last_viewed_at: string | null
  is_archived: boolean
  title: string | null
}

interface FieldDiff {
  path: string
  before: unknown
  after: unknown
  abs_change?: number
  pct_change?: number
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const TYPE_COLORS: Record<string, string> = {
  dcf: 'var(--accent)',
  lbo: '#a78bfa',
  comps: '#60a5fa',
  research: '#34d399',
  earnings: '#fb923c',
  'ic-memo': '#f87171',
}

function typeColor(type: string): string {
  return TYPE_COLORS[type.toLowerCase()] ?? 'var(--text-muted)'
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return iso
  }
}

// ── Diff display ──────────────────────────────────────────────────────────────

function DiffPanel({
  aId,
  bId,
  onClose,
}: {
  aId: string
  bId: string
  onClose: () => void
}) {
  const { data, isLoading, isError } = useQuery<FieldDiff[]>({
    queryKey: ['artifact-diff', aId, bId],
    queryFn: async ({ signal }) => {
      const resp = await fetch(`${BASE_URL}/api/artifacts/${aId}/diff/${bId}`, { signal })
      if (resp.status === 404) throw new Error('One or both artifacts were deleted')
      if (!resp.ok) throw new Error(`Diff failed (${resp.status})`)
      return resp.json() as Promise<FieldDiff[]>
    },
  })

  return (
    <div
      style={{
        padding: 'var(--sp-4)',
        background: 'var(--elevated)',
        borderRadius: 'var(--r-md)',
        border: '1px solid var(--border)',
        marginTop: 'var(--sp-4)',
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          marginBottom: 'var(--sp-3)',
        }}
      >
        <span
          style={{
            fontSize: '0.78rem',
            fontWeight: 600,
            color: 'var(--text-primary)',
          }}
        >
          Artifact Diff
        </span>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-muted)',
            cursor: 'pointer',
            fontSize: '0.75rem',
          }}
        >
          Close
        </button>
      </div>

      {isLoading && (
        <div style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>
          Loading diff…
        </div>
      )}

      {isError && (
        <div style={{ color: 'var(--negative)', fontSize: '0.78rem' }}>
          Could not load diff. One or both artifacts may have been deleted.
        </div>
      )}

      {data && data.length === 0 && (
        <div style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>
          No differences found.
        </div>
      )}

      {data && data.length > 0 && (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.75rem' }}>
          <thead>
            <tr style={{ color: 'var(--text-muted)' }}>
              <th style={{ textAlign: 'left', paddingBottom: 4 }}>Field</th>
              <th style={{ textAlign: 'right', paddingBottom: 4 }}>Before</th>
              <th style={{ textAlign: 'right', paddingBottom: 4 }}>After</th>
              <th style={{ textAlign: 'right', paddingBottom: 4 }}>Δ%</th>
            </tr>
          </thead>
          <tbody>
            {data.map((d) => (
              <tr key={d.path} style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <td
                  style={{
                    padding: '4px 0',
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--text-secondary)',
                  }}
                >
                  {d.path}
                </td>
                <td
                  style={{
                    padding: '4px 0',
                    textAlign: 'right',
                    fontFamily: 'var(--font-mono)',
                  }}
                >
                  {String(d.before ?? '—')}
                </td>
                <td
                  style={{
                    padding: '4px 0',
                    textAlign: 'right',
                    fontFamily: 'var(--font-mono)',
                  }}
                >
                  {String(d.after ?? '—')}
                </td>
                <td
                  style={{
                    padding: '4px 0',
                    textAlign: 'right',
                    fontFamily: 'var(--font-mono)',
                    color:
                      d.pct_change == null
                        ? 'var(--text-muted)'
                        : d.pct_change > 0
                          ? 'var(--positive)'
                          : 'var(--negative)',
                  }}
                >
                  {d.pct_change != null
                    ? `${d.pct_change > 0 ? '+' : ''}${(d.pct_change * 100).toFixed(1)}%`
                    : '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

interface Props {
  ticker: string
}

export default function HistoryTab({ ticker }: Props) {
  const navigate = useNavigate()
  const addToast = useToastStore((s) => s.addToast)

  const { data, isLoading, isError, refetch } = useQuery<ArtifactSummary[]>({
    queryKey: ['ticker-artifacts', ticker],
    queryFn: async ({ signal }) => {
      const resp = await fetch(
        `${BASE_URL}/api/artifacts/by-ticker/${ticker}/timeline`,
        { signal },
      )
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
      return resp.json() as Promise<ArtifactSummary[]>
    },
    enabled: !!ticker,
    staleTime: 30_000,
    retry: 1,
  })

  // Diff selection: up to 2 artifact IDs
  const [diffSelection, setDiffSelection] = useState<string[]>([])
  const [showDiff, setShowDiff] = useState(false)

  const toggleDiff = useCallback(
    (id: string) => {
      setDiffSelection((prev) => {
        if (prev.includes(id)) return prev.filter((x) => x !== id)
        if (prev.length >= 2) return [prev[1], id]
        return [...prev, id]
      })
      setShowDiff(false)
    },
    [],
  )

  const handleOpen = useCallback(
    async (artifact: ArtifactSummary) => {
      // Mark as viewed
      try {
        await fetch(`${BASE_URL}/api/artifacts/${artifact.id}/view`, { method: 'POST' })
      } catch {
        // non-fatal
      }
      navigate(`/library/${artifact.ticker}`)
    },
    [navigate],
  )

  const handleRunDiff = useCallback(() => {
    if (diffSelection.length !== 2) {
      addToast({
        type: 'info',
        title: 'Select two artifacts',
        description: 'Check two artifacts to compare',
      })
      return
    }
    setShowDiff(true)
  }, [diffSelection, addToast])

  const artifacts = data ?? []

  return (
    <div className="tab-content history-tab">
      <div className="card animate-in">
        <div className="card-header">
          <span className="card-title">Analysis History — {ticker}</span>
          <div className="card-header-right">
            {diffSelection.length > 0 && (
              <button
                className="btn"
                onClick={handleRunDiff}
                disabled={diffSelection.length < 2}
                style={{ fontSize: '0.75rem', padding: '3px 10px' }}
                aria-label="Diff selected artifacts"
              >
                Diff ({diffSelection.length}/2)
              </button>
            )}
            <span className="card-badge">{artifacts.length}</span>
          </div>
        </div>

        <div className="card-body" style={{ padding: 0 }}>
          {isLoading && (
            <div
              style={{
                padding: 'var(--sp-6)',
                color: 'var(--text-muted)',
                textAlign: 'center',
                fontSize: '0.82rem',
              }}
            >
              Loading history…
            </div>
          )}

          {isError && (
            <div
              style={{
                padding: 'var(--sp-6)',
                textAlign: 'center',
                fontSize: '0.82rem',
              }}
            >
              <span style={{ color: 'var(--negative)' }}>
                Failed to load history.
              </span>{' '}
              <button
                onClick={() => void refetch()}
                style={{
                  background: 'none',
                  border: 'none',
                  color: 'var(--accent)',
                  cursor: 'pointer',
                  textDecoration: 'underline',
                  fontSize: '0.82rem',
                }}
              >
                Retry
              </button>
            </div>
          )}

          {!isLoading && !isError && artifacts.length === 0 && (
            <div
              style={{
                padding: 'var(--sp-8)',
                textAlign: 'center',
                color: 'var(--text-muted)',
                fontSize: '0.82rem',
              }}
            >
              No analysis runs for {ticker} yet.
              <br />
              Use the toolbar buttons above to run DCF, LBO, or Comps.
            </div>
          )}

          {!isLoading && artifacts.length > 0 && (
            <table className="fin-table" style={{ width: '100%' }}>
              <tbody>
                {artifacts.map((a) => {
                  const isSelected = diffSelection.includes(a.id)
                  return (
                    <tr
                      key={a.id}
                      style={{
                        background: isSelected
                          ? 'rgba(201, 168, 76, 0.06)'
                          : undefined,
                        transition: 'background 0.15s',
                      }}
                    >
                      {/* Diff checkbox */}
                      <td style={{ padding: '8px 12px', width: 32 }}>
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleDiff(a.id)}
                          aria-label={`Select ${a.type} artifact for diff`}
                          style={{ cursor: 'pointer', accentColor: 'var(--accent)' }}
                        />
                      </td>

                      {/* Type badge */}
                      <td style={{ padding: '8px 0', width: 80 }}>
                        <span
                          style={{
                            fontSize: '0.72rem',
                            fontWeight: 700,
                            fontFamily: 'var(--font-mono)',
                            color: typeColor(a.type),
                            textTransform: 'uppercase',
                          }}
                        >
                          {a.type}
                        </span>
                      </td>

                      {/* Title */}
                      <td style={{ padding: '8px 0', flex: 1 }}>
                        <span
                          style={{ fontSize: '0.78rem', color: 'var(--text-secondary)' }}
                          title={a.id}
                        >
                          {a.title ?? a.id.slice(0, 32)}
                        </span>
                      </td>

                      {/* Date */}
                      <td
                        style={{
                          padding: '8px 0',
                          fontSize: '0.72rem',
                          color: 'var(--text-muted)',
                          whiteSpace: 'nowrap',
                          width: 140,
                        }}
                      >
                        {formatDate(a.created_at)}
                      </td>

                      {/* Open button */}
                      <td style={{ padding: '8px 12px', width: 64 }}>
                        <button
                          className="btn"
                          onClick={() => void handleOpen(a)}
                          style={{ fontSize: '0.72rem', padding: '2px 8px' }}
                          aria-label={`Open ${a.type} artifact`}
                        >
                          Open
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* Diff panel */}
      {showDiff && diffSelection.length === 2 && (
        <DiffPanel
          aId={diffSelection[0]}
          bId={diffSelection[1]}
          onClose={() => {
            setShowDiff(false)
            setDiffSelection([])
          }}
        />
      )}
    </div>
  )
}
