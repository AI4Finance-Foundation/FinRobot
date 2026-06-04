// ResearchPage — the default search-first entry. This is the FinRobot wow
// surface: robot backdrop + ticker search. Opening a ticker lands in the
// single-stock workspace; that workspace auto-enrols the ticker into Coverage.

import { CoverageHero } from '../components/coverage/CoverageHero'

export function ResearchPage(): React.ReactElement {
  return (
    <div
      data-testid="research-page"
      style={{
        height: '100%',
        padding: '20px 24px 24px',
        overflow: 'hidden',
      }}
    >
      <CoverageHero />
    </div>
  )
}
