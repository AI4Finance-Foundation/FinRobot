// Auto-update state machine.
//
// Surfacing is a title-bar pill (UpdatePill), not a modal: a found update shows
// an unobtrusive "Update to vX" button at the top; clicking it downloads +
// installs + relaunches directly (Codex-style). `check()` returns a result so
// callers decide their own feedback — the startup check stays silent on
// errors/up-to-date, while the Settings button toasts. The only phase that
// surfaces an error in the pill is a failed *install* (user-initiated, so the
// retry must be visible); check failures fall back to idle.

import { create } from 'zustand'
import {
  checkForUpdate,
  relaunchApp,
  fetchMinVersion,
  compareVersions,
  type Update,
} from '../lib/updater'

export type UpdatePhase =
  | 'idle' // nothing to show
  | 'checking' // querying the endpoint
  | 'available' // newer version found — pill offers it
  | 'downloading' // streaming the new bundle
  | 'installing' // writing the downloaded update
  | 'ready' // installed; relaunching
  | 'error' // an install attempt failed — pill offers retry

export type CheckResult = 'available' | 'uptodate' | 'error' | 'skipped'

interface UpdaterState {
  phase: UpdatePhase
  update: Update | null
  version: string | null
  notes: string | null
  /** True when the installed version is below the published min-version floor:
   *  the update is mandatory and the app blocks until it is installed. */
  mandatory: boolean
  /** Download progress 0..1 (0 when content length is unknown). */
  progress: number
  error: string | null

  check: () => Promise<CheckResult>
  installAndRelaunch: () => Promise<void>
}

const INSTALL_BUSY: UpdatePhase[] = ['downloading', 'installing', 'ready']

export const useUpdaterStore = create<UpdaterState>((set, get) => ({
  phase: 'idle',
  update: null,
  version: null,
  notes: null,
  mandatory: false,
  progress: 0,
  error: null,

  check: async () => {
    if (get().phase === 'checking' || INSTALL_BUSY.includes(get().phase)) return 'skipped'
    // Keep an already-found update visible while a re-check runs.
    if (get().phase !== 'available') set({ phase: 'checking', error: null })
    try {
      const update = await checkForUpdate()
      if (update) {
        // Mandatory when the installed version is below the published floor.
        // fetchMinVersion fails soft (null) → never a false block.
        const min = await fetchMinVersion()
        const mandatory = !!min && compareVersions(update.currentVersion, min) < 0
        set({
          phase: 'available',
          update,
          version: update.version,
          notes: update.body?.trim() ? update.body.trim() : null,
          mandatory,
        })
        return 'available'
      }
      set({ phase: 'idle', update: null, version: null, notes: null, mandatory: false })
      return 'uptodate'
    } catch (err) {
      // A failed check is silent in the UI — only the manual caller toasts.
      set((s) => ({ phase: s.phase === 'checking' ? 'idle' : s.phase }))
      void (err instanceof Error ? err.message : String(err))
      return 'error'
    }
  },

  installAndRelaunch: async () => {
    const update = get().update
    if (!update || INSTALL_BUSY.includes(get().phase)) return
    set({ phase: 'downloading', progress: 0, error: null })
    let total = 0
    let downloaded = 0
    try {
      await update.downloadAndInstall((e) => {
        switch (e.event) {
          case 'Started':
            total = e.data.contentLength ?? 0
            break
          case 'Progress':
            downloaded += e.data.chunkLength
            set({ progress: total > 0 ? Math.min(downloaded / total, 1) : 0 })
            break
          case 'Finished':
            set({ phase: 'installing', progress: 1 })
            break
        }
      })
      set({ phase: 'ready' })
      await relaunchApp()
    } catch (err) {
      set({
        phase: 'error',
        error: err instanceof Error ? err.message : String(err),
      })
    }
  },
}))

// DEV-only handle so e2e visual tests can drive the pill through its phases
// (the "available" state only occurs inside Tauri). Stripped from prod builds.
if (import.meta.env.DEV && typeof window !== 'undefined') {
  ;(window as unknown as { __updaterStore?: typeof useUpdaterStore }).__updaterStore =
    useUpdaterStore
}
