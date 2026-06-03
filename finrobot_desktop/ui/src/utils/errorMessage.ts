// User-facing error message mapper.
//
// Errors thrown inside fetch / react-query / mutations land in the UI as
// `error.message`. Without a mapping layer they leak "HTTP 500" / "fetch
// failed" / "TypeError: NetworkError" — all developer language.
//
// Rules:
//   - 5xx                                → 服务暂时不可用，请稍后重试
//   - 4xx (404 special)                  → 请求异常 / 资源不存在
//   - network failure (no response)      → 网络连接失败，请检查网络
//   - AbortError                         → 已取消
//   - everything else                    → 加载失败，请稍后重试
//
// The catalog keys live in i18n/locales/{zh,en}/messages.po under `errors.*`.

import { tSync } from '../i18n'
import { RequestTimeoutError } from '../api/fetch'

/**
 * Typed HTTP error. Throw this from fetch wrappers instead of plain Error
 * so mapErrorToUserMessage can return the right user copy.
 *
 *   if (!resp.ok) throw new FetchHttpError(resp.status, resp.statusText)
 *
 * When the backend ships a human-readable `detail` (FastAPI's 中文 error copy),
 * pass it as the 3rd arg so mapErrorToUserMessage surfaces it verbatim instead
 * of the generic status-bucket fallback — and err.status is still preserved for
 * any status-based branching.
 */
export class FetchHttpError extends Error {
  readonly status: number
  readonly statusText: string
  readonly detail: string

  constructor(status: number, statusText = '', detail = '') {
    // The dev-facing message is fine to keep technical; the UI never reads
    // err.message directly when going through mapErrorToUserMessage.
    super(`HTTP ${status}${statusText ? ` ${statusText}` : ''}`)
    this.name = 'FetchHttpError'
    this.status = status
    this.statusText = statusText
    this.detail = detail
  }
}

/**
 * Best-effort convert any thrown value into a user-friendly localised string.
 *
 * If the error already carries a Chinese / English user-facing message
 * (e.g. extracted from the backend's `detail`), we trust and return it.
 * Otherwise we apply the rules above.
 */
export function mapErrorToUserMessage(err: unknown): string {
  if (err instanceof RequestTimeoutError) {
    return tSync('errors.network.offline')
  }

  // Network failure — fetch couldn't get a response at all.
  if (err instanceof TypeError && /fetch|network/i.test(err.message)) {
    return tSync('errors.network.offline')
  }

  // User cancelled (AbortController).
  if (err instanceof DOMException && err.name === 'AbortError') {
    return tSync('errors.cancelled')
  }

  // Typed HTTP error. A backend-supplied `detail` is already user-facing 中文
  // copy (e.g. "ticker XYZ 不存在" / "分组名已存在") — prefer it over the
  // generic status bucket so the analyst sees the actual reason.
  if (err instanceof FetchHttpError) {
    if (err.detail.trim()) return err.detail
    if (err.status >= 500) return tSync('errors.server.unavailable')
    if (err.status === 404) return tSync('errors.notfound')
    if (err.status >= 400) return tSync('errors.client.invalid')
  }

  // Plain Error with a message. Heuristic: messages containing "HTTP <num>"
  // are dev-facing and should be replaced; messages with Chinese characters
  // or proper sentences are pre-localised user messages — pass through.
  if (err instanceof Error) {
    const msg = err.message
    if (/^HTTP\s+\d{3}/i.test(msg.trim())) {
      const m = msg.match(/HTTP\s+(\d{3})/i)
      const status = m ? Number(m[1]) : 0
      if (status >= 500) return tSync('errors.server.unavailable')
      if (status === 404) return tSync('errors.notfound')
      if (status >= 400) return tSync('errors.client.invalid')
    }
    if (msg && msg.length > 0 && !/^Error$/i.test(msg)) {
      return msg
    }
  }

  return tSync('errors.unknown')
}
