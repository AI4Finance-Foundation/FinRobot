import { useState, useEffect, useCallback } from 'react'
import { QueryClientProvider, useQuery } from '@tanstack/react-query'
import { queryClient } from './api/queryClient'
import { api } from './api/client'
import { ErrorBoundary } from './components/ErrorBoundary'
import { useAppStore } from './stores/appStore'
import CommandPalette from './components/CommandPalette'
import SettingsView from './views/SettingsView'
import TickerWorkspace from './views/TickerWorkspace'
import RunHistory from './views/RunHistory'

function AppInner() {
  const [forceSettings, setForceSettings] = useState(false)
  const [cmdOpen, setCmdOpen] = useState(false)
  const view = useAppStore((s) => s.view)

  // Global Cmd+K / Ctrl+K shortcut
  const handleGlobalKeyDown = useCallback((e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault()
      setCmdOpen((o) => !o)
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
      onClose={() => setCmdOpen(false)}
      onOpenSettings={() => setForceSettings(true)}
    />
  )

  if (isLoading) {
    return (
      <div className="app" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {cmdPalette}
        <div style={{ color: 'var(--text-secondary)' }}>Connecting to backend...</div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="app" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {cmdPalette}
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
        <RunHistory onBack={() => useAppStore.getState().setView('workspace')} />
      </div>
    )
  }

  return (
    <div className="app">
      {cmdPalette}
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
