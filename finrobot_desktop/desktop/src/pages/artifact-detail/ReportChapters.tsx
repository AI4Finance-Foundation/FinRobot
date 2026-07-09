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
import { deriveReportData, parseSurfacedContractFindings, layerComputeWarnings } from './reportData'
import { ComputeWarningsPanel } from './ComputeWarningsPanel'
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
  // "[CONTRACT/Cn] …" evidence the same way (artifact/contract.py); report-drift
  // adds "[REPORT-DRIFT/review] …" (a pre-publish QA flag). None belong in the
  // reader-facing compute-warnings list — the first two render richly in the audit
  // banner, the last is a builder-only signal. Single source of truth in reportData
  // so the compact viewer agrees (readerFacingComputeWarnings).
  const allWarnings = d.outputs.warnings ?? []
  // Layer the reader-facing warnings: genuine caveats (⚠) vs always-fires template
  // boilerplate (collapsed "Methodology notes") vs the out-of-consensus street-range
  // disclosure (routed to the valuation box on the cover). Single source of truth in
  // reportData so the compact viewer + standalone export layer identically.
  const layered = layerComputeWarnings(allWarnings)
  // Analyst-facing hard-clause contract evidence ("[CONTRACT/C1] …"). Internal
  // invariants (C7's no-resurrection scrub) and the "/note" / "/withheld" variants
  // are excluded — only per-clause analyst-facing evidence drives the cover withhold
  // reason + audit banner. (See parseSurfacedContractFindings.)
  const contractFindings = parseSurfacedContractFindings(allWarnings)
  // The cover one-liner = the first clause's evidence (the point target is
  // withheld; the directional verdict still stands).
  const withheldReason = contractFindings[0]?.evidence ?? null

  // Balance-sheet financial (bank / insurer): the backend withholds the FCFF-DCF,
  // Monte Carlo and EV/EBITDA band at the source (category errors). The single
  // authority is Python's is_balance_sheet_financial, persisted here — the chapters
  // frame the absent panels as "not applicable" rather than "re-run", never
  // re-deriving the classification client-side.
  const financialSector = d.valuationSynthesis?.financial_sector ?? false

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
        // Structured methods + engine-flagged outliers → the readable
        // price-target-basis readout (replaces the raw dev string on the cover).
        methods={d.valuationSynthesis?.methods ?? []}
        outlierMethods={d.valuationSynthesis?.outlier_methods ?? []}
        // Out-of-consensus street-range disclosure, relocated here from the ⚠ pile
        // (beside the target it qualifies). null when the target sits in-band.
        streetContext={layered.streetContext}
      />
      {/* Rating / target / conviction / band live ONCE on the cover above — the
          thesis chapter is the full ARGUMENT: narrative + takeaways → bull/bear
          case → valuation bridge (summary) → market-implied. Every number reads
          from the same derived synthesis the cover / Valuation chapter use. */}
      <ChapterThesis
        thesis={d.thesis}
        valuationSynthesis={d.valuationSynthesis}
        dcf={d.dcf}
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
        // BACKLOG A4 (2026-07-09): segment revenue mix table. Segment metrics
        // are REPORTING currency (mirrors SOTPBreakdownPanel in ChapterValuation).
        segmentOverview={d.segmentOverview}
        reportingCurrency={d.reportingCurrency}
      />
      {/* Competitive landscape precedes the financial build-up: the moat / peer
          context frames how to read the numbers (analyst reading order). */}
      <ChapterCompetitive peers={d.peers} thesis={d.thesis} financialSector={financialSector} />
      <ChapterFinancialAnalysis
        dcf={d.dcf}
        rawData={d.inputs.raw_data ?? null}
        historicalMetrics={d.historicalMetrics}
        reportingCurrency={d.reportingCurrency}
        financialSector={financialSector}
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
      <ChapterSensitivity
        dcf={d.dcf}
        financialSector={financialSector}
        quoteCurrency={d.quoteCurrency}
      />
      {/* News = the itemized, sourced record of recent events; Catalysts = the
          aggregate directional read of that same flow (net sentiment + category
          mix, no re-listing). Each event appears in exactly one of the two. */}
      <ChapterNews thesis={d.thesis} catalysts={d.catalysts} />
      <ChapterCatalysts catalysts={d.catalysts} />
      <ChapterTechnical
        technical={d.technical}
        financialSector={financialSector}
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

      <ComputeWarningsPanel
        caveats={layered.caveats}
        methodologyNotes={layered.methodologyNotes}
        formulaWarnings={d.compute_version?.formula_warnings ?? []}
      />
    </main>
  )
}
