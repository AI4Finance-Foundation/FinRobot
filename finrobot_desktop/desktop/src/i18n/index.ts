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
  // The app currently ships English-only: there is no in-app language switcher
  // and English is the single active locale. The i18n machinery (catalogs,
  // LOCALES, useI18n/t/tSync, the persisted store, the backend `lang` param)
  // is kept intact so re-enabling multi-language is a matter of re-adding the
  // selector — not rebuilding the plumbing.
  return 'en'
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

// ── Missing-key guard ─────────────────────────────────────────────────
// Lingui's _() falls back to the raw dotted id ("coverage.reason.quote_stale")
// when a key is absent — developer language on an analyst-facing surface.
// Several call sites build keys dynamically (t(`prefix.${backendValue}`)), so
// a new backend enum value must degrade to READABLE copy, not a raw key.
// This guard is the single throat for that rule: every t()/tSync() goes
// through it, so no per-call-site whitelist can drift.

const CATALOGS: Record<Locale, Record<string, unknown>> = {
  zh: zhMessages as Record<string, unknown>,
  en: enMessages as Record<string, unknown>,
}

/** Readable fallback for a missing key: last dot-segment, with underscores /
 * hyphens / camelCase split into plain words ("quote_stale" → "quote stale"). */
function humanizeKey(key: string): string {
  const last = key.split('.').pop() ?? key
  return last
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z\d])([A-Z])/g, '$1 $2')
    .toLowerCase()
    .trim()
}

function translate(key: string, params?: Record<string, string | number>): string {
  const { locale } = useUiPrefs.getState()
  if (key in CATALOGS[locale]) return i18n._(key, params ?? {})
  // Active catalog misses the key — try the other locale before humanizing so
  // a partially-translated key still shows real copy rather than a guess.
  const other: Locale = locale === 'zh' ? 'en' : 'zh'
  if (key in CATALOGS[other]) {
    const saved = i18n.locale
    i18n.activate(other)
    try {
      return i18n._(key, params ?? {})
    } finally {
      i18n.activate(saved)
    }
  }
  if (import.meta.env?.DEV) {
    console.warn(`[i18n] missing catalog key: ${key}`)
  }
  return humanizeKey(key)
}

// ── React hook ────────────────────────────────────────────────────────
export function useI18n() {
  const locale = useUiPrefs((s) => s.locale)
  const setLocale = useUiPrefs((s) => s.setLocale)
  const t = (key: string, params?: Record<string, string | number>): string =>
    translate(key, params)
  return { locale, setLocale, t }
}

// Helper for non-React code — reads the latest zustand snapshot.
export function tSync(key: string, params?: Record<string, string | number>): string {
  // i18n is already activated for the current locale via zustand setLocale;
  // the guard reads the same snapshot, so both paths share one fallback rule.
  return translate(key, params)
}

// Re-export the Lingui core instance for advanced consumers (e.g. tests).
export { i18n }
