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

export async function fetchWithTimeout(
  input: RequestInfo | URL,
  init: RequestInit = {},
  timeoutMs = DEFAULT_API_TIMEOUT_MS,
): Promise<Response> {
  const controller = new AbortController()
  const callerSignal = init.signal
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
    return await fetch(input, { ...init, signal: controller.signal })
  } catch (err) {
    if (timedOut) throw new RequestTimeoutError(timeoutMs)
    throw err
  } finally {
    globalThis.clearTimeout(timeoutId)
    callerSignal?.removeEventListener('abort', abortFromCaller)
  }
}
