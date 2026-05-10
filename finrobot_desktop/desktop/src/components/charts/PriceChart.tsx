import { useState, useMemo } from 'react'
import {
  ComposedChart,
  Area,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

type TimeRange = '1M' | '3M' | '6M' | '1Y' | 'ALL'
const TIME_RANGES: TimeRange[] = ['1M', '3M', '6M', '1Y', 'ALL']

function daysForRange(range: TimeRange): number {
  switch (range) {
    case '1M': return 30
    case '3M': return 90
    case '6M': return 180
    case '1Y': return 365
    case 'ALL': return Infinity
  }
}

// Design system chart palette
const PRICE_COLOR = '#60A5FA'   // chart-1
const VOLUME_COLOR = '#C9A84C'  // chart-2

const CHART_TOOLTIP = {
  backgroundColor: '#1A1F2E',
  border: '1px solid #252A37',
  borderRadius: 6,
  color: '#E8ECF4',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

function formatVolume(value: number): string {
  if (value >= 1e6) return `${(value / 1e6).toFixed(1)}M`
  if (value >= 1e3) return `${(value / 1e3).toFixed(0)}K`
  return String(value)
}

export default function PriceChart({ data, title }: ChartProps) {
  const [range, setRange] = useState<TimeRange>('1Y')

  const filteredData = useMemo(() => {
    if (!data || data.length === 0) return []
    if (range === 'ALL') return data
    const days = daysForRange(range)
    const cutoff = new Date()
    cutoff.setDate(cutoff.getDate() - days)
    const cutoffStr = cutoff.toISOString().slice(0, 10)
    return data.filter((d) => (d.date as string) >= cutoffStr)
  }, [data, range])

  if (!data || data.length === 0) return null

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
        <div className="time-range-selector">
          {TIME_RANGES.map((r) => (
            <button
              key={r}
              className={`time-range-btn${range === r ? ' active' : ''}`}
              onClick={() => setRange(r)}
            >
              {r}
            </button>
          ))}
        </div>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={260}>
          <ComposedChart data={filteredData}>
            <defs>
              <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={PRICE_COLOR} stopOpacity={0.15} />
                <stop offset="95%" stopColor={PRICE_COLOR} stopOpacity={0.01} />
              </linearGradient>
            </defs>
            <XAxis
              dataKey="date"
              tick={{ fill: '#7A8299', fontSize: 10, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
              tickFormatter={(d: string) => {
                const date = new Date(d)
                return range === '1M'
                  ? `${date.getMonth() + 1}/${date.getDate()}`
                  : `${date.getFullYear().toString().slice(2)}/${(date.getMonth() + 1).toString().padStart(2, '0')}`
              }}
              minTickGap={40}
            />
            <YAxis
              yAxisId="price"
              orientation="left"
              tick={{ fill: '#7A8299', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
              tickFormatter={(v: number) => `$${v}`}
              domain={['auto', 'auto']}
            />
            <YAxis
              yAxisId="volume"
              orientation="right"
              tick={{ fill: '#7A8299', fontSize: 11, fontFamily: "'JetBrains Mono', monospace" }}
              axisLine={{ stroke: '#252A37' }}
              tickFormatter={formatVolume}
            />
            <Tooltip
              contentStyle={CHART_TOOLTIP}
              formatter={(value: number, name: string) => {
                if (name === 'Volume') return [formatVolume(value), name]
                return [`$${value.toFixed(2)}`, name]
              }}
            />
            <Legend wrapperStyle={{ color: '#7A8299', fontSize: '0.72rem' }} />
            <Bar
              yAxisId="volume"
              dataKey="volume"
              name="Volume"
              fill={VOLUME_COLOR}
              opacity={0.3}
              barSize={4}
            />
            <Area
              yAxisId="price"
              type="monotone"
              dataKey="close"
              name="Close"
              stroke={PRICE_COLOR}
              strokeWidth={2}
              fill="url(#priceGradient)"
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
