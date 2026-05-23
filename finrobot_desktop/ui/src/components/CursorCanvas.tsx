// CursorCanvas — React wrapper around mountCursorTrail.
//
// Mounted by AppShell. Reads `cursorTrailEnabled` from uiStore (default
// true, persisted via Settings toggle). When disabled, no canvas exists
// and native cursor returns. When the user toggles, this component
// rebuilds — old handle stops, new mount kicks in.

import { useEffect } from 'react'
import { useUiStore } from '../stores/uiStore'
import { mountCursorTrail } from '../lib/cursorCanvas'

export function CursorCanvas(): null {
  const enabled = useUiStore((s) => s.cursorTrailEnabled)

  useEffect(() => {
    if (!enabled) return
    if (typeof window === 'undefined') return
    // jsdom doesn't ship matchMedia; treat absence as "no reduce preference".
    const mql =
      typeof window.matchMedia === 'function'
        ? window.matchMedia('(prefers-reduced-motion: reduce)')
        : null
    if (mql?.matches) return

    const handle = mountCursorTrail()
    return () => handle.stop()
  }, [enabled])

  return null
}
