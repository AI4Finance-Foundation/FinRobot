/**
 * Workspace store — cross-ticker grouping with localStorage persistence.
 * Groups are purely a UI concept: they hold a list of tickers and a name.
 * No backend API needed; the frontend loops individual ticker endpoints
 * for batch operations.
 */
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export interface Workspace {
  id: string
  name: string
  description?: string
  tickers: string[]
  created_at: string
}

/** State of one in-flight batch run per workspace. */
export interface BatchJobItem {
  ticker: string
  status: 'pending' | 'running' | 'done' | 'error'
  error?: string
}

export interface BatchJob {
  workspaceId: string
  pipelineType: 'dcf' | 'comps'
  items: BatchJobItem[]
}

interface WorkspaceState {
  workspaces: Workspace[]
  /** Current batch job per workspace (at most one active). */
  batchJobs: Record<string, BatchJob>

  /** CRUD */
  createWorkspace: (name: string, description?: string) => Workspace
  renameWorkspace: (id: string, name: string) => void
  deleteWorkspace: (id: string) => void
  addTickerToWorkspace: (workspaceId: string, ticker: string) => void
  removeTickerFromWorkspace: (workspaceId: string, ticker: string) => void

  /** Batch ops */
  startBatchJob: (workspaceId: string, pipelineType: 'dcf' | 'comps') => void
  updateBatchItem: (workspaceId: string, ticker: string, update: Partial<BatchJobItem>) => void
  clearBatchJob: (workspaceId: string) => void
}

let _idCounter = 0
function newId(): string {
  return `ws_${Date.now()}_${++_idCounter}`
}

export const useWorkspaceStore = create<WorkspaceState>()(
  persist(
    (set, get) => ({
      workspaces: [],
      batchJobs: {},

      createWorkspace: (name, description) => {
        const ws: Workspace = {
          id: newId(),
          name: name.trim(),
          description,
          tickers: [],
          created_at: new Date().toISOString(),
        }
        set((s) => ({ workspaces: [...s.workspaces, ws] }))
        return ws
      },

      renameWorkspace: (id, name) => {
        set((s) => ({
          workspaces: s.workspaces.map((w) =>
            w.id === id ? { ...w, name: name.trim() } : w
          ),
        }))
      },

      deleteWorkspace: (id) => {
        set((s) => ({
          workspaces: s.workspaces.filter((w) => w.id !== id),
          batchJobs: Object.fromEntries(
            Object.entries(s.batchJobs).filter(([k]) => k !== id)
          ),
        }))
      },

      addTickerToWorkspace: (workspaceId, ticker) => {
        const upper = ticker.toUpperCase().trim()
        set((s) => ({
          workspaces: s.workspaces.map((w) =>
            w.id === workspaceId && !w.tickers.includes(upper)
              ? { ...w, tickers: [...w.tickers, upper] }
              : w
          ),
        }))
      },

      removeTickerFromWorkspace: (workspaceId, ticker) => {
        const upper = ticker.toUpperCase().trim()
        set((s) => ({
          workspaces: s.workspaces.map((w) =>
            w.id === workspaceId
              ? { ...w, tickers: w.tickers.filter((t) => t !== upper) }
              : w
          ),
        }))
      },

      startBatchJob: (workspaceId, pipelineType) => {
        const ws = get().workspaces.find((w) => w.id === workspaceId)
        if (!ws) return
        const items: BatchJobItem[] = ws.tickers.map((ticker) => ({
          ticker,
          status: 'pending',
        }))
        set((s) => ({
          batchJobs: {
            ...s.batchJobs,
            [workspaceId]: { workspaceId, pipelineType, items },
          },
        }))
      },

      updateBatchItem: (workspaceId, ticker, update) => {
        set((s) => {
          const job = s.batchJobs[workspaceId]
          if (!job) return s
          return {
            batchJobs: {
              ...s.batchJobs,
              [workspaceId]: {
                ...job,
                items: job.items.map((item) =>
                  item.ticker === ticker ? { ...item, ...update } : item
                ),
              },
            },
          }
        })
      },

      clearBatchJob: (workspaceId) => {
        set((s) => {
          const next = { ...s.batchJobs }
          delete next[workspaceId]
          return { batchJobs: next }
        })
      },
    }),
    {
      name: 'finagent-workspaces',
      partialize: (s) => ({ workspaces: s.workspaces }),
    }
  )
)
