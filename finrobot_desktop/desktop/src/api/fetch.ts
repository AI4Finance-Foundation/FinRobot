import { getCapabilityToken } from './capability'
import { isBackendUrl } from './backendUrl'
import { acquireHeavySlot, isHeavyApiPath } from './requestLanes'

export const DEFAULT_API_TIMEOUT_MS = 8_000

// Heavy endpoints — provider round-trips (historical / earnings-calls /
// valuation aggregate / artifact diff) and compute (dcf-seed) that legitimately
// take longer than a snappy 8s. Still bounded so a wedged backend can't hang the
// query forever; the long-running research pipeline does NOT use this — it streams
// over EventSource, which carries no fetch timeout.
export const HEAVY_API_TIMEOUT_MS = 30_000

export class RequestTimeoutError extends Error {
  readonly timeoutMs: number

  constructor(timeoutMs: number) {
    super(`Request timed out after ${timeoutMs}ms`)
    this.name = 'RequestTimeoutError'
    this.timeoutMs = timeoutMs
  }
}

// True when the request targets our local backend: a relative path the Vite dev
// proxy forwards, or the absolute loopback URL in a packaged build — never a
// third-party host. Gates token injection so the capability token can't leak
// off-box even if some caller passes an external URL through fetchWithTimeout.
function backendBound(input: RequestInfo | URL): boolean {
  const url = typeof input === 'string' || input instanceof URL ? input : input.url
  return isBackendUrl(url)
}

/**
 * The single capability-token injection home for fetch-based backend calls
 * (EventSource cannot set headers, so it uses withCapabilityToken's ?token=
 * instead). Every backend request flows through fetchWithTimeout — the typed
 * openapi-fetch client uses it as its `fetch`, and the hooks/stores/pages call
 * it directly — so injecting here covers all of them with no per-call-site
 * bookkeeping. No-op for non-backend URLs and in browser dev (no token).
 */
async function injectCapabilityToken(
  input: RequestInfo | URL,
  init: RequestInit,
): Promise<RequestInit> {
  if (!backendBound(input)) return init
  const token = await getCapabilityToken()
  if (!token) return init
  if (input instanceof Request) {
    // openapi-fetch hands us a prebuilt Request; mutate its (mutable) headers
    // in place — the same pattern openapi-fetch's own onRequest middleware uses.
    input.headers.set('Authorization', `Bearer ${token}`)
    return init
  }
  const headers = new Headers(init.headers)
  headers.set('Authorization', `Bearer ${token}`)
  return { ...init, headers }
}

/**
 * Token-injecting fetch with NO timeout — for long-lived streaming responses.
 * The AI chat's SSE-over-fetch runs 30-60s, so it must not carry the 8s cap;
 * pass this as DefaultChatTransport's `fetch` so /chat is authenticated like
 * every other backend call without being killed mid-stream.
 */
export async function fetchBackendStream(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const authedInit = await injectCapabilityToken(input, init)
  return fetch(input, authedInit)
}

export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs = DEFAULT_API_TIMEOUT_MS,
): Promise<Response> {
  const authedInit = await injectCapabilityToken(input, init)
  const callerSignal = authedInit.signal

  // Heavy lane (requestLanes.ts): cap concurrent provider/compute calls so a
  // millisecond local read (artifact timeline) always finds a free browser
  // socket instead of queueing behind 5-15 s live fetches. Acquired BEFORE the
  // timeout timer starts — lane wait is not request time, so a throttled live
  // call can't surface as a fake timeout error on an honest degraded card.
  // An abort while queued rejects with the same AbortError fetch would throw.
  const release = isHeavyApiPath(input) ? await acquireHeavySlot(callerSignal ?? undefined) : null

  const controller = new AbortController()
  let timedOut = false

  const timeoutId = globalThis.setTimeout(() => {
    timedOut = true
    controller.abort()
  }, timeoutMs)

  const abortFromCaller = () => controller.abort()
  if (callerSignal?.aborted) {
    abortFromCaller()
  } else {
    callerSignal?.addEventListener('abort', abortFromCaller, { once: true })
  }

  try {
    return await fetch(input, { ...authedInit, signal: controller.signal })
  } catch (err) {
    if (timedOut) throw new RequestTimeoutError(timeoutMs)
    throw err
  } finally {
    release?.()
    globalThis.clearTimeout(timeoutId)
    callerSignal?.removeEventListener('abort', abortFromCaller)
  }
}
