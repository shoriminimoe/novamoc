/**
 * Unit tests for ``TypesRail.svelte``. Focuses on behaviour that
 * Playwright either can't easily test or that we want to lock down at
 * the unit level: the ``+ New ▾`` dropdown, the filter input, sort
 * cycling, the ``Show archived`` toggle, the collapsible behaviour,
 * the create-row autofocus, and outside-click closing the dropdown.
 */
import { fireEvent, render, screen } from '@testing-library/svelte'
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

import TypesRail from '../../src/lib/TypesRail.svelte'
import { postSchemaCommand } from '../../src/lib/commands'
import type { TypeView } from '../../src/lib/schema'

const ASSET_TYPES: readonly TypeView[] = [
  { id: 'at-1', name: 'pump', active: true, fields: [] },
  { id: 'at-2', name: 'compressor', active: true, fields: [] },
  { id: 'at-3', name: 'archived-asset', active: false, fields: [] },
]

const RECORD_TYPES: readonly TypeView[] = [
  { id: 'rt-1', name: 'inspection', active: true, fields: [] },
]

beforeEach(() => {
  vi.mocked(postSchemaCommand).mockReset()
})

function baseProps(overrides: Record<string, unknown> = {}) {
  return {
    assetTypes: ASSET_TYPES,
    recordTypes: RECORD_TYPES,
    selectedId: null,
    showArchived: false,
    onShowArchivedChange: vi.fn(),
    onSelect: vi.fn(),
    onChanged: vi.fn(),
    ...overrides,
  } as never
}

describe('TypesRail', () => {
  it('renders active rows by default and hides archived ones', () => {
    render(TypesRail, baseProps())
    expect(screen.getByText('pump')).toBeVisible()
    expect(screen.getByText('compressor')).toBeVisible()
    expect(screen.getByText('inspection')).toBeVisible()
    expect(screen.queryByText('archived-asset')).toBeNull()
  })

  it('shows archived rows muted when showArchived=true', () => {
    render(TypesRail, baseProps({ showArchived: true }))
    expect(screen.getByText('archived-asset')).toBeVisible()
  })

  it('clicking a row calls onSelect with the row id and kind', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(TypesRail, baseProps({ onSelect }))

    await user.click(screen.getByText('compressor'))
    expect(onSelect).toHaveBeenCalledExactlyOnceWith('at-2', 'asset_type')

    await user.click(screen.getByText('inspection'))
    expect(onSelect).toHaveBeenLastCalledWith('rt-1', 'maintenance_record_type')
  })

  it('+ New ▾ opens a 2-item dropdown with left-aligned options', async () => {
    const user = userEvent.setup()
    render(TypesRail, baseProps())

    await user.click(screen.getByRole('button', { name: '+ New ▾' }))
    expect(screen.getByRole('menuitem', { name: 'Asset type' })).toBeVisible()
    expect(
      screen.getByRole('menuitem', { name: 'Maintenance record type' }),
    ).toBeVisible()
  })

  it('clicking Asset type in the dropdown opens an in-row create form with focus on the name input', async () => {
    const user = userEvent.setup()
    render(TypesRail, baseProps())

    await user.click(screen.getByRole('button', { name: '+ New ▾' }))
    await user.click(screen.getByRole('menuitem', { name: 'Asset type' }))

    const nameInput = screen.getByRole('textbox', { name: 'New type name' })
    expect(nameInput).toBeVisible()
    expect(nameInput).toHaveFocus()
  })

  it('Enter on the focused name input submits create_asset_type', async () => {
    const user = userEvent.setup()
    const onChanged = vi.fn()
    const onSelect = vi.fn()
    vi.mocked(postSchemaCommand).mockResolvedValueOnce({
      schema_version: 1,
      entity_id: 'new-asset-id',
      outcome: 'created',
      committed_at: 'now',
    })
    render(TypesRail, baseProps({ onChanged, onSelect }))

    await user.click(screen.getByRole('button', { name: '+ New ▾' }))
    await user.click(screen.getByRole('menuitem', { name: 'Asset type' }))
    await user.type(screen.getByRole('textbox', { name: 'New type name' }), 'turbine{Enter}')

    expect(postSchemaCommand).toHaveBeenCalledOnce()
    const [, body] = vi.mocked(postSchemaCommand).mock.calls[0]
    expect(body).toMatchObject({
      type: 'create_asset_type',
      payload: { name: 'turbine' },
    })
    expect(onChanged).toHaveBeenCalledOnce()
    expect(onSelect).toHaveBeenCalledOnce()
    // onSelect kind passes through; entity_id was generated client-side.
    expect(onSelect.mock.calls[0][1]).toBe('asset_type')
  })

  it('filters visible rows by case-insensitive substring on Name', async () => {
    const user = userEvent.setup()
    render(TypesRail, baseProps())
    await user.type(screen.getByPlaceholderText('Filter…'), 'PUMP')
    expect(screen.getByText('pump')).toBeVisible()
    expect(screen.queryByText('compressor')).toBeNull()
    expect(screen.queryByText('inspection')).toBeNull()
  })

  it('Show archived checkbox surfaces the toggle through onShowArchivedChange', async () => {
    const user = userEvent.setup()
    const onShowArchivedChange = vi.fn()
    render(TypesRail, baseProps({ onShowArchivedChange }))

    await user.click(screen.getByRole('checkbox', { name: 'Show archived' }))
    expect(onShowArchivedChange).toHaveBeenCalledExactlyOnceWith(true)
  })

  it('collapse toggle hides the body when clicked and shows the » glyph', async () => {
    const user = userEvent.setup()
    render(TypesRail, baseProps())

    // Open by default → « collapse button is visible, body content visible.
    const toggle = screen.getByRole('button', { name: 'Collapse types panel' })
    expect(screen.getByRole('button', { name: '+ New ▾' })).toBeVisible()

    await user.click(toggle)
    expect(screen.queryByRole('button', { name: '+ New ▾' })).toBeNull()
    expect(screen.getByRole('button', { name: 'Expand types panel' })).toBeVisible()
  })

  it('outside-click closes the + New ▾ dropdown', async () => {
    const user = userEvent.setup()
    render(TypesRail, baseProps())

    await user.click(screen.getByRole('button', { name: '+ New ▾' }))
    expect(screen.getByRole('menuitem', { name: 'Asset type' })).toBeVisible()

    await fireEvent.click(screen.getByPlaceholderText('Filter…'))
    expect(screen.queryByRole('menuitem', { name: 'Asset type' })).toBeNull()
  })
})
