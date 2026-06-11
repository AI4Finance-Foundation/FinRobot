// UI shell state — simplified for Desktop V1.
//
// Scope: shell chrome only — AI Panel visibility/width, workspace path, and
// the one-shot chat prompt handoff.
//
// Deliberately separate from:
//   - useUiPrefs  (i18n/index.ts)      → persisted prefs (locale, legacy chatExpanded)
//
// Workspace research data (DCF result, comps, …) is NOT here — it lives in
// TanStack Query (server-state).
//
// Persistence: only width/open/workspacePath are persisted.
//
// History: the Phase-4 Tab system (openTabs/openTab) and the manual
// ContextBundle (pinned/mentions/selected_text) were removed 2026-06-10 —
// nothing ever produced them, so AiChatTab's /chat payload derives the live
// context purely from the route (pathname / ticker / artifact id).

import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { DEFAULT_WORKSPACE_PATH } from '../lib/tauri'
import { AI_CHAT_ENABLED } from '../config/features'

// ─── Store shape ──────────────────────────────────────────────────

interface UiStoreState {
  // AI Panel
  aiPanelOpen: boolean
  aiPanelWidth: number

  // Workspace
  workspacePath: string

  /** One-shot message handoff from other parts of the UI (Dashboard hero, etc.)
   * into RightChatPanel. Panel consumes & clears it on read. */
  pendingChatPrompt: { text: string; autoSend: boolean } | null

  // ── Actions ───────────────────────────────────────────────────
  setAiPanelOpen: (open: boolean) => void
  toggleAiPanel: () => void
  setAiPanelWidth: (w: number) => void

  setWorkspacePath: (p: string) => void

  /** Hand a prompt to RightChatPanel and (optionally) auto-send it.
   * Opens the AI panel if collapsed. */
  sendChatPrompt: (text: string, autoSend?: boolean) => void
  consumePendingChatPrompt: () => void
}

// ─── Defaults ─────────────────────────────────────────────────────

const DEFAULT_AIPANEL_W = 420
const MIN_AIPANEL_W = 320
const MAX_AIPANEL_W = 640

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n))
}

// ─── Store ────────────────────────────────────────────────────────

export const useUiStore = create<UiStoreState>()(
  persist(
    (set) => ({
      aiPanelOpen: true,
      aiPanelWidth: DEFAULT_AIPANEL_W,

      workspacePath: DEFAULT_WORKSPACE_PATH,

      pendingChatPrompt: null,

      // AI panel
      setAiPanelOpen: (aiPanelOpen) => set({ aiPanelOpen: AI_CHAT_ENABLED && aiPanelOpen }),
      toggleAiPanel: () => {
        if (!AI_CHAT_ENABLED) return
        set((s) => ({ aiPanelOpen: !s.aiPanelOpen }))
      },
      setAiPanelWidth: (w) => set({ aiPanelWidth: clamp(w, MIN_AIPANEL_W, MAX_AIPANEL_W) }),

      // workspace
      setWorkspacePath: (workspacePath) => set({ workspacePath }),

      // chat handoff (Dashboard hero → RightChatPanel)
      sendChatPrompt: (text, autoSend = true) =>
        set(
          AI_CHAT_ENABLED
            ? {
                pendingChatPrompt: { text, autoSend },
                aiPanelOpen: true,
              }
            : {
                pendingChatPrompt: null,
                aiPanelOpen: false,
              },
        ),
      consumePendingChatPrompt: () => set({ pendingChatPrompt: null }),
    }),
    {
      name: 'finrobot-ui-shell',
      storage: createJSONStorage(() => localStorage),
      // Persist only stable chrome prefs.
      partialize: (s) => ({
        aiPanelWidth: s.aiPanelWidth,
        aiPanelOpen: AI_CHAT_ENABLED && s.aiPanelOpen,
        workspacePath: s.workspacePath,
      }),
      onRehydrateStorage: () => () => {
        // 没有 theme toggle：清掉持久化里残留的 light 主题，
        // 否则本地存了 light 的用户启动后还是 light，看着乱。
        document.documentElement.removeAttribute('data-theme')
      },
    },
  ),
)
