// Locks the surfaced-contract-finding parse — specifically that the INTERNAL C7
// no-resurrection scrub never reaches the analyst UI (the cover withhold reason /
// audit banner). Regression for the MU leak where C7's plumbing ("…nulling so it
// cannot resurrect downstream" + a raw float) showed at the top of the report.

import { describe, it, expect } from 'vitest'

import { parseSurfacedContractFindings } from './reportData'

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
