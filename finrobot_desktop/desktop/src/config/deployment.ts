// How this build is being hosted.
//
// The desktop app is single-user: whoever opens it owns the machine and may
// configure it. When the same bundle is served over HTTP by a host that manages
// accounts, that host decides whether the current viewer may change deployment
// settings (API keys, providers, log level) — those are shared by everyone the
// host serves, not per-viewer.
//
// The host states its decision in the URL it loads this bundle with. Read once
// at module load: react-router rewrites the address as the user navigates, so
// re-reading it later would lose the flag.

function readSettingsFlag(): boolean {
  if (typeof window === 'undefined') return true
  try {
    return new URLSearchParams(window.location.search).get('settings') !== '0'
  } catch {
    return true
  }
}

/**
 * Whether to offer the Settings door.
 *
 * Defaults to true, so the desktop app and `npm run dev` are unaffected. This
 * is presentation only — the host is what actually refuses a write, since a
 * flag in a URL is trivially edited.
 */
export const SETTINGS_ALLOWED: boolean = readSettingsFlag()
