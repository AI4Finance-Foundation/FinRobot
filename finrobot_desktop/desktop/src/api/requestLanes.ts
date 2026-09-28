// requestLanes — two-lane client-side scheduler for backend API calls.
//
// WHY: the webview speaks HTTP/1.1 to the loopback backend, and every browser
// caps concurrent connections per origin at ~6. The workspace fires 7+ API
// calls on mount; the live-provider ones legitimately take seconds each, and
// once they occupy all 6 sockets a millisecond local-SQLite read (the artifact
// timeline) queues behind them in the BROWSER — measured: 2 ms server time,
// 2.6 s in-page. The backend is fully async and never the bottleneck; the
// scarce resource is the client connection pool, so it is managed here, at the
// single fetch chokepoint, instead of by fragile component-mount ordering.
//
// Socket budget (6 per origin): ≤ HEAVY_LANE_LIMIT heavy calls + 1 long-lived
// stream (run SSE / chat) + at least 1 always free for fast local reads and
// health probes. Fast-lane calls all resolve in milliseconds, so they drain
// through the spare sockets no matter how many fire.

export const HEAVY_LANE_LIMIT = 4

// Paths whose handlers await live provider round-trips (yfinance / FMP /
// EDGAR) or multi-second compute. Everything NOT listed here (artifacts /
// runs / coverage / dashboard / settings / health / chat-sessions) reads
// local state in milliseconds and must NEVER wait behind a provider call.
// A new endpoint belongs here iff its handler awaits a provider/network or
// heavy compute; local-SQLite reads stay off this list.
const HEAVY_PATH_PREFIXES = [
  '/api/data/',
  '/api/sentiment/',
  '/api/valuation/',
  '/api/compute/',
  '/api/search',
  '/api/sec-holdings',
]

function pathnameOf(input: RequestInfo | URL): string {
  const raw = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
  try {
    // Base only matters for relative dev-proxy paths ('/api/…'); absolute
    // packaged-build URLs keep their own origin. Query strings never match —
    // we compare pathname only.
    return new URL(raw, 'http://relative.invalid').pathname
  } catch {
    return ''
  }
}

export function isHeavyApiPath(input: RequestInfo | URL): boolean {
  const path = pathnameOf(input)
  return HEAVY_PATH_PREFIXES.some((p) => path.startsWith(p))
}

interface Waiter {
  grant: () => void
  onAbort: () => void
  signal: AbortSignal | undefined
}

let active = 0
const waiters: Waiter[] = []

function abortError(): DOMException {
  return new DOMException('The operation was aborted.', 'AbortError')
}

// Each grant gets its own idempotent release — a double call (defensive
// finally paths) must not inflate capacity.
function makeRelease(): () => void {
  let released = false
  return () => {
    if (released) return
    released = true
    active -= 1
    dispatchNext()
  }
}

function dispatchNext(): void {
  while (active < HEAVY_LANE_LIMIT) {
    const next = waiters.shift()
    if (!next) return
    active += 1
    next.grant()
  }
}

/**
 * Acquire a heavy-lane slot; resolves with the matching release function.
 * FIFO. An abort of `signal` while queued removes the waiter and rejects
 * with a DOMException named AbortError — the same shape fetch itself throws —
 * so callers (React Query cancellation on unmount) treat it as a cancel.
 * The caller MUST invoke the release in a finally around its fetch.
 */
export function acquireHeavySlot(signal?: AbortSignal): Promise<() => void> {
  if (signal?.aborted) return Promise.reject(abortError())
  if (active < HEAVY_LANE_LIMIT) {
    active += 1
    return Promise.resolve(makeRelease())
  }
  return new Promise<() => void>((resolve, reject) => {
    const waiter: Waiter = {
      signal,
      grant: () => {
        signal?.removeEventListener('abort', waiter.onAbort)
        resolve(makeRelease())
      },
      onAbort: () => {
        const i = waiters.indexOf(waiter)
        if (i >= 0) waiters.splice(i, 1)
        reject(abortError())
      },
    }
    signal?.addEventListener('abort', waiter.onAbort, { once: true })
    waiters.push(waiter)
  })
}

/** Test-only: restore full capacity and drop queued waiters. */
export function __resetRequestLanes(): void {
  active = 0
  waiters.length = 0
}
