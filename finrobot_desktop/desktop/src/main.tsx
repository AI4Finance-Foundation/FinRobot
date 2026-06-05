import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
// Fonts are bundled (not CDN-loaded) so the desktop app renders its cosmic
// identity offline — Space Grotesk (--font-display), IBM Plex Sans
// (--font-body), JetBrains Mono (--font-mono). These mirror the App.css design
// tokens and the FinRobot.html research-cockpit reference. All three are Latin
// faces; CJK glyphs (the app is zh/en bilingual) fall back to the system CJK
// font (PingFang SC / Microsoft YaHei) declared in the token font stacks.
import '@fontsource/space-grotesk/400.css'
import '@fontsource/space-grotesk/500.css'
import '@fontsource/space-grotesk/600.css'
import '@fontsource/space-grotesk/700.css'
import '@fontsource/ibm-plex-sans/300.css'
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/500.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-sans/700.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import '@fontsource/jetbrains-mono/600.css'
import '@fontsource/jetbrains-mono/700.css'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from './api/queryClient'
import { router } from './router'
import { ErrorBoundary } from './components/ErrorBoundary'
// Importing the i18n module runs its side effects (load catalogs + activate the
// persisted/default locale) before the first render.
import { useUiPrefs } from './i18n'
import { detectInitialLocale, hasStoredLocale } from './i18n/detect'
import './App.css'
import './styles/tabs.css'

// First-launch language: if the user has never picked a language, match the OS
// locale (English OS → English UI, Chinese OS → Chinese UI) before the first
// paint. Once set, setLocale() persists it, so subsequent launches honor the
// stored choice and skip detection. Chinese-first remains the fallback when the
// OS gives no usable hint (or outside Tauri).
async function bootstrap(): Promise<void> {
  if (!hasStoredLocale()) {
    const detected = await detectInitialLocale()
    useUiPrefs.getState().setLocale(detected)
  }

  const root = document.getElementById('root')
  if (!(root instanceof HTMLElement)) {
    throw new Error('FinRobot root element #root was not found')
  }

  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <ErrorBoundary>
          <RouterProvider router={router} />
        </ErrorBoundary>
      </QueryClientProvider>
    </StrictMode>,
  )
}

void bootstrap()
