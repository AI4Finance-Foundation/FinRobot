// transcriptReplay tests — the transcript → UIMessage mapping is the contract
// that lets a past session resume. Event shapes mirror
// finrobot/audit/transcript.py (do NOT drift from it).

import { describe, it, expect } from 'vitest'
import {
  reconstructMessages,
  INTERRUPTED_TOOL_TEXT,
  type TranscriptEvent,
} from './transcriptReplay'
import type { DynamicToolUIPart } from 'ai'

function evt(
  event: string,
  data: Record<string, unknown>,
  timestamp = '2026-06-08T00:00:00Z',
): TranscriptEvent {
  return { timestamp, session_id: 's1', event, data }
}

describe('reconstructMessages', () => {
  it('returns no messages for an empty / metadata-only transcript', () => {
    expect(reconstructMessages([])).toEqual([])
    expect(
      reconstructMessages([
        evt('session_start', { user_id: 'local', model: 'anthropic:claude' }),
        evt('context', { context_bundle: { route: '/stocks', ticker: 'AAPL' } }),
        evt('session_end', {}),
      ]),
    ).toEqual([])
  })

  it('maps user_msg → a user message with a text part', () => {
    const out = reconstructMessages([evt('user_msg', { text: 'Hello AAPL' })])
    expect(out).toHaveLength(1)
    expect(out[0].role).toBe('user')
    expect(out[0].parts).toEqual([{ type: 'text', text: 'Hello AAPL' }])
  })

  it('maps assistant_text → an assistant message with a text part', () => {
    const out = reconstructMessages([
      evt('user_msg', { text: 'hi' }),
      evt('assistant_text', { text: 'Hello, how can I help?' }),
    ])
    expect(out).toHaveLength(2)
    expect(out[1].role).toBe('assistant')
    expect(out[1].parts).toEqual([{ type: 'text', text: 'Hello, how can I help?' }])
  })

  it('coalesces consecutive assistant events (text + tool) into ONE assistant message', () => {
    const out = reconstructMessages([
      evt('user_msg', { text: 'value AAPL' }),
      evt('assistant_text', { text: 'Let me run a DCF.' }),
      evt('tool_call', {
        tool_name: 'run_dcf_valuation',
        tool_use_id: 'tc1',
        args: { ticker: 'AAPL' },
      }),
      evt('tool_result', {
        tool_use_id: 'tc1',
        tool_name: 'run_dcf_valuation',
        result: { summary: 'DCF: $198–$224', ticker: 'AAPL' },
        is_error: false,
        artifact_id: 'art_1',
      }),
      evt('assistant_text', { text: 'The fair value range is $198–$224.' }),
    ])

    // user + ONE assistant bubble holding [text, tool, text]
    expect(out).toHaveLength(2)
    const asst = out[1]
    expect(asst.role).toBe('assistant')
    expect(asst.parts).toHaveLength(3)
    expect(asst.parts[0]).toEqual({ type: 'text', text: 'Let me run a DCF.' })
    expect(asst.parts[2]).toEqual({ type: 'text', text: 'The fair value range is $198–$224.' })

    const tool = asst.parts[1] as DynamicToolUIPart
    expect(tool.type).toBe('dynamic-tool')
    expect(tool.toolName).toBe('run_dcf_valuation')
    expect(tool.toolCallId).toBe('tc1')
    expect(tool.state).toBe('output-available')
    expect(tool.input).toEqual({ ticker: 'AAPL' })
    if (tool.state === 'output-available') {
      expect(tool.output).toMatchObject({
        summary: 'DCF: $198–$224',
        artifact_id: 'art_1',
        ticker: 'AAPL',
      })
    }
  })

  it('a new user_msg closes the prior assistant message (new turn = new bubble)', () => {
    const out = reconstructMessages([
      evt('user_msg', { text: 'q1' }),
      evt('assistant_text', { text: 'a1' }),
      evt('user_msg', { text: 'q2' }),
      evt('assistant_text', { text: 'a2' }),
    ])
    expect(out.map((m) => m.role)).toEqual(['user', 'assistant', 'user', 'assistant'])
    expect(out[1].parts).toEqual([{ type: 'text', text: 'a1' }])
    expect(out[3].parts).toEqual([{ type: 'text', text: 'a2' }])
  })

  it('maps a failed tool_result → output-error with the message', () => {
    const out = reconstructMessages([
      evt('tool_call', { tool_name: 'run_lbo', tool_use_id: 'tcE', args: {} }),
      evt('tool_result', {
        tool_use_id: 'tcE',
        tool_name: 'run_lbo',
        result: null,
        is_error: true,
        message: 'data unavailable',
      }),
    ])
    const tool = out[0].parts[0] as DynamicToolUIPart
    expect(tool.state).toBe('output-error')
    if (tool.state === 'output-error') expect(tool.errorText).toBe('data unavailable')
  })

  it('finalizes a tool_call with no matching tool_result as output-error (interrupted, not a live spinner)', () => {
    // A replayed transcript is historical — nothing is live-streaming into it,
    // so a dangling tool_call (its result line never written = the turn was cut
    // off mid-stream) must NOT come back as `input-available`, which the UI
    // renders as a perpetual spinner. It is a terminal, interrupted step.
    const out = reconstructMessages([
      evt('tool_call', { tool_name: 'run_comps', tool_use_id: 'tcX', args: { ticker: 'KO' } }),
    ])
    const tool = out[0].parts[0] as DynamicToolUIPart
    expect(tool.state).toBe('output-error')
    expect(tool.input).toEqual({ ticker: 'KO' })
    if (tool.state === 'output-error') expect(tool.errorText).toBe(INTERRUPTED_TOOL_TEXT)
  })

  it('finalizes a dangling tool_call inside a coalesced turn (text before it stays intact)', () => {
    const out = reconstructMessages([
      evt('user_msg', { text: 'analyze AAPL' }),
      evt('assistant_text', { text: 'Running equity research…' }),
      evt('tool_call', {
        tool_name: 'run_equity_research',
        tool_use_id: 'tcRun',
        args: { ticker: 'AAPL' },
      }),
      // no tool_result — the user closed the panel mid-run
    ])
    expect(out).toHaveLength(2)
    const asst = out[1]
    expect(asst.parts[0]).toEqual({ type: 'text', text: 'Running equity research…' })
    const tool = asst.parts[1] as DynamicToolUIPart
    expect(tool.state).toBe('output-error')
    if (tool.state === 'output-error') expect(tool.errorText).toBe(INTERRUPTED_TOOL_TEXT)
  })

  it('surfaces an error event as an inline assistant note (history stays honest)', () => {
    const out = reconstructMessages([
      evt('user_msg', { text: 'go' }),
      evt('error', { exception_class: 'ProviderError', message: 'upstream 503', context: {} }),
    ])
    expect(out).toHaveLength(2)
    expect(out[1].role).toBe('assistant')
    expect(out[1].parts[0]).toEqual({ type: 'text', text: '⚠ upstream 503' })
  })

  it('falls back to a JSON preview when a tool result has no summary', () => {
    const out = reconstructMessages([
      evt('tool_call', { tool_name: 'fetch_quote', tool_use_id: 't', args: {} }),
      evt('tool_result', {
        tool_use_id: 't',
        tool_name: 'fetch_quote',
        result: { price: 196.4, currency: 'USD' },
        is_error: false,
      }),
    ])
    const tool = out[0].parts[0] as DynamicToolUIPart
    if (tool.state === 'output-available') {
      const output = tool.output as { summary: string }
      expect(output.summary).toContain('196.4')
    }
  })

  it('carries the event timestamp in metadata.createdAt for honest times', () => {
    // metadata (not a root field) — a root extra is rejected by the backend's
    // strict UIMessage schema and 422s the next send in a resumed session.
    const out = reconstructMessages([evt('user_msg', { text: 'hi' }, '2026-06-08T12:34:00Z')])
    expect((out[0] as { metadata?: { createdAt?: string } }).metadata?.createdAt).toBe(
      '2026-06-08T12:34:00Z',
    )
    // No off-spec root field leaks onto the wire.
    expect('createdAt' in out[0]).toBe(false)
  })
})
