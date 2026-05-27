// Three-tier initial locale detection.
//
//   1. localStorage (user already changed it before) — handled by zustand persist
//      so we only run when the storage key is absent.
//   2. OS locale via Tauri plugin-os (BCP-47 like "zh-CN" / "en-US").
//   3. Chinese fallback — FinRobot positions Chinese-first.
//
// detectInitialLocale() is async because the Tauri call crosses the IPC bridge.
// Call it once at app startup BEFORE the first React render; see main.tsx.

import { locale as osLocale } from '@tauri-apps/plugin-os'
import type { Locale } from '.'

const STORAGE_KEY = 'finrobot-ui-prefs'

export function hasStoredLocale(): boolean {
  try {
    return !!localStorage.getItem(STORAGE_KEY)
  } catch {
    return false
  }
}

export async function detectInitialLocale(): Promise<Locale> {
  // Tier 1 — stored preference takes precedence. We don't parse it here; we
  // just return early if the caller hasn't already filtered via hasStoredLocale().
  if (hasStoredLocale()) {
    // Caller should have used persisted locale; if we're here anyway, fall through.
  }

  // Tier 2 — OS locale via Tauri. Gracefully falls back to tier 3 if the plugin
  // is unavailable (e.g. browser preview without Tauri runtime).
  try {
    const sys = await osLocale() // e.g. 'zh-CN', 'en-US', 'ja-JP', or null
    const lower = sys?.toLowerCase() ?? ''
    if (lower.startsWith('zh')) return 'zh'
    if (lower.startsWith('en')) return 'en'
  } catch {
    // Tauri plugin-os not available — silently skip.
  }

  // Tier 3 — Chinese-first fallback (FinRobot product positioning).
  return 'zh'
}
