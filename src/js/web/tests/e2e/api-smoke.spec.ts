/**
 * Minimal harness smoke test (issue #197).
 *
 * Proves the Playwright e2e pair boots end-to-end *with the real API
 * present*: the API webServer migrates + seeds a throwaway file SQLite
 * DB and clears the ADR-021 startup gate, Vite serves the SPA, and the
 * browser reaches a rendered route. Before #197 this could not pass —
 * the API crashed at boot against an unmigrated in-memory DB.
 *
 * Deliberately small: it exercises the API+app pair, not login logic.
 * It is NOT skipped (unlike the three lifecycle specs, which wait on
 * the #81 selector rewrite). It does not depend on the seeded
 * admin/admin credentials — it only asserts the login route renders.
 */

import { expect, test } from '@playwright/test'

test('login route renders with the API present', async ({ page }) => {
  await page.goto('/login')

  await expect(page.getByRole('heading', { name: 'Sign in' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: 'Username' })).toBeVisible()
  await expect(page.getByLabel('Password')).toBeVisible()
  await expect(page.getByRole('button', { name: /Sign in/ })).toBeVisible()
})
