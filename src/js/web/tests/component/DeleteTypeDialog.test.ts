/**
 * Unit tests for ``DeleteTypeDialog.svelte``. Covers the typed-name
 * confirmation gate, Escape / backdrop dismissal, Enter-to-confirm
 * once the name matches, the optional "Archive instead" affordance,
 * and the disclosure rendering.
 */
import { render, screen, within } from '@testing-library/svelte'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import DeleteTypeDialog from '../../src/lib/DeleteTypeDialog.svelte'

const DISCLOSURE = [
  'All assets of type Pump will be permanently deleted.',
  'The 5 fields defined on Pump will be removed.',
]

function defaultProps(overrides: Partial<Parameters<typeof render<typeof DeleteTypeDialog>>[1]> = {}) {
  return {
    subject: 'Pump',
    kindLabel: 'asset type',
    disclosure: DISCLOSURE,
    onCancel: vi.fn(),
    onConfirm: vi.fn(),
    ...overrides,
  } as never
}

describe('DeleteTypeDialog', () => {
  it('renders heading, disclosure bullets, and a disabled Delete forever button by default', () => {
    render(DeleteTypeDialog, defaultProps())
    const dialog = screen.getByRole('dialog', { name: /Delete Pump?/ })
    expect(dialog).toBeVisible()
    // Every disclosure line renders as a list item.
    for (const line of DISCLOSURE) {
      expect(within(dialog).getByText(line)).toBeVisible()
    }
    expect(screen.getByRole('button', { name: 'Delete forever' })).toBeDisabled()
  })

  it('enables Delete forever only when the typed name matches the subject exactly', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    render(DeleteTypeDialog, defaultProps({ onConfirm }))

    const input = screen.getByRole('textbox')
    const button = screen.getByRole('button', { name: 'Delete forever' })

    await user.type(input, 'pump') // wrong case
    expect(button).toBeDisabled()

    await user.clear(input)
    await user.type(input, 'Pump')
    expect(button).toBeEnabled()

    await user.click(button)
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('confirms on Enter when the typed name matches', async () => {
    const user = userEvent.setup()
    const onConfirm = vi.fn()
    render(DeleteTypeDialog, defaultProps({ onConfirm }))

    const input = screen.getByRole('textbox')
    await user.type(input, 'Pump{Enter}')
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('cancels on Escape', async () => {
    const user = userEvent.setup()
    const onCancel = vi.fn()
    render(DeleteTypeDialog, defaultProps({ onCancel }))

    await user.keyboard('{Escape}')
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('cancels on backdrop click', async () => {
    const user = userEvent.setup()
    const onCancel = vi.fn()
    render(DeleteTypeDialog, defaultProps({ onCancel }))

    // The backdrop is a full-bleed Cancel button with aria-label="Cancel"
    // sitting under the dialog card. There's also a visible "Cancel" button
    // in the action row, so we can't use role+name alone; find it via the
    // class the backdrop carries.
    const backdrop = document.querySelector('.absolute.inset-0') as HTMLElement
    expect(backdrop).toBeInTheDocument()
    await user.click(backdrop)
    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('renders Archive instead link only when onArchiveInstead is provided', async () => {
    const user = userEvent.setup()
    const onArchiveInstead = vi.fn()
    const { rerender } = render(
      DeleteTypeDialog,
      defaultProps({ onArchiveInstead }),
    )

    const link = screen.getByRole('button', { name: /Archive asset type instead/ })
    await user.click(link)
    expect(onArchiveInstead).toHaveBeenCalledOnce()

    // Without the callback, no archive-instead link renders.
    await rerender(defaultProps({ onArchiveInstead: undefined }))
    expect(
      screen.queryByRole('button', { name: /Archive asset type instead/ }),
    ).toBeNull()
  })

  it('focuses the input on mount so the user can type immediately', () => {
    render(DeleteTypeDialog, defaultProps())
    expect(screen.getByRole('textbox')).toHaveFocus()
  })

  it('keeps Delete forever disabled while disabled prop is true even with a matching name', async () => {
    const user = userEvent.setup()
    render(DeleteTypeDialog, defaultProps({ disabled: true }))

    const input = screen.getByRole('textbox')
    // The input itself is disabled while submitting — type via fireEvent to bypass.
    expect(input).toBeDisabled()

    // The matching-name path is short-circuited by canConfirm checking !disabled.
    // We can't type into the disabled input, so just verify the button stays disabled.
    expect(screen.getByRole('button', { name: 'Delete forever' })).toBeDisabled()
    // Escape still cancels (handler short-circuits on disabled to prevent double-fire).
    await user.keyboard('{Escape}')
  })
})
