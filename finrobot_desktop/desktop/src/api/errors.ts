/**
 * Centralised HTTP error parsing for fetch-based hooks.
 *
 * The backend returns user-facing detail strings on errors (see
 * finrobot/routes/data.py _data_http_error). Every HTTPException across the
 * backend uses a string detail, so this helper pulls that string out of the
 * FastAPI error envelope `{detail: string}` and falls back to a caller-supplied
 * default if the body is empty or unparseable.
 *
 * Status code semantics (matching the backend):
 *   422 — input invalid / ticker not recognised (ValueError)
 *   502 — data provider failed upstream (ProviderError)
 *   503 — capability disabled (missing API key, etc.)
 */

export async function extractErrorDetail(resp: Response, fallback: string): Promise<string> {
  const body = await resp.json().catch(() => null as unknown as { detail?: unknown } | null)

  const detail = body?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  // Do not leak HTTP status to end users — they don't care, and "HTTP 500"
  // looks like a crash. The dev-side info is still in resp.status / network tab.
  return fallback
}
