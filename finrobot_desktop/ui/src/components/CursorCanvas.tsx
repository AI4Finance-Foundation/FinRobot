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
    // Respect prefers-reduced-motion — disable trail for accessibility.
    const mql = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (mql.matches) return

    const handle = mountCursorTrail()
    return () => handle.stop()
  }, [enabled])

  return null
}
