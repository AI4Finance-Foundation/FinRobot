// Chapter 11 — Disclaimer. Static investment-advice disclaimer + the
// reproducibility footer (artifact id / compute version / created at)
// every analyst-grade report needs.

import { Chapter } from './ChapterBase'

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
  return (
    <Chapter id="disclaimer" num="11" title="Disclaimer" sub="Investment Advice Notice">
      <div
        style={{
          background: 'rgba(15, 15, 34, 0.5)',
          border: '1px dashed var(--border-soft)',
          borderRadius: 'var(--radius-md)',
          padding: '18px 22px',
          fontSize: 11.5,
          lineHeight: 1.75,
          color: 'var(--text-muted)',
        }}
      >
        <p>
          <strong style={{ color: 'var(--text-secondary)' }}>
            FinAgent equity research reports are AI-generated combinations of deterministic
            financial computations and large-language-model narrative synthesis.
          </strong>{' '}
          All financial data is sourced from regulatory filings (SEC 10-K / 10-Q), market data
          providers (yfinance, FMP, Finnhub), and public news. Forecasts are model outputs, not
          predictions. The recommendation (BUY / HOLD / SELL) and price target reflect the model's
          interpretation as of the report date and may not be revised in response to subsequent
          events.
        </p>
        <p style={{ marginTop: 12 }}>
          This material is for informational purposes only and does not constitute investment
          advice, an offer or solicitation to buy or sell any security, or a recommendation to
          engage in any transaction. Past performance does not guarantee future results. Readers
          should conduct their own due diligence and consult licensed financial advisors before
          making investment decisions.
        </p>
        <p style={{ marginTop: 12 }}>
          FinAgent and its contributors disclaim any liability for losses arising from reliance on
          this report. Apache-2.0 licensed open-source software, provided "as is" without warranty.
        </p>
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
          ARTIFACT {artifactId} ·{' '}
          {computeVersion && <>COMPUTE {computeVersion} · </>}
          {createdAt && <>GENERATED {new Date(createdAt).toLocaleString('zh-CN')}</>}
        </p>
      </div>
    </Chapter>
  )
}
