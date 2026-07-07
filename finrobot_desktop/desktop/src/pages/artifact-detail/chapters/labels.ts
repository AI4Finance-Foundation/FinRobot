// Single source of truth for chapter labels (number + title + sub).
// Both ReportLeftRail (left rail) and each Chapter component read from here so
// the chapter index never drifts between sidebar and headers.
//
// Chapter ids match the <section id="..."> on each chapter and the URL hash
// (e.g. /stocks/AAPL/runs/abc#thesis).

import type { Locale } from '../../../i18n'

export interface ChapterLabel {
  /** Two-digit display number, e.g. "01". User-visible — must read 1-13, not 0-12. */
  num: string
  title: string
  sub: string
}

// Reading order is importance- and dependency-driven (2026-06): the thesis leads
// (conclusion-first), then the company (overview) and WHERE it competes
// (competitive) frame how to read the numbers — so the valuation case is built up
// (financial → valuation) and stress-tested immediately (sensitivity), then the
// recent event record (news — itemized, sourced) and its aggregate signal read
// (catalysts — net direction + category mix, no re-listing), the quant deep-dive
// (technical), and finally the appendix (data → ownership → disclaimer).
//
// ⚠ This array drives ONLY the numbering (chapterNum) + left-rail nav order. The
// actual VISUAL render order is the hardcoded JSX sequence in ReportChapters.tsx —
// reorder BOTH in lockstep, or the chapter numbers/nav will disagree with the page.
export const CHAPTER_ORDER = [
  'cover',
  'thesis',
  'overview',
  'competitive',
  'financial',
  'valuation',
  'sensitivity',
  'news',
  'catalysts',
  'technical',
  'data',
  'ownership',
  'disclaimer',
] as const

export type ChapterId = (typeof CHAPTER_ORDER)[number]

const ZH: Record<ChapterId, Omit<ChapterLabel, 'num'>> = {
  cover: { title: '封面', sub: '研报基本信息' },
  thesis: { title: '投资论点', sub: '多空论证 · 估值依据 · 市场隐含' },
  overview: { title: '公司概览', sub: '板块 · 行业 · 规模 · 盈利质量' },
  financial: { title: '财务分析', sub: '历史回顾与三年预测' },
  // 不在副标列举方法名——实际渲染的方法行按票动态取舍(KO 无 DDM/LBO 行,
  // 静态列举必然漂移,外审当成"标题承诺正文没有"挑掉,2026-07-07)。
  valuation: { title: '估值分析', sub: 'Football Field · 多方法三角互证' },
  news: { title: '近期新闻与事件', sub: '事件 · 情绪' },
  sensitivity: { title: '敏感性分析', sub: '关键假设变动' },
  catalysts: { title: '催化剂信号', sub: '方向判读 · 类别构成' },
  technical: { title: '技术分析', sub: '蒙特卡洛 · 交易点位 · 价格走势' },
  competitive: { title: '竞争格局', sub: '同业三视图' },
  data: { title: '财务数据', sub: '原始数据 · 来源 · 审计轨迹' },
  ownership: { title: '股权与治理', sub: '内部人交易 · 机构持仓 · 高管薪酬' },
  disclaimer: { title: '免责声明', sub: '投资建议提示' },
}

const EN: Record<ChapterId, Omit<ChapterLabel, 'num'>> = {
  cover: { title: 'Cover', sub: 'Report meta' },
  thesis: { title: 'Investment Thesis', sub: 'Bull / Bear · Valuation Bridge · Market-Implied' },
  overview: { title: 'Company Overview', sub: 'Sector · Industry · Scale · Profitability' },
  financial: { title: 'Financial Analysis', sub: 'Historical · 3-Year Forecast' },
  valuation: { title: 'Valuation Analysis', sub: 'Football Field · Method Triangulation' },
  news: { title: 'Recent News & Events', sub: 'Events · Sentiment' },
  sensitivity: { title: 'Sensitivity Analysis', sub: 'Key Assumption Shifts' },
  catalysts: { title: 'Catalyst Signal', sub: 'Directional Read · Category Mix' },
  technical: { title: 'Technical Analysis', sub: 'Monte Carlo · Trade Levels · Price' },
  competitive: { title: 'Competitive Landscape', sub: 'Peers — 3 views' },
  data: { title: 'Financial Data', sub: 'Raw · Source · Audit Trail' },
  ownership: { title: 'Ownership & Governance', sub: 'Insiders · Institutions · Compensation' },
  disclaimer: { title: 'Disclaimer', sub: 'Investment Advice Notice' },
}

export function chapterNum(id: ChapterId): string {
  const idx = CHAPTER_ORDER.indexOf(id)
  // Display 01-13 (1-indexed); 0-based is a developer convention not appropriate for users.
  return String(idx + 1).padStart(2, '0')
}

export function chapterLabel(id: ChapterId, locale: Locale): ChapterLabel {
  const table = locale === 'en' ? EN : ZH
  return { num: chapterNum(id), ...table[id] }
}

/** All chapter labels for a given locale — used by ReportLeftRail. */
export function allChapterLabels(locale: Locale): (ChapterLabel & { id: ChapterId })[] {
  return CHAPTER_ORDER.map((id) => ({ id, ...chapterLabel(id, locale) }))
}
