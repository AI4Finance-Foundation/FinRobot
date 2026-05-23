// v5 (spec §11.4): 6 menu → 2 menu (个股 + 设置). The 4 removed pages are
// not deleted from the URL space immediately — each retired path redirects
// to its v5 equivalent for one release so links shared in chat / docs don't
// 404 overnight. v5+1 will remove the redirect block.
//
// `RedirectWithToast` writes a single-shot message into sessionStorage so the
// destination page can surface a banner like "工作台已合并到「个股」首页"
// without us building a global toast queue. AppShell reads + clears the slot
// on mount.

import { createBrowserRouter, Navigate, useNavigate } from 'react-router-dom'
import { useEffect } from 'react'
import { AppShell } from './layout/AppShell'
import { StocksPage } from './pages/StocksPage'
import { SettingsPage } from './pages/SettingsPage'
import { ArtifactDetailPage } from './pages/ArtifactDetailPage'
import { StockWorkspace } from './views/StockWorkspace'

export const REDIRECT_TOAST_KEY = 'finagent.redirect_toast'

interface RedirectWithToastProps {
  to: string
  message: string
  /** When true, preserves the :ticker URL segment by interpolating it into `to`. */
  preserveTicker?: boolean
}

function RedirectWithToast({ to, message, preserveTicker = false }: RedirectWithToastProps) {
  const navigate = useNavigate()
  useEffect(() => {
    sessionStorage.setItem(REDIRECT_TOAST_KEY, message)
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
  }, [to, message, preserveTicker, navigate])
  return null
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/stocks" replace /> },

      // v5 live routes — single canonical path. The old 8-tab StocksPage
      // is retained ONLY at /stocks (no ticker) as a landing placeholder
      // until spec §2 cross-ticker landing ships. Any /stocks/:ticker
      // hit renders the v5 single-page StockWorkspace.
      { path: 'stocks', element: <StocksPage /> },
      { path: 'stocks/:ticker', element: <StockWorkspace /> },
      { path: 'stocks/:ticker/runs/:artifactId', element: <ArtifactDetailPage /> },
      { path: 'settings', element: <SettingsPage /> },

      // v5 deprecation redirects (one release window) — spec §11.4
      {
        path: 'dashboard',
        element: <RedirectWithToast to="/stocks" message="工作台已合并到「个股」首页" />,
      },
      {
        path: 'library',
        element: (
          <RedirectWithToast to="/stocks" message="报告库已合并到 ticker 的「我的研究」section" />
        ),
      },
      {
        path: 'library/:ticker',
        element: (
          <RedirectWithToast
            to="/stocks"
            message="报告库已合并到「我的研究」section"
            preserveTicker
          />
        ),
      },
      {
        path: 'journal',
        element: <RedirectWithToast to="/stocks" message="决策日记 v3 重新设计中" />,
      },
      {
        path: 'playground',
        element: <RedirectWithToast to="/stocks" message="估值假设调节 v2.1 重新设计" />,
      },
      {
        path: 'playground/:ticker',
        element: (
          <RedirectWithToast to="/stocks" message="估值假设调节 v2.1 重新设计" preserveTicker />
        ),
      },
    ],
  },
])
