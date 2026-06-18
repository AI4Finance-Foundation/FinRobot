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
import { deriveReportData, parseSurfacedContractFindings } from './reportData'
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

  // The numeric-audit findings are mirrored into outputs.warnings with a
  // "[NUMERIC-AUDIT/…]" prefix (artifact/builders.py); the output contract adds
  // "[CONTRACT/Cn] …" evidence the same way (artifact/contract.py). Both render
  // richly in the audit banner, so strip them from the generic compute-warnings
  // list at the bottom — otherwise every finding shows twice.
  const allWarnings = d.outputs.warnings ?? []
  const computeWarnings = allWarnings.filter(
    (w) => !w.startsWith('[NUMERIC-AUDIT/') && !w.startsWith('[CONTRACT/'),
  )
  // Analyst-facing hard-clause contract evidence ("[CONTRACT/C1] …"). Internal
  // invariants (C7's no-resurrection scrub) and the "/note" / "/withheld" variants
  // are excluded — only per-clause analyst-facing evidence drives the cover withhold
  // reason + audit banner. (See parseSurfacedContractFindings.)
  const contractFindings = parseSurfacedContractFindings(allWarnings)
  // The cover one-liner = the first clause's evidence (the point target is
  // withheld; the directional verdict still stands).
  const withheldReason = contractFindings[0]?.evidence ?? null

  return (
    <main style={{ minWidth: 0, padding: '12px 0 60px' }}>
      <ChapterAuditBanner audit={d.numericAudit} contractFindings={contractFindings} />
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
        withheldReason={withheldReason}
        // Reverse-DCF withheld-target headline inputs. The cash-flow ceiling comes
        // from the dcf method (valuation_synthesis), NOT dcf.implied_price (null
        // when the target is withheld). current_price is the live pricing anchor.
        marketImplied={d.dcf?.market_implied ?? null}
        dcfMethod={d.valuationSynthesis?.methods?.find((m) => m.name === 'dcf') ?? null}
        currentPrice={d.valuationSynthesis?.current_price ?? null}
        quoteCurrency={d.quoteCurrency}
        // Confidence dial → tier chip + TargetRange band width.
        confidence={d.valuationSynthesis?.confidence ?? null}
        targetLow={d.valuationSynthesis?.target_low ?? null}
        targetHigh={d.valuationSynthesis?.target_high ?? null}
        anchorMethod={d.valuationSynthesis?.anchor_method ?? null}
      />
      <ChapterThesis
        thesis={d.thesis}
        // Same valuation-synthesis provenance the cover restates — the thesis
        // header is a sell-side restatement of the rating, so the target gets a
        // confidence-scaled band + drill-down, not a bare false-precise number.
        confidence={d.valuationSynthesis?.confidence ?? null}
        targetLow={d.valuationSynthesis?.target_low ?? null}
        targetHigh={d.valuationSynthesis?.target_high ?? null}
        anchorMethod={d.valuationSynthesis?.anchor_method ?? null}
        currentPrice={d.valuationSynthesis?.current_price ?? null}
        quoteCurrency={d.quoteCurrency}
      />
      <ChapterCompanyOverview
        thesis={d.thesis}
        rawData={d.inputs.raw_data ?? null}
        historicalMetrics={d.historicalMetrics}
        // Market cap is a quote-currency figure (same arg ChapterFinancialData uses).
        quoteCurrency={d.quoteCurrency}
        dataSource={d.inputs.data_source ?? null}
        fetchedAt={d.inputs.data_fetched_at ?? null}
      />
      <ChapterFinancialAnalysis
        dcf={d.dcf}
        rawData={d.inputs.raw_data ?? null}
        historicalMetrics={d.historicalMetrics}
        reportingCurrency={d.reportingCurrency}
      />
      <ChapterValuation
        dcf={d.dcf}
        thesis={d.thesis}
        valuationSynthesis={d.valuationSynthesis}
        forwardEstimates={d.forwardEstimates}
        sotpBreakdown={d.sotpBreakdown}
        quoteCurrency={d.quoteCurrency}
        reportingCurrency={d.reportingCurrency}
        numericAudit={d.numericAudit}
        // Same EV/EBITDA band the Technical chapter charts — surfaced here as the
        // football field's per-multiple provenance rail (frozen, no live refetch).
        historicalBand={d.technical?.historical_bands ?? null}
      />
      <ChapterSensitivity dcf={d.dcf} quoteCurrency={d.quoteCurrency} />
      <ChapterCatalysts catalysts={d.catalysts} thesis={d.thesis} />
      <ChapterNews thesis={d.thesis} catalysts={d.catalysts} />
      <ChapterCompetitive peers={d.peers} thesis={d.thesis} />
      <ChapterTechnical
        technical={d.technical}
        quoteCurrency={d.quoteCurrency}
        snapshotPrice={d.snapshotPrice}
        snapshotBeta={d.snapshotBeta}
        snapshot52wHigh={d.snapshot52wHigh}
        snapshot52wLow={d.snapshot52wLow}
      />
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
