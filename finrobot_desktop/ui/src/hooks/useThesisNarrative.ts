// useThesisNarrative — shared accessor for FinRobot LLM narrative slots.
//
// FootballField / PeersSection / NewsTimeline all want to render the
// thesis-step narrative segments (valuation_overview / competitor_analysis
// / news_summary). Centralise the path-into-Artifact lookup so they don't
// each re-derive it from the unknown outputs blob.

import { useLatestArtifact, useArtifactDetail } from './useV5Artifacts'

export interface ThesisNarrative {
  tagline?: string
  key_takeaways?: string[]
  valuation_overview?: string
  competitor_analysis?: string
  news_summary?: string
  recommendation?: string
  catalysts?: string[]
  risks?: string[]
  narrative?: string
}

/**
 * Pull the thesis dict out of the latest equity_research artifact for the
 * given ticker. Safe across cold-state (no artifact), legacy artifacts (no
 * narrative fields), and the new schema.
 */
export function useThesisNarrative(ticker: string): ThesisNarrative | null {
  const { latest } = useLatestArtifact(ticker, 'equity_research')
  const { data } = useArtifactDetail(latest?.id)
  const raw = (data?.outputs as { structured?: { thesis?: unknown } } | undefined)
    ?.structured?.thesis
  if (!raw || typeof raw !== 'object') return null
  return raw as ThesisNarrative
}
