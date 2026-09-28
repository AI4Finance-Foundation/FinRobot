import FootballField from '../../../components/charts/FootballField'
import WaterfallChart from '../../../components/charts/WaterfallChart'
import { useI18n } from '../../../i18n'
import { TermTip } from '../../../components/TermTip'
import { MarkdownLite } from '../../../components/MarkdownLite'
import { formatCurrency, formatCurrencyCompact } from '../../../utils/format'
import { Chapter, Narrative, SubChapter } from './ChapterBase'
import { MetricModule, type MetricCell } from './MetricModule'
import { FieldCaveat, findingsFor } from './FieldCaveat'
import type {
  DcfShape,
  ForwardEstimatesShape,
  HistoricalBandShape,
  NumericAuditShape,
  SOTPBreakdownShape,
  SOTPScenarioBandShape,
  ThesisShape,
  ValuationSynthesisShape,
} from './types'

interface ChapterValuationProps {
  dcf: DcfShape | null
  thesis: ThesisShape | null
  // Frozen football-field data: per-method ranges + the SNAPSHOT price the report
  // is anchored to. The report renders THIS (persisted at generation) instead of
  // re-fetching /api/valuation/aggregate live, so the football field's current
  // price can never disagree with the cover/narrative (the price-split bug).
  valuationSynthesis: ValuationSynthesisShape | null
  // Frozen forward-estimate provenance (FY year / source / confidence) — labels
  // the forward comps row + footnotes its source from the snapshot, not a live
  // refetch. null when no forward estimate landed at generation.
  forwardEstimates: ForwardEstimatesShape | null
  // Scenario SOTP (Batch 3B v1): the reverse-SOTP market-implied decomposition for
  // an option-value name. Independent channel — rendered as a floor /
  // implied-option-premium panel below the football field, NOT a method bar. null
  // for every non-option-value name (the deterministic gate didn't fire).
  sotpBreakdown: SOTPBreakdownShape | null
  // quote → DCF implied price & price target (per-share); reporting → EV &
  // equity value (absolutes). Differ for foreign ADRs (BUG-030).
  quoteCurrency: string
  reportingCurrency: string
  // Numeric-audit gate verdict — used to flag the EV cell when the EV family
  // (enterprise_value / ev_ebitda / ev_revenue) is a category error (bank EV)
  // or dimensionally mixed (cross-currency ratio). null on legacy artifacts.
  numericAudit?: NumericAuditShape | null
  // Frozen historical multiple band (EV/EBITDA · P/FCF) from technical_analysis.
  // Feeds the football field's provenance rail: where the current multiple sits
  // vs the company's own 3-year P25–P75 — the "why" behind that method's target.
  // null on legacy artifacts / when the band could not be computed.
  historicalBand?: HistoricalBandShape | null
}

export function ChapterValuation(props: ChapterValuationProps): React.ReactElement {
  return (
    <Chapter id="valuation">
      <ValuationBody {...props} />
    </Chapter>
  )
}

/** The valuation content WITHOUT the numbered <Chapter> chrome, so the standalone
 * DCF tool page (CompactArtifactViewer) can reuse the exact same DCF-inputs +
 * bridge + football rendering under its own section header — one source of truth,
 * no drift. Degrades cleanly when a standalone artifact lacks the report-only
 * blocks: the review echo, football field, forward footnote and target line all
 * gate on thesis / valuation_synthesis / forwardEstimates / sotp and simply omit
 * themselves; the DCF-inputs module + bridge render from `dcf` alone. */
export function ValuationBody({
  dcf,
  thesis,
  valuationSynthesis,
  forwardEstimates,
  sotpBreakdown,
  quoteCurrency,
  reportingCurrency,
  numericAudit = null,
  historicalBand = null,
}: ChapterValuationProps): React.ReactElement {
  const { t, locale } = useI18n()
  const overview = thesis?.valuation_overview ?? null
  const wacc = dcf?.wacc ?? null
  const terminalGrowth = dcf?.inputs?.terminal_growth_rate ?? null
  const taxRate = dcf?.inputs?.tax_rate ?? null
  const beta = dcf?.inputs?.beta ?? null
  const implied = dcf?.implied_price ?? null
  const ev = dcf?.enterprise_value ?? null
  const eq = dcf?.equity_value ?? null
  const mi = dcf?.market_implied ?? null

  // Withheld-target echo: when the point target is withheld financial_modeling.
  // implied_price is null, so the "DCF Implied Price" cell drops and the grid
  // looks "缺数". Lead the chapter with a compact reverse-DCF banner that echoes
  // the cover headline — the cash-flow ceiling here is the dcf METHOD mid
  // (valuation_synthesis), never implied_price.
  const dcfMethodMid = valuationSynthesis?.methods?.find((m) => m.name === 'dcf')?.mid ?? null
  // Balance-sheet financial (bank / insurer): the DCF cells are absent by design
  // (FCFF-DCF is a category error), but the football field still leads on P/B · P/E
  // (+ DDM / residual income). Frame the empty DCF-inputs box as "not applicable",
  // not "re-run", so it does not contradict the full football field rendered below.
  const financialSector = valuationSynthesis?.financial_sector ?? false
  const reviewMarketPrice = valuationSynthesis?.current_price ?? null
  const showReviewEcho =
    mi !== null &&
    implied === null &&
    reviewMarketPrice !== null &&
    reviewMarketPrice > 0 &&
    (mi.growth_unreachable ? mi.ceiling_price != null : mi.implied_growth != null)

  // EV-family fields the numeric-audit gate flags as a category error (bank EV)
  // or dimensionally mixed (cross-currency). When any is flagged, the EV cell
  // carries a hover caveat so the suspect number isn't read at face value.
  const evFindings = findingsFor(numericAudit, ['enterprise_value', 'ev_ebitda', 'ev_revenue'])

  // Football rows come from the frozen valuation_synthesis (persisted at
  // generation against the snapshot price), NOT a live aggregate refetch.
  // `name` is the method key (dcf / comps_pe / …); FootballField maps it to a
  // label. The `source` caliber string (e.g. "peer_median_core_pe × core_eps")
  // lets FootballField label the comps row so the target reconciles with the
  // comps table.
  const footballRows = (valuationSynthesis?.methods ?? []).map((m) => ({
    method: m.name,
    low: m.low,
    mid: m.mid,
    high: m.high,
    source: m.source,
  }))

  // DCF bridge: PV(FCF) + PV(terminal) → enterprise value → −net debt → equity.
  // Net debt is implied by EV − equity value (the DCF result doesn't carry it
  // separately). Only build when the full chain is present so the bridge always
  // reconciles to the implied equity value.
  const pvFcf = dcf?.pv_fcf_total ?? null
  const pvTerminal = dcf?.pv_terminal ?? null
  const waterfallRows =
    pvFcf !== null && pvTerminal !== null && ev !== null && eq !== null
      ? [
          { label: t('chapter.valuation.bridge.pvFcf'), value: pvFcf, is_total: false },
          { label: t('chapter.valuation.bridge.pvTerminal'), value: pvTerminal, is_total: false },
          { label: t('chapter.valuation.bridge.ev'), value: ev, is_total: true },
          {
            // Net debt = EV − equity. Net-cash names (eq > EV) produce a positive
            // (adding) bar, so the label must flip to "Net Cash" — "Less: Net Debt"
            // on an additive bar reads as a contradiction.
            label:
              ev - eq >= 0
                ? t('chapter.valuation.bridge.netDebt')
                : t('chapter.valuation.bridge.netCash'),
            value: -(ev - eq),
            is_total: false,
          },
          { label: t('chapter.valuation.bridge.equity'), value: eq, is_total: true },
        ]
      : []

  // Visual cell = MetricCell (the `sub` line carries what was the KvGrid `delta`).
  // Labels stay ReactNode (TermTip / FieldCaveat wrappers); values/tone unchanged.
  type Cell = MetricCell
  const cells: Cell[] = [
    wacc !== null &&
      ({
        // Headline term explainers: WACC, terminal growth and EV are the DCF
        // levers a non-IB reader most needs unpacked — wrap them in TermTip
        // (hover gloss + "ask FinRobot" deep dive). One wrap per term per chapter.
        label: <TermTip term="WACC" />,
        value: `${(wacc * 100).toFixed(2)}%`,
        sub: beta !== null ? <TermTip term="β">{`β ${beta.toFixed(2)}`}</TermTip> : undefined,
      } as Cell),
    terminalGrowth !== null &&
      ({
        label: <TermTip term="Terminal Growth">{t('chapter.valuation.kv.terminalGrowth')}</TermTip>,
        value: `${(terminalGrowth * 100).toFixed(2)}%`,
      } as Cell),
    taxRate !== null &&
      ({
        label: t('chapter.valuation.kv.taxRate'),
        value: `${(taxRate * 100).toFixed(0)}%`,
      } as Cell),
    implied !== null &&
      ({
        label: t('chapter.valuation.kv.dcfImplied'),
        // Per-share → quote currency.
        value: formatCurrency(implied, quoteCurrency, locale, 2),
        tone: (thesis?.price_target && implied >= thesis.price_target ? 'up' : undefined) as
          | 'up'
          | undefined,
      } as Cell),
    // Reverse-DCF reality check: the growth the CURRENT market price implies.
    // 'Unreachable' (down/red tone) is the option-value signal; otherwise show
    // the implied annual growth with the horizon it's solved over.
    mi !== null &&
      (mi.growth_unreachable || mi.implied_growth != null) &&
      ({
        label: t('chapter.valuation.kv.marketImpliedGrowth'),
        value:
          !mi.growth_unreachable && mi.implied_growth != null
            ? `${(mi.implied_growth * 100).toFixed(1)}%`
            : t('chapter.valuation.marketImplied.na'),
        sub: t('chapter.valuation.marketImplied.horizon', { n: mi.horizon_years }),
        tone: (mi.growth_unreachable ? 'down' : undefined) as 'down' | undefined,
      } as Cell),
    // Companion reverse-DCF lever: the discount rate that would equate the DCF to
    // the CURRENT price (solved independently of the implied-growth path). Shown
    // beside implied growth so the reality check carries BOTH levers, with a
    // descriptive sub-line vs our own DCF WACC (no verdict — that's the analyst's).
    // Was computed (market_implied.implied_wacc) but never rendered before.
    mi !== null &&
      !mi.growth_unreachable &&
      mi.implied_wacc != null &&
      wacc != null &&
      ({
        label: t('chapter.valuation.kv.marketImpliedWacc'),
        value: `${(mi.implied_wacc * 100).toFixed(1)}%`,
        sub: t('chapter.valuation.marketImplied.vsDcf', {
          wacc: `${(wacc * 100).toFixed(1)}%`,
        }),
      } as Cell),
    ev !== null &&
      ({
        label: (
          <>
            <TermTip term="EV">{t('chapter.valuation.kv.enterpriseValue')}</TermTip>
            <FieldCaveat findings={evFindings} />
          </>
        ),
        // Absolute IS/BS-caliber → reporting currency.
        value: formatCurrencyCompact(ev, reportingCurrency, locale),
      } as Cell),
    eq !== null &&
      ({
        label: t('chapter.valuation.kv.equityValue'),
        value: formatCurrencyCompact(eq, reportingCurrency, locale),
      } as Cell),
  ].filter((c): c is Cell => Boolean(c))

  return (
    <>
      {showReviewEcho && mi && (
        <div
          data-testid="valuation-review-echo"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 14,
            marginBottom: 16,
            padding: '14px 16px',
            borderRadius: 'var(--radius-md)',
            background: `linear-gradient(160deg, color-mix(in srgb, ${mi.growth_unreachable ? 'var(--danger)' : 'var(--warning)'} 10%, transparent), var(--bg-card-50))`,
            border: `1px solid color-mix(in srgb, ${mi.growth_unreachable ? 'var(--danger)' : 'var(--warning)'} 38%, transparent)`,
            borderLeft: `3px solid ${mi.growth_unreachable ? 'var(--danger)' : 'var(--warning)'}`,
          }}
        >
          <div style={{ minWidth: 0, flex: 1 }}>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 10,
                letterSpacing: '0.1em',
                textTransform: 'uppercase',
                color: 'var(--text-muted)',
                marginBottom: 6,
              }}
            >
              {t('chapter.cover.reverseDcf.scaleTitle')}
            </div>
            <div
              style={{
                fontFamily: 'var(--font-body)',
                fontSize: 13.5,
                lineHeight: 1.5,
                color: 'var(--text-secondary)',
              }}
            >
              {mi.growth_unreachable ? (
                <>
                  {t('chapter.cover.reverseDcf.ledeB.pre')}{' '}
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 700,
                      color: 'var(--danger)',
                    }}
                  >
                    {mi.growth_ceiling != null ? `${(mi.growth_ceiling * 100).toFixed(0)}%` : '—'}
                  </span>{' '}
                  {t('chapter.cover.reverseDcf.ledeB.mid')}{' '}
                  <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                    {mi.horizon_years}y
                  </span>{' '}
                  {t('chapter.cover.reverseDcf.ledeB.impliesOnly')}{' '}
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 700,
                      color: 'var(--text-primary)',
                    }}
                  >
                    {mi.ceiling_price != null
                      ? formatCurrency(mi.ceiling_price, quoteCurrency, locale, 2)
                      : '—'}
                  </span>{' '}
                  {t('chapter.cover.reverseDcf.ledeB.marketAt')}{' '}
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 700,
                      color: 'var(--accent-cyan)',
                    }}
                  >
                    {formatCurrency(reviewMarketPrice as number, quoteCurrency, locale, 2)}
                  </span>
                  .
                </>
              ) : (
                <>
                  {t('chapter.cover.reverseDcf.ledeA.pre')}{' '}
                  <span
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 700,
                      color: 'var(--warning)',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    ~{mi.implied_growth != null ? `${(mi.implied_growth * 100).toFixed(1)}%` : '—'}
                    /yr
                  </span>{' '}
                  {t('chapter.cover.reverseDcf.ledeA.mid')}{' '}
                  <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600 }}>
                    {mi.horizon_years}y
                  </span>
                  {dcfMethodMid != null && (
                    <>
                      {' · '}
                      {t('chapter.cover.reverseDcf.modelTopsOut')}{' '}
                      <span
                        style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}
                      >
                        {formatCurrency(dcfMethodMid, quoteCurrency, locale, 2)}
                      </span>
                    </>
                  )}
                  .
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {overview && (
        <Narrative>
          <MarkdownLite text={overview} />
        </Narrative>
      )}

      {cells.length > 0 ? (
        <MetricModule
          title={locale === 'en' ? 'DCF Inputs & Implied Value' : 'DCF 输入与隐含价值'}
          accent="violet"
          cells={cells}
          columns={3}
        />
      ) : (
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11.5,
            color: 'var(--text-muted)',
            padding: '14px 18px',
            background: 'var(--bg-card-50)',
            border: '1px dashed var(--border-soft)',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          {financialSector
            ? t('chapter.cashflowMethods.notApplicableForFinancials')
            : t('chapter.valuation.empty')}
        </p>
      )}

      {mi?.growth_unreachable && mi.growth_ceiling != null && mi.ceiling_price != null && (
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            lineHeight: 1.7,
            color: 'var(--danger)',
            padding: '12px 16px',
            background: 'var(--bg-card-50)',
            border: '1px solid var(--border-soft)',
            borderRadius: 'var(--radius-sm)',
            marginTop: 12,
          }}
        >
          {t('chapter.valuation.marketImplied.unreachableNote', {
            ceiling: `${(mi.growth_ceiling * 100).toFixed(0)}%`,
            price: formatCurrency(mi.ceiling_price, quoteCurrency, locale, 2),
          })}
        </p>
      )}

      {waterfallRows.length > 0 && (
        <SubChapter heading={t('chapter.valuation.subheading.bridge')}>
          <WaterfallChart data={waterfallRows} title={t('chapter.valuation.bridge.title')} />
        </SubChapter>
      )}

      {footballRows.length > 0 && (
        <SubChapter heading={t('chapter.valuation.subheading.football')}>
          <FootballField
            data={footballRows}
            title={t('chapter.valuation.football.title')}
            currentPrice={valuationSynthesis?.current_price ?? undefined}
            // Forward fiscal year (e.g. "FY2026E") for the forward comps row,
            // read from the FROZEN provenance the artifact persisted — not a live
            // aggregate refetch.
            forwardFiscalPeriod={forwardEstimates?.fiscal_period ?? null}
            // Provenance rail: where the current EV/EBITDA (or P/FCF) multiple
            // sits vs the company's own 3-year band (frozen in technical_analysis).
            historicalBand={historicalBand}
            // Calibrated synthesis target overlaid on the price axis: the
            // HEADLINE target (the same number the cover / left-rail / thesis
            // publish) + its target_low–target_high band, so the method bars
            // visibly reconcile to the published conclusion.
            //
            // The point is `thesis.price_target`, NOT valuation_synthesis.weighted_price:
            // when methods diverge the confidence dial DISCARDS the blend and anchors
            // the headline on a single method (anchor-not-blend), so weighted_price is
            // the rejected midpoint — labelling it "Target" here contradicts the cover
            // (the price-split bug: cover $188 anchored vs football "Target $209" blend).
            // Withheld point (thesis.price_target=null) → no marker, but the band still
            // renders — 撤点≠撤区间.
            targetBand={{
              low: valuationSynthesis?.target_low ?? null,
              high: valuationSynthesis?.target_high ?? null,
              point: thesis?.price_target ?? null,
            }}
          />
          {forwardEstimates?.source && (
            <p
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: 11,
                color: 'var(--text-muted)',
                marginTop: 8,
                lineHeight: 1.5,
              }}
            >
              {t('chapter.valuation.forwardEstimates')}: {forwardEstimates.source}
              {forwardEstimates.confidence && (
                <span style={{ marginLeft: 8, color: 'var(--text-dim)' }}>
                  · {forwardEstimates.confidence}
                </span>
              )}
            </p>
          )}
          {/* Scenario SOTP — the option-value decomposition row. For a name a DCF
              point target can't honestly reach, the publishable product is the
              cash-flow floor (SEC-filed segments × conservative multiples) plus
              the pure-subtraction market-implied option value above it, NOT a
              fabricated target. Rendered as a decomposition panel — it is an
              INDEPENDENT channel, never a method bar competing for the target. */}
          {sotpBreakdown && (
            <SOTPBreakdownPanel
              sotp={sotpBreakdown}
              quoteCurrency={quoteCurrency}
              reportingCurrency={reportingCurrency}
            />
          )}
        </SubChapter>
      )}

      {thesis?.price_target && (
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            color: 'var(--text-secondary)',
            marginTop: 12,
          }}
        >
          <span style={{ color: 'var(--text-muted)' }}>
            <TermTip term="Target Price">{t('chapter.valuation.target12m')}</TermTip>
          </span>{' '}
          <span style={{ color: 'var(--accent-cyan)', fontSize: 14 }}>
            {formatCurrency(thesis.price_target, quoteCurrency, locale, 2)}
          </span>
          {thesis.price_target_basis && (
            <span style={{ color: 'var(--text-muted)', marginLeft: 10 }}>
              · {thesis.price_target_basis}
            </span>
          )}
        </p>
      )}
    </>
  )
}

/**
 * Scenario SOTP decomposition panel (Batch 3B v1). Renders the reverse-SOTP
 * channel as a "floor → implied option premium → market cap" stacked bar plus a
 * per-segment table. Every number is COMPUTED + sourceable; the price_floor is a
 * FLOOR (cash-flow business value), NOT a target — the implied option value above
 * it is the market's pure-subtraction valuation of robotaxi/FSD/Optimus optionality.
 *
 * Segment metrics (gross profit) are REPORTING currency; the market cap / floor
 * equity / implied option are QUOTE currency. v1 only ships USD reporters so the
 * two coincide, but the labels stay currency-correct for the foreign-reporter case.
 */
function SOTPBreakdownPanel({
  sotp,
  quoteCurrency,
  reportingCurrency,
}: {
  sotp: SOTPBreakdownShape
  quoteCurrency: string
  reportingCurrency: string
}): React.ReactElement {
  const { t, locale } = useI18n()
  const market = sotp.market_equity
  // Floor share of cap (clamped to [0,1] for the bar only; the % label uses the
  // raw implied_option_pct, which can legally exceed 1 / go negative).
  const floorPct = market > 0 ? Math.max(0, Math.min(1, sotp.equity_floor / market)) : 0
  const optionPctRaw = sotp.implied_option_pct
  const optionPctLabel = `${(optionPctRaw * 100).toFixed(1)}%`

  return (
    <SubChapter
      heading={locale === 'en' ? 'Sum-of-the-Parts · Option Value' : '分部加总 · 期权价值'}
    >
      <p
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--text-muted)',
          lineHeight: 1.6,
          marginBottom: 12,
        }}
      >
        {locale === 'en'
          ? 'Reverse-SOTP: the deterministic cash-flow floor (SEC-filed segments × comparable multiples) plus the market-implied option value above it — reverse-derived from the live price, never a fabricated target.'
          : '反向 SOTP:确定性现金流底(SEC 申报分部 × 可比倍数)+ 其上市价隐含的期权价值——由现价反推,绝非编造的目标价。'}
      </p>

      {/* Stacked floor / option bar */}
      <div
        style={{
          display: 'flex',
          height: 26,
          borderRadius: 'var(--radius-sm)',
          overflow: 'hidden',
          border: '1px solid var(--border-soft)',
          marginBottom: 6,
        }}
      >
        <div
          style={{
            width: `${floorPct * 100}%`,
            background:
              'linear-gradient(90deg, color-mix(in srgb, var(--primary) 45%, transparent), color-mix(in srgb, var(--secondary) 60%, transparent))',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: 'var(--text-primary)',
            whiteSpace: 'nowrap',
          }}
        >
          {floorPct > 0.12 ? (locale === 'en' ? 'Cash-flow floor' : '现金流底') : ''}
        </div>
        <div
          style={{
            flex: 1,
            background: 'color-mix(in srgb, var(--warning) 22%, transparent)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: 'var(--warning)',
            whiteSpace: 'nowrap',
          }}
        >
          {locale === 'en' ? 'Implied option' : '隐含期权'} {optionPctLabel}
        </div>
      </div>

      {/* Headline scalars */}
      <MetricModule
        title={locale === 'en' ? 'Floor & Implied Option' : '现金流底 & 隐含期权'}
        accent="violet"
        columns={3}
        cells={[
          {
            label: t('chapter.valuation.sotp.priceFloor'),
            value: formatCurrency(sotp.price_floor, quoteCurrency, locale, 2),
          },
          {
            label: t('chapter.valuation.sotp.equityFloor'),
            value: formatCurrencyCompact(sotp.equity_floor, quoteCurrency, locale),
          },
          {
            label: t('chapter.valuation.sotp.currentPrice'),
            value: formatCurrency(sotp.current_price, quoteCurrency, locale, 2),
          },
          {
            label: t('chapter.valuation.sotp.marketEquity'),
            value: formatCurrencyCompact(sotp.market_equity, quoteCurrency, locale),
          },
          {
            label: locale === 'en' ? 'Implied Option EV' : '隐含期权 EV',
            value: formatCurrencyCompact(sotp.implied_option_ev, quoteCurrency, locale),
          },
          {
            label: locale === 'en' ? 'Implied Option %' : '隐含期权占比',
            value: optionPctLabel,
          },
          ...(sotp.implied_success_probability != null
            ? [
                {
                  label: t('chapter.valuation.sotp.impliedProbability'),
                  value: `${(sotp.implied_success_probability * 100).toFixed(1)}%`,
                },
              ]
            : []),
        ]}
      />

      {/* Per-segment floor legs */}
      <div style={{ marginTop: 12, overflowX: 'auto' }}>
        <table
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
          }}
        >
          <thead>
            <tr style={{ color: 'var(--text-muted)', textAlign: 'left' }}>
              <th style={{ padding: '4px 8px' }}>{t('chapter.valuation.sotp.segment')}</th>
              <th style={{ padding: '4px 8px', textAlign: 'right' }}>
                {t('chapter.valuation.sotp.metric')}
              </th>
              <th style={{ padding: '4px 8px', textAlign: 'right' }}>
                {t('chapter.valuation.sotp.multiple')}
              </th>
              <th style={{ padding: '4px 8px', textAlign: 'right' }}>
                {locale === 'en' ? 'Implied EV' : '隐含 EV'}
              </th>
            </tr>
          </thead>
          <tbody>
            {sotp.modelable_segments.map((s) => (
              <tr key={s.name} style={{ borderTop: '1px solid var(--border-grid)' }}>
                <td style={{ padding: '4px 8px', color: 'var(--text-primary)' }}>
                  {s.name}
                  <span style={{ display: 'block', color: 'var(--text-dim)', fontSize: 10.5 }}>
                    {s.multiple_source}
                  </span>
                </td>
                <td
                  style={{ padding: '4px 8px', textAlign: 'right', color: 'var(--text-secondary)' }}
                >
                  {formatCurrencyCompact(s.metric_value, reportingCurrency, locale)}
                </td>
                <td
                  style={{ padding: '4px 8px', textAlign: 'right', color: 'var(--text-secondary)' }}
                >
                  {s.multiple.toFixed(1)}×
                </td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: 'var(--accent-cyan)' }}>
                  {formatCurrencyCompact(s.implied_ev, reportingCurrency, locale)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {sotp.scenario_band && (
        <ScenarioBandBlock band={sotp.scenario_band} quoteCurrency={quoteCurrency} />
      )}

      {sotp.option_anchor_source && (
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: 'var(--text-dim)',
            marginTop: 8,
          }}
        >
          {t('chapter.valuation.sotp.anchorSource')}: {sotp.option_anchor_source}
        </p>
      )}

      {sotp.warnings && sotp.warnings.length > 0 && (
        <ul
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 10,
            color: 'var(--warning)',
            marginTop: 8,
            paddingLeft: 16,
            lineHeight: 1.5,
          }}
        >
          {sotp.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </SubChapter>
  )
}

/**
 * Forward STREET scenario band (Batch 3B v2). A range bar over the 12-month analyst
 * price-target distribution (bear/consensus/bull) with the live price marked. The
 * range-position readout is STREET positioning within the sell-side range — labelled
 * as such, NEVER a "robotaxi-success probability" and NEVER the report's price target
 * (the legs are 12-month forward values; the reverse-SOTP floor above is present).
 */
function ScenarioBandBlock({
  band,
  quoteCurrency,
}: {
  band: SOTPScenarioBandShape
  quoteCurrency: string
}): React.ReactElement {
  const { locale } = useI18n()
  const en = locale === 'en'
  const span = band.bull - band.bear
  const posOf = (v: number) => (span > 0 ? ((v - band.bear) / span) * 100 : 0)
  const basePos = Math.max(0, Math.min(100, posOf(band.base)))
  // Marker is clamped to the track; the raw % (can be <0 / >100) rides the readout.
  const currentPos = Math.max(0, Math.min(100, band.range_position * 100))
  const price = (v: number) => formatCurrency(v, quoteCurrency, locale, 2)
  const confColor = band.confidence === 'very_low' ? 'var(--danger)' : 'var(--warning)'

  return (
    <div style={{ marginTop: 18, paddingTop: 14, borderTop: '1px solid var(--border-soft)' }}>
      <div
        style={{
          fontFamily: 'var(--font-display)',
          fontSize: 12,
          letterSpacing: '1.5px',
          color: 'var(--text-secondary)',
          textTransform: 'uppercase',
          marginBottom: 4,
        }}
      >
        {en ? 'Forward Scenario Band' : '前向情景带'}
      </div>
      <p
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-muted)',
          lineHeight: 1.6,
          marginBottom: 14,
        }}
      >
        {en
          ? 'Two calibers, each labelled distinctly: the reverse-SOTP cash-flow floor (a present value, the robotaxi-fails downside) and the 12-month analyst target cluster (forward). The bar positions the live price within the street range — same-caliber street positioning, not the report price target and not a robotaxi-success probability.'
          : '两种口径,各自分标:reverse-SOTP 现金流底(现值,robotaxi 失败态下行)与 12 个月分析师目标价簇(前瞻)。带内标记 = 现价在卖方区间内的位置(同口径卖方定位),既不是研报目标价,也不是 robotaxi 成功概率。'}
      </p>

      {band.cash_flow_floor != null && (
        <div style={{ marginBottom: 14 }}>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9.5,
              letterSpacing: '0.08em',
              color: 'var(--text-dim)',
              textTransform: 'uppercase',
              marginBottom: 3,
            }}
          >
            {en ? 'Cash-flow floor · present value' : '现金流底 · 现值'}
          </div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
            <span style={{ fontSize: 15, fontWeight: 600, color: 'var(--text-primary)' }}>
              {price(band.cash_flow_floor)}
            </span>{' '}
            <span>{en ? '· robotaxi-fails downside' : '· robotaxi 失败态下行'}</span>
            {band.floor_coverage != null && (
              <span>
                {' '}
                · {en ? 'covers' : '覆盖现价'}{' '}
                <span style={{ color: 'var(--text-secondary)' }}>
                  {(band.floor_coverage * 100).toFixed(0)}%
                </span>{' '}
                {en ? 'of the live price' : ''}
              </span>
            )}
          </div>
        </div>
      )}

      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 9.5,
          letterSpacing: '0.08em',
          color: 'var(--text-dim)',
          textTransform: 'uppercase',
          marginBottom: 8,
        }}
      >
        {en ? '12-month analyst targets · forward' : '12 个月分析师目标价 · 前瞻'}
      </div>

      {/* Range bar: track bear→bull, consensus tick, live-price (cyan) marker. */}
      <div style={{ position: 'relative', height: 34 }}>
        <div
          style={{
            position: 'absolute',
            left: `${currentPos}%`,
            top: 0,
            transform: 'translateX(-50%)',
            textAlign: 'center',
          }}
        >
          <div
            style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--accent-cyan)' }}
          >
            {price(band.current_price)}
          </div>
          <div
            style={{ width: 2, height: 9, background: 'var(--accent-cyan)', margin: '2px auto 0' }}
          />
        </div>
        <div
          style={{
            position: 'absolute',
            bottom: 6,
            left: 0,
            right: 0,
            height: 8,
            borderRadius: 'var(--radius-sm)',
            background:
              'linear-gradient(90deg, color-mix(in srgb, var(--primary) 40%, transparent), color-mix(in srgb, var(--secondary) 55%, transparent))',
            border: '1px solid var(--border-soft)',
          }}
        />
        <div
          style={{
            position: 'absolute',
            bottom: 4,
            left: `${basePos}%`,
            transform: 'translateX(-50%)',
            width: 2,
            height: 12,
            background: 'var(--text-secondary)',
          }}
        />
      </div>

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          marginTop: 2,
        }}
      >
        <span style={{ color: 'var(--text-muted)' }}>
          {en ? 'Bear' : '看空'} {price(band.bear)}
        </span>
        <span style={{ color: 'var(--text-secondary)' }}>
          {en ? 'Consensus' : '共识'} {price(band.base)}
        </span>
        <span style={{ color: 'var(--text-muted)' }}>
          {en ? 'Bull' : '看多'} {price(band.bull)}
        </span>
      </div>

      <div
        style={{
          marginTop: 12,
          display: 'flex',
          gap: 12,
          alignItems: 'center',
          flexWrap: 'wrap',
          fontFamily: 'var(--font-mono)',
          fontSize: 10.5,
          color: 'var(--text-muted)',
        }}
      >
        <span>
          {en ? 'Market at' : '现价位于'}{' '}
          <span style={{ color: 'var(--accent-cyan)' }}>
            {(band.range_position * 100).toFixed(1)}%
          </span>{' '}
          {en ? 'of the street range' : '卖方区间'}
        </span>
        <span
          style={{
            padding: '1px 7px',
            borderRadius: 'var(--radius-sm)',
            border: `1px solid ${confColor}`,
            color: confColor,
          }}
        >
          {en ? 'confidence' : '置信'}: {band.confidence}
        </span>
        {band.analyst_count != null && (
          <span>
            · {band.analyst_count} {en ? 'analysts' : '家分析师'}
          </span>
        )}
      </div>

      <p
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          color: 'var(--text-dim)',
          marginTop: 8,
          lineHeight: 1.5,
        }}
      >
        {band.source}
      </p>
    </div>
  )
}
