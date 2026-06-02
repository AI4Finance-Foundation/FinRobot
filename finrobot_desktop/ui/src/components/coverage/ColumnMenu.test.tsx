import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ColumnMenu } from './ColumnMenu'
import { COVERAGE_COLUMNS } from './columns'

describe('ColumnMenu', () => {
  it('opens on click and lists every column as a checkbox', () => {
    render(<ColumnMenu hiddenColumns={[]} onToggle={() => {}} />)
    expect(screen.queryByRole('menu')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Columns/ }))
    const menu = screen.getByRole('menu')
    expect(menu.querySelectorAll('input[type="checkbox"]')).toHaveLength(COVERAGE_COLUMNS.length)
  })

  it('reflects hidden columns as unchecked and toggles on change', () => {
    const onToggle = vi.fn()
    render(<ColumnMenu hiddenColumns={['pe']} onToggle={onToggle} />)
    fireEvent.click(screen.getByRole('button', { name: /Columns/ }))
    // P/E is hidden → its checkbox is unchecked.
    const pe = screen.getByLabelText('P/E') as HTMLInputElement
    expect(pe.checked).toBe(false)
    fireEvent.click(pe)
    expect(onToggle).toHaveBeenCalledWith('pe')
  })
})
