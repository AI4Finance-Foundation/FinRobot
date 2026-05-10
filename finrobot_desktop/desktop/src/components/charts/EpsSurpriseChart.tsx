import {
  ComposedChart,
  Bar,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from 'recharts'

interface SurpriseDataPoint {
  quarter: string
  eps_actual: number
  eps_estimated: number
  surprise_pct: number
  direction: 'beat' | 'miss' | 'inline'
}

interface ChartProps {
  data: SurpriseDataPoint[]
  title: string
}

const BEAT_COLOR = '#34D399'
const MISS_COLOR = '#F87171'
const INLINE_COLOR = '#C9A84C'
const ESTIMATE_COLOR = 'rgba(122, 130, 153, 0.6)'

const CHART_TOOLTIP = {
  backgroundColor: '#1A1F2E',
  border: '1px solid #252A37',
  borderRadius: 6,
  color: '#E8ECF4',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

function dirColor(dir: string): string {
  if (dir === 'beat') return BEAT_COLOR
  if (dir === 'miss') return MISS_COLOR
  return INLINE_COLOR
}

export default function EpsSurpriseChart({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={data} barGap={1} barCategoryGap="20%">
            <XAxis
              dataKey="quarter"
              tick={{ fill: '#7A8299', fontSize: 10, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
              interval={0}
              angle={-30}
              textAnchor="end"
              height={45}
            />
            <YAxis
              tick={{ fill: '#7A8299', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
              tickFormatter={(v: number) => `$${v.toFixed(2)}`}
            />
            <Tooltip
              contentStyle={CHART_TOOLTIP}
              formatter={(value: number, name: string) => {
                if (name === 'Estimate') return [`$${value.toFixed(2)}`, name]
                return [`$${value.toFixed(2)}`, name]
              }}
              labelFormatter={(label: string) => `Quarter: ${label}`}
            />
            <Legend wrapperStyle={{ color: '#7A8299', fontSize: '0.72rem' }} />
            <ReferenceLine y={0} stroke="#252A37" strokeDasharray="3 3" />
            <Bar
              dataKey="eps_estimated"
              name="Estimate"
              fill={ESTIMATE_COLOR}
              radius={[2, 2, 0, 0]}
              barSize={16}
            />
            <Bar
              dataKey="eps_actual"
              name="Actual"
              radius={[2, 2, 0, 0]}
              barSize={16}
            >
              {data.map((entry, index) => (
                <Cell key={`actual-${index}`} fill={dirColor(entry.direction)} />
              ))}
            </Bar>
            <Line
              type="monotone"
              dataKey="eps_estimated"
              stroke="#7A8299"
              strokeWidth={1}
              strokeDasharray="4 3"
              dot={false}
              name="Consensus"
              legendType="none"
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
