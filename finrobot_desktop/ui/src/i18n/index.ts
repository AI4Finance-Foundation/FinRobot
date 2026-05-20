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
  // 产品定位：散户优先 — 默认中文。
  // 英文用户可通过顶部语言切换器改回 en（持久化到 localStorage）。
  return 'zh'
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
