import { test, expect } from '@playwright/test'

// Cold-start (no coverage yet) leads with the SAME search hero as the populated
// desk — one identity (UX-014) — and drives into research, not a "create group"
// form (UX-001). Backend stubbed: zero groups.

test.use({ viewport: { width: 1280, height: 900 } })

test('cold start is search-first: hero + quick-pick, no create-group form', async ({ page }) => {
  await page.route('**/api/coverage/groups', (r) =>
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  )

  await page.goto('/coverage')
  const empty = page.getByTestId('coverage-empty')
  await expect(empty).toBeVisible({ timeout: 8000 })
  // The search hero is the primary CTA (same component as the populated desk).
  await expect(page.getByTestId('coverage-hero')).toBeVisible()
  // Quick-pick chips drive straight into a ticker workspace.
  await expect(empty.getByRole('button', { name: /Research AAPL|研究 AAPL/ })).toBeVisible()
  await page.screenshot({ path: 'e2e/_coverage-coldstart.png' })

  // Clicking a quick-pick chip navigates to /stocks/:ticker (research entry).
  await empty.getByRole('button', { name: /Research NVDA|研究 NVDA/ }).click()
  await expect(page).toHaveURL(/\/stocks\/NVDA/)
})
