// AiChatTab — chat body of the right panel (cosmic Stage A split).
//
// Was: the entire RightChatPanel (outer aside + expand/collapse + chat),
// then a single 1250-line file. Now: composition shell only — the chat state
// machine lives in chat/useChatStream, and the header / message list / input
// area / collapsed icon column each live in their own file under chat/.
// This file owns the expanded/collapsed prop shim, unread tracking for the
// collapsed state, and the sessions drawer toggle.

import { useState, useEffect, useRef } from 'react'
import { useParams } from 'react-router-dom'
import { useUiStore } from '../../stores/uiStore'
import { ContextBar } from '../AIPanel/ContextBar'
import { SessionsDrawer } from './SessionsDrawer'
import { CoverageTriageStrip } from './CoverageTriageStrip'
import { useChatStream } from './chat/useChatStream'
import { AiPanelHeader, modelLabel } from './chat/AiPanelHeader'
import { MessageList } from './chat/MessageList'
import { AiInputArea } from './chat/AiInputArea'
import { IconColumn } from './chat/IconColumn'

// ──────────────────────────────────────────────────────────────
// AiChatTab — chat body, no aside wrapper.
//
// Props are inherited from the legacy RightChatPanel API so existing
// tests that injected `expanded` / `onToggle` keep working through the
// shim in RightChatPanel/index.tsx.
// ──────────────────────────────────────────────────────────────

interface AiChatTabProps {
  /** When provided by tests/legacy callers, overrides uiStore.aiPanelOpen. */
  expanded?: boolean
  /** When provided by tests/legacy callers, called instead of uiStore.toggleAiPanel. */
  onToggle?: () => void
}

export function AiChatTab({
  expanded: expandedProp,
  onToggle: onToggleProp,
}: AiChatTabProps = {}): React.ReactElement {
  const { ticker } = useParams<{ ticker?: string }>()

  // ── uiStore bindings ────────────────────────────────────────
  const storeOpen = useUiStore((s) => s.aiPanelOpen)
  const toggleAiPanel = useUiStore((s) => s.toggleAiPanel)

  // Prop-override: if caller supplies expanded/onToggle, use those.
  // Otherwise fall through to uiStore.
  const isExpanded = expandedProp !== undefined ? expandedProp : storeOpen
  const handleToggle = onToggleProp !== undefined ? onToggleProp : toggleAiPanel

  // Sessions drawer — list / switch / delete past conversations.
  const [sessionsOpen, setSessionsOpen] = useState(false)

  // The chat state machine: session-bound transport, transcript seeding,
  // artifact invalidation, input state, submit/retry, pending prompts.
  const {
    inputText,
    setInputText,
    sessions,
    sessionsLoading,
    sessionsError,
    activeSessionId,
    seedLoading,
    newSession,
    switchSession,
    deleteSession,
    deletingId,
    settings,
    configuredModel,
    messages,
    status,
    error,
    isLoading,
    stop,
    handleSubmit,
    handleReload,
  } = useChatStream(ticker)

  // Track unread for collapsed state
  const [unreadCount, setUnreadCount] = useState(0)
  const lastSeenMessageCountRef = useRef(0)

  // Track unread when panel is collapsed
  useEffect(() => {
    if (!isExpanded) {
      const assistantCount = messages.filter((m) => m.role === 'assistant').length
      if (assistantCount > lastSeenMessageCountRef.current) {
        setUnreadCount(assistantCount - lastSeenMessageCountRef.current)
      }
    } else {
      lastSeenMessageCountRef.current = messages.filter((m) => m.role === 'assistant').length
      setUnreadCount(0)
    }
  }, [messages, isExpanded])

  // ── Collapsed: legacy/test path (prop injected) ───────────────
  // Tests that inject expanded={false} still expect an IconColumn; the
  // uiStore path renders nothing here because the splitter (index.tsx)
  // owns the aside + the expand button.
  if (expandedProp === false) {
    return (
      <IconColumn
        onToggle={() => {
          handleToggle()
          setUnreadCount(0)
          lastSeenMessageCountRef.current = messages.filter((m) => m.role === 'assistant').length
        }}
        unreadCount={unreadCount}
        onNewSession={newSession}
      />
    )
  }

  return (
    <div
      data-testid="right-chat-panel-chat"
      style={{
        position: 'relative',
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
        flex: 1,
      }}
    >
      <AiPanelHeader
        modelLabel={modelLabel(configuredModel, settings?.providers)}
        onToggle={handleToggle}
        onNewSession={newSession}
        onOpenHistory={() => setSessionsOpen(true)}
        ticker={ticker}
        thinking={isLoading}
      />

      {sessionsOpen && (
        <SessionsDrawer
          sessions={sessions}
          activeSessionId={activeSessionId}
          loading={sessionsLoading}
          error={sessionsError}
          deletingId={deletingId}
          onSwitch={switchSession}
          onNew={newSession}
          onDelete={deleteSession}
          onClose={() => setSessionsOpen(false)}
        />
      )}

      <ContextBar />

      <CoverageTriageStrip defaultCollapsed={messages.length > 0} />

      <MessageList
        messages={messages}
        isLoading={isLoading}
        status={status}
        restoring={seedLoading}
      />

      <AiInputArea
        value={inputText}
        onChange={setInputText}
        onSubmit={handleSubmit}
        isLoading={isLoading}
        onStop={stop}
        onReload={handleReload}
        error={error}
        hasMessages={messages.length > 0}
      />
    </div>
  )
}
