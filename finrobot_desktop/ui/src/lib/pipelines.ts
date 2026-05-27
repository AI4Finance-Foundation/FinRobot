// Single source of truth for hardcoded pipeline metadata.
// Dashboard and Explorer both import from here — never duplicate this data.
//
// Financial numbers (runs count) here are UI-chrome run counts, not
// financial data — they come from pipeline run tracking (Phase 5 TODO).
// placeholder, not for production

export type PipelineCategory = 'stock' | 'sector' | 'event' | 'portfolio' | 'batch'

export interface Pipeline {
  id: string
  name: string
  desc: string
  source: string
  time: string
  runs: number
  category: PipelineCategory
}

export const PIPELINES: readonly Pipeline[] = [
  {
    id: 'PL-001',
    name: '个股深度分析',
    desc: '财报 · 估值 · 情绪',
    source: '12 章研报',
    time: '~ 42s',
    runs: 128,
    category: 'stock',
  },
  {
    id: 'PL-002',
    name: '财报速读',
    desc: '10-K / 季报解析',
    source: 'EDGAR',
    time: '~ 28s',
    runs: 94,
    category: 'stock',
  },
  {
    id: 'PL-003',
    name: '行业轮动监测',
    desc: '板块情绪热力',
    source: 'Realtime',
    time: '~ 35s',
    runs: 61,
    category: 'sector',
  },
  {
    id: 'PL-004',
    name: '事件驱动扫描',
    desc: '公告 / 政策 / 突发',
    source: '24/7',
    time: '~ 18s',
    runs: 203,
    category: 'event',
  },
  {
    id: 'PL-005',
    name: '投资组合诊断',
    desc: '归因 / 风险敞口',
    source: '本地',
    time: '~ 56s',
    runs: 12,
    category: 'portfolio',
  },
  {
    id: 'PL-006',
    name: '研报批处理',
    desc: '批量导出 PDF',
    source: '本地',
    time: '~ 2m',
    runs: 7,
    category: 'batch',
  },
] as const

export function getPipeline(id: string): Pipeline | undefined {
  return PIPELINES.find((p) => p.id === id)
}

/** Map pipeline id to backend pipeline_type string for StocksPage. */
export function pipelineIdToType(id: string): 'research' | 'earnings' {
  if (id === 'PL-002') return 'earnings'
  return 'research'
}
