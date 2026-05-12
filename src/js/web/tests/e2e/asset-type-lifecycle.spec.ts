/**
 * Full-lifecycle browser e2e for an ``asset_type`` through the M4.3
 * schema browser UI. Drives every accepted verb — create, rename,
 * deactivate, activate (resurrection), delete — and a duplicate-name
 * attempt to exercise the inline ``name_reserved`` rendering path.
 *
 * Each verb's effect is asserted through the UI's observable
 * surface: the ``Asset types (N)`` counter, the ``version N`` header
 * stamped from the snapshot's ``schema_version``, and the card /
 * action-button presence transitions. ``schema_version`` advances by
 * one on every accepted command including the duplicate-name 409
 * (NO — it should not advance: handlers append a change-log row only
 * on success; the controller rolls back on raise), so the version
 * stays at 1 after the failed second create and reaches 5 after
 * delete (create, rename, deactivate, activate, delete).
 */

import { expect, test } from '@playwright/test'

const NAME = 'lifecycle-fixture'
const RENAMED = `${NAME}-renamed`

test('asset type lifecycle through the schema browser UI', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'novaMOC' })).toBeVisible()

  // Fresh in-memory DB → zero asset types to start.
  await expect(page.getByText('Asset types (0)')).toBeVisible()

  // -- create
  await page.getByRole('button', { name: '+ New asset type' }).click()
  await page.getByRole('textbox', { name: 'Name' }).fill(NAME)
  await page.getByRole('button', { name: 'Create' }).click()

  await expect(page.getByText('Asset types (1)')).toBeVisible()
  await expect(page.getByText('version 1')).toBeVisible()
  await expect(page.getByRole('heading', { name: NAME })).toBeVisible()

  // -- duplicate name → inline name_reserved, version stays at 1.
  await page.getByRole('button', { name: '+ New asset type' }).click()
  await page.getByRole('textbox', { name: 'Name' }).fill(NAME)
  await page.getByRole('button', { name: 'Create' }).click()

  await expect(page.getByText(/409 · name_reserved/)).toBeVisible()
  await expect(page.getByText('version 1')).toBeVisible()
  await expect(page.getByText('Asset types (1)')).toBeVisible()
  await page.getByRole('button', { name: 'Cancel' }).click()

  // -- rename (Save disabled when unchanged, enabled after edit)
  await page.getByRole('button', { name: 'Rename' }).click()
  await expect(page.getByRole('button', { name: 'Save' })).toBeDisabled()
  await page.getByRole('textbox', { name: 'New name' }).fill(RENAMED)
  await page.getByRole('button', { name: 'Save' }).click()

  await expect(page.getByText('version 2')).toBeVisible()
  await expect(page.getByRole('heading', { name: RENAMED })).toBeVisible()
  await expect(page.getByRole('heading', { name: NAME, exact: true })).toHaveCount(0)

  // -- deactivate (row drops from the active list)
  await page.getByRole('button', { name: 'Deactivate' }).click()

  await expect(page.getByText('version 3')).toBeVisible()
  await expect(page.getByText('Asset types (0)')).toBeVisible()
  await expect(page.getByRole('heading', { name: RENAMED })).toHaveCount(0)

  // -- toggle "Show tombstoned" → row reappears with Activate button
  await page.getByRole('checkbox', { name: 'Show tombstoned' }).check()

  await expect(page.getByText('Asset types (1)')).toBeVisible()
  await expect(page.getByRole('heading', { name: RENAMED })).toBeVisible()
  // "tombstoned" the badge, not "Show tombstoned" the checkbox label.
  await expect(page.getByText('tombstoned', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Activate' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Deactivate' })).toHaveCount(0)

  // -- activate (resurrection)
  await page.getByRole('button', { name: 'Activate' }).click()

  await expect(page.getByText('version 4')).toBeVisible()
  await expect(page.getByText('tombstoned', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Deactivate' })).toBeVisible()

  // -- delete (two-step confirm)
  await page.getByRole('button', { name: 'Delete' }).click()
  await expect(page.getByText(`Delete ${RENAMED}?`)).toBeVisible()
  // The confirm row replaces the action buttons, so the only remaining
  // Delete button is the confirmation one.
  await page.getByRole('button', { name: 'Delete' }).click()

  await expect(page.getByText('version 5')).toBeVisible()
  await expect(page.getByText('Asset types (0)')).toBeVisible()
  await expect(page.getByRole('heading', { name: RENAMED })).toHaveCount(0)
})
