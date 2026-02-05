/**
 * Input validation schemas using Zod
 * Central validation for all API routes
 */
import { z } from 'zod'

// ═══════════════════════════════════════════════════════════════════════════════
// TICKER VALIDATION
// ═══════════════════════════════════════════════════════════════════════════════

const MAX_TICKERS_PER_REQUEST = 50
const TICKER_PATTERN = /^[A-Z0-9._=-]{1,20}$/

export const TickerSchema = z
  .string()
  .min(1, 'Ticker cannot be empty')
  .max(20, 'Ticker too long')
  .transform((val) => val.trim().toUpperCase())
  .refine((val) => TICKER_PATTERN.test(val), {
    message: 'Invalid ticker format',
  })

export const TickerListSchema = z
  .string()
  .min(1, 'No tickers specified')
  .transform((val) => val.split(',').map((t) => t.trim().toUpperCase()).filter(Boolean))
  .refine((arr) => arr.length > 0, { message: 'No valid tickers found' })
  .refine((arr) => arr.length <= MAX_TICKERS_PER_REQUEST, {
    message: `Too many tickers. Max: ${MAX_TICKERS_PER_REQUEST}`,
  })
  .pipe(z.array(z.string().regex(TICKER_PATTERN, 'Invalid ticker format')))

// ═══════════════════════════════════════════════════════════════════════════════
// PRICE API SCHEMAS
// ═══════════════════════════════════════════════════════════════════════════════

export const PriceRequestSchema = z.object({
  tickers: TickerListSchema,
})

export const ManualPriceUpdateSchema = z.object({
  ticker: TickerSchema,
  price: z.number().positive('Price must be positive'),
})

// ═══════════════════════════════════════════════════════════════════════════════
// SNAPSHOT SCHEMAS
// ═══════════════════════════════════════════════════════════════════════════════

export const DateSchema = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/, 'Invalid date format (expected YYYY-MM-DD)')

export const SnapshotQuerySchema = z.object({
  days: z.coerce.number().int().min(1).max(365).optional().default(30),
  startDate: DateSchema.optional(),
  endDate: DateSchema.optional(),
})

export const SnapshotSchema = z.object({
  timestamp: z.string().optional(),
  date: DateSchema.optional(),
  totalValue: z.number().positive('Total value must be positive'),
  totalCost: z.number().positive('Total cost must be positive'),
  totalPnL: z.number(),
  totalPnLPct: z.number(),
  rvValue: z.number().nonnegative().optional(),
  rvCost: z.number().nonnegative().optional(),
  rvPnL: z.number().optional(),
  rvPnLPct: z.number().optional(),
  rfValue: z.number().nonnegative().optional(),
  rfCost: z.number().nonnegative().optional(),
  rfPnL: z.number().optional(),
  rfPnLPct: z.number().optional(),
  indexaValue: z.number().nonnegative().optional(),
  indexaPnL: z.number().optional(),
  bankinterValue: z.number().nonnegative().optional(),
  bankinterPnL: z.number().optional(),
  andbankValue: z.number().nonnegative().optional(),
  andbankPnL: z.number().optional(),
  oroValue: z.number().nonnegative().optional(),
  oroPnL: z.number().optional(),
  criptoValue: z.number().nonnegative().optional(),
  criptoPnL: z.number().optional(),
  liquidezValue: z.number().nonnegative().optional(),
  positions: z.array(z.unknown()).optional(),
})

// ═══════════════════════════════════════════════════════════════════════════════
// CHAT API SCHEMAS
// ═══════════════════════════════════════════════════════════════════════════════

export const ChatMessageSchema = z.object({
  role: z.enum(['user', 'assistant', 'system']),
  content: z.string().min(1).max(50000),
})

export const ChatRequestSchema = z.object({
  message: z.string().min(1, 'Message cannot be empty').max(10000, 'Message too long'),
  history: z.array(ChatMessageSchema).max(50, 'Too many messages in history').default([]),
  portfolioId: z.enum(['salva', 'madre', 'consolidado']).default('salva'),
})

// ═══════════════════════════════════════════════════════════════════════════════
// HELPER FUNCTIONS
// ═══════════════════════════════════════════════════════════════════════════════

export type ValidationResult<T> =
  | { success: true; data: T }
  | { success: false; error: string }

export function validateRequest<T>(
  schema: z.ZodSchema<T>,
  data: unknown
): ValidationResult<T> {
  const result = schema.safeParse(data)
  if (result.success) {
    return { success: true, data: result.data }
  }
  const errorMessage = result.error.errors.map((e) => e.message).join(', ')
  return { success: false, error: errorMessage }
}

// Type exports
export type PriceRequest = z.infer<typeof PriceRequestSchema>
export type ManualPriceUpdate = z.infer<typeof ManualPriceUpdateSchema>
export type SnapshotQuery = z.infer<typeof SnapshotQuerySchema>
export type Snapshot = z.infer<typeof SnapshotSchema>
export type ChatMessage = z.infer<typeof ChatMessageSchema>
export type ChatRequest = z.infer<typeof ChatRequestSchema>
