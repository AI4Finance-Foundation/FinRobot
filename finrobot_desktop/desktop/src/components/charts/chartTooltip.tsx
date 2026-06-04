// Shared cosmic tooltip + legend for Recharts bar/line/area charts.
//
// Extracted from RevenueEbitdaChart, which solved a recurring user complaint
// (2026-05-22, again 2026-06-01): the Recharts default tooltip (bg barely
// lighter than the chart surface) and default legend swatches (rendered black)
// both "blend into the background". Any chart using the library defaults
// reproduces that bug, so every cosmic chart routes its <Tooltip>/<Legend>
// through these.
//
// Most charts use <CosmicTooltip>/<CosmicLegend> directly. Charts with bespoke
// row semantics (waterfall add/subtract/total, histogram bins) compose the same
// look from <CosmicTooltipShell> + <CosmicTooltipRow> so there is exactly one
// visual source of truth.

import type { CSSProperties, ReactNode } from 'react'

interface TooltipPayloadItem {
  value?: number | string | null
  name?: string
  dataKey?: string | number
  color?: string
}

export interface CosmicTooltipProps {
  active?: boolean
  payload?: TooltipPayloadItem[]
  label?: string | number
  // How each row's numeric value is rendered (e.g. `${v}x`, `$${v}B`).
  format?: (value: number) => string
  // Render the header from the raw category label (e.g. bin number -> `$152.30`).
  labelFormat?: (label: string | number) => ReactNode
  // Accent color for the header.
  labelColor?: string
}

interface LegendPayloadItem {
  value: string
  color?: string
}

export interface CosmicLegendProps {
  payload?: LegendPayloadItem[]
}

const TOOLTIP_SHELL: CSSProperties = {
  background: 'rgba(15, 15, 34, 0.92)',
  backdropFilter: 'blur(12px)',
  WebkitBackdropFilter: 'blur(12px)',
  border: '1px solid var(--border-glow)',
  borderRadius: 8,
  padding: '10px 14px',
  fontFamily: 'var(--font-mono)',
  fontSize: 12,
  color: 'var(--text-primary)',
  boxShadow: 'var(--glow-blue)',
  minWidth: 160,
}

export function CosmicTooltipShell({
  label,
  labelColor = 'var(--accent-cyan)',
  children,
}: {
  label?: ReactNode
  labelColor?: string
  children: ReactNode
}) {
  return (
    <div style={TOOLTIP_SHELL}>
      {label != null && label !== '' && (
        <div
          style={{
            fontFamily: 'var(--font-display)',
            fontSize: 11,
            letterSpacing: '0.12em',
            color: labelColor,
            marginBottom: 6,
          }}
        >
          {label}
        </div>
      )}
      {children}
    </div>
  )
}

export function CosmicTooltipRow({
  color,
  name,
  value,
}: {
  color?: string
  name: ReactNode
  value: ReactNode
}) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}>
      <span
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          color: 'var(--text-secondary)',
        }}
      >
        <span
          aria-hidden
          style={{
            display: 'inline-block',
            width: 8,
            height: 8,
            borderRadius: 2,
            background: color ?? 'var(--text-muted)',
            boxShadow: `0 0 6px ${color ?? 'transparent'}`,
          }}
        />
        {name}
      </span>
      <span style={{ color: 'var(--text-primary)', fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </span>
    </div>
  )
}

export function CosmicTooltip({
  active,
  payload,
  label,
  format = (v) => String(v),
  labelFormat,
  labelColor,
}: CosmicTooltipProps) {
  if (!active || !payload || payload.length === 0) return null
  const header = labelFormat && label != null ? labelFormat(label) : label
  return (
    <CosmicTooltipShell label={header} labelColor={labelColor}>
      {payload.map((p) => {
        const v = typeof p.value === 'number' ? p.value : 0
        return (
          <CosmicTooltipRow
            key={String(p.dataKey ?? p.name)}
            color={p.color}
            name={p.name}
            value={format(v)}
          />
        )
      })}
    </CosmicTooltipShell>
  )
}

export function CosmicLegend({ payload = [] }: CosmicLegendProps) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        gap: 18,
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        letterSpacing: '0.04em',
        color: 'var(--text-secondary)',
        marginTop: 6,
      }}
    >
      {payload.map((entry) => (
        <span
          key={String(entry.value)}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
        >
          <span
            aria-hidden
            style={{
              display: 'inline-block',
              width: 10,
              height: 10,
              borderRadius: 2,
              background: entry.color,
              boxShadow: `0 0 8px ${entry.color}`,
            }}
          />
          {entry.value}
        </span>
      ))}
    </div>
  )
}
