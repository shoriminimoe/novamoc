/**
 * Full-lifecycle browser e2e for an ``asset_type`` through the M4.6
 * master-detail schema management UI. Drives every accepted verb —
 * create, rename, deactivate (archive), activate (restore), delete —
 * plus a duplicate-name attempt to exercise the inline
 * ``name_reserved`` rendering path.
 *
 * Effects are asserted through observable UI surface: row presence /
 * absence in the rail, the right-pane title block, the
 * ``v<N> · synced`` footer (replaces the M4.3 ``version N`` header),
 * and the action-row button transitions. ``schema_version`` advances
 * by one on every accepted command and does NOT advance on the
 * duplicate-name 409, so the version stays at 1 after the failed
 * second create and reaches 5 after delete.
 */

import { expect, test } from '@playwright/test'

const NAME = 'lifecycle-fixture'
const RENAMED = `${NAME}-renamed`

// Skipped pending issue #81 (M4.6 e2e rewrite): the SPA now sits behind
// session-cookie auth (ADR-020), so reaching ``/`` requires a logged-in
// session that this spec doesn't establish. Unskip after #81 lands the
// login-aware test harness.
test.skip('asset type lifecycle through the master-detail UI', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'novaMOC' })).toBeVisible()

  // Fresh in-memory DB → empty rail.
  await expect(page.getByText('No types yet')).toBeVisible()

  // -- create
  await page.getByRole('button', { name: '+ New ▾' }).click()
  await page.getByRole('menuitem', { name: 'Asset type' }).click()
  // Autofocus drops the cursor in the name input — type and Enter.
  await page.getByRole('textbox', { name: 'New type name' }).fill(NAME)
  await page.getByRole('textbox', { name: 'New type name' }).press('Enter')

  // Selected row + right pane lights up.
  await expect(page.getByRole('row', { name: new RegExp(`^A\\s+${NAME}$`) })).toBeVisible()
  await expect(page.getByRole('heading', { name: NAME })).toBeVisible()
  await expect(page.getByText('v1 · synced')).toBeVisible()

  // -- duplicate name → inline name_reserved, version stays at 1
  await page.getByRole('button', { name: '+ New ▾' }).click()
  await page.getByRole('menuitem', { name: 'Asset type' }).click()
  await page.getByRole('textbox', { name: 'New type name' }).fill(NAME)
  await page.getByRole('textbox', { name: 'New type name' }).press('Enter')
  await expect(page.getByText('Name is already in use.')).toBeVisible()
  await expect(page.getByText('v1 · synced')).toBeVisible()
  await page.getByRole('button', { name: 'Cancel' }).click()

  // -- rename via the action row
  await page.getByRole('button', { name: 'Rename', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Save' })).toBeDisabled()
  await page.getByRole('textbox', { name: 'Rename' }).fill(RENAMED)
  await page.getByRole('button', { name: 'Save' }).click()

  await expect(page.getByText('v2 · synced')).toBeVisible()
  await expect(page.getByRole('heading', { name: RENAMED })).toBeVisible()
  await expect(page.getByRole('row', { name: new RegExp(`^A\\s+${RENAMED}$`) })).toBeVisible()

  // -- archive (confirm bar appears next to the action row)
  await page.getByRole('button', { name: 'Archive…' }).click()
  await expect(page.getByText(`Archive ${RENAMED}?`)).toBeVisible()
  await page
    .getByRole('alertdialog', { name: `Archive ${RENAMED}?` })
    .getByRole('button', { name: 'Archive' })
    .click()

  // Hidden by default — row drops out of the rail. Selection sticks
  // (the type still exists in the snapshot, just archived), so the
  // right pane keeps showing it with Restore… instead of Archive….
  await expect(page.getByText('v3 · synced')).toBeVisible()
  await expect(page.getByRole('row', { name: new RegExp(`^A\\s+${RENAMED}`) })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Restore…' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Archive…' })).toHaveCount(0)

  // -- show archived → row returns muted with an Archived pill
  await page.getByRole('checkbox', { name: 'Show archived' }).check()
  await expect(page.getByRole('row', { name: new RegExp(`^A\\s+${RENAMED}$`) })).toBeVisible()

  // -- restore (resurrection) — Restore is already on the action row.
  await page.getByRole('button', { name: 'Restore…' }).click()
  await expect(page.getByText(`Restore ${RENAMED}?`)).toBeVisible()
  await page
    .getByRole('alertdialog', { name: `Restore ${RENAMED}?` })
    .getByRole('button', { name: 'Restore' })
    .click()

  await expect(page.getByText('v4 · synced')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Archive…' })).toBeVisible()

  // -- delete (modal with typed-name confirmation)
  await page.getByRole('button', { name: 'Delete…' }).click()
  const dialog = page.getByRole('dialog', { name: new RegExp(`Delete ${RENAMED}?`) })
  await expect(dialog).toBeVisible()
  const deleteForever = dialog.getByRole('button', { name: 'Delete forever' })
  await expect(deleteForever).toBeDisabled()
  // Mismatched type → button stays disabled.
  await dialog.getByRole('textbox').fill('something-else')
  await expect(deleteForever).toBeDisabled()
  // Matching type → button enables.
  await dialog.getByRole('textbox').fill(RENAMED)
  await expect(deleteForever).toBeEnabled()
  await deleteForever.click()

  await expect(page.getByText('v5 · synced')).toBeVisible()
  await expect(page.getByRole('row', { name: new RegExp(`^A\\s+${RENAMED}`) })).toHaveCount(0)
  await expect(page.getByText('Pick a type on the left')).toBeVisible()
})
