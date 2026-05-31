/**
 * Playwright e2e for the OPFS feature probe (ADR-003) and the
 * blocking error UI it routes to.
 *
 * Two cases:
 *
 * 1. Cross-origin isolation missing — we override
 *    ``window.crossOriginIsolated`` to ``false`` via ``addInitScript``
 *    before navigation. The probe in ``$lib/db/probe`` runs at layout
 *    mount, sees the override, and routes to ``/unsupported?missing=
 *    cross_origin_isolation``. The blocking UI must surface BOTH the
 *    failed precondition AND the supported-browser list (acceptance
 *    criterion).
 *
 * 2. Direct visit to ``/unsupported`` with a query param renders the
 *    matching reason. Confirms a reload / bookmark of the error URL
 *    still names the right precondition.
 *
 * COOP/COEP are set on the Vite dev server (see ``vite.config.ts``),
 * so ``crossOriginIsolated`` is genuinely ``true`` in a vanilla browser
 * context. The override is the cheapest reliable way to drive the
 * probe into its failure branch without spinning a second server with
 * different headers just for the test.
 */

import { expect, test } from '@playwright/test'

test('blocking UI renders when an OPFS precondition is missing', async ({ page }) => {
  // Spoof ``window.crossOriginIsolated`` to ``false`` for every
  // navigation in this page context, AND null out
  // ``navigator.storage`` so the very first precondition (OPFS) trips.
  // We don't need to drive the probe into one specific branch — the
  // acceptance criterion is that the blocking UI renders for an
  // unsupported environment AND names BOTH the failed precondition
  // and the supported browsers (issue #140).
  //
  // We pick the OPFS branch by deleting ``navigator.storage`` because
  // it's the cheapest to override and works identically across
  // browsers — the other two require runtime introspection of the
  // page context.
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'storage', {
      configurable: true,
      get: () => undefined,
    })
    Object.defineProperty(window, 'crossOriginIsolated', {
      configurable: true,
      get: () => false,
    })
  })

  await page.goto('/')

  // Layout redirects to ``/unsupported?missing=...``. The exact reason
  // depends on which check trips first; we assert on the URL path and
  // the rendered content rather than pinning a specific ``missing=``.
  await page.waitForURL(/\/unsupported\?missing=/, { timeout: 10_000 })

  // The failed precondition is named.
  await expect(page.getByTestId('missing-precondition')).toBeVisible()

  // Supported browsers are listed (acceptance criterion).
  await expect(page.getByText('Chrome / Edge 109 or later')).toBeVisible()
  await expect(page.getByText('Safari 17 or later')).toBeVisible()
  await expect(page.getByText('Firefox is best-effort')).toBeVisible()
})

test('direct visit to /unsupported with missing=opfs names the OPFS precondition', async ({
  page,
}) => {
  await page.goto('/unsupported?missing=opfs')

  await expect(page.getByTestId('missing-precondition')).toContainText(
    'Origin Private File System',
  )
  await expect(page.getByText('Chrome / Edge 109 or later')).toBeVisible()
})

test('direct visit to /unsupported with missing=sync_handle names the sync-handle precondition', async ({
  page,
}) => {
  await page.goto('/unsupported?missing=sync_handle')

  await expect(page.getByTestId('missing-precondition')).toContainText(
    'synchronous access handles',
  )
})
