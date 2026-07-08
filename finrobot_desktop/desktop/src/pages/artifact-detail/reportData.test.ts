// Locks the surfaced-contract-finding parse — specifically that the INTERNAL C7
// no-resurrection scrub never reaches the analyst UI (the cover withhold reason /
// audit banner). Regression for the MU leak where C7's plumbing ("…nulling so it
// cannot resurrect downstream" + a raw float) showed at the top of the report.

import { describe, it, expect } from 'vitest'

import {
  parseSurfacedContractFindings,
  readerFacingComputeWarnings,
  layerComputeWarnings,
  STREET_CONTEXT_MARKER,
} from './reportData'

describe('parseSurfacedContractFindings', () => {
  it('parses analyst-facing hard-clause findings (clause id + evidence)', () => {
    const out = parseSurfacedContractFindings([
      '[CONTRACT/C1] headline target 2172.00 is 2.5x the entry price 864.00, outside the band',
      '[CONTRACT/C2] malformed amount $2172.062.06 (two decimal points)',
    ])
    expect(out).toEqual([
      {
        clause: 'C1',
        evidence: 'headline target 2172.00 is 2.5x the entry price 864.00, outside the band',
      },
      { clause: 'C2', evidence: 'malformed amount $2172.062.06 (two decimal points)' },
    ])
  })

  it('drops the internal C7 scrub — both the bare legacy tag and the /internal form', () => {
    // C7 evidence is engineering plumbing, never an analyst withhold reason. Older
    // artifacts emitted a bare [CONTRACT/C7]; new ones emit [CONTRACT/C7/internal].
    // Neither may surface.
    expect(
      parseSurfacedContractFindings([
        '[CONTRACT/C7] withheld-target artifact still carries a headline 188.11721651475037 in financial_modeling.implied_price — nulling so it cannot resurrect downstream',
      ]),
    ).toEqual([])

    expect(
      parseSurfacedContractFindings([
        '[CONTRACT/C7/internal] withheld-target artifact still carries a headline 188.12 — nulling so it cannot resurrect downstream',
      ]),
    ).toEqual([])
  })

  it('ignores the /note (soft) and /withheld (provenance) variants', () => {
    expect(
      parseSurfacedContractFindings([
        '[CONTRACT/C6/note] single-method headline with no cross-check disclosure',
        '[CONTRACT/withheld] Price target withheld by the output contract; the verdict stands.',
      ]),
    ).toEqual([])
  })

  it('keeps an analyst clause while dropping the internal C7 in a mixed list (MU shape)', () => {
    // MU's real warnings: a method-spread line (generic, not [CONTRACT/]) + the
    // internal C7 scrub + a genuine analyst clause. Only the last should surface.
    const out = parseSurfacedContractFindings([
      'Method spread warning: dcf mid $188.12 deviates 77% from median $803.15',
      '[CONTRACT/C7] withheld-target artifact still carries a headline 188.117 — nulling so it cannot resurrect downstream',
      '[CONTRACT/C1] headline 2172 outside band',
    ])
    expect(out).toEqual([{ clause: 'C1', evidence: 'headline 2172 outside band' }])
  })
})

describe('readerFacingComputeWarnings', () => {
  it('keeps analyst-facing compute caveats verbatim', () => {
    const reader = [
      'Forward P/E based on 4 of 5 peers — 1 without USD-denominated analyst consensus',
      'EV/EBITDA valuation ($266.01) diverges 41% from the cross-method median ($189.27)',
      'Trailing-twelve-month revenue includes a calculated Q4 (full year minus the first nine months), not a separately reported quarter.',
    ]
    expect(readerFacingComputeWarnings(reader)).toEqual(reader)
  })

  it('drops every machine-tagged audit / pre-publish QA line', () => {
    const out = readerFacingComputeWarnings([
      'Forward P/E based on 4 of 5 peers',
      '[NUMERIC-AUDIT/ev_ebitda] enterprise_value=284630945210.52',
      '[CONTRACT/C1] headline 2172 outside band',
      '[REPORT-DRIFT/review] 6/36 narrative $-amounts match no computed value ($4.04) — verify the narrative before publishing',
    ])
    expect(out).toEqual(['Forward P/E based on 4 of 5 peers'])
  })

  it('never leaks "verify the narrative before publishing" to the reader', () => {
    const out = readerFacingComputeWarnings([
      '[REPORT-DRIFT/review] 2/27 narrative $-amounts match no computed value — verify the narrative before publishing',
    ])
    expect(out).toEqual([])
  })

  it('drops blank warning entries before rendering reader-facing bullets', () => {
    const out = readerFacingComputeWarnings(['', '   ', '  Forward P/E based on 4 of 5 peers  '])
    expect(out).toEqual(['Forward P/E based on 4 of 5 peers'])
  })
})

describe('layerComputeWarnings', () => {
  // A realistic MSFT/GOOGL-shape mixed list: ~half template boilerplate, two genuine
  // caveats, one out-of-consensus street disclosure, plus machine-tagged audit lines.
  const STREET = `${STREET_CONTEXT_MARKER} the 12-month target $274.32 sits below the entire sell-side target range ($360.00–$480.00, 42 analysts) — an out-of-consensus call, disclosed for context; it does not alter the verdict or confidence.`
  const METHOD_SPREAD =
    'EV/EBITDA valuation ($623.13) diverges 37% from the cross-method median ($453.40) — wide method spread; treat the point estimate with caution.'
  const RERATING =
    'ev_ebitda: reverting the target to its own 5-year historical multiple implies its price-implied EV/forward-EBITDA must expand from 14.8× to the trailing band mid 23.2× (1.58×) — an unproven mean-reversion premise; judge independently whether that multiple shift is warranted.'
  const TTM = [
    'Trailing-twelve-month revenue includes a calculated Q4 (full year minus the first nine months), not a separately reported quarter.',
    'Trailing-twelve-month revenue: Some quarters were derived from YTD or annual facts. These are calculated values, not directly reported quarterly data.',
    'Trailing-twelve-month net income includes a calculated Q4 (full year minus the first nine months), not a separately reported quarter.',
    'Trailing-twelve-month net income: Some quarters were derived from YTD or annual facts. These are calculated values, not directly reported quarterly data.',
  ]

  const MSFT_WARNINGS = [
    'SEC FILINGS_8K fetch exceeded 30s — SEC slow/unreachable, skipped',
    ...TTM,
    'EV/EBITDA based on 4 of 6 peers — 2 excluded (data quality, or an NM EV/EBITDA above 50x — kept in the set, out of the median)',
    'P/E based on 4 of 6 peers — 2 excluded (loss-making, or an NM trailing P/E above 75x — kept in the set, out of the median)',
    'Forward P/E based on 4 of 6 peers — 2 without USD-denominated analyst consensus, or with an NM forward P/E above 75x (kept in the set, out of the median)',
    'Peers excluded from the comp set (each with its reason below): FTNT: trimmed as excess drop-insurance beyond the 6-peer comp-set cap',
    'PLTR EV/EBITDA 146.97x deviates >5x from peer median 28.54x',
    'PANW P/E 289.11x deviates >9x from peer median 33.60x',
    METHOD_SPREAD,
    RERATING,
    'SEC INSIDER_TRADES fetch exceeded 30s — SEC slow/unreachable, skipped',
    'SEC SCHEDULE_13 fetch exceeded 30s — SEC slow/unreachable, skipped',
    // machine-tagged — must never reach any reader bucket
    '[NUMERIC-AUDIT/ev_ebitda] enterprise_value=284630945210.52',
    '[REPORT-DRIFT/review] 6/36 narrative $-amounts match no computed value — verify the narrative before publishing',
    STREET,
  ]

  it('routes the street-range disclosure OUT of the caveat pile to its own channel', () => {
    const out = layerComputeWarnings(MSFT_WARNINGS)
    expect(out.streetContext).toBe(STREET)
    expect(out.caveats).not.toContain(STREET)
    expect(out.methodologyNotes).not.toContain(STREET)
  })

  it('keeps ONLY the genuine caveats in the ⚠ list (method spread + re-rating)', () => {
    const out = layerComputeWarnings(MSFT_WARNINGS)
    expect(out.caveats).toEqual([METHOD_SPREAD, RERATING])
    // ≤5 is the batch-1a target; no boilerplate leaks up here.
    expect(out.caveats.length).toBeLessThanOrEqual(5)
    for (const w of out.caveats) {
      expect(w.startsWith('Trailing-twelve-month')).toBe(false)
      expect(w.startsWith('SEC ')).toBe(false)
      expect(w).not.toMatch(/ based on \d+ of \d+ peers/)
    }
  })

  it('sinks boilerplate into methodology notes, merging same-family lines', () => {
    const out = layerComputeWarnings(MSFT_WARNINGS)
    const notes = out.methodologyNotes.join('\n')
    // SEC timeouts collapse to one line naming every skipped endpoint (no loss).
    expect(out.methodologyNotes.filter((w) => w.startsWith('SEC EDGAR slow')).length).toBe(1)
    expect(notes).toContain('3 endpoints skipped')
    expect(notes).toContain('FILINGS_8K')
    expect(notes).toContain('INSIDER_TRADES')
    expect(notes).toContain('SCHEDULE_13')
    // Peer-count votes collapse to one line keeping each multiple's count.
    expect(out.methodologyNotes.filter((w) => w.startsWith('Peer multiples computed')).length).toBe(
      1,
    )
    expect(notes).toContain('EV/EBITDA 4 of 6')
    expect(notes).toContain('P/E 4 of 6')
    expect(notes).toContain('Forward P/E 4 of 6')
    // NM-outlier exclusions collapse to one line naming each excluded peer.
    expect(
      out.methodologyNotes.filter((w) => w.startsWith('Excluded from the peer median')).length,
    ).toBe(1)
    expect(notes).toContain('PLTR')
    expect(notes).toContain('PANW')
  })

  it('loses nothing — every reader-facing token stays reachable somewhere', () => {
    const out = layerComputeWarnings(MSFT_WARNINGS)
    const notes = out.methodologyNotes.join('\n')
    // All four TTM lines survive verbatim in the (collapsed) methodology section.
    for (const line of TTM) expect(out.methodologyNotes).toContain(line)
    // The drop-insurance trim + each outlier's identifying values are preserved.
    expect(notes).toContain('FTNT')
    expect(notes).toContain('146.97x')
    expect(notes).toContain('289.11x')
    expect(notes).toContain('28.54x')
  })

  it('never leaks machine-tagged audit / QA lines into any bucket', () => {
    const out = layerComputeWarnings(MSFT_WARNINGS)
    const all = [...out.caveats, ...out.methodologyNotes, out.streetContext ?? '']
    for (const w of all) {
      expect(w).not.toContain('[NUMERIC-AUDIT/')
      expect(w).not.toContain('[REPORT-DRIFT/')
      expect(w).not.toContain('verify the narrative before publishing')
    }
  })

  it('handles the all-boilerplate case (KO shape): empty caveats, null street, everything sunk', () => {
    const koWarnings = [
      'SEC FILINGS_10K fetch exceeded 30s — SEC slow/unreachable, skipped',
      'SEC FILINGS_10Q fetch exceeded 30s — SEC slow/unreachable, skipped',
      ...TTM,
      'Peers excluded from the comp set (each with its reason below): CCEP: trimmed as excess drop-insurance beyond the 6-peer comp-set cap',
    ]
    const out = layerComputeWarnings(koWarnings)
    expect(out.caveats).toEqual([])
    expect(out.streetContext).toBeNull()
    // 1 merged SEC line + 4 TTM + 1 drop-insurance = every input still reachable.
    expect(out.methodologyNotes.length).toBe(6)
    expect(out.methodologyNotes.join('\n')).toContain('CCEP')
  })
})
