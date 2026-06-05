import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

import { TickerNotFoundView } from './TickerNotFoundView'

vi.mock('../../i18n', async () => {
  const actual = await vi.importActual<Record<string, unknown>>('../../i18n')
  return {
    ...actual,
    tSync: (key: string, params?: Record<string, unknown>) => {
      const t = params?.ticker ?? ''
      const map: Record<string, string> = {
        'ticker.notFound.title': `未找到 ${t}`,
        'ticker.notFound.description': 'yfinance 无该代码的数据。请检查拼写。',
        'ticker.notFound.backButton': '回搜索',
        'ticker.notFound.hint1': '仅支持美股（NASDAQ / NYSE / AMEX）',
        'ticker.notFound.hint2': '当前仅按代码搜索，不支持公司名',
        'ticker.notFound.hint3': '港股 / A 股代码不支持',
        'ticker.notFound.hint4': '如确认拼写无误，可能 yfinance 暂未收录该代码',
      }
      return map[key] ?? key
    },
    useI18n: () => ({
      locale: 'zh',
      t: (k: string, params?: Record<string, unknown>) => {
        const t_ = params?.ticker ?? ''
        const map: Record<string, string> = {
          'ticker.notFound.title': `未找到 ${t_}`,
          'ticker.notFound.description': 'yfinance 无该代码的数据。请检查拼写。',
          'ticker.notFound.backButton': '回搜索',
          'ticker.notFound.hint1': '仅支持美股（NASDAQ / NYSE / AMEX）',
          'ticker.notFound.hint2': '当前仅按代码搜索，不支持公司名',
          'ticker.notFound.hint3': '港股 / A 股代码不支持',
          'ticker.notFound.hint4': '如确认拼写无误，可能 yfinance 暂未收录该代码',
        }
        return map[k] ?? k
      },
    }),
  }
})

describe('TickerNotFoundView', () => {
  it('renders the not-found title with the ticker', () => {
    render(
      <MemoryRouter>
        <TickerNotFoundView ticker="XYZINVALID" />
      </MemoryRouter>,
    )
    expect(screen.getByText(/未找到 XYZINVALID/)).toBeInTheDocument()
    expect(screen.getByText(/yfinance 无该代码的数据/)).toBeInTheDocument()
  })

  it('renders all 4 troubleshooting hints', () => {
    render(
      <MemoryRouter>
        <TickerNotFoundView ticker="ZZZ" />
      </MemoryRouter>,
    )
    expect(screen.getByText(/仅支持美股/)).toBeInTheDocument()
    expect(screen.getByText(/不支持公司名/)).toBeInTheDocument()
    expect(screen.getByText(/港股 \/ A 股/)).toBeInTheDocument()
    expect(screen.getByText(/yfinance 暂未收录/)).toBeInTheDocument()
  })

  it('Back-to-search link navigates to /research (the search homepage, matching its label)', () => {
    render(
      <MemoryRouter initialEntries={['/stocks/INVALID']}>
        <Routes>
          <Route path="/stocks/:ticker" element={<TickerNotFoundView ticker="INVALID" />} />
          <Route path="/research" element={<div data-testid="research">research</div>} />
        </Routes>
      </MemoryRouter>,
    )
    const back = screen.getByRole('link', { name: /回搜索/ })
    fireEvent.click(back)
    expect(screen.getByTestId('research')).toBeInTheDocument()
  })
})
