// One-off: render the live Spline robot scene and capture a clean square still
// to use as the desktop app icon master. Not part of the build — run by hand.
import { chromium } from 'playwright'

const SCRIPT_SRC = 'https://unpkg.com/@splinetool/viewer@1.9.54/build/spline-viewer.js'
const SCENE_SRC = 'https://prod.spline.design/kZDDjO5HuC9GJUM2/scene.splinecode'
const OUT = new URL('./robot-shot.png', import.meta.url).pathname

const browser = await chromium.launch({
  proxy: { server: 'http://127.0.0.1:7897' },
  args: ['--use-gl=angle', '--use-angle=swiftshader', '--ignore-gpu-blocklist'],
})
const page = await browser.newPage({
  viewport: { width: 1024, height: 1024 },
  deviceScaleFactor: 2,
})

await page.setContent(`<!doctype html><html><head><style>
  html,body{margin:0;background:transparent}
  spline-viewer{width:1024px;height:1024px;display:block}
</style></head><body>
  <spline-viewer url="${SCENE_SRC}"></spline-viewer>
  <script type="module" src="${SCRIPT_SRC}"></script>
</body></html>`)

// Wait for the viewer custom element + a couple seconds of settle for the
// intro zoom to land on the robot.
await page.waitForFunction(() => !!customElements.get('spline-viewer'), { timeout: 30000 })
await page.waitForTimeout(9000)

// Kill the "Built with Spline" badge inside shadow DOM before the shot.
await page.evaluate(() => {
  const v = document.querySelector('spline-viewer')
  const root = v && v.shadowRoot
  if (root) {
    const s = document.createElement('style')
    s.textContent = '#logo,.logo,a[href*="spline.design"]{display:none!important}'
    root.appendChild(s)
  }
})

const el = await page.$('spline-viewer')
await el.screenshot({ path: OUT, omitBackground: true })
console.log('wrote', OUT)
await browser.close()
