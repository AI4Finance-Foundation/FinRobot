// Cover (chapter 00) — the withheld-target self-explain surface (ArtifactContract
// step 1b). When the point target is withheld, the cover must state WHY at a
// glance and offer a jump to the per-finding audit banner — not just a bare
// "N/A". The directional verdict still ships; only the precise number is held.

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ChapterCover } from './ChapterCover'
import type { DcfShape, ThesisShape } from './types'

const BASE = {
  ticker: 'MU',
  createdAt: '2026-06-08T00:00:00Z',
  artifactId: 'art_MU_equity_research',
  reportType: 'equity_research',
  versionNumber: 1,
  totalVersions: 1,
}

function thesis(partial: Partial<ThesisShape>): ThesisShape {
  return partial as ThesisShape
}

describe('ChapterCover — withheld-target self-explanation', () => {
  it('renders the withheld reason + a jump to the audit banner when the point target is null (verdict still directional)', () => {
    render(
      <ChapterCover
        {...BASE}
        thesis={thesis({ recommendation: 'HOLD' })}
        withheldReason="headline target 2172.00 is 2.5x the entry price 864.00, outside the single-method corroboration band [0.5x, 2x]"
        // The synthesis can still ship a defensible band even when the point is
        // withheld — the range renders without a point tick.
        targetLow={900}
        targetHigh={1400}
        currentPrice={864}
      />,
    )
    const link = screen.getByRole('link')
    expect(link).toHaveAttribute('href', '#report-audit-banner')
    // The reason is visible at a glance on the cover (not buried in the banner).
    expect(screen.getByText(/2\.5x the entry price/)).toBeInTheDocument()
    // The directional badge keeps its hue — never "REVIEW".
    const badge = screen.getByTestId('cover-verdict')
    expect(badge).toHaveAttribute('data-verdict', 'HOLD')
    expect(badge).not.toHaveTextContent('REVIEW')
    // The TargetRange renders in withheld mode (no point tick).
    expect(screen.getByTestId('target-range')).toHaveAttribute('data-withheld', 'true')
  })

  it('suppresses the standalone TargetRange once the reverse-DCF gap headline renders (live price + band drawn once, not duplicated)', () => {
    render(
      <ChapterCover
        {...BASE}
        thesis={thesis({ recommendation: 'HOLD' })}
        withheldReason={null}
        currentPrice={995.87}
        marketImplied={
          {
            horizon_years: 10,
            implied_growth: 0.349,
            growth_unreachable: false,
          } as NonNullable<DcfShape['market_implied']>
        }
        dcfMethod={{
          name: 'dcf',
          low: 157.97,
          mid: 197.46,
          high: 236.96,
          confidence: 0.5,
          source: 'dcf',
        }}
      />,
    )
    // The reverse-DCF gap headline (the verdict-grade visual) renders…
    expect(screen.getByTestId('reverse-dcf-headline')).toBeInTheDocument()
    // …and the standalone TargetRange is NOT also drawn — the live price and the
    // cash-flow band live on the ruler/anchors, never duplicated in a second
    // primitive (this duplication was the cover's "drawn 3-4×" clutter).
    expect(screen.queryByTestId('target-range')).toBeNull()
  })

  it('renders a confidence chip + a non-withheld TargetRange for a normal directional call', () => {
    render(
      <ChapterCover
        {...BASE}
        thesis={thesis({ recommendation: 'BUY', price_target: 130 })}
        withheldReason={null}
        confidence="high"
        targetLow={120}
        targetHigh={140}
        currentPrice={110}
        anchorMethod="dcf"
      />,
    )
    expect(screen.queryByRole('link')).toBeNull()
    const chip = screen.getByTestId('confidence-chip')
    expect(chip).toHaveAttribute('data-confidence', 'high')
    const range = screen.getByTestId('target-range')
    expect(range).toHaveAttribute('data-withheld', 'false')
  })

  it('renders the price-target basis as a labelled line under the hero (promoted from the metadata footer)', () => {
    render(
      <ChapterCover
        {...BASE}
        thesis={thesis({
          recommendation: 'BUY',
          price_target: 130,
          price_target_basis:
            'method-weighted blend: DCF $189 (wt 0.85), Comps (P/E) $193 (wt 0.80), EV/EBITDA $265 (wt 0.72)',
        })}
        withheldReason={null}
        confidence="high"
        targetLow={120}
        targetHigh={140}
        currentPrice={110}
        anchorMethod="dcf"
      />,
    )
    // Promoted to a first-class labelled line — no longer a 10px mono footer suffix
    // jammed beside the compute version.
    expect(screen.getByText('Price Target Basis')).toBeInTheDocument()
    expect(screen.getByText(/method-weighted blend: DCF \$189/)).toBeInTheDocument()
  })

  it('humanizes the report-type metadata line (no raw snake_case enum, no internal package version)', () => {
    render(
      <ChapterCover
        {...BASE}
        thesis={thesis({ recommendation: 'HOLD' })}
        withheldReason={null}
        versionNumber={3}
        totalVersions={3}
      />,
    )
    // "equity_research" reads as "EQUITY RESEARCH" — a raw underscore is
    // developer-ese ("EQUITY_RESEARCH") that leaked onto the analyst-facing
    // cover metadata line.
    const meta = screen.getByTestId('cover-meta')
    expect(meta).toHaveTextContent('EQUITY RESEARCH')
    expect(meta).not.toHaveTextContent('EQUITY_RESEARCH')
    // The version sequence (v3 of 3) is analyst-meaningful and stays; the
    // internal finrobot package version (e.g. "0.1.0") is not and must not
    // render here (it still appears in the Disclaimer's reproducibility footer).
    expect(meta).toHaveTextContent('v3 of 3')
    expect(meta).not.toHaveTextContent('0.1.0')
  })

  it('maps a legacy REVIEW recommendation to a neutral WITHHELD badge, never the word REVIEW', () => {
    render(
      <ChapterCover
        {...BASE}
        thesis={thesis({ recommendation: 'REVIEW' })}
        withheldReason={null}
      />,
    )
    // No contract reason → no link, but the badge still renders neutrally.
    expect(screen.queryByRole('link')).toBeNull()
    const badge = screen.getByTestId('cover-verdict')
    expect(badge).toHaveAttribute('data-verdict', 'REVIEW')
    expect(badge).toHaveTextContent('WITHHELD')
    expect(badge).not.toHaveTextContent('REVIEW')
  })
})

// The withheld-target cover's reverse-DCF "fair-value band" MUST be the DCF
// method's own low/high (a real cash-flow range), NOT valuation_synthesis
// target_low/high. On a method-divergent name (MU) the synthesis target_high is
// a non-cash-flow method (comps P/B), so routing it into the band would both
// mislabel a price/book figure as "cash-flow" and pin the mid marker to the
// band's left edge. This block is the regression lock for that caliber fix.
describe('ChapterCover — reverse-DCF cash-flow band caliber', () => {
  const DCF_METHOD = {
    name: 'dcf',
    low: 157.97,
    mid: 197.46,
    high: 236.96,
    confidence: 0.5,
    source: 'dcf',
  }
  const REACHABLE = {
    horizon_years: 10,
    implied_growth: 0.349,
    growth_unreachable: false,
  } as NonNullable<DcfShape['market_implied']>

  function renderWithheldCover(
    extra: Partial<React.ComponentProps<typeof ChapterCover>> = {},
  ): void {
    render(
      <ChapterCover
        {...BASE}
        thesis={thesis({ recommendation: 'HOLD' })}
        withheldReason={null}
        currentPrice={995.87}
        marketImplied={REACHABLE}
        dcfMethod={DCF_METHOD}
        {...extra}
      />,
    )
  }

  it('draws the band from the DCF method low/high, ignoring a divergent synthesis target band', () => {
    // The synthesis ships a method-divergent target band (a comps P/B high of
    // 1414, like MU) ALONGSIDE the dcf method. The band must follow the dcf
    // method (157.97–236.96), never the target band. This test FAILS under the
    // pre-fix behavior (`fvLow = targetLow ?? dcfMethod.low`), which routed the
    // synthesis target_low/high into the band and showed 900–1414 here.
    renderWithheldCover({ targetLow: 900, targetHigh: 1414 })
    const band = screen.getByTestId('reverse-dcf-band')
    expect(band).toHaveAttribute('data-band-low', '157.97')
    expect(band).toHaveAttribute('data-band-high', '236.96')
    // The human-readable band range restates the same dcf figures (it appears in
    // both the metric card and the value-bar caption), not the target band —
    // guards against a range wired to a different source. The divergent target
    // high (1,414) must NOT surface anywhere.
    expect(screen.getAllByText(/\$157\.97.*\$236\.96/).length).toBeGreaterThan(0)
    expect(screen.queryByText(/1,414/)).toBeNull()
  })

  it('places the DCF mid marker strictly inside the band, not pinned to an edge', () => {
    // The old bug pinned mid to the band's left edge because the band spanned the
    // (wider) target range while mid stayed at the dcf mid. With band == dcf
    // low/high, mid (197.46) sits between low (157.97) and high (236.96). The bar
    // scale (and thus pct) is strictly monotonic in value, so value-interiority
    // ⇒ pixel-interiority; we assert both for an unambiguous lock.
    renderWithheldCover()
    const band = screen.getByTestId('reverse-dcf-band')
    const mid = screen.getByTestId('reverse-dcf-mid')
    const low = Number(band.getAttribute('data-band-low'))
    const high = Number(band.getAttribute('data-band-high'))
    expect(low).toBeLessThan(DCF_METHOD.mid)
    expect(DCF_METHOD.mid).toBeLessThan(high)
    // The marker's own left-% must not collapse onto the band's left edge (the
    // old visual symptom). low=157.97 maps to ~3.8% under the component's scale;
    // mid sits clearly to its right.
    const midPct = Number(mid.getAttribute('data-mid-pct'))
    expect(midPct).toBeGreaterThan(5)
    expect(midPct).toBeLessThan(95)
  })

  it('suppresses the band entirely in the unreachable (option-value) regime', () => {
    // growth_unreachable ⇒ the ceiling is a different solve (ceiling_price) the
    // dcf-method band could sit above, so showFvBand is false and no bar renders.
    renderWithheldCover({
      marketImplied: {
        horizon_years: 10,
        implied_growth: null,
        growth_unreachable: true,
        growth_ceiling: 0.5,
        ceiling_price: 302.57,
      } as NonNullable<DcfShape['market_implied']>,
    })
    // The headline still renders (the ceiling lede), but the band/markers do not.
    expect(screen.getByTestId('reverse-dcf-headline')).toBeInTheDocument()
    expect(screen.queryByTestId('reverse-dcf-band')).toBeNull()
    expect(screen.queryByTestId('reverse-dcf-mid')).toBeNull()
  })

  it('renders the band when the DCF method has a valid low<high range', () => {
    renderWithheldCover()
    expect(screen.getByTestId('reverse-dcf-band')).toBeInTheDocument()
  })
})
