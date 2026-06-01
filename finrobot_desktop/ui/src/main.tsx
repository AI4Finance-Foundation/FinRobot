import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
// Fonts are bundled (not CDN-loaded) so the desktop app renders its cosmic
// identity offline — Audiowide (--font-display), Inter (--font-body),
// JetBrains Mono (--font-mono). These mirror the App.css design tokens; the
// old DM Sans / Fraunces imports were pre-cosmic leftovers wired to no token.
import '@fontsource/audiowide/400.css'
import '@fontsource/inter/300.css'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'
import '@fontsource/inter/700.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import '@fontsource/jetbrains-mono/600.css'
import '@fontsource/jetbrains-mono/700.css'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from './api/queryClient'
import { router } from './router'
// Importing the i18n module runs its side effects (load catalogs + activate the
// persisted/default locale) before the first render. FinRobot is Chinese-first:
// the default locale is zh and we deliberately do NOT probe the OS locale on
// first launch; English users switch via Settings → 外观 → 语言.
import './i18n'
import './App.css'
import './styles/tabs.css'

const root = document.getElementById('root')
if (!(root instanceof HTMLElement)) {
  throw new Error('FinRobot root element #root was not found')
}

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
