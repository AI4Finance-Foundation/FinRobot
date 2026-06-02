import { test, expect } from '@playwright/test'

// Visual harness for the MarketImpliedPanel (reverse-DCF expert probe).
// Backend isn't required — every /api/* call is stubbed (page.route), including
// the debate SSE stream, so the page reaches the completed state and the panel
// renders against fixed NVDA-shaped data.

const SSE_BODY = [
  'event: debate.evidence',
  'data: ' +
    JSON.stringify({
      event: 'debate.evidence',
      ticker: 'NVDA',
      current_price: 224.36,
      reliable: true,
      items: [{ evidence_id: 'method.dcf.mid', label: 'dcf 中值估值', value: 72.86, unit: '$' }],
    }),
  '',
  'event: debate.point',
  'data: ' +
    JSON.stringify({
      event: 'debate.point',
      side: 'bear',
      claim: '在 WACC 16.6%、5年增长40%→2.5% 的假设下，DCF 仅 72.86，远低于现价。',
      evidence_ids: ['method.dcf.mid'],
      verified: true,
      reason: '',
    }),
  '',
  'event: debate.verdict',
  'data: ' +
    JSON.stringify({
      call: 'SELL',
      conviction: 0.75,
      swing_factor: '同业 P/E 对 NVDA 盈利质量的适用性是否足以抵消 DCF 下行风险',
      change_my_mind: '若能证明 NVDA 增长率持续高于当前假设，DCF 显著上调',
    }),
  '',
  'event: run.completed',
  'data: {}',
  '',
  '',
].join('\n')

const SEED = {
  reverse_growth: {
    implied_growth: null,
    implied_wacc: null,
    implied_horizon: null,
    assumed_growth: null,
    wacc: 0.166,
    terminal_growth: 0.025,
    message: '在固定增长率上限、WACC 16.6% + 5年窗口下，目标价够不着——增长这根轴撑不到 $224。',
  },
  reverse_wacc: {
    implied_growth: null,
    implied_wacc: 0.076,
    implied_horizon: null,
    assumed_growth: null,
    wacc: 0.166,
    terminal_growth: 0.025,
    message:
      '固定 40%→2.5% 增长曲线 + 5年窗口下，市场隐含 WACC 7.6%——低到债券级，多半是窗口太短的投影。',
  },
  reverse_horizon: {
    implied_growth: null,
    implied_wacc: null,
    implied_horizon: 7.5,
    assumed_growth: 0.4,
    wacc: 0.166,
    terminal_growth: 0.025,
    message:
      '在固定增长率 40%、WACC 16.6% 下，$224 隐含约 7.5 年高增长窗口。换个增长率年限就不同。',
  },
  current_price: 224.36,
}

const LINE = {
  ticker: 'NVDA',
  target_price: 224.36,
  wacc: 0.166,
  terminal_growth: 0.025,
  points: [
    { growth: 0.2, implied_horizon: 22.7 },
    { growth: 0.25, implied_horizon: 14.6 },
    { growth: 0.3, implied_horizon: 11.0 },
    { growth: 0.35, implied_horizon: 8.9 },
    { growth: 0.4, implied_horizon: 7.5 },
    { growth: 0.45, implied_horizon: 6.5 },
    { growth: 0.5, implied_horizon: 5.7 },
  ],
}

test('market-implied panel renders cards + equivalence line', async ({ page }) => {
  await page.route('**/api/debate', (r) =>
    r.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ run_id: 'test-run' }),
    }),
  )
  await page.route('**/api/runs/*/events', (r) =>
    r.fulfill({ status: 200, contentType: 'text/event-stream', body: SSE_BODY }),
  )
  await page.route('**/api/compute/dcf-seed', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SEED) }),
  )
  await page.route('**/api/compute/dcf-equivalence-line', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LINE) }),
  )

  await page.goto('/ic/NVDA?artifact_id=harness')
  await page.getByRole('button', { name: /开始投委会辩论/ }).click()

  // Wait for the completed verdict (SELL) → the panel mounts (collapsed).
  await expect(page.getByText('市场隐含预期')).toBeVisible({ timeout: 8000 })
  await page.getByText('市场隐含预期').click()
  // Line section (unique title) confirms cards + chart fetched and rendered.
  await expect(page.getByText('增长 → 隐含年限 等价线')).toBeVisible({ timeout: 8000 })
  await page.waitForTimeout(900)
  // Screenshot the panel element directly (AppShell scrolls an inner container,
  // so fullPage can't reach below-fold content).
  const panel = page.getByTestId('market-implied-panel')
  await panel.scrollIntoViewIfNeeded()
  await panel.screenshot({ path: 'e2e/_market-implied.png' })
})
