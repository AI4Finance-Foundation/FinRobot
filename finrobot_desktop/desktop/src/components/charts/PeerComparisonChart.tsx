import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from 'recharts'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

const PRIMARY = '#1a365d'
const ACCENT = '#d4a843'
const TARGET_HIGHLIGHT = '#f59e0b'

export default function PeerComparisonChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h4 className="text-sm font-medium text-gray-400 mb-3">{title}</h4>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data} barGap={4}>
          <XAxis
            dataKey="ticker"
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#4b5563' }}
          />
          <YAxis
            tick={{ fill: '#9ca3af', fontSize: 12 }}
            axisLine={{ stroke: '#4b5563' }}
          />
          <Tooltip
            formatter={(value: number) => value.toFixed(1)}
            contentStyle={{
              backgroundColor: '#1f2937',
              border: '1px solid #374151',
              borderRadius: 8,
              color: '#e5e7eb',
            }}
          />
          <Legend wrapperStyle={{ color: '#9ca3af' }} />
          <Bar dataKey="ev_ebitda" name="EV/EBITDA" radius={[4, 4, 0, 0]}>
            {data.map((entry, index) => (
              <Cell
                key={`ev-${index}`}
                fill={entry.is_target ? TARGET_HIGHLIGHT : PRIMARY}
              />
            ))}
          </Bar>
          <Bar dataKey="pe_ratio" name="P/E Ratio" radius={[4, 4, 0, 0]}>
            {data.map((entry, index) => (
              <Cell
                key={`pe-${index}`}
                fill={entry.is_target ? TARGET_HIGHLIGHT : ACCENT}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
