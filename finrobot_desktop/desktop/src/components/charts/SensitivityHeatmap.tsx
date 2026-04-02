import { useMemo } from 'react'

interface ChartProps {
  data: Record<string, number | string | boolean | null>[]
  title: string
}

/**
 * Interpolate between red and green based on a normalized value [0, 1].
 * 0 → red (#ef4444), 0.5 → yellow (#eab308), 1 → green (#22c55e)
 */
function priceColor(normalised: number): string {
  const clamped = Math.max(0, Math.min(1, normalised))
  if (clamped < 0.5) {
    const t = clamped / 0.5
    const r = Math.round(239 + (234 - 239) * t)
    const g = Math.round(68 + (179 - 68) * t)
    const b = Math.round(68 + (8 - 68) * t)
    return `rgb(${r},${g},${b})`
  }
  const t = (clamped - 0.5) / 0.5
  const r = Math.round(234 + (34 - 234) * t)
  const g = Math.round(179 + (197 - 179) * t)
  const b = Math.round(8 + (94 - 8) * t)
  return `rgb(${r},${g},${b})`
}

interface GridCell {
  wacc: number
  tg: number
  price: number
}

export default function SensitivityHeatmap({ data, title }: ChartProps) {
  if (!data || data.length === 0) return null

  const { waccValues, tgValues, grid, minPrice, maxPrice } = useMemo(() => {
    const cells: GridCell[] = data.map((d) => ({
      wacc: Number(d.wacc),
      tg: Number(d.tg),
      price: Number(d.implied_price),
    }))

    const waccSet = [...new Set(cells.map((c) => c.wacc))].sort((a, b) => a - b)
    const tgSet = [...new Set(cells.map((c) => c.tg))].sort((a, b) => a - b)

    const lookup = new Map<string, number>()
    for (const c of cells) {
      lookup.set(`${c.wacc}_${c.tg}`, c.price)
    }

    const prices = cells.map((c) => c.price)
    return {
      waccValues: waccSet,
      tgValues: tgSet,
      grid: lookup,
      minPrice: Math.min(...prices),
      maxPrice: Math.max(...prices),
    }
  }, [data])

  const range = maxPrice - minPrice || 1

  return (
    <div className="bg-gray-800/50 rounded-lg p-4 border border-gray-700">
      <h4 className="text-sm font-medium text-gray-400 mb-3">{title}</h4>
      <div className="overflow-x-auto">
        <table className="w-full text-xs" role="table">
          <thead>
            <tr>
              <th className="p-1 text-gray-500 text-left">WACC \ TG</th>
              {tgValues.map((tg) => (
                <th key={tg} className="p-1 text-gray-400 text-center">
                  {(tg * 100).toFixed(1)}%
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {waccValues.map((wacc) => (
              <tr key={wacc}>
                <td className="p-1 text-gray-400 font-medium">
                  {(wacc * 100).toFixed(1)}%
                </td>
                {tgValues.map((tg) => {
                  const price = grid.get(`${wacc}_${tg}`)
                  const normalised =
                    price != null ? (price - minPrice) / range : 0.5
                  return (
                    <td
                      key={`${wacc}_${tg}`}
                      className="p-1 text-center font-mono rounded"
                      style={{
                        backgroundColor: priceColor(normalised),
                        color: normalised > 0.6 || normalised < 0.4 ? '#fff' : '#1f2937',
                      }}
                    >
                      {price != null ? `$${price.toFixed(0)}` : '—'}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
