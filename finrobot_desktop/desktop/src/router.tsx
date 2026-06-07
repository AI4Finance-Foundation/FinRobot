// v5 (spec §11.4): retired pages remain in the URL space for one release so
// links shared in chat / docs don't 404 overnight. The current top-level
// product doors are Research (search-first single-stock flow), Coverage
// (studied ticker archive), and Settings. v5+1 will remove the redirect block.
//
// `RetiredRouteRedirect` does a silent `replace` navigation, optionally
// carrying the trailing :ticker segment over to the new path. It shows no
// banner — the redirect is transparent by design (an earlier
// sessionStorage-backed "merged" toast was never read by any consumer, so it
// was removed rather than wired up; BUG-067).

import { createBrowserRouter, Navigate, useNavigate } from 'react-router-dom'
import { lazy, Suspense, useEffect } from 'react'
import { AppShell } from './layout/AppShell'
import { CoveragePage } from './pages/CoveragePage'
import { ResearchPage } from './pages/ResearchPage'
import { StockWorkspace } from './views/StockWorkspace'

// Lazy-routed: ArtifactDetailPage pulls 13 chapter components + the 4-panel
// chrome, and Settings imports the full provider/channel matrix. Loading them
// only when the user navigates keeps the initial bundle under the
// chunk-size warning threshold and shaves cold-start time on the workspace
// landing — analysts hit `/stocks/:ticker` before any artifact detail.
const ArtifactDetailPage = lazy(() =>
  import('./pages/ArtifactDetailPage').then((m) => ({ default: m.ArtifactDetailPage })),
)
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
)
const IcDebatePage = lazy(() =>
  import('./pages/ic/IcDebatePage').then((m) => ({ default: m.IcDebatePage })),
)

function RouteSuspense({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div
          data-testid="route-suspense"
          style={{
            padding: '64px 24px',
            fontFamily: 'var(--font-mono)',
            fontSize: 11,
            color: 'var(--text-muted)',
            letterSpacing: '0.08em',
          }}
        >
          loading…
        </div>
      }
    >
      {children}
    </Suspense>
  )
}

interface RetiredRouteRedirectProps {
  to: string
  /** When true, preserves the :ticker URL segment by interpolating it into `to`. */
  preserveTicker?: boolean
}

function RetiredRouteRedirect({ to, preserveTicker = false }: RetiredRouteRedirectProps) {
  const navigate = useNavigate()
  useEffect(() => {
    let target = to
    if (preserveTicker) {
      // The retired routes (/library/:ticker, /playground/:ticker) share their
      // tail with /stock/:ticker. Pull the trailing segment off window.location
      // rather than relying on react-router params here — keeps this redirect
      // component framework-light and side-effect-free.
      const segments = window.location.pathname.split('/').filter(Boolean)
      const tail = segments[segments.length - 1]
      if (tail && /^[A-Za-z][A-Za-z0-9.-]{0,10}$/.test(tail)) {
        target = `${to}/${tail.toUpperCase()}`
      }
    }
    navigate(target, { replace: true })
  }, [to, preserveTicker, navigate])
  return null
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/research" replace /> },

      // Research is the search-first homepage; Coverage is the archive desk.
      { path: 'research', element: <ResearchPage /> },
      { path: 'coverage', element: <CoveragePage /> },

      // The old /stocks landing retired into Research; the per-ticker
      // drill-down (StockWorkspace) and report detail keep their routes.
      {
        path: 'stocks',
        element: <RetiredRouteRedirect to="/research" />,
      },
      { path: 'stocks/:ticker', element: <StockWorkspace /> },
      {
        path: 'stocks/:ticker/runs/:artifactId',
        element: (
          <RouteSuspense>
            <ArtifactDetailPage />
          </RouteSuspense>
        ),
      },
      {
        path: 'settings',
        element: (
          <RouteSuspense>
            <SettingsPage />
          </RouteSuspense>
        ),
      },
      {
        // IC debate is entered from a report (ReportToolbar → onOpenIcDebate)
        // with an artifact_id; there is no standalone landing/picker route.
        path: 'ic/:ticker',
        element: (
          <RouteSuspense>
            <IcDebatePage />
          </RouteSuspense>
        ),
      },

      // v5 deprecation redirects (one release window) — spec §11.4.
      // Bare retired pages land on /coverage directly (the old /stocks landing
      // also retired into /coverage, so pointing here avoids a double hop).
      // The :ticker variants preserve their symbol into /stocks/:ticker
      // (StockWorkspace) — a canonical route, not a redirect — to keep context.
      {
        path: 'dashboard',
        element: <RetiredRouteRedirect to="/coverage" />,
      },
      {
        path: 'library',
        element: <RetiredRouteRedirect to="/coverage" />,
      },
      {
        path: 'library/:ticker',
        element: <RetiredRouteRedirect to="/stocks" preserveTicker />,
      },
      {
        path: 'journal',
        element: <RetiredRouteRedirect to="/coverage" />,
      },
      {
        path: 'playground',
        element: <RetiredRouteRedirect to="/coverage" />,
      },
      {
        path: 'playground/:ticker',
        element: <RetiredRouteRedirect to="/stocks" preserveTicker />,
      },
    ],
  },
])
