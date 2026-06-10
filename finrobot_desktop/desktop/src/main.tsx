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
// default locale) before the first render.
import { useUiPrefs } from './i18n'
import { useRunStreamStore } from './stores/runStreamStore'
import './App.css'
import './styles/tabs.css'

// The app ships English-only (no in-app language switcher). Force 'en' on every
// launch so any stale persisted 'zh' from an earlier build is coerced back to
// English. When multi-language returns, replace this with locale detection /
// the persisted choice — the i18n machinery is otherwise untouched.
async function bootstrap(): Promise<void> {
  useUiPrefs.getState().setLocale('en')

  // Reattach to pipeline runs still executing on the backend (P1-30): a
  // webview reload / app restart drops the in-memory run map while the
  // backend keeps burning — without this the workspace shows the cold launch
  // CTA over a live pipeline and invites a duplicate run. Fire-and-forget:
  // render never waits, and an unreachable backend is a silent no-op.
  void useRunStreamStore.getState().reattachActiveRuns()

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
