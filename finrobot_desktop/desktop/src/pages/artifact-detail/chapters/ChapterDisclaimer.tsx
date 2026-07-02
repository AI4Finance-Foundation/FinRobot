// Chapter 11 — Disclaimer. Static investment-advice disclaimer + the
// reproducibility footer (artifact id / compute version / created at)
// every analyst-grade report needs.

import { Chapter } from './ChapterBase'
import { formatDate } from '../../../utils/format'
import { useI18n } from '../../../i18n'
import { FOUNDATION_NAME, SITE_LABEL } from '../../../config/links'

interface ChapterDisclaimerProps {
  artifactId: string
  createdAt: string | null
  computeVersion: string | null
}

export function ChapterDisclaimer({
  artifactId,
  createdAt,
  computeVersion,
}: ChapterDisclaimerProps): React.ReactElement {
  const { locale } = useI18n()
  const isEn = locale === 'en'
  return (
    <Chapter id="disclaimer">
      <div
        style={{
          background: 'var(--bg-card-50)',
          border: '1px dashed var(--border-soft)',
          borderRadius: 'var(--radius-md)',
          padding: '18px 22px',
          fontSize: 11.5,
          lineHeight: 1.75,
          color: 'var(--text-muted)',
        }}
      >
        {isEn ? (
          <>
            <p>
              <strong style={{ color: 'var(--text-secondary)' }}>
                FinRobot equity research reports are AI-generated combinations of deterministic
                financial computations and large-language-model narrative synthesis.
              </strong>{' '}
              All financial data is sourced from regulatory filings (SEC 10-K / 10-Q), market data
              providers (yfinance, FMP, Finnhub), and public news. Forecasts are model outputs, not
              predictions. The recommendation (BUY / HOLD / SELL) and price target reflect the
              model's interpretation as of the report date and may not be revised in response to
              subsequent events.
            </p>
            <p style={{ marginTop: 12 }}>
              This material is for informational purposes only and does not constitute investment
              advice, an offer or solicitation to buy or sell any security, or a recommendation to
              engage in any transaction. Past performance does not guarantee future results. Readers
              should conduct their own due diligence and consult licensed financial advisors before
              making investment decisions.
            </p>
            <p style={{ marginTop: 12 }}>
              FinRobot and its contributors disclaim any liability for losses arising from reliance
              on this report. Apache-2.0 licensed open-source software, provided "as is" without
              warranty.
            </p>
          </>
        ) : (
          <>
            <p>
              <strong style={{ color: 'var(--text-secondary)' }}>
                FinRobot 股票研报由确定性金融计算与大语言模型叙事合成共同生成。
              </strong>{' '}
              全部财务数据来自监管文件（SEC 10-K / 10-Q）、行情数据源（yfinance、FMP、Finnhub）以及
              公开新闻。预测均为模型输出，不构成结果预测。研报中的评级（买入 / 持有 / 卖出）与目标价
              代表模型在研报生成日的判断，后续事件不会自动触发修订。
            </p>
            <p style={{ marginTop: 12 }}>
              本研报仅供参考，不构成任何形式的投资建议，亦不构成买入或卖出任何证券的要约或邀请。
              过往业绩不代表未来表现。读者应在投资前自行尽职调查，并咨询有执业资格的金融顾问。
            </p>
            <p style={{ marginTop: 12 }}>
              FinRobot 及其贡献者对任何因依赖本研报而产生的损失不承担任何责任。本软件以 Apache-2.0
              开源协议发布，按"现状"提供，不附带任何明示或暗示的担保。
            </p>
          </>
        )}
        <p
          style={{
            marginTop: 16,
            paddingTop: 12,
            borderTop: '1px solid var(--border-faint)',
            fontFamily: 'var(--font-mono)',
            fontSize: 10.5,
            color: 'var(--text-dim)',
          }}
        >
          {/* Full ID, not a truncated prefix — every artifact ID shares the same
              "art_<date>T…" prefix (created-at timestamp), so slicing the first
              N characters rendered visually-identical, zero-information IDs
              across every report generated on the same day. */}
          {isEn ? 'ID' : '编号'} {artifactId} ·{' '}
          {computeVersion && (
            <>
              {isEn ? 'COMPUTE' : '计算版本'} {computeVersion} ·{' '}
            </>
          )}
          {createdAt && (
            <>
              {isEn ? 'GENERATED' : '生成时间'} {formatDate(createdAt, locale, 'datetime')}
            </>
          )}
        </p>
        <p
          style={{
            marginTop: 10,
            fontFamily: 'var(--font-mono)',
            fontSize: 10.5,
            letterSpacing: 0.2,
            color: 'var(--text-muted)',
          }}
        >
          {isEn ? 'Copyright' : '版权所有'} © {FOUNDATION_NAME} · {SITE_LABEL}
        </p>
      </div>
    </Chapter>
  )
}
