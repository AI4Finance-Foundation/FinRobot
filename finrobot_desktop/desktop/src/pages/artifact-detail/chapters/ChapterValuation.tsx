import FootballField from '../../../components/charts/FootballField'
import WaterfallChart from '../../../components/charts/WaterfallChart'
import { useI18n } from '../../../i18n'
import { TermTip } from '../../../components/TermTip'
import { formatCurrency, formatCurrencyCompact } from '../../../utils/format'
import { Chapter, KvGrid, Narrative, SubChapter } from './ChapterBase'
import { FieldCaveat, findingsFor } from './FieldCaveat'
import type {
  DcfShape,
  ForwardEstimatesShape,
  NumericAuditShape,
  SOTPBreakdownShape,
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
}

export function ChapterValuation({
  dcf,
  thesis,
  valuationSynthesis,
  forwardEstimates,
  sotpBreakdown,
  quoteCurrency,
  reportingCurrency,
  numericAudit = null,
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

  // REVIEW echo: in REVIEW state financial_modeling.implied_price is null, so the
  // "DCF Implied Price" cell drops and the grid looks "缺数". Lead the chapter with
  // a compact reverse-DCF banner that echoes the cover headline — the cash-flow
  // ceiling here is the dcf METHOD mid (valuation_synthesis), never implied_price.
  const dcfMethodMid = valuationSynthesis?.methods?.find((m) => m.name === 'dcf')?.mid ?? null
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
          { label: t('chapter.valuation.bridge.netDebt'), value: -(ev - eq), is_total: false },
          { label: t('chapter.valuation.bridge.equity'), value: eq, is_total: true },
        ]
      : []

  type Cell = {
    label: React.ReactNode
    value: string
    delta?: React.ReactNode
    tone?: 'up' | 'down'
  }
  const cells: Cell[] = [
    wacc !== null &&
      ({
        // Headline term explainers: WACC, terminal growth and EV are the DCF
        // levers a non-IB reader most needs unpacked — wrap them in TermTip
        // (hover gloss + "ask FinRobot" deep dive). One wrap per term per chapter.
        label: <TermTip term="WACC" />,
        value: `${(wacc * 100).toFixed(2)}%`,
        delta: beta !== null ? <TermTip term="β">{`β ${beta.toFixed(2)}`}</TermTip> : undefined,
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
        delta: t('chapter.valuation.marketImplied.horizon', { n: mi.horizon_years }),
        tone: (mi.growth_unreachable ? 'down' : undefined) as 'down' | undefined,
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
    <Chapter id="valuation">
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
          <p>{overview}</p>
        </Narrative>
      )}

      {cells.length > 0 ? (
        <KvGrid cells={cells} columns={3} />
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
          {t('chapter.valuation.empty')}
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
    </Chapter>
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
    <SubChapter heading={t('chapter.valuation.sotp.heading')}>
      <p
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--text-muted)',
          lineHeight: 1.6,
          marginBottom: 12,
        }}
      >
        {t('chapter.valuation.sotp.intro')}
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
          {floorPct > 0.12 ? t('chapter.valuation.sotp.floorLabel') : ''}
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
          {t('chapter.valuation.sotp.optionLabel')} {optionPctLabel}
        </div>
      </div>

      {/* Headline scalars */}
      <KvGrid
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
            label: t('chapter.valuation.sotp.impliedOptionEv'),
            value: formatCurrencyCompact(sotp.implied_option_ev, quoteCurrency, locale),
          },
          {
            label: t('chapter.valuation.sotp.impliedOptionPct'),
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
                {t('chapter.valuation.sotp.impliedEv')}
              </th>
            </tr>
          </thead>
          <tbody>
            {sotp.modelable_segments.map((s) => (
              <tr key={s.name} style={{ borderTop: '1px solid var(--border-grid)' }}>
                <td style={{ padding: '4px 8px', color: 'var(--text-primary)' }}>
                  {s.name}
                  <span style={{ display: 'block', color: 'var(--text-dim)', fontSize: 9.5 }}>
                    {s.multiple_source}
                  </span>
                </td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: 'var(--text-secondary)' }}>
                  {formatCurrencyCompact(s.metric_value, reportingCurrency, locale)}
                </td>
                <td style={{ padding: '4px 8px', textAlign: 'right', color: 'var(--text-secondary)' }}>
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
