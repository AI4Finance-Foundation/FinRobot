/**
 * LibraryPage — artifact + conversation index, ticker-first.
 *
 * Left panel (320px):
 *   - Search box
 *   - View tabs: by-ticker / by-time / workspaces
 *   - Ticker list (sorted by most recent artifact), workspace list
 *
 * Main pane:
 *   - Empty state when nothing exists
 *   - Ticker timeline: artifacts + sessions sorted newest first
 *   - Workspace detail: tickers, batch operations, per-item progress
 *
 * Right panel (slide-in):
 *   - Artifact detail (4 elements: inputs, assumptions, compute_version, outputs)
 *   - Session transcript replay
 *
 * ArtifactDiff modal: field-level diff between two same-type artifacts.
 */

import { useState, useMemo, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useDebouncedCallback } from 'use-debounce'
import { BASE_URL } from '../api/client'
import { ArtifactDiff } from '../components/ArtifactDiff'
import { useWorkspaceStore } from '../stores/workspaceStore'
import type { Workspace, BatchJobItem } from '../stores/workspaceStore'
import { useToastStore } from '../stores/toastStore'
import { useEffect, useRef } from 'react'

// ── Types ──────────────────────────────────────────────────────────────────

interface ArtifactSummary {
  id: string
  ticker: string | null
  cross_tickers: string[]
  type: string
  created_at: string
  headline: string
  source: string
  archived: boolean
}

interface ArtifactFull {
  id: string
  ticker: string | null
  cross_tickers: string[]
  type: string
  inputs: {
    data_source: string
    data_fetched_at: string
    raw_data: Record<string, unknown>
  }
  assumptions: {
    parameters: Record<string, unknown>
    user_overrides: Record<string, unknown>
  }
  compute_version: {
    package: string
    version: string
    git_commit: string | null
    formula_id: string
    formula_warnings: string[]
  }
  outputs: {
    structured: Record<string, unknown>
    summary_text: string
    warnings: string[]
  }
  meta: {
    created_at: string
    source: string
    user_id: string
    tags: string[]
    parent_artifact_id: string | null
    last_viewed_at: string | null
    archived: boolean
  }
}

interface Session {
  session_id: string
  started_at?: string
  ticker?: string
  pipeline?: string
}

type ViewMode = 'by-ticker' | 'by-time' | 'workspaces'

interface TickerEntry {
  ticker: string
  count: number
  latestAt: string
}

// ── API helpers ────────────────────────────────────────────────────────────

async function fetchArtifacts(ticker?: string, includeArchived = false): Promise<ArtifactSummary[]> {
  const params = new URLSearchParams()
  if (ticker) params.set('ticker', ticker)
  if (includeArchived) params.set('archived', 'true')
  const resp = await fetch(`${BASE_URL}/api/artifacts?${params}`)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json() as Promise<ArtifactSummary[]>
}

async function fetchArtifact(id: string): Promise<ArtifactFull> {
  const resp = await fetch(`${BASE_URL}/api/artifacts/${id}`)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  return resp.json() as Promise<ArtifactFull>
}

async function deleteArtifactApi(id: string): Promise<void> {
  const resp = await fetch(`${BASE_URL}/api/artifacts/${id}`, { method: 'DELETE' })
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
}

async function markViewed(id: string): Promise<void> {
  await fetch(`${BASE_URL}/api/artifacts/${id}/view`, { method: 'POST' })
}

async function fetchSessions(): Promise<Session[]> {
  const resp = await fetch(`${BASE_URL}/api/search/sessions`)
  if (!resp.ok) return []
  const data = await resp.json() as { sessions: Session[] }
  return data.sessions ?? []
}

async function fetchTranscript(sessionId: string): Promise<unknown[]> {
  const resp = await fetch(`${BASE_URL}/api/search/sessions/${sessionId}/transcript`)
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
  const data = await resp.json() as { events: unknown[] }
  return data.events ?? []
}

// ── Formatting ─────────────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime()
    const mins = Math.floor(diff / 60_000)
    if (mins < 1) return '刚刚'
    if (mins < 60) return `${mins}分钟前`
    const hrs = Math.floor(mins / 60)
    if (hrs < 24) return `${hrs}小时前`
    const days = Math.floor(hrs / 24)
    if (days < 7) return `${days}天前`
    return new Date(iso).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
  } catch {
    return iso
  }
}

function fmtDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString('zh-CN', { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' })
  } catch {
    return iso
  }
}

const TYPE_LABELS: Record<string, string> = {
  dcf: 'DCF',
  lbo: 'LBO',
  comps: 'Comps',
  ddm: 'DDM',
  earnings: 'Earnings',
  ic_memo: 'IC Memo',
  equity_research: 'Research',
  peer_research: 'Peers',
  ad_hoc: 'Ad Hoc',
}

const TYPE_COLORS: Record<string, string> = {
  dcf: 'var(--chart-1)',
  lbo: 'var(--chart-4)',
  comps: 'var(--chart-2)',
  earnings: 'var(--chart-3)',
  ic_memo: 'var(--chart-5)',
  equity_research: 'var(--info)',
  peer_research: 'var(--info)',
  ddm: 'var(--gold)',
  ad_hoc: 'var(--text-secondary)',
}

// ── Sub-components ─────────────────────────────────────────────────────────

function TypeBadge({ type }: { type: string }) {
  return (
    <span style={{
      fontSize: '0.65rem',
      fontWeight: 700,
      letterSpacing: '0.05em',
      padding: '2px 6px',
      borderRadius: 3,
      backgroundColor: `${TYPE_COLORS[type] ?? 'var(--text-secondary)'}22`,
      color: TYPE_COLORS[type] ?? 'var(--text-secondary)',
      textTransform: 'uppercase',
      flexShrink: 0,
    }}>
      {TYPE_LABELS[type] ?? type}
    </span>
  )
}

function EmptyState({ onNavigate }: { onNavigate: () => void }) {
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, padding: 48, textAlign: 'center' }}>
      <svg width="48" height="48" viewBox="0 0 48 48" fill="none" style={{ color: 'var(--text-muted)' }}>
        <rect x="8" y="10" width="32" height="36" rx="3" stroke="currentColor" strokeWidth="1.5" />
        <path d="M16 20h16M16 26h12M16 32h8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <circle cx="36" cy="36" r="8" fill="var(--base)" stroke="currentColor" strokeWidth="1.5" />
        <path d="M33 36h6M36 33v6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
      <div>
        <div style={{ fontSize: '1rem', fontWeight: 600, marginBottom: 6 }}>暂无分析记录</div>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', maxWidth: 320 }}>
          前往股票页面，运行 DCF、LBO 或 Comps 分析，生成第一条记录。
        </div>
      </div>
      <button
        onClick={onNavigate}
        style={{ padding: '8px 20px', background: 'var(--gold)', color: 'var(--text-primary)', border: 'none', borderRadius: 'var(--r-md)', cursor: 'pointer', fontSize: '0.9rem', fontWeight: 600 }}
      >
        前往股票
      </button>
    </div>
  )
}

// ── Delete confirm modal ───────────────────────────────────────────────────

function DeleteConfirm({ headline, onConfirm, onCancel }: { headline: string; onConfirm: () => void; onCancel: () => void }) {
  return (
    <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.6)', zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--elevated)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 24, width: 360, boxShadow: 'var(--shadow-lg)' }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>删除记录？</div>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: 4 }}>{headline}</div>
        <div style={{ fontSize: '0.8rem', color: 'var(--negative)', marginBottom: 20 }}>此操作不可撤销。</div>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onCancel} style={{ padding: '6px 16px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', color: 'var(--text-primary)', cursor: 'pointer', fontSize: '0.85rem' }}>取消</button>
          <button onClick={onConfirm} style={{ padding: '6px 16px', background: 'var(--negative)', border: 'none', borderRadius: 'var(--r-md)', color: 'var(--text-primary)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}>删除</button>
        </div>
      </div>
    </div>
  )
}

// ── Delete workspace confirm ───────────────────────────────────────────────

function DeleteWorkspaceConfirm({ name, onConfirm, onCancel }: { name: string; onConfirm: () => void; onCancel: () => void }) {
  return (
    <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.6)', zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--elevated)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 24, width: 380, boxShadow: 'var(--shadow-lg)' }}>
        <div style={{ fontWeight: 600, marginBottom: 8 }}>删除分组？</div>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: 4 }}>"{name}"</div>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: 20 }}>
          组内标的不会被删除，仅解除分组关联。
        </div>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onCancel} style={{ padding: '6px 16px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', color: 'var(--text-primary)', cursor: 'pointer', fontSize: '0.85rem' }}>取消</button>
          <button onClick={onConfirm} style={{ padding: '6px 16px', background: 'var(--negative)', border: 'none', borderRadius: 'var(--r-md)', color: 'var(--text-primary)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}>删除</button>
        </div>
      </div>
    </div>
  )
}

// ── Create/Rename workspace modal ──────────────────────────────────────────

function WorkspaceFormModal({
  initial,
  onSave,
  onCancel,
}: {
  initial?: { name: string; description?: string }
  onSave: (name: string, description?: string) => void
  onCancel: () => void
}) {
  const [name, setName] = useState(initial?.name ?? '')
  const [desc, setDesc] = useState(initial?.description ?? '')
  const [touched, setTouched] = useState(false)
  const nameError = touched && name.trim() === '' ? '请输入分组名称' : ''

  const handleSave = () => {
    setTouched(true)
    if (!name.trim()) return
    onSave(name.trim(), desc.trim() || undefined)
  }

  return (
    <div style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.6)', zIndex: 1100, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ background: 'var(--elevated)', border: '1px solid var(--border)', borderRadius: 'var(--r-lg)', padding: 24, width: 380, boxShadow: 'var(--shadow-lg)' }}>
        <div style={{ fontWeight: 600, marginBottom: 16 }}>{initial ? '重命名分组' : '新建分组'}</div>
        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>名称 *</label>
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => setTouched(true)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSave() }}
            placeholder="例如：半导体"
            style={{ width: '100%', padding: '8px 10px', background: 'var(--surface)', border: `1px solid ${nameError ? 'var(--negative)' : 'var(--border)'}`, borderRadius: 'var(--r-md)', color: 'var(--text-primary)', fontSize: '0.9rem', outline: 'none' }}
          />
          {nameError && <div style={{ fontSize: '0.75rem', color: 'var(--negative)', marginTop: 4 }}>{nameError}</div>}
        </div>
        <div style={{ marginBottom: 20 }}>
          <label style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'block', marginBottom: 4 }}>备注（可选）</label>
          <input
            value={desc}
            onChange={(e) => setDesc(e.target.value)}
            placeholder="例如：高确信度多头"
            style={{ width: '100%', padding: '8px 10px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', color: 'var(--text-primary)', fontSize: '0.9rem', outline: 'none' }}
          />
        </div>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button onClick={onCancel} style={{ padding: '6px 16px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', color: 'var(--text-primary)', cursor: 'pointer', fontSize: '0.85rem' }}>取消</button>
          <button onClick={handleSave} style={{ padding: '6px 16px', background: 'var(--gold)', border: 'none', borderRadius: 'var(--r-md)', color: 'var(--text-primary)', cursor: 'pointer', fontSize: '0.85rem', fontWeight: 600 }}>
            {initial ? '重命名' : '创建'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Add to workspace dropdown ──────────────────────────────────────────────

function WorkspacePickerDropdown({
  ticker,
  onClose,
}: {
  ticker: string
  onClose: () => void
}) {
  const workspaces = useWorkspaceStore((s) => s.workspaces)
  const addTicker = useWorkspaceStore((s) => s.addTickerToWorkspace)
  const addToast = useToastStore((s) => s.addToast)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  if (workspaces.length === 0) {
    return (
      <div ref={ref} style={{ position: 'absolute', right: 0, top: '100%', zIndex: 200, background: 'var(--elevated)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', padding: 12, width: 200, boxShadow: 'var(--shadow-md)', fontSize: '0.8rem', color: 'var(--text-muted)' }}>
        暂无分组，请先在「分组」视图中创建。
      </div>
    )
  }

  return (
    <div ref={ref} style={{ position: 'absolute', right: 0, top: '100%', zIndex: 200, background: 'var(--elevated)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', overflow: 'hidden', width: 200, boxShadow: 'var(--shadow-md)' }}>
      <div style={{ padding: '6px 10px', fontSize: '0.72rem', color: 'var(--text-muted)', borderBottom: '1px solid var(--border-subtle)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>添加到分组</div>
      {workspaces.map((ws) => {
        const already = ws.tickers.includes(ticker.toUpperCase())
        return (
          <button
            key={ws.id}
            disabled={already}
            onClick={() => {
              addTicker(ws.id, ticker)
              addToast({ type: 'success', title: `${ticker} 已添加到「${ws.name}」` })
              onClose()
            }}
            style={{ display: 'block', width: '100%', textAlign: 'left', padding: '8px 10px', background: 'none', border: 'none', color: already ? 'var(--text-muted)' : 'var(--text-primary)', cursor: already ? 'default' : 'pointer', fontSize: '0.85rem' }}
          >
            {ws.name} {already && <span style={{ fontSize: '0.7rem' }}>（已添加）</span>}
          </button>
        )
      })}
    </div>
  )
}

// ── Artifact row ───────────────────────────────────────────────────────────

function ArtifactRow({
  artifact,
  onOpen,
  onDelete,
  canDiff,
  onDiff,
  ticker,
}: {
  artifact: ArtifactSummary
  onOpen: () => void
  onDelete: () => void
  canDiff: boolean
  onDiff: () => void
  ticker: string
}) {
  const [showWsPicker, setShowWsPicker] = useState(false)

  return (
    <div
      style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', borderBottom: '1px solid var(--border-subtle)', position: 'relative' }}
      data-testid="artifact-row"
    >
      <TypeBadge type={artifact.type} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{artifact.headline}</div>
        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 2 }}>{relativeTime(artifact.created_at)}</div>
      </div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexShrink: 0 }}>
        {canDiff ? (
          <button
            onClick={onDiff}
            title="与上一版本对比"
            style={{ padding: '3px 8px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', color: 'var(--info)', cursor: 'pointer', fontSize: '0.72rem' }}
          >
            对比
          </button>
        ) : (
          <button
            disabled
            title="至少需要 2 个版本才能对比"
            style={{ padding: '3px 8px', background: 'var(--surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--r-sm)', color: 'var(--text-muted)', cursor: 'default', fontSize: '0.72rem', opacity: 0.5 }}
          >
            对比
          </button>
        )}
        <button
          onClick={onOpen}
          style={{ padding: '3px 8px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', color: 'var(--text-primary)', cursor: 'pointer', fontSize: '0.72rem' }}
        >
          查看
        </button>
        <div style={{ position: 'relative' }}>
          <button
            onClick={() => setShowWsPicker((v) => !v)}
            title="添加到分组"
            style={{ padding: '3px 8px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.72rem' }}
          >
            + 分组
          </button>
          {showWsPicker && (
            <WorkspacePickerDropdown ticker={ticker} onClose={() => setShowWsPicker(false)} />
          )}
        </div>
        <button
          onClick={onDelete}
          title="删除记录"
          style={{ padding: '3px 6px', background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.8rem' }}
          aria-label="删除记录"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M3 4h8M5 4V3h4v1M5.5 6.5v4M8.5 6.5v4M3.5 4l.5 8h6l.5-8" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>
    </div>
  )
}

// ── Session row ────────────────────────────────────────────────────────────

function SessionRow({ session, onOpen }: { session: Session; onOpen: () => void }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 16px', borderBottom: '1px solid var(--border-subtle)' }} data-testid="session-row">
      <span style={{ fontSize: '0.65rem', fontWeight: 700, padding: '2px 6px', borderRadius: 3, background: 'rgba(122,130,153,0.15)', color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em', flexShrink: 0 }}>Chat</span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: '0.85rem', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {session.pipeline ? `${session.pipeline} 分析` : `会话 ${session.session_id.slice(0, 8)}`}
        </div>
        {session.started_at && (
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 2 }}>{relativeTime(session.started_at)}</div>
        )}
      </div>
      <button
        onClick={onOpen}
        style={{ padding: '3px 8px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', color: 'var(--text-primary)', cursor: 'pointer', fontSize: '0.72rem', flexShrink: 0 }}
      >
        回放
      </button>
    </div>
  )
}

// ── JsonTree: recursive expand/collapse ───────────────────────────────────

function JsonTree({ value, depth = 0 }: { value: unknown; depth?: number }) {
  const [collapsed, setCollapsed] = useState(depth > 1)

  if (value === null || value === undefined) return <span style={{ color: 'var(--text-muted)' }}>—</span>
  if (typeof value === 'boolean') return <span style={{ color: 'var(--info)' }}>{String(value)}</span>
  if (typeof value === 'number') {
    return <span style={{ color: 'var(--chart-3)' }}>{value.toLocaleString('en-US', { maximumFractionDigits: 6 })}</span>
  }
  if (typeof value === 'string') return <span style={{ color: 'var(--gold)' }}>"{value}"</span>
  if (Array.isArray(value)) {
    if (value.length === 0) return <span style={{ color: 'var(--text-muted)' }}>[]</span>
    return (
      <span>
        <button onClick={() => setCollapsed((v) => !v)} style={{ background: 'none', border: 'none', color: 'var(--info)', cursor: 'pointer', fontSize: '0.75rem', padding: 0 }}>
          {collapsed ? `[${value.length} items] ▶` : '▼'}
        </button>
        {!collapsed && (
          <div style={{ marginLeft: 16 }}>
            {value.map((item, i) => (
              <div key={i}><JsonTree value={item} depth={depth + 1} /></div>
            ))}
          </div>
        )}
      </span>
    )
  }
  if (typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    if (entries.length === 0) return <span style={{ color: 'var(--text-muted)' }}>{'{}'}</span>
    return (
      <span>
        <button onClick={() => setCollapsed((v) => !v)} style={{ background: 'none', border: 'none', color: 'var(--info)', cursor: 'pointer', fontSize: '0.75rem', padding: 0 }}>
          {collapsed ? `{${entries.length} fields} ▶` : '▼'}
        </button>
        {!collapsed && (
          <div style={{ marginLeft: 16 }}>
            {entries.map(([k, v]) => (
              <div key={k} style={{ display: 'flex', gap: 6, marginBottom: 2 }}>
                <span style={{ color: 'var(--text-secondary)', fontSize: '0.8rem', flexShrink: 0 }}>{k}:</span>
                <JsonTree value={v} depth={depth + 1} />
              </div>
            ))}
          </div>
        )}
      </span>
    )
  }
  return <span>{String(value)}</span>
}

// ── Collapsible section ────────────────────────────────────────────────────

function Section({ title, defaultOpen = false, children }: { title: string; defaultOpen?: boolean; children: React.ReactNode }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div style={{ marginBottom: 12, background: 'var(--surface)', borderRadius: 'var(--r-md)', overflow: 'hidden' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{ width: '100%', textAlign: 'left', padding: '8px 12px', background: 'none', border: 'none', borderBottom: open ? '1px solid var(--border-subtle)' : 'none', color: 'var(--text-primary)', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.8rem', fontWeight: 600 }}
      >
        <span style={{ transform: open ? 'rotate(90deg)' : 'rotate(0)', transition: 'transform 0.15s', display: 'inline-block', color: 'var(--text-muted)' }}>▶</span>
        {title}
      </button>
      {open && <div style={{ padding: 12, fontSize: '0.8rem' }}>{children}</div>}
    </div>
  )
}

// ── Artifact detail panel ──────────────────────────────────────────────────

function ArtifactDetail({
  artifactId,
  onClose,
  onNavigateToStocks,
}: {
  artifactId: string
  onClose: () => void
  onNavigateToStocks: (ticker: string) => void
}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['artifact-full', artifactId],
    queryFn: () => fetchArtifact(artifactId),
    staleTime: 60_000,
  })

  useEffect(() => {
    if (artifactId) void markViewed(artifactId)
  }, [artifactId])

  const handleExcelExport = async () => {
    if (!data?.ticker) return
    const type = ['equity_research', 'peer_research', 'earnings', 'ic_memo', 'ad_hoc'].includes(data.type)
      ? 'dcf'
      : data.type
    const resp = await fetch(`${BASE_URL}/api/export/excel/${type}/${data.ticker}`)
    if (!resp.ok) return
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${data.ticker}_${data.type}.xlsx`
    a.click()
    URL.revokeObjectURL(url)
  }

  if (isLoading) {
    return <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)' }}>加载中…</div>
  }
  if (error || !data) {
    return <div style={{ padding: 32, textAlign: 'center', color: 'var(--negative)' }}>加载失败。</div>
  }

  return (
    <div style={{ height: '100%', overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
      {/* Header */}
      <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <TypeBadge type={data.type} />
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: '0.85rem', color: 'var(--text-primary)', fontWeight: 600 }}>
            {data.ticker ?? data.cross_tickers.join(', ')}
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{fmtDate(data.meta.created_at)}</div>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: 4 }} aria-label="Close">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>

      {/* Action bar */}
      <div style={{ padding: '10px 20px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {data.ticker && (
          <button
            onClick={() => onNavigateToStocks(data.ticker!)}
            style={{ padding: '5px 12px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', color: 'var(--text-primary)', cursor: 'pointer', fontSize: '0.8rem' }}
          >
            在股票页查看
          </button>
        )}
        {(['dcf', 'lbo', 'comps'] as const).includes(data.type as 'dcf' | 'lbo' | 'comps') && data.ticker && (
          <button
            onClick={() => void handleExcelExport()}
            style={{ padding: '5px 12px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', color: 'var(--gold)', cursor: 'pointer', fontSize: '0.8rem' }}
          >
            导出 Excel
          </button>
        )}
      </div>

      {/* 4-element sections */}
      <div style={{ flex: 1, overflow: 'auto', padding: '16px 20px' }}>
        <Section title="输出结果" defaultOpen>
          {data.outputs.summary_text && (
            <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginBottom: 8 }}>{data.outputs.summary_text}</div>
          )}
          {data.outputs.warnings.length > 0 && (
            <div style={{ background: 'rgba(251,191,36,0.1)', border: '1px solid rgba(251,191,36,0.3)', borderRadius: 'var(--r-sm)', padding: 8, marginBottom: 8 }}>
              {data.outputs.warnings.map((w, i) => (
                <div key={i} style={{ fontSize: '0.78rem', color: 'var(--warning)' }}>⚠ {w}</div>
              ))}
            </div>
          )}
          <JsonTree value={data.outputs.structured} />
        </Section>

        <Section title="假设参数">
          <div style={{ marginBottom: 8 }}>
            <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>参数</div>
            <JsonTree value={data.assumptions.parameters} />
          </div>
          {Object.keys(data.assumptions.user_overrides).length > 0 && (
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>用户覆盖</div>
              <JsonTree value={data.assumptions.user_overrides} />
            </div>
          )}
        </Section>

        <Section title="数据来源">
          <div style={{ marginBottom: 6 }}>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>来源：</span>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-primary)' }}>{data.inputs.data_source}</span>
          </div>
          <div style={{ marginBottom: 8 }}>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>获取时间：</span>
            <span style={{ fontSize: '0.8rem', color: 'var(--text-primary)' }}>{fmtDate(data.inputs.data_fetched_at)}</span>
          </div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>raw_data：（大型数据已折叠）</div>
        </Section>

        <Section title="计算版本">
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.8rem' }}>
            <div><span style={{ color: 'var(--text-muted)' }}>package:</span> <span style={{ color: 'var(--text-primary)' }}>{data.compute_version.package} v{data.compute_version.version}</span></div>
            {data.compute_version.git_commit && (
              <div><span style={{ color: 'var(--text-muted)' }}>commit:</span> <span style={{ color: 'var(--text-primary)' }}>{data.compute_version.git_commit}</span></div>
            )}
            <div><span style={{ color: 'var(--text-muted)' }}>formula:</span> <span style={{ color: 'var(--gold)' }}>{data.compute_version.formula_id}</span></div>
            {data.compute_version.formula_warnings.map((w, i) => (
              <div key={i} style={{ color: 'var(--warning)', fontSize: '0.75rem' }}>⚠ {w}</div>
            ))}
          </div>
        </Section>
      </div>
    </div>
  )
}

// ── Session transcript viewer ──────────────────────────────────────────────

function SessionTranscript({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['session-transcript', sessionId],
    queryFn: () => fetchTranscript(sessionId),
    staleTime: 60_000,
  })

  return (
    <div style={{ height: '100%', overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <div style={{ fontSize: '0.85rem', fontWeight: 600 }}>会话回放</div>
          <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{sessionId.slice(0, 16)}…</div>
        </div>
        <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', padding: 4 }} aria-label="Close">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M3 3l8 8M11 3l-8 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </div>
      <div style={{ flex: 1, overflow: 'auto', padding: 16 }}>
        {isLoading && <div style={{ color: 'var(--text-muted)' }}>加载记录中…</div>}
        {error && <div style={{ color: 'var(--negative)' }}>加载失败。</div>}
        {data && data.map((event, i) => (
          <div key={i} style={{ marginBottom: 8, padding: '8px 10px', background: 'var(--surface)', borderRadius: 'var(--r-sm)', fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-secondary)', wordBreak: 'break-all' }}>
            {JSON.stringify(event, null, 2)}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Batch job runner ───────────────────────────────────────────────────────

async function runOneTicker(
  workspaceId: string,
  ticker: string,
  pipelineType: 'dcf' | 'comps',
  updateItem: (wid: string, ticker: string, update: Partial<BatchJobItem>) => void
): Promise<void> {
  updateItem(workspaceId, ticker, { status: 'running' })
  try {
    const resp = await fetch(`${BASE_URL}/api/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker, pipeline_type: pipelineType }),
    })
    if (!resp.ok) {
      // Check if ticker looks invalid (4xx means bad ticker)
      const is4xx = resp.status >= 400 && resp.status < 500
      const errMsg = is4xx ? `Invalid ticker or error ${resp.status}` : `HTTP ${resp.status}`
      updateItem(workspaceId, ticker, { status: 'error', error: errMsg })
      return
    }
    const run = await resp.json() as { id: string }
    await new Promise<void>((resolve) => {
      const es = new EventSource(`${BASE_URL}/api/runs/${run.id}/stream`)
      es.onmessage = (e: MessageEvent) => {
        try {
          const msg = JSON.parse(e.data as string) as { type?: string; status?: string }
          if (msg.type === 'complete' || msg.status === 'completed') {
            es.close(); updateItem(workspaceId, ticker, { status: 'done' }); resolve()
          } else if (msg.type === 'error' || msg.status === 'failed') {
            es.close(); updateItem(workspaceId, ticker, { status: 'error', error: 'Pipeline failed' }); resolve()
          }
        } catch { /* ignore parse errors */ }
      }
      es.onerror = () => {
        es.close()
        updateItem(workspaceId, ticker, { status: 'error', error: 'Connection lost' })
        resolve()
      }
    })
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : 'Unknown error'
    updateItem(workspaceId, ticker, { status: 'error', error: msg })
  }
}

// ── Workspace detail ───────────────────────────────────────────────────────

function WorkspaceDetail({
  workspace,
  onSelectTicker,
  onBatchRun,
}: {
  workspace: Workspace
  onSelectTicker: (ticker: string) => void
  onBatchRun: (pipelineType: 'dcf' | 'comps') => void
}) {
  const batchJob = useWorkspaceStore((s) => s.batchJobs[workspace.id])
  const removeTicker = useWorkspaceStore((s) => s.removeTickerFromWorkspace)
  const updateItem = useWorkspaceStore((s) => s.updateBatchItem)
  const clearJob = useWorkspaceStore((s) => s.clearBatchJob)

  const completedCount = batchJob?.items.filter((i) => i.status === 'done').length ?? 0
  const errorCount = batchJob?.items.filter((i) => i.status === 'error').length ?? 0
  const totalCount = batchJob?.items.length ?? 0
  const isRunning = batchJob?.items.some((i) => i.status === 'running' || i.status === 'pending')

  const handleRetry = (item: BatchJobItem) => {
    updateItem(workspace.id, item.ticker, { status: 'pending', error: undefined })
    void runOneTicker(workspace.id, item.ticker, batchJob!.pipelineType, updateItem)
  }

  return (
    <div style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: '1rem', fontWeight: 700, marginBottom: 4 }}>{workspace.name}</div>
        {workspace.description && (
          <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: 8 }}>{workspace.description}</div>
        )}
        <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)' }}>{workspace.tickers.length} 个标的</div>
      </div>

      {workspace.tickers.length > 0 && (
        <div style={{ padding: '10px 20px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
          <button
            disabled={!!isRunning}
            onClick={() => onBatchRun('dcf')}
            style={{ padding: '5px 12px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', color: isRunning ? 'var(--text-muted)' : 'var(--text-primary)', cursor: isRunning ? 'default' : 'pointer', fontSize: '0.8rem' }}
          >
            批量运行 DCF
          </button>
          <button
            disabled={!!isRunning}
            onClick={() => onBatchRun('comps')}
            style={{ padding: '5px 12px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', color: isRunning ? 'var(--text-muted)' : 'var(--text-primary)', cursor: isRunning ? 'default' : 'pointer', fontSize: '0.8rem' }}
          >
            批量运行 Comps
          </button>
          {batchJob && !isRunning && (
            <button
              onClick={() => clearJob(workspace.id)}
              style={{ padding: '5px 12px', background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.8rem' }}
            >
              清除
            </button>
          )}
          {batchJob && (
            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginLeft: 'auto' }}>
              {isRunning ? `运行中… ${completedCount}/${totalCount}` : `完成：${completedCount}/${totalCount}${errorCount > 0 ? `，${errorCount} 个错误` : ''}`}
            </span>
          )}
        </div>
      )}

      {workspace.tickers.length === 0 && (
        <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
          该分组暂无标的，可在标的列表中点击「+ 分组」添加。
        </div>
      )}

      {workspace.tickers.map((ticker) => {
        const batchItem = batchJob?.items.find((i) => i.ticker === ticker)
        return (
          <div key={ticker} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 20px', borderBottom: '1px solid var(--border-subtle)' }} data-testid="workspace-ticker-row">
            <div style={{ flex: 1 }}>
              <span
                style={{ fontWeight: 700, cursor: 'pointer', color: 'var(--text-primary)' }}
                onClick={() => onSelectTicker(ticker)}
              >
                {ticker}
              </span>
              {batchItem && (
                <span style={{
                  marginLeft: 8,
                  fontSize: '0.72rem',
                  color: batchItem.status === 'done' ? 'var(--positive)' : batchItem.status === 'error' ? 'var(--negative)' : batchItem.status === 'running' ? 'var(--info)' : 'var(--text-muted)',
                }}>
                  {batchItem.status === 'error' ? `错误：${batchItem.error ?? '失败'}` : batchItem.status === 'done' ? '完成' : batchItem.status === 'running' ? '运行中' : '等待中'}
                </span>
              )}
            </div>
            {batchItem?.status === 'error' && (
              <button
                onClick={() => handleRetry(batchItem)}
                style={{ padding: '3px 8px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-sm)', color: 'var(--warning)', cursor: 'pointer', fontSize: '0.72rem' }}
              >
                重试
              </button>
            )}
            <button
              onClick={() => removeTicker(workspace.id, ticker)}
              title={`从分组移除 ${ticker}`}
              style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', padding: 4, fontSize: '1rem' }}
              aria-label={`从分组移除 ${ticker}`}
            >
              ×
            </button>
          </div>
        )
      })}
    </div>
  )
}

// ── Main LibraryPage ───────────────────────────────────────────────────────

type RightPanelState =
  | { kind: 'none' }
  | { kind: 'artifact'; id: string }
  | { kind: 'session'; id: string }

export function LibraryPage() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const addToast = useToastStore((s) => s.addToast)

  const [viewMode, setViewMode] = useState<ViewMode>('by-ticker')
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null)
  const [selectedWorkspace, setSelectedWorkspace] = useState<string | null>(null)
  const [rightPanel, setRightPanel] = useState<RightPanelState>({ kind: 'none' })
  const [showArchived, setShowArchived] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [diffModal, setDiffModal] = useState<{ a: ArtifactSummary; b: ArtifactSummary } | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ArtifactSummary | null>(null)
  const [wsFormModal, setWsFormModal] = useState<{
    mode: 'create' | 'rename'
    id?: string
    initial?: { name: string; description?: string }
  } | null>(null)
  const [wsDeleteTarget, setWsDeleteTarget] = useState<Workspace | null>(null)

  const debounceSearch = useDebouncedCallback((val: string) => {
    setDebouncedSearch(val)
  }, 200)

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchQuery(e.target.value)
    debounceSearch(e.target.value)
  }

  // Workspace store
  const workspaces = useWorkspaceStore((s) => s.workspaces)
  const createWorkspace = useWorkspaceStore((s) => s.createWorkspace)
  const renameWorkspace = useWorkspaceStore((s) => s.renameWorkspace)
  const deleteWorkspace = useWorkspaceStore((s) => s.deleteWorkspace)
  const startBatchJob = useWorkspaceStore((s) => s.startBatchJob)
  const updateBatchItem = useWorkspaceStore((s) => s.updateBatchItem)

  // Data
  const { data: allArtifacts = [], isLoading: artifactsLoading } = useQuery({
    queryKey: ['artifacts', showArchived],
    queryFn: () => fetchArtifacts(undefined, showArchived),
    staleTime: 60_000,
  })

  const { data: sessions = [] } = useQuery({
    queryKey: ['sessions'],
    queryFn: fetchSessions,
    staleTime: 60_000,
  })

  const tickerArtifactsQuery = useQuery({
    queryKey: ['artifacts-ticker', selectedTicker, showArchived],
    queryFn: () =>
      selectedTicker ? fetchArtifacts(selectedTicker, showArchived) : Promise.resolve([] as ArtifactSummary[]),
    enabled: !!selectedTicker && viewMode !== 'workspaces',
    staleTime: 60_000,
  })

  // Delete mutation
  const deleteMut = useMutation({
    mutationFn: deleteArtifactApi,
    onSuccess: (_data, id) => {
      void qc.invalidateQueries({ queryKey: ['artifacts'] })
      void qc.invalidateQueries({ queryKey: ['artifacts-ticker'] })
      setDeleteTarget(null)
      if (rightPanel.kind === 'artifact' && rightPanel.id === id) {
        setRightPanel({ kind: 'none' })
      }
      addToast({ type: 'success', title: '记录已删除' })
    },
    onError: () => {
      addToast({ type: 'error', title: '删除失败' })
    },
  })

  // Ticker list from all artifacts
  const tickerList: TickerEntry[] = useMemo(() => {
    const map = new Map<string, { count: number; latestAt: string }>()
    for (const a of allArtifacts) {
      const t = a.ticker ?? a.cross_tickers[0] ?? ''
      if (!t) continue
      const existing = map.get(t)
      if (!existing) {
        map.set(t, { count: 1, latestAt: a.created_at })
      } else {
        existing.count += 1
        if (a.created_at > existing.latestAt) existing.latestAt = a.created_at
      }
    }
    return Array.from(map.entries())
      .map(([ticker, { count, latestAt }]) => ({ ticker, count, latestAt }))
      .sort((a, b) => b.latestAt.localeCompare(a.latestAt))
  }, [allArtifacts])

  const filteredTickerList = useMemo(() => {
    if (!debouncedSearch) return tickerList
    const q = debouncedSearch.toLowerCase()
    return tickerList.filter(
      ({ ticker }) =>
        ticker.toLowerCase().includes(q) ||
        allArtifacts.some(
          (a) => (a.ticker ?? '') === ticker && (a.type.includes(q) || a.headline.toLowerCase().includes(q))
        )
    )
  }, [tickerList, debouncedSearch, allArtifacts])

  const filteredAllArtifacts = useMemo(() => {
    if (!debouncedSearch) return allArtifacts
    const q = debouncedSearch.toLowerCase()
    return allArtifacts.filter(
      (a) =>
        (a.ticker ?? '').toLowerCase().includes(q) ||
        a.type.toLowerCase().includes(q) ||
        a.headline.toLowerCase().includes(q)
    )
  }, [allArtifacts, debouncedSearch])

  const tickerTimeline = useMemo(() => {
    if (!selectedTicker) return { artifacts: [] as ArtifactSummary[], sessions: [] as Session[] }
    const artifacts = tickerArtifactsQuery.data ?? []
    const tickerSessions = sessions.filter(
      (s) => s.ticker?.toUpperCase() === selectedTicker.toUpperCase()
    )
    return { artifacts, sessions: tickerSessions }
  }, [selectedTicker, tickerArtifactsQuery.data, sessions])

  const findPrevArtifact = useCallback(
    (artifact: ArtifactSummary): ArtifactSummary | null => {
      const pool = tickerArtifactsQuery.data ?? []
      const sameType = pool.filter((a) => a.type === artifact.type && a.id !== artifact.id)
      if (sameType.length === 0) return null
      const older = sameType.filter((a) => a.created_at < artifact.created_at)
      if (older.length > 0) return older[0]
      return sameType[sameType.length - 1]
    },
    [tickerArtifactsQuery.data]
  )

  const typeCountInTicker = useMemo(() => {
    const pool = tickerArtifactsQuery.data ?? []
    const map = new Map<string, number>()
    for (const a of pool) map.set(a.type, (map.get(a.type) ?? 0) + 1)
    return map
  }, [tickerArtifactsQuery.data])

  const handleBatchRun = useCallback(
    async (workspaceId: string, pipelineType: 'dcf' | 'comps') => {
      const ws = workspaces.find((w) => w.id === workspaceId)
      if (!ws || ws.tickers.length === 0) return
      startBatchJob(workspaceId, pipelineType)
      for (const ticker of ws.tickers) {
        await runOneTicker(workspaceId, ticker, pipelineType, updateBatchItem)
      }
      void qc.invalidateQueries({ queryKey: ['artifacts'] })
      void qc.invalidateQueries({ queryKey: ['artifacts-ticker'] })
    },
    [workspaces, startBatchJob, updateBatchItem, qc]
  )

  const VIRTUAL_THRESHOLD = 200
  const currentWorkspace = workspaces.find((w) => w.id === selectedWorkspace) ?? null
  const globalEmpty = !artifactsLoading && allArtifacts.length === 0

  return (
    <>
      <div style={{ display: 'flex', height: '100%', overflow: 'hidden', background: 'var(--base)', color: 'var(--text-primary)' }}>

        {/* Left sidebar */}
        <div style={{ width: 320, minWidth: 320, borderRight: '1px solid var(--border)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Search */}
          <div style={{ padding: '12px 14px', borderBottom: '1px solid var(--border)' }}>
            <div style={{ position: 'relative' }}>
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ position: 'absolute', left: 9, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', pointerEvents: 'none' }}>
                <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeWidth="1.2" />
                <path d="M10 10l2.5 2.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
              </svg>
              <input
                value={searchQuery}
                onChange={handleSearch}
                placeholder="搜索标的、类型、关键词…"
                aria-label="搜索记录库"
                data-testid="library-search"
                style={{ width: '100%', padding: '7px 10px 7px 30px', background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 'var(--r-md)', color: 'var(--text-primary)', fontSize: '0.82rem', outline: 'none' }}
              />
            </div>
          </div>

          {/* View tabs */}
          <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', padding: '0 4px' }}>
            {(['by-ticker', 'by-time', 'workspaces'] as ViewMode[]).map((v) => (
              <button
                key={v}
                onClick={() => { setViewMode(v); setSelectedTicker(null); setSelectedWorkspace(null) }}
                aria-pressed={viewMode === v}
                data-testid={`view-tab-${v}`}
                style={{
                  flex: 1,
                  padding: '8px 4px',
                  background: 'none',
                  border: 'none',
                  borderBottom: viewMode === v ? '2px solid var(--gold)' : '2px solid transparent',
                  color: viewMode === v ? 'var(--text-primary)' : 'var(--text-muted)',
                  cursor: 'pointer',
                  fontSize: '0.72rem',
                  fontWeight: viewMode === v ? 700 : 400,
                  letterSpacing: '0.03em',
                }}
              >
                {v === 'by-ticker' ? '按标的' : v === 'by-time' ? '按时间' : '分组'}
              </button>
            ))}
          </div>

          {/* Archive toggle */}
          <div style={{ padding: '6px 14px', borderBottom: '1px solid var(--border-subtle)', display: 'flex', alignItems: 'center', gap: 8 }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
              <input
                type="checkbox"
                checked={showArchived}
                onChange={(e) => setShowArchived(e.target.checked)}
                data-testid="archive-toggle"
                style={{ cursor: 'pointer' }}
              />
              显示已归档
            </label>
          </div>

          {/* List */}
          <div style={{ flex: 1, overflow: 'auto' }}>
            {viewMode === 'by-ticker' && (
              <>
                {filteredTickerList.length === 0 && !artifactsLoading && (
                  <div style={{ padding: 20, fontSize: '0.8rem', color: 'var(--text-muted)', textAlign: 'center' }}>
                    {debouncedSearch ? `"${debouncedSearch}" 无匹配结果，可按 cmd+K 全局搜索。` : '暂无标的。'}
                  </div>
                )}
                {filteredTickerList.map(({ ticker, count, latestAt }) => (
                  <button
                    key={ticker}
                    onClick={() => { setSelectedTicker(ticker); setRightPanel({ kind: 'none' }) }}
                    data-testid="ticker-list-item"
                    style={{
                      display: 'flex', alignItems: 'center', width: '100%', padding: '10px 14px',
                      background: selectedTicker === ticker ? 'var(--elevated)' : 'none',
                      border: 'none', borderBottom: '1px solid var(--border-subtle)',
                      cursor: 'pointer', textAlign: 'left', gap: 10,
                    }}
                  >
                    <div style={{ width: 32, height: 32, borderRadius: '50%', background: 'var(--surface)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.7rem', fontWeight: 700, color: 'var(--gold)', flexShrink: 0 }}>
                      {ticker.slice(0, 2)}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 700, fontSize: '0.88rem', color: 'var(--text-primary)' }}>{ticker}</div>
                      <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 1 }}>{count} 条记录 · {relativeTime(latestAt)}</div>
                    </div>
                    {selectedTicker === ticker && (
                      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style={{ color: 'var(--gold)', flexShrink: 0 }}>
                        <path d="M3 6l3 3 3-6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    )}
                  </button>
                ))}
              </>
            )}

            {viewMode === 'by-time' && (
              <>
                {filteredAllArtifacts.length === 0 && !artifactsLoading && (
                  <div style={{ padding: 20, fontSize: '0.8rem', color: 'var(--text-muted)', textAlign: 'center' }}>
                    {debouncedSearch ? `"${debouncedSearch}" 无匹配结果` : '暂无记录。'}
                  </div>
                )}
                {filteredAllArtifacts.slice(0, VIRTUAL_THRESHOLD).map((a) => (
                  <button
                    key={a.id}
                    onClick={() => setRightPanel({ kind: 'artifact', id: a.id })}
                    data-testid="by-time-artifact-item"
                    style={{
                      display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '8px 14px',
                      background: rightPanel.kind === 'artifact' && rightPanel.id === a.id ? 'var(--elevated)' : 'none',
                      border: 'none', borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer', textAlign: 'left',
                    }}
                  >
                    <TypeBadge type={a.type} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: '0.82rem', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{a.ticker} — {a.headline}</div>
                      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{relativeTime(a.created_at)}</div>
                    </div>
                  </button>
                ))}
                {filteredAllArtifacts.length > VIRTUAL_THRESHOLD && (
                  <div style={{ padding: '8px 14px', fontSize: '0.75rem', color: 'var(--text-muted)', textAlign: 'center' }}>
                    显示 {VIRTUAL_THRESHOLD} / {filteredAllArtifacts.length} 条，请搜索以缩小范围。
                  </div>
                )}
              </>
            )}

            {viewMode === 'workspaces' && (
              <>
                <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--border-subtle)' }}>
                  <button
                    onClick={() => setWsFormModal({ mode: 'create' })}
                    data-testid="create-workspace-btn"
                    style={{ width: '100%', padding: '7px 10px', background: 'var(--surface)', border: '1px dashed var(--border)', borderRadius: 'var(--r-md)', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center' }}
                  >
                    <span style={{ fontSize: '1rem', lineHeight: 1 }}>+</span> 新建分组
                  </button>
                </div>
                {workspaces.length === 0 && (
                  <div style={{ padding: 20, fontSize: '0.8rem', color: 'var(--text-muted)', textAlign: 'center' }}>暂无分组。</div>
                )}
                {workspaces.map((ws) => (
                  <div key={ws.id} style={{ position: 'relative' }}>
                    <button
                      onClick={() => { setSelectedWorkspace(ws.id); setSelectedTicker(null) }}
                      data-testid="workspace-list-item"
                      style={{
                        display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '10px 14px',
                        background: selectedWorkspace === ws.id ? 'var(--elevated)' : 'none',
                        border: 'none', borderBottom: '1px solid var(--border-subtle)', cursor: 'pointer', textAlign: 'left', paddingRight: 80,
                      }}
                    >
                      <span>📂</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 600, fontSize: '0.88rem', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ws.name}</div>
                        <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{ws.tickers.length} 个标的</div>
                      </div>
                    </button>
                    <div style={{ position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)', display: 'flex', gap: 4, zIndex: 1 }}>
                      <button
                        onClick={(e) => { e.stopPropagation(); setWsFormModal({ mode: 'rename', id: ws.id, initial: { name: ws.name, description: ws.description } }) }}
                        title="重命名"
                        data-testid="workspace-rename-btn"
                        style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.75rem', padding: 4 }}
                      >✎</button>
                      <button
                        onClick={(e) => { e.stopPropagation(); setWsDeleteTarget(ws) }}
                        title="删除分组"
                        data-testid="workspace-delete-btn"
                        style={{ background: 'none', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '0.75rem', padding: 4 }}
                      >×</button>
                    </div>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>

        {/* Main pane */}
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          {globalEmpty && (
            <EmptyState onNavigate={() => navigate('/stocks')} />
          )}

          {!globalEmpty && viewMode === 'workspaces' && selectedWorkspace && currentWorkspace && (
            <WorkspaceDetail
              workspace={currentWorkspace}
              onSelectTicker={(t) => { setViewMode('by-ticker'); setSelectedTicker(t) }}
              onBatchRun={(pt) => void handleBatchRun(currentWorkspace.id, pt)}
            />
          )}

          {!globalEmpty && viewMode === 'workspaces' && !selectedWorkspace && (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              请在左侧选择一个分组。
            </div>
          )}

          {!globalEmpty && viewMode === 'by-time' && (
            <div style={{ flex: 1, overflow: 'auto' }} data-testid="by-time-main">
              <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontWeight: 700 }}>全部记录</span>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>共 {filteredAllArtifacts.length} 条</span>
              </div>
              {filteredAllArtifacts.slice(0, VIRTUAL_THRESHOLD).map((a) => (
                <ArtifactRow
                  key={a.id}
                  artifact={a}
                  ticker={a.ticker ?? a.cross_tickers[0] ?? ''}
                  onOpen={() => setRightPanel({ kind: 'artifact', id: a.id })}
                  onDelete={() => setDeleteTarget(a)}
                  canDiff={false}
                  onDiff={() => {}}
                />
              ))}
              {filteredAllArtifacts.length > VIRTUAL_THRESHOLD && (
                <div style={{ padding: '8px 16px', fontSize: '0.75rem', color: 'var(--text-muted)', textAlign: 'center' }}>
                  显示 {VIRTUAL_THRESHOLD} / {filteredAllArtifacts.length} 条，请搜索以筛选。
                </div>
              )}
            </div>
          )}

          {!globalEmpty && viewMode === 'by-ticker' && !selectedTicker && (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
              请在左侧选择一个标的，查看其时间线。
            </div>
          )}

          {!globalEmpty && viewMode === 'by-ticker' && selectedTicker && (
            <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              {/* Ticker header */}
              <div style={{ padding: '14px 20px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 700, fontSize: '1rem' }}>{selectedTicker}</div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                    {tickerTimeline.artifacts.length} 条记录 · {tickerTimeline.sessions.length} 个会话
                  </div>
                </div>
                <button
                  onClick={() => navigate(`/stocks/${selectedTicker}`)}
                  style={{ padding: '6px 14px', background: 'var(--gold)', border: 'none', borderRadius: 'var(--r-md)', color: 'var(--text-primary)', cursor: 'pointer', fontSize: '0.82rem', fontWeight: 600 }}
                >
                  新建分析
                </button>
              </div>

              {/* Timeline */}
              <div style={{ flex: 1, overflow: 'auto' }} data-testid="ticker-timeline">
                {tickerArtifactsQuery.isLoading && (
                  <div style={{ padding: 20, color: 'var(--text-muted)', fontSize: '0.85rem', textAlign: 'center' }}>加载中…</div>
                )}

                {!tickerArtifactsQuery.isLoading && tickerTimeline.artifacts.length === 0 && tickerTimeline.sessions.length === 0 && (
                  <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
                    {selectedTicker} 的所有记录已被删除。
                  </div>
                )}

                {tickerTimeline.artifacts.map((a) => {
                  const canDiff = (typeCountInTicker.get(a.type) ?? 0) >= 2
                  const prev = canDiff ? findPrevArtifact(a) : null
                  return (
                    <ArtifactRow
                      key={a.id}
                      artifact={a}
                      ticker={selectedTicker}
                      onOpen={() => setRightPanel({ kind: 'artifact', id: a.id })}
                      onDelete={() => setDeleteTarget(a)}
                      canDiff={canDiff && !!prev}
                      onDiff={() => { if (prev) setDiffModal({ a: prev, b: a }) }}
                    />
                  )
                })}

                {tickerTimeline.sessions.map((s) => (
                  <SessionRow
                    key={s.session_id}
                    session={s}
                    onOpen={() => setRightPanel({ kind: 'session', id: s.session_id })}
                  />
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right detail panel */}
        {rightPanel.kind !== 'none' && (
          <div style={{ width: 380, minWidth: 380, borderLeft: '1px solid var(--border)', overflow: 'hidden', display: 'flex', flexDirection: 'column', background: 'var(--surface)' }} data-testid="right-panel">
            {rightPanel.kind === 'artifact' && (
              <ArtifactDetail
                artifactId={rightPanel.id}
                onClose={() => setRightPanel({ kind: 'none' })}
                onNavigateToStocks={(t) => navigate(`/stocks/${t}`)}
              />
            )}
            {rightPanel.kind === 'session' && (
              <SessionTranscript
                sessionId={rightPanel.id}
                onClose={() => setRightPanel({ kind: 'none' })}
              />
            )}
          </div>
        )}
      </div>

      {/* Modals */}
      {deleteTarget && (
        <DeleteConfirm
          headline={deleteTarget.headline}
          onConfirm={() => deleteMut.mutate(deleteTarget.id)}
          onCancel={() => setDeleteTarget(null)}
        />
      )}

      {wsDeleteTarget && (
        <DeleteWorkspaceConfirm
          name={wsDeleteTarget.name}
          onConfirm={() => {
            deleteWorkspace(wsDeleteTarget.id)
            setWsDeleteTarget(null)
            if (selectedWorkspace === wsDeleteTarget.id) setSelectedWorkspace(null)
          }}
          onCancel={() => setWsDeleteTarget(null)}
        />
      )}

      {wsFormModal && (
        <WorkspaceFormModal
          initial={wsFormModal.initial}
          onSave={(name, desc) => {
            if (wsFormModal.mode === 'create') {
              createWorkspace(name, desc)
            } else if (wsFormModal.id) {
              renameWorkspace(wsFormModal.id, name)
            }
            setWsFormModal(null)
          }}
          onCancel={() => setWsFormModal(null)}
        />
      )}

      {diffModal && (
        <ArtifactDiff
          artifactA={diffModal.a}
          artifactB={diffModal.b}
          onClose={() => setDiffModal(null)}
        />
      )}
    </>
  )
}
