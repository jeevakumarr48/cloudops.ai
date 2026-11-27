import { expect, test } from '@playwright/test'

test.describe('public demo', () => {
  test('a visitor can explore findings and fix commands without an account', async ({ page, isMobile }) => {
    await page.goto('/')
    await page.getByRole('button', { name: /Try the demo/ }).first().click()
    await expect(page).toHaveURL(/demo=1/)
    await expect(page.getByRole('status').filter({ hasText: 'Sample data, not a real AWS account' })).toBeVisible()

    const rows = page.locator('.finding-tr')
    await expect(rows.first()).toBeVisible()
    expect(await rows.count()).toBeGreaterThan(10)
    await rows.first().click()
    await expect(page.getByRole('heading', { name: 'Evidence' })).toBeVisible()
    await expect(page.getByText('Status changes', { exact: false })).toHaveCount(0)

    if (isMobile) await page.getByRole('button', { name: 'Open navigation' }).click()
    await page.getByRole('button', { name: 'Recommendations', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Where to start' })).toBeVisible()
    const firstFix = page.locator('.rec-card').first().getByRole('button', { name: /How to fix it/ })
    await firstFix.click()
    await expect(page.getByText('CloudOps never runs these commands').first()).toBeVisible()
    await expect(page.locator('.fix-code').first()).toContainText('aws ')
    await expect(page.getByRole('button', { name: /Rewrite/ })).toHaveCount(0)
  })

  test('the demo link survives a reload and can be exited', async ({ page }) => {
    await page.goto('/?demo=1')
    await expect(page.locator('.finding-tr').first()).toBeVisible()
    await page.reload()
    await expect(page.locator('.demo-banner')).toBeVisible()
    await page.getByRole('button', { name: /Exit demo/ }).click()
    await expect(page.locator('.demo-banner')).toHaveCount(0)
    await expect(page).not.toHaveURL(/demo=1/)
  })

  test('live-data pages explain that they are not part of the demo', async ({ page, isMobile }) => {
    await page.goto('/?demo=1')
    if (isMobile) await page.getByRole('button', { name: 'Open navigation' }).click()
    await page.getByRole('button', { name: 'Overview', exact: true }).click()
    await expect(page.getByText('Overview uses live AWS data')).toBeVisible()
  })

  test('the page never scrolls sideways', async ({ page }) => {
    await page.goto('/?demo=1')
    await expect(page.locator('.finding-tr').first()).toBeVisible()
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    expect(overflow).toBeLessThanOrEqual(0)
  })
})
