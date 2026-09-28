// ResearchPage — the default search-first entry. This is the FinRobot wow
// surface: the research cockpit (SplineHero robot presiding over the ticker
// console + capability dock). Opening a ticker lands in the single-stock
// workspace; that workspace auto-enrols the ticker into Coverage.
//
// Full-bleed: CoverageHero owns its own internal spacing and docks the
// capability bay to the bottom edge, so the page wrapper adds no padding.

import { CoverageHero } from '../components/coverage/CoverageHero'

export function ResearchPage(): React.ReactElement {
  return (
    <div data-testid="research-page" style={{ height: '100%', overflow: 'hidden' }}>
      <CoverageHero />
    </div>
  )
}
