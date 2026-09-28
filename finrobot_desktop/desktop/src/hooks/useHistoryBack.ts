// useHistoryBack — a "go back to where I came from" handler.
//
// Pops the in-app history stack when there is one, and otherwise routes to a
// known parent. React Router stamps a monotonic `idx` onto history.state; idx
// 0 / absent means this entry is the FIRST the app pushed (deep link, cold
// start, external open) — there navigate(-1) would dead-end or leave the app,
// so we replace into `fallback` instead of popping into the void.

import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'

export function useHistoryBack(fallback: string): () => void {
  const navigate = useNavigate()
  return useCallback(() => {
    const idx = (window.history.state as { idx?: number } | null)?.idx ?? 0
    if (idx > 0) navigate(-1)
    else navigate(fallback, { replace: true })
  }, [navigate, fallback])
}
