// Revenue / EBITDA 多年趋势图 — cosmic 化重写。
//
// 用户痛点（2026-05-22 反馈）:
//   - 数字看不清：Y 轴 tick 用了 --text-muted (42% opacity)，dark bg 上几乎不可见
//   - 不好看：EBITDA 用 #C9A84C 暗黄、Recharts 默认 hover cursor 渲染成大灰矩形挡住整柱、
//     图例 swatch 黑掉、柱顶没有直接数值
//
// 修法:
//   1. Y 轴 / X 轴 tick 升级到 --text-secondary，cosmic mono 字体
//   2. EBITDA 改用 --accent-cyan（cosmic 双轨第二色），跟 Revenue 蓝拉开
//   3. 关掉 Recharts 默认 cursor，换成 var(--primary-soft) 的柔光矩形
//   4. 每柱顶部用 LabelList 直接挂 $XB 数字（cosmic mono · 11px）
//   5. Legend swatch 用 payload 显式控制颜色，不让 recharts 偷偷渲染黑色
//   6. Tooltip 加 neon glow border + backdrop blur

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
  LabelList,
} from 'recharts'

// Recharts custom-component prop types are notoriously imprecise across
// versions; using narrow local shapes keeps this file portable as the
// library evolves.
interface TooltipPayloadItem {
  value?: number | string | null
  name?: string
  dataKey?: string | number
  color?: string
}
interface CosmicTooltipProps {
  active?: boolean
  payload?: TooltipPayloadItem[]
  label?: string | number
}
interface LegendPayloadItem {
  value: string
  color?: string
}
interface CosmicLegendProps {
  payload?: LegendPayloadItem[]
}

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

const REVENUE_COLOR = 'var(--primary)'
const EBITDA_COLOR = 'var(--accent-cyan)'
const FORECAST_REVENUE = 'rgba(59, 130, 246, 0.32)'
const FORECAST_EBITDA = 'rgba(34, 211, 238, 0.32)'

function formatBillions(value: number): string {
  if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(1)}B`
  if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(1)}M`
  return `$${value.toLocaleString()}`
}

function CosmicTooltip({ active, payload, label }: CosmicTooltipProps) {
  if (!active || !payload || payload.length === 0) return null
  return (
    <div
      style={{
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
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 11,
          letterSpacing: '0.12em',
          color: 'var(--accent-cyan)',
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      {payload.map((p) => {
        const v = typeof p.value === 'number' ? p.value : 0
        return (
          <div
            key={String(p.dataKey ?? p.name)}
            style={{ display: 'flex', justifyContent: 'space-between', gap: 16 }}
          >
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, color: 'var(--text-secondary)' }}>
              <span
                aria-hidden
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: 2,
                  background: p.color ?? 'var(--text-muted)',
                  boxShadow: `0 0 6px ${p.color ?? 'transparent'}`,
                }}
              />
              {p.name}
            </span>
            <span style={{ color: 'var(--text-primary)', fontVariantNumeric: 'tabular-nums' }}>
              {formatBillions(v)}
            </span>
          </div>
        )
      })}
    </div>
  )
}

function CosmicLegend(props: CosmicLegendProps) {
  const payload = props.payload ?? []
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

export default function RevenueEbitdaChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={300}>
          <BarChart data={data} barGap={6} margin={{ top: 24, right: 16, left: 0, bottom: 4 }}>
            <XAxis
              dataKey="year"
              tick={{
                fill: 'var(--text-secondary)',
                fontSize: 12,
                fontFamily: "'JetBrains Mono', monospace",
              }}
              tickLine={false}
              axisLine={{ stroke: 'var(--border-soft)' }}
            />
            <YAxis
              tickFormatter={formatBillions}
              tick={{
                fill: 'var(--text-secondary)',
                fontSize: 11,
                fontFamily: "'JetBrains Mono', monospace",
              }}
              tickLine={false}
              axisLine={{ stroke: 'var(--border-soft)' }}
              width={64}
            />
            <Tooltip
              content={<CosmicTooltip />}
              // The default hover-cursor is a giant filled rect that on dark
              // bg becomes that "ghost rectangle" the user flagged. Tint it
              // to the cosmic primary-soft so it reads as a focus highlight
              // rather than a render bug.
              cursor={{ fill: 'var(--primary-soft)', radius: 4 }}
            />
            <Legend content={<CosmicLegend />} />
            <Bar
              dataKey="revenue"
              name="Revenue"
              radius={[4, 4, 0, 0]}
              fill={REVENUE_COLOR}
              isAnimationActive={false}
            >
              {data.map((entry, index) => (
                <Cell
                  key={`rev-${index}`}
                  fill={entry.is_forecast ? FORECAST_REVENUE : REVENUE_COLOR}
                />
              ))}
              <LabelList
                dataKey="revenue"
                position="top"
                formatter={(v: unknown) =>
                  typeof v === 'number' && v > 0 ? formatBillions(v) : ''
                }
                style={{
                  fill: 'var(--text-primary)',
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 11,
                  fontWeight: 600,
                }}
              />
            </Bar>
            <Bar
              dataKey="ebitda"
              name="EBITDA"
              radius={[4, 4, 0, 0]}
              fill={EBITDA_COLOR}
              isAnimationActive={false}
            >
              {data.map((entry, index) => (
                <Cell
                  key={`ebitda-${index}`}
                  fill={entry.is_forecast ? FORECAST_EBITDA : EBITDA_COLOR}
                />
              ))}
              <LabelList
                dataKey="ebitda"
                position="top"
                formatter={(v: unknown) =>
                  typeof v === 'number' && v > 0 ? formatBillions(v) : ''
                }
                style={{
                  fill: 'var(--accent-cyan)',
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 11,
                  fontWeight: 600,
                }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
