// FinRobot i18n module — Lingui-backed, zustand-persisted.
//
// Public surface (kept stable so existing call sites don't change):
//   useI18n()         → { locale, setLocale, t(key, params?) }
//   tSync(key, params?) — non-React snapshot read (utils, queries, store actions)
//   useUiPrefs        — zustand store (locale persisted in localStorage)
//   LOCALES           — supported locale list (display in settings dropdown)
//   Locale            — 'zh' | 'en'
//
// Catalogs live in ./locales/{zh,en}/messages.po and are compiled to
// messages.mjs by `npx lingui compile` (run automatically via npm scripts).

import { i18n } from '@lingui/core'
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

import { messages as zhMessages } from './locales/zh/messages.mjs'
import { messages as enMessages } from './locales/en/messages.mjs'

export type Locale = 'zh' | 'en'

export const LOCALES: { code: Locale; label: string; native: string }[] = [
  { code: 'zh', label: 'Chinese', native: '中文' },
  { code: 'en', label: 'English', native: 'English' },
]

// ── Load all catalogs once at module init ─────────────────────────────
i18n.load({ zh: zhMessages as Record<string, string>, en: enMessages as Record<string, string> })

// ── Zustand store: locale persistence ─────────────────────────────────
interface UiPrefsState {
  locale: Locale
  setLocale: (l: Locale) => void
}

function defaultLocale(): Locale {
  // Sync default — async OS-locale detection happens in initLocale() at app startup.
  // We pick 'zh' here for the SSR/first-render frame; detectLocale() may override
  // before the first paint by calling setLocale.
  return 'zh'
}

export const useUiPrefs = create<UiPrefsState>()(
  persist(
    (set) => ({
      locale: defaultLocale(),
      setLocale: (locale) => {
        i18n.activate(locale)
        set({ locale })
      },
    }),
    {
      name: 'finrobot-ui-prefs',
      storage: createJSONStorage(() => localStorage),
      onRehydrateStorage: () => (state) => {
        // After zustand rehydrates from localStorage, activate Lingui with the persisted locale.
        if (state) i18n.activate(state.locale)
      },
    },
  ),
)

// Activate the (possibly default) locale before React mounts so the first paint
// uses real translations. zustand's persist may overwrite this once rehydrated.
i18n.activate(useUiPrefs.getState().locale)

// ── React hook ────────────────────────────────────────────────────────
export function useI18n() {
  const locale = useUiPrefs((s) => s.locale)
  const setLocale = useUiPrefs((s) => s.setLocale)
  const t = (key: string, params?: Record<string, string | number>): string => {
    // Lingui's _() returns the translated string. Missing keys fall back to the
    // key itself (Lingui's default), matching old translate() behaviour.
    return i18n._(key, params ?? {})
  }
  return { locale, setLocale, t }
}

// Helper for non-React code — reads the latest zustand snapshot.
export function tSync(key: string, params?: Record<string, string | number>): string {
  // i18n is already activated for the current locale via zustand setLocale;
  // calling _() directly gets the current locale's translation.
  return i18n._(key, params ?? {})
}

// Re-export the Lingui core instance for advanced consumers (e.g. tests).
export { i18n }
