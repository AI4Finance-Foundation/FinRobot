// ──────────────────────────────────────────────────────────────
// StatusIndicator — REAL streaming status (replaces the old fake 3-dot
// blinker). Aligned to how Claude Code drives its waiting indicator: a phase
// derived from actual stream state, a real elapsed-seconds counter, and a
// stall detector (no new content for >3s with no tool running ⇒ honest red
// "is it stuck?" signal). No random verb words, no token counts, no shimmer.
//
//   submitted                         → Requesting…   (TTFT — nothing back yet)
//   streaming + tool running          → Running {tool}…
//   streaming + reasoning, no text    → Thinking…
//   streaming + text present          → Responding…   (the text itself shows;
//                                                       the line stays subtle)
//   streaming, nothing yet            → Thinking…
// ──────────────────────────────────────────────────────────────

import { useState, useEffect, useRef } from 'react'
import type { UIMessage, DynamicToolUIPart } from 'ai'
import { isTextUIPart, isToolUIPart, isReasoningUIPart } from 'ai'
import { useI18n } from '../../../i18n'

export type ChatStatus = 'submitted' | 'streaming' | 'ready' | 'error'

const STALL_MS = 3000

type Phase =
  | { kind: 'requesting' }
  | { kind: 'thinking' }
  | { kind: 'responding' }
  | { kind: 'tool'; toolName: string }

/** Derive the live phase from the raw status + the last assistant message's
 * parts. Pure so it can be unit-tested without timers. */
function derivePhase(status: ChatStatus, messages: UIMessage[]): Phase {
  if (status === 'submitted') return { kind: 'requesting' }

  // status === 'streaming' (the indicator only renders while isLoading)
  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant')
  const parts = lastAssistant?.parts ?? []

  // A tool whose output hasn't landed yet is the most concrete in-flight signal.
  for (let i = parts.length - 1; i >= 0; i--) {
    const part = parts[i]
    if (!isToolUIPart(part)) continue
    const anyPart = part as DynamicToolUIPart
    if (anyPart.state === 'input-streaming' || anyPart.state === 'input-available') {
      return { kind: 'tool', toolName: anyPart.toolName ?? part.type.replace(/^tool-/, '') }
    }
  }

  const hasText = parts.some((p) => isTextUIPart(p) && p.text.length > 0)
  if (hasText) return { kind: 'responding' }

  const hasReasoning = parts.some((p) => isReasoningUIPart(p) && (p.text ?? '').length > 0)
  if (hasReasoning) return { kind: 'thinking' }

  return { kind: 'thinking' }
}

/** A signature of the last assistant message's content. Grows whenever the
 * model emits more text/reasoning or a tool part changes state — i.e. exactly
 * when "new content arrived". Drives the stall detector's lastContentChange. */
function contentSignature(status: ChatStatus, messages: UIMessage[]): string {
  const lastAssistant = [...messages].reverse().find((m) => m.role === 'assistant')
  const parts = lastAssistant?.parts ?? []
  let textLen = 0
  let reasoningLen = 0
  const toolStates: string[] = []
  for (const part of parts) {
    if (isTextUIPart(part)) textLen += part.text.length
    else if (isReasoningUIPart(part)) reasoningLen += (part.text ?? '').length
    else if (isToolUIPart(part)) toolStates.push((part as DynamicToolUIPart).state ?? '')
  }
  return `${status}|${messages.length}|${textLen}|${reasoningLen}|${toolStates.join(',')}`
}

export function StatusIndicator({
  status,
  messages,
}: {
  status: ChatStatus
  messages: UIMessage[]
}): React.ReactElement {
  const { t } = useI18n()

  // Turn start = mount (the indicator only mounts while isLoading is true, and
  // unmounts when it flips false, so mount/unmount == the turn boundary and the
  // elapsed counter resets per turn for free).
  const turnStart = useRef(Date.now())
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    // Tick at 500ms so the stall flips red close to the ~3s threshold (a 1s
    // cadence would only catch it at 4s); the elapsed counter still floors to
    // whole seconds, so the displayed number ticks once per second.
    const id = setInterval(() => setNow(Date.now()), 500)
    return () => clearInterval(id)
  }, [])

  const phase = derivePhase(status, messages)

  // Stall detector: track when content last grew; if no growth for >3s AND no
  // tool is in flight, surface the honest red "still waiting" affordance. A
  // running tool legitimately produces no chat content for a while, so it
  // suppresses the stall flag.
  const sig = contentSignature(status, messages)
  const lastContentChange = useRef(Date.now())
  const lastSig = useRef(sig)
  if (lastSig.current !== sig) {
    lastSig.current = sig
    lastContentChange.current = Date.now()
  }
  const toolRunning = phase.kind === 'tool'
  const stalled = !toolRunning && now - lastContentChange.current > STALL_MS

  const elapsed = Math.max(0, Math.floor((now - turnStart.current) / 1000))

  let label: string
  switch (phase.kind) {
    case 'requesting':
      label = t('chat.status.requesting')
      break
    case 'tool':
      label = t('chat.status.running', { tool: phase.toolName })
      break
    case 'responding':
      label = t('chat.status.responding')
      break
    case 'thinking':
    default:
      label = t('chat.thinking')
      break
  }

  return (
    <div data-testid="thinking-indicator" className="msg agent">
      <div className="msg-head">● FINROBOT</div>
      <div
        data-testid="status-line"
        data-phase={phase.kind}
        data-stalled={stalled ? 'true' : 'false'}
        className={`ai-status${stalled ? ' stalled' : ''}`}
      >
        <span className="ai-status-dot" aria-hidden="true" />
        <span className="ai-status-label">{stalled ? t('chat.status.stalled') : label}</span>
        <span className="ai-status-elapsed">{elapsed}s</span>
      </div>
    </div>
  )
}
