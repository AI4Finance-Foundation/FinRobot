// Debounced auto-save machinery for PUT /api/settings — owns the save
// indicator state, the pending-payload merge buffer, retry, and the
// flush-before-test path used by the data-source connectivity probes.

import { useState, useEffect, useRef, useCallback } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/client'
import { useToastStore } from '../../stores/toastStore'
import { mapErrorToUserMessage } from '../../utils/errorMessage'
import { useI18n } from '../../i18n'

// ─── Auto-save indicator ───────────────────────────────────────────────────

export type SaveState = 'idle' | 'saving' | 'saved' | 'error'

export function useSettingsSave() {
  const { t } = useI18n()
  const queryClient = useQueryClient()
  const addToast = useToastStore((s) => s.addToast)

  // ── Save indicator ───────────────────────────────────────────────────────
  const [saveState, setSaveState] = useState<SaveState>('idle')
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const initializedRef = useRef(false)
  const lastPayloadRef = useRef<Record<string, unknown> | null>(null)

  // ── PUT /api/settings mutation (debounced auto-save) ─────────────────────
  const settingsMutation = useMutation({
    mutationFn: async (body: Record<string, unknown>) => {
      const { data, error } = await api.PUT('/api/settings', { body: body as never })
      if (error) {
        const detail = (error as { detail?: string }).detail
        throw new Error(detail || 'Settings update failed')
      }
      return data
    },
    onSuccess: (data, variables) => {
      queryClient.setQueryData(['settings'], data)
      // Saving the Adanos key rebuilds the data layer server-side, so the retail
      // sentiment card's cached `available:false` is now stale. Without this it
      // keeps showing "Adanos not configured" until staleTime (5 min) elapses —
      // the user configures the key and the card still calls them unconfigured.
      if (variables && 'adanos_api_key' in variables) {
        void queryClient.invalidateQueries({ queryKey: ['ticker-sentiment'] })
      }
      if (lastPayloadRef.current === variables) {
        lastPayloadRef.current = null
      }
      setSaveState('saved')
      saveTimerRef.current = setTimeout(() => setSaveState('idle'), 2500)
    },
    onError: (err: Error) => {
      setSaveState('error')
      addToast({
        type: 'error',
        title: t('settings.saveFailedTitle'),
        description: mapErrorToUserMessage(err),
      })
    },
  })

  // ── Debounced auto-save ────────────────────────────────────────────────────
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const settingsMutationRef = useRef(settingsMutation)
  useEffect(() => {
    settingsMutationRef.current = settingsMutation
  }, [settingsMutation])

  // `onSaved` fires once after THIS debounced PUT succeeds (react-query per-call
  // onSuccess runs in addition to the mutation-level one). Used by the AI Model
  // panel to auto-run the live connection test the instant the key/model lands
  // server-side — so a wrong key is caught at config time, not 60s into a run.
  // The debounce coalesces rapid edits, so only the final call's onSaved runs.
  const scheduleStandardSave = useCallback(
    (payload: Record<string, unknown>, onSaved?: () => void) => {
      if (!initializedRef.current) return
      if (debounceRef.current) clearTimeout(debounceRef.current)
      const merged = { ...(lastPayloadRef.current ?? {}), ...payload }
      lastPayloadRef.current = merged
      setSaveState('saving')
      debounceRef.current = setTimeout(() => {
        settingsMutationRef.current.mutate(
          merged as never,
          onSaved ? { onSuccess: () => onSaved() } : undefined,
        )
      }, 500)
    },
    [],
  )

  const retrySave = useCallback(() => {
    const payload = lastPayloadRef.current
    if (!payload) return
    setSaveState('saving')
    settingsMutationRef.current.mutate(payload as never)
  }, [])

  /** Immediately persist any queued debounced edit and resolve once it is
   * stored server-side. No-op when nothing is queued — the last edit already
   * saved, so the caller probes the stored value.
   *
   * Both "Test connection" buttons (LLM + data-source) await this BEFORE the
   * probe. Without it, a Test click that lands inside the 500ms auto-save window
   * tests the value the PUT hasn't written yet → the backend reports the key as
   * missing, the user assumes it failed and re-enters it. That race was the
   * root cause of "every key had to be configured two or three times before the
   * test passed". The queued payload already carries whatever field changed —
   * every edit funnels through `scheduleStandardSave` — so one flush covers any
   * field without the caller naming it. */
  const flushPending = useCallback(async () => {
    if (debounceRef.current) {
      clearTimeout(debounceRef.current)
      debounceRef.current = null
    }
    const payload = lastPayloadRef.current
    if (!payload) return
    await settingsMutationRef.current.mutateAsync(payload as never)
  }, [])

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current)
    }
  }, [])

  return { saveState, scheduleStandardSave, retrySave, flushPending, initializedRef }
}
