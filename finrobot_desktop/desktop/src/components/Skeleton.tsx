// Shared loading-skeleton primitive.
//
// One shimmer bar, reused by every skeleton placeholder (Kv / catalyst /
// sentiment grids in MarketDataZone, the price-trend card, the market-implied
// panel) so a loading state reflow-matches its loaded content with a single
// visual recipe instead of each surface hand-rolling its own. The global
// `.skeleton` utility is near-invisible on the dark cards, so this paints a
// visible muted gradient (color-mix over var tokens — no hardcoded hex) swept
// by the global `shimmer` keyframe (App.css). Reduced-motion users get the
// frozen flat fallback via that keyframe's media query.

export function SkelBar({
  height,
  width,
  radius = 'var(--r-sm)',
}: {
  height: number
  width: number | string
  radius?: number | string
}): React.ReactElement {
  return (
    <span
      style={{
        display: 'block',
        height,
        width,
        borderRadius: radius,
        background:
          'linear-gradient(90deg, color-mix(in srgb, var(--text-muted) 16%, transparent) 25%, ' +
          'color-mix(in srgb, var(--text-secondary) 34%, transparent) 50%, ' +
          'color-mix(in srgb, var(--text-muted) 16%, transparent) 75%)',
        backgroundSize: '200% 100%',
        animation: 'shimmer 1.4s ease-in-out infinite',
      }}
    />
  )
}
