/**
 * Unit tests for ``TypeDetail.svelte``. Focuses on the empty-state,
 * the action-row affordances toggling between Active and Archived
 * states, the rename in-row form, and the selection-change effect
 * that resets the mode when the user clicks a different type in the
 * rail.
 */
import { render, screen } from '@testing-library/svelte'
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

import TypeDetail from '../../src/lib/TypeDetail.svelte'
import { postSchemaCommand } from '../../src/lib/commands'
import type { TypeView } from '../../src/lib/schema'

const ACTIVE_TYPE: TypeView = {
  id: 't-1',
  name: 'pump',
  active: true,
  fields: [
    { id: 'f-1', name: 'manufacturer', data_type: 'text', validation: null, active: true },
    { id: 'f-2', name: 'model', data_type: 'text', validation: null, active: true },
  ],
}

const ARCHIVED_TYPE: TypeView = {
  id: 't-2',
  name: 'boiler',
  active: false,
  fields: [],
}

beforeEach(() => {
  vi.mocked(postSchemaCommand).mockReset()
})

function baseProps(overrides: Record<string, unknown> = {}) {
  return {
    type: ACTIVE_TYPE,
    kind: 'asset_type' as const,
    showArchived: false,
    onChanged: vi.fn(),
    onDeleted: vi.fn(),
    ...overrides,
  } as never
}

describe('TypeDetail', () => {
  it('renders the empty state when no type is selected', () => {
    render(TypeDetail, baseProps({ type: null, kind: null }))
    expect(screen.getByText('Pick a type on the left')).toBeVisible()
  })

  it('renders the type name, kind label, Active pill, and the three action buttons for an active type', () => {
    render(TypeDetail, baseProps())
    expect(screen.getByRole('heading', { name: 'pump' })).toBeVisible()
    expect(screen.getByText(/asset type/)).toBeVisible()
    // Multiple "Active" pills exist (the type's, plus one per field row).
    // The header's pill is rendered with a smaller font-size; just verify
    // at least one is present.
    expect(screen.getAllByText('Active').length).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Rename' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Archive…' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Delete…' })).toBeVisible()
  })

  it('renders Restore… (not Archive…) on an archived type', () => {
    render(TypeDetail, baseProps({ type: ARCHIVED_TYPE }))
    // Archived type has no fields, so the only "Archived" text is the header pill.
    expect(screen.getByText('Archived')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Restore…' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Archive…' })).toBeNull()
  })

  it('Rename opens an inline form with Save disabled when name is unchanged', async () => {
    const user = userEvent.setup()
    render(TypeDetail, baseProps())

    await user.click(screen.getByRole('button', { name: 'Rename' }))

    const input = screen.getByRole('textbox', { name: 'Rename' })
    expect(input).toHaveValue('pump')
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()

    await user.type(input, '_v2')
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled()
  })

  it('Archive… opens an inline confirm bar with the active-type consequence copy', async () => {
    const user = userEvent.setup()
    render(TypeDetail, baseProps())

    await user.click(screen.getByRole('button', { name: 'Archive…' }))
    const bar = screen.getByRole('alertdialog', { name: 'Archive pump?' })
    expect(bar).toBeVisible()
    expect(bar.textContent).toMatch(/Existing assets and records keep working/)
  })

  it('Delete… opens a DeleteTypeDialog with the correct disclosure including the field count', async () => {
    const user = userEvent.setup()
    render(TypeDetail, baseProps())

    await user.click(screen.getByRole('button', { name: 'Delete…' }))
    const dialog = screen.getByRole('dialog', { name: /Delete pump?/ })
    expect(dialog).toBeVisible()
    expect(dialog.textContent).toMatch(/2 fields defined on pump/)
  })

  it('selection change resets the mode (opening another type cancels an in-progress rename)', async () => {
    const user = userEvent.setup()
    const { rerender } = render(TypeDetail, baseProps())

    await user.click(screen.getByRole('button', { name: 'Rename' }))
    expect(screen.getByRole('textbox', { name: 'Rename' })).toBeVisible()

    // Simulate selecting a different type in the rail.
    await rerender(baseProps({ type: ARCHIVED_TYPE }))
    expect(screen.queryByRole('textbox', { name: 'Rename' })).toBeNull()
    expect(screen.getByRole('heading', { name: 'boiler' })).toBeVisible()
  })
})
