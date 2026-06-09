import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useI18n } from '../i18n'
import { MarkdownLite } from './MarkdownLite'

// A complete tool result carries the tool's `summary`. For most tools this is a
// one-liner (a DCF range, a quote), but a pipeline tool like run_equity_research
// returns its ENTIRE report markdown here (the same body the artifact page
// renders chapter-by-chapter). Past this length we collapse the summary behind a
// clamp + disclosure so a long report never floods the chat thread — the full
// text is one click away (expand) and the canonical surface is "Open report".
const SUMMARY_CLAMP_CHARS = 360

// ──────────────────────────────────────────────────────────────
// Types
// ──────────────────────────────────────────────────────────────

export type ToolCardState = 'pending' | 'running' | 'complete' | 'error'

export interface ToolResult {
  summary: string
  artifact_id?: string
  ticker?: string
}

export interface ToolCardProps {
  toolCallId: string
  toolName: string
  args: Record<string, unknown>
  result?: ToolResult
  errorText?: string
  state: ToolCardState
  onRetry?: () => void
}

// ──────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────

function argsPreview(args: Record<string, unknown>): string {
  const entries = Object.entries(args).slice(0, 3)
  return entries.map(([k, v]) => `${k}="${String(v)}"`).join(', ')
}

function StatusIcon({ state }: { state: ToolCardState }): React.ReactElement {
  switch (state) {
    case 'pending':
      return (
        <span
          className="inline-block h-3 w-3 rounded-full border border-neutral-500"
          aria-label="pending"
        />
      )
    case 'running':
      return (
        <span
          className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-neutral-500 border-t-blue-400"
          aria-label="running"
        />
      )
    case 'complete':
      return (
        <svg
          className="h-3 w-3 text-emerald-400"
          viewBox="0 0 12 12"
          fill="none"
          aria-label="complete"
        >
          <circle cx="6" cy="6" r="5" stroke="currentColor" strokeWidth="1.5" />
          <path
            d="M3.5 6.2L5.2 7.9L8.5 4.5"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )
    case 'error':
      return (
        <svg className="h-3 w-3 text-red-400" viewBox="0 0 12 12" fill="none" aria-label="error">
          <circle cx="6" cy="6" r="5" stroke="currentColor" strokeWidth="1.5" />
          <path
            d="M4 4L8 8M8 4L4 8"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      )
  }
}

// ──────────────────────────────────────────────────────────────
// ToolCard
// ──────────────────────────────────────────────────────────────

export function ToolCard({
  toolCallId,
  toolName,
  args,
  result,
  errorText,
  state,
  onRetry,
}: ToolCardProps): React.ReactElement {
  const [expanded, setExpanded] = useState(false)
  const [summaryOpen, setSummaryOpen] = useState(false)
  const { t } = useI18n()

  const summary = result?.summary ?? ''
  const summaryIsLong = summary.length > SUMMARY_CLAMP_CHARS

  // The artifact detail route is /stocks/:ticker/runs/:artifactId — there is
  // no `?artifact=` consumer anywhere (the old /stocks landing now redirects to
  // /coverage), so we can only build a live link when we know the ticker.
  // Without a ticker we hide the link rather than emit a dead one.
  const artifactHref =
    result?.artifact_id && result?.ticker
      ? `/stocks/${result.ticker.toUpperCase()}/runs/${result.artifact_id}`
      : null

  return (
    <div
      data-testid="tool-card"
      data-tool-call-id={toolCallId}
      data-state={state}
      className="my-2 rounded-md border p-3 text-sm"
      style={{ borderColor: 'var(--border)', backgroundColor: 'var(--elevated)' }}
    >
      {/* Header row */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <StatusIcon state={state} />

          <button
            onClick={() => setExpanded((v) => !v)}
            className="min-w-0 flex-1 truncate text-left font-mono text-xs"
            style={{ color: 'var(--text-secondary)' }}
            title={`${toolName}(${argsPreview(args)})`}
          >
            <span style={{ color: 'var(--text-primary)' }}>{toolName}</span>
            <span style={{ color: 'var(--text-muted)' }}>({argsPreview(args)})</span>
          </button>

          {state === 'complete' && (
            <span
              className="shrink-0 rounded px-1.5 py-0.5 text-xs"
              style={{
                backgroundColor: 'var(--positive-bg)',
                color: 'var(--positive)',
              }}
            >
              ✓ Code-Computed
            </span>
          )}
        </div>

        {artifactHref && state === 'complete' && (
          // react-router <Link>, not a raw <a>: under createBrowserRouter a bare
          // anchor does a full document navigation that reboots the SPA and
          // discards the chat panel. <Link> keeps it an in-app transition.
          <Link
            to={artifactHref}
            data-testid="artifact-link"
            className="ml-2 shrink-0 text-xs"
            style={{ color: 'var(--info)' }}
          >
            {t('toolcard.openArtifact')}
          </Link>
        )}
      </div>

      {/* Expanded args */}
      {expanded && (
        <div
          className="mt-2 rounded px-2 py-1.5 text-xs font-mono whitespace-pre-wrap"
          style={{
            backgroundColor: 'var(--surface)',
            color: 'var(--text-secondary)',
          }}
        >
          {JSON.stringify(args, null, 2)}
        </div>
      )}

      {/* Result summary. A short result (a DCF range, a quote) renders inline,
          markdown-aware. A long body — a pipeline tool returns its ENTIRE report
          markdown here — stays collapsed behind a toggle and, when opened, lives
          in a fixed-height scroll box so it never blows the chat thread open. The
          canonical full report is the "Open report" artifact page. */}
      {state === 'complete' &&
        summary &&
        (summaryIsLong ? (
          <div className="mt-2">
            <button
              type="button"
              data-testid="summary-toggle"
              onClick={() => setSummaryOpen((v) => !v)}
              aria-expanded={summaryOpen}
              className="flex cursor-pointer items-center gap-1 text-xs"
              style={{ background: 'none', border: 'none', color: 'var(--text-muted)' }}
            >
              <span>{summaryOpen ? '▴' : '▾'}</span>
              {/* Hardcoded EN (app ships English-only): the Lingui catalog is
                  frozen legacy — 960/961 ids are gettext-obsolete, and a missing
                  key would render its raw id. */}
              <span>{summaryOpen ? 'Hide result' : 'Show full result'}</span>
            </button>
            {summaryOpen && (
              <div
                data-testid="tool-summary"
                className="mt-1.5 rounded text-xs leading-relaxed"
                style={{
                  maxHeight: 320,
                  overflowY: 'auto',
                  padding: '8px 10px',
                  background: 'var(--surface)',
                  color: 'var(--text-secondary)',
                }}
              >
                <MarkdownLite text={summary} />
              </div>
            )}
          </div>
        ) : (
          <div
            data-testid="tool-summary"
            className="mt-2 text-xs leading-relaxed"
            style={{ color: 'var(--text-secondary)' }}
          >
            <MarkdownLite text={summary} />
          </div>
        ))}

      {/* Error */}
      {state === 'error' && (
        <div className="mt-2 flex items-center gap-2 text-xs" style={{ color: 'var(--negative)' }}>
          <span>{errorText ?? t('toolcard.failed')}</span>
          {onRetry && (
            <button onClick={onRetry} className="underline" style={{ color: 'var(--info)' }}>
              {t('toolcard.retry')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
