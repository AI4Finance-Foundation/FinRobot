// Shared horizontal frame width for the stock workspace. The back bar, the
// identity hero, and the two-column scroll region all centre to this same max so
// the ticker glyph's left edge lines up with the market card's edge. Hoisted to
// ONE constant because three sites must stay in lockstep — they previously each
// hardcoded the value with a "keep in sync" comment, exactly the drift trap a
// constant removes.
//
// Raised 1320 → 1600 so wide monitors don't leave the dashboard floating in big
// empty side margins. Pair it with the grid's CAPPED AI column (in
// StockWorkspace) so the extra width flows to the dense market/data column, not
// the sparse research card.
export const WORKSPACE_FRAME_MAX_WIDTH = 1600
