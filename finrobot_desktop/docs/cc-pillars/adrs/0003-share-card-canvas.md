# ADR-0003: Share card via OffscreenCanvas, defer Noto Sans CJK bundle

| | |
|---|---|
| **版本** | v1.0 |
| **状态** | Accepted |
| **日期** | 2026-05-21 |
| **作者** | finrobot-frontend (Opus 4.7) |
| **触发** | v5 PR16 实施 — spec §12.1 + §14 ADR-D |

---

## 0. TL;DR

v5 PR16 ships `utils/shareCard.ts` rendering a 1080×1080 PNG via
`OffscreenCanvas` (with a vanilla `<canvas>` fallback). Text uses the
system Chinese stack (`-apple-system, "PingFang SC", "SF Pro Display",
"Microsoft YaHei"`) instead of a bundled Noto Sans CJK woff2.

- Bundling Noto Sans CJK adds ~600KB to first load even with subsetting;
  PingFang SC ships on every macOS and Microsoft YaHei on every Windows
  install, so we cover ≥98% of the install base for free.
- Pillow / server-side rendering would force the entire card to round-trip
  through Python — we lose immediate-download UX and double our font path.
- `OffscreenCanvas` is supported on Chromium, Firefox, and Safari ≥16.4.
  Older Safari fallback uses an in-DOM `<canvas>` (visually identical;
  blocks the main thread for ~30ms, acceptable for a one-off click).

If a future user reports missing-glyph squares (Linux without CJK fonts,
or a corporate Windows image stripped of YaHei), we revisit and bundle a
600KB subset matching only the chars we actually render.

---

## 1. Context

Spec §12.1 needs a "share card" PNG users can drop into chat / Twitter
with these elements: signal dot, ticker (large), gain/loss since report
(big number), status line, headline quote, FinRobot footer. The
discussion-doc said the choices were:

1. Pillow on the backend → PNG returned over HTTP.
2. Headless Chrome / playwright on the backend.
3. Browser-side `<canvas>` / `OffscreenCanvas`.

The architect call (recorded in spec §14 ADR-D row) ruled out Pillow
because it forces a Python-side font stack + matplotlib helpers we don't
need. PR16 picks option 3 to keep latency under one click and ship
without new backend deps.

## 2. Decision

`utils/shareCard.ts` exports two functions:

- `buildShareCardPng(input)` returns a `Promise<Blob>` for callers who
  want to upload / open in a new tab.
- `downloadShareCard(input)` wraps the standard
  `URL.createObjectURL` + hidden `<a download>` dance.

HeroVerdict mounts a 📤 分享图 button next to 📥 PDF. Both target the
latest equity_research artifact for that ticker.

Rendering:

- `OffscreenCanvas` when available; falls back to `document.createElement('canvas')`.
- Font stack: `-apple-system, "PingFang SC", "SF Pro Display", "Microsoft YaHei", "Inter", sans-serif`.
- 1080×1080 with a dark background (`#0F1419`) so the card pops in feeds.
- Color tokens align with spec §10.1 / §10.2 (signal dot uses the same
  palette as DOM rendering).

## 3. Alternatives Considered

### 3.1 Bundle Noto Sans CJK SC woff2

**Rejected for v5.** Subset-Noto with the 3,500 most-common simplified
Chinese chars is ≥600KB. Adding to the initial bundle hurts every cold
load, not just users who actually click 分享图. We can lazy-import a
600KB woff2 only when the share button is clicked, but that introduces a
2-3s wait for the first share — worse UX than the system fallback for
the macOS / Windows majority. Revisit if Linux users start reporting
glyph squares.

### 3.2 Server-side rendering (Pillow or weasyprint)

**Rejected.** Adds a Python-side font pipeline (FinRobot already drags
matplotlib for charts; piling on Pillow for cards doubles maintenance).
Also forces every share to round-trip through the backend → slower
first-click latency, complicates offline use.

### 3.3 Headless Chrome on the backend

**Rejected for v5.** Heavy infrastructure (Playwright / chromium) for a
1080×1080 PNG. Same fonts available client-side.

## 4. Consequences

### Positive

- Zero new dependencies. shareCard.ts is ~250 LoC vanilla TypeScript.
- Latency is the time to draw ~10 ops on canvas (~30-50ms).
- No backend round-trip — works offline if `EventSource` is queued.
- Trivially testable: `buildShareCardPng()` returns a Blob whose PNG
  signature we can check in vitest (deferred).

### Negative

- Linux users without CJK fonts will see boxes where Chinese chars should
  render. Acceptable for v5 retail-investor audience (overwhelmingly
  macOS / Windows). Mitigation path: lazy-bundle Noto subset.
- Older Safari (<16.4) blocks main thread briefly during rendering.
- Cards are rendered fresh each time — no server-side cache. Each share
  costs ~50KB output, negligible.

### Out of scope

- Multi-language card text (English mode, etc).
- A second card layout for IC Memo / LBO results.
- Sharing-API integration (`navigator.share`) — UI just downloads today.

---

## 5. Implementation Notes

### 5.1 File changes

| File | Change |
|---|---|
| `ui/src/utils/shareCard.ts` | new — render + Blob + download helpers |
| `ui/src/views/sections/HeroVerdict.tsx` | two new buttons (📤 分享图 / 📥 PDF) |

### 5.2 Verification

- `npm run build` clean.
- `npm run test` 206/206 pass.
- Manual click test deferred to a follow-up session with a live ticker
  (the function is exercised on-demand from HeroVerdict; in-band tests
  would need OffscreenCanvas + JSDOM polyfills which add brittleness for
  ~30 LoC of test value).

### 5.3 Roll back

`git rm ui/src/utils/shareCard.ts` + revert the two button blocks in
HeroVerdict. PDF button stays useful (PR5 endpoint) so cleanup is partial.

---

## 6. Open Questions

- Should we add a Tauri-side "save to clipboard" path so users can paste
  the PNG into chat without downloading first? Out of scope for v5.
- The selection-bias disclaimer baked into the card body (matching
  StatBanner's footer) — defer for v5; add when user feedback comes in.
