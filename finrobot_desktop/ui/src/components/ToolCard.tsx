import { useState } from 'react'
import { useI18n } from '../i18n'

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
        <svg
          className="h-3 w-3 text-red-400"
          viewBox="0 0 12 12"
          fill="none"
          aria-label="error"
        >
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
  const { t } = useI18n()

  // v5 (spec §11.1.C): /library route retired. Artifact links point at the
  // ticker workspace (/stock/:ticker) when we know the ticker, or the
  // /stocks landing when we don't — both surface the artifact via the
  // ?artifact=… query the new "我的研究" section will consume in PR15.
  const artifactHref =
    result?.artifact_id && result?.ticker
      ? `/stocks/${result.ticker}?artifact=${result.artifact_id}`
      : result?.artifact_id
        ? `/stocks?artifact=${result.artifact_id}`
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
            <span style={{ color: 'var(--text-muted)' }}>
              ({argsPreview(args)})
            </span>
          </button>

          {state === 'complete' && (
            <span
              className="shrink-0 rounded px-1.5 py-0.5 text-xs"
              style={{
                backgroundColor: 'rgba(52,211,153,0.12)',
                color: 'var(--positive)',
              }}
            >
              ✓ Code-Computed
            </span>
          )}
        </div>

        {artifactHref && state === 'complete' && (
          <a
            href={artifactHref}
            data-testid="artifact-link"
            className="ml-2 shrink-0 text-xs"
            style={{ color: 'var(--info)' }}
          >
            {t('toolcard.openArtifact')}
          </a>
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

      {/* Result summary */}
      {state === 'complete' && result?.summary && (
        <div
          className="mt-2 whitespace-pre-wrap text-xs leading-relaxed"
          style={{ color: 'var(--text-secondary)' }}
        >
          {result.summary}
        </div>
      )}

      {/* Error */}
      {state === 'error' && (
        <div className="mt-2 flex items-center gap-2 text-xs" style={{ color: 'var(--negative)' }}>
          <span>{errorText ?? t('toolcard.failed')}</span>
          {onRetry && (
            <button
              onClick={onRetry}
              className="underline"
              style={{ color: 'var(--info)' }}
            >
              {t('toolcard.retry')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}
