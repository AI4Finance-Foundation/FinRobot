import { describe, it, expect, beforeEach } from 'vitest'
import { FetchHttpError, mapErrorToUserMessage } from '../errorMessage'
import { RequestTimeoutError } from '../../api/fetch'
import { useUiPrefs } from '../../i18n'

describe('FetchHttpError', () => {
  it('captures status + statusText', () => {
    const err = new FetchHttpError(503, 'Service Unavailable')
    expect(err.status).toBe(503)
    expect(err.statusText).toBe('Service Unavailable')
    expect(err.name).toBe('FetchHttpError')
    expect(err.message).toContain('503')
    expect(err.detail).toBe('')
  })

  it('carries an optional backend detail', () => {
    const err = new FetchHttpError(422, 'Unprocessable Entity', 'ticker XYZ 不存在')
    expect(err.status).toBe(422)
    expect(err.detail).toBe('ticker XYZ 不存在')
  })
})

describe('mapErrorToUserMessage (zh)', () => {
  beforeEach(() => useUiPrefs.getState().setLocale('zh'))

  it('5xx → 服务暂时不可用', () => {
    expect(mapErrorToUserMessage(new FetchHttpError(500))).toBe('服务暂时不可用，请稍后重试')
    expect(mapErrorToUserMessage(new FetchHttpError(502))).toBe('服务暂时不可用，请稍后重试')
  })

  it('404 → 数据不存在', () => {
    expect(mapErrorToUserMessage(new FetchHttpError(404))).toBe('数据不存在')
  })

  it('4xx (non-404) → 请求异常', () => {
    expect(mapErrorToUserMessage(new FetchHttpError(400))).toBe('请求异常，请刷新页面')
    expect(mapErrorToUserMessage(new FetchHttpError(422))).toBe('请求异常，请刷新页面')
  })

  it('backend detail is preferred over the generic status bucket', () => {
    expect(mapErrorToUserMessage(new FetchHttpError(422, '', 'ticker XYZ 不存在'))).toBe(
      'ticker XYZ 不存在',
    )
    expect(mapErrorToUserMessage(new FetchHttpError(409, '', '分组名已存在'))).toBe('分组名已存在')
  })

  it('network TypeError → offline message', () => {
    const err = new TypeError('Failed to fetch')
    expect(mapErrorToUserMessage(err)).toBe('网络连接失败，请检查网络')
  })

  it('request timeout → restart app guidance', () => {
    expect(mapErrorToUserMessage(new RequestTimeoutError(5000))).toBe('网络连接失败，请检查网络')
  })

  it('AbortError → 已取消', () => {
    const err = new DOMException('Aborted', 'AbortError')
    expect(mapErrorToUserMessage(err)).toBe('已取消')
  })

  it("plain Error with 'HTTP 500' message → server unavailable", () => {
    expect(mapErrorToUserMessage(new Error('HTTP 500'))).toBe('服务暂时不可用，请稍后重试')
    expect(mapErrorToUserMessage(new Error('HTTP 503 Service Unavailable'))).toBe(
      '服务暂时不可用，请稍后重试',
    )
  })

  it('pre-localised Error message passes through', () => {
    expect(mapErrorToUserMessage(new Error('无法加载季度财务数据'))).toBe('无法加载季度财务数据')
  })

  it('unknown error → unknown fallback', () => {
    expect(mapErrorToUserMessage(undefined)).toBe('加载失败，请稍后重试')
    expect(mapErrorToUserMessage(null)).toBe('加载失败，请稍后重试')
    expect(mapErrorToUserMessage('string error')).toBe('加载失败，请稍后重试')
  })
})

describe('mapErrorToUserMessage (en)', () => {
  beforeEach(() => useUiPrefs.getState().setLocale('en'))

  it('5xx → service unavailable', () => {
    expect(mapErrorToUserMessage(new FetchHttpError(500))).toBe(
      'Service temporarily unavailable. Please try again later.',
    )
  })

  it('network failure', () => {
    const err = new TypeError('network failure')
    expect(mapErrorToUserMessage(err)).toBe(
      'Network connection failed. Please check your connection.',
    )
  })

  it('request timeout', () => {
    expect(mapErrorToUserMessage(new RequestTimeoutError(5000))).toBe(
      'Network connection failed. Please check your connection.',
    )
  })
})
