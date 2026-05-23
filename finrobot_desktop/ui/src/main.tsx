import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import '@fontsource/dm-sans/400.css'
import '@fontsource/dm-sans/500.css'
import '@fontsource/dm-sans/600.css'
import '@fontsource/dm-sans/700.css'
import '@fontsource/jetbrains-mono/400.css'
import '@fontsource/jetbrains-mono/500.css'
import '@fontsource/jetbrains-mono/600.css'
import '@fontsource/jetbrains-mono/700.css'
import '@fontsource/fraunces/400.css'
import '@fontsource/fraunces/500.css'
import '@fontsource/fraunces/600.css'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient } from './api/queryClient'
import { router } from './router'
import { useUiPrefs } from './i18n'
import { detectInitialLocale, hasStoredLocale } from './i18n/detect'
import './App.css'
import './styles/tabs.css'

// FinAgent positions Chinese-first. We do NOT probe OS locale on first run —
// English macOS users were getting an English UI by default which contradicts
// the product positioning. Default is always zh; English users can switch via
// Settings → 外观 → 语言. The detect.ts helper is kept for future opt-in use
// (e.g. a "first-launch language picker" feature).
void detectInitialLocale
void hasStoredLocale
void useUiPrefs

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
