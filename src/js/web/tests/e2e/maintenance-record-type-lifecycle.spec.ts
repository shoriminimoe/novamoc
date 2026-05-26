/**
 * Full-lifecycle browser e2e for a ``maintenance_record_type`` and a
 * nested ``maintenance_record_type_field`` through the M4.6
 * master-detail UI. Drives every accepted verb on both entities the
 * new UI exposes (type: create / activate / update / deactivate /
 * delete; field: create / activate / update / deactivate / delete —
 * ``clear`` is wire-only in M4.6, not surfaced in the UI).
 *
 * Schema commands here exercise the ``Maintenance record type`` path
 * through the unified ``+ New ▾`` rail dropdown, which selects the
 * ``maintenance_record_type`` kind rather than the asset-type kind.
 *
 * Spec order is alphabetical; this spec runs after asset-type and
 * field, both of which clean up after themselves. Like those, this
 * spec is version-counter-tolerant: ``schema_version`` accumulates
 * across the run and isn't asserted directly.
 */

import { expect, test, type Locator } from '@playwright/test'

const TYPE = 'mr-lifecycle-fixture'
const TYPE_RENAMED = `${TYPE}-renamed`
const FIELD = 'completed_at'
const FIELD_RENAMED = `${FIELD}_v2`

// Skipped pending issue #81 (M4.6 e2e rewrite): the SPA now sits behind
// session-cookie auth (ADR-020), so reaching ``/`` requires a logged-in
// session that this spec doesn't establish. Unskip after #81 lands the
// login-aware test harness.
test.skip('maintenance_record_type and field lifecycle through the master-detail UI', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'novaMOC' })).toBeVisible()

  // -- create maintenance record type
  await page.getByRole('button', { name: '+ New ▾' }).click()
  await page.getByRole('menuitem', { name: 'Maintenance record type' }).click()
  await page.getByRole('textbox', { name: 'New type name' }).fill(TYPE)
  await page.getByRole('textbox', { name: 'New type name' }).press('Enter')

  await expect(page.getByRole('heading', { name: TYPE })).toBeVisible()
  await expect(page.getByText('maintenance record type', { exact: false })).toBeVisible()

  // -- duplicate name → inline name_reserved
  await page.getByRole('button', { name: '+ New ▾' }).click()
  await page.getByRole('menuitem', { name: 'Maintenance record type' }).click()
  await page.getByRole('textbox', { name: 'New type name' }).fill(TYPE)
  await page.getByRole('textbox', { name: 'New type name' }).press('Enter')
  await expect(page.getByText('Name is already in use.')).toBeVisible()
  await page.getByRole('button', { name: 'Cancel' }).click()

  // -- rename type via the action row
  await page.getByRole('button', { name: 'Rename', exact: true }).click()
  await page.getByRole('textbox', { name: 'Rename' }).fill(TYPE_RENAMED)
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('heading', { name: TYPE_RENAMED })).toBeVisible()

  // -- create a datetime field on the renamed type
  await page.getByRole('button', { name: '+ Add field' }).click()
  await page.getByLabel('Name', { exact: true }).fill(FIELD)
  const typeCombo: Locator = page.getByRole('combobox', { name: 'Field data type' })
  await typeCombo.fill('datet')
  await typeCombo.press('Enter')
  await expect(typeCombo).toHaveValue('datetime')
  await page.getByRole('button', { name: 'Save' }).click()

  const fieldRow: Locator = page.getByRole('row', { name: new RegExp(`^${FIELD}\\s+datetime\\s+Active`) })
  await expect(fieldRow).toBeVisible()

  // -- rename field via ⋯ → Edit
  await fieldRow.getByRole('button', { name: `Field actions for ${FIELD}` }).click()
  await page.getByRole('menuitem', { name: 'Edit' }).click()
  await page.getByLabel('Name', { exact: true }).fill(FIELD_RENAMED)
  await page.getByRole('button', { name: 'Save' }).click()
  const renamedFieldRow: Locator = page
    .getByRole('row', { name: new RegExp(`^${FIELD_RENAMED}\\s+datetime\\s+Active`) })
  await expect(renamedFieldRow).toBeVisible()

  // -- archive field via ⋯ → Archive…
  await renamedFieldRow.getByRole('button', { name: `Field actions for ${FIELD_RENAMED}` }).click()
  await page.getByRole('menuitem', { name: 'Archive…' }).click()
  await page
    .getByRole('alertdialog', { name: `Archive ${FIELD_RENAMED}?` })
    .getByRole('button', { name: 'Archive' })
    .click()
  await expect(page.getByRole('row', { name: new RegExp(`^${FIELD_RENAMED}`) })).toHaveCount(0)

  // -- show archived → field reappears, restore
  await page.getByRole('checkbox', { name: 'Show archived' }).check()
  const archivedFieldRow: Locator = page
    .getByRole('row', { name: new RegExp(`^${FIELD_RENAMED}\\s+datetime\\s+Archived`) })
  await expect(archivedFieldRow).toBeVisible()
  await archivedFieldRow.getByRole('button', { name: `Field actions for ${FIELD_RENAMED}` }).click()
  await page.getByRole('menuitem', { name: 'Restore…' }).click()
  await page
    .getByRole('alertdialog', { name: `Restore ${FIELD_RENAMED}?` })
    .getByRole('button', { name: 'Restore' })
    .click()
  await expect(
    page.getByRole('row', { name: new RegExp(`^${FIELD_RENAMED}\\s+datetime\\s+Active`) }),
  ).toBeVisible()

  // -- delete field
  await page.getByRole('checkbox', { name: 'Show archived' }).uncheck()
  const liveFieldRow: Locator = page
    .getByRole('row', { name: new RegExp(`^${FIELD_RENAMED}\\s+datetime\\s+Active`) })
  await liveFieldRow.getByRole('button', { name: `Field actions for ${FIELD_RENAMED}` }).click()
  await page.getByRole('menuitem', { name: 'Delete…' }).click()
  const fieldDialog = page.getByRole('dialog', { name: new RegExp(`Delete ${FIELD_RENAMED}?`) })
  await fieldDialog.getByRole('textbox').fill(FIELD_RENAMED)
  await fieldDialog.getByRole('button', { name: 'Delete forever' }).click()
  await expect(page.getByRole('row', { name: new RegExp(`^${FIELD_RENAMED}`) })).toHaveCount(0)

  // -- archive the type. Rail row drops (Show archived off) but the
  //    selection sticks; Restore… replaces Archive… on the action row.
  await page.getByRole('button', { name: 'Archive…' }).click()
  await page
    .getByRole('alertdialog', { name: `Archive ${TYPE_RENAMED}?` })
    .getByRole('button', { name: 'Archive' })
    .click()
  await expect(page.getByRole('row', { name: new RegExp(`^R\\s+${TYPE_RENAMED}`) })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Restore…' })).toBeVisible()

  // -- restore the type
  await page.getByRole('button', { name: 'Restore…' }).click()
  await page
    .getByRole('alertdialog', { name: `Restore ${TYPE_RENAMED}?` })
    .getByRole('button', { name: 'Restore' })
    .click()
  await expect(page.getByRole('button', { name: 'Archive…' })).toBeVisible()

  // -- delete the type
  await page.getByRole('button', { name: 'Delete…' }).click()
  const typeDialog = page.getByRole('dialog', { name: new RegExp(`Delete ${TYPE_RENAMED}?`) })
  await typeDialog.getByRole('textbox').fill(TYPE_RENAMED)
  await typeDialog.getByRole('button', { name: 'Delete forever' }).click()
  await expect(page.getByRole('row', { name: new RegExp(`^R\\s+${TYPE_RENAMED}`) })).toHaveCount(0)
})
