// First-launch locale detection.
//
// Precedence:
//   1. Stored preference (user already picked a language) — owned by zustand
//      persist; detection is skipped entirely when hasStoredLocale() is true.
//   2. OS locale via Tauri plugin-os (BCP-47 like "zh-CN" / "en-US").
//   3. Chinese fallback — FinRobot is Chinese-first when the OS gives no hint.
//
// detectInitialLocale() is async because the Tauri call crosses the IPC bridge.
// main.tsx awaits it once before the first render, only when no stored
// preference exists; thereafter setLocale() persists the choice so this never
// runs again.

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
  // OS locale via Tauri. Gracefully falls back to Chinese if the plugin is
  // unavailable (e.g. browser preview without the Tauri runtime).
  try {
    const sys = await osLocale() // e.g. 'zh-CN', 'en-US', 'ja-JP', or null
    const lower = sys?.toLowerCase() ?? ''
    if (lower.startsWith('zh')) return 'zh'
    if (lower.startsWith('en')) return 'en'
  } catch {
    // Tauri plugin-os not available — fall through to the Chinese default.
  }
  return 'zh'
}
