// Financial-term glossary backing <TermTip>. Definitions live here (not in the
// Lingui .po catalogs) so the full zh/en pair for a term is one editable block,
// not 4 scattered .po msgids — and a sell-side reviewer can vet caliber in situ.
//
// Each entry carries, per locale:
//   short — one-line hover definition (caliber-accurate, no marketing fluff)
//   ask   — the prompt sent to the RightChatPanel LLM when "ask more" is clicked
//
// TermTip resolves the entry by its display term via `lookupTerm()`. The map key
// is the *suffix* (e.g. 'wacc'); ALIASES maps the on-screen string a chapter
// wraps (e.g. 'EV/EBITDA', 'WACC') to that suffix, so chapters wrap the literal
// label they already render.

import type { Locale } from '../i18n'

export interface TermDef {
  short: string
  ask: string
}

type LocalizedTerm = Record<Locale, TermDef>

// ── Definitions ──────────────────────────────────────────────────────────
// Keyed by canonical suffix. Keep `short` to one sentence; keep `ask` framed as
// a request an analyst would actually make.
const TERMS: Record<string, LocalizedTerm> = {
  wacc: {
    zh: {
      short:
        '加权平均资本成本——债权与股权按市值加权的综合融资成本，DCF 用它把未来现金流折现到现值。',
      ask: '请解释 WACC（加权平均资本成本）的构成、计算公式，以及它如何影响这份 DCF 估值。',
    },
    en: {
      short:
        'Weighted Average Cost of Capital — the blended cost of debt and equity (market-value weighted) used as the DCF discount rate.',
      ask: 'Explain WACC: its components, the formula, and how it drives this DCF valuation.',
    },
  },
  nopat: {
    zh: {
      short:
        '税后净营业利润 = EBIT ×(1−税率)——剔除资本结构(利息)与非经营项后的核心经营盈利,是 FCFF 与核心 P/E 的盈利口径。',
      ask: '请解释 NOPAT(税后净营业利润)的口径,它和净利润、EBIT 有什么区别,为什么估值里常用它?',
    },
    en: {
      short:
        'Net Operating Profit After Tax = EBIT × (1 − tax rate) — core operating earnings stripped of capital structure (interest) and non-operating items; the earnings base for FCFF and core P/E.',
      ask: 'Explain NOPAT: how it differs from net income and EBIT, and why valuation uses it as the core-earnings base.',
    },
  },
  evEbitda: {
    zh: {
      short: 'EV/EBITDA——企业价值 / 息税折旧摊销前利润,资本结构中性的估值倍数,便于跨公司可比。',
      ask: '请解释 EV/EBITDA 倍数:为什么用 EV 而不是市值、为什么用 EBITDA,以及它相对 P/E 的优劣。',
    },
    en: {
      short:
        'Enterprise Value ÷ EBITDA — a capital-structure-neutral multiple that makes peers comparable regardless of leverage.',
      ask: 'Explain the EV/EBITDA multiple: why EV (not market cap), why EBITDA, and its pros/cons versus P/E.',
    },
  },
  fcf: {
    zh: {
      short:
        '自由现金流——经营产生、扣除维持/扩张资本开支后可自由分配给资本提供方的现金,是 DCF 的折现对象。',
      ask: '请解释自由现金流(FCF):FCFF 与 FCFE 的区别,以及它如何驱动 DCF 估值。',
    },
    en: {
      short:
        'Free Cash Flow — operating cash left after capital expenditure, available to capital providers; the cash stream a DCF discounts.',
      ask: 'Explain Free Cash Flow: the difference between FCFF and FCFE, and how it drives the DCF.',
    },
  },
  fcff: {
    zh: {
      short:
        '企业自由现金流 = NOPAT + 折旧摊销 − 资本开支 − 营运资本增加——付息前、归属全体资本提供方的现金流,用 WACC 折现。',
      ask: '请解释 FCFF(企业自由现金流)的计算公式,它为什么用 WACC 折现而不是股权成本。',
    },
    en: {
      short:
        'Free Cash Flow to the Firm = NOPAT + D&A − capex − ΔNWC — pre-interest cash to all capital providers; discounted at WACC.',
      ask: 'Explain FCFF: its build-up formula and why it is discounted at WACC rather than the cost of equity.',
    },
  },
  pe: {
    zh: {
      short:
        '市盈率 = 股价 / 每股收益(或市值 / 净利润)——市场为每一元盈利支付的价格,最常用的相对估值倍数。',
      ask: '请解释市盈率(P/E):TTM 与 forward 口径的区别,以及怎样判断它是高估还是低估。',
    },
    en: {
      short:
        'Price / Earnings — price paid per dollar of earnings (price ÷ EPS); the most common relative-valuation multiple.',
      ask: 'Explain P/E: trailing vs forward, and how to judge whether a P/E signals over- or under-valuation.',
    },
  },
  corePe: {
    zh: {
      short:
        '核心 P/E = 市值 / NOPAT——用税后核心营业利润替代 GAAP 净利润的 P/E,剔除非经营性损益,使跨公司可比性更强。',
      ask: '请解释核心 P/E(市值/NOPAT)与普通 P/E 的区别,为什么用核心盈利口径做同业可比更可靠。',
    },
    en: {
      short:
        'Core P/E = market cap ÷ NOPAT — a P/E on after-tax core operating earnings, stripping non-operating items for cleaner peer comparability.',
      ask: 'Explain Core P/E (market cap ÷ NOPAT) versus ordinary P/E, and why the core-earnings base improves peer comparability.',
    },
  },
  terminalGrowth: {
    zh: {
      short:
        '永续增长率(g)——DCF 预测期后假设现金流永远以此速率增长,通常不超过长期 GDP/通胀,对终值极度敏感。',
      ask: '请解释永续增长率(g)在 DCF 中的作用,合理取值范围,以及它对终值和估值的敏感性。',
    },
    en: {
      short:
        'Terminal growth (g) — the perpetual growth rate assumed for cash flows beyond the forecast horizon; usually ≤ long-run GDP/inflation, and the terminal value is highly sensitive to it.',
      ask: 'Explain terminal growth (g) in a DCF: a sensible range, and how sensitive the terminal value is to it.',
    },
  },
  dcf: {
    zh: {
      short: '现金流折现法——把未来自由现金流按 WACC 折现到现值求内在价值,绝对估值的主力方法。',
      ask: '请解释 DCF(现金流折现)估值的步骤、关键假设,以及它对 WACC 和永续增长率的敏感性。',
    },
    en: {
      short:
        'Discounted Cash Flow — intrinsic value from discounting projected free cash flows at WACC; the workhorse of absolute valuation.',
      ask: 'Walk through the DCF method: steps, key assumptions, and sensitivity to WACC and terminal growth.',
    },
  },
  ddm: {
    zh: {
      short:
        '股利折现模型——把未来股利按股权成本折现求股权价值,适用于稳定派息的成熟公司(如银行、公用事业)。',
      ask: '请解释股利折现模型(DDM):Gordon 增长模型公式、适用场景,以及它与 DCF 的区别。',
    },
    en: {
      short:
        'Dividend Discount Model — equity value from discounting future dividends at the cost of equity; suited to stable dividend payers (banks, utilities).',
      ask: 'Explain the DDM: the Gordon-growth formula, where it fits, and how it differs from a DCF.',
    },
  },
  lbo: {
    zh: {
      short: '杠杆收购——以大量债务融资收购公司,用标的现金流偿债、几年后退出,以 IRR/MOIC 衡量回报。',
      ask: '请解释杠杆收购(LBO)的结构、回报来源(去杠杆/EBITDA 增长/倍数扩张),以及 IRR 怎么算。',
    },
    en: {
      short:
        'Leveraged Buyout — acquiring a company largely with debt, repaying it from the target’s cash flows and exiting in a few years; return measured by IRR/MOIC.',
      ask: 'Explain the LBO: its structure, return drivers (deleveraging / EBITDA growth / multiple expansion), and how IRR is computed.',
    },
  },
  irr: {
    zh: {
      short: '内部收益率——使投资净现值为零的年化折现率,是 LBO/项目投资衡量回报的核心指标。',
      ask: '请解释内部收益率(IRR):定义、与 MOIC 的关系,以及为什么持有期会影响 IRR。',
    },
    en: {
      short:
        'Internal Rate of Return — the annualized discount rate that sets an investment’s NPV to zero; the headline return metric for LBO/project deals.',
      ask: 'Explain IRR: its definition, its relationship to MOIC, and why holding period affects it.',
    },
  },
  moic: {
    zh: {
      short:
        'MOIC——投入资本倍数 = 退出权益价值 / 投入权益,衡量本金翻了几倍(不考虑时间),与 IRR 互补。',
      ask: '请解释 MOIC(投入资本倍数)与 IRR 的区别,为什么两者要一起看。',
    },
    en: {
      short:
        'Multiple on Invested Capital = exit equity value ÷ invested equity — how many times the money returned (ignoring time); complements IRR.',
      ask: 'Explain MOIC versus IRR, and why both are read together.',
    },
  },
  thirteenF: {
    zh: {
      short:
        '13F——管理 1 亿美元以上的机构每季度向 SEC 申报的持仓报告,用于追踪机构买卖动向(滞后约 45 天)。',
      ask: '请解释 13F 持仓报告:谁要申报、申报什么、有约 45 天滞后,使用时要注意哪些坑。',
    },
    en: {
      short:
        'Form 13F — the quarterly SEC filing of US equity holdings by institutions managing $100M+; used to track institutional buying/selling (≈45-day lag).',
      ask: 'Explain Form 13F: who files, what is disclosed, the ~45-day reporting lag, and its caveats.',
    },
  },
  def14a: {
    zh: {
      short:
        'DEF 14A——年度股东大会的委托投票说明书,披露高管薪酬、CEO 薪酬比率、董事会与重大投票事项。',
      ask: '请解释 DEF 14A(委托投票说明书)里有哪些治理与薪酬信息,分析师该重点看什么。',
    },
    en: {
      short:
        'DEF 14A — the definitive proxy statement for the annual meeting; discloses executive compensation, CEO pay ratio, board, and matters up for vote.',
      ask: 'Explain the DEF 14A proxy: what governance and compensation data it carries, and what an analyst should focus on.',
    },
  },
  payRatio: {
    zh: {
      short:
        'CEO 薪酬比率——CEO 总薪酬 / 员工薪酬中位数(SEC 强制披露),衡量内部薪酬差距,治理与 ESG 关注点。',
      ask: '请解释 CEO 薪酬比率(CEO Pay Ratio)的口径、SEC 披露要求,以及它对治理评估的意义。',
    },
    en: {
      short:
        'CEO Pay Ratio — CEO total compensation ÷ median employee pay (SEC-mandated disclosure); a gauge of internal pay disparity and a governance/ESG signal.',
      ask: 'Explain the CEO Pay Ratio: its calculation, the SEC disclosure rule, and what it tells you about governance.',
    },
  },
  beta: {
    zh: {
      short:
        'Beta(β)——个股相对大盘的系统性风险系数,β>1 波动大于市场;CAPM 用它求股权成本,进而影响 WACC。估值用的是 Blume 调整后的 β(原始 5 年回归 β 经 2/3·β+1/3·1 向 1.0 收敛,得到更稳的前瞻 β),所以它比技术面那栏的原始 5 年 β 略低——两者是不同口径,不是对不上。',
      ask: '请解释 Beta(β):怎么估计、levered 与 unlevered 的区别、Blume 调整为何让 WACC 用的 β 与原始 5 年 β 不同,以及它如何进入 CAPM 和 WACC。',
    },
    en: {
      short:
        'Beta (β) — a stock’s systematic risk versus the market; β>1 means more volatile than the market. CAPM uses it to derive the cost of equity, feeding WACC. The valuation uses the Blume-adjusted β (the raw 5Y regression beta shrunk 2/3·β+1/3·1 toward 1.0 for a steadier forward estimate), so it reads a touch lower than the raw 5Y beta in the technicals — different calibers, not a mismatch.',
      ask: 'Explain Beta: how it is estimated, levered vs unlevered, why the Blume adjustment makes the WACC beta differ from the raw 5Y beta, and how it enters CAPM and WACC.',
    },
  },
  targetPrice: {
    zh: {
      short:
        '目标价——分析师对 12 个月后合理股价的判断,通常由 DCF、可比公司、情景加权综合得出,对应买入/持有/卖出评级。',
      ask: '请解释目标价(target price)怎么得出,DCF/可比法/情景如何加权,以及它和当前股价的关系怎么解读。',
    },
    en: {
      short:
        'Target price — an analyst’s view of fair value ~12 months out, usually a blend of DCF, comps and scenarios; it anchors the buy/hold/sell rating.',
      ask: 'Explain how a 12-month target price is derived, how DCF/comps/scenarios are weighted, and how to read it against the current price.',
    },
  },
  terminalValue: {
    zh: {
      short: '终值——DCF 预测期末之后所有现金流的现值(永续增长法或退出倍数法),常占 DCF 估值的大头。',
      ask: '请解释终值(terminal value):永续增长法 vs 退出倍数法,以及为什么它在 DCF 中占比这么高。',
    },
    en: {
      short:
        'Terminal value — the present value of all cash flows beyond the explicit forecast (perpetuity-growth or exit-multiple method); often the bulk of a DCF.',
      ask: 'Explain terminal value: perpetuity-growth vs exit-multiple, and why it dominates DCF valuations.',
    },
  },
  enterpriseValue: {
    zh: {
      short:
        '企业价值(EV)= 市值 + 净债务(+少数股东权益等)——收购整家公司的理论成本,资本结构中性,用于 EV/EBITDA 等倍数。',
      ask: '请解释企业价值(EV)的构成、它和市值的桥接,以及为什么倍数估值常用 EV 而非市值。',
    },
    en: {
      short:
        'Enterprise Value = market cap + net debt (+ minorities, etc.) — the theoretical cost to acquire the whole firm; capital-structure-neutral, used in EV/EBITDA.',
      ask: 'Explain Enterprise Value: its build-up, the bridge from market cap, and why multiples use EV over market cap.',
    },
  },
}

// ── Aliases: on-screen label → canonical suffix ───────────────────────────
// Chapters wrap the literal text they render. Keep these case-sensitive matches
// to what actually appears in the report.
const ALIASES: Record<string, string> = {
  WACC: 'wacc',
  NOPAT: 'nopat',
  'EV/EBITDA': 'evEbitda',
  FCF: 'fcf',
  FCFF: 'fcff',
  'P/E': 'pe',
  PE: 'pe',
  'Core P/E': 'corePe',
  '核心 P/E': 'corePe',
  'Terminal Growth': 'terminalGrowth',
  DCF: 'dcf',
  DDM: 'ddm',
  LBO: 'lbo',
  IRR: 'irr',
  MOIC: 'moic',
  '13F': 'thirteenF',
  '13F-HR': 'thirteenF',
  'DEF 14A': 'def14a',
  'Pay Ratio': 'payRatio',
  Beta: 'beta',
  β: 'beta',
  'Target Price': 'targetPrice',
  'Terminal Value': 'terminalValue',
  EV: 'enterpriseValue',
  'Enterprise Value': 'enterpriseValue',
}

/** Resolve a display term to its localized definition, or null if unknown. */
export function lookupTerm(term: string, locale: Locale): TermDef | null {
  const suffix = ALIASES[term]
  if (!suffix) return null
  return TERMS[suffix][locale]
}
