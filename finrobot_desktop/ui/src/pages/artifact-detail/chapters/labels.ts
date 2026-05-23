// Single source of truth for chapter labels (number + title + sub).
// Both ReportTOC (left rail) and each Chapter component read from here so
// the chapter index never drifts between sidebar and headers.
//
// Chapter ids match the <section id="..."> on each chapter and the URL hash
// (e.g. /stocks/AAPL/runs/abc#thesis).

import type { Locale } from '../../../i18n'

export interface ChapterLabel {
  /** Two-digit display number, e.g. "01". User-visible — must read 1-12, not 0-11. */
  num: string
  title: string
  sub: string
}

export const CHAPTER_ORDER = [
  'cover',
  'thesis',
  'overview',
  'financial',
  'valuation',
  'news',
  'sensitivity',
  'catalysts',
  'technical',
  'competitive',
  'data',
  'disclaimer',
] as const

export type ChapterId = (typeof CHAPTER_ORDER)[number]

const ZH: Record<ChapterId, Omit<ChapterLabel, 'num'>> = {
  cover: { title: '封面', sub: '研报基本信息' },
  thesis: { title: '投资论点', sub: '评级 · 摘要 · 核心结论' },
  overview: { title: '公司概览', sub: '业务 · 板块 · 地区 · 护城河' },
  financial: { title: '财务分析', sub: '历史回顾与三年预测' },
  valuation: { title: '估值分析', sub: 'Football Field · DCF · Comps · DDM' },
  news: { title: '近期新闻与事件', sub: '事件 · 情绪' },
  sensitivity: { title: '敏感性分析', sub: '关键假设变动' },
  catalysts: { title: '关键催化剂', sub: '正向 · 风险 · 待观察' },
  technical: { title: '技术与高阶分析', sub: '蒙特卡洛 · 狙击位 · 价格走势' },
  competitive: { title: '竞争格局', sub: '同业三视图' },
  data: { title: '财务数据', sub: '原始数据 · 来源 · 审计轨迹' },
  disclaimer: { title: '免责声明', sub: '投资建议提示' },
}

const EN: Record<ChapterId, Omit<ChapterLabel, 'num'>> = {
  cover: { title: 'Cover', sub: 'Report meta' },
  thesis: { title: 'Investment Thesis', sub: 'Recommendation · Tagline · Key Takeaways' },
  overview: { title: 'Company Overview', sub: 'Business · Segments · Geography · Moat' },
  financial: { title: 'Financial Analysis', sub: 'Historical · 3-Year Forecast' },
  valuation: { title: 'Valuation Analysis', sub: 'Football Field · DCF · Comps · DDM' },
  news: { title: 'Recent News & Events', sub: 'Events · Sentiment' },
  sensitivity: { title: 'Sensitivity Analysis', sub: 'Key Assumption Shifts' },
  catalysts: { title: 'Key Catalysts', sub: 'Positive · Risks · Watch' },
  technical: { title: 'Technical & Advanced', sub: 'Monte Carlo · Sniper · Price' },
  competitive: { title: 'Competitive Landscape', sub: 'Peers — 3 views' },
  data: { title: 'Financial Data', sub: 'Raw · Source · Audit Trail' },
  disclaimer: { title: 'Disclaimer', sub: 'Investment Advice Notice' },
}

export function chapterNum(id: ChapterId): string {
  const idx = CHAPTER_ORDER.indexOf(id)
  // Display 01-12 (1-indexed); 0-based is a developer convention not appropriate for users.
  return String(idx + 1).padStart(2, '0')
}

export function chapterLabel(id: ChapterId, locale: Locale): ChapterLabel {
  const table = locale === 'en' ? EN : ZH
  return { num: chapterNum(id), ...table[id] }
}

/** All chapter labels for a given locale — used by ReportTOC. */
export function allChapterLabels(locale: Locale): (ChapterLabel & { id: ChapterId })[] {
  return CHAPTER_ORDER.map((id) => ({ id, ...chapterLabel(id, locale) }))
}
