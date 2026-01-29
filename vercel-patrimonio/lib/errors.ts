/**
 * Custom error types for FinRobot frontend.
 *
 * All custom errors extend FinRobotError for unified error handling.
 *
 * @example
 * try {
 *   const prices = await fetchPrices(tickers);
 * } catch (error) {
 *   if (error instanceof DataFetchError) {
 *     console.error(`Failed to fetch from ${error.source}: ${error.message}`);
 *   }
 * }
 */

/**
 * Base error class for all FinRobot application errors.
 */
export class FinRobotError extends Error {
  readonly code: string
  readonly details: Record<string, unknown>
  readonly timestamp: string

  constructor(
    message: string,
    code: string = 'FINROBOT_ERROR',
    details: Record<string, unknown> = {}
  ) {
    super(message)
    this.name = this.constructor.name
    this.code = code
    this.details = details
    this.timestamp = new Date().toISOString()

    // Maintains proper stack trace for where error was thrown
    if (Error.captureStackTrace) {
      Error.captureStackTrace(this, this.constructor)
    }
  }

  /**
   * Convert error to a plain object for logging or API responses.
   */
  toJSON(): Record<string, unknown> {
    return {
      name: this.name,
      code: this.code,
      message: this.message,
      details: this.details,
      timestamp: this.timestamp,
    }
  }
}

/**
 * Raised when fetching data from an external source fails.
 *
 * @example
 * throw new DataFetchError('Timeout fetching prices', 'yahoo_finance', { tickers: ['AAPL'] });
 */
export class DataFetchError extends FinRobotError {
  readonly source: string | undefined

  constructor(
    message: string,
    source?: string,
    details: Record<string, unknown> = {}
  ) {
    super(message, 'DATA_FETCH_ERROR', { source, ...details })
    this.source = source
  }
}

/**
 * Raised when input validation fails.
 *
 * @example
 * throw new ValidationError('Invalid ticker format', 'ticker', 'AAPL!!');
 */
export class ValidationError extends FinRobotError {
  readonly field: string | undefined
  readonly value: unknown

  constructor(
    message: string,
    field?: string,
    value?: unknown,
    details: Record<string, unknown> = {}
  ) {
    super(message, 'VALIDATION_ERROR', { field, value, ...details })
    this.field = field
    this.value = value
  }
}

/**
 * Raised when configuration is missing or invalid.
 *
 * @example
 * throw new ConfigurationError('Missing API key', 'OPENAI_API_KEY');
 */
export class ConfigurationError extends FinRobotError {
  readonly configKey: string | undefined

  constructor(
    message: string,
    configKey?: string,
    details: Record<string, unknown> = {}
  ) {
    super(message, 'CONFIGURATION_ERROR', { configKey, ...details })
    this.configKey = configKey
  }
}

/**
 * Raised for portfolio-specific errors.
 *
 * @example
 * throw new PortfolioError('Portfolio not found', 'invalid_id');
 */
export class PortfolioError extends FinRobotError {
  readonly portfolioId: string | undefined

  constructor(
    message: string,
    portfolioId?: string,
    details: Record<string, unknown> = {}
  ) {
    super(message, 'PORTFOLIO_ERROR', { portfolioId, ...details })
    this.portfolioId = portfolioId
  }
}

/**
 * Raised for price service specific errors.
 *
 * @example
 * throw new PriceServiceError('Stale price data', 'AAPL', { lastUpdate: '2024-01-01' });
 */
export class PriceServiceError extends FinRobotError {
  readonly ticker: string | undefined

  constructor(
    message: string,
    ticker?: string,
    details: Record<string, unknown> = {}
  ) {
    super(message, 'PRICE_SERVICE_ERROR', { ticker, ...details })
    this.ticker = ticker
  }
}

/**
 * Raised when an API request fails.
 */
export class ApiError extends FinRobotError {
  readonly status: number
  readonly endpoint: string | undefined

  constructor(
    message: string,
    status: number,
    endpoint?: string,
    details: Record<string, unknown> = {}
  ) {
    super(message, 'API_ERROR', { status, endpoint, ...details })
    this.status = status
    this.endpoint = endpoint
  }
}

/**
 * Type guard to check if an error is a FinRobotError.
 */
export function isFinRobotError(error: unknown): error is FinRobotError {
  return error instanceof FinRobotError
}

/**
 * Extract a user-friendly error message from any error.
 */
export function getErrorMessage(error: unknown): string {
  if (error instanceof FinRobotError) {
    return error.message
  }
  if (error instanceof Error) {
    return error.message
  }
  if (typeof error === 'string') {
    return error
  }
  return 'An unexpected error occurred'
}

/**
 * Extract error code from any error.
 */
export function getErrorCode(error: unknown): string {
  if (error instanceof FinRobotError) {
    return error.code
  }
  return 'UNKNOWN_ERROR'
}
