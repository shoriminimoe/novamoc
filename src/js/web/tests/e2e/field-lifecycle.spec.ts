/**
 * Full-lifecycle browser e2e for an ``asset_type_field`` through the
 * M4.4 schema browser UI. Drives every accepted verb — create,
 * rename, deactivate, activate (resurrection), clear, delete — plus a
 * duplicate-name attempt to exercise the inline ``name_reserved``
 * rendering path on the field-level form.
 *
 * The asset-type lifecycle spec runs first under the same in-memory
 * server and leaves zero asset types, but the ``schema_version``
 * counter persists across specs (it tracks ``MAX(seq)`` on
 * ``schema_change_log``, not the current state). This spec therefore
 * does NOT assert absolute version numbers — it relies on positive
 * existence assertions plus the schema browser's reload-on-change
 * pattern.
 *
 * Field-level and type-level action rows share button labels
 * (Rename / Activate / Deactivate / Delete). Field-level actions live
 * inside the field's ``<li>`` element so this spec scopes those
 * selectors through ``page.getByRole('listitem')``; type-level
 * actions hang off the type's ``<article>`` sibling and use the
 * unscoped ``page`` root.
 */

import { expect, test, type Locator } from '@playwright/test'

const PARENT = 'field-host'
const FIELD = 'serial_number'
const FIELD_RENAMED = `${FIELD}_v2`

test('asset_type_field lifecycle through the schema browser UI', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'novaMOC' })).toBeVisible()

  // -- Seed: create the parent asset type so the field form's
  //    parent dropdown has at least one option.
  await page.getByRole('button', { name: '+ New asset type' }).click()
  await page.getByRole('textbox', { name: 'Name' }).fill(PARENT)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.getByRole('heading', { name: PARENT })).toBeVisible()

  // -- create field
  await page.getByRole('button', { name: '+ New asset-type field' }).click()
  await expect(
    page.getByRole('combobox', { name: 'Parent asset type' }),
  ).toHaveValue(/.+/)
  await page.getByRole('textbox', { name: 'Name' }).fill(FIELD)
  await page.getByRole('combobox', { name: 'Data type' }).selectOption('text')
  await page.getByRole('button', { name: 'Create', exact: true }).click()

  // The field appears as a list item under the parent's card; capture it
  // and use it to scope field-level button selectors that share their
  // accessible name with type-level buttons.
  const fieldRow: Locator = page
    .getByRole('listitem')
    .filter({ hasText: FIELD })
  await expect(fieldRow).toBeVisible()
  await expect(fieldRow.getByText('text', { exact: true })).toBeVisible()

  // -- duplicate field name → inline name_reserved
  await page.getByRole('button', { name: '+ New asset-type field' }).click()
  await page.getByRole('textbox', { name: 'Name' }).fill(FIELD)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.getByText(/409 · name_reserved/)).toBeVisible()
  await page.getByRole('button', { name: 'Cancel' }).click()

  // -- rename field
  await fieldRow.getByRole('button', { name: 'Rename' }).click()
  await expect(fieldRow.getByRole('button', { name: 'Save' })).toBeDisabled()
  await fieldRow.getByRole('textbox', { name: 'New name' }).fill(FIELD_RENAMED)
  await fieldRow.getByRole('button', { name: 'Save' }).click()
  const renamedRow: Locator = page
    .getByRole('listitem')
    .filter({ hasText: FIELD_RENAMED })
  await expect(renamedRow).toBeVisible()

  // -- deactivate field (drops from the active list)
  await renamedRow.getByRole('button', { name: 'Deactivate' }).click()
  await expect(
    page.getByRole('listitem').filter({ hasText: FIELD_RENAMED }),
  ).toHaveCount(0)

  // -- show tombstoned → field reappears with Activate button
  await page.getByRole('checkbox', { name: 'Show tombstoned' }).check()
  const tombstonedRow: Locator = page
    .getByRole('listitem')
    .filter({ hasText: FIELD_RENAMED })
  await expect(tombstonedRow).toBeVisible()
  await expect(tombstonedRow.getByRole('button', { name: 'Activate' })).toBeVisible()

  // -- activate (resurrection)
  await tombstonedRow.getByRole('button', { name: 'Activate' }).click()
  await expect(tombstonedRow.getByRole('button', { name: 'Deactivate' })).toBeVisible()

  // -- clear (one-step confirm)
  await tombstonedRow.getByRole('button', { name: 'Clear' }).click()
  await expect(
    page.getByText(`Clear values for ${FIELD_RENAMED}?`),
  ).toBeVisible()
  await tombstonedRow.getByRole('button', { name: 'Clear', exact: true }).click()
  // After clear, the field is still present (clear wipes values, not the
  // definition). The action buttons return.
  await expect(tombstonedRow.getByRole('button', { name: 'Rename' })).toBeVisible()

  // -- delete field (two-step confirm)
  await tombstonedRow.getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByText(`Delete field ${FIELD_RENAMED}?`)).toBeVisible()
  await tombstonedRow.getByRole('button', { name: 'Delete' }).click()
  await expect(
    page.getByRole('listitem').filter({ hasText: FIELD_RENAMED }),
  ).toHaveCount(0)

  // -- teardown: delete the parent asset type (two-step confirm on the
  //    type-level action row).
  await page.getByRole('checkbox', { name: 'Show tombstoned' }).uncheck()
  await page.getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByText(`Delete ${PARENT}?`)).toBeVisible()
  await page.getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByRole('heading', { name: PARENT })).toHaveCount(0)
})
