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

// ─── Forced-update floor (min-version.json) ──────────────────────────────────
// Every release publishes a min-version.json next to latest.json; when the
// installed version is below it, the app blocks until updated (mandatory
// update). Keep this base URL in sync with the updater endpoint in
// src-tauri/tauri.conf.json → plugins.updater.endpoints.
const RELEASES_LATEST_BASE =
  'https://github.com/AI4Finance-Foundation/FinRobot/releases/latest/download'

/** Minimum supported version published alongside the latest release. Returns
 *  null in the browser, or when the file is absent / unreadable / blocked — the
 *  caller then degrades to a normal optional update (never a false block). */
export async function fetchMinVersion(): Promise<string | null> {
  if (!isTauri()) return null
  try {
    const resp = await fetch(`${RELEASES_LATEST_BASE}/min-version.json`, { cache: 'no-store' })
    if (!resp.ok) return null
    const j = (await resp.json()) as { min_version?: unknown }
    return typeof j.min_version === 'string' ? j.min_version : null
  } catch {
    return null
  }
}

/** Compare two dotted versions numerically. -1 if a<b, 0 if equal, 1 if a>b. */
export function compareVersions(a: string, b: string): number {
  const pa = a.split('.').map((n) => parseInt(n, 10) || 0)
  const pb = b.split('.').map((n) => parseInt(n, 10) || 0)
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0)
    if (d !== 0) return d < 0 ? -1 : 1
  }
  return 0
}
