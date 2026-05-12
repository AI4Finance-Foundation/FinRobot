/**
 * Pure deterministic technical indicator computations.
 *
 * These mirror the backend Python implementations in
 * finagent/engine/charts/technical_indicators.py but run client-side
 * so no additional API round-trip is needed.
 */

/** Simple Moving Average. Returns null for indices before the window is full. */
export function sma(data: number[], period: number): (number | null)[] {
  const result: (number | null)[] = new Array(data.length).fill(null)
  if (data.length < period || period <= 0) return result

  let windowSum = 0
  for (let i = 0; i < period; i++) {
    windowSum += data[i]
  }
  result[period - 1] = windowSum / period

  for (let i = period; i < data.length; i++) {
    windowSum += data[i] - data[i - period]
    result[i] = windowSum / period
  }
  return result
}

/** Wilder's RSI (same algorithm as backend _rsi). */
export function rsi(closes: number[], period: number = 14): (number | null)[] {
  const n = closes.length
  const result: (number | null)[] = new Array(n).fill(null)

  if (n < period + 1) return result

  // Price changes
  const deltas: number[] = []
  for (let i = 1; i < n; i++) {
    deltas.push(closes[i] - closes[i - 1])
  }

  const gains = deltas.map((d) => Math.max(d, 0))
  const losses = deltas.map((d) => Math.max(-d, 0))

  // Initial averages over the first `period` changes
  let avgGain = 0
  let avgLoss = 0
  for (let i = 0; i < period; i++) {
    avgGain += gains[i]
    avgLoss += losses[i]
  }
  avgGain /= period
  avgLoss /= period

  if (avgLoss === 0) {
    result[period] = 100
  } else {
    const rs = avgGain / avgLoss
    result[period] = 100 - 100 / (1 + rs)
  }

  // Wilder smoothing
  for (let i = period; i < deltas.length; i++) {
    avgGain = (avgGain * (period - 1) + gains[i]) / period
    avgLoss = (avgLoss * (period - 1) + losses[i]) / period
    if (avgLoss === 0) {
      result[i + 1] = 100
    } else {
      const rs = avgGain / avgLoss
      result[i + 1] = 100 - 100 / (1 + rs)
    }
  }

  return result
}

export interface BollingerPoint {
  upper: number | null
  lower: number | null
  middle: number | null
}

/** Bollinger Bands (same rolling sum/sum-of-squares as backend _bollinger). */
export function bollingerBands(
  closes: number[],
  period: number = 20,
  stdDev: number = 2,
): BollingerPoint[] {
  const n = closes.length
  const result: BollingerPoint[] = new Array(n)
    .fill(null)
    .map(() => ({ upper: null, lower: null, middle: null }))

  if (n < period) return result

  let windowSum = 0
  let windowSqSum = 0
  for (let i = 0; i < period; i++) {
    windowSum += closes[i]
    windowSqSum += closes[i] * closes[i]
  }

  for (let i = period - 1; i < n; i++) {
    if (i > period - 1) {
      const outgoing = closes[i - period]
      const incoming = closes[i]
      windowSum += incoming - outgoing
      windowSqSum += incoming * incoming - outgoing * outgoing
    }
    const mean = windowSum / period
    const variance = windowSqSum / period - mean * mean
    const std = variance > 0 ? Math.sqrt(variance) : 0
    result[i] = {
      middle: mean,
      upper: mean + stdDev * std,
      lower: mean - stdDev * std,
    }
  }

  return result
}
