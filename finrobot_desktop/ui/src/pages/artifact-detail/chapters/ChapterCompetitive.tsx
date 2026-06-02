import PeerComparisonChart from '../../../components/charts/PeerComparisonChart'
import CompanyRadarChart from '../../../components/charts/CompanyRadarChart'
import { compsResultToPeerChartData, compsResultToRadarData } from '../../../utils/chartAdapters'
import type { CompsResult } from '../../../stores/appStore'
import { useI18n } from '../../../i18n'
import { formatCompactNumber } from '../../../utils/format'
import { Chapter, Narrative, SubChapter, tableStyle } from './ChapterBase'
import type { PeerCompsShape, ThesisShape } from './types'

interface ChapterCompetitiveProps {
  peers: PeerCompsShape | null
  thesis: ThesisShape | null
}

export function ChapterCompetitive({ peers, thesis }: ChapterCompetitiveProps): React.ReactElement {
  const { t, locale } = useI18n()
  const narrative = thesis?.competitor_analysis ?? null
  const target = peers?.target
  const peerList = peers?.peers ?? []
  const all = target ? [target, ...peerList] : peerList

  // No fitting i18n key for the NOPAT-core caliber — inline literal per the
  // VersionDiffBanner precedent (do not touch .po in this task). The comps
  // price target (football-field "Comps (core P/E)") is computed on this core
  // median, so surfacing it here lets an analyst reconcile target ↔ table.
  const coreLabel =
    locale === 'zh'
      ? {
          header: '核心 P/E',
          tooltip:
            'NOPAT 核心盈利口径 P/E（市值 / NOPAT），剔除非经营性损益。Comps 估值目标用同业核心 P/E 中位数计算，与此列对齐。',
          medianPrefix: '核心 P/E',
        }
      : {
          header: 'Core P/E',
          tooltip:
            'NOPAT core-earnings P/E (market cap / NOPAT), stripping non-operating items. The Comps price target uses the peer core-P/E median, so it reconciles with this column.',
          medianPrefix: 'Core P/E',
        }

  const compsForCharts: CompsResult | null =
    target && peerList.length > 0
      ? ({
          target,
          peers: peerList,
          median_ev_ebitda: peers?.median_ev_ebitda ?? null,
          median_pe: peers?.median_pe ?? null,
          median_ev_revenue: peers?.median_ev_revenue ?? null,
          mean_ev_ebitda: null,
          mean_pe: null,
          peer_justification: peers?.peer_justification ?? '',
          positioning_narrative: peers?.positioning_narrative ?? '',
        } as unknown as CompsResult)
      : null
  const peerBarData = compsForCharts ? compsResultToPeerChartData(compsForCharts) : []
  const radarData = compsForCharts ? compsResultToRadarData(compsForCharts) : []

  return (
    <Chapter id="competitive">
      {narrative && (
        <Narrative>
          <p>{narrative}</p>
        </Narrative>
      )}

      {all.length > 0 ? (
        <table style={tableStyle}>
          <thead style={{ background: 'var(--bg-elevated)' }}>
            <tr>
              <th style={thStyle}>{t('chapter.competitive.col.ticker')}</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>
                {t('chapter.competitive.col.revenue')}
              </th>
              <th style={{ ...thStyle, textAlign: 'right' }}>P/E</th>
              <th
                style={{ ...thStyle, textAlign: 'right', cursor: 'help' }}
                title={coreLabel.tooltip}
              >
                {coreLabel.header}
              </th>
              <th style={{ ...thStyle, textAlign: 'right' }}>EV/EBITDA</th>
              <th style={{ ...thStyle, textAlign: 'right' }}>
                {t('chapter.competitive.col.grossMargin')}
              </th>
              <th style={{ ...thStyle, textAlign: 'right' }}>
                {t('chapter.competitive.col.opMargin')}
              </th>
            </tr>
          </thead>
          <tbody>
            {all.map((c, i) => {
              const isTarget = i === 0 && target !== undefined
              return (
                <tr
                  key={c.ticker}
                  style={
                    isTarget
                      ? { background: 'color-mix(in srgb, var(--accent-cyan) 6%, transparent)' }
                      : undefined
                  }
                >
                  <td
                    style={{
                      ...tdStyle,
                      color: isTarget ? 'var(--accent-cyan)' : 'var(--text-primary)',
                      fontWeight: 500,
                    }}
                  >
                    {c.ticker}
                    {c.name && (
                      <span
                        style={{
                          marginLeft: 8,
                          color: 'var(--text-muted)',
                          fontSize: 11,
                          fontWeight: 300,
                        }}
                      >
                        {c.name}
                      </span>
                    )}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {/* USD assumed — peer comps are US-listed; PeerCompShape
                        carries no currency field. Locale-aware compact units. */}
                    {`$${formatCompactNumber(c.revenue, locale)}`}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {c.pe_ratio !== null && c.pe_ratio !== undefined ? c.pe_ratio.toFixed(1) : '—'}
                  </td>
                  <td
                    style={{
                      ...tdStyle,
                      textAlign: 'right',
                      color: 'var(--accent-cyan)',
                    }}
                  >
                    {c.core_pe_ratio !== null && c.core_pe_ratio !== undefined
                      ? c.core_pe_ratio.toFixed(1)
                      : '—'}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {c.ev_ebitda !== null && c.ev_ebitda !== undefined
                      ? c.ev_ebitda.toFixed(1)
                      : '—'}
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {(c.gross_margin * 100).toFixed(1)}%
                  </td>
                  <td style={{ ...tdStyle, textAlign: 'right' }}>
                    {(c.operating_margin * 100).toFixed(1)}%
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      ) : (
        <p style={mutedNote}>{t('chapter.competitive.empty')}</p>
      )}

      {(peers?.median_pe !== null && peers?.median_pe !== undefined) ||
      (peers?.median_core_pe !== null && peers?.median_core_pe !== undefined) ||
      (peers?.median_ev_ebitda !== null && peers?.median_ev_ebitda !== undefined) ? (
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11.5,
            color: 'var(--text-muted)',
            marginTop: 6,
          }}
        >
          {t('chapter.competitive.peerMedian')}
          {peers.median_pe !== null && peers.median_pe !== undefined && (
            <span style={{ marginLeft: 10, color: 'var(--text-secondary)' }}>
              P/E {peers.median_pe.toFixed(1)}
            </span>
          )}
          {peers.median_core_pe !== null && peers.median_core_pe !== undefined && (
            <span
              style={{ marginLeft: 10, color: 'var(--accent-cyan)', cursor: 'help' }}
              title={coreLabel.tooltip}
            >
              {coreLabel.medianPrefix} {peers.median_core_pe.toFixed(1)}
            </span>
          )}
          {peers.median_ev_ebitda !== null && peers.median_ev_ebitda !== undefined && (
            <span style={{ marginLeft: 10, color: 'var(--text-secondary)' }}>
              EV/EBITDA {peers.median_ev_ebitda.toFixed(1)}
            </span>
          )}
        </p>
      ) : null}

      {peerBarData.length > 0 && (
        <SubChapter heading={t('chapter.competitive.subheading.multiples')}>
          <PeerComparisonChart
            data={peerBarData}
            title={t('chapter.competitive.chart.multiples')}
          />
        </SubChapter>
      )}

      {radarData.length > 0 && (
        <SubChapter heading={t('chapter.competitive.subheading.profile')}>
          <CompanyRadarChart data={radarData} title={t('chapter.competitive.chart.radar')} />
        </SubChapter>
      )}

      {peers?.positioning_narrative && (
        <SubChapter heading={t('chapter.competitive.subheading.positioning')}>
          <p style={{ fontSize: 13, lineHeight: 1.7, color: 'var(--text-secondary)' }}>
            {peers.positioning_narrative}
          </p>
        </SubChapter>
      )}
    </Chapter>
  )
}

const thStyle: React.CSSProperties = {
  padding: '10px 14px',
  textAlign: 'left',
  fontWeight: 500,
  fontSize: 10.5,
  color: 'var(--secondary)',
  letterSpacing: '0.08em',
  textTransform: 'uppercase',
  borderBottom: '1px solid var(--border-soft)',
}
const tdStyle: React.CSSProperties = {
  padding: '9px 14px',
  borderBottom: '1px solid var(--border-faint)',
  color: 'var(--text-secondary)',
  fontVariantNumeric: 'tabular-nums',
}
const mutedNote: React.CSSProperties = {
  fontFamily: 'var(--font-mono)',
  fontSize: 11.5,
  color: 'var(--text-muted)',
  padding: '14px 18px',
  background: 'var(--bg-card-50)',
  border: '1px dashed var(--border-soft)',
  borderRadius: 'var(--radius-sm)',
}
