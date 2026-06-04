import { describe, it, expect, beforeEach, vi } from 'vitest'
import { render, screen, cleanup } from '@testing-library/react'
import { ReportTOC } from '../ReportTOC'
import { allChapterLabels } from '../../chapters/labels'
import { useUiPrefs } from '../../../../i18n'

// jsdom doesn't ship IntersectionObserver; ReportTOC uses it for scroll-spy.
class IO {
  observe() {}
  disconnect() {}
  unobserve() {}
  takeRecords(): IntersectionObserverEntry[] {
    return []
  }
  readonly root = null
  readonly rootMargin = ''
  readonly thresholds: ReadonlyArray<number> = []
}
vi.stubGlobal('IntersectionObserver', IO)

describe('ReportTOC — locale-aware chapter sidebar', () => {
  beforeEach(() => {
    cleanup()
  })

  it('renders 中文 chapter titles when locale=zh', () => {
    useUiPrefs.getState().setLocale('zh')
    render(<ReportTOC entries={allChapterLabels('zh')} />)
    // sidebar header
    expect(screen.getByText('研报章节')).toBeInTheDocument()
    // 13 chapters — sample a few across the spread
    expect(screen.getByText('封面')).toBeInTheDocument()
    expect(screen.getByText('投资论点')).toBeInTheDocument()
    expect(screen.getByText('估值分析')).toBeInTheDocument()
    expect(screen.getByText('竞争格局')).toBeInTheDocument()
    expect(screen.getByText('免责声明')).toBeInTheDocument()
  })

  it('renders English chapter titles when locale=en', () => {
    useUiPrefs.getState().setLocale('en')
    render(<ReportTOC entries={allChapterLabels('en')} />)
    expect(screen.getByText('REPORT NAV')).toBeInTheDocument()
    expect(screen.getByText('Cover')).toBeInTheDocument()
    expect(screen.getByText('Investment Thesis')).toBeInTheDocument()
    expect(screen.getByText('Disclaimer')).toBeInTheDocument()
  })

  it('numbers chapters 01-12 not 00-11 (user-facing 1-indexed)', () => {
    useUiPrefs.getState().setLocale('zh')
    render(<ReportTOC entries={allChapterLabels('zh')} />)
    // First chapter should display "01" not "00"
    expect(screen.getByText('01')).toBeInTheDocument()
    expect(screen.getByText('12')).toBeInTheDocument()
    expect(screen.queryByText('00')).not.toBeInTheDocument()
  })

  it('each chapter has data-testid toc-{id} for scroll-spy', () => {
    useUiPrefs.getState().setLocale('zh')
    render(<ReportTOC entries={allChapterLabels('zh')} />)
    expect(screen.getByTestId('toc-cover')).toBeInTheDocument()
    expect(screen.getByTestId('toc-thesis')).toBeInTheDocument()
    expect(screen.getByTestId('toc-disclaimer')).toBeInTheDocument()
  })
})
