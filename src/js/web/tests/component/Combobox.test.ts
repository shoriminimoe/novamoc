/**
 * Unit tests for ``Combobox.svelte`` — the typeable single-select
 * primitive used by ``FieldsTable``'s data-type picker. Covers the
 * keyboard contract (Arrow / Enter / Esc / Tab), the type-to-filter
 * behaviour, free-text revert on outside-click, and the ARIA wiring
 * that screen readers rely on.
 */
import { render, screen } from '@testing-library/svelte'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import Combobox from '../../src/lib/Combobox.svelte'

const OPTIONS = [
  { value: 'text', preview: 'Aa' },
  { value: 'number', preview: '12.5' },
  { value: 'integer', preview: '42' },
  { value: 'date', preview: '📅' },
  { value: 'datetime', preview: '📅⏰' },
] as const

describe('Combobox', () => {
  it('wires combobox ARIA: role, expanded, controls, activedescendant', async () => {
    const onChange = vi.fn()
    render(Combobox, { value: '', options: OPTIONS, onChange, ariaLabel: 'Type' })

    const input = screen.getByRole('combobox', { name: 'Type' })
    expect(input).toHaveAttribute('aria-expanded', 'false')

    await userEvent.click(input)
    expect(input).toHaveAttribute('aria-expanded', 'true')

    const listId = input.getAttribute('aria-controls')
    expect(listId).toMatch(/^combobox-list-/)
    expect(document.getElementById(listId!)).toBeInTheDocument()
    // First option is highlighted on open; activedescendant points at it.
    expect(input.getAttribute('aria-activedescendant')).toBe(`${listId}-0`)
  })

  it('filters options by case-insensitive substring as the user types', async () => {
    const user = userEvent.setup()
    render(Combobox, { value: '', options: OPTIONS, onChange: vi.fn() })

    const input = screen.getByRole('combobox')
    await user.click(input)
    expect(screen.getAllByRole('option')).toHaveLength(5)

    await user.type(input, 'DA')
    const filtered = screen.getAllByRole('option')
    expect(filtered.map((o) => o.textContent)).toEqual(
      expect.arrayContaining([expect.stringMatching(/date/), expect.stringMatching(/datetime/)]),
    )
    expect(filtered).toHaveLength(2)
  })

  it('commits the highlighted option on Enter and calls onChange', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(Combobox, { value: '', options: OPTIONS, onChange })

    const input = screen.getByRole('combobox')
    await user.click(input)
    await user.type(input, 'da')
    // Two filtered options (date, datetime) — ArrowDown to move to "datetime".
    await user.keyboard('{ArrowDown}')
    await user.keyboard('{Enter}')

    expect(onChange).toHaveBeenCalledExactlyOnceWith('datetime')
    expect(input).toHaveValue('datetime')
    expect(input).toHaveAttribute('aria-expanded', 'false')
  })

  it('reverts free text to the committed value on Escape without calling onChange', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(Combobox, { value: 'text', options: OPTIONS, onChange })

    const input = screen.getByRole('combobox')
    await user.click(input)
    await user.clear(input)
    await user.type(input, 'wat')
    await user.keyboard('{Escape}')

    expect(input).toHaveValue('text')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('reverts free text on outside-click', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(Combobox, { value: 'integer', options: OPTIONS, onChange })

    const input = screen.getByRole('combobox')
    await user.click(input)
    await user.clear(input)
    await user.type(input, 'gibberish')
    // Click outside the combobox's root.
    await user.click(document.body)

    expect(input).toHaveValue('integer')
    expect(onChange).not.toHaveBeenCalled()
  })

  it('commits the highlighted option on mousedown of an option', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(Combobox, { value: '', options: OPTIONS, onChange })

    const input = screen.getByRole('combobox')
    await user.click(input)
    const dateOption = screen
      .getAllByRole('option')
      .find((o) => o.textContent?.includes('date '))!
    // The component uses mousedown (not click) to beat the input blur race.
    await user.pointer({ keys: '[MouseLeft]', target: dateOption })

    expect(onChange).toHaveBeenCalledExactlyOnceWith('date')
  })

  it('respects the disabled prop — input is disabled, no callbacks fire', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(Combobox, { value: '', options: OPTIONS, onChange, disabled: true })

    const input = screen.getByRole('combobox')
    expect(input).toBeDisabled()
    await user.click(input).catch(() => undefined)
    expect(onChange).not.toHaveBeenCalled()
  })
})
