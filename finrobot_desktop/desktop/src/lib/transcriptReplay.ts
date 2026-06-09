// transcriptReplay — rebuild a `UIMessage[]` from a session's on-disk JSONL
// transcript so a past conversation can be re-seeded into `useChat` and the
// user can keep chatting (not just read it).
//
// The backend side-logs every turn to ~/.finrobot/sessions/<id>.jsonl via
// `finrobot.audit.transcript.TranscriptWriter`. The event names and `data`
// shapes are the authoritative contract this mapping depends on (verified
// against transcript.py — do NOT guess):
//
//   event            data shape                                    → UIMessage part
//   ───────────────  ────────────────────────────────────────────  ─────────────────────────
//   user_msg         { text }                                      → user msg, text part
//   assistant_text   { text }                                      → assistant msg, text part
//   tool_call        { tool_name, tool_use_id, args }              → assistant dynamic-tool part
//                                                                     (output-available/error;
//                                                                      no result = output-error
//                                                                      "interrupted")
//   tool_result      { tool_use_id, tool_name, result, is_error,   → finalize matching tool part
//                      artifact_id }                                  (output-available/error)
//   error            { exception_class, message, context }         → assistant text part (honest)
//   session_start /                                                  (skipped — no chat content)
//   session_end /
//   context
//
// Coalescing: consecutive assistant events (assistant_text / tool_call /
// tool_result / error) accumulate into ONE assistant UIMessage so a single
// turn that interleaved text + tool calls renders as one bubble — mirroring how
// the live stream builds a multi-part assistant message. A user_msg always
// starts a fresh user message and closes any open assistant message.
//
// Replayed tool parts are intentionally lighter than live ones: we keep the
// tool name, the input args, and a result summary/artifact link so the model
// (and the user) sees what happened, but we don't reconstruct streaming state.

import type { UIMessage, UIMessagePart, UIDataTypes, UITools, DynamicToolUIPart } from 'ai'

/** One JSONL transcript event as returned by GET /api/chat/sessions/{id}. */
export interface TranscriptEvent {
  timestamp: string
  session_id: string
  event: string
  data: Record<string, unknown>
}

type AssistantPart = UIMessagePart<UIDataTypes, UITools>

/** A UIMessage carrying the originating event timestamp so MessageBubble can
 * show a real time instead of "now". The timestamp lives in the Vercel AI SDK's
 * typed `metadata` slot — NOT a root field. A root extra (the old `createdAt`)
 * is echoed verbatim by DefaultChatTransport on the next send and rejected by
 * the backend's strict UIMessage schema (`extra='forbid'`), 422-ing every
 * follow-up in a resumed session. `metadata` is a defined field, so it passes. */
type ReplayMessage = UIMessage & { metadata?: { createdAt?: string } }

function isNonEmptyString(v: unknown): v is string {
  return typeof v === 'string' && v.length > 0
}

/** Pull a human-readable summary + artifact link out of a tool_result payload.
 * Tool results are arbitrary JSON; we surface the same fields the live ToolCard
 * reads ({ summary, artifact_id, ticker }) and fall back to a compact JSON
 * snippet so a result without a summary still carries its information. */
function summarizeToolResult(result: unknown): {
  summary: string
  artifact_id?: string
  ticker?: string
} {
  if (result && typeof result === 'object') {
    const o = result as Record<string, unknown>
    const summary = isNonEmptyString(o.summary) ? o.summary : compactJson(o)
    return {
      summary,
      ...(isNonEmptyString(o.artifact_id) ? { artifact_id: o.artifact_id } : {}),
      ...(isNonEmptyString(o.ticker) ? { ticker: o.ticker } : {}),
    }
  }
  return { summary: result == null ? '' : String(result) }
}

/** Compact one-line JSON preview, truncated, for results lacking a summary. */
function compactJson(value: unknown): string {
  let text: string
  try {
    text = JSON.stringify(value)
  } catch {
    return ''
  }
  if (!text) return ''
  return text.length > 400 ? `${text.slice(0, 400)}…` : text
}

/** Shown on a tool call whose result was never written to the transcript — the
 * turn was cut off mid-stream (panel/app closed, navigated away) before the tool
 * finished. A replay is historical, so this is a terminal interrupted step, not
 * a live one. */
export const INTERRUPTED_TOOL_TEXT =
  'Interrupted — this step did not finish before the session was closed.'

/** Build a finalized dynamic-tool part. When a matching tool_result is known we
 * emit output-available / output-error. A tool_call with NO result line means
 * the turn was interrupted mid-stream (the backend writes the call the instant
 * it is announced but only writes the result when the tool returns). A replayed
 * transcript is historical — nothing is live-streaming into it — so we finalize
 * the dangling call as `output-error` (interrupted) rather than leaving it
 * `input-available`, which the UI would render as a spinner that never stops.
 * The terminal state also gives the tool_use a result, keeping the message
 * sequence valid if the user resumes the session. */
function toolPart(
  toolName: string,
  toolCallId: string,
  input: unknown,
  resultEvt: TranscriptEvent | undefined,
): DynamicToolUIPart {
  const base = { type: 'dynamic-tool' as const, toolName, toolCallId }
  if (!resultEvt) {
    return { ...base, state: 'output-error', input, errorText: INTERRUPTED_TOOL_TEXT }
  }
  const data = resultEvt.data
  const isError = data.is_error === true
  if (isError) {
    const message = isNonEmptyString(data.message)
      ? data.message
      : compactJson(data.result) || 'tool error'
    return { ...base, state: 'output-error', input, errorText: message }
  }
  const out = summarizeToolResult(data.result)
  // The artifact id is the authoritative link source; transcript.py records it
  // at the top level of the tool_result event, so prefer it over any nested one.
  if (isNonEmptyString(data.artifact_id)) out.artifact_id = data.artifact_id
  return { ...base, state: 'output-available', input, output: out }
}

/**
 * Rebuild an ordered `UIMessage[]` from raw transcript events.
 *
 * Pure + deterministic (no I/O, no clock) so it is trivially unit-testable and
 * safe to call on every session switch / reload.
 */
export function reconstructMessages(events: TranscriptEvent[]): UIMessage[] {
  const messages: ReplayMessage[] = []

  // Pre-index tool_result events by tool_use_id so a tool_call can be finalized
  // in one pass even though the result line comes later.
  const resultByUseId = new Map<string, TranscriptEvent>()
  for (const e of events) {
    if (e.event === 'tool_result') {
      const id = e.data.tool_use_id
      if (isNonEmptyString(id)) resultByUseId.set(id, e)
    }
  }

  let current: ReplayMessage | null = null
  let seq = 0

  const closeAssistant = (): void => {
    current = null
  }

  const openAssistant = (timestamp: string): ReplayMessage => {
    if (current && current.role === 'assistant') return current
    const msg: ReplayMessage = {
      id: `replay-asst-${seq++}`,
      role: 'assistant',
      parts: [],
      metadata: { createdAt: timestamp },
    }
    messages.push(msg)
    current = msg
    return msg
  }

  for (const e of events) {
    switch (e.event) {
      case 'user_msg': {
        closeAssistant()
        const text = isNonEmptyString(e.data.text) ? e.data.text : ''
        const msg: ReplayMessage = {
          id: `replay-user-${seq++}`,
          role: 'user',
          parts: [{ type: 'text', text }],
          metadata: { createdAt: e.timestamp },
        }
        messages.push(msg)
        break
      }

      case 'assistant_text': {
        const text = isNonEmptyString(e.data.text) ? e.data.text : ''
        if (!text) break
        const msg = openAssistant(e.timestamp)
        msg.parts.push({ type: 'text', text } as AssistantPart)
        break
      }

      case 'tool_call': {
        const toolName = isNonEmptyString(e.data.tool_name) ? e.data.tool_name : 'tool'
        const toolUseId = isNonEmptyString(e.data.tool_use_id)
          ? e.data.tool_use_id
          : `replay-call-${seq}`
        const input = (e.data.args ?? {}) as unknown
        const msg = openAssistant(e.timestamp)
        msg.parts.push(
          toolPart(toolName, toolUseId, input, resultByUseId.get(toolUseId)) as AssistantPart,
        )
        break
      }

      case 'tool_result':
        // Folded into its tool_call above; nothing to emit standalone.
        break

      case 'error': {
        // Surface the failure inline so the replayed history is honest about a
        // turn that errored rather than silently swallowing it.
        const message = isNonEmptyString(e.data.message) ? e.data.message : 'error'
        const msg = openAssistant(e.timestamp)
        msg.parts.push({ type: 'text', text: `⚠ ${message}` } as AssistantPart)
        break
      }

      // session_start / session_end / context carry no chat content.
      default:
        break
    }
  }

  // Drop any assistant message that ended up with zero parts (e.g. a turn that
  // only emitted a context event) so we never render an empty bubble.
  return messages.filter((m) => m.parts.length > 0)
}
