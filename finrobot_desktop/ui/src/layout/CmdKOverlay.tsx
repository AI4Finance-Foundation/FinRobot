/**
 * CmdKOverlay — global command palette wired to /api/search.
 *
 * Trigger paths:
 *   1. ⌘K / Ctrl+K  (global keydown listener)
 *   2. TopBar button dispatches `toggleCmdPalette()` via appStore
 *   3. `window.dispatchEvent(new Event("finrobot:open-cmdk"))`
 *   4. `useAppStore.getState().toggleCmdPalette()`  (programmatic)
 *
 * All four paths share the single `cmdPaletteOpen` flag in appStore.
 */

import { useEffect, useRef, useCallback, useMemo } from 'react'
import { Command } from 'cmdk'
import { useQuery } from '@tanstack/react-query'
import { useDebounce } from 'use-debounce'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAppStore } from '../stores/appStore'
import { useToastStore } from '../stores/toastStore'
import { useI18n, tSync } from '../i18n'
import { FetchHttpError } from '../utils/errorMessage'
import { BASE_URL } from '../api/client'
import { STOCK_WORKSPACE_SECTIONS } from '../views/sectionDirectory'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const MAX_QUERY_LENGTH = 200
const RECENT_SEARCHES_KEY = 'finrobot:recent-searches'
const MAX_RECENT_SEARCHES = 10
const SEARCH_DEBOUNCE_MS = 200
const SEARCH_STALE_TIME_MS = 30_000
const SEARCH_TIMEOUT_MS = 5_000

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ResultKind = 'ticker' | 'slash_command' | 'artifact'

export interface SearchResult {
  kind: ResultKind
  title: string
  subtitle: string
  action: string
  score: number
}

interface SearchResponse {
  query: string
  results: SearchResult[]
}

interface GroupedResults {
  ticker: SearchResult[]
  slash_command: SearchResult[]
  artifact: SearchResult[]
}

// ---------------------------------------------------------------------------
// Recent searches helpers (exported for tests)
// ---------------------------------------------------------------------------

export function loadRecentSearches(): string[] {
  try {
    const raw = localStorage.getItem(RECENT_SEARCHES_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter((v): v is string => typeof v === 'string')
  } catch {
    return []
  }
}

export function saveRecentSearch(query: string): void {
  try {
    const existing = loadRecentSearches().filter((q) => q !== query)
    const updated = [query, ...existing].slice(0, MAX_RECENT_SEARCHES)
    localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(updated))
  } catch {
    // localStorage unavailable — silently skip
  }
}

// ---------------------------------------------------------------------------
// Action executor (exported for tests)
// ---------------------------------------------------------------------------

type NavigateFn = ReturnType<typeof useNavigate>

export function buildActionExecutor(navigate: NavigateFn, close: () => void) {
  return function executeAction(action: string, queryText?: string): void {
    try {
      const colonIdx = action.indexOf(':')
      if (colonIdx === -1) {
        useToastStore.getState().addToast({
          type: 'error',
          title: tSync('cmdk.error.invalidAction'),
          description: action,
        })
        return
      }
      const kind = action.slice(0, colonIdx)
      const rest = action.slice(colonIdx + 1)

      if (kind === 'navigate') {
        const target = rest.startsWith('/') ? rest : `/${rest}`
        navigate(target)
        if (queryText) saveRecentSearch(queryText)
        close()
        return
      }

      if (kind === 'run') {
        // rest: "dcf:AAPL" / "ic-memo:AAPL"
        const firstColon = rest.indexOf(':')
        if (firstColon === -1) {
          useToastStore.getState().addToast({
            type: 'error',
            title: tSync('cmdk.error.tickerRequired'),
            description: `run:${rest}:??`,
          })
          return
        }
        const tool = rest.slice(0, firstColon)
        const ticker = rest.slice(firstColon + 1).toUpperCase()
        if (!ticker || ticker === '??') {
          useToastStore.getState().addToast({
            type: 'error',
            title: tSync('cmdk.error.tickerRequired'),
            description: `/${tool} ??`,
          })
          return
        }
        navigate(`/stocks/${ticker}?action=run_${tool.replace(/-/g, '_')}`)
        if (queryText) saveRecentSearch(queryText)
        close()
        return
      }

      useToastStore.getState().addToast({
        type: 'error',
        title: tSync('cmdk.error.unknownAction'),
        description: `kind=${kind}`,
      })
    } catch {
      useToastStore.getState().addToast({
        type: 'error',
        title: tSync('cmdk.error.actionFailed'),
        description: action,
      })
    }
  }
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function KindIcon({ kind }: { kind: ResultKind }) {
  const icons: Record<ResultKind, string> = {
    ticker: '📈',
    slash_command: '/',
    artifact: '📄',
  }
  return (
    <span
      className="flex h-6 w-6 shrink-0 items-center justify-center rounded text-xs"
      style={{
        backgroundColor: 'var(--surface)',
        color: 'var(--text-secondary)',
        fontFamily: kind === 'slash_command' ? 'var(--font-mono, monospace)' : undefined,
        fontWeight: kind === 'slash_command' ? 700 : undefined,
      }}
      aria-hidden="true"
    >
      {icons[kind]}
    </span>
  )
}

interface ResultItemProps {
  result: SearchResult
  onSelect: (action: string) => void
}

function ResultItem({ result, onSelect }: ResultItemProps) {
  return (
    <Command.Item
      key={result.action}
      value={`${result.kind}:${result.title}:${result.subtitle}`}
      onSelect={() => onSelect(result.action)}
      data-testid="cmdk-result-item"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
        padding: '8px 12px',
        cursor: 'pointer',
        borderRadius: '6px',
      }}
    >
      <KindIcon kind={result.kind} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div
          style={{
            fontSize: '14px',
            fontWeight: 500,
            color: 'var(--text-primary)',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {result.title}
        </div>
        {result.subtitle && (
          <div
            style={{
              fontSize: '12px',
              color: 'var(--text-muted)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {result.subtitle}
          </div>
        )}
      </div>
    </Command.Item>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function CmdKOverlay() {
  const open = useAppStore((s) => s.cmdPaletteOpen)
  const rawQuery = useAppStore((s) => s.cmdKQuery ?? '')
  const setCmdPaletteOpen = useAppStore((s) => s.setCmdPaletteOpen)
  const setCmdKQuery = useAppStore((s) => s.setCmdKQuery)
  const navigate = useNavigate()
  const location = useLocation()
  const { t } = useI18n()

  // Detect if we're on a ticker workspace — if so, surface the section
  // navigator (replaces the v5 AnchorNav sticky bar per spec §8).
  const onTickerWorkspace = useMemo(
    () => /^\/stocks\/[A-Z0-9.-]{1,12}/.test(location.pathname),
    [location.pathname],
  )

  const abortRef = useRef<AbortController | null>(null)

  // ---------------------------------------------------------------------------
  // Controlled close: also clear query
  // ---------------------------------------------------------------------------
  const handleClose = useCallback(() => {
    setCmdPaletteOpen(false)
    setCmdKQuery('')
  }, [setCmdPaletteOpen, setCmdKQuery])

  // ---------------------------------------------------------------------------
  // Trigger 1: ⌘K / Ctrl+K global keydown  +  finrobot:open-cmdk event
  // Note: App.tsx already handles ⌘K → toggleCmdPalette(). We register here
  // too so CmdKOverlay works standalone (e.g. AppShell without App.tsx).
  // Both handlers are idempotent via toggle/set.
  // ---------------------------------------------------------------------------
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        // Prevent default even when an input is focused — overlay should
        // always respond (exception paths G6, G7).
        e.preventDefault()
        e.stopPropagation()
        useAppStore.getState().toggleCmdPalette()
        // When toggling off, also clear the query
        if (useAppStore.getState().cmdPaletteOpen === false) {
          useAppStore.getState().setCmdKQuery('')
        }
        return
      }
      // Esc closes and clears
      if (e.key === 'Escape' && useAppStore.getState().cmdPaletteOpen) {
        handleClose()
      }
    }
    function onOpenEvent() {
      useAppStore.getState().setCmdPaletteOpen(true)
    }
    window.addEventListener('keydown', onKeyDown, true /* capture, beats inputs */)
    window.addEventListener('finrobot:open-cmdk', onOpenEvent)
    return () => {
      window.removeEventListener('keydown', onKeyDown, true)
      window.removeEventListener('finrobot:open-cmdk', onOpenEvent)
    }
  }, [handleClose])

  // ---------------------------------------------------------------------------
  // Query processing
  // ---------------------------------------------------------------------------
  const isTruncated = rawQuery.length > MAX_QUERY_LENGTH
  const effectiveQuery = isTruncated ? rawQuery.slice(0, MAX_QUERY_LENGTH) : rawQuery
  const trimmedQuery = effectiveQuery.trim()

  const [debouncedQuery] = useDebounce(trimmedQuery, SEARCH_DEBOUNCE_MS)

  // ---------------------------------------------------------------------------
  // Search fetch — AbortController + timeout
  // ---------------------------------------------------------------------------
  const {
    data: searchData,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery<SearchResponse>({
    queryKey: ['cmdk-search', debouncedQuery],
    queryFn: async ({ signal: querySignal }) => {
      if (abortRef.current) {
        abortRef.current.abort()
      }
      const controller = new AbortController()
      abortRef.current = controller

      const timeoutId = setTimeout(() => controller.abort(new Error('timeout')), SEARCH_TIMEOUT_MS)

      // Merge query-cancellation signal with our own controller
      let fetchSignal: AbortSignal = controller.signal
      if (typeof AbortSignal.any === 'function') {
        fetchSignal = AbortSignal.any([controller.signal, querySignal])
      }

      try {
        const resp = await fetch(
          `${BASE_URL}/api/search?q=${encodeURIComponent(debouncedQuery)}&limit=20`,
          { signal: fetchSignal },
        )
        if (!resp.ok) {
          throw new FetchHttpError(resp.status, resp.statusText)
        }
        return (await resp.json()) as SearchResponse
      } catch (err) {
        if (err instanceof Error) {
          if (
            err.message.includes('timeout') ||
            (err.name === 'AbortError' &&
              controller.signal.reason instanceof Error &&
              (controller.signal.reason as Error).message === 'timeout')
          ) {
            throw new Error(tSync('cmdk.results.timeout'))
          }
        }
        throw err
      } finally {
        clearTimeout(timeoutId)
      }
    },
    enabled: debouncedQuery.length > 0,
    staleTime: SEARCH_STALE_TIME_MS,
    retry: false,
  })

  // ---------------------------------------------------------------------------
  // Group results by kind
  // ---------------------------------------------------------------------------
  const grouped = useMemo<GroupedResults>(() => {
    const groups: GroupedResults = {
      ticker: [],
      slash_command: [],
      artifact: [],
    }
    for (const r of searchData?.results ?? []) {
      if (r.kind in groups) groups[r.kind].push(r)
    }
    return groups
  }, [searchData])

  // ---------------------------------------------------------------------------
  // Recent searches — recomputed each time overlay opens or query changes
  // ---------------------------------------------------------------------------
  const recentSearches = useMemo<string[]>(() => {
    if (trimmedQuery.length > 0) return []
    return loadRecentSearches()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trimmedQuery, open])

  // ---------------------------------------------------------------------------
  // Action execution
  // ---------------------------------------------------------------------------
  const executeAction = useMemo(
    () => buildActionExecutor(navigate, handleClose),
    [navigate, handleClose],
  )

  const handleSelectAction = useCallback(
    (action: string) => executeAction(action, trimmedQuery),
    [executeAction, trimmedQuery],
  )

  // ---------------------------------------------------------------------------
  // AI fallback
  // ---------------------------------------------------------------------------
  const handleAIFallback = useCallback(() => {
    const text = trimmedQuery
    if (!text) return
    // v5 (spec §11.1.C): /library is retired. Free-text questions land on
    // /stocks (search-first landing). The Ask AI fab in StockWorkspace picks
    // up the same query via session storage when wired in PR8.
    sessionStorage.setItem('finrobot.cmdk_ai_query', text)
    navigate('/stocks')
    saveRecentSearch(text)
    handleClose()
  }, [trimmedQuery, navigate, handleClose])

  // ---------------------------------------------------------------------------
  // Derived state
  // ---------------------------------------------------------------------------
  const hasResults =
    grouped.ticker.length > 0 ||
    grouped.slash_command.length > 0 ||
    grouped.artifact.length > 0

  const showEmpty = !isLoading && !isError && debouncedQuery.length > 0 && !hasResults

  const showRecentSearches = trimmedQuery.length === 0 && recentSearches.length > 0

  const showPlaceholder = trimmedQuery.length === 0 && recentSearches.length === 0

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <Command.Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) handleClose()
      }}
      label={t('cmdk.search.aria')}
      shouldFilter={false}
      aria-label={t('cmdk.search.aria')}
      loop
      style={
        {
          // Override default cmdk dialog styles to match design system
          '--cmdk-shadow': '0 16px 48px rgba(0,0,0,0.6)',
        } as React.CSSProperties
      }
    >
      {/* ------------------------------------------------------------------ */}
      {/* Input row                                                            */}
      {/* ------------------------------------------------------------------ */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '0 12px',
          borderBottom: '1px solid var(--border)',
          height: '48px',
        }}
      >
        <span
          style={{ color: 'var(--text-muted)', fontSize: '16px', flexShrink: 0 }}
          aria-hidden="true"
        >
          🔍
        </span>
        <Command.Input
          value={effectiveQuery}
          onValueChange={setCmdKQuery}
          placeholder={t('cmdk.placeholder')}
          style={{
            flex: 1,
            background: 'transparent',
            border: 'none',
            outline: 'none',
            fontSize: '14px',
            color: 'var(--text-primary)',
            padding: '0',
          }}
          autoFocus
          data-testid="cmdk-input"
        />
        {isLoading && (
          <span
            style={{
              fontSize: '12px',
              color: 'var(--text-muted)',
              flexShrink: 0,
            }}
            aria-live="polite"
            aria-label={t('cmdk.results.searching')}
          >
            …
          </span>
        )}
      </div>

      {/* Query truncated warning */}
      {isTruncated && (
        <div
          role="alert"
          data-testid="truncation-warning"
          style={{
            padding: '6px 12px',
            fontSize: '12px',
            color: 'var(--warning)',
            backgroundColor: 'var(--surface)',
            borderBottom: '1px solid var(--border)',
          }}
        >
          {t('cmdk.overlength', { max: MAX_QUERY_LENGTH })}
        </div>
      )}

      {/* Network error banner */}
      {isError && debouncedQuery.length > 0 && (
        <div
          role="alert"
          data-testid="search-error"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 12px',
            fontSize: '12px',
            color: 'var(--danger)',
            backgroundColor: 'var(--surface)',
            borderBottom: '1px solid var(--border)',
          }}
        >
          <span>
            {error instanceof Error &&
            (error.message === t('cmdk.results.timeout') ||
              error.message.toLowerCase().includes('timeout') ||
              error.message.includes('超时'))
              ? t('cmdk.results.timeout')
              : t('cmdk.results.networkError')}
          </span>
          <button
            onClick={() => refetch()}
            data-testid="retry-button"
            style={{
              marginLeft: '8px',
              padding: '2px 8px',
              fontSize: '12px',
              border: '1px solid var(--danger)',
              color: 'var(--danger)',
              backgroundColor: 'transparent',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            {t('common.retry')}
          </button>
        </div>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Results list                                                         */}
      {/* ------------------------------------------------------------------ */}
      <Command.List
        data-testid="cmdk-list"
        style={{ maxHeight: '440px', overflowY: 'auto' }}
        aria-label={t('cmdk.results.aria')}
      >
        {/* Section navigator — shows when on a ticker workspace and query
            is empty. Replaces the v5 AnchorNav sticky horizontal bar
            (spec §8). Clicking a row scrolls to the section. */}
        {onTickerWorkspace && trimmedQuery.length === 0 && (
          <>
            {STOCK_WORKSPACE_SECTIONS.map((group) => (
              <Command.Group
                key={`section-group:${group.label}`}
                heading={group.label}
                data-testid={`section-group-${group.label}`}
              >
                {group.items.map((it) => (
                  <Command.Item
                    key={`section:${it.id}`}
                    value={`section:${it.label}:${group.label}`}
                    onSelect={() => {
                      const el = document.getElementById(it.id)
                      if (el) {
                        el.scrollIntoView({ behavior: 'smooth', block: 'start' })
                      }
                      handleClose()
                    }}
                    data-testid="section-jump-item"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '10px',
                      padding: '8px 12px',
                      cursor: 'pointer',
                    }}
                  >
                    <span
                      aria-hidden
                      style={{
                        width: 24,
                        textAlign: 'center',
                        fontSize: 13,
                        color: 'var(--accent-cyan)',
                        fontFamily: 'var(--font-mono)',
                      }}
                    >
                      §
                    </span>
                    <span style={{ fontSize: 14, color: 'var(--text-primary)' }}>{it.label}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            ))}
          </>
        )}

        {/* Recent searches — shown when query is empty */}
        {showRecentSearches && (
          <Command.Group heading={t('cmdk.section.recent')} data-testid="recent-searches-group">
            {recentSearches.map((q) => (
              <Command.Item
                key={`recent:${q}`}
                value={`recent:${q}`}
                onSelect={() => setCmdKQuery(q)}
                data-testid="recent-search-item"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  padding: '8px 12px',
                  cursor: 'pointer',
                }}
              >
                <span
                  style={{
                    fontSize: '14px',
                    color: 'var(--text-muted)',
                    flexShrink: 0,
                    width: '24px',
                    textAlign: 'center',
                  }}
                  aria-hidden="true"
                >
                  🕐
                </span>
                <span
                  style={{
                    fontSize: '14px',
                    color: 'var(--text-secondary)',
                  }}
                >
                  {q}
                </span>
              </Command.Item>
            ))}
          </Command.Group>
        )}

        {/* Ticker results */}
        {grouped.ticker.length > 0 && (
          <Command.Group heading={t('cmdk.section.tickers')} data-testid="ticker-group">
            {grouped.ticker.map((r) => (
              <ResultItem key={`ticker:${r.action}`} result={r} onSelect={handleSelectAction} />
            ))}
          </Command.Group>
        )}

        {/* Slash command results */}
        {grouped.slash_command.length > 0 && (
          <Command.Group heading={t('cmdk.section.commands')} data-testid="slash-group">
            {grouped.slash_command.map((r) => (
              <ResultItem key={`slash:${r.action}`} result={r} onSelect={handleSelectAction} />
            ))}
          </Command.Group>
        )}

        {/* Artifact results */}
        {grouped.artifact.length > 0 && (
          <Command.Group heading={t('cmdk.section.artifacts')} data-testid="artifact-group">
            {grouped.artifact.map((r) => (
              <ResultItem key={`artifact:${r.action}`} result={r} onSelect={handleSelectAction} />
            ))}
          </Command.Group>
        )}

        {/* Empty placeholder when no query */}
        {showPlaceholder && (
          <div
            data-testid="empty-placeholder"
            style={{
              padding: '32px 16px',
              textAlign: 'center',
              fontSize: '14px',
              color: 'var(--text-muted)',
            }}
          >
            {t('cmdk.empty')}
          </div>
        )}

        {/* AI fallback — zero results with non-empty query */}
        {showEmpty && (
          <Command.Empty data-testid="ai-fallback">
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                gap: '12px',
                padding: '24px 16px',
                textAlign: 'center',
              }}
            >
              <span style={{ fontSize: '14px', color: 'var(--text-muted)' }}>
                {t('cmdk.results.nothing', { query: debouncedQuery })}
              </span>
              <button
                onClick={handleAIFallback}
                data-testid="ai-fallback-button"
                style={{
                  padding: '6px 16px',
                  fontSize: '14px',
                  fontWeight: 500,
                  backgroundColor: 'var(--info)',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer',
                }}
              >
                {t('cmdk.results.askHint')}
              </button>
            </div>
          </Command.Empty>
        )}
      </Command.List>

      {/* ------------------------------------------------------------------ */}
      {/* Footer hint                                                          */}
      {/* ------------------------------------------------------------------ */}
      <div
        data-testid="cmdk-footer"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '8px 12px',
          borderTop: '1px solid var(--border)',
          fontSize: '12px',
          color: 'var(--text-muted)',
        }}
      >
        <span>
          <kbd
            style={{
              padding: '1px 5px',
              border: '1px solid var(--border)',
              borderRadius: '3px',
              fontSize: '11px',
              backgroundColor: 'var(--surface)',
            }}
          >
            ↑↓
          </kbd>{' '}
          {t('cmdk.foot.select')}{' '}
          <kbd
            style={{
              padding: '1px 5px',
              border: '1px solid var(--border)',
              borderRadius: '3px',
              fontSize: '11px',
              backgroundColor: 'var(--surface)',
            }}
          >
            Enter
          </kbd>{' '}
          {t('cmdk.foot.confirm')}{' '}
          <kbd
            style={{
              padding: '1px 5px',
              border: '1px solid var(--border)',
              borderRadius: '3px',
              fontSize: '11px',
              backgroundColor: 'var(--surface)',
            }}
          >
            Esc
          </kbd>{' '}
          {t('cmdk.foot.close')}
        </span>
        <span style={{ opacity: 0.6 }}>{t('cmdk.foot.tipDcf')}</span>
      </div>
    </Command.Dialog>
  )
}
