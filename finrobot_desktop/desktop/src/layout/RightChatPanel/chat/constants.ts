// Shared chat constants — sizing limits and error classification used by both
// the chat state machine (useChatStream) and the input area's error banner.

export const MAX_INPUT_LENGTH = 20_000

// True only for a genuine LLM context-window overflow, matched on the specific
// phrases providers actually emit — NOT the bare substrings "context"/"token".
// A 422 from /chat echoes the request body (which carries our `context_bundle`),
// and auth failures mention the "capability token"; matching bare "context" or
// "token" mislabeled those protocol/auth errors as "Conversation too long"
// (a one-line message that triggered four 422 retries, all misreported).
const CONTEXT_OVERFLOW_RE =
  /context[_ ]length|maximum context|context window|prompt is too long|reduce the length/i
export function isContextOverflowError(message: string): boolean {
  return CONTEXT_OVERFLOW_RE.test(message)
}
