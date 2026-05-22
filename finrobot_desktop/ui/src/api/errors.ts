/**
 * Centralised HTTP error parsing for fetch-based hooks.
 *
 * The backend returns Chinese, user-facing detail strings on errors (see
 * finagent/routes/data.py _data_http_error). This helper pulls that detail out
 * of the FastAPI error envelope `{detail: string|object}` and falls back to a
 * caller-supplied 中文 default if the body is empty or unparseable.
 *
 * Status code semantics (matching the backend):
 *   422 — input invalid / ticker not recognised (ValueError)
 *   502 — data provider failed upstream (ProviderError)
 *   503 — capability disabled (missing API key, etc.)
 */

export async function extractErrorDetail(
  resp: Response,
  fallback: string,
): Promise<string> {
  const body = await resp
    .json()
    .catch(() => null as unknown as { detail?: unknown } | null)

  const detail = body?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object') {
    // Some endpoints (catalysts) return {error, message, ticker}
    const message =
      (detail as { message?: string }).message ??
      (detail as { error?: string }).error
    if (message) return message
  }
  return `${fallback}（HTTP ${resp.status}）`
}
