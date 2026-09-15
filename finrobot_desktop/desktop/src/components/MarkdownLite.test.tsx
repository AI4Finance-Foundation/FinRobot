import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MarkdownLite } from './MarkdownLite'

describe('MarkdownLite', () => {
  it('still renders ### headings and **bold** (regression guard)', () => {
    render(<MarkdownLite text={'### Title\n\nsome **bold** text'} />)
    expect(screen.getByText('Title')).toBeInTheDocument()
    expect(screen.getByText('bold').tagName).toBe('STRONG')
  })

  it('renders a markdown link to an http(s) url as a real external anchor', () => {
    render(<MarkdownLite text={'see [the report](https://example.com/r)'} />)
    const link = screen.getByText('the report')
    expect(link.tagName).toBe('A')
    expect(link).toHaveAttribute('href', 'https://example.com/r')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('renders an internal sandbox:// ref as styled text, never raw [text](url) syntax', () => {
    // sandbox://… is an internal artifact reference, not a navigable URL — it must
    // never render as a dead anchor, and the raw markdown/url must never leak.
    render(<MarkdownLite text={'open the [Equity Research Report](sandbox://art_123) now'} />)
    const label = screen.getByText('Equity Research Report')
    expect(label.tagName).not.toBe('A')
    expect(screen.queryByText(/sandbox:\/\//)).not.toBeInTheDocument()
    expect(screen.queryByText(/\]\(/)).not.toBeInTheDocument()
  })
})
