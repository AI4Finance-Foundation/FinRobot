import createClient from 'openapi-fetch'
import type { paths } from './schema'
import { fetchWithTimeout } from './fetch'

// Dev: empty string → relative paths go through Vite proxy (same origin, no CORS).
// Prod: Electron loads from file://, so we need the absolute backend URL.
const BASE_URL = import.meta.env.DEV ? '' : 'http://127.0.0.1:8321'

export const api = createClient<paths>({ baseUrl: BASE_URL, fetch: fetchWithTimeout })

export { BASE_URL }

/**
 * Mark an artifact as viewed (POST /api/artifacts/{id}/view).
 *
 * This refreshes the backend's `last_viewed_at` so the stale-archive task
 * (30-day window keyed on last_viewed_at || created_at) does not auto-archive
 * reports the user is actively reading. Returns the resolved artifact id on
 * success.
 *
 * Throws on any non-2xx (caller decides how loud to be — a 404/410 means the
 * artifact is gone; a network blip should not block reading the report).
 */
export async function markArtifactViewed(artifactId: string): Promise<string> {
  const { data, error, response } = await api.POST('/api/artifacts/{artifact_id}/view', {
    params: { path: { artifact_id: artifactId } },
  })
  if (error) {
    throw new Error(`markArtifactViewed failed (${response.status}): ${artifactId}`)
  }
  return data.id
}

/**
 * Permanently delete an artifact (DELETE /api/artifacts/{id}).
 *
 * Irreversible — the artifact and its index entry are removed, which also busts
 * the dashboard hit-rate / recent-research caches server-side. Throws on any
 * non-2xx (404 = already gone) so the caller can surface it; callers should
 * confirm with the user FIRST (deletion can't be undone).
 */
export async function deleteArtifact(id: string): Promise<void> {
  const { error, response } = await api.DELETE('/api/artifacts/{artifact_id}', {
    params: { path: { artifact_id: id } },
  })
  if (error) {
    throw new Error(`deleteArtifact failed (${response.status}): ${id}`)
  }
}
