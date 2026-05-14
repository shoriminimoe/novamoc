/**
 * Unit tests for ``ArchiveConfirmBar.svelte``. The component is fully
 * controlled — no internal state, no API calls — so the surface is
 * narrow: it renders the consequence sentence + Cancel/Confirm
 * buttons, the buttons fire the supplied callbacks, the ``disabled``
 * prop disables both, and the ``confirmLabel`` swap toggles the
 * primary button copy (Archive ↔ Restore).
 */
import { render, screen } from '@testing-library/svelte'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import ArchiveConfirmBar from '../../src/lib/ArchiveConfirmBar.svelte'

describe('ArchiveConfirmBar', () => {
  it('renders subject + consequence and wires Cancel / Confirm callbacks', async () => {
    const user = userEvent.setup()
    const onCancel = vi.fn()
    const onConfirm = vi.fn()
    render(ArchiveConfirmBar, {
      subject: 'Pump',
      consequence: 'Existing assets keep working.',
      onCancel,
      onConfirm,
    })

    expect(screen.getByText('Pump')).toBeVisible()
    expect(screen.getByText('Existing assets keep working.')).toBeVisible()
    // The alertdialog wraps the consequence + buttons.
    expect(screen.getByRole('alertdialog', { name: 'Archive Pump?' })).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalledOnce()
    expect(onConfirm).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Archive' }))
    expect(onConfirm).toHaveBeenCalledOnce()
  })

  it('renders the Restore variant when confirmLabel = "Restore"', () => {
    render(ArchiveConfirmBar, {
      subject: 'Pump',
      consequence: 'Restore this so new records can be created.',
      confirmLabel: 'Restore',
      onCancel: vi.fn(),
      onConfirm: vi.fn(),
    })

    expect(screen.getByRole('alertdialog', { name: 'Restore Pump?' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Restore' })).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Archive' })).toBeNull()
  })

  it('disables both buttons when disabled=true and does not fire callbacks', async () => {
    const user = userEvent.setup()
    const onCancel = vi.fn()
    const onConfirm = vi.fn()
    render(ArchiveConfirmBar, {
      subject: 'Pump',
      consequence: 'x',
      disabled: true,
      onCancel,
      onConfirm,
    })

    const cancel = screen.getByRole('button', { name: 'Cancel' })
    const archive = screen.getByRole('button', { name: 'Archive' })
    expect(cancel).toBeDisabled()
    expect(archive).toBeDisabled()
    await user.click(cancel).catch(() => undefined)
    await user.click(archive).catch(() => undefined)
    expect(onCancel).not.toHaveBeenCalled()
    expect(onConfirm).not.toHaveBeenCalled()
  })
})
