// Section directory — the spec §3.3 ticker-workspace section map.
//
// Previously hard-coded inside AnchorNav.tsx (now retired in Stage A).
// Lifted out so CmdKOverlay's section-jump panel and any future TOC
// surface share the same source of truth.

export interface SectionGroup {
  label: string
  items: { id: string; label: string }[]
}

export const STOCK_WORKSPACE_SECTIONS: SectionGroup[] = [
  {
    label: '总览',
    items: [
      { id: 'sec-now', label: '当前判断' },
      { id: 'sec-score', label: '综合评分' },
      { id: 'sec-catalyst', label: '催化剂' },
      { id: 'sec-risk', label: '风险' },
    ],
  },
  {
    label: '估值',
    items: [
      { id: 'sec-football', label: '估值范围' },
      { id: 'sec-sensitivity', label: '敏感性' },
      { id: 'sec-band', label: '历史估值带' },
      { id: 'sec-monte-carlo', label: '蒙特卡洛' },
    ],
  },
  {
    label: '数据',
    items: [
      { id: 'sec-data', label: '快照' },
      { id: 'sec-price', label: '股价走势' },
      { id: 'sec-revenue', label: '营收 / EBITDA' },
      { id: 'sec-margins', label: '利润率' },
      { id: 'sec-cashflow', label: '现金流' },
      { id: 'sec-financials', label: '季度财务' },
      { id: 'sec-performance', label: '走势统计' },
    ],
  },
  {
    label: '市场',
    items: [
      { id: 'sec-peers', label: '同业表' },
      { id: 'sec-peer-radar', label: '同业雷达' },
      { id: 'sec-peer-bars', label: '同业倍数' },
      { id: 'sec-sniper', label: '阻力支撑' },
      { id: 'sec-news', label: '新闻' },
      { id: 'sec-sentiment', label: '散户情绪' },
      { id: 'sec-earnings', label: '财报会' },
    ],
  },
  {
    label: '我的',
    items: [{ id: 'sec-research', label: '我的研究' }],
  },
]

/** Flat list with stable order, useful for hotkey 1..9 binding. */
export const FLAT_SECTIONS = STOCK_WORKSPACE_SECTIONS.flatMap((g) =>
  g.items.map((i) => ({ ...i, group: g.label })),
)
