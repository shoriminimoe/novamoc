/**
 * Full-lifecycle browser e2e for a ``maintenance_record_type`` and a
 * nested ``maintenance_record_type_field`` through the M4.5 schema
 * browser UI. Drives every accepted verb on both entities — the five
 * type-level verbs (create / activate / update / deactivate / delete)
 * and the six field-level verbs (the five type-level verbs plus
 * ``clear``). Schema commands here exercise the
 * ``maintenance-record-types`` column of the browser, which shares the
 * same generic ``TypeCreateForm`` / ``TypeActions`` / ``FieldCreateForm``
 * / ``FieldActions`` components as the asset-types column with a
 * different ``kind`` prop.
 *
 * Like the M4.4 spec this one is order-tolerant: ``schema_version``
 * counts up across the test run and isn't asserted directly. Specs
 * earlier in alphabetical order (``asset-type-lifecycle``,
 * ``field-lifecycle``) clean up after themselves so the maintenance
 * record column starts empty here.
 */

import { expect, test, type Locator } from '@playwright/test'

const TYPE = 'mr-lifecycle-fixture'
const TYPE_RENAMED = `${TYPE}-renamed`
const FIELD = 'completed_at'
const FIELD_RENAMED = `${FIELD}_v2`

test('maintenance_record_type and field lifecycle through the schema browser UI', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'novaMOC' })).toBeVisible()

  // -- create type
  await page
    .getByRole('button', { name: '+ New maintenance record type' })
    .click()
  await page.getByRole('textbox', { name: 'Name' }).fill(TYPE)
  await page.getByRole('button', { name: 'Create', exact: true }).click()

  const typeCard: Locator = page
    .locator('article')
    .filter({ hasText: TYPE })
  await expect(typeCard).toBeVisible()

  // -- duplicate name → inline name_reserved
  await page
    .getByRole('button', { name: '+ New maintenance record type' })
    .click()
  await page.getByRole('textbox', { name: 'Name' }).fill(TYPE)
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.getByText(/409 · name_reserved/)).toBeVisible()
  await page.getByRole('button', { name: 'Cancel' }).click()

  // The type-level action row is a sibling of the article — wrap both
  // together so we can scope rename / delete buttons that share the
  // accessible name with field-level ones.
  const typeBlock: Locator = page
    .locator('div')
    .filter({
      has: page.locator('article').filter({ hasText: TYPE }),
    })
    .first()

  // -- rename type
  await typeBlock.getByRole('button', { name: 'Rename' }).click()
  await typeBlock.getByRole('textbox', { name: 'New name' }).fill(TYPE_RENAMED)
  await typeBlock.getByRole('button', { name: 'Save' }).click()
  await expect(
    page.locator('article').filter({ hasText: TYPE_RENAMED }),
  ).toBeVisible()

  // Reload the block locator after rename — text matching now keys off
  // TYPE_RENAMED.
  const renamedBlock: Locator = page
    .locator('div')
    .filter({
      has: page.locator('article').filter({ hasText: TYPE_RENAMED }),
    })
    .first()

  // -- create field on the renamed type
  await page
    .getByRole('button', { name: '+ New maintenance-record-type field' })
    .click()
  await page.getByRole('textbox', { name: 'Name' }).fill(FIELD)
  await page.getByRole('combobox', { name: 'Data type' }).selectOption('datetime')
  await page.getByRole('button', { name: 'Create', exact: true }).click()

  const fieldRow: Locator = page
    .getByRole('listitem')
    .filter({ hasText: FIELD })
  await expect(fieldRow).toBeVisible()
  await expect(fieldRow.getByText('datetime', { exact: true })).toBeVisible()

  // -- rename field
  await fieldRow.getByRole('button', { name: 'Rename' }).click()
  await fieldRow.getByRole('textbox', { name: 'New name' }).fill(FIELD_RENAMED)
  await fieldRow.getByRole('button', { name: 'Save' }).click()
  const renamedFieldRow: Locator = page
    .getByRole('listitem')
    .filter({ hasText: FIELD_RENAMED })
  await expect(renamedFieldRow).toBeVisible()

  // -- deactivate field
  await renamedFieldRow.getByRole('button', { name: 'Deactivate' }).click()
  await expect(
    page.getByRole('listitem').filter({ hasText: FIELD_RENAMED }),
  ).toHaveCount(0)

  // -- show tombstoned → field reappears, activate
  await page.getByRole('checkbox', { name: 'Show tombstoned' }).check()
  const tombstonedFieldRow: Locator = page
    .getByRole('listitem')
    .filter({ hasText: FIELD_RENAMED })
  await expect(tombstonedFieldRow).toBeVisible()
  await tombstonedFieldRow.getByRole('button', { name: 'Activate' }).click()
  await expect(tombstonedFieldRow.getByRole('button', { name: 'Deactivate' })).toBeVisible()

  // -- clear field (one-step confirm)
  await tombstonedFieldRow.getByRole('button', { name: 'Clear' }).click()
  await expect(
    page.getByText(`Clear values for ${FIELD_RENAMED}?`),
  ).toBeVisible()
  await tombstonedFieldRow
    .getByRole('button', { name: 'Clear', exact: true })
    .click()
  await expect(tombstonedFieldRow.getByRole('button', { name: 'Rename' })).toBeVisible()

  // -- delete field (two-step confirm)
  await tombstonedFieldRow.getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByText(`Delete field ${FIELD_RENAMED}?`)).toBeVisible()
  await tombstonedFieldRow.getByRole('button', { name: 'Delete' }).click()
  await expect(
    page.getByRole('listitem').filter({ hasText: FIELD_RENAMED }),
  ).toHaveCount(0)

  // -- deactivate type
  await page.getByRole('checkbox', { name: 'Show tombstoned' }).uncheck()
  await renamedBlock.getByRole('button', { name: 'Deactivate' }).click()
  await expect(
    page.locator('article').filter({ hasText: TYPE_RENAMED }),
  ).toHaveCount(0)

  // -- show tombstoned → activate type
  await page.getByRole('checkbox', { name: 'Show tombstoned' }).check()
  const tombstonedTypeCard: Locator = page
    .locator('article')
    .filter({ hasText: TYPE_RENAMED })
  await expect(tombstonedTypeCard).toBeVisible()
  // Re-anchor the block locator now that the card is visible again.
  const tombstonedBlock: Locator = page
    .locator('div')
    .filter({
      has: page.locator('article').filter({ hasText: TYPE_RENAMED }),
    })
    .first()
  await tombstonedBlock.getByRole('button', { name: 'Activate' }).click()
  await expect(tombstonedBlock.getByRole('button', { name: 'Deactivate' })).toBeVisible()

  // -- delete type (two-step confirm)
  await tombstonedBlock.getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByText(`Delete ${TYPE_RENAMED}?`)).toBeVisible()
  await tombstonedBlock.getByRole('button', { name: 'Delete' }).click()
  await expect(
    page.locator('article').filter({ hasText: TYPE_RENAMED }),
  ).toHaveCount(0)
})
