import { describe, it, expect } from 'vitest'
import { CHAPTER_ORDER, chapterLabel, chapterNum, allChapterLabels } from '../labels'

describe('chapter labels — numbering', () => {
  it('starts at 01 (not 00) — user-visible numbering', () => {
    expect(chapterNum('cover')).toBe('01')
  })

  it('ownership sits at 12 — between data and disclaimer', () => {
    expect(chapterNum('ownership')).toBe('12')
  })

  it('ends at 13 for the last chapter (disclaimer)', () => {
    expect(chapterNum('disclaimer')).toBe('13')
  })

  it('CHAPTER_ORDER has all 13 chapters in spec order', () => {
    expect(CHAPTER_ORDER).toEqual([
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
    ])
  })

  it('every chapter has a 2-digit num between 01 and 13', () => {
    CHAPTER_ORDER.forEach((id, idx) => {
      const num = chapterNum(id)
      expect(num).toMatch(/^\d{2}$/)
      expect(Number(num)).toBe(idx + 1)
    })
  })
})

describe('chapter labels — zh', () => {
  it.each([
    ['cover', '封面'],
    ['thesis', '投资论点'],
    ['overview', '公司概览'],
    ['financial', '财务分析'],
    ['valuation', '估值分析'],
    ['news', '近期新闻与事件'],
    ['sensitivity', '敏感性分析'],
    ['catalysts', '催化剂信号'],
    ['technical', '技术分析'],
    ['competitive', '竞争格局'],
    ['data', '财务数据'],
    ['ownership', '股权与治理'],
    ['disclaimer', '免责声明'],
  ] as const)('zh chapter %s → %s', (id, title) => {
    expect(chapterLabel(id, 'zh').title).toBe(title)
  })

  it('no zh title leaks english (sanity scan)', () => {
    CHAPTER_ORDER.forEach((id) => {
      const { title, sub } = chapterLabel(id, 'zh')
      // zh title should not be just ASCII letters (financial terms like DCF/Football Field allowed in sub).
      expect(title).toMatch(/[一-龥]/) // contains at least one CJK char
      expect(sub.length).toBeGreaterThan(0)
    })
  })
})

describe('chapter labels — en', () => {
  it.each([
    ['cover', 'Cover'],
    ['thesis', 'Investment Thesis'],
    ['overview', 'Company Overview'],
    ['ownership', 'Ownership & Governance'],
    ['disclaimer', 'Disclaimer'],
  ] as const)('en chapter %s → %s', (id, title) => {
    expect(chapterLabel(id, 'en').title).toBe(title)
  })
})

describe('allChapterLabels', () => {
  it('returns 13 entries in CHAPTER_ORDER for zh', () => {
    const zh = allChapterLabels('zh')
    expect(zh).toHaveLength(13)
    expect(zh[0].id).toBe('cover')
    expect(zh[0].title).toBe('封面')
    expect(zh[11].id).toBe('ownership')
    expect(zh[11].title).toBe('股权与治理')
    expect(zh[12].id).toBe('disclaimer')
    expect(zh[12].title).toBe('免责声明')
  })

  it('returns 13 entries in CHAPTER_ORDER for en', () => {
    const en = allChapterLabels('en')
    expect(en).toHaveLength(13)
    expect(en[0].title).toBe('Cover')
    expect(en[11].title).toBe('Ownership & Governance')
    expect(en[12].title).toBe('Disclaimer')
  })

  it('zh and en have same id set and same num set — only titles differ', () => {
    const zh = allChapterLabels('zh')
    const en = allChapterLabels('en')
    expect(zh.map((c) => c.id)).toEqual(en.map((c) => c.id))
    expect(zh.map((c) => c.num)).toEqual(en.map((c) => c.num))
  })
})
