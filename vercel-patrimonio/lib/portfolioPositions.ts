// Posiciones reales con costes de adquisición para tracking P&L
// Actualizado: 14 Enero 2026

export type Position = {
  id: string
  ticker: string
  isin?: string
  nombre: string
  broker: 'Indexa' | 'Bankinter' | 'Andbank' | 'GDAF' | 'Varios'
  categoria: 'RV' | 'RF' | 'Oro' | 'Cripto' | 'Liquidez' | 'Commodities' | 'Nuclear'

  // Datos de compra
  shares: number // participaciones/títulos
  avgCost: number // coste medio por participación
  totalCost: number // coste total
  fechaCompra: string

  // Datos actuales (se actualizarán con API)
  currentPrice?: number
  currentValue?: number
  pnl?: number
  pnlPct?: number

  // Histórico
  ytdReturn?: number // Return Year-to-Date
  allTimeHigh?: number
  allTimeLow?: number

  // Metadata
  currency: 'EUR' | 'USD'
  type: 'ETF' | 'Fondo' | 'Acción' | 'Commodity' | 'Cripto' | 'Cash'
  region?: string
  sector?: string
}

// ═══════════════════════════════════════════════════════════════════════════
// INDEXA CAPITAL - POSICIONES REALES (14-Ene-2026)
// ═══════════════════════════════════════════════════════════════════════════

export const INDEXA_POSITIONS: Position[] = [
  // RENTA VARIABLE (€135,515 - 61.7%)
  {
    id: 'indexa_us500',
    ticker: 'VUSA',
    isin: 'IE00BFPM9V94',
    nombre: 'Vanguard US 500 Stk Idx EUR - Ins Plus',
    broker: 'Indexa',
    categoria: 'RV',
    shares: 110.0,
    avgCost: 524.40,
    totalCost: 57684,
    currentPrice: 524.26,
    currentValue: 57668.64,
    fechaCompra: '2020-01-01',
    currency: 'EUR',
    type: 'Fondo',
    region: 'USA',
    sector: 'Large Cap'
  },
  {
    id: 'indexa_europe',
    ticker: 'VEUR',
    isin: 'IE00BFPM9L96',
    nombre: 'Vanguard European Stk Idx EUR - Ins Plus',
    broker: 'Indexa',
    categoria: 'RV',
    shares: 129.7,
    avgCost: 266.81,
    totalCost: 34605,
    currentPrice: 266.85,
    currentValue: 34610.74,
    fechaCompra: '2020-01-01',
    currency: 'EUR',
    type: 'Fondo',
    region: 'Europa',
    sector: 'Broad Market'
  },
  {
    id: 'indexa_em',
    ticker: 'VFEM',
    isin: 'IE00BFPM9J74',
    nombre: 'Vanguard Emrg Mk Stk Idx EUR - Ins Plus',
    broker: 'Indexa',
    categoria: 'RV',
    shares: 62.0,
    avgCost: 224.17,
    totalCost: 13899,
    currentPrice: 224.14,
    currentValue: 13896.54,
    fechaCompra: '2020-01-01',
    currency: 'EUR',
    type: 'Fondo',
    region: 'Emergentes',
    sector: 'Broad Market'
  },
  {
    id: 'indexa_smallcap',
    ticker: 'VWSC',
    isin: 'IE00BFRTDD83',
    nombre: 'Vanguard Global Small Cap Idx EUR - Ins Plus',
    broker: 'Indexa',
    categoria: 'RV',
    shares: 42.2,
    avgCost: 313.23,
    totalCost: 13218,
    currentPrice: 313.01,
    currentValue: 13208.88,
    fechaCompra: '2020-01-01',
    currency: 'EUR',
    type: 'Fondo',
    region: 'Global',
    sector: 'Small Cap'
  },
  {
    id: 'indexa_japan',
    ticker: 'VJPN',
    isin: 'IE00BFPM9P35',
    nombre: 'Vanguard Japan Stk Idx EUR - Ins Plus',
    broker: 'Indexa',
    categoria: 'RV',
    shares: 41.5,
    avgCost: 273.10,
    totalCost: 11334,
    currentPrice: 273.23,
    currentValue: 11339.18,
    fechaCompra: '2020-01-01',
    currency: 'EUR',
    type: 'Fondo',
    region: 'Japón',
    sector: 'Broad Market'
  },
  {
    id: 'indexa_pacific',
    ticker: 'VPAC',
    isin: 'IE00BGCC5G60',
    nombre: 'Vanguard Pacific Ex-Japan Stk Idx EUR - Ins Plus',
    broker: 'Indexa',
    categoria: 'RV',
    shares: 22.3,
    avgCost: 215.05,
    totalCost: 4796,
    currentPrice: 214.86,
    currentValue: 4791.37,
    fechaCompra: '2020-01-01',
    currency: 'EUR',
    type: 'Fondo',
    region: 'Asia-Pacífico',
    sector: 'Broad Market'
  },

  // RENTA FIJA (€84,225 - 38.3%)
  {
    id: 'indexa_goveur',
    ticker: 'VGOV',
    isin: 'IE00BFPM9W02',
    nombre: 'Vanguard Eur Gov Bnd Idx - Ins Plus',
    broker: 'Indexa',
    categoria: 'RF',
    shares: 192.4,
    avgCost: 114.94,
    totalCost: 22114,
    currentPrice: 114.94,
    currentValue: 22113.73,
    fechaCompra: '2020-01-01',
    currency: 'EUR',
    type: 'Fondo',
    sector: 'Gov Bonds EUR'
  },
  {
    id: 'indexa_govusd',
    ticker: 'VUSG',
    isin: 'IE00BF6T7R10',
    nombre: 'Vanguard US Gov Bnd Idx EUR Hdg - Ins Plus',
    broker: 'Indexa',
    categoria: 'RF',
    shares: 224.4,
    avgCost: 93.29,
    totalCost: 20930,
    currentPrice: 93.30,
    currentValue: 20936.70,
    fechaCompra: '2020-01-01',
    currency: 'EUR',
    type: 'Fondo',
    sector: 'Gov Bonds USA'
  },
  {
    id: 'indexa_corpeur',
    ticker: 'VCOR',
    isin: 'IE00BFPM9X19',
    nombre: 'Vanguard Euro Inv Gr Bnd Idx EUR - Ins Plus',
    broker: 'Indexa',
    categoria: 'RF',
    shares: 136.8,
    avgCost: 116.92,
    totalCost: 15995,
    currentPrice: 116.93,
    currentValue: 15996.48,
    fechaCompra: '2020-01-01',
    currency: 'EUR',
    type: 'Fondo',
    sector: 'Corp Bonds EUR'
  },
  {
    id: 'indexa_corpusd',
    ticker: 'VUSC',
    isin: 'IE00BZ04LQ92',
    nombre: 'Vanguard US Inv Gr Bnd Idx EUR Hdg - Ins Plus',
    broker: 'Indexa',
    categoria: 'RF',
    shares: 113.6,
    avgCost: 110.20,
    totalCost: 12519,
    currentPrice: 110.20,
    currentValue: 12518.29,
    fechaCompra: '2020-01-01',
    currency: 'EUR',
    type: 'Fondo',
    sector: 'Corp Bonds USA'
  },
  {
    id: 'indexa_inflation',
    ticker: 'VINF',
    isin: 'IE00BGCZ0Z19',
    nombre: 'Vanguard Euroz Infl Lk Bnd Idx EUR - Ins Plus',
    broker: 'Indexa',
    categoria: 'RF',
    shares: 64.4,
    avgCost: 130.36,
    totalCost: 8395,
    currentPrice: 130.30,
    currentValue: 8391.21,
    fechaCompra: '2020-01-01',
    currency: 'EUR',
    type: 'Fondo',
    sector: 'Inflation Linked'
  },
  {
    id: 'indexa_emgov',
    ticker: 'IEAG',
    isin: 'IE0000J01ZR0',
    nombre: 'iShares Emrg Mk Gov Bnd Idx EUR - Class D',
    broker: 'Indexa',
    categoria: 'RF',
    shares: 368.0,
    avgCost: 11.60,
    totalCost: 4269,
    currentPrice: 11.60,
    currentValue: 4268.26,
    fechaCompra: '2020-01-01',
    currency: 'EUR',
    type: 'Fondo',
    sector: 'EM Gov Bonds'
  }
]

// ═══════════════════════════════════════════════════════════════════════════
// ANDBANK - POSICIONES REALES (14-Ene-2026)
// ═══════════════════════════════════════════════════════════════════════════

export const ANDBANK_POSITIONS: Position[] = [
  {
    id: 'andbank_wf',
    ticker: 'WFECTR',
    isin: 'LU1164219682',
    nombre: 'WF Euro Credit Total Return',
    broker: 'Andbank',
    categoria: 'RF',
    shares: 1135.71,
    avgCost: 141.58,
    totalCost: 160794,
    currentPrice: 151.94,
    currentValue: 172559.63,
    fechaCompra: '2022-01-01',
    currency: 'EUR',
    type: 'Fondo',
    sector: 'Corp Bonds EUR'
  },
  {
    id: 'andbank_myinvestor',
    ticker: 'MYSP500',
    isin: 'ES0165242001',
    nombre: 'MyInvestor S&P500 Equiponderado',
    broker: 'Andbank',
    categoria: 'RV',
    shares: 41433.24,
    avgCost: 1.207,
    totalCost: 50000,
    currentPrice: 1.31,
    currentValue: 54175.20,
    fechaCompra: '2024-01-01',
    currency: 'EUR',
    type: 'Fondo',
    region: 'USA',
    sector: 'Equal Weight'
  },
  {
    id: 'andbank_lly',
    ticker: 'LLY',
    isin: 'US5324571083',
    nombre: 'Eli Lilly & Co',
    broker: 'Andbank',
    categoria: 'RV',
    shares: 22,
    avgCost: 925.50,
    totalCost: 20361,
    currentPrice: 918.50,
    currentValue: 20207.00,
    fechaCompra: '2026-01-14',
    currency: 'EUR',
    type: 'Acción',
    region: 'USA',
    sector: 'Farmacéutico/GLP-1'
  },
  {
    id: 'andbank_ceg',
    ticker: 'CEG',
    isin: 'US21037T1097',
    nombre: 'Constellation Energy',
    broker: 'Andbank',
    categoria: 'Nuclear',
    shares: 71,
    avgCost: 330.94,
    totalCost: 23496,
    currentPrice: 280.82,
    currentValue: 19938.44,
    fechaCompra: '2026-01-14',
    currency: 'USD',
    type: 'Acción',
    region: 'USA',
    sector: 'Nuclear/Energía'
  },
  {
    id: 'andbank_gev',
    ticker: 'GEV',
    isin: 'US36828A1016',
    nombre: 'GE Vernova LLC',
    broker: 'Andbank',
    categoria: 'Nuclear',
    shares: 19,
    avgCost: 651.31,
    totalCost: 12375,
    currentPrice: 548.53,
    currentValue: 10422.02,
    fechaCompra: '2026-01-14',
    currency: 'USD',
    type: 'Acción',
    region: 'USA',
    sector: 'Nuclear/Energía'
  },
  {
    id: 'andbank_cspx',
    ticker: 'CSPX',
    isin: 'IE00B5BMR087',
    nombre: 'iShares Core S&P 500',
    broker: 'Andbank',
    categoria: 'RV',
    shares: 100,
    avgCost: 637.45,
    totalCost: 63745,
    currentPrice: 635.10,
    currentValue: 63510.00,
    fechaCompra: '2026-01-14',
    currency: 'EUR',
    type: 'ETF',
    region: 'USA',
    sector: 'S&P 500'
  },
  {
    id: 'andbank_ihe',
    ticker: 'IHE',
    isin: 'IE00B43HR379',
    nombre: 'iShares S&P Healthcare',
    broker: 'Andbank',
    categoria: 'RV',
    shares: 2000,
    avgCost: 10.854,
    totalCost: 21708,
    currentPrice: 10.804,
    currentValue: 21608.00,
    fechaCompra: '2026-01-14',
    currency: 'EUR',
    type: 'ETF',
    region: 'USA',
    sector: 'Salud'
  },
  {
    id: 'andbank_dfen',
    ticker: 'DFEN',
    isin: 'IE000YYE6WK5',
    nombre: 'VanEck Defense ETF',
    broker: 'Andbank',
    categoria: 'RV',
    shares: 200,
    avgCost: 62.40,
    totalCost: 12480,
    currentPrice: 62.31,
    currentValue: 12462.00,
    fechaCompra: '2026-01-14',
    currency: 'EUR',
    type: 'ETF',
    region: 'Global',
    sector: 'Defensa'
  }
]

// ═══════════════════════════════════════════════════════════════════════════
// BANKINTER - POSICIONES REALES (14-Ene-2026)
// ═══════════════════════════════════════════════════════════════════════════

export const BANKINTER_POSITIONS: Position[] = [
  {
    id: 'bankinter_brkb',
    ticker: 'BRK.B',
    isin: 'US0846707026',
    nombre: 'Berkshire Hathaway Inc-CL B',
    broker: 'Bankinter',
    categoria: 'RV',
    shares: 20,
    avgCost: 470.60,
    totalCost: 9412,
    currentPrice: 479.10,
    currentValue: 9582.00,
    fechaCompra: '2024-12-09',
    currency: 'USD',
    type: 'Acción',
    region: 'USA',
    sector: 'Conglomerado'
  },
  {
    id: 'bankinter_gldm',
    ticker: 'GLDM',
    isin: 'LU2611731824',
    nombre: 'Amundi NYSE Arca Gold BUGS',
    broker: 'Bankinter',
    categoria: 'Oro',
    shares: 400,
    avgCost: 28.00,
    totalCost: 11200,
    currentPrice: 67.06,
    currentValue: 26822.40,
    fechaCompra: '2024-12-09',
    currency: 'EUR',
    type: 'ETF',
    sector: 'Oro/Mineras'
  },
  {
    id: 'bankinter_exxy',
    ticker: 'EXXY',
    isin: 'DE000A0H0728',
    nombre: 'iShares Diversified Commodity Swap',
    broker: 'Bankinter',
    categoria: 'Commodities',
    shares: 120,
    avgCost: 27.26,
    totalCost: 3271,
    currentPrice: 28.32,
    currentValue: 3398.40,
    fechaCompra: '2026-01-05',
    currency: 'EUR',
    type: 'ETF',
    sector: 'Commodities'
  },
  {
    id: 'bankinter_is3v',
    ticker: 'IS3V',
    isin: 'IE00BKPT2S34',
    nombre: 'iShares Global Inflation Linked Govt Bond',
    broker: 'Bankinter',
    categoria: 'RF',
    shares: 2208,
    avgCost: 4.53,
    totalCost: 10002,
    currentPrice: 4.59,
    currentValue: 10134.72,
    fechaCompra: '2026-01-05',
    currency: 'EUR',
    type: 'ETF',
    sector: 'Inflation Bonds'
  },
  {
    id: 'bankinter_is0e',
    ticker: 'IS0E',
    isin: 'IE00B6R52Q36',
    nombre: 'iShares Gold Producers',
    broker: 'Bankinter',
    categoria: 'Oro',
    shares: 270,
    avgCost: 34.345,
    totalCost: 9273,
    currentPrice: 37.88,
    currentValue: 10227.60,
    fechaCompra: '2026-01-05',
    currency: 'EUR',
    type: 'ETF',
    sector: 'Oro/Mineras'
  },
  {
    id: 'bankinter_nukl',
    ticker: 'NUKL',
    isin: 'IE000M7V94E1',
    nombre: 'VanEck Uranium and Nuclear Technologies',
    broker: 'Bankinter',
    categoria: 'Nuclear',
    shares: 100,
    avgCost: 49.97,
    totalCost: 4997,
    currentPrice: 49.97,
    currentValue: 4997.00,
    fechaCompra: '2026-01-05',
    currency: 'EUR',
    type: 'ETF',
    sector: 'Nuclear/Uranio'
  }
]

// ═══════════════════════════════════════════════════════════════════════════
// CRIPTO Y LIQUIDEZ
// ═══════════════════════════════════════════════════════════════════════════

export const OTHER_POSITIONS: Position[] = [
  {
    id: 'cripto_gdaf',
    ticker: 'CRYPTO',
    isin: undefined,
    nombre: 'GDAF Cripto (BTC/ETH)',
    broker: 'GDAF',
    categoria: 'Cripto',
    shares: 1,
    avgCost: 205000,
    totalCost: 205000,
    currentPrice: 97321,
    currentValue: 97321,
    fechaCompra: '2023-04-01',
    currency: 'EUR',
    type: 'Cripto',
    sector: 'Cripto'
  },
  {
    id: 'liquidez',
    ticker: 'CASH',
    isin: undefined,
    nombre: 'Liquidez (113,732 + 75,000)',
    broker: 'Varios',
    categoria: 'Liquidez',
    shares: 1,
    avgCost: 188732,
    totalCost: 188732,
    currentPrice: 188732,
    currentValue: 188732,
    fechaCompra: '2026-01-14',
    currency: 'EUR',
    type: 'Cash',
    sector: 'Liquidez'
  }
]

// ═══════════════════════════════════════════════════════════════════════════
// CONSOLIDADO
// ═══════════════════════════════════════════════════════════════════════════

export const ALL_POSITIONS: Position[] = [
  ...INDEXA_POSITIONS,
  ...ANDBANK_POSITIONS,
  ...BANKINTER_POSITIONS,
  ...OTHER_POSITIONS
]

// Funciones auxiliares
export function calculatePnL(position: Position): {
  pnl: number
  pnlPct: number
  currentValue: number
} {
  const currentPrice = position.currentPrice || position.avgCost
  const currentValue = position.shares * currentPrice
  const pnl = currentValue - position.totalCost
  const pnlPct = (pnl / position.totalCost) * 100

  return { pnl, pnlPct, currentValue }
}

export function getTotalPnL(positions: Position[]): {
  totalCost: number
  totalValue: number
  totalPnL: number
  totalPnLPct: number
} {
  const totalCost = positions.reduce((sum, p) => sum + p.totalCost, 0)
  const totalValue = positions.reduce((sum, p) => {
    const price = p.currentPrice || p.avgCost
    return sum + (p.shares * price)
  }, 0)
  const totalPnL = totalValue - totalCost
  const totalPnLPct = (totalPnL / totalCost) * 100

  return { totalCost, totalValue, totalPnL, totalPnLPct }
}

export function getPositionsByCategory(categoria: string): Position[] {
  return ALL_POSITIONS.filter(p => p.categoria === categoria)
}

export function getPositionsByBroker(broker: string): Position[] {
  return ALL_POSITIONS.filter(p => p.broker === broker)
}

// Mapeo de tickers para APIs externas
export const TICKER_MAP: Record<string, string> = {
  // Indexa (usar proxies cotizados)
  'VUSA': 'VUSA.L',
  'VEUR': 'VEUR.L',
  'VFEM': 'VFEM.L',
  'VWSC': 'VWSC.L',
  'VJPN': 'EWJ',

  // Andbank
  'LLY': 'LLY',
  'CEG': 'CEG',
  'GEV': 'GEV',
  'CSPX': 'CSPX.L',
  'IHE': 'IXJ',
  'DFEN': 'ITA',

  // Bankinter
  'BRK.B': 'BRK-B',
  'GLDM': 'GDX',
  'EXXY': 'DJP',
  'IS3V': 'TIP',
  'IS0E': 'GDX',
  'NUKL': 'URA',

  // Cripto
  'CRYPTO': 'BTC-EUR',
}

// Resumen por broker
export const BROKER_SUMMARY = {
  INDEXA: {
    total: 219740.02,
    rv: 135515.35,
    rf: 84224.67
  },
  ANDBANK: {
    total: 374882.29,
    rv: 202402.66,
    rf: 172559.63
  },
  BANKINTER: {
    total: 65162.12,
    oro: 37050.00,
    rf: 10134.72,
    rv: 9582.00,
    commodities: 3398.40,
    nuclear: 4997.00
  },
  OTROS: {
    cripto: 97321.00,
    liquidez: 188732.00
  }
}

// TOTAL PATRIMONIO SALVADOR: €945,837.43
