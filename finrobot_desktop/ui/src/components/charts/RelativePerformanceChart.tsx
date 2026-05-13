import { useMemo } from 'react'
import { LineChart, Line, XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, ReferenceLine } from 'recharts'
import type { PerformanceData } from '../../stores/appStore'

interface Props {
  data: PerformanceData
  title: string
}

const LINE_COLORS = ['#60A5FA', '#C9A84C', '#34D399', '#F87171', '#A78BFA', '#FB923C']

const CHART_TOOLTIP = {
  backgroundColor: '#1A1F2E',
  border: '1px solid #252A37',
  borderRadius: 6,
  color: '#E8ECF4',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

export default function RelativePerformanceChart({ data, title }: Props) {
  if (!data || data.series.length === 0) return null

  // Pivot array-of-series into shared-date rows: { date, AAPL: 112, MSFT: 108, ... }
  // Use sanitized ticker keys (replace . with _ to avoid Recharts dot-notation issues)
  const pivoted = useMemo(() => {
    const dateMap = new Map<string, Record<string, string | number>>()
    for (const series of data.series) {
      const safeKey = series.ticker.replace(/\./g, '_')
      for (const pt of series.data) {
        if (!dateMap.has(pt.date)) dateMap.set(pt.date, { date: pt.date })
        dateMap.get(pt.date)![safeKey] = pt.value
      }
    }
    return Array.from(dateMap.values()).sort((a, b) =>
      (a.date as string).localeCompare(b.date as string)
    )
  }, [data])

  const lines = data.series.map((s, i) => ({
    dataKey: s.ticker.replace(/\./g, '_'),
    label: s.label,
    color: LINE_COLORS[i % LINE_COLORS.length],
    isTarget: i === 0,
  }))

  return (
    <div className="card animate-in">
      <div className="card-header">
        <span className="card-title">{title}</span>
      </div>
      <div className="card-body">
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={pivoted}>
            <XAxis dataKey="date" tick={{ fill: '#7A8299', fontSize: 10 }} axisLine={{ stroke: '#252A37' }} />
            <YAxis tick={{ fill: '#7A8299', fontSize: 11 }} axisLine={{ stroke: '#252A37' }} domain={['auto', 'auto']} />
            <Tooltip contentStyle={CHART_TOOLTIP} />
            <Legend wrapperStyle={{ color: '#7A8299', fontSize: '0.72rem' }} />
            <ReferenceLine y={100} stroke="#252A37" strokeDasharray="3 3" />
            {lines.map((l) => (
              <Line
                key={l.dataKey}
                dataKey={l.dataKey}
                name={l.label}
                stroke={l.color}
                strokeWidth={l.isTarget ? 2.5 : 1.5}
                dot={false}
                type="monotone"
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
