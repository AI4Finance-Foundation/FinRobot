const BACKEND_HOSTS = new Set(['127.0.0.1', 'localhost'])

export function isBackendUrl(input: string | URL): boolean {
  const raw = typeof input === 'string' ? input : input.href
  if (!raw) return false
  if (raw.startsWith('//')) return false
  if (raw.startsWith('/')) return true

  let url: URL
  try {
    url = typeof input === 'string' ? new URL(raw) : input
  } catch {
    return false
  }

  return url.protocol === 'http:' && url.port === '8321' && BACKEND_HOSTS.has(url.hostname)
}
