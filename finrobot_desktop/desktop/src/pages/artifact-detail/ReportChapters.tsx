// The report body — 13 chapters rendered from a single artifact. Shared by the
// in-app detail page (ArtifactDetailPage) and the standalone HTML export viewer
// (src/export/viewer.tsx) so both render byte-identical chapter content,
// interactions included (Recharts tooltips, heatmap, football field).
//
// This is ONLY the <main> column. The surrounding chrome (toolbar, TOC,
// right-rail, status bar) lives in ArtifactDetailPage and is intentionally NOT
// part of the export — the deliverable is the research, not the workstation UI.

import type { ArtifactDetail } from '../../hooks/useV5Artifacts'
import type { ArtifactSummaryV5 } from '../../types/v5'
import { useI18n } from '../../i18n'
import { deriveReportData } from './reportData'
import {
  ChapterAuditBanner,
  ChapterCover,
  ChapterThesis,
  ChapterCompanyOverview,
  ChapterFinancialAnalysis,
  ChapterValuation,
  ChapterNews,
  ChapterSensitivity,
  ChapterCatalysts,
  ChapterTechnical,
  ChapterCompetitive,
  ChapterFinancialData,
  ChapterOwnershipGovernance,
  ChapterDisclaimer,
} from './chapters'

export function ReportChapters({
  artifact,
  timeline,
}: {
  artifact: ArtifactDetail
  timeline: ArtifactSummaryV5[]
}): React.ReactElement {
  const { locale, t } = useI18n()
  const d = deriveReportData(artifact, timeline, locale)
  // UI-locale-vs-prose-language mismatch is a workstation affordance; the export
  // activates the report's own language, so this is naturally false there.
  const langMismatch = d.reportLang !== locale

  // The numeric-audit findings are ALSO mirrored into outputs.warnings with a
  // "[NUMERIC-AUDIT/…]" prefix (artifact/builders.py). The dedicated audit banner
  // already renders them richly at the top, so strip them from the generic
  // compute-warnings list at the bottom — otherwise every finding shows twice.
  const computeWarnings = (d.outputs.warnings ?? []).filter((w) => !w.startsWith('[NUMERIC-AUDIT/'))

  return (
    <main style={{ minWidth: 0, padding: '12px 0 60px' }}>
      <ChapterAuditBanner audit={d.numericAudit} />
      {langMismatch && (
        <div
          data-testid="report-lang-mismatch"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            padding: '10px 14px',
            marginBottom: 16,
            borderRadius: 8,
            fontSize: 13,
            lineHeight: 1.5,
            color: 'var(--text-secondary)',
            background: 'var(--surface-2)',
            border: '1px solid var(--border)',
          }}
        >
          <span aria-hidden style={{ fontSize: 15 }}>
            🌐
          </span>
          <span>
            {t('report.lang.mismatch', {
              lang: t(d.reportLang === 'zh' ? 'report.lang.zh' : 'report.lang.en'),
            })}
          </span>
        </div>
      )}
      <ChapterCover
        ticker={d.symbol}
        thesis={d.thesis}
        createdAt={d.createdAt}
        artifactId={artifact.id}
        computeVersion={d.computeVersionStr}
        reportType={artifact.type}
        versionNumber={d.versionNumber}
        totalVersions={d.totalVersions}
      />
      <ChapterThesis thesis={d.thesis} />
      <ChapterCompanyOverview thesis={d.thesis} />
      <ChapterFinancialAnalysis
        ticker={d.symbol}
        dcf={d.dcf}
        rawData={d.inputs.raw_data ?? null}
        reportingCurrency={d.reportingCurrency}
      />
      <ChapterValuation
        dcf={d.dcf}
        thesis={d.thesis}
        valuationSynthesis={d.valuationSynthesis}
        forwardEstimates={d.forwardEstimates}
        quoteCurrency={d.quoteCurrency}
        reportingCurrency={d.reportingCurrency}
        numericAudit={d.numericAudit}
      />
      <ChapterNews thesis={d.thesis} />
      <ChapterSensitivity dcf={d.dcf} quoteCurrency={d.quoteCurrency} />
      <ChapterCatalysts catalysts={d.catalysts} thesis={d.thesis} />
      <ChapterTechnical
        technical={d.technical}
        quoteCurrency={d.quoteCurrency}
        snapshotPrice={d.snapshotPrice}
        snapshotBeta={d.snapshotBeta}
        snapshot52wHigh={d.snapshot52wHigh}
        snapshot52wLow={d.snapshot52wLow}
      />
      <ChapterCompetitive peers={d.peers} thesis={d.thesis} />
      <ChapterFinancialData
        rawData={d.inputs.raw_data ?? null}
        dataSource={d.inputs.data_source ?? null}
        fetchedAt={d.inputs.data_fetched_at ?? null}
        ticker={d.symbol}
        quoteCurrency={d.quoteCurrency}
        reportingCurrency={d.reportingCurrency}
      />
      <ChapterOwnershipGovernance ownership={d.ownership} reportingCurrency={d.reportingCurrency} />
      <ChapterDisclaimer
        artifactId={artifact.id}
        createdAt={d.createdAt}
        computeVersion={d.computeVersionStr}
      />

      {computeWarnings.length > 0 ||
      (d.compute_version?.formula_warnings && d.compute_version.formula_warnings.length > 0) ? (
        <section
          data-testid="report-warnings"
          style={{
            margin: '32px 0',
            padding: '14px 18px',
            background: 'color-mix(in srgb, var(--warning) 6%, transparent)',
            border: '1px solid color-mix(in srgb, var(--warning) 32%, transparent)',
            borderRadius: 'var(--radius-sm)',
            fontSize: 12,
            color: 'var(--warning)',
          }}
        >
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 10.5,
              letterSpacing: '0.08em',
              marginBottom: 6,
            }}
          >
            ⚠ {t('report.computeWarnings')}
          </div>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {computeWarnings.map((w, i) => (
              <li key={`o-${i}`} style={{ marginBottom: 4 }}>
                {w}
              </li>
            ))}
            {(d.compute_version?.formula_warnings ?? []).map((w, i) => (
              <li key={`f-${i}`} style={{ marginBottom: 4 }}>
                {w}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </main>
  )
}
