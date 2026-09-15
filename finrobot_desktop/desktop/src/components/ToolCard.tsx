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
// Tool identity — raw tool name → human action label + an icon that
// gives each tool a shape you can recognise at a glance. The card shows
// IDENTITY + STATUS + the route to the data (Open report); it deliberately
// does NOT re-render the report's numbers (those live in the artifact, and
// echoing a computed figure here would risk it drifting from the source).
// ──────────────────────────────────────────────────────────────

interface ToolMeta {
  label: string
  icon: React.ReactElement
}

const TOOL_META: Record<string, ToolMeta> = {
  run_equity_research: { label: 'Equity Research', icon: <IconReport /> },
  run_comps_analysis: { label: 'Comparable Companies', icon: <IconNodes /> },
  run_dcf_valuation: { label: 'DCF Valuation', icon: <IconFunnel /> },
  run_lbo_analysis: { label: 'LBO Analysis', icon: <IconLayers /> },
  run_ddm_valuation: { label: 'DDM Valuation', icon: <IconCoins /> },
  run_earnings_analysis: { label: 'Earnings Quality', icon: <IconBars /> },
  run_ic_memo: { label: 'IC Memo', icon: <IconClipboard /> },
  query_financial_data: { label: 'Financial Data', icon: <IconDatabase /> },
  query_coverage_universe: { label: 'Watchlist', icon: <IconList /> },
  activate_skill: { label: 'Skill', icon: <IconSpark /> },
}

function toolMeta(toolName: string): ToolMeta {
  const known = TOOL_META[toolName]
  if (known) return known
  // Unknown / future tool: humanise the snake_case name (run_x_y → "X Y") so a
  // newly-added pipeline still reads as a product, not a function identifier.
  const label = toolName
    .replace(/^run_/, '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase())
  return { label: label || toolName, icon: <IconTool /> }
}

// ──────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────

function argsPreview(args: Record<string, unknown>): string {
  const entries = Object.entries(args).slice(0, 3)
  return entries.map(([k, v]) => `${k}="${String(v)}"`).join(', ')
}

function firstString(...vals: unknown[]): string | undefined {
  for (const v of vals) if (typeof v === 'string' && v.trim()) return v
  return undefined
}

// Top-right state glyph. Carries the aria-label that announces the tool's
// lifecycle to assistive tech (and that the unit tests assert on).
function StatusGlyph({ state }: { state: ToolCardState }): React.ReactElement {
  switch (state) {
    case 'pending':
      return (
        <span className="tcard__glyph" aria-label="pending">
          <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
            <circle cx="7" cy="7" r="5.25" stroke="var(--text-muted)" strokeWidth="1.4" />
          </svg>
        </span>
      )
    case 'running':
      return (
        <span className="tcard__glyph tcard__glyph--spin" aria-label="running">
          <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
            <circle
              cx="7"
              cy="7"
              r="5.25"
              stroke="color-mix(in srgb, var(--aip-accent) 26%, transparent)"
              strokeWidth="1.4"
            />
            <path
              d="M7 1.75a5.25 5.25 0 0 1 5.25 5.25"
              stroke="var(--aip-accent)"
              strokeWidth="1.4"
              strokeLinecap="round"
            />
          </svg>
        </span>
      )
    case 'complete':
      return (
        <span className="tcard__glyph" aria-label="complete">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <circle cx="7" cy="7" r="6" stroke="var(--success)" strokeWidth="1.4" />
            <path
              d="M4.3 7.2L6.2 9.1L9.8 5.2"
              stroke="var(--success)"
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </span>
      )
    case 'error':
      return (
        <span className="tcard__glyph" aria-label="error">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <circle cx="7" cy="7" r="6" stroke="var(--danger)" strokeWidth="1.4" />
            <path
              d="M5 5L9 9M9 5L5 9"
              stroke="var(--danger)"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </span>
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
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [summaryOpen, setSummaryOpen] = useState(false)
  const { t } = useI18n()

  const meta = toolMeta(toolName)
  const summary = result?.summary ?? ''
  const summaryIsLong = summary.length > SUMMARY_CLAMP_CHARS

  const ticker = firstString(result?.ticker, args.ticker as unknown)?.toUpperCase()
  // query_financial_data carries the data slice it pulled (quote / financials / …);
  // surfacing it as a quiet hint tells the analyst WHICH cut ran without dumping it.
  const dataType = firstString(args.data_type as unknown)

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
      className="tcard"
    >
      {/* Header: icon tile · action title (hover = raw call, click = args) · status */}
      <div className="tcard__head">
        <span className="tcard__tile">{meta.icon}</span>

        <span className="tcard__headtext">
          <button
            type="button"
            onClick={() => setDetailsOpen((v) => !v)}
            className="tcard__title"
            aria-expanded={detailsOpen}
            title={`${toolName}(${argsPreview(args)})`}
          >
            {meta.label}
          </button>
          <span className="tcard__meta">
            {ticker && <span className="tcard__ticker">{ticker}</span>}
            {dataType && <span className="tcard__hint">{dataType}</span>}
            {state === 'running' && <span className="tcard__hint">running…</span>}
          </span>
        </span>

        <StatusGlyph state={state} />
      </div>

      {/* Running: a slim indeterminate scan bar — honest "working" signal. */}
      {state === 'running' && (
        <div className="tcard__progress" aria-hidden="true">
          <span />
        </div>
      )}

      {/* Raw call args (collapsed; opened from the title). */}
      {detailsOpen && <div className="tcard__details">{JSON.stringify(args, null, 2)}</div>}

      {/* Result body — only on complete. A short result (a DCF range, a quote)
          renders inline. A long body (a pipeline returns its WHOLE report here)
          stays collapsed behind a toggle and, when opened, sits in a bounded
          scroll box so it never blows the chat thread open. */}
      {state === 'complete' && (summary || artifactHref) && (
        <div className="tcard__body">
          {summary &&
            (summaryIsLong ? (
              <div>
                <button
                  type="button"
                  data-testid="summary-toggle"
                  onClick={() => setSummaryOpen((v) => !v)}
                  aria-expanded={summaryOpen}
                  className="tcard__toggle"
                >
                  {/* Hardcoded EN (app ships English-only): the Lingui catalog is
                      frozen legacy — a missing key would render its raw id. */}
                  <span>{summaryOpen ? 'Hide result' : 'Show full result'}</span>
                  <svg
                    className="tcard__chev"
                    data-open={summaryOpen}
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </button>
                {summaryOpen && (
                  <div
                    data-testid="tool-summary"
                    className="tcard__summarybox"
                    style={{ maxHeight: 320, overflowY: 'auto' }}
                  >
                    <MarkdownLite text={summary} />
                  </div>
                )}
              </div>
            ) : (
              <div data-testid="tool-summary" className="tcard__summary">
                <MarkdownLite text={summary} />
              </div>
            ))}

          {/* Footer: provenance seal + the route to the full, sourced report. */}
          <div className="tcard__foot">
            <span
              className="tcard__seal"
              title="Every figure is computed by code and traceable to source."
            >
              <svg
                width="13"
                height="13"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <polyline points="9 12 11 14 15 10" />
              </svg>
              <span>Code-Computed</span>
              <span className="tcard__seal-sub">· Traceable</span>
            </span>

            {artifactHref && (
              // react-router <Link>, not a raw <a>: under createBrowserRouter a
              // bare anchor does a full document navigation that reboots the SPA
              // and discards the chat panel. <Link> keeps it an in-app transition.
              <Link to={artifactHref} data-testid="artifact-link" className="tcard__open">
                <svg
                  width="13"
                  height="13"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                  <polyline points="15 3 21 3 21 9" />
                  <line x1="10" y1="14" x2="21" y2="3" />
                </svg>
                {t('toolcard.openArtifact')}
              </Link>
            )}
          </div>
        </div>
      )}

      {/* Error */}
      {state === 'error' && (
        <div className="tcard__error">
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span>{errorText ?? t('toolcard.failed')}</span>
          {onRetry && (
            <button type="button" onClick={onRetry} className="tcard__retry">
              {t('toolcard.retry')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────────────────────
// Icons — inline SVG, 1.5 stroke, currentColor (tinted by the tile).
// ──────────────────────────────────────────────────────────────

function svgProps() {
  return {
    width: 17,
    height: 17,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.5,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
  }
}

function IconReport(): React.ReactElement {
  return (
    <svg {...svgProps()}>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <polyline points="14 2 14 8 20 8" />
      <line x1="16" y1="13" x2="8" y2="13" />
      <line x1="16" y1="17" x2="8" y2="17" />
      <line x1="10" y1="9" x2="8" y2="9" />
    </svg>
  )
}

function IconFunnel(): React.ReactElement {
  return (
    <svg {...svgProps()}>
      <path d="M22 3H2l8 9.46V19l4 2V12.46L22 3z" />
    </svg>
  )
}

function IconNodes(): React.ReactElement {
  return (
    <svg {...svgProps()}>
      <circle cx="12" cy="5" r="2" />
      <circle cx="5" cy="19" r="2" />
      <circle cx="19" cy="19" r="2" />
      <line x1="12" y1="7" x2="5" y2="17" />
      <line x1="12" y1="7" x2="19" y2="17" />
    </svg>
  )
}

function IconLayers(): React.ReactElement {
  return (
    <svg {...svgProps()}>
      <polygon points="12 2 2 7 12 12 22 7 12 2" />
      <polyline points="2 17 12 22 22 17" />
      <polyline points="2 12 12 17 22 12" />
    </svg>
  )
}

function IconCoins(): React.ReactElement {
  return (
    <svg {...svgProps()}>
      <ellipse cx="12" cy="6" rx="8" ry="3" />
      <path d="M4 6v6c0 1.66 3.58 3 8 3s8-1.34 8-3V6" />
      <path d="M4 12v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6" />
    </svg>
  )
}

function IconBars(): React.ReactElement {
  return (
    <svg {...svgProps()}>
      <line x1="6" y1="20" x2="6" y2="13" />
      <line x1="12" y1="20" x2="12" y2="4" />
      <line x1="18" y1="20" x2="18" y2="9" />
    </svg>
  )
}

function IconClipboard(): React.ReactElement {
  return (
    <svg {...svgProps()}>
      <path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" />
      <rect x="8" y="2" width="8" height="4" rx="1" />
      <line x1="8" y1="12" x2="16" y2="12" />
      <line x1="8" y1="16" x2="13" y2="16" />
    </svg>
  )
}

function IconDatabase(): React.ReactElement {
  return (
    <svg {...svgProps()}>
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  )
}

function IconList(): React.ReactElement {
  return (
    <svg {...svgProps()}>
      <line x1="8" y1="6" x2="21" y2="6" />
      <line x1="8" y1="12" x2="21" y2="12" />
      <line x1="8" y1="18" x2="21" y2="18" />
      <circle cx="3.5" cy="6" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="3.5" cy="12" r="1.2" fill="currentColor" stroke="none" />
      <circle cx="3.5" cy="18" r="1.2" fill="currentColor" stroke="none" />
    </svg>
  )
}

function IconSpark(): React.ReactElement {
  return (
    <svg {...svgProps()}>
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4M5.6 5.6l2.8 2.8M15.6 15.6l2.8 2.8M18.4 5.6l-2.8 2.8M8.4 15.6l-2.8 2.8" />
    </svg>
  )
}

function IconTool(): React.ReactElement {
  return (
    <svg {...svgProps()}>
      <path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.3 2.3-2.4-.6-.6-2.4z" />
    </svg>
  )
}
