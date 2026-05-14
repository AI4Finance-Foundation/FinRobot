// UI shell state for the IDE-style desktop layout (REFACTOR.md §8).
//
// Scope: shell chrome only — Activity Bar selection, Explorer width,
// AI Panel visibility, Tab system, conversation mode/model, ContextBundle,
// workspace path.
//
// Deliberately separate from:
//   - useAppStore (stores/appStore.ts) → workspace data (ticker, DCF result, …)
//   - useUiPrefs  (i18n/index.ts)      → persisted prefs (locale, legacy chatExpanded)
//
// Persistence: only width/mode/model/workspacePath are persisted; tabs and
// context are intentionally session-scoped (REFACTOR §8: "messages not
// persisted unless saved as report").

import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { DEFAULT_WORKSPACE_PATH } from '../lib/tauri'

// ─── Activity Bar ─────────────────────────────────────────────────

export type ActivityKey =
  | 'dashboard'
  | 'pipelines'
  | 'reports'
  | 'monitor'
  | 'datasources'
  | 'watchlist'
  | 'settings'

// ─── Tabs ─────────────────────────────────────────────────────────

export type TabKind =
  | 'dashboard'
  | 'pipeline'
  | 'report'
  | 'monitor'
  | 'datasources'
  | 'watchlist'
  | 'settings'
  | 'about'

export interface Tab {
  /** Stable id; for kind=dashboard always "dashboard". For pipeline/report
   * use the entity id so re-opening reuses an existing tab. */
  id: string
  kind: TabKind
  title: string
  /** Optional payload — e.g. { ticker: 'NVDA' } for pipeline tabs. */
  payload?: Record<string, unknown>
  /** Unsaved changes marker (●). */
  dirty?: boolean
}

// ─── Context Bundle (REFACTOR §3.2) ───────────────────────────────

export type ContextItemKind =
  | 'file'
  | 'pipeline'
  | 'symbol'
  | 'report'
  | 'run_result'
  | 'workspace'
  | 'tab'

export interface ContextItem {
  kind: ContextItemKind
  id: string
  label: string
  /** Optional payload serialised into the prompt by Phase 4 wiring. */
  payload?: unknown
}

export interface ActiveTabRef {
  type: TabKind
  id: string
  /** Phase 4: content snapshot for the agent to inspect. */
  content?: string
}

export interface ContextBundle {
  active_tab?: ActiveTabRef
  selected_text?: string
  pinned: ContextItem[]
  mentions: ContextItem[]
  workspace_path: string
}

// ─── Conversation mode ────────────────────────────────────────────

/** A = narrative (LLM agent), B = computation (pipeline). */
export type AgentMode = 'A' | 'B'

// ─── Store shape ──────────────────────────────────────────────────

interface UiStoreState {
  // Shell chrome
  activityBarSelection: ActivityKey
  explorerWidth: number
  aiPanelOpen: boolean
  aiPanelWidth: number

  // Workspace (P1: hardcoded; Phase 5 wires dialog.open)
  workspacePath: string

  // Tabs
  openTabs: Tab[]
  activeTabId: string | null

  // AI Panel
  mode: AgentMode
  currentModel: string
  contextBundle: ContextBundle

  // ── Actions ───────────────────────────────────────────────────
  setActivityBarSelection: (a: ActivityKey) => void
  setExplorerWidth: (w: number) => void
  setAiPanelOpen: (open: boolean) => void
  toggleAiPanel: () => void
  setAiPanelWidth: (w: number) => void

  setWorkspacePath: (p: string) => void

  openTab: (tab: Tab) => void
  closeTab: (id: string) => void
  setActiveTab: (id: string | null) => void
  markTabDirty: (id: string, dirty: boolean) => void

  setMode: (m: AgentMode) => void
  setCurrentModel: (model: string) => void

  setSelectedText: (text: string | undefined) => void
  addPinned: (item: ContextItem) => void
  removePinned: (id: string) => void
  addMention: (item: ContextItem) => void
  removeMention: (id: string) => void
  clearMentions: () => void
}

// ─── Defaults ─────────────────────────────────────────────────────

const DEFAULT_EXPLORER_W = 260
const MIN_EXPLORER_W = 200
const MAX_EXPLORER_W = 400

const DEFAULT_AIPANEL_W = 420
const MIN_AIPANEL_W = 320
const MAX_AIPANEL_W = 640

const DASHBOARD_TAB: Tab = {
  id: 'dashboard',
  kind: 'dashboard',
  title: '工作台',
}

const initialContext: ContextBundle = {
  pinned: [],
  mentions: [],
  workspace_path: DEFAULT_WORKSPACE_PATH,
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n))
}

// ─── Store ────────────────────────────────────────────────────────

export const useUiStore = create<UiStoreState>()(
  persist(
    (set, get) => ({
      activityBarSelection: 'dashboard',
      explorerWidth: DEFAULT_EXPLORER_W,
      aiPanelOpen: true,
      aiPanelWidth: DEFAULT_AIPANEL_W,

      workspacePath: DEFAULT_WORKSPACE_PATH,

      openTabs: [DASHBOARD_TAB],
      activeTabId: DASHBOARD_TAB.id,

      mode: 'A',
      currentModel: 'deepseek',
      contextBundle: initialContext,

      // shell chrome
      setActivityBarSelection: (a) => set({ activityBarSelection: a }),
      setExplorerWidth: (w) =>
        set({ explorerWidth: clamp(w, MIN_EXPLORER_W, MAX_EXPLORER_W) }),
      setAiPanelOpen: (aiPanelOpen) => set({ aiPanelOpen }),
      toggleAiPanel: () => set((s) => ({ aiPanelOpen: !s.aiPanelOpen })),
      setAiPanelWidth: (w) =>
        set({ aiPanelWidth: clamp(w, MIN_AIPANEL_W, MAX_AIPANEL_W) }),

      // workspace
      setWorkspacePath: (workspacePath) =>
        set((s) => ({
          workspacePath,
          contextBundle: { ...s.contextBundle, workspace_path: workspacePath },
        })),

      // tabs
      openTab: (tab) =>
        set((s) => {
          const exists = s.openTabs.some((t) => t.id === tab.id)
          return {
            openTabs: exists ? s.openTabs : [...s.openTabs, tab],
            activeTabId: tab.id,
          }
        }),
      closeTab: (id) =>
        set((s) => {
          const next = s.openTabs.filter((t) => t.id !== id)
          // If we just closed the active tab, fall back to last remaining.
          let activeTabId = s.activeTabId
          if (activeTabId === id) {
            activeTabId = next.length > 0 ? next[next.length - 1].id : null
          }
          // Never let the user end up with zero tabs — always keep dashboard.
          if (next.length === 0) {
            return {
              openTabs: [DASHBOARD_TAB],
              activeTabId: DASHBOARD_TAB.id,
            }
          }
          return { openTabs: next, activeTabId }
        }),
      setActiveTab: (id) => set({ activeTabId: id }),
      markTabDirty: (id, dirty) =>
        set((s) => ({
          openTabs: s.openTabs.map((t) =>
            t.id === id ? { ...t, dirty } : t,
          ),
        })),

      // mode & model
      setMode: (mode) => set({ mode }),
      setCurrentModel: (currentModel) => set({ currentModel }),

      // context bundle
      setSelectedText: (selected_text) =>
        set((s) => ({
          contextBundle: { ...s.contextBundle, selected_text },
        })),
      addPinned: (item) =>
        set((s) => {
          const exists = s.contextBundle.pinned.some(
            (p) => p.id === item.id && p.kind === item.kind,
          )
          if (exists) return s
          return {
            contextBundle: {
              ...s.contextBundle,
              pinned: [...s.contextBundle.pinned, item],
            },
          }
        }),
      removePinned: (id) =>
        set((s) => ({
          contextBundle: {
            ...s.contextBundle,
            pinned: s.contextBundle.pinned.filter((p) => p.id !== id),
          },
        })),
      addMention: (item) =>
        set((s) => {
          const exists = s.contextBundle.mentions.some(
            (m) => m.id === item.id && m.kind === item.kind,
          )
          if (exists) return s
          return {
            contextBundle: {
              ...s.contextBundle,
              mentions: [...s.contextBundle.mentions, item],
            },
          }
        }),
      removeMention: (id) =>
        set((s) => ({
          contextBundle: {
            ...s.contextBundle,
            mentions: s.contextBundle.mentions.filter((m) => m.id !== id),
          },
        })),
      clearMentions: () =>
        set((s) => ({
          contextBundle: { ...s.contextBundle, mentions: [] },
        })),
    }),
    {
      name: 'finagent-ui-shell',
      storage: createJSONStorage(() => localStorage),
      // Persist only stable chrome prefs; tabs / context reset each session.
      partialize: (s) => ({
        explorerWidth: s.explorerWidth,
        aiPanelWidth: s.aiPanelWidth,
        aiPanelOpen: s.aiPanelOpen,
        mode: s.mode,
        currentModel: s.currentModel,
        workspacePath: s.workspacePath,
        activityBarSelection: s.activityBarSelection,
      }),
    },
  ),
)

// ─── Selectors / helpers (do not over-engineer; just the common ones) ──

export const selectActiveTab = (s: UiStoreState): Tab | null => {
  if (!s.activeTabId) return null
  return s.openTabs.find((t) => t.id === s.activeTabId) ?? null
}
