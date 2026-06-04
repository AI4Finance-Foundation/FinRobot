/**
 * RightChatPanel tests
 *
 * useChat (v3 @ai-sdk/react) is mocked so tests run without a live server.
 * The mock exposes controls that individual tests can manipulate:
 *   mockChatControls.setMessages(msgs)
 *   mockChatControls.setStatus('streaming' | 'ready' | 'submitted' | 'error')
 *   mockChatControls.setError(new Error('...'))
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { UIMessage } from 'ai'

// ──────────────────────────────────────────────────────────────
// Mock @ai-sdk/react
// ──────────────────────────────────────────────────────────────

interface MockChatControls {
  messages: UIMessage[]
  status: 'ready' | 'submitted' | 'streaming' | 'error'
  error: Error | undefined
  setMessages: (m: UIMessage[]) => void
  setStatus: (s: 'ready' | 'submitted' | 'streaming' | 'error') => void
  setError: (e: Error | undefined) => void
  sendMessage: ReturnType<typeof vi.fn>
  stop: ReturnType<typeof vi.fn>
  regenerate: ReturnType<typeof vi.fn>
  clearError: ReturnType<typeof vi.fn>
}

const mockChatControls: MockChatControls = {
  messages: [],
  status: 'ready',
  error: undefined,
  setMessages(m) {
    this.messages = m
  },
  setStatus(s) {
    this.status = s
  },
  setError(e) {
    this.error = e
  },
  sendMessage: vi.fn(),
  stop: vi.fn(),
  regenerate: vi.fn(),
  clearError: vi.fn(),
}

vi.mock('@ai-sdk/react', () => ({
  useChat: vi.fn(() => ({
    id: 'session-test',
    messages: mockChatControls.messages,
    status: mockChatControls.status,
    error: mockChatControls.error,
    sendMessage: mockChatControls.sendMessage,
    stop: mockChatControls.stop,
    regenerate: mockChatControls.regenerate,
    clearError: mockChatControls.clearError,
    setMessages: vi.fn(),
  })),
}))

// Mock 'ai' module to export type guards used in the component.
// isToolUIPart in the real library returns true for BOTH:
//   - ToolUIPart (type = `tool-<name>`)
//   - DynamicToolUIPart (type = `dynamic-tool`)
// Capture the options the component passes to DefaultChatTransport so tests
// can assert the resolved request body (locale + context_bundle — BUG 038/048).
interface CapturedTransport {
  api?: string
  body?: unknown
}
const lastTransportOptions: { current: CapturedTransport | null } = { current: null }

vi.mock('ai', () => {
  const isTextUIPart = (p: { type: string }): boolean => p.type === 'text'
  const isToolUIPart = (p: { type: string }): boolean =>
    p.type === 'dynamic-tool' || p.type.startsWith('tool-')
  const isReasoningUIPart = (p: { type: string }): boolean => p.type === 'reasoning'
  return {
    DefaultChatTransport: class {
      constructor(opts: CapturedTransport) {
        lastTransportOptions.current = opts
      }
    },
    isTextUIPart,
    isToolUIPart,
    isReasoningUIPart,
  }
})

// Mock toastStore
const mockAddToast = vi.fn()
vi.mock('../stores/toastStore', () => ({
  useToastStore: (selector: (s: { addToast: typeof mockAddToast }) => unknown) =>
    selector({ addToast: mockAddToast }),
}))

// ──────────────────────────────────────────────────────────────
// Helpers
// ──────────────────────────────────────────────────────────────

import { RightChatPanel } from './RightChatPanel'

interface RenderOptions {
  expanded?: boolean
  ticker?: string
}

// The model badge reads settings.model_name via the shared ['settings'] query.
// Seed it with a configured model that differs from the old prototype default
// so the test proves the badge reflects the REAL configured model, not a
// hardcoded 'deepseek'. staleTime: Infinity keeps the seeded value (no refetch
// against a non-existent server in jsdom).
const SEEDED_MODEL_NAME = 'anthropic:claude-sonnet-4-6'

function makeSeededClient(): QueryClient {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  // Mirror /api/settings: model_name + the provider registry the badge derives
  // its label from (single source of truth — no hardcoded label map).
  queryClient.setQueryData(['settings'], {
    model_name: SEEDED_MODEL_NAME,
    providers: [
      {
        id: 'anthropic',
        label: 'Anthropic',
        kind: 'anthropic',
        base_url: null,
        models: ['claude-sonnet-4-6'],
        key_set: true,
        is_builtin: true,
      },
    ],
  })
  return queryClient
}

function renderPanel(opts: RenderOptions = {}) {
  const { expanded = true, ticker } = opts
  const onToggle = vi.fn()

  const initialPath = ticker ? `/stocks/${ticker}` : '/stocks'

  return render(
    <QueryClientProvider client={makeSeededClient()}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route
            path="/stocks/:ticker"
            element={<RightChatPanel expanded={expanded} onToggle={onToggle} />}
          />
          <Route
            path="/stocks"
            element={<RightChatPanel expanded={expanded} onToggle={onToggle} />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

// Render against a caller-supplied QueryClient so a test can spy on
// invalidateQueries. Mirrors renderPanel's provider/router shape.
function renderPanelWithClient(client: QueryClient, opts: RenderOptions = {}) {
  const { expanded = true, ticker } = opts
  const onToggle = vi.fn()
  const initialPath = ticker ? `/stocks/${ticker}` : '/stocks'

  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route
            path="/stocks/:ticker"
            element={<RightChatPanel expanded={expanded} onToggle={onToggle} />}
          />
          <Route
            path="/stocks"
            element={<RightChatPanel expanded={expanded} onToggle={onToggle} />}
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function makeUserMessage(text: string): UIMessage {
  return {
    id: `user-${Math.random()}`,
    role: 'user',
    parts: [{ type: 'text', text }],
  }
}

function makeAssistantMessage(text: string): UIMessage {
  return {
    id: `asst-${Math.random()}`,
    role: 'assistant',
    parts: [{ type: 'text', text }],
  }
}

function makeToolCallMessage(
  toolCallId: string,
  toolName: string,
  state: 'input-available' | 'output-available' | 'output-error',
  output?: { summary: string; artifact_id?: string; ticker?: string },
  errorText?: string,
): UIMessage {
  const basePart = {
    type: 'dynamic-tool' as const,
    toolName,
    toolCallId,
    input: { ticker: 'AAPL' },
  }

  let fullPart: Record<string, unknown>
  if (state === 'output-available') {
    fullPart = { ...basePart, state, output: output ?? { summary: 'done' } }
  } else if (state === 'output-error') {
    fullPart = { ...basePart, state, errorText: errorText ?? '失败' }
  } else {
    fullPart = { ...basePart, state }
  }

  return {
    id: `tool-${Math.random()}`,
    role: 'assistant',
    parts: [fullPart as UIMessage['parts'][0]],
  }
}

// ──────────────────────────────────────────────────────────────
// Reset state before each test
// ──────────────────────────────────────────────────────────────

beforeEach(() => {
  mockChatControls.messages = []
  mockChatControls.status = 'ready'
  mockChatControls.error = undefined
  mockChatControls.sendMessage.mockReset()
  mockChatControls.stop.mockReset()
  mockChatControls.regenerate.mockReset()
  mockChatControls.clearError.mockReset()
  mockAddToast.mockReset()
})

afterEach(() => {
  vi.clearAllMocks()
})

// ──────────────────────────────────────────────────────────────
// Tests: collapse / expand
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — collapse / expand', () => {
  it('renders expanded panel when expanded=true', () => {
    renderPanel({ expanded: true })
    expect(screen.getByTestId('right-chat-panel')).toBeInTheDocument()
    expect(screen.queryByTestId('icon-column')).not.toBeInTheDocument()
  })

  it('renders icon-column when expanded=false', () => {
    renderPanel({ expanded: false })
    expect(screen.getByTestId('icon-column')).toBeInTheDocument()
    expect(screen.queryByTestId('right-chat-panel')).not.toBeInTheDocument()
  })

  it('calls onToggle when collapse button clicked', () => {
    const onToggle = vi.fn()
    render(
      <QueryClientProvider client={makeSeededClient()}>
        <MemoryRouter>
          <Routes>
            <Route path="/" element={<RightChatPanel expanded onToggle={onToggle} />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    fireEvent.click(screen.getByTestId('collapse-btn'))
    expect(onToggle).toHaveBeenCalledOnce()
  })

  it('calls onToggle when expand button in icon-column is clicked', () => {
    const onToggle = vi.fn()
    render(
      <QueryClientProvider client={makeSeededClient()}>
        <MemoryRouter>
          <Routes>
            <Route path="/" element={<RightChatPanel expanded={false} onToggle={onToggle} />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )
    fireEvent.click(screen.getByTestId('expand-btn'))
    expect(onToggle).toHaveBeenCalledOnce()
  })
})

// ──────────────────────────────────────────────────────────────
// Tests: unread badge
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — unread badge', () => {
  it('shows no badge when no messages', () => {
    renderPanel({ expanded: false })
    expect(screen.queryByTestId('unread-badge')).not.toBeInTheDocument()
  })

  it('shows badge when assistant messages arrive while collapsed', async () => {
    const onToggle = vi.fn()

    const client = makeSeededClient()
    const { rerender } = render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Routes>
            <Route path="/" element={<RightChatPanel expanded={false} onToggle={onToggle} />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    // Simulate assistant message arriving while collapsed
    await act(async () => {
      mockChatControls.setMessages([makeAssistantMessage('Hello')])
    })

    rerender(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <Routes>
            <Route path="/" element={<RightChatPanel expanded={false} onToggle={onToggle} />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(screen.getByTestId('unread-badge')).toBeInTheDocument()
    })
  })
})

// ──────────────────────────────────────────────────────────────
// Tests: sending messages
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — sending messages', () => {
  it('calls sendMessage with text on send button click', () => {
    renderPanel()
    const input = screen.getByTestId('chat-input')
    fireEvent.change(input, { target: { value: 'AAPL DCF 估值' } })
    fireEvent.click(screen.getByTestId('send-btn'))
    expect(mockChatControls.sendMessage).toHaveBeenCalledWith({ text: 'AAPL DCF 估值' })
  })

  it('sends on Enter', () => {
    renderPanel()
    const input = screen.getByTestId('chat-input')
    fireEvent.change(input, { target: { value: '问题' } })
    fireEvent.keyDown(input, { key: 'Enter' })
    expect(mockChatControls.sendMessage).toHaveBeenCalled()
  })

  it('does NOT send on Shift+Enter (newline)', () => {
    renderPanel()
    const input = screen.getByTestId('chat-input')
    fireEvent.change(input, { target: { value: '问题' } })
    fireEvent.keyDown(input, { key: 'Enter', shiftKey: true })
    expect(mockChatControls.sendMessage).not.toHaveBeenCalled()
  })

  it('does not send empty message', () => {
    renderPanel()
    fireEvent.click(screen.getByTestId('send-btn'))
    expect(mockChatControls.sendMessage).not.toHaveBeenCalled()
  })

  it('send button is disabled for empty input', () => {
    renderPanel()
    // The button is present but has cursor:not-allowed / opacity style
    const btn = screen.getByTestId('send-btn')
    // disabled prop
    expect(btn).toBeDisabled()
  })

  it('does not send when message is over 20000 chars', () => {
    renderPanel()
    const input = screen.getByTestId('chat-input')
    fireEvent.change(input, { target: { value: 'a'.repeat(20001) } })
    const btn = screen.queryByTestId('send-btn')
    if (btn) {
      fireEvent.click(btn)
    }
    expect(mockChatControls.sendMessage).not.toHaveBeenCalled()
  })

  it('shows overlength warning for >20000 chars', () => {
    renderPanel()
    const input = screen.getByTestId('chat-input')
    fireEvent.change(input, { target: { value: 'a'.repeat(20001) } })
    expect(screen.getByTestId('overlength-warning')).toBeInTheDocument()
  })

  it('clears input after send', () => {
    renderPanel()
    const input = screen.getByTestId('chat-input') as HTMLTextAreaElement
    fireEvent.change(input, { target: { value: '你好' } })
    fireEvent.click(screen.getByTestId('send-btn'))
    expect(input.value).toBe('')
  })
})

// ──────────────────────────────────────────────────────────────
// Tests: loading state (stop button)
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — loading / stop', () => {
  it('shows stop button when streaming', async () => {
    mockChatControls.setStatus('streaming')
    renderPanel()
    await waitFor(() => {
      expect(screen.getByTestId('stop-btn')).toBeInTheDocument()
    })
    expect(screen.queryByTestId('send-btn')).not.toBeInTheDocument()
  })

  it('calls stop when stop button clicked', async () => {
    mockChatControls.setStatus('streaming')
    renderPanel()
    await waitFor(() => {
      expect(screen.getByTestId('stop-btn')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByTestId('stop-btn'))
    expect(mockChatControls.stop).toHaveBeenCalledOnce()
  })

  it('shows thinking indicator while loading', async () => {
    mockChatControls.setStatus('streaming')
    renderPanel()
    await waitFor(() => {
      expect(screen.getByTestId('thinking-indicator')).toBeInTheDocument()
    })
  })
})

// ──────────────────────────────────────────────────────────────
// Tests: streaming text rendering
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — message rendering', () => {
  it('renders user message on the right', async () => {
    mockChatControls.setMessages([makeUserMessage('AAPL 分析')])
    renderPanel()
    await waitFor(() => {
      expect(screen.getAllByTestId('message-user').length).toBeGreaterThan(0)
    })
    expect(screen.getByText('AAPL 分析')).toBeInTheDocument()
  })

  it('renders assistant message', async () => {
    mockChatControls.setMessages([makeAssistantMessage('根据 DCF 分析...')])
    renderPanel()
    await waitFor(() => {
      expect(screen.getAllByTestId('message-assistant').length).toBeGreaterThan(0)
    })
    expect(screen.getByText('根据 DCF 分析...')).toBeInTheDocument()
  })

  it('renders streamed text incrementally (text-part present)', async () => {
    mockChatControls.setMessages([makeAssistantMessage('流式文本')])
    renderPanel()
    await waitFor(() => {
      expect(screen.getByTestId('text-part')).toBeInTheDocument()
    })
  })

  it('shows empty state when no messages', () => {
    renderPanel()
    expect(screen.getByTestId('empty-state')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────
// Tests: tool call state machine
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — tool card state machine', () => {
  it('renders tool card for dynamic-tool part in running state', async () => {
    mockChatControls.setMessages([
      makeToolCallMessage('call_001', 'run_dcf_valuation', 'input-available'),
    ])
    renderPanel()
    await waitFor(() => {
      const card = screen.getByTestId('tool-card')
      expect(card).toHaveAttribute('data-state', 'running')
    })
  })

  it('renders tool card with complete state and Code-Computed badge', async () => {
    mockChatControls.setMessages([
      makeToolCallMessage('call_002', 'run_dcf_valuation', 'output-available', {
        summary: 'DCF: $198-$224',
        artifact_id: 'art_001',
        ticker: 'AAPL',
      }),
    ])
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText(/Code-Computed/)).toBeInTheDocument()
    })
  })

  it('renders artifact link from tool result', async () => {
    mockChatControls.setMessages([
      makeToolCallMessage('call_003', 'run_dcf_valuation', 'output-available', {
        summary: 'done',
        artifact_id: 'art_002',
        ticker: 'AAPL',
      }),
    ])
    renderPanel()
    await waitFor(() => {
      const link = screen.getByTestId('artifact-link')
      expect(link).toHaveAttribute('href', '/stocks/AAPL/runs/art_002')
    })
  })

  it('renders error state for failed tool call', async () => {
    mockChatControls.setMessages([
      makeToolCallMessage('call_004', 'run_dcf_valuation', 'output-error', undefined, '数据不可用'),
    ])
    renderPanel()
    await waitFor(() => {
      const card = screen.getByTestId('tool-card')
      expect(card).toHaveAttribute('data-state', 'error')
    })
    expect(screen.getByText('数据不可用')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────
// Tests: AI-generated artifact → query invalidation (BUG-20260602-037)
//
// When a tool output carrying artifact_id arrives in the chat, the panel
// must invalidate the SAME read models the REST run path refreshes so the
// workspace/dashboard flip out of their stale snapshot. Keys must mirror
// StockWorkspace exactly:
//   ['v5-artifacts-timeline', <TICKER>], ['studied-tickers'], ['dashboard']
// and must fire ONCE per artifact_id (guarded by a Set ref).
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — AI artifact invalidation', () => {
  it('invalidates timeline/studied/dashboard once when a tool output has artifact_id', async () => {
    const client = makeSeededClient()
    const spy = vi.spyOn(client, 'invalidateQueries')

    mockChatControls.setMessages([
      makeToolCallMessage('call_inv', 'run_dcf_valuation', 'output-available', {
        summary: 'DCF done',
        artifact_id: 'art_inv_1',
        ticker: 'aapl',
      }),
    ])
    renderPanelWithClient(client, { ticker: 'AAPL' })

    await waitFor(() => {
      expect(spy).toHaveBeenCalledWith({ queryKey: ['v5-artifacts-timeline', 'AAPL'] })
    })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['studied-tickers'] })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['dashboard'] })

    // Exactly the three artifact keys (no duplicate firing for one artifact).
    const artifactCalls = spy.mock.calls.filter(([arg]) => {
      const key = (arg as { queryKey?: unknown[] })?.queryKey
      return (
        Array.isArray(key) &&
        (key[0] === 'v5-artifacts-timeline' ||
          key[0] === 'studied-tickers' ||
          key[0] === 'dashboard')
      )
    })
    expect(artifactCalls).toHaveLength(3)
  })

  it('does NOT invalidate when a tool output has no artifact_id', async () => {
    const client = makeSeededClient()
    const spy = vi.spyOn(client, 'invalidateQueries')

    mockChatControls.setMessages([
      makeToolCallMessage('call_noart', 'run_dcf_valuation', 'output-available', {
        summary: 'no artifact produced',
      }),
    ])
    renderPanelWithClient(client, { ticker: 'AAPL' })

    // Let any effect flush, then assert none of the artifact keys fired.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
    const artifactCalls = spy.mock.calls.filter(([arg]) => {
      const key = (arg as { queryKey?: unknown[] })?.queryKey
      return (
        Array.isArray(key) &&
        (key[0] === 'v5-artifacts-timeline' ||
          key[0] === 'studied-tickers' ||
          key[0] === 'dashboard')
      )
    })
    expect(artifactCalls).toHaveLength(0)
  })
})

// ──────────────────────────────────────────────────────────────
// Tests: error paths (exception paths 1-15 from spec)
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — exception paths', () => {
  it('[EP1] shows error banner and reload button on network error', async () => {
    mockChatControls.setMessages([makeUserMessage('hello'), makeAssistantMessage('partial')])
    mockChatControls.setError(new Error('Network failure'))
    renderPanel()
    await waitFor(() => {
      expect(screen.getByTestId('error-banner')).toBeInTheDocument()
      expect(screen.getByTestId('reload-btn')).toBeInTheDocument()
    })
  })

  it('[EP2] calls regenerate when reload button clicked', async () => {
    mockChatControls.setMessages([makeUserMessage('q'), makeAssistantMessage('a')])
    mockChatControls.setError(new Error('503'))
    renderPanel()
    await waitFor(() => screen.getByTestId('reload-btn'))
    fireEvent.click(screen.getByTestId('reload-btn'))
    expect(mockChatControls.regenerate).toHaveBeenCalledOnce()
  })

  it('[EP3] tool card renders error state for failed tool call', async () => {
    mockChatControls.setMessages([
      makeToolCallMessage('x', 'run_lbo', 'output-error', undefined, '工具调用失败'),
    ])
    renderPanel()
    await waitFor(() => {
      const card = screen.getByTestId('tool-card')
      expect(card).toHaveAttribute('data-state', 'error')
    })
  })

  it('[EP4] shows context-too-long message when error contains "token"', async () => {
    mockChatControls.setMessages([makeUserMessage('q')])
    mockChatControls.setError(new Error('token limit exceeded'))
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText(/Conversation too long/)).toBeInTheDocument()
    })
  })

  it('[EP5] send button disabled for empty message', () => {
    renderPanel()
    const btn = screen.getByTestId('send-btn')
    expect(btn).toBeDisabled()
  })

  it('[EP6] overlength warning shown for >20000 char input', () => {
    renderPanel()
    fireEvent.change(screen.getByTestId('chat-input'), {
      target: { value: 'x'.repeat(20001) },
    })
    expect(screen.getByTestId('overlength-warning')).toBeInTheDocument()
  })

  it('[EP9] multiple tool calls render independently', async () => {
    mockChatControls.setMessages([
      {
        id: 'multi',
        role: 'assistant',
        parts: [
          {
            type: 'dynamic-tool',
            toolName: 'run_dcf_valuation',
            toolCallId: 'c1',
            state: 'input-available',
            input: { ticker: 'AAPL' },
          },
          {
            type: 'dynamic-tool',
            toolName: 'run_lbo_analysis',
            toolCallId: 'c2',
            state: 'output-available',
            input: { ticker: 'AAPL' },
            output: { summary: 'LBO done' },
          },
        ],
      } as UIMessage,
    ])
    renderPanel()
    await waitFor(() => {
      const cards = screen.getAllByTestId('tool-card')
      expect(cards.length).toBe(2)
      expect(cards[0]).toHaveAttribute('data-state', 'running')
      expect(cards[1]).toHaveAttribute('data-state', 'complete')
    })
  })

  it('[EP12] stop button calls stop()', async () => {
    mockChatControls.setStatus('streaming')
    renderPanel()
    await waitFor(() => screen.getByTestId('stop-btn'))
    fireEvent.click(screen.getByTestId('stop-btn'))
    expect(mockChatControls.stop).toHaveBeenCalledOnce()
  })

  it('[EP13] reload calls regenerate not sendMessage', async () => {
    mockChatControls.setMessages([makeUserMessage('q'), makeAssistantMessage('a')])
    mockChatControls.setError(new Error('failed'))
    renderPanel()
    await waitFor(() => screen.getByTestId('reload-btn'))
    fireEvent.click(screen.getByTestId('reload-btn'))
    expect(mockChatControls.regenerate).toHaveBeenCalledOnce()
    expect(mockChatControls.sendMessage).not.toHaveBeenCalled()
  })
})

// ──────────────────────────────────────────────────────────────
// Tests: model selector
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — model selector', () => {
  it('renders model selector in header', () => {
    renderPanel()
    expect(screen.getByTestId('model-selector')).toBeInTheDocument()
  })

  it('model badge reflects the configured model_name from settings', () => {
    renderPanel()
    const badge = screen.getByTestId('model-selector')
    // Badge derives its label from the provider registry ("<label> · <model>"),
    // proving it reads the real configured model, not a hardcoded default.
    expect(badge.textContent).toBe('Anthropic · claude-sonnet-4-6')
  })

  it('model badge is read-only (configured via Settings)', () => {
    renderPanel()
    const badge = screen.getByTestId('model-selector')
    // Verify it's a span (read-only), not a select
    expect(badge.tagName).toBe('SPAN')
    expect(badge).toHaveAttribute('title', 'Model is configured in Settings')
  })
})

// ──────────────────────────────────────────────────────────────
// Tests: new session button
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — new session', () => {
  it('new session button is rendered', () => {
    renderPanel()
    expect(screen.getByTestId('new-session-btn')).toBeInTheDocument()
  })

  it('clicking new session clears input', () => {
    renderPanel()
    const input = screen.getByTestId('chat-input') as HTMLTextAreaElement
    fireEvent.change(input, { target: { value: '之前的消息' } })
    fireEvent.click(screen.getByTestId('new-session-btn'))
    expect(input.value).toBe('')
  })
})

// ──────────────────────────────────────────────────────────────
// Tests: panel header — ticker display
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — panel header', () => {
  it('shows ticker in header when ticker is in URL', () => {
    renderPanel({ ticker: 'AAPL' })
    const header = screen.getByTestId('panel-header')
    expect(header).toBeInTheDocument()
    // Scope to the header: the route-derived ContextBar chip also renders
    // "AAPL", so a global getByText would match multiple nodes.
    expect(within(header).getByText('AAPL')).toBeInTheDocument()
  })

  it('shows "探索" when no ticker', () => {
    renderPanel()
    expect(screen.getByText('Explore')).toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────
// Tests: icon column long-press menu
// ──────────────────────────────────────────────────────────────

// ──────────────────────────────────────────────────────────────
// Tests: chat transport body carries locale + context_bundle
// (BUG-20260602-038 / 048)
// ──────────────────────────────────────────────────────────────

import { useUiStore } from '../stores/uiStore'
import { useUiPrefs } from '../i18n'

describe('RightChatPanel — transport body context (038/048)', () => {
  it('body thunk includes locale and a structured context_bundle', () => {
    useUiPrefs.setState({ locale: 'zh' })
    renderPanel({ ticker: 'AAPL' })

    const opts = lastTransportOptions.current
    expect(opts).not.toBeNull()
    // The component passes a thunk (resolved per-send), not a static object.
    expect(typeof opts?.body).toBe('function')
    const body = (opts?.body as () => Record<string, unknown>)()

    expect(body.locale).toBe('zh')
    expect(body.ticker).toBe('AAPL')
    expect(body.context_bundle).toBeTruthy()
    const bundle = body.context_bundle as Record<string, unknown>
    expect(bundle.ticker).toBe('AAPL')
    expect(Array.isArray(bundle.pinned)).toBe(true)
    expect(typeof bundle.route).toBe('string')
  })

  it('context_bundle carries pinned items from the uiStore', () => {
    useUiPrefs.setState({ locale: 'en' })
    useUiStore.getState().addPinned({ kind: 'report', id: 'art_42', label: 'NVDA DCF' })
    renderPanel({ ticker: 'NVDA' })

    const body = (lastTransportOptions.current?.body as () => Record<string, unknown>)()
    const bundle = body.context_bundle as { pinned: Array<{ id: string; label: string }> }
    expect(bundle.pinned.some((p) => p.id === 'art_42' && p.label === 'NVDA DCF')).toBe(true)

    // cleanup so other tests start from a clean pinned list
    useUiStore.getState().removePinned('art_42')
  })
})

// ──────────────────────────────────────────────────────────────
// Tests: suggestion chips are honest — no chip implies a tool the lead
// agent does not have (BUG-20260602-046)
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — honest suggestion chips (046)', () => {
  it('ticker workspace drops Monte Carlo / 10-K Q&A chips (no backing tool)', () => {
    renderPanel({ ticker: 'AAPL' })
    const chips = screen.getByTestId('suggestion-chips')
    // Kept: dcf / peers (run_* tools exist)
    expect(within(chips).getByText('Explain DCF assumptions')).toBeInTheDocument()
    // Removed: no monte-carlo / 10-K-QA tool registered on /chat
    expect(within(chips).queryByText('Monte Carlo simulation')).not.toBeInTheDocument()
    expect(within(chips).queryByText('10-K Q&A')).not.toBeInTheDocument()
  })
})

// ──────────────────────────────────────────────────────────────
// Tests: history entry point (BUG-20260602-045)
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — history entry point (045)', () => {
  it('renders a history button that opens the history drawer', () => {
    renderPanel()
    const btn = screen.getByTestId('history-btn')
    expect(btn).toBeInTheDocument()
    fireEvent.click(btn)
    expect(screen.getByTestId('history-drawer')).toBeInTheDocument()
  })
})

describe('RightChatPanel — icon column menu', () => {
  it('shows context menu after long press', async () => {
    renderPanel({ expanded: false })
    const btn = screen.getByTestId('expand-btn')

    // Simulate long press (pointerDown without pointerUp for 600ms)
    fireEvent.pointerDown(btn)
    await act(async () => {
      await new Promise((r) => setTimeout(r, 650))
    })

    await waitFor(() => {
      expect(screen.getByTestId('icon-menu')).toBeInTheDocument()
    })
  })

  it('does not show menu on short press (immediate pointerUp)', () => {
    renderPanel({ expanded: false })
    const btn = screen.getByTestId('expand-btn')
    fireEvent.pointerDown(btn)
    fireEvent.pointerUp(btn)
    expect(screen.queryByTestId('icon-menu')).not.toBeInTheDocument()
  })
})
