// ─── SEC identity validation (mirrors edgar_provider._is_valid_identity) ──────

export const SEC_IDENTITY_EXAMPLE = 'Acme Research analyst@example.com'
const SEC_EMAIL_RE = /[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}/

function extractSecEmail(s: string): RegExpMatchArray | null {
  return s.match(SEC_EMAIL_RE)
}

/** SEC requires `Name email@domain` — we also reject the backend's placeholder
 * default `FinRobot admin@example.com` so the user has to set a real one. */
export function isValidSecIdentity(s: string | null | undefined): boolean {
  if (!s) return false
  const trimmed = s.trim()
  if (!trimmed.includes('@') || !trimmed.includes(' ')) return false
  if (trimmed === 'FinRobot admin@example.com') return false
  return extractSecEmail(trimmed) !== null
}

export function secHeaderIdentityPreview(s: string | null | undefined): string | null {
  if (!s || !isValidSecIdentity(s)) return null
  const raw = s.trim()
  const match = extractSecEmail(raw)
  if (!match || match.index === undefined) return null
  const email = match[0]
  const nameBeforeEmail = raw.slice(0, match.index).trim()
  const nameAfterEmail = raw.slice(match.index + email.length).trim()
  const displayName = nameBeforeEmail || nameAfterEmail
  const asciiName = [...displayName]
    .map((ch) => (ch.charCodeAt(0) < 128 ? ch : ' '))
    .join('')
    .split(/\s+/)
    .filter(Boolean)
    .join(' ')
  return `${asciiName || 'FinRobot'} ${email}`
}
