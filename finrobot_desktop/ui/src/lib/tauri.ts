// Thin Tauri integration wrapper.
//
// Phase 5: static imports replace the dynamic loadPlugin stubs.
// Every function still works in both browser (dev) and Tauri (production).
// Browser fallbacks are safe no-ops or window.open equivalents.

import { open as openShell } from '@tauri-apps/plugin-shell'
import { open as openDialog } from '@tauri-apps/plugin-dialog'
import { readTextFile as fsReadTextFile } from '@tauri-apps/plugin-fs'
import {
  register as registerGlobalShortcut,
  unregister as unregisterGlobalShortcut,
} from '@tauri-apps/plugin-global-shortcut'

/** Returns true when running inside a Tauri webview. */
export function isTauri(): boolean {
  if (typeof window === 'undefined') return false
  // Tauri v2 attaches __TAURI_INTERNALS__; v1 used __TAURI__.
  const w = window as unknown as Record<string, unknown>
  return Boolean(w.__TAURI_INTERNALS__ ?? w.__TAURI__)
}

// ─── Shell ────────────────────────────────────────────────────────

export async function openExternal(url: string): Promise<void> {
  if (!isTauri()) {
    window.open(url, '_blank', 'noopener,noreferrer')
    return
  }
  await openShell(url)
}

// ─── Global shortcuts ─────────────────────────────────────────────

export type Shortcut = {
  /** Logical key e.g. "l" | "k" | "p" — case-insensitive, single char. */
  key: string
  /** Require ⌘ on macOS / Ctrl on Win/Linux. */
  mod?: boolean
  /** Require Shift. */
  shift?: boolean
}

/**
 * Register a shortcut via both DOM keydown listener and (in Tauri) a
 * system-wide global shortcut so the handler fires even when the webview
 * does not hold focus.
 *
 * Returns a cleanup function that removes both listeners.
 *
 * NOTE: now async — callers must handle the returned Promise.
 * AppShell pattern:
 *   useEffect(() => {
 *     let cleanup: (() => void) | null = null
 *     registerShortcut(...).then(c => { cleanup = c })
 *     return () => cleanup?.()
 *   }, [])
 */
export async function registerShortcut(
  shortcut: Shortcut,
  handler: () => void,
): Promise<() => void> {
  // DOM listener — always registered; fires when webview has focus.
  const onKey = (e: KeyboardEvent) => {
    if (shortcut.mod && !(e.metaKey || e.ctrlKey)) return
    if (shortcut.shift && !e.shiftKey) return
    if (e.key.toLowerCase() !== shortcut.key.toLowerCase()) return
    e.preventDefault()
    handler()
  }
  window.addEventListener('keydown', onKey)

  // Global shortcut — Tauri only; fires even without webview focus.
  let unregGlobal: (() => Promise<void>) | null = null
  if (isTauri()) {
    try {
      const mod = shortcut.mod ? 'CmdOrCtrl+' : ''
      const shift = shortcut.shift ? 'Shift+' : ''
      const accel = `${mod}${shift}${shortcut.key.toUpperCase()}`
      await registerGlobalShortcut(accel, () => handler())
      unregGlobal = async () => {
        await unregisterGlobalShortcut(accel)
      }
    } catch (err) {
      // Non-fatal: some platforms/environments reject global shortcuts.
      console.warn('[tauri] global shortcut register failed:', err)
    }
  }

  return () => {
    window.removeEventListener('keydown', onKey)
    if (unregGlobal) void unregGlobal()
  }
}

// ─── Dialog (workspace picker) ────────────────────────────────────

export async function pickDirectory(): Promise<string | null> {
  if (!isTauri()) {
    // Browser cannot prompt for a real directory path. Return null;
    // caller falls back to the hardcoded DEFAULT_WORKSPACE_PATH.
    return null
  }
  const picked = await openDialog({ directory: true, multiple: false })
  // openDialog returns string | string[] | null depending on multiple flag.
  return typeof picked === 'string' ? picked : null
}

// ─── File system ──────────────────────────────────────────────────

export async function readTextFile(path: string): Promise<string> {
  if (!isTauri()) {
    throw new Error(`readTextFile not available in browser (path: ${path})`)
  }
  return fsReadTextFile(path)
}

// ─── Workspace path (P1 default; Phase 5 T5.6 wires real dialog) ──

export const DEFAULT_WORKSPACE_PATH = '~/finrobot'
