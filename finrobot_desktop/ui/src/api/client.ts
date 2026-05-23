import createClient from 'openapi-fetch'
import type { paths } from './schema'

// Dev: empty string → relative paths go through Vite proxy (same origin, no CORS).
// Prod: Electron loads from file://, so we need the absolute backend URL.
const BASE_URL = import.meta.env.DEV ? '' : 'http://127.0.0.1:8321'

export const api = createClient<paths>({ baseUrl: BASE_URL })

export { BASE_URL }
