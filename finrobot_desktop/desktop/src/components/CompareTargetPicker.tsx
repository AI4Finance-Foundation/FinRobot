// CompareTargetPicker — in-context entry into the /compare view (UX-010).
//
// The compare flow needs to be available from the ticker workspace/report,
// because Coverage cards now open the ticker directly. A user reading NVDA who
// wants to pull in AMD should not detour through the coverage archive. This
// picker lets them name a second ticker right where they are: it reuses the
// same /api/search endpoint the command palette calls, lets the user pick a
// matched ticker (or type a raw symbol), validates it with isValidTicker, then
// navigates to /compare?tickers=<current>,<picked>.
//
// It does NOT pre-block tickers without a DCF — ComparePage already honestly
// shows "run DCF first" for those, so the entry stays permissive and lets the
// user land there.

import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useDebounce } from 'use-debounce'
import { BASE_URL } from '../api/client'
import { FetchHttpError } from '../utils/errorMessage'
import { isValidTicker, sanitizeTickerInput } from '../utils/ticker'
import { useI18n } from '../i18n'

const SEARCH_DEBOUNCE_MS = 200
const SEARCH_STALE_TIME_MS = 30_000
const SEARCH_TIMEOUT_MS = 5_000

interface RawSearchResult {
  kind: 'ticker' | 'artifact'
  title: string
  subtitle: string
  action: string
  score: number
}

interface SearchResponse {
  query: string
  results: RawSearchResult[]
}

/** Pull the ticker symbol out of a search result's `navigate:/stocks/<TICKER>[/runs/…]`
 *  action. Both ticker- and artifact-kind results route through /stocks/<TICKER>,
 *  so the action is the authoritative symbol source (title carries extra chrome
 *  like "AAPL · DCF" for artifacts). Returns the upper-cased symbol or null. */
function tickerFromAction(action: string): string | null {
  const m = action.match(/^navigate:\/stocks\/([^/]+)/)
  if (!m) return null
  return decodeURIComponent(m[1]).toUpperCase()
}

interface CompareTargetPickerProps {
  /** The ticker already in context — becomes the first tickers= entry. */
  currentTicker: string
  onClose: () => void
}

/** A small popover anchored by the caller: an input + recent-research search
 *  list. Picking a row (or hitting Enter on a valid raw symbol) navigates to
 *  /compare?tickers=<current>,<picked>. Caller renders this conditionally and
 *  owns the trigger button + anchor positioning. */
export function CompareTargetPicker({
  currentTicker,
  onClose,
}: CompareTargetPickerProps): React.ReactElement {
  const navigate = useNavigate()
  const { t } = useI18n()
  const current = currentTicker.toUpperCase()
  const [raw, setRaw] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)

  // Sanitise to a legal ticker shape on every keystroke (same definition the
  // Coverage hero search + CmdK use), so the search query and the Enter-to-pick
  // path can never carry an illegal symbol.
  const query = sanitizeTickerInput(raw)
  const [debouncedQuery] = useDebounce(query, SEARCH_DEBOUNCE_MS)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Esc closes; an outside click closes. Keeps the popover from trapping the
  // user — there's no backdrop, it floats over the toolbar/hero row.
  useEffect(() => {
    function onKey(e: KeyboardEvent): void {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }
    function onClick(e: MouseEvent): void {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) onClose()
    }
    window.addEventListener('keydown', onKey, true)
    // Defer the outside-click listener a tick so the click that opened the
    // popover doesn't immediately close it.
    const id = window.setTimeout(() => document.addEventListener('mousedown', onClick), 0)
    return () => {
      window.removeEventListener('keydown', onKey, true)
      window.clearTimeout(id)
      document.removeEventListener('mousedown', onClick)
    }
  }, [onClose])

  const abortRef = useRef<AbortController | null>(null)
  const { data, isLoading, isError } = useQuery<SearchResponse>({
    queryKey: ['compare-picker-search', debouncedQuery],
    queryFn: async ({ signal: querySignal }) => {
      if (abortRef.current) abortRef.current.abort()
      const controller = new AbortController()
      abortRef.current = controller
      const timeoutId = setTimeout(() => controller.abort(new Error('timeout')), SEARCH_TIMEOUT_MS)
      let fetchSignal: AbortSignal = controller.signal
      if (typeof AbortSignal.any === 'function') {
        fetchSignal = AbortSignal.any([controller.signal, querySignal])
      }
      try {
        const resp = await fetch(
          `${BASE_URL}/api/search?q=${encodeURIComponent(debouncedQuery)}&limit=20`,
          { signal: fetchSignal },
        )
        if (!resp.ok) throw new FetchHttpError(resp.status, resp.statusText)
        return (await resp.json()) as SearchResponse
      } finally {
        clearTimeout(timeoutId)
      }
    },
    enabled: debouncedQuery.length > 0,
    staleTime: SEARCH_STALE_TIME_MS,
    retry: false,
  })

  // Distinct, valid candidate tickers from the search results, excluding the
  // current ticker (comparing a name to itself is meaningless). De-duped because
  // a ticker can appear as both a `ticker` hit and several `artifact` hits.
  const candidates = useMemo<string[]>(() => {
    const seen = new Set<string>()
    const out: string[] = []
    for (const r of data?.results ?? []) {
      const sym = tickerFromAction(r.action)
      if (!sym || sym === current || !isValidTicker(sym) || seen.has(sym)) continue
      seen.add(sym)
      out.push(sym)
    }
    return out
  }, [data, current])

  function pick(picked: string): void {
    const sym = picked.toUpperCase()
    // Guard the URL: never emit /compare with an illegal or self-referential
    // ticker. ComparePage handles "no DCF yet" itself, so we don't pre-block on
    // valuation availability here — only on syntactic validity.
    if (!isValidTicker(sym) || sym === current) return
    navigate(`/compare?tickers=${encodeURIComponent(`${current},${sym}`)}`)
    onClose()
  }

  // Enter on a typed-but-not-listed symbol: if the sanitised query is itself a
  // valid ticker (and not the current one), compare against it directly. Lets a
  // user who knows the symbol skip the result list entirely.
  function onInputKeyDown(e: React.KeyboardEvent<HTMLInputElement>): void {
    if (e.key !== 'Enter') return
    e.preventDefault()
    const first = candidates[0]
    if (first) {
      pick(first)
      return
    }
    if (isValidTicker(query) && query !== current) pick(query)
  }

  const rawIsValidNew = isValidTicker(query) && query !== current
  const showRawHint = query.length > 0 && candidates.length === 0 && !isLoading

  return (
    <div
      ref={boxRef}
      role="dialog"
      aria-label={t('compare.addEntry')}
      data-testid="compare-target-picker"
      style={{
        position: 'absolute',
        top: 'calc(100% + 6px)',
        right: 0,
        zIndex: 50,
        width: 280,
        background: 'var(--bg-card)',
        border: '1px solid var(--border-soft)',
        borderRadius: 'var(--radius-md)',
        boxShadow: '0 16px 48px color-mix(in srgb, var(--bg-void) 60%, transparent)',
        padding: 12,
        textAlign: 'left',
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          letterSpacing: '0.06em',
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          marginBottom: 8,
        }}
      >
        {t('compare.pickTitle', { ticker: current })}
      </div>
      <input
        ref={inputRef}
        value={raw}
        onChange={(e) => setRaw(e.target.value)}
        onKeyDown={onInputKeyDown}
        placeholder={t('compare.pickPlaceholder')}
        data-testid="compare-picker-input"
        spellCheck={false}
        autoCapitalize="characters"
        style={{
          width: '100%',
          boxSizing: 'border-box',
          background: 'var(--bg-card-deep)',
          border: '1px solid var(--border-soft)',
          borderRadius: 'var(--radius-sm)',
          padding: '8px 10px',
          color: 'var(--text-primary)',
          fontFamily: 'var(--font-mono)',
          fontSize: 12.5,
          letterSpacing: '0.04em',
          outline: 'none',
        }}
      />

      <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 2 }}>
        {isLoading && query.length > 0 && <div style={hintStyle}>{t('compare.pickSearching')}</div>}
        {isError && query.length > 0 && (
          <div style={{ ...hintStyle, color: 'var(--danger)' }}>{t('compare.pickError')}</div>
        )}
        {candidates.map((sym) => (
          <button
            key={sym}
            type="button"
            data-testid={`compare-picker-option-${sym}`}
            onClick={() => pick(sym)}
            style={optionStyle}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'var(--secondary-hover)'
              e.currentTarget.style.borderColor = 'var(--secondary)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'var(--bg-card-translucent)'
              e.currentTarget.style.borderColor = 'var(--border-faint)'
            }}
          >
            <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>{sym}</span>
            <span style={{ color: 'var(--text-dim)', fontSize: 10.5 }}>
              {current} vs {sym}
            </span>
          </button>
        ))}
        {/* No matched name, but the typed symbol is itself a legal ticker — let
            the user compare against it directly (it may simply not be studied
            yet; ComparePage will prompt to run a DCF there). */}
        {showRawHint && rawIsValidNew && (
          <button
            type="button"
            data-testid="compare-picker-raw"
            onClick={() => pick(query)}
            style={optionStyle}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = 'var(--secondary-hover)'
              e.currentTarget.style.borderColor = 'var(--secondary)'
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = 'var(--bg-card-translucent)'
              e.currentTarget.style.borderColor = 'var(--border-faint)'
            }}
          >
            <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>{query}</span>
            <span style={{ color: 'var(--text-dim)', fontSize: 10.5 }}>
              {t('compare.pickUseTyped')}
            </span>
          </button>
        )}
        {showRawHint && !rawIsValidNew && (
          <div style={hintStyle}>
            {query === current ? t('compare.pickSameTicker') : t('compare.pickNoMatch')}
          </div>
        )}
      </div>
    </div>
  )
}

const hintStyle: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 10.5,
  color: 'var(--text-dim)',
  padding: '6px 4px',
  letterSpacing: '0.04em',
}

const optionStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: 10,
  width: '100%',
  padding: '8px 10px',
  background: 'var(--bg-card-translucent)',
  border: '1px solid var(--border-faint)',
  borderRadius: 'var(--radius-sm)',
  cursor: 'pointer',
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
  textAlign: 'left',
  transition: 'all 0.16s',
}
