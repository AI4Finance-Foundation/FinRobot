import { useState, useEffect, useCallback } from 'react'
import { QueryClientProvider, useQuery } from '@tanstack/react-query'
import { queryClient } from './api/queryClient'
import { api } from './api/client'
import { ErrorBoundary } from './components/ErrorBoundary'
import { useAppStore } from './stores/appStore'
import type { PipelineType } from './stores/appStore'
import CommandPalette from './components/CommandPalette'
import ShortcutSheet from './components/ShortcutSheet'
import ToastContainer from './components/Toast'
import SettingsView from './views/SettingsView'
import TickerWorkspace from './views/TickerWorkspace'
import RunHistory from './views/RunHistory'

const NUM_KEY_PIPELINE: Record<string, PipelineType> = {
  '1': 'research',
  '2': 'dcf',
  '3': 'comps',
  '4': 'earnings',
  '5': 'lbo',
}

function AppInner() {
  const [forceSettings, setForceSettings] = useState(false)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const view = useAppStore((s) => s.view)
  const cmdOpen = useAppStore((s) => s.cmdPaletteOpen)

  // Global Cmd+K / Ctrl+K shortcut + Cmd+/ for shortcut sheet + number keys for pipeline tabs
  const handleGlobalKeyDown = useCallback((e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault()
      useAppStore.getState().toggleCmdPalette()
    }
    if ((e.metaKey || e.ctrlKey) && e.key === '/') {
      e.preventDefault()
      setShortcutsOpen((o) => !o)
    }
    // Number keys 1-5 switch pipeline tabs (only when not typing in an input)
    const tag = (e.target as HTMLElement)?.tagName
    if (!e.metaKey && !e.ctrlKey && !e.altKey && tag !== 'INPUT' && tag !== 'TEXTAREA' && tag !== 'SELECT') {
      const pipeline = NUM_KEY_PIPELINE[e.key]
      if (pipeline) {
        const state = useAppStore.getState()
        if (state.phase !== 'idle' && state.phase !== 'running_pipeline') {
          state.setPipelineType(pipeline)
        }
      }
    }
  }, [])

  useEffect(() => {
    window.addEventListener('keydown', handleGlobalKeyDown)
    return () => window.removeEventListener('keydown', handleGlobalKeyDown)
  }, [handleGlobalKeyDown])

  const {
    data: settings,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['settings'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/settings')
      if (error) throw new Error('Failed to load settings')
      return data
    },
  })

  // Determine if the required provider key is set
  const settingsReady = (() => {
    if (!settings) return false
    const provider = settings.model_name.split(':')[0]
    if (provider === 'test') return true
    const keyField = `${provider}_api_key_set` as keyof typeof settings
    return Boolean(settings[keyField])
  })()

  const showSettings = forceSettings || (!isLoading && !settingsReady)

  const cmdPalette = (
    <CommandPalette
      open={cmdOpen}
      onClose={() => useAppStore.getState().setCmdPaletteOpen(false)}
      onOpenSettings={() => setForceSettings(true)}
    />
  )

  const shortcutSheet = (
    <ShortcutSheet open={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />
  )

  if (isLoading) {
    return (
      <div className="app" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {cmdPalette}
        {shortcutSheet}
        <ToastContainer />
        <div style={{ color: 'var(--text-secondary)' }}>Connecting to backend...</div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="app" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {cmdPalette}
        {shortcutSheet}
        <ToastContainer />
        <div style={{ color: 'var(--negative)' }}>
          Failed to connect to backend. Make sure the server is running.
        </div>
      </div>
    )
  }

  if (showSettings) {
    return (
      <div className="app">
        {cmdPalette}
        {shortcutSheet}
        <ToastContainer />
        <SettingsView
          onComplete={() => setForceSettings(false)}
        />
      </div>
    )
  }

  if (view === 'history') {
    return (
      <div className="app">
        {cmdPalette}
        {shortcutSheet}
        <ToastContainer />
        <RunHistory onBack={() => useAppStore.getState().setView('workspace')} />
      </div>
    )
  }

  return (
    <div className="app">
      {cmdPalette}
      {shortcutSheet}
      <ToastContainer />
      <TickerWorkspace onOpenSettings={() => setForceSettings(true)} />
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <AppInner />
      </ErrorBoundary>
    </QueryClientProvider>
  )
}
