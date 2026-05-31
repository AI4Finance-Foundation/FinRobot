import createClient from 'openapi-fetch'
import type { paths } from './schema'
import { fetchWithTimeout } from './fetch'

// Dev: empty string → relative paths go through Vite proxy (same origin, no CORS).
// Prod: Electron loads from file://, so we need the absolute backend URL.
const BASE_URL = import.meta.env.DEV ? '' : 'http://127.0.0.1:8321'

export const api = createClient<paths>({ baseUrl: BASE_URL, fetch: fetchWithTimeout })

export { BASE_URL }

export async function exportDiagnosticsLogs(): Promise<Blob> {
  const res = await fetch(`${BASE_URL}/api/diagnostics/logs/export`)
  if (!res.ok) throw new Error(`export failed: ${res.status}`)
  return res.blob()
}
