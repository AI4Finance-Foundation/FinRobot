/**
 * Tests for the errors module.
 *
 * Tests cover all custom error classes and utility functions.
 */
import { describe, it, expect } from 'vitest'
import {
  FinRobotError,
  DataFetchError,
  ValidationError,
  ConfigurationError,
  PortfolioError,
  PriceServiceError,
  ApiError,
  isFinRobotError,
  getErrorMessage,
  getErrorCode,
} from '../lib/errors'

describe('FinRobotError', () => {
  it('should create error with message only', () => {
    const error = new FinRobotError('Something went wrong')

    expect(error.message).toBe('Something went wrong')
    expect(error.code).toBe('FINROBOT_ERROR')
    expect(error.details).toEqual({})
    expect(error.name).toBe('FinRobotError')
  })

  it('should create error with custom code', () => {
    const error = new FinRobotError('Error', 'CUSTOM_CODE')

    expect(error.code).toBe('CUSTOM_CODE')
  })

  it('should create error with details', () => {
    const error = new FinRobotError('Error', 'CODE', { ticker: 'AAPL' })

    expect(error.details.ticker).toBe('AAPL')
  })

  it('should include timestamp', () => {
    const before = new Date().toISOString()
    const error = new FinRobotError('Error')
    const after = new Date().toISOString()

    expect(error.timestamp >= before).toBe(true)
    expect(error.timestamp <= after).toBe(true)
  })

  it('should convert to JSON', () => {
    const error = new FinRobotError('Test error', 'TEST_CODE', { key: 'value' })
    const json = error.toJSON()

    expect(json.name).toBe('FinRobotError')
    expect(json.code).toBe('TEST_CODE')
    expect(json.message).toBe('Test error')
    expect(json.details).toEqual({ key: 'value' })
    expect(json.timestamp).toBeDefined()
  })

  it('should be instance of Error', () => {
    const error = new FinRobotError('Test')

    expect(error instanceof Error).toBe(true)
    expect(error instanceof FinRobotError).toBe(true)
  })
})

describe('DataFetchError', () => {
  it('should create error with source', () => {
    const error = new DataFetchError('Timeout', 'yahoo_finance')

    expect(error.source).toBe('yahoo_finance')
    expect(error.code).toBe('DATA_FETCH_ERROR')
    expect(error.details.source).toBe('yahoo_finance')
  })

  it('should create error without source', () => {
    const error = new DataFetchError('Connection refused')

    expect(error.source).toBeUndefined()
    expect(error.code).toBe('DATA_FETCH_ERROR')
  })

  it('should include additional details', () => {
    const error = new DataFetchError('Rate limited', 'api', { retryAfter: 60 })

    expect(error.details.source).toBe('api')
    expect(error.details.retryAfter).toBe(60)
  })

  it('should inherit from FinRobotError', () => {
    const error = new DataFetchError('Test')

    expect(error instanceof FinRobotError).toBe(true)
    expect(error instanceof Error).toBe(true)
  })
})

describe('ValidationError', () => {
  it('should create error with field and value', () => {
    const error = new ValidationError('Invalid format', 'ticker', 'AAPL!!')

    expect(error.field).toBe('ticker')
    expect(error.value).toBe('AAPL!!')
    expect(error.code).toBe('VALIDATION_ERROR')
  })

  it('should create error without field info', () => {
    const error = new ValidationError('Invalid input')

    expect(error.field).toBeUndefined()
    expect(error.value).toBeUndefined()
  })

  it('should include field info in details', () => {
    const error = new ValidationError('Invalid', 'price', -100)

    expect(error.details.field).toBe('price')
    expect(error.details.value).toBe(-100)
  })
})

describe('ConfigurationError', () => {
  it('should create error with config key', () => {
    const error = new ConfigurationError('Missing API key', 'OPENAI_API_KEY')

    expect(error.configKey).toBe('OPENAI_API_KEY')
    expect(error.code).toBe('CONFIGURATION_ERROR')
  })

  it('should create error without config key', () => {
    const error = new ConfigurationError('Invalid configuration')

    expect(error.configKey).toBeUndefined()
  })
})

describe('PortfolioError', () => {
  it('should create error with portfolio ID', () => {
    const error = new PortfolioError('Not found', 'carrillo_sanchez')

    expect(error.portfolioId).toBe('carrillo_sanchez')
    expect(error.code).toBe('PORTFOLIO_ERROR')
  })

  it('should create error without portfolio ID', () => {
    const error = new PortfolioError('Invalid allocation')

    expect(error.portfolioId).toBeUndefined()
  })
})

describe('PriceServiceError', () => {
  it('should create error with ticker', () => {
    const error = new PriceServiceError('Stale data', 'AAPL')

    expect(error.ticker).toBe('AAPL')
    expect(error.code).toBe('PRICE_SERVICE_ERROR')
  })

  it('should include additional details', () => {
    const error = new PriceServiceError('Stale', 'MSFT', { lastUpdate: '2024-01-01' })

    expect(error.details.ticker).toBe('MSFT')
    expect(error.details.lastUpdate).toBe('2024-01-01')
  })
})

describe('ApiError', () => {
  it('should create error with status and endpoint', () => {
    const error = new ApiError('Not found', 404, '/api/prices')

    expect(error.status).toBe(404)
    expect(error.endpoint).toBe('/api/prices')
    expect(error.code).toBe('API_ERROR')
  })

  it('should include status in details', () => {
    const error = new ApiError('Server error', 500)

    expect(error.details.status).toBe(500)
  })
})

describe('isFinRobotError', () => {
  it('should return true for FinRobotError', () => {
    expect(isFinRobotError(new FinRobotError('Test'))).toBe(true)
  })

  it('should return true for subclasses', () => {
    expect(isFinRobotError(new DataFetchError('Test'))).toBe(true)
    expect(isFinRobotError(new ValidationError('Test'))).toBe(true)
    expect(isFinRobotError(new ConfigurationError('Test'))).toBe(true)
    expect(isFinRobotError(new PortfolioError('Test'))).toBe(true)
    expect(isFinRobotError(new PriceServiceError('Test'))).toBe(true)
    expect(isFinRobotError(new ApiError('Test', 500))).toBe(true)
  })

  it('should return false for regular Error', () => {
    expect(isFinRobotError(new Error('Test'))).toBe(false)
  })

  it('should return false for non-errors', () => {
    expect(isFinRobotError('string')).toBe(false)
    expect(isFinRobotError(null)).toBe(false)
    expect(isFinRobotError(undefined)).toBe(false)
    expect(isFinRobotError({ message: 'Test' })).toBe(false)
  })
})

describe('getErrorMessage', () => {
  it('should extract message from FinRobotError', () => {
    const error = new FinRobotError('Custom message')
    expect(getErrorMessage(error)).toBe('Custom message')
  })

  it('should extract message from regular Error', () => {
    const error = new Error('Standard error')
    expect(getErrorMessage(error)).toBe('Standard error')
  })

  it('should return string directly', () => {
    expect(getErrorMessage('Error string')).toBe('Error string')
  })

  it('should return fallback for unknown types', () => {
    expect(getErrorMessage(null)).toBe('An unexpected error occurred')
    expect(getErrorMessage(undefined)).toBe('An unexpected error occurred')
    expect(getErrorMessage(123)).toBe('An unexpected error occurred')
  })
})

describe('getErrorCode', () => {
  it('should extract code from FinRobotError', () => {
    const error = new DataFetchError('Test')
    expect(getErrorCode(error)).toBe('DATA_FETCH_ERROR')
  })

  it('should return UNKNOWN_ERROR for regular Error', () => {
    const error = new Error('Test')
    expect(getErrorCode(error)).toBe('UNKNOWN_ERROR')
  })

  it('should return UNKNOWN_ERROR for non-errors', () => {
    expect(getErrorCode('string')).toBe('UNKNOWN_ERROR')
    expect(getErrorCode(null)).toBe('UNKNOWN_ERROR')
  })
})

describe('Error hierarchy', () => {
  it('should allow catching all errors with base class', () => {
    const errors = [
      new DataFetchError('test'),
      new ValidationError('test'),
      new ConfigurationError('test'),
      new PortfolioError('test'),
      new PriceServiceError('test'),
      new ApiError('test', 500),
    ]

    for (const error of errors) {
      expect(error instanceof FinRobotError).toBe(true)
    }
  })
})
