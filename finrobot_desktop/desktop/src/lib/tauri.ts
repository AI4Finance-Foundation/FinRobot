// Thin Tauri integration wrapper.
//
// Phase 5: static imports replace the dynamic loadPlugin stubs.
// Every function still works in both browser (dev) and Tauri (production).
// Browser fallbacks are safe no-ops or window.open equivalents.

import { open as openShell } from '@tauri-apps/plugin-shell'
import { open as openDialog, save as saveDialog } from '@tauri-apps/plugin-dialog'
import { writeTextFile as fsWriteTextFile } from '@tauri-apps/plugin-fs'
import { getCurrentWindow } from '@tauri-apps/api/window'
import { platform } from '@tauri-apps/plugin-os'

/** Returns true when running inside a Tauri webview. */
export function isTauri(): boolean {
  if (typeof window === 'undefined') return false
  // Tauri v2 attaches __TAURI_INTERNALS__; v1 used __TAURI__.
  const w = window as unknown as Record<string, unknown>
  return Boolean(w.__TAURI_INTERNALS__ ?? w.__TAURI__)
}

/**
 * True when running inside a Tauri webview ON Windows. Drives the few places
 * the shell must diverge from its macOS-native chrome — e.g. the titlebar
 * reserves 72px for macOS traffic lights that Windows doesn't have (Windows
 * gets a native window frame with top-right controls instead).
 *
 * `platform()` from plugin-os is synchronous in Tauri v2 (resolved from an
 * init snapshot). In a plain browser (dev) there is no native platform, so we
 * report false and render the macOS layout we develop against.
 */
export function isWindows(): boolean {
  if (!isTauri()) return false
  try {
    return platform() === 'windows'
  } catch {
    return false
  }
}

// ─── Window dragging ──────────────────────────────────────────────

/**
 * Start a native window drag from a titlebar mousedown; double-click zooms
 * (toggleMaximize). No-op in a plain browser (dev) where no native window
 * exists.
 *
 * We keep native macOS traffic lights (decorations:true + titleBarStyle
 * "Overlay"), and Tauri v2's `data-tauri-drag-region` only works with
 * decorations:false — so the whole-bar drag must go through the window API
 * explicitly rather than the HTML attribute.
 */
export function startWindowDrag(doubleClick: boolean): void {
  if (!isTauri()) return
  const win = getCurrentWindow()
  // Surface failures (e.g. a missing core:window:allow-start-dragging /
  // allow-toggle-maximize capability denies the IPC call) instead of letting
  // the rejected promise vanish — a silent denial reads exactly like "drag
  // doesn't work".
  const op = doubleClick ? win.toggleMaximize() : win.startDragging()
  op.catch((err) => console.warn('[tauri] window drag failed:', err))
}

// ─── Shell ────────────────────────────────────────────────────────

export async function openExternal(url: string): Promise<void> {
  if (!isTauri()) {
    window.open(url, '_blank', 'noopener,noreferrer')
    return
  }
  await openShell(url)
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

export interface SaveFileFilter {
  /** Human label shown in the OS save dialog, e.g. "HTML". */
  name: string
  /** Extensions without the dot, e.g. ["html"]. */
  extensions: string[]
}

/**
 * Save text to a user-chosen path. In Tauri: native save dialog → writeTextFile
 * (fs capability scopes writes to $HOME/** — covers Desktop/Documents/Downloads).
 * In a plain browser (dev): trigger a Blob download. Returns true if a file was
 * written, false if the user cancelled the dialog.
 */
export async function saveTextFile(
  suggestedName: string,
  contents: string,
  filters?: SaveFileFilter[],
): Promise<boolean> {
  if (!isTauri()) {
    const mime = suggestedName.endsWith('.html')
      ? 'text/html;charset=utf-8'
      : 'text/plain;charset=utf-8'
    const url = URL.createObjectURL(new Blob([contents], { type: mime }))
    const a = document.createElement('a')
    a.href = url
    a.download = suggestedName
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    return true
  }
  const path = await saveDialog({ defaultPath: suggestedName, filters })
  if (!path) return false
  await fsWriteTextFile(path, contents)
  return true
}

// ─── Workspace path (P1 default; Phase 5 T5.6 wires real dialog) ──

export const DEFAULT_WORKSPACE_PATH = '~/finrobot'
