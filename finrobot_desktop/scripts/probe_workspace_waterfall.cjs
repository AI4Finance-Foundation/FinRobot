// probe_workspace_waterfall.cjs — measure the workspace's REAL request waterfall
// in a browser, at the final consumption surface (user-perceived latency).
//
// WHY THIS EXISTS: "report history slower than live market data" was fixed 3x
// at the backend (each time verified with curl against the endpoint) and kept
// recurring, because the actual bottleneck was the browser's ~6-connection
// per-origin HTTP/1.1 pool — invisible to any server-side measurement. Rule:
// a performance claim about a UI surface is only verified by THIS kind of
// browser waterfall, never by endpoint latency alone (复发台账 2026-07-02,
// surface-钉最终消费面 家族).
//
// Usage (backend on :8321 + vite on :5173 must be running, e.g. ./dev.sh):
//   TICKER=PG node scripts/probe_workspace_waterfall.cjs
//
// Pick a ticker with artifacts in ~/.finrobot/artifacts.db but a COLD live
// cache (no recent rows in data_cache.db) — cold provider fetches are what
// exposes queueing. Interpret: the timeline request (local SQLite read, ~2ms
// server-side) must complete in <300ms wall-clock; if it lands seconds after
// START while /api/data|sentiment|valuation requests are in flight, fast-lane
// requests are queueing again (see desktop/src/api/requestLanes.ts).

const path = require('path')
const { chromium } = require(
  path.join(__dirname, '..', 'desktop', 'node_modules', '@playwright', 'test'),
)

const TICKER = process.env.TICKER || 'MSFT'
const BASE = process.env.BASE_URL || 'http://localhost:5173'
const SETTLE_MS = Number(process.env.SETTLE_MS || 20000)

;(async () => {
  const browser = await chromium.launch()
  const page = await browser.newPage()
  const t0 = Date.now()
  const events = []
  const short = (u) => u.replace(BASE, '').replace(/token=[^&]+/, 'token=~')
  const isApi = (u) => u.includes('/api/') || u.includes('/health')
  page.on('request', (req) => {
    if (isApi(req.url()))
      events.push({ t: Date.now() - t0, ev: 'START', url: short(req.url()), method: req.method() })
  })
  page.on('requestfinished', async (req) => {
    if (isApi(req.url())) {
      const resp = await req.response()
      events.push({
        t: Date.now() - t0,
        ev: 'DONE ',
        url: short(req.url()),
        status: resp ? resp.status() : null,
      })
    }
  })
  page.on('requestfailed', (req) => {
    if (req.url().includes('/api/'))
      events.push({ t: Date.now() - t0, ev: 'FAIL ', url: short(req.url()) })
  })

  await page.goto(`${BASE}/stocks/${TICKER}`, { waitUntil: 'domcontentloaded' })
  const deadline = Date.now() + 30000
  while (Date.now() < deadline) {
    if (events.find((e) => e.ev === 'DONE ' && e.url.includes('/timeline'))) {
      await page.waitForTimeout(SETTLE_MS) // let queued heavy calls dispatch + finish
      break
    }
    await page.waitForTimeout(250)
  }

  for (const e of events) {
    console.log(
      String(e.t).padStart(6) + 'ms',
      e.ev,
      e.method || '',
      e.status || '',
      e.url.slice(0, 110),
    )
  }
  const tlStart = events.find((e) => e.ev === 'START' && e.url.includes('/timeline'))
  const tlDone = events.find((e) => e.ev === 'DONE ' && e.url.includes('/timeline'))
  if (tlStart && tlDone) {
    const ms = tlDone.t - tlStart.t
    console.log(
      `\ntimeline wall-clock: ${ms}ms — ${ms < 300 ? 'OK (fast lane clear)' : 'SLOW: local read is queueing behind heavy calls'}`,
    )
  } else {
    console.log('\ntimeline request never completed — backend down or ticker has no artifacts?')
  }
  await browser.close()
})()
