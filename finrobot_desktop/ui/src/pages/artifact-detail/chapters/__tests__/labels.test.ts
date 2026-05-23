import { describe, it, expect } from "vitest"
import {
  CHAPTER_ORDER,
  chapterLabel,
  chapterNum,
  allChapterLabels,
} from "../labels"

describe("chapter labels — numbering", () => {
  it("starts at 01 (not 00) — user-visible numbering", () => {
    expect(chapterNum("cover")).toBe("01")
  })

  it("ends at 12 for the last chapter", () => {
    expect(chapterNum("disclaimer")).toBe("12")
  })

  it("CHAPTER_ORDER has all 12 chapters in spec order", () => {
    expect(CHAPTER_ORDER).toEqual([
      "cover",
      "thesis",
      "overview",
      "financial",
      "valuation",
      "news",
      "sensitivity",
      "catalysts",
      "technical",
      "competitive",
      "data",
      "disclaimer",
    ])
  })

  it("every chapter has a 2-digit num between 01 and 12", () => {
    CHAPTER_ORDER.forEach((id, idx) => {
      const num = chapterNum(id)
      expect(num).toMatch(/^\d{2}$/)
      expect(Number(num)).toBe(idx + 1)
    })
  })
})

describe("chapter labels — zh", () => {
  it.each([
    ["cover", "封面"],
    ["thesis", "投资论点"],
    ["overview", "公司概览"],
    ["financial", "财务分析"],
    ["valuation", "估值分析"],
    ["news", "近期新闻与事件"],
    ["sensitivity", "敏感性分析"],
    ["catalysts", "关键催化剂"],
    ["technical", "技术与高阶分析"],
    ["competitive", "竞争格局"],
    ["data", "财务数据"],
    ["disclaimer", "免责声明"],
  ] as const)("zh chapter %s → %s", (id, title) => {
    expect(chapterLabel(id, "zh").title).toBe(title)
  })

  it("no zh title leaks english (sanity scan)", () => {
    CHAPTER_ORDER.forEach((id) => {
      const { title, sub } = chapterLabel(id, "zh")
      // zh title should not be just ASCII letters (financial terms like DCF/Football Field allowed in sub).
      expect(title).toMatch(/[一-龥]/) // contains at least one CJK char
      expect(sub.length).toBeGreaterThan(0)
    })
  })
})

describe("chapter labels — en", () => {
  it.each([
    ["cover", "Cover"],
    ["thesis", "Investment Thesis"],
    ["overview", "Company Overview"],
    ["disclaimer", "Disclaimer"],
  ] as const)("en chapter %s → %s", (id, title) => {
    expect(chapterLabel(id, "en").title).toBe(title)
  })
})

describe("allChapterLabels", () => {
  it("returns 12 entries in CHAPTER_ORDER for zh", () => {
    const zh = allChapterLabels("zh")
    expect(zh).toHaveLength(12)
    expect(zh[0].id).toBe("cover")
    expect(zh[0].title).toBe("封面")
    expect(zh[11].id).toBe("disclaimer")
    expect(zh[11].title).toBe("免责声明")
  })

  it("returns 12 entries in CHAPTER_ORDER for en", () => {
    const en = allChapterLabels("en")
    expect(en).toHaveLength(12)
    expect(en[0].title).toBe("Cover")
    expect(en[11].title).toBe("Disclaimer")
  })

  it("zh and en have same id set and same num set — only titles differ", () => {
    const zh = allChapterLabels("zh")
    const en = allChapterLabels("en")
    expect(zh.map((c) => c.id)).toEqual(en.map((c) => c.id))
    expect(zh.map((c) => c.num)).toEqual(en.map((c) => c.num))
  })
})
