/**
 * Tests for validation.ts module.
 *
 * Tests cover all Zod schemas and validation helpers.
 */
import { describe, it, expect } from 'vitest'
import {
  TickerSchema,
  TickerListSchema,
  ManualPriceUpdateSchema,
  DateSchema,
  SnapshotQuerySchema,
  ChatMessageSchema,
  ChatRequestSchema,
  validateRequest,
} from '../lib/validation'

describe('TickerSchema', () => {
  it('should accept valid tickers', () => {
    expect(TickerSchema.parse('AAPL')).toBe('AAPL')
    expect(TickerSchema.parse('MSFT')).toBe('MSFT')
    expect(TickerSchema.parse('IWDA.AS')).toBe('IWDA.AS')
    expect(TickerSchema.parse('BTC-USD')).toBe('BTC-USD')
  })

  it('should transform lowercase to uppercase', () => {
    expect(TickerSchema.parse('aapl')).toBe('AAPL')
    expect(TickerSchema.parse('msft')).toBe('MSFT')
  })

  it('should trim whitespace', () => {
    expect(TickerSchema.parse('  AAPL  ')).toBe('AAPL')
    expect(TickerSchema.parse('\tMSFT\n')).toBe('MSFT')
  })

  it('should reject empty tickers', () => {
    expect(() => TickerSchema.parse('')).toThrow()
    expect(() => TickerSchema.parse('   ')).toThrow()
  })

  it('should reject tickers that are too long', () => {
    expect(() => TickerSchema.parse('A'.repeat(21))).toThrow()
  })

  it('should reject invalid characters', () => {
    expect(() => TickerSchema.parse('AAPL!')).toThrow()
    expect(() => TickerSchema.parse('AA PL')).toThrow()
    expect(() => TickerSchema.parse('AAPL@NASDAQ')).toThrow()
  })
})

describe('TickerListSchema', () => {
  it('should accept comma-separated tickers', () => {
    const result = TickerListSchema.parse('AAPL,MSFT,GOOGL')
    expect(result).toEqual(['AAPL', 'MSFT', 'GOOGL'])
  })

  it('should handle whitespace in list', () => {
    const result = TickerListSchema.parse('AAPL, MSFT , GOOGL')
    expect(result).toEqual(['AAPL', 'MSFT', 'GOOGL'])
  })

  it('should transform to uppercase', () => {
    const result = TickerListSchema.parse('aapl,msft')
    expect(result).toEqual(['AAPL', 'MSFT'])
  })

  it('should filter empty entries', () => {
    const result = TickerListSchema.parse('AAPL,,MSFT,')
    expect(result).toEqual(['AAPL', 'MSFT'])
  })

  it('should reject empty input', () => {
    expect(() => TickerListSchema.parse('')).toThrow()
  })

  it('should reject too many tickers', () => {
    const tickers = Array(51).fill('AAPL').join(',')
    expect(() => TickerListSchema.parse(tickers)).toThrow('Too many tickers')
  })

  it('should accept exactly 50 tickers', () => {
    const tickers = Array(50).fill('AAPL').join(',')
    const result = TickerListSchema.parse(tickers)
    expect(result).toHaveLength(50)
  })
})

describe('ManualPriceUpdateSchema', () => {
  it('should accept valid price update', () => {
    const result = ManualPriceUpdateSchema.parse({
      ticker: 'AAPL',
      price: 175.50,
    })
    expect(result.ticker).toBe('AAPL')
    expect(result.price).toBe(175.5)
  })

  it('should reject negative price', () => {
    expect(() =>
      ManualPriceUpdateSchema.parse({
        ticker: 'AAPL',
        price: -10,
      })
    ).toThrow('Price must be positive')
  })

  it('should reject zero price', () => {
    expect(() =>
      ManualPriceUpdateSchema.parse({
        ticker: 'AAPL',
        price: 0,
      })
    ).toThrow()
  })

  it('should reject invalid ticker', () => {
    expect(() =>
      ManualPriceUpdateSchema.parse({
        ticker: '',
        price: 100,
      })
    ).toThrow()
  })
})

describe('DateSchema', () => {
  it('should accept valid dates', () => {
    expect(DateSchema.parse('2024-01-15')).toBe('2024-01-15')
    expect(DateSchema.parse('2023-12-31')).toBe('2023-12-31')
  })

  it('should reject invalid date formats', () => {
    expect(() => DateSchema.parse('01-15-2024')).toThrow()
    expect(() => DateSchema.parse('2024/01/15')).toThrow()
    expect(() => DateSchema.parse('Jan 15, 2024')).toThrow()
    expect(() => DateSchema.parse('2024-1-15')).toThrow() // Single digit month
  })

  it('should reject invalid strings', () => {
    expect(() => DateSchema.parse('not-a-date')).toThrow()
    expect(() => DateSchema.parse('')).toThrow()
  })
})

describe('SnapshotQuerySchema', () => {
  it('should accept valid query with defaults', () => {
    const result = SnapshotQuerySchema.parse({})
    expect(result.days).toBe(30) // Default value
  })

  it('should accept days parameter', () => {
    const result = SnapshotQuerySchema.parse({ days: '90' })
    expect(result.days).toBe(90)
  })

  it('should coerce string to number for days', () => {
    const result = SnapshotQuerySchema.parse({ days: '60' })
    expect(result.days).toBe(60)
  })

  it('should reject days below minimum', () => {
    expect(() => SnapshotQuerySchema.parse({ days: 0 })).toThrow()
  })

  it('should reject days above maximum', () => {
    expect(() => SnapshotQuerySchema.parse({ days: 400 })).toThrow()
  })

  it('should accept optional date range', () => {
    const result = SnapshotQuerySchema.parse({
      startDate: '2024-01-01',
      endDate: '2024-01-31',
    })
    expect(result.startDate).toBe('2024-01-01')
    expect(result.endDate).toBe('2024-01-31')
  })
})

describe('ChatMessageSchema', () => {
  it('should accept valid user message', () => {
    const result = ChatMessageSchema.parse({
      role: 'user',
      content: 'Hello, world!',
    })
    expect(result.role).toBe('user')
    expect(result.content).toBe('Hello, world!')
  })

  it('should accept valid assistant message', () => {
    const result = ChatMessageSchema.parse({
      role: 'assistant',
      content: 'Hi there!',
    })
    expect(result.role).toBe('assistant')
  })

  it('should accept valid system message', () => {
    const result = ChatMessageSchema.parse({
      role: 'system',
      content: 'You are a helpful assistant.',
    })
    expect(result.role).toBe('system')
  })

  it('should reject invalid roles', () => {
    expect(() =>
      ChatMessageSchema.parse({
        role: 'admin',
        content: 'Hello',
      })
    ).toThrow()
  })

  it('should reject empty content', () => {
    expect(() =>
      ChatMessageSchema.parse({
        role: 'user',
        content: '',
      })
    ).toThrow()
  })
})

describe('ChatRequestSchema', () => {
  it('should accept valid chat request', () => {
    const result = ChatRequestSchema.parse({
      message: 'What is my portfolio value?',
    })
    expect(result.message).toBe('What is my portfolio value?')
    expect(result.history).toEqual([]) // Default
    expect(result.portfolioId).toBe('salva') // Default
  })

  it('should accept request with history', () => {
    const result = ChatRequestSchema.parse({
      message: 'Continue...',
      history: [
        { role: 'user', content: 'Hello' },
        { role: 'assistant', content: 'Hi!' },
      ],
    })
    expect(result.history).toHaveLength(2)
  })

  it('should accept different portfolio IDs', () => {
    expect(ChatRequestSchema.parse({ message: 'Hi', portfolioId: 'madre' }).portfolioId).toBe(
      'madre'
    )
    expect(
      ChatRequestSchema.parse({ message: 'Hi', portfolioId: 'consolidado' }).portfolioId
    ).toBe('consolidado')
  })

  it('should reject invalid portfolio ID', () => {
    expect(() =>
      ChatRequestSchema.parse({
        message: 'Hi',
        portfolioId: 'invalid',
      })
    ).toThrow()
  })

  it('should reject empty message', () => {
    expect(() => ChatRequestSchema.parse({ message: '' })).toThrow()
  })

  it('should reject message that is too long', () => {
    const longMessage = 'a'.repeat(10001)
    expect(() => ChatRequestSchema.parse({ message: longMessage })).toThrow()
  })

  it('should reject too many messages in history', () => {
    const history = Array(51)
      .fill(null)
      .map(() => ({ role: 'user' as const, content: 'Hi' }))
    expect(() =>
      ChatRequestSchema.parse({
        message: 'Hello',
        history,
      })
    ).toThrow()
  })
})

describe('validateRequest', () => {
  it('should return success for valid data', () => {
    const result = validateRequest(TickerSchema, 'AAPL')
    expect(result.success).toBe(true)
    if (result.success) {
      expect(result.data).toBe('AAPL')
    }
  })

  it('should return error for invalid data', () => {
    const result = validateRequest(TickerSchema, '')
    expect(result.success).toBe(false)
    if (!result.success) {
      expect(result.error).toContain('empty')
    }
  })

  it('should combine multiple error messages', () => {
    const result = validateRequest(ManualPriceUpdateSchema, { ticker: '', price: -5 })
    expect(result.success).toBe(false)
    if (!result.success) {
      expect(result.error).toContain(',') // Multiple errors joined
    }
  })
})
