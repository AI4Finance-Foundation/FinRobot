import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from 'recharts'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

const COLORS = ['#1a365d', '#d4a843', '#6b7280', '#3b82f6', '#10b981', '#f59e0b']

/**
 * Football field chart: horizontal stacked bars showing valuation ranges.
 *
 * Each row is a valuation method. The bar spans from `low` to `high`,
 * with `mid` shown as a reference dot. We achieve the floating bar by
 * using a transparent "base" bar (from 0 to low) plus a visible "range"
 * bar (from low to high).
 */
export default function FootballField({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  const shaped = data.map((d) => ({
    method: String(d.method),
    low: Number(d.low),
    mid: Number(d.mid),
    high: Number(d.high),
    base: Number(d.low),
    range: Number(d.high) - Number(d.low),
  }))

  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h4 className="text-sm font-medium text-gray-400 mb-3">{title}</h4>
      <ResponsiveContainer width="100%" height={Math.max(200, shaped.length * 50 + 60)}>
        <BarChart data={shaped} layout="vertical" barSize={20}>
          <XAxis
            type="number"
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#4b5563' }}
            tickFormatter={(v: number) => `$${v}`}
          />
          <YAxis
            type="category"
            dataKey="method"
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#4b5563' }}
            width={100}
          />
          <Tooltip
            formatter={(value: number, name: string) => {
              if (name === 'base') return [null, null]
              return [`$${value.toFixed(0)}`, 'Range']
            }}
            contentStyle={{
              backgroundColor: '#1f2937',
              border: '1px solid #374151',
              borderRadius: 8,
              color: '#e5e7eb',
            }}
          />
          {/* Invisible base bar */}
          <Bar dataKey="base" stackId="stack" fill="transparent" />
          {/* Visible range bar */}
          <Bar dataKey="range" stackId="stack" radius={[0, 4, 4, 0]}>
            {shaped.map((_, index) => (
              <Cell key={`range-${index}`} fill={COLORS[index % COLORS.length]} />
            ))}
          </Bar>
          {/* Mid-point reference lines */}
          {shaped.map((entry) => (
            <ReferenceLine
              key={`mid-${entry.method}`}
              x={entry.mid}
              stroke="#e5e7eb"
              strokeDasharray="3 3"
              strokeWidth={1}
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
