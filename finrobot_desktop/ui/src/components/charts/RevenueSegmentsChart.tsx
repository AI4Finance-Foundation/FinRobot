import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts'
import type { TooltipValueType } from 'recharts'
import type { PieLabelRenderProps } from 'recharts'

interface SegmentData {
  segment: string
  revenue: number
  pct: number
}

interface ChartProps {
  data: SegmentData[]
  title: string
}

const COLORS = ['var(--primary)', '#C9A84C', 'var(--success)', 'var(--danger)', 'var(--secondary)', 'var(--warning)']

const CHART_TOOLTIP = {
  backgroundColor: 'var(--bg-3)',
  border: '1px solid var(--border-hover)',
  borderRadius: 6,
  color: 'var(--text-primary)',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

function formatBillions(v: number): string {
  if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(1)}B`
  if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(0)}M`
  return String(v)
}

function renderLabel(props: PieLabelRenderProps): string {
  // `percent` is provided by recharts (0–1); multiply by 100 for display
  const pct = typeof props.percent === 'number' ? props.percent * 100 : 0
  return `${pct.toFixed(1)}%`
}

export default function RevenueSegmentsChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={260}>
          <PieChart>
            <Pie
              data={data}
              dataKey="revenue"
              nameKey="segment"
              cx="50%"
              cy="50%"
              outerRadius={90}
              label={renderLabel}
              labelLine={false}
            >
              {data.map((_entry, index) => (
                <Cell key={`seg-${index}`} fill={COLORS[index % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              formatter={(value: TooltipValueType | undefined) =>
                formatBillions(typeof value === 'number' ? value : 0)
              }
              contentStyle={CHART_TOOLTIP}
              labelStyle={{ color: 'var(--text-primary)' }}
            />
            <Legend wrapperStyle={{ color: 'var(--text-secondary)', fontSize: '0.72rem' }} />
          </PieChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
