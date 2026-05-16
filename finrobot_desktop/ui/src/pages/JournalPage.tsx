/**
 * JournalPage — investment decision journal with CRUD + live P&L tracking.
 *
 * Backend endpoints:
 *   POST   /api/journal              — create entry
 *   GET    /api/journal              — list all entries (enriched with live price + P&L)
 *   PUT    /api/journal/{id}         — update entry
 *   DELETE /api/journal/{id}         — delete entry
 *
 * Design: navy premium aesthetic, blue accent, timeline layout with left border dots.
 */

import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { BASE_URL } from '../api/client'

// ── Types ──────────────────────────────────────────────────────────────────────

type ActionType = 'BUY' | 'SELL' | 'HOLD'

interface JournalEntry {
  id: string
  ticker: string
  action: ActionType
  entry_price: number
  target_price: number | null
  thesis: string
  notes: string | null
  created_at: string
  current_price: number | null
  pnl_pct: number | null
  pnl_abs: number | null
}

interface CreateEntryPayload {
  ticker: string
  action: ActionType
  entry_price: number
  target_price?: number
  thesis: string
  notes?: string
}

// ── Fetch helpers ──────────────────────────────────────────────────────────────

async function fetchEntries(): Promise<JournalEntry[]> {
  const r = await fetch(`${BASE_URL}/api/journal`)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<JournalEntry[]>
}

async function createEntry(payload: CreateEntryPayload): Promise<JournalEntry> {
  const r = await fetch(`${BASE_URL}/api/journal`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<JournalEntry>
}

async function updateEntry(id: string, payload: Partial<CreateEntryPayload>): Promise<JournalEntry> {
  const r = await fetch(`${BASE_URL}/api/journal/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  return r.json() as Promise<JournalEntry>
}

async function deleteEntry(id: string): Promise<void> {
  const r = await fetch(`${BASE_URL}/api/journal/${id}`, { method: 'DELETE' })
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
}

// ── Utility helpers ────────────────────────────────────────────────────────────

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function fmtPrice(v: number): string {
  return v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtPct(v: number): string {
  const sign = v >= 0 ? '+' : ''
  return `${sign}${v.toFixed(1)}%`
}

function actionDescription(action: ActionType, ticker: string): string {
  const map: Record<ActionType, string> = {
    BUY: `买入 ${ticker}`,
    SELL: `卖出 ${ticker}`,
    HOLD: `持有 ${ticker}`,
  }
  return map[action]
}

// ── Skeleton ───────────────────────────────────────────────────────────────────

function SkeletonCard() {
  return (
    <div
      style={{
        display: 'flex',
        gap: 16,
        paddingLeft: 20,
        position: 'relative',
      }}
    >
      {/* Timeline dot placeholder */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 18,
          width: 9,
          height: 9,
          borderRadius: '50%',
          background: 'var(--border-hover)',
        }}
      />
      <div
        style={{
          flex: 1,
          background: 'var(--bg-2)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--r-sm)',
          padding: 16,
          display: 'flex',
          flexDirection: 'column',
          gap: 10,
        }}
      >
        {[80, 140, 200, 100].map((w, i) => (
          <div
            key={i}
            style={{
              width: w,
              height: i === 2 ? 32 : 14,
              borderRadius: 4,
              background: 'var(--bg-3)',
              animation: 'skeleton-pulse 1.5s ease infinite',
            }}
          />
        ))}
      </div>
    </div>
  )
}

// ── Action badge ───────────────────────────────────────────────────────────────

function ActionBadge({ action }: { action: ActionType }) {
  const styleMap: Record<ActionType, React.CSSProperties> = {
    BUY: {
      color: 'var(--positive)',
      background: 'var(--positive-bg)',
      border: '1px solid rgba(16, 185, 129, 0.25)',
    },
    SELL: {
      color: 'var(--negative)',
      background: 'var(--negative-bg)',
      border: '1px solid rgba(239, 68, 68, 0.25)',
    },
    HOLD: {
      color: 'var(--accent)',
      background: 'var(--accent-dim)',
      border: '1px solid rgba(59, 130, 246, 0.25)',
    },
  }

  return (
    <span
      style={{
        ...styleMap[action],
        fontFamily: 'var(--font-mono)',
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: '0.06em',
        padding: '2px 7px',
        borderRadius: 4,
        display: 'inline-block',
      }}
    >
      {action === 'BUY' ? '买入' : action === 'SELL' ? '卖出' : '持有'}
    </span>
  )
}

// ── New Entry Form ─────────────────────────────────────────────────────────────

interface NewEntryFormProps {
  onClose: () => void
  onSuccess: () => void
}

function NewEntryForm({ onClose, onSuccess }: NewEntryFormProps) {
  const queryClient = useQueryClient()
  const [ticker, setTicker] = useState('')
  const [action, setAction] = useState<ActionType>('BUY')
  const [entryPrice, setEntryPrice] = useState('')
  const [targetPrice, setTargetPrice] = useState('')
  const [thesis, setThesis] = useState('')
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: createEntry,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['journal-entries'] })
      onSuccess()
    },
    onError: (err: Error) => {
      setError(err.message)
    },
  })

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    const t = ticker.trim().toUpperCase()
    if (!t) { setError('Ticker is required'); return }
    if (!entryPrice || isNaN(parseFloat(entryPrice))) { setError('Entry price is required'); return }
    if (!thesis.trim()) { setError('Thesis is required'); return }

    const payload: CreateEntryPayload = {
      ticker: t,
      action,
      entry_price: parseFloat(entryPrice),
      thesis: thesis.trim(),
    }
    if (targetPrice && !isNaN(parseFloat(targetPrice))) {
      payload.target_price = parseFloat(targetPrice)
    }
    if (notes.trim()) {
      payload.notes = notes.trim()
    }

    mutation.mutate(payload)
  }

  const inputStyle: React.CSSProperties = {
    background: 'var(--bg-3)',
    border: '1px solid var(--border)',
    borderRadius: 4,
    padding: '8px 10px',
    color: 'var(--text-primary)',
    fontFamily: 'var(--font-mono)',
    fontSize: 12,
    outline: 'none',
    width: '100%',
    transition: 'border-color 0.12s',
  }

  const labelStyle: React.CSSProperties = {
    fontSize: 10,
    fontFamily: 'var(--font-mono)',
    fontWeight: 700,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.08em',
    color: 'var(--text-muted)',
    display: 'block',
    marginBottom: 5,
  }

  const toggleBtnStyle = (active: boolean, a: ActionType): React.CSSProperties => {
    const colorMap: Record<ActionType, string> = {
      BUY: 'var(--positive)',
      SELL: 'var(--negative)',
      HOLD: 'var(--accent)',
    }
    const bgMap: Record<ActionType, string> = {
      BUY: 'var(--positive-bg)',
      SELL: 'var(--negative-bg)',
      HOLD: 'var(--accent-dim)',
    }
    return {
      flex: 1,
      padding: '7px 0',
      fontFamily: 'var(--font-mono)',
      fontSize: 11,
      fontWeight: 700,
      letterSpacing: '0.06em',
      border: active ? `1px solid ${colorMap[a]}` : '1px solid var(--border)',
      borderRadius: 4,
      cursor: 'pointer',
      color: active ? colorMap[a] : 'var(--text-muted)',
      background: active ? bgMap[a] : 'var(--bg-3)',
      transition: 'all 0.12s',
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        background: 'var(--bg-2)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--r-sm)',
        padding: 20,
        display: 'flex',
        flexDirection: 'column',
        gap: 14,
      }}
    >
      {/* Row 1: Ticker + Action */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <div>
          <label style={labelStyle}>Ticker</label>
          <input
            style={inputStyle}
            placeholder="AAPL"
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            maxLength={12}
            onFocus={(e) => (e.target.style.borderColor = 'var(--accent)')}
            onBlur={(e) => (e.target.style.borderColor = 'var(--border)')}
          />
        </div>
        <div>
          <label style={labelStyle}>Action</label>
          <div style={{ display: 'flex', gap: 6 }}>
            {(['BUY', 'SELL', 'HOLD'] as ActionType[]).map((a) => (
              <button
                key={a}
                type="button"
                style={toggleBtnStyle(action === a, a)}
                onClick={() => setAction(a)}
              >
                {a === 'BUY' ? '买入' : a === 'SELL' ? '卖出' : '持有'}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Row 2: Entry Price + Target Price */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
        <div>
          <label style={labelStyle}>Entry Price ($)</label>
          <input
            style={inputStyle}
            type="number"
            step="0.01"
            min="0"
            placeholder="135.40"
            value={entryPrice}
            onChange={(e) => setEntryPrice(e.target.value)}
            onFocus={(e) => (e.target.style.borderColor = 'var(--accent)')}
            onBlur={(e) => (e.target.style.borderColor = 'var(--border)')}
          />
        </div>
        <div>
          <label style={labelStyle}>Target Price ($) <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>optional</span></label>
          <input
            style={inputStyle}
            type="number"
            step="0.01"
            min="0"
            placeholder="162.30"
            value={targetPrice}
            onChange={(e) => setTargetPrice(e.target.value)}
            onFocus={(e) => (e.target.style.borderColor = 'var(--accent)')}
            onBlur={(e) => (e.target.style.borderColor = 'var(--border)')}
          />
        </div>
      </div>

      {/* Thesis */}
      <div>
        <label style={labelStyle}>Thesis</label>
        <textarea
          style={{ ...inputStyle, minHeight: 72, resize: 'vertical', lineHeight: 1.5 }}
          placeholder="Why are you making this decision? What's your core thesis..."
          value={thesis}
          onChange={(e) => setThesis(e.target.value)}
          onFocus={(e) => (e.target.style.borderColor = 'var(--accent)')}
          onBlur={(e) => (e.target.style.borderColor = 'var(--border)')}
        />
      </div>

      {/* Notes */}
      <div>
        <label style={labelStyle}>Notes <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>optional</span></label>
        <textarea
          style={{ ...inputStyle, minHeight: 52, resize: 'vertical', lineHeight: 1.5 }}
          placeholder="Risks, catalysts, exit criteria..."
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          onFocus={(e) => (e.target.style.borderColor = 'var(--accent)')}
          onBlur={(e) => (e.target.style.borderColor = 'var(--border)')}
        />
      </div>

      {/* Error */}
      {error && (
        <div
          style={{
            fontSize: 11,
            fontFamily: 'var(--font-mono)',
            color: 'var(--negative)',
            background: 'var(--negative-bg)',
            border: '1px solid rgba(239,83,80,0.2)',
            borderRadius: 4,
            padding: '6px 10px',
          }}
        >
          {error}
        </div>
      )}

      {/* Buttons */}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button
          type="button"
          onClick={onClose}
          style={{
            padding: '7px 16px',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--text-muted)',
            background: 'transparent',
            border: '1px solid var(--border)',
            borderRadius: 4,
            cursor: 'pointer',
            transition: 'border-color 0.12s',
          }}
          onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--border-hover)')}
          onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--border)')}
        >
          取消
        </button>
        <button
          type="submit"
          disabled={mutation.isPending}
          style={{
            padding: '7px 18px',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            fontWeight: 700,
            color: '#000',
            background: mutation.isPending ? 'var(--accent-hover)' : 'var(--accent)',
            border: '1px solid transparent',
            borderRadius: 4,
            cursor: mutation.isPending ? 'not-allowed' : 'pointer',
            transition: 'background 0.12s',
            letterSpacing: '0.04em',
          }}
          onMouseEnter={(e) => {
            if (!mutation.isPending) e.currentTarget.style.background = 'var(--accent-hover)'
          }}
          onMouseLeave={(e) => {
            if (!mutation.isPending) e.currentTarget.style.background = 'var(--accent)'
          }}
        >
          {mutation.isPending ? '保存中...' : '保存'}
        </button>
      </div>
    </form>
  )
}

// ── Edit Notes Modal (inline) ──────────────────────────────────────────────────

interface EditNotesFormProps {
  entry: JournalEntry
  onClose: () => void
}

function EditNotesForm({ entry, onClose }: EditNotesFormProps) {
  const queryClient = useQueryClient()
  const [notes, setNotes] = useState(entry.notes ?? '')
  const [thesis, setThesis] = useState(entry.thesis)
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: (payload: Partial<CreateEntryPayload>) => updateEntry(entry.id, payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['journal-entries'] })
      onClose()
    },
    onError: (err: Error) => setError(err.message),
  })

  const inputStyle: React.CSSProperties = {
    background: 'var(--bg-3)',
    border: '1px solid var(--border)',
    borderRadius: 4,
    padding: '8px 10px',
    color: 'var(--text-primary)',
    fontFamily: 'var(--font-mono)',
    fontSize: 12,
    outline: 'none',
    width: '100%',
    lineHeight: 1.5,
    resize: 'vertical' as const,
    transition: 'border-color 0.12s',
  }

  const labelStyle: React.CSSProperties = {
    fontSize: 10,
    fontFamily: 'var(--font-mono)',
    fontWeight: 700,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.08em',
    color: 'var(--text-muted)',
    display: 'block',
    marginBottom: 5,
  }

  return (
    <div
      style={{
        background: 'var(--bg-3)',
        border: '1px solid var(--border-hover)',
        borderRadius: 'var(--r-sm)',
        padding: 14,
        marginTop: 10,
        display: 'flex',
        flexDirection: 'column',
        gap: 10,
      }}
    >
      <div>
        <label style={labelStyle}>Thesis</label>
        <textarea
          style={{ ...inputStyle, minHeight: 60 }}
          value={thesis}
          onChange={(e) => setThesis(e.target.value)}
          onFocus={(e) => (e.target.style.borderColor = 'var(--accent)')}
          onBlur={(e) => (e.target.style.borderColor = 'var(--border)')}
        />
      </div>
      <div>
        <label style={labelStyle}>Notes</label>
        <textarea
          style={{ ...inputStyle, minHeight: 48 }}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          onFocus={(e) => (e.target.style.borderColor = 'var(--accent)')}
          onBlur={(e) => (e.target.style.borderColor = 'var(--border)')}
        />
      </div>
      {error && (
        <div style={{ fontSize: 11, color: 'var(--negative)', fontFamily: 'var(--font-mono)' }}>
          {error}
        </div>
      )}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button
          type="button"
          onClick={onClose}
          style={{
            padding: '5px 12px',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-muted)',
            background: 'transparent',
            border: '1px solid var(--border)',
            borderRadius: 4,
            cursor: 'pointer',
          }}
        >
          取消
        </button>
        <button
          type="button"
          disabled={mutation.isPending}
          onClick={() => mutation.mutate({ thesis, notes: notes || undefined })}
          style={{
            padding: '5px 12px',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            fontWeight: 700,
            color: '#000',
            background: 'var(--accent)',
            border: '1px solid transparent',
            borderRadius: 4,
            cursor: mutation.isPending ? 'not-allowed' : 'pointer',
          }}
        >
          {mutation.isPending ? '保存中...' : '保存'}
        </button>
      </div>
    </div>
  )
}

// ── Journal Entry Card ─────────────────────────────────────────────────────────

function EntryCard({ entry }: { entry: JournalEntry }) {
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const deleteMutation = useMutation({
    mutationFn: () => deleteEntry(entry.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['journal-entries'] })
    },
  })

  const hasPnl = entry.pnl_pct !== null && entry.pnl_pct !== undefined
  const pnlPositive = hasPnl && entry.pnl_pct! >= 0

  const actionColorMap: Record<ActionType, string> = {
    BUY: 'var(--positive)',
    SELL: 'var(--negative)',
    HOLD: 'var(--accent)',
  }

  const linkStyle: React.CSSProperties = {
    fontSize: 11,
    fontFamily: 'var(--font-mono)',
    color: 'var(--text-muted)',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    padding: 0,
    textDecoration: 'none',
    transition: 'color 0.12s',
  }

  return (
    <div
      style={{
        display: 'flex',
        gap: 16,
        paddingLeft: 20,
        position: 'relative',
      }}
    >
      {/* Timeline left border */}
      <div
        style={{
          position: 'absolute',
          left: 4,
          top: 0,
          bottom: 0,
          width: 1,
          background: 'var(--border)',
        }}
      />

      {/* Timeline dot */}
      <div
        style={{
          position: 'absolute',
          left: 0,
          top: 20,
          width: 9,
          height: 9,
          borderRadius: '50%',
          border: '2px solid var(--accent)',
          background: 'var(--bg-2)',
          zIndex: 1,
        }}
      />

      {/* Card */}
      <div
        style={{
          flex: 1,
          background: 'var(--bg-2)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--r-sm)',
          padding: 16,
          transition: 'border-color 0.12s',
        }}
        onMouseEnter={(e) => {
          (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border-hover)'
        }}
        onMouseLeave={(e) => {
          (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border)'
        }}
      >
        {/* Row 1: date + ticker */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                color: 'var(--text-muted)',
              }}
            >
              {relativeTime(entry.created_at)}
            </span>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 14,
                fontWeight: 700,
                color: 'var(--accent)',
                letterSpacing: '0.04em',
              }}
            >
              {entry.ticker}
            </span>
          </div>

          {/* P&L result */}
          {hasPnl && (
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                fontWeight: 700,
                color: pnlPositive ? 'var(--positive)' : 'var(--negative)',
                background: pnlPositive ? 'var(--positive-bg)' : 'var(--negative-bg)',
                padding: '2px 8px',
                borderRadius: 4,
              }}
            >
              {fmtPct(entry.pnl_pct!)} {pnlPositive ? '✓' : ''}
            </span>
          )}
        </div>

        {/* Row 2: title */}
        <div
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--text-primary)',
            marginBottom: 8,
            fontFamily: 'var(--font-ui)',
          }}
        >
          {actionDescription(entry.action, entry.ticker)}
        </div>

        {/* Row 3: action line */}
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-secondary)',
            marginBottom: 6,
            display: 'flex',
            alignItems: 'center',
            gap: 6,
          }}
        >
          <span>Action:</span>
          <span style={{ color: actionColorMap[entry.action], fontWeight: 700 }}>
            {entry.action}
          </span>
          <span>@ ${fmtPrice(entry.entry_price)}</span>
          <ActionBadge action={entry.action} />
        </div>

        {/* Row 4: target vs current */}
        {(entry.target_price !== null || entry.current_price !== null) && (
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 11,
              color: 'var(--text-muted)',
              marginBottom: 8,
            }}
          >
            {entry.target_price !== null && (
              <span>DCF Target: ${fmtPrice(entry.target_price)}</span>
            )}
            {entry.target_price !== null && entry.current_price !== null && (
              <span style={{ margin: '0 6px', color: 'var(--border-hover)' }}>|</span>
            )}
            {entry.current_price !== null && (
              <span>Current: ${fmtPrice(entry.current_price)}</span>
            )}
          </div>
        )}

        {/* Thesis */}
        <div
          style={{
            fontSize: 12,
            color: 'var(--text-secondary)',
            lineHeight: 1.6,
            marginBottom: editing ? 0 : 10,
            fontStyle: 'italic',
          }}
        >
          {entry.thesis}
        </div>

        {/* Notes (if present and not editing) */}
        {!editing && entry.notes && (
          <div
            style={{
              fontSize: 11,
              color: 'var(--text-muted)',
              lineHeight: 1.5,
              marginBottom: 10,
              paddingLeft: 10,
              borderLeft: '2px solid var(--border-hover)',
            }}
          >
            {entry.notes}
          </div>
        )}

        {/* Inline edit form */}
        {editing && (
          <EditNotesForm entry={entry} onClose={() => setEditing(false)} />
        )}

        {/* Action links row */}
        {!editing && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginTop: 8 }}>
            <Link
              to={`/stocks/${entry.ticker}`}
              style={{ ...linkStyle, color: 'var(--accent)' }}
              onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--accent-hover)')}
              onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--accent)')}
            >
              查看报告
            </Link>

            <button
              style={linkStyle}
              onClick={() => setEditing(true)}
              onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--text-primary)')}
              onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
            >
              编辑备注
            </button>

            {!confirmDelete ? (
              <button
                style={{ ...linkStyle, marginLeft: 'auto' }}
                onClick={() => setConfirmDelete(true)}
                onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--negative)')}
                onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
              >
                删除
              </button>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 'auto' }}>
                <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                  确认？
                </span>
                <button
                  style={{ ...linkStyle, color: 'var(--negative)', fontWeight: 700 }}
                  onClick={() => deleteMutation.mutate()}
                  disabled={deleteMutation.isPending}
                >
                  {deleteMutation.isPending ? '删除中...' : '确认删除'}
                </button>
                <button
                  style={linkStyle}
                  onClick={() => setConfirmDelete(false)}
                  onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--text-primary)')}
                  onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-muted)')}
                >
                  取消
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── JournalPage ────────────────────────────────────────────────────────────────

export function JournalPage() {
  const [showForm, setShowForm] = useState(false)

  const { data, isLoading, isError } = useQuery<JournalEntry[]>({
    queryKey: ['journal-entries'],
    queryFn: fetchEntries,
    staleTime: 30_000,
    retry: 1,
  })

  return (
    <div
      style={{
        height: '100%',
        overflowY: 'auto',
        background: 'var(--bg-0)',
      }}
    >
      <div
        style={{
          maxWidth: 780,
          margin: '0 auto',
          padding: '20px 20px 48px',
          display: 'flex',
          flexDirection: 'column',
          gap: 16,
        }}
      >
        {/* ── Header ─────────────────────────────────────────────────────────── */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            paddingBottom: 4,
          }}
        >
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 16,
              fontWeight: 700,
              color: 'var(--text-primary)',
              letterSpacing: '-0.01em',
            }}
          >
            决策日记
          </span>
          <button
            onClick={() => setShowForm((v) => !v)}
            style={{
              padding: '7px 16px',
              fontFamily: 'var(--font-mono)',
              fontSize: 12,
              fontWeight: 700,
              letterSpacing: '0.04em',
              color: '#000',
              background: showForm ? 'var(--accent-hover)' : 'var(--accent)',
              border: '1px solid transparent',
              borderRadius: 4,
              cursor: 'pointer',
              transition: 'background 0.12s',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--accent-hover)')}
            onMouseLeave={(e) => (e.currentTarget.style.background = showForm ? 'var(--accent-hover)' : 'var(--accent)')}
          >
            {showForm ? '✕ 取消' : '+ 新建记录'}
          </button>
        </div>

        {/* ── New Entry Form ──────────────────────────────────────────────────── */}
        {showForm && (
          <NewEntryForm
            onClose={() => setShowForm(false)}
            onSuccess={() => setShowForm(false)}
          />
        )}

        {/* ── Loading ─────────────────────────────────────────────────────────── */}
        {isLoading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {[0, 1, 2].map((i) => <SkeletonCard key={i} />)}
          </div>
        )}

        {/* ── Error ───────────────────────────────────────────────────────────── */}
        {isError && (
          <div
            style={{
              padding: '12px 16px',
              background: 'var(--bg-2)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--r-sm)',
              fontSize: 12,
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-mono)',
            }}
          >
            无法加载决策记录 — 后端服务是否已启动？
          </div>
        )}

        {/* ── Empty state ──────────────────────────────────────────────────────── */}
        {!isLoading && !isError && data && data.length === 0 && (
          <div
            style={{
              padding: '32px 20px',
              background: 'var(--bg-2)',
              border: '1px dashed var(--border)',
              borderRadius: 'var(--r-sm)',
              textAlign: 'center',
            }}
          >
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 12,
                color: 'var(--text-muted)',
                lineHeight: 1.6,
              }}
            >
              暂无决策记录。<br />
              记录你的第一笔投资决策。
            </div>
          </div>
        )}

        {/* ── Timeline ─────────────────────────────────────────────────────────── */}
        {!isLoading && !isError && data && data.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 9,
                fontWeight: 700,
                textTransform: 'uppercase',
                letterSpacing: '0.10em',
                color: 'var(--text-muted)',
                marginBottom: -4,
              }}
            >
              {data.length} {data.length === 1 ? 'ENTRY' : 'ENTRIES'} — NEWEST FIRST
            </div>
            {data.map((entry) => (
              <EntryCard key={entry.id} entry={entry} />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
