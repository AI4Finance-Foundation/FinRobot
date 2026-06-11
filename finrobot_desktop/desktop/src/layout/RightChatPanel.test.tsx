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
// Mock useChatSessions — the chat panel's session server-state. Tests drive
// the chat UI, not the sessions REST integration, so we control the hook's
// return and capture the callbacks (new / switch / delete) the panel wires.
// onSwitch is invoked so the panel's "clear input on session change" runs.
// ──────────────────────────────────────────────────────────────
import type { ChatSessionSummary } from '../hooks/useChatSessions'

interface MockSessionsControls {
  sessions: ChatSessionSummary[]
  activeSessionId: string
  seedMessages: UIMessage[] | undefined
  seedLoading: boolean
  deletingId: string | null
  onSwitch: (() => void) | undefined
  newSession: ReturnType<typeof vi.fn>
  switchSession: ReturnType<typeof vi.fn>
  deleteSession: ReturnType<typeof vi.fn>
}

const mockSessions: MockSessionsControls = {
  sessions: [],
  activeSessionId: 'sess-active',
  seedMessages: [],
  seedLoading: false,
  deletingId: null,
  onSwitch: undefined,
  newSession: vi.fn(),
  switchSession: vi.fn(),
  deleteSession: vi.fn(),
}

vi.mock('../hooks/useChatSessions', () => ({
  useChatSessions: (onSwitch?: () => void) => {
    mockSessions.onSwitch = onSwitch
    return {
      sessions: mockSessions.sessions,
      sessionsLoading: false,
      sessionsError: false,
      activeSessionId: mockSessions.activeSessionId,
      seedMessages: mockSessions.seedMessages,
      seedLoading: mockSessions.seedLoading,
      newSession: mockSessions.newSession,
      switchSession: mockSessions.switchSession,
      deleteSession: mockSessions.deleteSession,
      deletingId: mockSessions.deletingId,
    }
  },
}))

function makeSessionSummary(over: Partial<ChatSessionSummary> = {}): ChatSessionSummary {
  return {
    session_id: `s-${Math.random()}`,
    title: 'Untitled',
    created_at: new Date().toISOString(),
    last_active_at: new Date().toISOString(),
    turn_count: 1,
    model: 'anthropic:claude-sonnet-4-6',
    user_id: 'local',
    ticker: null,
    ...over,
  }
}

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

  mockSessions.sessions = []
  mockSessions.activeSessionId = 'sess-active'
  mockSessions.seedMessages = []
  mockSessions.seedLoading = false
  mockSessions.deletingId = null
  mockSessions.onSwitch = undefined
  mockSessions.newSession.mockReset()
  mockSessions.switchSession.mockReset()
  mockSessions.deleteSession.mockReset()
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
// Tests: StatusIndicator — REAL streaming status (phase + elapsed + stall),
// CC-aligned. Phase is derived from status + the last assistant message's
// parts; the elapsed counter and stall→red run on real timers.
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — status indicator (real phase)', () => {
  it("status==='submitted' reads Requesting (TTFT wait)", async () => {
    mockChatControls.setStatus('submitted')
    renderPanel()
    await waitFor(() => {
      const line = screen.getByTestId('status-line')
      expect(line).toHaveAttribute('data-phase', 'requesting')
    })
    expect(screen.getByTestId('status-line')).toHaveTextContent('Requesting…')
  })

  it('streaming with a running tool reads Running {tool}', async () => {
    mockChatControls.setStatus('streaming')
    mockChatControls.setMessages([
      makeToolCallMessage('call_run', 'run_dcf_valuation', 'input-available'),
    ])
    renderPanel()
    await waitFor(() => {
      const line = screen.getByTestId('status-line')
      expect(line).toHaveAttribute('data-phase', 'tool')
    })
    expect(screen.getByTestId('status-line')).toHaveTextContent('Running run_dcf_valuation…')
  })

  it('streaming with text present reads Responding', async () => {
    mockChatControls.setStatus('streaming')
    mockChatControls.setMessages([makeAssistantMessage('partial answer…')])
    renderPanel()
    await waitFor(() => {
      const line = screen.getByTestId('status-line')
      expect(line).toHaveAttribute('data-phase', 'responding')
    })
    expect(screen.getByTestId('status-line')).toHaveTextContent('Responding…')
  })

  it('streaming with only a reasoning part reads Thinking', async () => {
    mockChatControls.setStatus('streaming')
    mockChatControls.setMessages([
      {
        id: 'asst-reasoning',
        role: 'assistant',
        parts: [{ type: 'reasoning', text: 'weighing the comps…' } as UIMessage['parts'][0]],
      },
    ])
    renderPanel()
    await waitFor(() => {
      const line = screen.getByTestId('status-line')
      expect(line).toHaveAttribute('data-phase', 'thinking')
    })
    expect(screen.getByTestId('status-line')).toHaveTextContent('Thinking…')
  })

  it('renders a real elapsed-seconds counter that ticks', async () => {
    vi.useFakeTimers()
    try {
      mockChatControls.setStatus('streaming')
      mockChatControls.setMessages([makeAssistantMessage('partial…')])
      renderPanel()
      expect(screen.getByTestId('status-line')).toHaveTextContent('0s')
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2000)
      })
      expect(screen.getByTestId('status-line')).toHaveTextContent('2s')
    } finally {
      vi.useRealTimers()
    }
  })

  it('turns red (stalled) after >3s with no new content and no tool running', async () => {
    vi.useFakeTimers()
    try {
      mockChatControls.setStatus('streaming')
      mockChatControls.setMessages([makeAssistantMessage('stuck here')])
      renderPanel()
      const line = screen.getByTestId('status-line')
      expect(line).toHaveAttribute('data-stalled', 'false')
      // 4 interval ticks (now = baseline+4000) cross the 3000ms stall threshold.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(4200)
      })
      expect(screen.getByTestId('status-line')).toHaveAttribute('data-stalled', 'true')
      expect(screen.getByTestId('status-line')).toHaveTextContent('still waiting…')
    } finally {
      vi.useRealTimers()
    }
  })

  it('does NOT stall while a tool is running (long tool calls are legit)', async () => {
    vi.useFakeTimers()
    try {
      mockChatControls.setStatus('streaming')
      mockChatControls.setMessages([
        makeToolCallMessage('call_slow', 'run_equity_research', 'input-available'),
      ])
      renderPanel()
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000)
      })
      expect(screen.getByTestId('status-line')).toHaveAttribute('data-stalled', 'false')
    } finally {
      vi.useRealTimers()
    }
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
// must invalidate the SAME read model the REST run path refreshes so the
// workspace flips out of its stale snapshot. Key must mirror
// StockWorkspace exactly:
//   ['v5-artifacts-timeline', <TICKER>]
// and must fire ONCE per artifact_id (guarded by a Set ref).
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — AI artifact invalidation', () => {
  it('invalidates the artifact timeline once when a tool output has artifact_id', async () => {
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

    // Exactly one artifact key (no duplicate firing for one artifact).
    const artifactCalls = spy.mock.calls.filter(([arg]) => {
      const key = (arg as { queryKey?: unknown[] })?.queryKey
      return Array.isArray(key) && key[0] === 'v5-artifacts-timeline'
    })
    expect(artifactCalls).toHaveLength(1)
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

    // Let any effect flush, then assert the artifact key never fired.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0))
    })
    const artifactCalls = spy.mock.calls.filter(([arg]) => {
      const key = (arg as { queryKey?: unknown[] })?.queryKey
      return Array.isArray(key) && key[0] === 'v5-artifacts-timeline'
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

  it('[EP4] shows context-too-long message for a real provider overflow error', async () => {
    mockChatControls.setMessages([makeUserMessage('q')])
    mockChatControls.setError(new Error("This model's maximum context length is 8192 tokens"))
    renderPanel()
    await waitFor(() => {
      expect(screen.getByText(/Conversation too long/)).toBeInTheDocument()
    })
  })

  it('[EP4b] does NOT mislabel a 422 protocol error (echoes "context_bundle") as too-long', async () => {
    // Regression: the backend's 422 validation body echoes the request `input`,
    // which carries our `context_bundle` field. A bare substring match on
    // "context"/"token" misread that protocol/auth error as "Conversation too
    // long" — one short message, four 422 retries, all mislabeled.
    mockChatControls.setMessages([makeUserMessage('q')])
    mockChatControls.setError(
      new Error(
        '[{"type":"union_tag_not_found","msg":"Unable to extract tag using discriminator \'trigger\'","input":{"context_bundle":{"route":"/research"}}}]',
      ),
    )
    renderPanel()
    await waitFor(() => {
      expect(screen.getByTestId('error-banner')).toBeInTheDocument()
    })
    expect(screen.queryByText(/Conversation too long/)).not.toBeInTheDocument()
    expect(screen.getByText(/Request failed/)).toBeInTheDocument()
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

  it('clicking new session starts a fresh session (non-destructive — does not clear the list)', () => {
    renderPanel()
    fireEvent.click(screen.getByTestId('new-session-btn'))
    // The panel delegates to useChatSessions.newSession (mints a new id +
    // switches); it never deletes or overwrites existing sessions.
    expect(mockSessions.newSession).toHaveBeenCalledOnce()
    expect(mockSessions.deleteSession).not.toHaveBeenCalled()
  })

  it('switching session (onSwitch) clears the pending input', () => {
    renderPanel()
    const input = screen.getByTestId('chat-input') as HTMLTextAreaElement
    fireEvent.change(input, { target: { value: '之前的消息' } })
    // The panel hands useChatSessions an onSwitch that resets transient input;
    // invoking it (as a real new/switch would) must clear the box.
    act(() => {
      mockSessions.onSwitch?.()
    })
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
    expect(typeof bundle.route).toBe('string')
  })
})

// ──────────────────────────────────────────────────────────────
// Tests: history entry point (BUG-20260602-045)
// ──────────────────────────────────────────────────────────────

describe('RightChatPanel — sessions drawer (multi-session management)', () => {
  it('the header clock button opens the sessions drawer', () => {
    renderPanel()
    const btn = screen.getByTestId('history-btn')
    expect(btn).toBeInTheDocument()
    fireEvent.click(btn)
    expect(screen.getByTestId('sessions-drawer')).toBeInTheDocument()
  })

  it('shows an empty state when there are no sessions', () => {
    mockSessions.sessions = []
    renderPanel()
    fireEvent.click(screen.getByTestId('history-btn'))
    expect(screen.getByTestId('sessions-empty')).toBeInTheDocument()
  })

  it('lists sessions and highlights the active one', () => {
    mockSessions.activeSessionId = 'sess-b'
    mockSessions.sessions = [
      makeSessionSummary({ session_id: 'sess-a', title: 'AAPL deep dive', ticker: 'AAPL' }),
      makeSessionSummary({ session_id: 'sess-b', title: 'NVDA thesis', ticker: 'NVDA' }),
    ]
    renderPanel()
    fireEvent.click(screen.getByTestId('history-btn'))

    expect(screen.getByText('AAPL deep dive')).toBeInTheDocument()
    expect(screen.getByText('NVDA thesis')).toBeInTheDocument()

    const rows = screen.getAllByTestId('session-row')
    const activeRow = rows.find((r) => r.getAttribute('data-active') === 'true')
    expect(activeRow).toBeTruthy()
    expect(within(activeRow as HTMLElement).getByText('NVDA thesis')).toBeInTheDocument()
  })

  it('clicking a session row switches to it (resume) and closes the drawer', () => {
    mockSessions.sessions = [makeSessionSummary({ session_id: 'sess-a', title: 'AAPL deep dive' })]
    renderPanel()
    fireEvent.click(screen.getByTestId('history-btn'))
    fireEvent.click(screen.getByText('AAPL deep dive'))

    expect(mockSessions.switchSession).toHaveBeenCalledWith('sess-a')
    // Drawer closes after switching.
    expect(screen.queryByTestId('sessions-drawer')).not.toBeInTheDocument()
  })

  it('the in-drawer "New chat" button starts a new session and closes the drawer', () => {
    mockSessions.sessions = [makeSessionSummary({ title: 'old' })]
    renderPanel()
    fireEvent.click(screen.getByTestId('history-btn'))
    fireEvent.click(screen.getByTestId('sessions-new-btn'))

    expect(mockSessions.newSession).toHaveBeenCalledOnce()
    expect(screen.queryByTestId('sessions-drawer')).not.toBeInTheDocument()
  })

  it('delete requires a two-step inline confirm (no accidental delete)', () => {
    mockSessions.sessions = [makeSessionSummary({ session_id: 'sess-del', title: 'to delete' })]
    renderPanel()
    fireEvent.click(screen.getByTestId('history-btn'))

    // First click only reveals the confirm affordance — nothing deleted yet.
    fireEvent.click(screen.getByTestId('session-delete-btn'))
    expect(mockSessions.deleteSession).not.toHaveBeenCalled()
    expect(screen.getByTestId('session-confirm-delete')).toBeInTheDocument()

    // Confirm → delete fires with the right id.
    fireEvent.click(screen.getByTestId('session-confirm-delete'))
    expect(mockSessions.deleteSession).toHaveBeenCalledWith('sess-del')
  })

  it('cancelling the delete confirm does not delete', () => {
    mockSessions.sessions = [makeSessionSummary({ session_id: 'sess-keep', title: 'keep me' })]
    renderPanel()
    fireEvent.click(screen.getByTestId('history-btn'))
    fireEvent.click(screen.getByTestId('session-delete-btn'))
    fireEvent.click(screen.getByTestId('session-cancel-delete'))

    expect(mockSessions.deleteSession).not.toHaveBeenCalled()
    expect(screen.queryByTestId('session-confirm-delete')).not.toBeInTheDocument()
  })
})

describe('RightChatPanel — icon column menu', () => {
  it('shows context menu on right-click', () => {
    renderPanel({ expanded: false })
    const btn = screen.getByTestId('expand-btn')

    fireEvent.contextMenu(btn)

    expect(screen.getByTestId('icon-menu')).toBeInTheDocument()
  })

  it('does not show menu on pointer press', () => {
    renderPanel({ expanded: false })
    const btn = screen.getByTestId('expand-btn')
    fireEvent.pointerDown(btn)
    expect(screen.queryByTestId('icon-menu')).not.toBeInTheDocument()
  })
})
