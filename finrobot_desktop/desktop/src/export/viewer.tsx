// Standalone report viewer — the entry point of the self-contained HTML export.
//
// Built by vite.viewer.config.ts into ONE IIFE JS + CSS, which exportReport
// inlines into the exported .html alongside the report data. At runtime it reads
// window.__FINROBOT_REPORT__ (artifact + version timeline + a dehydrated
// react-query cache + locale), rehydrates the query cache so the chapters' data
// hooks resolve from inlined data WITHOUT any network, and renders the exact
// same body the app uses (ReportExportBody → the 13-chapter ReportChapters for
// equity_research, the CompactArtifactViewer for dcf / ddm / lbo / comps / …) —
// Recharts tooltips, heatmap and football field all live, fully offline.

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import {
  QueryClient,
  QueryClientProvider,
  hydrate,
  type DehydratedState,
} from '@tanstack/react-query'

// Same fonts + base styles as the app so the export looks identical. The viewer
// CSS (imported last) re-enables document scroll, which App.css disables for the
// in-app inner scroll container that does not exist here.
// Latin subsets only — the report is Latin/CJK; CJK falls back to system fonts
// anyway, so bundling cyrillic/greek/vietnamese would just bloat the file.
import '@fontsource/space-grotesk/latin-400.css'
import '@fontsource/space-grotesk/latin-500.css'
import '@fontsource/space-grotesk/latin-600.css'
import '@fontsource/space-grotesk/latin-700.css'
import '@fontsource/ibm-plex-sans/latin-300.css'
import '@fontsource/ibm-plex-sans/latin-400.css'
import '@fontsource/ibm-plex-sans/latin-500.css'
import '@fontsource/ibm-plex-sans/latin-600.css'
import '@fontsource/jetbrains-mono/latin-400.css'
import '@fontsource/jetbrains-mono/latin-500.css'
import '../App.css'
import '../styles/tabs.css'
import './viewer.css'

import { useUiPrefs } from '../i18n'
import { ReportExportBody } from './ReportExportBody'
import type { ArtifactDetail } from '../hooks/useV5Artifacts'
import type { ArtifactSummaryV5 } from '../types/v5'

interface ExportPayload {
  artifact: ArtifactDetail
  timeline: ArtifactSummaryV5[]
  queryState: DehydratedState
  locale: 'zh' | 'en'
}

function mount(): void {
  const root = document.getElementById('root')
  if (!root) return

  const payload = (window as unknown as { __FINROBOT_REPORT__?: ExportPayload }).__FINROBOT_REPORT__
  if (!payload) {
    root.textContent = 'No report data embedded.'
    return
  }

  // Activate the report's own language so the chrome matches the prose.
  useUiPrefs.getState().setLocale(payload.locale)

  // A frozen, offline cache: hydrate the captured queries and never refetch, so
  // the chapters' data hooks resolve from inlined data even on file://.
  const qc = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: Infinity,
        gcTime: Infinity,
        retry: false,
        refetchOnMount: false,
        refetchOnReconnect: false,
        refetchOnWindowFocus: false,
      },
    },
  })
  hydrate(qc, payload.queryState)

  createRoot(root).render(
    <StrictMode>
      <QueryClientProvider client={qc}>
        {/* MemoryRouter satisfies the one chapter that uses router hooks; links
            become harmless in-memory no-ops in the standalone file. */}
        <MemoryRouter>
          <div className="report-export-shell">
            {/* Mirrors the in-app page's type branch: the 13-chapter report for
                equity_research, the compact single-computation viewer for
                dcf / ddm / lbo / comps / earnings / … (so a standalone export
                isn't an empty equity shell — BUG-20260602-039). */}
            <ReportExportBody artifact={payload.artifact} timeline={payload.timeline} />
          </div>
        </MemoryRouter>
      </QueryClientProvider>
    </StrictMode>,
  )
}

mount()
