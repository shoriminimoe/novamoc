/**
 * Full-lifecycle browser e2e for an ``asset_type_field`` through the
 * M4.6 master-detail UI. Drives every accepted verb the new UI exposes
 * — create, edit (rename + change data type), deactivate (archive),
 * activate (restore), delete — plus a duplicate-name attempt to
 * exercise the inline ``name_reserved`` rendering path. ``clear`` is
 * still in the wire layer (``commands.ts``) but the M4.6 redesign
 * doesn't surface it; rewriting that affordance is a separate concern.
 *
 * The asset-type lifecycle spec runs first under the same in-memory
 * server and leaves zero types, but ``schema_version`` (the
 * ``v<N> · synced`` footer) persists across specs because
 * ``schema_change_log.seq`` tracks ``MAX(seq)``, not current state. So
 * this spec asserts version-advance via *positive* assertions only
 * (existence after each action), not absolute numbers.
 */

import { expect, test, type Locator } from '@playwright/test'

const PARENT = 'field-host'
const FIELD = 'serial_number'
const FIELD_RENAMED = `${FIELD}_v2`

// Skipped pending issue #81 (M4.6 e2e rewrite): the SPA now sits behind
// session-cookie auth (ADR-020), so reaching ``/`` requires a logged-in
// session that this spec doesn't establish. Unskip after #81 lands the
// login-aware test harness.
test.skip('asset_type_field lifecycle through the master-detail UI', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'novaMOC' })).toBeVisible()

  // -- Seed: create a parent asset type so the fields table has a host.
  await page.getByRole('button', { name: '+ New ▾' }).click()
  await page.getByRole('menuitem', { name: 'Asset type' }).click()
  await page.getByRole('textbox', { name: 'New type name' }).fill(PARENT)
  await page.getByRole('textbox', { name: 'New type name' }).press('Enter')
  await expect(page.getByRole('heading', { name: PARENT })).toBeVisible()

  // -- create field — open + Add field, fill name, pick Type via the
  //    combobox (typing "te" + Enter picks "text"), Save.
  await page.getByRole('button', { name: '+ Add field' }).click()
  await page.getByLabel('Name', { exact: true }).fill(FIELD)
  const typeCombo: Locator = page.getByRole('combobox', { name: 'Field data type' })
  await typeCombo.fill('te')
  await typeCombo.press('Enter')
  await expect(typeCombo).toHaveValue('text')
  await page.getByRole('button', { name: 'Save' }).click()

  const fieldRow: Locator = page.getByRole('row', { name: new RegExp(`^${FIELD}\\s+text\\s+Active`) })
  await expect(fieldRow).toBeVisible()

  // -- duplicate field name → inline name_reserved error
  await page.getByRole('button', { name: '+ Add field' }).click()
  await page.getByLabel('Name', { exact: true }).fill(FIELD)
  await typeCombo.fill('text')
  await typeCombo.press('Enter')
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByText('Name is already in use on this type.')).toBeVisible()
  await page.getByRole('button', { name: 'Cancel' }).click()

  // -- edit field (rename + leave type at text) via ⋯ → Edit
  await fieldRow.getByRole('button', { name: `Field actions for ${FIELD}` }).click()
  await page.getByRole('menuitem', { name: 'Edit' }).click()
  await page.getByLabel('Name', { exact: true }).fill(FIELD_RENAMED)
  await page.getByRole('button', { name: 'Save' }).click()
  const renamedRow: Locator = page.getByRole('row', { name: new RegExp(`^${FIELD_RENAMED}\\s+text\\s+Active`) })
  await expect(renamedRow).toBeVisible()

  // -- archive field via ⋯ → Archive… → inline confirm bar (sub-row)
  await renamedRow.getByRole('button', { name: `Field actions for ${FIELD_RENAMED}` }).click()
  await page.getByRole('menuitem', { name: 'Archive…' }).click()
  await expect(page.getByText(`Archive ${FIELD_RENAMED}?`)).toBeVisible()
  await page
    .getByRole('alertdialog', { name: `Archive ${FIELD_RENAMED}?` })
    .getByRole('button', { name: 'Archive' })
    .click()
  // Hidden by default — row drops out of the fields table.
  await expect(page.getByRole('row', { name: new RegExp(`^${FIELD_RENAMED}`) })).toHaveCount(0)

  // -- show archived → field reappears, status Archived
  await page.getByRole('checkbox', { name: 'Show archived' }).check()
  const archivedRow: Locator = page.getByRole('row', { name: new RegExp(`^${FIELD_RENAMED}\\s+text\\s+Archived`) })
  await expect(archivedRow).toBeVisible()

  // -- restore via ⋯ → Restore…
  await archivedRow.getByRole('button', { name: `Field actions for ${FIELD_RENAMED}` }).click()
  await page.getByRole('menuitem', { name: 'Restore…' }).click()
  await expect(page.getByText(`Restore ${FIELD_RENAMED}?`)).toBeVisible()
  await page
    .getByRole('alertdialog', { name: `Restore ${FIELD_RENAMED}?` })
    .getByRole('button', { name: 'Restore' })
    .click()
  await expect(
    page.getByRole('row', { name: new RegExp(`^${FIELD_RENAMED}\\s+text\\s+Active`) }),
  ).toBeVisible()

  // -- delete field via ⋯ → Delete… → modal + typed name confirm
  await page.getByRole('checkbox', { name: 'Show archived' }).uncheck()
  const liveRow: Locator = page.getByRole('row', { name: new RegExp(`^${FIELD_RENAMED}\\s+text\\s+Active`) })
  await liveRow.getByRole('button', { name: `Field actions for ${FIELD_RENAMED}` }).click()
  await page.getByRole('menuitem', { name: 'Delete…' }).click()
  const dialog = page.getByRole('dialog', { name: new RegExp(`Delete ${FIELD_RENAMED}?`) })
  await expect(dialog).toBeVisible()
  const deleteForever = dialog.getByRole('button', { name: 'Delete forever' })
  await expect(deleteForever).toBeDisabled()
  await dialog.getByRole('textbox').fill(FIELD_RENAMED)
  await expect(deleteForever).toBeEnabled()
  await deleteForever.click()
  await expect(page.getByRole('row', { name: new RegExp(`^${FIELD_RENAMED}`) })).toHaveCount(0)

  // -- teardown: delete the parent asset type
  await page.getByRole('button', { name: 'Delete…' }).click()
  const typeDialog = page.getByRole('dialog', { name: new RegExp(`Delete ${PARENT}?`) })
  await typeDialog.getByRole('textbox').fill(PARENT)
  await typeDialog.getByRole('button', { name: 'Delete forever' }).click()
  await expect(page.getByText('Pick a type on the left')).toBeVisible()
})
