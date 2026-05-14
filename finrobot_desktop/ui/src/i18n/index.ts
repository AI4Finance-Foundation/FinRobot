// Lightweight i18n hook backed by zustand store with localStorage persistence.
// Usage:
//   const { t, locale, setLocale } = useI18n()
//   <span>{t('nav.stocks')}</span>
//   <span>{t('tool.toast.success', { tool: 'DCF' })}</span>

import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { type Locale, translate, LOCALES } from './messages'

export { LOCALES }
export type { Locale }

interface UiPrefsState {
  locale: Locale
  setLocale: (l: Locale) => void
}

function defaultLocale(): Locale {
  if (typeof navigator !== 'undefined') {
    const lang = navigator.language?.toLowerCase() ?? 'en'
    if (lang.startsWith('zh')) return 'zh'
  }
  return 'en'
}

export const useUiPrefs = create<UiPrefsState>()(
  persist(
    (set) => ({
      locale: defaultLocale(),
      setLocale: (locale) => set({ locale }),
    }),
    {
      name: 'finagent-ui-prefs',
      storage: createJSONStorage(() => localStorage),
    },
  ),
)

export function useI18n() {
  const locale = useUiPrefs((s) => s.locale)
  const setLocale = useUiPrefs((s) => s.setLocale)
  const t = (key: string, params?: Record<string, string | number>): string =>
    translate(locale, key, params)
  return { locale, setLocale, t }
}

// Helper for non-React code (utils, queries) — reads current store snapshot.
export function tSync(key: string, params?: Record<string, string | number>): string {
  return translate(useUiPrefs.getState().locale, key, params)
}
