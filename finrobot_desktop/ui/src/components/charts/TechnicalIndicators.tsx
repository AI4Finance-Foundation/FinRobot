import { useMemo } from 'react'
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'
import type { TooltipValueType } from 'recharts'
import { rsi } from './technicalUtils'
import type { OHLCRow } from './CandlestickChart'

// ---------- Design tokens ----------

const RSI_COLOR = '#60A5FA'    // --chart-1
const OVERBOUGHT_COLOR = '#F87171' // --negative
const OVERSOLD_COLOR = '#34D399'   // --positive

const CHART_TOOLTIP = {
  backgroundColor: '#1A1F2E',
  border: '1px solid #252A37',
  borderRadius: 6,
  color: '#E8ECF4',
  fontFamily: "'JetBrains Mono', monospace",
  fontSize: '0.78rem',
}

// ---------- Types ----------

interface TechnicalIndicatorsProps {
  data: OHLCRow[]
  showRSI: boolean
}

interface RSIRow {
  date: string
  rsi: number | null
}

// ---------- Component ----------

export default function TechnicalIndicators({ data, showRSI }: TechnicalIndicatorsProps) {
  const rsiData = useMemo((): RSIRow[] => {
    if (!data || data.length === 0) return []
    const closes = data.map((d) => d.close)
    const rsiValues = rsi(closes, 14)
    return data.map((row, i) => ({
      date: row.date,
      rsi: rsiValues[i],
    }))
  }, [data])

  if (!showRSI || rsiData.length === 0) return null

  return (
    <div style={{ marginTop: 4 }}>
      <div
        style={{
          fontSize: '0.65rem',
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          color: '#7A8299',
          padding: '0 16px 4px',
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        RSI(14)
      </div>
      <ResponsiveContainer width="100%" height={100}>
        <ComposedChart
          data={rsiData}
          margin={{ top: 4, right: 8, bottom: 0, left: 0 }}
        >
          <XAxis
            dataKey="date"
            tick={false}
            axisLine={{ stroke: '#252A37' }}
            height={0}
          />
          <YAxis
            domain={[0, 100]}
            ticks={[30, 50, 70]}
            tick={{ fill: '#7A8299', fontSize: 10, fontFamily: "'JetBrains Mono', monospace" }}
            axisLine={{ stroke: '#252A37' }}
            width={40}
          />
          <Tooltip
            contentStyle={CHART_TOOLTIP}
            labelStyle={{ color: '#E8ECF4' }}
            formatter={(value: TooltipValueType | undefined) => {
              const v = typeof value === 'number' ? value : 0
              return [v.toFixed(1), 'RSI']
            }}
          />

          {/* Overbought / oversold zones */}
          <ReferenceLine y={70} stroke={OVERBOUGHT_COLOR} strokeDasharray="3 3" strokeOpacity={0.6} />
          <ReferenceLine y={30} stroke={OVERSOLD_COLOR} strokeDasharray="3 3" strokeOpacity={0.6} />
          <ReferenceLine y={50} stroke="#252A37" strokeDasharray="2 2" />

          <Line
            dataKey="rsi"
            stroke={RSI_COLOR}
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
            connectNulls
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
