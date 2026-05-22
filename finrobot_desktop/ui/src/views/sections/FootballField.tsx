// v5 §6.4 Football Field — horizontal box plot for the 4 valuation methods +
// 2 multiple-based reverse ranges. Reads PR2's
// GET /api/valuation/aggregate/{ticker}.
//
// Visual contract (spec §6.4): valuation rows render with solid filled bars,
// multiple rows render as dashed-outline ranges. Current-price line is a
// blue vertical at the right x-position.

import { useMemo } from 'react'
import { useValuationAggregate } from '../../hooks/useV5Artifacts'
import { useThesisNarrative } from '../../hooks/useThesisNarrative'
import type { ValuationMethodRange } from '../../types/v5'

const METHOD_LABELS: Record<string, string> = {
  dcf: 'DCF',
  comps_pe: 'Comps (P/E)',
  ddm: 'DDM',
  lbo: 'LBO',
  ev_ebitda: 'EV/EBITDA',
  p_fcf: 'P/FCF',
}


const ROW_HEIGHT = 28
const LABEL_WIDTH = 120
const RIGHT_PAD = 92

interface FootballFieldProps {
  ticker: string
}

export function FootballField({ ticker }: FootballFieldProps): React.ReactElement {
  const { data, isLoading, isError } = useValuationAggregate(ticker)
  const thesis = useThesisNarrative(ticker)

  const methods = data?.methods ?? []
  const current = data?.current_price ?? null

  const axis = useMemo(() => buildAxis(methods, current), [methods, current])

  if (isLoading) {
    return (
      <section id="sec-football" className="cosmic-card" style={{ margin: "12px 0" }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>
          🏟️ 估值范围 (Football Field)
        </h2>
        <p style={{ marginTop: 12, fontSize: 12, color: 'var(--text-faint)' }}>加载中…</p>
      </section>
    )
  }

  if (isError || methods.length === 0) {
    return (
      <section id="sec-football" className="cosmic-card" style={{ margin: "12px 0" }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>
          🏟️ 估值范围 (Football Field)
        </h2>
        <p style={{ marginTop: 12, color: 'var(--text-soft)', fontSize: 13 }}>
          跑分析后这里展示 4 valuation + 2 multiple 反推的目标价范围。
        </p>
        {data?.warnings.map((w, i) => (
          <p key={i} style={{ marginTop: 6, fontSize: 11, color: 'var(--text-faint)' }}>
            • {w}
          </p>
        ))}
      </section>
    )
  }

  return (
    <section id="sec-football" className="cosmic-card" style={{ margin: "12px 0" }}>
      <header style={{ marginBottom: 14 }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>
          🏟️ 估值范围 (Football Field)
        </h2>
        <p style={{ marginTop: 2, fontSize: 11, color: 'var(--text-faint)' }}>
          {methods.filter((m) => m.method_type === 'valuation').length} valuation +{' '}
          {methods.filter((m) => m.method_type === 'multiple').length} multiple 反推 ·
          当前 ${current?.toFixed(2) ?? 'N/A'}
        </p>
      </header>

      <div
        data-testid="football-field-svg-wrapper"
        style={{
          position: 'relative',
          paddingLeft: LABEL_WIDTH,
          paddingRight: RIGHT_PAD,
          minHeight: methods.length * (ROW_HEIGHT + 8) + 30,
        }}
      >
        {/* Current price vertical line */}
        {current !== null && (
          <div
            data-testid="football-field-current-line"
            style={{
              position: 'absolute',
              top: 0,
              bottom: 24,
              left: `calc(${LABEL_WIDTH}px + ${
                ((current - axis.min) / (axis.max - axis.min)) * 100
              }% - ${
                ((current - axis.min) / (axis.max - axis.min)) * (LABEL_WIDTH + RIGHT_PAD)
              }px)`,
              width: 2,
              background: 'var(--blue, #3B82F6)',
              opacity: 0.55,
            }}
          />
        )}
        {methods.map((m) => (
          <MethodRow key={m.method} method={m} axis={axis} />
        ))}
        {/* X-axis labels */}
        <div
          style={{
            position: 'relative',
            height: 18,
            marginTop: 8,
            fontSize: 10,
            color: 'var(--text-faint)',
          }}
        >
          <span style={{ position: 'absolute', left: 0 }}>${axis.min.toFixed(0)}</span>
          <span style={{ position: 'absolute', right: 0 }}>${axis.max.toFixed(0)}</span>
        </div>
      </div>

      {thesis?.valuation_overview && (
        <NarrativeCallout
          label="估值解读"
          icon="🔬"
          body={thesis.valuation_overview}
        />
      )}

      {data && data.warnings.length > 0 && (
        <details style={{ marginTop: 16, fontSize: 11 }}>
          <summary style={{ cursor: 'pointer', color: 'var(--text-faint)' }}>
            {data.warnings.length} 个 method 当前不可见（点开查看原因）
          </summary>
          <ul style={{ marginTop: 6, paddingLeft: 16, color: 'var(--text-soft)' }}>
            {data.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}

function NarrativeCallout({
  label,
  icon,
  body,
}: {
  label: string
  icon: string
  body: string
}): React.ReactElement {
  return (
    <div
      style={{
        marginTop: 18,
        padding: '14px 16px',
        borderRadius: 'var(--radius-md)',
        background: 'rgba(34, 211, 238, 0.06)',
        border: '1px solid rgba(34, 211, 238, 0.22)',
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          letterSpacing: '0.12em',
          textTransform: 'uppercase',
          color: 'var(--accent-cyan)',
          marginBottom: 6,
        }}
      >
        {icon} {label}
      </div>
      <p
        style={{
          margin: 0,
          fontFamily: 'var(--font-body)',
          fontSize: 13,
          color: 'var(--text-secondary)',
          lineHeight: 1.65,
        }}
      >
        {body}
      </p>
    </div>
  )
}

interface MethodRowProps {
  method: ValuationMethodRange
  axis: { min: number; max: number }
}

function MethodRow({ method, axis }: MethodRowProps): React.ReactElement {
  const left = ((method.low - axis.min) / (axis.max - axis.min)) * 100
  const width = ((method.high - method.low) / (axis.max - axis.min)) * 100
  const isMultiple = method.method_type === 'multiple'

  return (
    <div
      data-testid={`football-row-${method.method}`}
      data-method-type={method.method_type}
      style={{
        position: 'relative',
        height: ROW_HEIGHT,
        marginBottom: 8,
      }}
    >
      <span
        style={{
          position: 'absolute',
          left: -LABEL_WIDTH,
          width: LABEL_WIDTH - 8,
          textAlign: 'right',
          fontSize: 12,
          lineHeight: `${ROW_HEIGHT}px`,
          color: 'var(--text)',
        }}
        title={method.source}
      >
        {METHOD_LABELS[method.method] ?? method.method}
      </span>
      <div
        style={{
          position: 'absolute',
          left: `${left}%`,
          width: `${width}%`,
          top: 6,
          height: ROW_HEIGHT - 12,
          background: isMultiple ? 'rgba(59, 130, 246, 0.08)' : 'rgba(16, 185, 129, 0.18)',
          border: isMultiple
            ? '1px dashed rgba(59, 130, 246, 0.55)'
            : '1px solid rgba(16, 185, 129, 0.55)',
          borderRadius: 4,
        }}
      />
      {/* Mid marker */}
      <div
        style={{
          position: 'absolute',
          left: `${((method.mid - axis.min) / (axis.max - axis.min)) * 100}%`,
          top: 4,
          width: 2,
          height: ROW_HEIGHT - 8,
          background: isMultiple ? '#3B82F6' : '#10B981',
        }}
      />
      <span
        style={{
          position: 'absolute',
          right: -RIGHT_PAD + 8,
          width: RIGHT_PAD - 12,
          textAlign: 'left',
          fontSize: 11,
          lineHeight: `${ROW_HEIGHT}px`,
          color: 'var(--text-faint)',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        ${method.mid.toFixed(0)}
      </span>
    </div>
  )
}

function buildAxis(
  methods: ValuationMethodRange[],
  current: number | null,
): { min: number; max: number } {
  const lows = methods.map((m) => m.low)
  const highs = methods.map((m) => m.high)
  if (current !== null) {
    lows.push(current)
    highs.push(current)
  }
  const min = Math.min(...lows) * 0.92
  const max = Math.max(...highs) * 1.05
  return { min, max }
}
