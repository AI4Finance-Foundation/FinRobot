// Shared bullet list for THESIS-LEVEL qualitative items (string[]): the bull /
// bear case in the Investment Thesis chapter. Tone drives the left-border colour
// (success / danger / warning). Distinct from ChapterCatalysts' CatalystList,
// which renders structured CatalystEventShape rows with impact/probability meters
// — different data caliber (qualitative argument vs dated event).

interface BulletListProps {
  items: string[]
  tone: 'positive' | 'negative' | 'neutral'
}

export function BulletList({ items, tone }: BulletListProps): React.ReactElement {
  const border =
    tone === 'positive'
      ? 'var(--success)'
      : tone === 'negative'
        ? 'var(--danger)'
        : 'var(--warning)'
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {items.map((item, i) => (
        <div
          key={`${tone}-${i}-${item.slice(0, 24)}`}
          style={{
            padding: '10px 14px',
            background: 'var(--bg-card-50)',
            borderLeft: `2px solid ${border}`,
            borderRadius: '0 var(--radius-sm) var(--radius-sm) 0',
            fontSize: 12.5,
            color: 'var(--text-secondary)',
            lineHeight: 1.55,
          }}
        >
          {item}
        </div>
      ))}
    </div>
  )
}
