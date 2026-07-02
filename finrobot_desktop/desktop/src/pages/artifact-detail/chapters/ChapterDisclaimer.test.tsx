// Chapter 11 — Disclaimer reproducibility footer. Locks the artifact ID
// rendering: every ID shares the same "art_<created-at-timestamp>_…" prefix
// (see builders.py), so truncating to the first N characters produced a
// visually-identical, zero-information ID across every report generated the
// same day — the footer must render the full ID.

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'

import { ChapterDisclaimer } from './ChapterDisclaimer'

describe('ChapterDisclaimer — reproducibility footer', () => {
  it('renders the full artifact ID, not a truncated same-day-collision prefix', () => {
    const artifactId = 'art_2026-07-02T16:41:23_TSM_equity_research_988425'
    render(
      <ChapterDisclaimer
        artifactId={artifactId}
        createdAt="2026-07-02T16:41:23Z"
        computeVersion="0.1.0"
      />,
    )
    expect(screen.getByText(new RegExp(artifactId))).toBeInTheDocument()
  })
})
