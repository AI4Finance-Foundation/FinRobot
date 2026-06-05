// Tauri auto-update wrapper.
//
// Mirrors lib/tauri.ts: every function is safe in both the browser (dev, where
// there is no Tauri runtime) and the packaged app. In the browser these are
// no-ops so the dev loop never sees an updater error — the real check/install
// only runs inside the Tauri webview against the configured GitHub endpoint
// (see src-tauri/tauri.conf.json → plugins.updater).

import { check, type Update, type DownloadEvent } from '@tauri-apps/plugin-updater'
import { relaunch } from '@tauri-apps/plugin-process'
import { getVersion } from '@tauri-apps/api/app'
import { isTauri } from './tauri'

export type { Update, DownloadEvent }

/** Hits the updater endpoint and returns an Update when a newer version exists,
 *  or null when up to date. Returns null in the browser (no Tauri runtime). */
export async function checkForUpdate(): Promise<Update | null> {
  if (!isTauri()) return null
  return check()
}

/** Current installed app version (from tauri.conf.json), e.g. "0.1.0".
 *  Returns null in the browser where the app API is unavailable. */
export async function currentAppVersion(): Promise<string | null> {
  if (!isTauri()) return null
  try {
    return await getVersion()
  } catch {
    return null
  }
}

/** Relaunch the app after an update is installed. No-op in the browser. */
export async function relaunchApp(): Promise<void> {
  if (!isTauri()) return
  await relaunch()
}
