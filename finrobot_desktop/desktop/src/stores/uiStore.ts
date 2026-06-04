// UI shell state — simplified for Desktop V1.
//
// Scope: shell chrome only — AI Panel visibility/width, Tab system (kept for
// StatusBar "About" tab + RightChatPanel "pipeline" tab), conversation
// mode/model, ContextBundle, workspace path.
//
// Deliberately separate from:
//   - useUiPrefs  (i18n/index.ts)      → persisted prefs (locale, legacy chatExpanded)
//
// Workspace research data (DCF result, comps, …) is NOT here — it lives in
// TanStack Query (server-state). The ⌘K command palette is shell chrome, so
// its open/query state lives here (session-scoped, not persisted).
//
// Persistence: only width/mode/model/workspacePath are persisted; tabs and
// context are intentionally session-scoped.

import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { DEFAULT_WORKSPACE_PATH } from '../lib/tauri'

// ─── Tabs ─────────────────────────────────────────────────────────

export type TabKind =
  | 'dashboard'
  | 'pipeline'
  | 'report'
  | 'monitor'
  | 'datasources'
  | 'settings'
  | 'about'
  | 'backtest'

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

// ─── Context Bundle ────────────────────────────────────────────────

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

// ─── Store shape ──────────────────────────────────────────────────

export type Theme = 'dark' | 'light'

interface UiStoreState {
  // AI Panel
  aiPanelOpen: boolean
  aiPanelWidth: number

  /** Cosmic desktop trail cursor (spec §5.3). Default OFF — a 60fps RAF
   *  loop pinning one core was the #1 fan/heat complaint. Users who want
   *  the "桌面 App 灵魂" can opt-in via Settings. */
  cursorTrailEnabled: boolean

  /** Spline 3D AI Analyst on the /stocks landing backdrop. Default ON —
   *  mounts only on the landing route, not the ticker workspace (the detail
   *  page shows numbers, not 3D). When off, the static FakeRobotRings
   *  fallback renders. */
  splineEnabled: boolean

  // Command palette (⌘K) — shell chrome, session-scoped
  cmdPaletteOpen: boolean
  cmdKQuery: string

  // Workspace
  workspacePath: string

  // Tabs (kept: StatusBar opens 'about', RightChatPanel opens 'pipeline')
  openTabs: Tab[]
  activeTabId: string | null

  // AI Panel
  contextBundle: ContextBundle

  /** One-shot message handoff from other parts of the UI (Dashboard hero, etc.)
   * into RightChatPanel. Panel consumes & clears it on read. */
  pendingChatPrompt: { text: string; autoSend: boolean } | null

  // ── Actions ───────────────────────────────────────────────────
  setAiPanelOpen: (open: boolean) => void
  toggleAiPanel: () => void
  setAiPanelWidth: (w: number) => void

  setCursorTrailEnabled: (on: boolean) => void
  setSplineEnabled: (on: boolean) => void

  setCmdPaletteOpen: (open: boolean) => void
  toggleCmdPalette: () => void
  setCmdKQuery: (q: string) => void

  setWorkspacePath: (p: string) => void

  openTab: (tab: Tab) => void

  /** Hand a prompt to RightChatPanel and (optionally) auto-send it.
   * Opens the AI panel if collapsed. */
  sendChatPrompt: (text: string, autoSend?: boolean) => void
  consumePendingChatPrompt: () => void

  setSelectedText: (text: string | undefined) => void
  addPinned: (item: ContextItem) => void
  removePinned: (id: string) => void
  addMention: (item: ContextItem) => void
  removeMention: (id: string) => void
  clearMentions: () => void
}

// ─── Defaults ─────────────────────────────────────────────────────

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
    (set) => ({
      aiPanelOpen: true,
      aiPanelWidth: DEFAULT_AIPANEL_W,
      // Heat-conservative defaults — cosmic decorations are opt-in for
      // anything that pegs a CPU core. Spline (single landing backdrop)
      // stays on because it only mounts on /stocks and unmounts the
      // moment the user enters a ticker workspace.
      cursorTrailEnabled: false,
      splineEnabled: true,

      cmdPaletteOpen: false,
      cmdKQuery: '',

      workspacePath: DEFAULT_WORKSPACE_PATH,

      openTabs: [DASHBOARD_TAB],
      activeTabId: DASHBOARD_TAB.id,

      contextBundle: initialContext,
      pendingChatPrompt: null,

      // AI panel
      setAiPanelOpen: (aiPanelOpen) => set({ aiPanelOpen }),
      toggleAiPanel: () => set((s) => ({ aiPanelOpen: !s.aiPanelOpen })),
      setAiPanelWidth: (w) => set({ aiPanelWidth: clamp(w, MIN_AIPANEL_W, MAX_AIPANEL_W) }),

      // Cosmic cursor trail
      setCursorTrailEnabled: (cursorTrailEnabled) => set({ cursorTrailEnabled }),
      setSplineEnabled: (splineEnabled) => set({ splineEnabled }),

      // command palette (⌘K)
      setCmdPaletteOpen: (cmdPaletteOpen) => set({ cmdPaletteOpen }),
      toggleCmdPalette: () => set((s) => ({ cmdPaletteOpen: !s.cmdPaletteOpen })),
      setCmdKQuery: (cmdKQuery) => set({ cmdKQuery }),

      // workspace
      setWorkspacePath: (workspacePath) =>
        set((s) => ({
          workspacePath,
          contextBundle: { ...s.contextBundle, workspace_path: workspacePath },
        })),

      // tabs — openTab only; close/setActive removed (no EditorTabs consumer)
      openTab: (tab) =>
        set((s) => {
          const exists = s.openTabs.some((t) => t.id === tab.id)
          return {
            openTabs: exists ? s.openTabs : [...s.openTabs, tab],
            activeTabId: tab.id,
          }
        }),

      // chat handoff (Dashboard hero → RightChatPanel)
      sendChatPrompt: (text, autoSend = true) =>
        set({
          pendingChatPrompt: { text, autoSend },
          aiPanelOpen: true,
        }),
      consumePendingChatPrompt: () => set({ pendingChatPrompt: null }),

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
      name: 'finrobot-ui-shell',
      storage: createJSONStorage(() => localStorage),
      // Persist only stable chrome prefs; tabs / context reset each session.
      partialize: (s) => ({
        aiPanelWidth: s.aiPanelWidth,
        aiPanelOpen: s.aiPanelOpen,
        cursorTrailEnabled: s.cursorTrailEnabled,
        splineEnabled: s.splineEnabled,
        workspacePath: s.workspacePath,
      }),
      onRehydrateStorage: () => (state) => {
        // 没有 theme toggle：清掉持久化里残留的 light 主题，
        // 否则本地存了 light 的用户启动后还是 light，看着乱。
        document.documentElement.removeAttribute('data-theme')
        // prefers-reduced-motion: 自动关掉所有 heavy 装饰（仅首次冷启动）
        // 已经 hydrate 过的用户保留其手动选择。
        if (typeof window !== 'undefined' && state) {
          const mql =
            typeof window.matchMedia === 'function'
              ? window.matchMedia('(prefers-reduced-motion: reduce)')
              : null
          if (mql?.matches) {
            const stored = localStorage.getItem('finrobot-ui-shell')
            // Only auto-disable if the user has no persisted choice — i.e.,
            // they never used Settings to flip these on. Once they manually
            // turn on the cosmic decorations we respect that.
            if (!stored || !stored.includes('"cursorTrailEnabled"')) {
              state.cursorTrailEnabled = false
              state.splineEnabled = false
            }
          }
        }
      },
    },
  ),
)
