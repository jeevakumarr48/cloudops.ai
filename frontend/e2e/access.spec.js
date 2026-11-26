import { expect, test } from '@playwright/test'

test('live AWS data and findings are private when signed out', async ({ page, request }) => {
  for (const path of ['/api/overview', '/api/costs', '/api/resources/ec2', '/api/governance/summary', '/api/ai/recommendations']) {
    const response = await request.get(path)
    expect(response.status(), path).toBe(401)
  }
  await page.goto('/')
  await expect(page.getByText('Sign in to view governance data')).toBeVisible()
  await expect(page.getByRole('button', { name: /Explore the demo/ })).toBeVisible()
})

test('an operator can sign in and sees the console even without AWS access', async ({ page, isMobile }) => {
  test.skip(isMobile, 'covered on desktop')
  await page.goto('/')
  await page.locator('.access-gate').getByRole('button', { name: 'Sign in' }).click()
  await page.getByText('Create one').click()
  await page.getByLabel('Email').fill('e2e-operator@example.com')
  await page.getByLabel(/^Password/).fill('correct horse battery staple')
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.locator('.account-role')).toHaveText('Operator')

  await page.getByRole('button', { name: 'Governance', exact: true }).click()
  // No AWS access in CI: every source reports unavailable instead of failing the page.
  await expect(page.getByRole('heading', { name: 'Governance findings' })).toBeVisible()
  await expect(page.locator('main:visible .source-status')).toContainText(/unavailable|not scanned/i)

  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('button', { name: /Try the demo/ })).toBeVisible()
})
