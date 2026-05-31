/**
 * Harness smoke test: proves the e2e pair boots end-to-end with the real
 * API present — the API clears the ADR-021 startup gate, Vite serves the
 * SPA, and the browser reaches a rendered route. Asserts only that the
 * login route renders, not login logic.
 */

import { expect, test } from '@playwright/test'

test('login route renders with the API present', async ({ page }) => {
  await page.goto('/login')

  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Username' })).toBeVisible()
  await expect(page.getByLabel('Password')).toBeVisible()
  await expect(page.getByRole('button', { name: /Sign in/ })).toBeVisible()
})
