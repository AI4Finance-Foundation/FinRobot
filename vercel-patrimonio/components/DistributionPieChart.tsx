'use client'

import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from 'recharts'

// Colors matching the established palette
const CATEGORY_COLORS: Record<string, string> = {
  renta_variable: '#3b82f6', // blue-500 - Equities
  renta_fija: '#10b981',     // green-500 - Fixed Income
  oro: '#f59e0b',            // amber-500 - Gold
  cripto: '#ef4444',         // red-500 - Crypto
  liquidez: '#8b5cf6',       // purple-500 - Cash
}

const CATEGORY_NAMES: Record<string, string> = {
  renta_variable: 'Renta Variable',
  renta_fija: 'Renta Fija',
  oro: 'Oro',
  cripto: 'Cripto',
  liquidez: 'Liquidez',
}

interface DistributionData {
  actual: number
  objetivo: number
  valor: number
}

interface Props {
  distribution: Record<string, DistributionData | undefined>
  showLegend?: boolean
  showTooltip?: boolean
  size?: 'small' | 'medium' | 'large'
  innerRadius?: number
  title?: string
}

interface PieDataEntry {
  name: string
  value: number
  percent: number
  color: string
  key: string
}

export default function DistributionPieChart({
  distribution,
  showLegend = true,
  showTooltip = true,
  size = 'medium',
  innerRadius,
  title,
}: Props) {
  // Convert distribution to pie chart data
  const data: PieDataEntry[] = Object.entries(distribution)
    .filter(([_, d]) => d && d.valor > 0)
    .map(([key, d]) => ({
      name: CATEGORY_NAMES[key] || key,
      value: d!.valor,
      percent: d!.actual,
      color: CATEGORY_COLORS[key] || '#6b7280',
      key,
    }))

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-gray-500 text-sm">
        No distribution data available
      </div>
    )
  }

  const heights = {
    small: 200,
    medium: 280,
    large: 350,
  } as const

  const outerRadii = {
    small: 70,
    medium: 90,
    large: 120,
  } as const

  const defaultInnerRadii = {
    small: 40,
    medium: 50,
    large: 70,
  } as const

  const formatEUR = (value: number) => {
    return new Intl.NumberFormat('es-ES', {
      style: 'currency',
      currency: 'EUR',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value)
  }

  const renderCustomLabel = ({
    cx,
    cy,
    midAngle,
    innerRadius: ir,
    outerRadius: or,
    percent,
  }: {
    cx: number
    cy: number
    midAngle: number
    innerRadius: number
    outerRadius: number
    percent: number
  }) => {
    if (percent < 0.05) return null // Don't show label for very small slices

    const RADIAN = Math.PI / 180
    const radius = ir + (or - ir) * 0.5
    const x = cx + radius * Math.cos(-midAngle * RADIAN)
    const y = cy + radius * Math.sin(-midAngle * RADIAN)

    return (
      <text
        x={x}
        y={y}
        fill="white"
        textAnchor="middle"
        dominantBaseline="central"
        style={{ fontSize: size === 'small' ? '10px' : '12px', fontWeight: 'bold' }}
      >
        {`${(percent * 100).toFixed(0)}%`}
      </text>
    )
  }

  const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: Array<{ payload: PieDataEntry }> }) => {
    if (!active || !payload || payload.length === 0) return null

    const firstPayload = payload[0]
    if (!firstPayload) return null
    const entry = firstPayload.payload

    return (
      <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3">
        <div className="flex items-center gap-2 mb-1">
          <div
            className="w-3 h-3 rounded-full"
            style={{ backgroundColor: entry.color }}
          />
          <span className="font-medium text-gray-900">{entry.name}</span>
        </div>
        <div className="text-sm text-gray-600">
          <div>{formatEUR(entry.value)}</div>
          <div className="text-xs text-gray-500">{entry.percent.toFixed(1)}% del total</div>
        </div>
      </div>
    )
  }

  const renderLegend = () => {
    return (
      <div className="flex flex-wrap justify-center gap-4 mt-2">
        {data.map((entry) => (
          <div key={entry.key} className="flex items-center gap-1.5">
            <div
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: entry.color }}
            />
            <span className="text-xs text-gray-600">{entry.name}</span>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="w-full">
      {title && (
        <h4 className="text-sm font-medium text-gray-700 mb-2 text-center">{title}</h4>
      )}
      <ResponsiveContainer width="100%" height={heights[size]}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={innerRadius ?? defaultInnerRadii[size]}
            outerRadius={outerRadii[size]}
            paddingAngle={2}
            dataKey="value"
            labelLine={false}
            label={renderCustomLabel}
          >
            {data.map((entry) => (
              <Cell key={entry.key} fill={entry.color} stroke="white" strokeWidth={2} />
            ))}
          </Pie>
          {showTooltip && <Tooltip content={<CustomTooltip />} />}
        </PieChart>
      </ResponsiveContainer>
      {showLegend && renderLegend()}
    </div>
  )
}

/**
 * Compact version for dashboard cards
 */
export function DistributionPieChartCompact({
  distribution,
}: {
  distribution: Record<string, DistributionData | undefined>
}) {
  return (
    <DistributionPieChart
      distribution={distribution}
      size="small"
      showLegend={false}
      innerRadius={35}
    />
  )
}
