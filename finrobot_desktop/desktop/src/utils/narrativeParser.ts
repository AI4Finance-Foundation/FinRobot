/**
 * Extract a section from markdown narrative by heading keywords.
 * Returns the text under the first matching heading until the next heading, or null.
 * Intentionally fragile — best-effort extraction from free text.
 */
export function extractNarrativeSection(
  narrative: string,
  sectionKeywords: string[],
): string | null {
  const lines = narrative.split('\n')
  let capturing = false
  const result: string[] = []

  for (const line of lines) {
    const isHeading = /^#{1,3}\s+/.test(line)

    if (isHeading) {
      if (capturing) break
      const headingText = line.replace(/^#{1,3}\s+/, '').toLowerCase()
      if (sectionKeywords.some((kw) => headingText.includes(kw))) {
        capturing = true
        continue
      }
    } else if (capturing) {
      result.push(line)
    }
  }

  const text = result.join('\n').trim()
  return text.length > 0 ? text : null
}
