/**
 * Unit tests for ``FieldsTable.svelte``. Playwright covers the
 * full-stack happy paths against a real API; this suite focuses on
 * behaviour the integration tests can't easily exercise:
 *
 * - filter input narrows visible rows
 * - column-header sort cycles asc → desc → none
 * - ``+ Add field`` opens an in-row form with name blank and Type blank
 * - Save stays disabled until name + type are both set
 * - the data-type combobox preview previews match the spec's data types
 * - the form survives a failed submit (regression for the
 *   ``mode = error`` bug that the e2e rewrite caught)
 */
import { fireEvent, render, screen, within } from '@testing-library/svelte'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../src/lib/commands', async () => {
  const actual = await vi.importActual<typeof import('../../src/lib/commands')>(
    '../../src/lib/commands',
  )
  return {
    ...actual,
    postSchemaCommand: vi.fn(),
  }
})

import FieldsTable from '../../src/lib/FieldsTable.svelte'
import { ProblemDetailsError } from '../../src/lib/api'
import { postSchemaCommand } from '../../src/lib/commands'
import type { FieldView } from '../../src/lib/schema'

const FIELDS: readonly FieldView[] = [
  { id: 'f-1', name: 'manufacturer', data_type: 'text', validation: null, active: true },
  { id: 'f-2', name: 'model', data_type: 'text', validation: null, active: true },
  { id: 'f-3', name: 'install_date', data_type: 'date', validation: null, active: true },
  { id: 'f-4', name: 'retired_at', data_type: 'date', validation: null, active: false },
]

beforeEach(() => {
  vi.mocked(postSchemaCommand).mockReset()
})

function baseProps(overrides: Record<string, unknown> = {}) {
  return {
    kind: 'asset_type_field' as const,
    parentTypeId: 'type-1',
    fields: FIELDS,
    showArchived: false,
    onChanged: vi.fn(),
    ...overrides,
  } as never
}

describe('FieldsTable', () => {
  it('hides archived fields by default', () => {
    render(FieldsTable, baseProps())
    expect(screen.getByText('manufacturer')).toBeVisible()
    expect(screen.queryByText('retired_at')).toBeNull()
  })

  it('shows archived fields when showArchived=true with an Archived status pill', () => {
    render(FieldsTable, baseProps({ showArchived: true }))
    const row = screen.getByRole('row', { name: /retired_at\s+date\s+Archived/ })
    expect(row).toBeVisible()
  })

  it('filters visible fields by case-insensitive substring on Name', async () => {
    const user = userEvent.setup()
    render(FieldsTable, baseProps())

    await user.type(screen.getByPlaceholderText('Filter fields…'), 'DATE')
    expect(screen.getByText('install_date')).toBeVisible()
    expect(screen.queryByText('manufacturer')).toBeNull()
    expect(screen.queryByText('model')).toBeNull()
  })

  it('cycles sort direction asc → desc → none on the Name column header', async () => {
    const user = userEvent.setup()
    render(FieldsTable, baseProps())

    const nameHeader = screen.getByRole('columnheader', { name: /^Name/ })

    // Initial state: name asc
    const names = () =>
      screen
        .getAllByRole('row')
        .slice(1) // skip header
        .map((r) => r.firstChild?.textContent?.trim())
        .filter((n): n is string => typeof n === 'string')
    expect(names()).toEqual(['install_date', 'manufacturer', 'model'])

    // Click → desc
    await user.click(nameHeader)
    expect(names()).toEqual(['model', 'manufacturer', 'install_date'])

    // Click → none (snapshot order)
    await user.click(nameHeader)
    expect(names()).toEqual(['manufacturer', 'model', 'install_date'])
  })

  it('opens an in-row form on + Add field with name + type both blank', async () => {
    const user = userEvent.setup()
    render(FieldsTable, baseProps())

    await user.click(screen.getByRole('button', { name: '+ Add field' }))

    const nameInput = screen.getByLabelText('Name', { exact: true })
    const typeCombo = screen.getByRole('combobox', { name: 'Field data type' })

    expect(nameInput).toHaveValue('')
    expect(typeCombo).toHaveValue('')
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('keeps Save disabled until both name and type are filled', async () => {
    const user = userEvent.setup()
    render(FieldsTable, baseProps())

    await user.click(screen.getByRole('button', { name: '+ Add field' }))
    const nameInput = screen.getByLabelText('Name', { exact: true })
    const typeCombo = screen.getByRole('combobox', { name: 'Field data type' })
    const save = screen.getByRole('button', { name: 'Save' })

    await user.type(nameInput, 'serial_number')
    expect(save).toBeDisabled() // type still blank

    await user.type(typeCombo, 'te')
    await user.keyboard('{Enter}')
    expect(typeCombo).toHaveValue('text')
    expect(save).toBeEnabled()
  })

  it('posts create_asset_type_field with parent_id + name + data_type and calls onChanged on success', async () => {
    const user = userEvent.setup()
    const onChanged = vi.fn()
    vi.mocked(postSchemaCommand).mockResolvedValueOnce({
      schema_version: 7,
      entity_id: 'new-id',
      outcome: 'created',
      committed_at: '2026-05-13T00:00:00Z',
    })
    render(FieldsTable, baseProps({ onChanged }))

    await user.click(screen.getByRole('button', { name: '+ Add field' }))
    await user.type(screen.getByLabelText('Name', { exact: true }), 'serial_number')
    const typeCombo = screen.getByRole('combobox', { name: 'Field data type' })
    await user.type(typeCombo, 'text')
    await user.keyboard('{Enter}')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(postSchemaCommand).toHaveBeenCalledOnce()
    const [, body] = vi.mocked(postSchemaCommand).mock.calls[0]
    expect(body).toMatchObject({
      type: 'create_asset_type_field',
      payload: {
        parent_id: 'type-1',
        name: 'serial_number',
        data_type: 'text',
      },
    })
    expect(onChanged).toHaveBeenCalledOnce()
  })

  it('keeps the form open with inline error when create returns name_reserved', async () => {
    const user = userEvent.setup()
    const onChanged = vi.fn()
    vi.mocked(postSchemaCommand).mockRejectedValueOnce(
      new ProblemDetailsError({
        type: 'https://x/name_reserved',
        title: 'Conflict',
        status: 409,
        detail: 'name in use',
        instance: 'urn:abc',
      }),
    )
    render(FieldsTable, baseProps({ onChanged }))

    await user.click(screen.getByRole('button', { name: '+ Add field' }))
    await user.type(screen.getByLabelText('Name', { exact: true }), 'manufacturer')
    const typeCombo = screen.getByRole('combobox', { name: 'Field data type' })
    await user.type(typeCombo, 'text')
    await user.keyboard('{Enter}')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    // Form stays open + inline error renders + onChanged did NOT fire.
    expect(screen.getByLabelText('Name', { exact: true })).toBeVisible()
    expect(screen.getByText('Name is already in use on this type.')).toBeVisible()
    expect(onChanged).not.toHaveBeenCalled()
    // Cancel still works, closing the form and clearing the error.
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByText('Name is already in use on this type.')).toBeNull()
  })

  it('Edit on a row prefills name + type with the row current values', async () => {
    const user = userEvent.setup()
    render(FieldsTable, baseProps())

    // Open the ⋯ menu for "manufacturer" and click Edit
    await user.click(
      screen.getByRole('button', { name: 'Field actions for manufacturer' }),
    )
    await user.click(screen.getByRole('menuitem', { name: 'Edit' }))

    expect(screen.getByLabelText('Name', { exact: true })).toHaveValue('manufacturer')
    expect(screen.getByRole('combobox', { name: 'Field data type' })).toHaveValue('text')
  })

  it('archive flow: ⋯ → Archive… inserts an inline confirm bar under the row', async () => {
    const user = userEvent.setup()
    render(FieldsTable, baseProps())

    await user.click(
      screen.getByRole('button', { name: 'Field actions for manufacturer' }),
    )
    await user.click(screen.getByRole('menuitem', { name: 'Archive…' }))

    const bar = screen.getByRole('alertdialog', { name: 'Archive manufacturer?' })
    expect(bar).toBeVisible()
    expect(within(bar).getByRole('button', { name: 'Archive' })).toBeVisible()
  })

  it('delete flow: ⋯ → Delete… opens the DeleteTypeDialog modal', async () => {
    const user = userEvent.setup()
    render(FieldsTable, baseProps())

    await user.click(
      screen.getByRole('button', { name: 'Field actions for model' }),
    )
    await user.click(screen.getByRole('menuitem', { name: 'Delete…' }))

    const dialog = screen.getByRole('dialog', { name: /Delete model?/ })
    expect(dialog).toBeVisible()
    expect(within(dialog).getByRole('button', { name: 'Delete forever' })).toBeDisabled()
  })

  it('outside-click closes an open ⋯ menu', async () => {
    const user = userEvent.setup()
    render(FieldsTable, baseProps())

    await user.click(
      screen.getByRole('button', { name: 'Field actions for manufacturer' }),
    )
    expect(screen.getByRole('menuitem', { name: 'Edit' })).toBeVisible()

    // Click somewhere outside any data-menu-region — the filter input qualifies.
    await fireEvent.click(screen.getByPlaceholderText('Filter fields…'))
    expect(screen.queryByRole('menuitem', { name: 'Edit' })).toBeNull()
  })
})
