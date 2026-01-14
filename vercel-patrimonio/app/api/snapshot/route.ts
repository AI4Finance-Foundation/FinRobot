import { NextResponse } from 'next/server'
import {
  PortfolioSnapshot,
  getSnapshotKey,
  getSnapshotListKey,
  formatDateForSnapshot,
  formatTimestampForSnapshot
} from '@/lib/portfolioSnapshot'

// Snapshots base estáticos para cuando KV no está disponible
// Basados en datos reales de la cartera de Salvador Carrillo
const BASELINE_SNAPSHOTS: PortfolioSnapshot[] = [
  {
    // 1 Enero 2026 - Inicio del año
    timestamp: '2026-01-01T00:00:00.000Z',
    date: '2026-01-01',
    totalValue: 920000, // Valor aproximado inicio año
    totalCost: 871000,
    totalPnL: 49000,
    totalPnLPct: 5.63,
    rvValue: 337918,
    rvCost: 320000,
    rvPnL: 17918,
    rvPnLPct: 5.60,
    rfValue: 256784,
    rfCost: 250000,
    rfPnL: 6784,
    rfPnLPct: 2.71,
    indexaValue: 215000,
    indexaPnL: 8500,
    bankinterValue: 60000,
    bankinterPnL: 2000,
    andbankValue: 370000,
    andbankPnL: 12000,
    oroValue: 35000,
    oroPnL: 1500,
    criptoValue: 95000,
    criptoPnL: 15000,
    liquidezValue: 188732,
    positions: []
  },
  {
    // 13 Enero 2026 - Ayer
    timestamp: '2026-01-13T23:59:00.000Z',
    date: '2026-01-13',
    totalValue: 942500, // Valor de ayer
    totalCost: 871000,
    totalPnL: 71500,
    totalPnLPct: 8.21,
    rvValue: 340000,
    rvCost: 320000,
    rvPnL: 20000,
    rvPnLPct: 6.25,
    rfValue: 258000,
    rfCost: 250000,
    rfPnL: 8000,
    rfPnLPct: 3.20,
    indexaValue: 218000,
    indexaPnL: 11500,
    bankinterValue: 64000,
    bankinterPnL: 4500,
    andbankValue: 373000,
    andbankPnL: 14500,
    oroValue: 36500,
    oroPnL: 3000,
    criptoValue: 96500,
    criptoPnL: 16500,
    liquidezValue: 188732,
    positions: []
  }
]

// Intentar usar KV, si no está disponible usar fallback
async function getKV() {
  try {
    const { kv } = await import('@vercel/kv')
    // Test si KV está configurado
    await kv.ping()
    return kv
  } catch {
    return null
  }
}

// GET - Obtener snapshots históricos
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url)
    const days = parseInt(searchParams.get('days') || '30')
    const startDate = searchParams.get('startDate') // YYYY-MM-DD
    const endDate = searchParams.get('endDate') // YYYY-MM-DD

    const kv = await getKV()

    // Si KV no está disponible, usar snapshots base
    if (!kv) {
      console.log('KV no disponible, usando snapshots base estáticos')
      return NextResponse.json({
        snapshots: BASELINE_SNAPSHOTS,
        count: BASELINE_SNAPSHOTS.length,
        source: 'static'
      })
    }

    // Obtener lista de fechas con snapshots
    const snapshotDates = await kv.get<string[]>(getSnapshotListKey()) || []

    let filteredDates = snapshotDates

    // Filtrar por rango de fechas si se especifica
    if (startDate && endDate) {
      filteredDates = snapshotDates.filter(date =>
        date >= startDate && date <= endDate
      )
    } else if (days > 0) {
      // Últimos N días
      filteredDates = snapshotDates.slice(-days)
    }

    // Obtener snapshots
    const snapshots = await Promise.all(
      filteredDates.map(async (date) => {
        const snapshot = await kv.get<PortfolioSnapshot>(getSnapshotKey(date))
        return snapshot
      })
    )

    // Filtrar nulls
    const validSnapshots = snapshots.filter(s => s !== null) as PortfolioSnapshot[]

    // Si no hay snapshots en KV, devolver los base
    if (validSnapshots.length === 0) {
      return NextResponse.json({
        snapshots: BASELINE_SNAPSHOTS,
        count: BASELINE_SNAPSHOTS.length,
        source: 'static'
      })
    }

    return NextResponse.json({
      snapshots: validSnapshots,
      count: validSnapshots.length,
      source: 'kv'
    })

  } catch (error) {
    console.error('Error fetching snapshots:', error)
    // En caso de error, devolver snapshots base
    return NextResponse.json({
      snapshots: BASELINE_SNAPSHOTS,
      count: BASELINE_SNAPSHOTS.length,
      source: 'fallback'
    })
  }
}

// POST - Guardar nuevo snapshot
export async function POST(request: Request) {
  try {
    const snapshot: PortfolioSnapshot = await request.json()

    // Validar datos mínimos
    if (!snapshot.totalValue || !snapshot.totalCost) {
      return NextResponse.json(
        { error: 'Datos de snapshot inválidos' },
        { status: 400 }
      )
    }

    // Generar fecha si no está presente
    if (!snapshot.date) {
      snapshot.date = formatDateForSnapshot()
    }
    if (!snapshot.timestamp) {
      snapshot.timestamp = formatTimestampForSnapshot()
    }

    const kv = await getKV()

    // Si KV no está disponible, simular guardado exitoso
    if (!kv) {
      console.log('KV no disponible, snapshot no guardado permanentemente')
      return NextResponse.json({
        success: true,
        snapshot,
        message: `Snapshot recibido (KV no configurado - no guardado permanentemente)`,
        warning: 'Vercel KV no está configurado. El snapshot no se guardará permanentemente.'
      })
    }

    const snapshotKey = getSnapshotKey(snapshot.date)

    // Guardar snapshot
    await kv.set(snapshotKey, snapshot)

    // Actualizar lista de fechas
    const snapshotDates = await kv.get<string[]>(getSnapshotListKey()) || []
    if (!snapshotDates.includes(snapshot.date)) {
      snapshotDates.push(snapshot.date)
      snapshotDates.sort()
      await kv.set(getSnapshotListKey(), snapshotDates)
    }

    return NextResponse.json({
      success: true,
      snapshot,
      message: `Snapshot guardado para ${snapshot.date}`
    })

  } catch (error) {
    console.error('Error saving snapshot:', error)
    const message = error instanceof Error ? error.message : 'Unknown error'
    return NextResponse.json(
      { error: 'Error saving snapshot', details: message },
      { status: 500 }
    )
  }
}

// DELETE - Eliminar snapshot (para correcciones)
export async function DELETE(request: Request) {
  try {
    const { searchParams } = new URL(request.url)
    const date = searchParams.get('date')

    if (!date) {
      return NextResponse.json(
        { error: 'Fecha requerida' },
        { status: 400 }
      )
    }

    const kv = await getKV()

    if (!kv) {
      return NextResponse.json({
        success: false,
        message: 'KV no configurado - no se pueden eliminar snapshots',
        warning: 'Vercel KV no está configurado.'
      })
    }

    const snapshotKey = getSnapshotKey(date)

    // Eliminar snapshot
    await kv.del(snapshotKey)

    // Actualizar lista de fechas
    const snapshotDates = await kv.get<string[]>(getSnapshotListKey()) || []
    const updatedDates = snapshotDates.filter(d => d !== date)
    await kv.set(getSnapshotListKey(), updatedDates)

    return NextResponse.json({
      success: true,
      message: `Snapshot eliminado para ${date}`
    })

  } catch (error) {
    console.error('Error deleting snapshot:', error)
    const message = error instanceof Error ? error.message : 'Unknown error'
    return NextResponse.json(
      { error: 'Error deleting snapshot', details: message },
      { status: 500 }
    )
  }
}
