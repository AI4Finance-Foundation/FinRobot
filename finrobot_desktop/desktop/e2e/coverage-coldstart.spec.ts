import { test, expect } from '@playwright/test'

// Cold-start (no coverage records yet). Coverage is the management surface, not a
// research entry point — research starts from /research — so the empty state is
// an archive-empty card whose single CTA opens Research. Backend stubbed: zero
// groups.

test.use({ viewport: { width: 1280, height: 900 } })

test('cold start shows the archive-empty card and routes to Research', async ({ page }) => {
  await page.route('**/api/coverage/groups', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )

  await page.goto('/coverage')
  const empty = page.getByTestId('coverage-empty')
  await expect(empty).toBeVisible({ timeout: 8000 })
  await expect(empty).toContainText(/No coverage records yet|还没有覆盖记录/)

  // The single CTA opens Research (the search-first door).
  const cta = empty.getByRole('button', { name: /Open Research|打开研究入口/ })
  await expect(cta).toBeVisible()
  await page.screenshot({ path: 'e2e/_coverage-coldstart.png' })

  await cta.click()
  await expect(page).toHaveURL(/\/research/)
})
