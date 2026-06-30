// Per-launch capability token — the WebView's half of the local-API auth.
//
// The Tauri shell mints a random token at launch (see src-tauri/src/lib.rs),
// hands it to the Python sidecar via FINROBOT_CAPABILITY_TOKEN, and exposes it
// to this WebView via the `capability_token` command. We attach it to every
// backend request so a different local process — which can reach loopback but
// cannot drive this WebView's IPC — cannot read /api/settings or burn quota.
//
// In a plain browser (Vite dev, no Tauri) there is no command and no token:
// getCapabilityToken() resolves null and the backend runs auth-disabled, so the
// dev loop is unchanged.

import { invoke } from '@tauri-apps/api/core'
import { isBackendUrl } from './backendUrl'
import { isTauri } from '../lib/tauri'

// Memoize: the token is constant for the process lifetime, and we don't want to
// cross the IPC boundary on every request. `pending` dedupes concurrent first
// callers; `resolved` is the settled value (null included).
let pending: Promise<string | null> | null = null
let resolved: { value: string | null } | null = null

export async function getCapabilityToken(): Promise<string | null> {
  if (resolved) return resolved.value
  if (!pending) {
    pending = (async () => {
      if (!isTauri()) return null
      try {
        return await invoke<string>('capability_token')
      } catch (err) {
        // A missing command / IPC failure must not wedge every request. The
        // backend rejects with 401 if it truly required a token; surface that
        // at the call site rather than hanging here.
        console.warn('[capability] could not read token from Tauri:', err)
        return null
      }
    })()
  }
  const value = await pending
  resolved = { value }
  return value
}

/**
 * Append the capability token as a `token` query parameter. EventSource (SSE)
 * cannot set an Authorization header, so the run event streams carry
 * the token this way instead. Returns the URL unchanged when no token is
 * configured (browser dev).
 */
export async function withCapabilityToken(url: string): Promise<string> {
  if (!isBackendUrl(url)) return url
  const token = await getCapabilityToken()
  if (!token) return url
  const sep = url.includes('?') ? '&' : '?'
  return `${url}${sep}token=${encodeURIComponent(token)}`
}

/** Test seam — clear the memoized token between cases. */
export function __resetCapabilityTokenCache(): void {
  pending = null
  resolved = null
}
