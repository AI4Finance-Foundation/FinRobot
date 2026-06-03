import { useQuery } from '@tanstack/react-query'
import FootballField from '../../../components/charts/FootballField'
import WaterfallChart from '../../../components/charts/WaterfallChart'
import { BASE_URL } from '../../../api/client'
import { fetchWithTimeout, HEAVY_API_TIMEOUT_MS } from '../../../api/fetch'
import { useI18n } from '../../../i18n'
import { TermTip } from '../../../components/TermTip'
import { Chapter, KvGrid, Narrative, SubChapter } from './ChapterBase'
import type { DcfShape, ThesisShape } from './types'

interface ValuationMethodRange {
  method: string
  method_type: string
  low: number
  mid: number
  high: number
  confidence: number
  source: string
  warnings: string[]
}

interface ValuationAggregate {
  ticker: string
  current_price: number | null
  methods: ValuationMethodRange[]
  warnings: string[]
}

function useValuationAggregate(ticker: string | null | undefined) {
  return useQuery<ValuationAggregate, Error>({
    queryKey: ['valuation-aggregate', ticker],
    queryFn: async () => {
      const resp = await fetchWithTimeout(
        `${BASE_URL}/api/valuation/aggregate/${ticker}`,
        {},
        HEAVY_API_TIMEOUT_MS,
      )
      if (!resp.ok) throw new Error(`${resp.status}`)
      return (await resp.json()) as ValuationAggregate
    },
    enabled: !!ticker,
    staleTime: 10 * 60_000,
    refetchOnMount: false,
    retry: 0,
  })
}

interface ChapterValuationProps {
  dcf: DcfShape | null
  thesis: ThesisShape | null
  ticker: string
}

export function ChapterValuation({
  dcf,
  thesis,
  ticker,
}: ChapterValuationProps): React.ReactElement {
  const { t } = useI18n()
  const overview = thesis?.valuation_overview ?? null
  const wacc = dcf?.wacc ?? null
  const terminalGrowth = dcf?.inputs?.terminal_growth_rate ?? null
  const taxRate = dcf?.inputs?.tax_rate ?? null
  const beta = dcf?.inputs?.beta ?? null
  const implied = dcf?.implied_price ?? null
  const ev = dcf?.enterprise_value ?? null
  const eq = dcf?.equity_value ?? null

  const { data: aggregate } = useValuationAggregate(ticker)
  const footballRows = (aggregate?.methods ?? []).map((m) => ({
    method: m.method,
    low: m.low,
    mid: m.mid,
    high: m.high,
    // Caliber/source string from valuation_aggregator (e.g. "peer_median_core_pe
    // × core_eps（NOPAT 核心盈利口径…）"). FootballField uses it to label the comps
    // row by its actual caliber so the target reconciles with the comps table.
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
        value: `$${implied.toFixed(2)}`,
        tone: (thesis?.price_target && implied >= thesis.price_target ? 'up' : undefined) as
          | 'up'
          | undefined,
      } as Cell),
    ev !== null &&
      ({
        label: <TermTip term="EV">{t('chapter.valuation.kv.enterpriseValue')}</TermTip>,
        value: fmtTrillions(ev),
      } as Cell),
    eq !== null &&
      ({ label: t('chapter.valuation.kv.equityValue'), value: fmtTrillions(eq) } as Cell),
  ].filter((c): c is Cell => Boolean(c))

  return (
    <Chapter id="valuation">
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
            currentPrice={aggregate?.current_price ?? undefined}
          />
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
            ${thesis.price_target.toFixed(2)}
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

function fmtTrillions(v: number): string {
  if (Math.abs(v) >= 1e12) return `$${(v / 1e12).toFixed(2)}T`
  if (Math.abs(v) >= 1e9) return `$${(v / 1e9).toFixed(2)}B`
  return `$${v.toFixed(0)}`
}
