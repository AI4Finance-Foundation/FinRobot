// Shared bullet list for THESIS-LEVEL qualitative items (string[]): the bull /
// bear case in the Investment Thesis chapter. Tone drives the left-border colour
// (success / danger / warning). This is where the forward-looking bull/bear
// catalysts live — the itemized recent events live in the news feed (ch 08) and
// their aggregate signal in the Catalysts chapter (ch 09).

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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {items.map((item, i) => (
        <div
          key={`${tone}-${i}-${item.slice(0, 24)}`}
          style={{
            padding: '12px 16px',
            background: 'var(--bg-card-50)',
            borderLeft: `2px solid ${border}`,
            borderRadius: '0 var(--radius-sm) var(--radius-sm) 0',
            fontSize: 14,
            color: 'var(--text-secondary)',
            lineHeight: 1.7,
          }}
        >
          {item}
        </div>
      ))}
    </div>
  )
}
