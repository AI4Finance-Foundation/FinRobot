import { useState, useCallback, useRef, useEffect } from 'react'
import { useAppStore } from '../stores/appStore'
import { BASE_URL } from '../api/client'

interface Citation {
  source: string
  text: string
  relevance: number
}

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  loading?: boolean
}

export default function AskPanel() {
  const { ticker, askPanelOpen, setAskPanelOpen } = useAppStore()
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Focus input when panel opens
  useEffect(() => {
    if (askPanelOpen) {
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [askPanelOpen])

  // Reset messages when ticker changes
  useEffect(() => {
    setMessages([])
  }, [ticker])

  const handleSubmit = useCallback(async () => {
    if (!input.trim() || !ticker || isLoading) return

    const userMsg: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
    }

    const loadingMsg: Message = {
      id: `loading-${Date.now()}`,
      role: 'assistant',
      content: '',
      loading: true,
    }

    setMessages((prev) => [...prev, userMsg, loadingMsg])
    setInput('')
    setIsLoading(true)

    try {
      const resp = await fetch(`${BASE_URL}/api/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, question: input.trim() }),
      })

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: 'Request failed' }))
        throw new Error(err.detail || `HTTP ${resp.status}`)
      }

      const data = await resp.json()

      const assistantMsg: Message = {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: data.answer,
        citations: data.citations || [],
      }

      setMessages((prev) => prev.filter((m) => !m.loading).concat(assistantMsg))
    } catch (e) {
      const errorMsg: Message = {
        id: `error-${Date.now()}`,
        role: 'assistant',
        content: `Error: ${e instanceof Error ? e.message : 'Unknown error'}`,
      }
      setMessages((prev) => prev.filter((m) => !m.loading).concat(errorMsg))
    } finally {
      setIsLoading(false)
    }
  }, [input, ticker, isLoading])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSubmit()
      }
    },
    [handleSubmit]
  )

  if (!ticker) return null

  return (
    <div className={`ask-panel${askPanelOpen ? ' open' : ''}`}>
      {/* Toggle button */}
      <button
        className="ask-panel-toggle"
        onClick={() => setAskPanelOpen(!askPanelOpen)}
      >
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.3">
          <circle cx="7" cy="7" r="5.5" />
          <path d="M5 5.5a2 2 0 0 1 3.5 1.5c0 1-1.5 1-1.5 2" />
          <circle cx="7" cy="10.5" r="0.5" fill="currentColor" />
        </svg>
        <span>Ask AI about {ticker}'s 10-K</span>
        <svg
          width="10"
          height="10"
          viewBox="0 0 10 10"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          style={{
            marginLeft: 'auto',
            transform: askPanelOpen ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.2s',
          }}
        >
          <path d="M2 4l3 3 3-3" />
        </svg>
      </button>

      {/* Collapsible content */}
      {askPanelOpen && (
        <div className="ask-panel-content">
          {/* Messages */}
          <div className="ask-panel-messages">
            {messages.length === 0 && (
              <div className="ask-panel-empty">
                Ask questions about {ticker}'s SEC 10-K filing. The AI will cite specific sections.
              </div>
            )}
            {messages.map((msg) => (
              <div key={msg.id} className={`ask-msg ask-msg--${msg.role}`}>
                {msg.loading ? (
                  <div className="ask-msg-loading">
                    <span className="ask-dot" />
                    <span className="ask-dot" />
                    <span className="ask-dot" />
                  </div>
                ) : (
                  <>
                    <div className="ask-msg-content">{msg.content}</div>
                    {msg.citations && msg.citations.length > 0 && (
                      <CitationList citations={msg.citations} />
                    )}
                  </>
                )}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>

          {/* Input */}
          <div className="ask-panel-input-row">
            <input
              ref={inputRef}
              type="text"
              className="ask-panel-input"
              placeholder={`Ask about ${ticker}'s 10-K filing...`}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
            />
            <button
              className="ask-panel-send"
              onClick={handleSubmit}
              disabled={isLoading || !input.trim()}
            >
              <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M1 7h12M8 3l4 4-4 4" />
              </svg>
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

function CitationList({ citations }: { citations: Citation[] }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="ask-citations">
      <button
        className="ask-citations-toggle"
        onClick={() => setExpanded(!expanded)}
      >
        {citations.length} source{citations.length > 1 ? 's' : ''} cited
        <svg
          width="8"
          height="8"
          viewBox="0 0 8 8"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          style={{
            transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
            transition: 'transform 0.15s',
          }}
        >
          <path d="M1.5 3l2.5 2.5L6.5 3" />
        </svg>
      </button>
      {expanded && (
        <div className="ask-citations-list">
          {citations.map((c, i) => (
            <div key={i} className="ask-citation-item">
              <div className="ask-citation-source">
                {c.source}
                <span className="ask-citation-score">
                  relevance: {c.relevance.toFixed(2)}
                </span>
              </div>
              <div className="ask-citation-text">{c.text}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
