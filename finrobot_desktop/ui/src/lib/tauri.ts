// Thin Tauri integration wrapper.
//
// Phase 0 contract: every function works in both browser and Tauri.
// In browser, falls back to safe no-ops / window.open. In Tauri, calls
// the corresponding plugin once we wire them in Phase 5.
//
// Phase 5 will:
//   - npm i @tauri-apps/api @tauri-apps/plugin-shell @tauri-apps/plugin-dialog
//          @tauri-apps/plugin-fs @tauri-apps/plugin-global-shortcut
//   - cargo add tauri-plugin-dialog tauri-plugin-fs tauri-plugin-global-shortcut
//   - replace the "TODO Phase 5" stubs below with real plugin imports
//   - update capabilities/default.json with the new permissions

/** Returns true when running inside a Tauri webview. */
export function isTauri(): boolean {
  if (typeof window === 'undefined') return false
  // Tauri v2 attaches __TAURI_INTERNALS__; v1 used __TAURI__.
  const w = window as unknown as Record<string, unknown>
  return Boolean(w.__TAURI_INTERNALS__ ?? w.__TAURI__)
}

// ─── Dynamic plugin loader ────────────────────────────────────────
// We dynamically import Tauri JS bindings via a variable so the TS
// compiler does not try to resolve them in Phase 0 (the npm packages
// are not installed until Phase 5). The `/* @vite-ignore */` comment
// keeps Vite from rewriting the import at build time.

async function loadPlugin<T>(modulePath: string): Promise<T | null> {
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const dyn = new Function('p', 'return import(/* @vite-ignore */ p)') as (
      p: string,
    ) => Promise<unknown>
    return (await dyn(modulePath)) as T
  } catch {
    return null
  }
}

// ─── Shell ────────────────────────────────────────────────────────
// tauri-plugin-shell is already installed (see src-tauri/Cargo.toml),
// but the JS binding @tauri-apps/plugin-shell is added in Phase 5.

export async function openExternal(url: string): Promise<void> {
  if (!isTauri()) {
    window.open(url, '_blank', 'noopener,noreferrer')
    return
  }
  const mod = await loadPlugin<{ open: (path: string) => Promise<void> }>(
    '@tauri-apps/plugin-shell',
  )
  if (mod) {
    await mod.open(url)
  } else {
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}

// ─── Global shortcuts ─────────────────────────────────────────────
// Phase 0 implementation: pure DOM keydown listener. Works in both
// Tauri and browser, but only fires when the webview has focus.
// Phase 5 will additionally register a system-wide shortcut via
// tauri-plugin-global-shortcut so ⌘L fires even when another app
// holds focus.

export type Shortcut = {
  /** Logical key e.g. "l" | "k" | "p" — case-insensitive, single char. */
  key: string
  /** Require ⌘ on macOS / Ctrl on Win/Linux. */
  mod?: boolean
  /** Require Shift. */
  shift?: boolean
}

export function registerShortcut(
  shortcut: Shortcut,
  handler: (e: KeyboardEvent) => void,
): () => void {
  const onKey = (e: KeyboardEvent) => {
    if (shortcut.mod && !(e.metaKey || e.ctrlKey)) return
    if (shortcut.shift && !e.shiftKey) return
    if (e.key.toLowerCase() !== shortcut.key.toLowerCase()) return
    e.preventDefault()
    handler(e)
  }
  window.addEventListener('keydown', onKey)
  // TODO Phase 5: also register globally via @tauri-apps/plugin-global-shortcut
  return () => window.removeEventListener('keydown', onKey)
}

// ─── Dialog (workspace picker) ────────────────────────────────────
// Stub for Phase 0. Phase 5 wires tauri-plugin-dialog.

export async function pickDirectory(): Promise<string | null> {
  if (!isTauri()) {
    // Browser cannot prompt for a real directory path. Return null;
    // caller should fall back to the hardcoded WORKSPACE_PATH default.
    return null
  }
  const mod = await loadPlugin<{
    open: (opts: object) => Promise<string | string[] | null>
  }>('@tauri-apps/plugin-dialog')
  if (!mod) return null
  const picked = await mod.open({ directory: true, multiple: false })
  return typeof picked === 'string' ? picked : null
}

// ─── File system ──────────────────────────────────────────────────
// Stubs for Phase 0. Phase 5 wires tauri-plugin-fs.

export async function readTextFile(path: string): Promise<string> {
  if (!isTauri()) {
    throw new Error(`readTextFile not available in browser (path: ${path})`)
  }
  const mod = await loadPlugin<{
    readTextFile: (path: string) => Promise<string>
  }>('@tauri-apps/plugin-fs')
  if (!mod) {
    throw new Error(`tauri-plugin-fs not wired yet (path: ${path})`)
  }
  return mod.readTextFile(path)
}

// ─── Workspace path (P1 placeholder) ──────────────────────────────
// REFACTOR Q2: P1 ships hardcoded ~/finagent. Phase 5 (T5.6) wires
// real dialog.open + persistence; for now this constant is the
// authoritative default and lives in uiStore.

export const DEFAULT_WORKSPACE_PATH = '~/finagent'
