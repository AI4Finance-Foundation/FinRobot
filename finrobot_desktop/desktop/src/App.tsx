import { useState } from 'react'
import { ErrorBoundary } from './components/ErrorBoundary'
import ResearchView from './components/ResearchView'
import DCFView from './components/DCFView'
import CompsView from './components/CompsView'
import SettingsView from './components/SettingsView'

type View = 'research' | 'dcf' | 'comps' | 'settings'

export default function App() {
  const [view, setView] = useState<View>('research')

  return (
    <ErrorBoundary>
      <div className="app">
        <nav className="nav">
          <span className="nav-title">FinAgent</span>
          <div className="nav-tabs">
            <button
              className={view === 'research' ? 'active' : ''}
              onClick={() => setView('research')}
            >
              Research
            </button>
            <button
              className={view === 'dcf' ? 'active' : ''}
              onClick={() => setView('dcf')}
            >
              DCF
            </button>
            <button
              className={view === 'comps' ? 'active' : ''}
              onClick={() => setView('comps')}
            >
              Comps
            </button>
            <button
              className={view === 'settings' ? 'active' : ''}
              onClick={() => setView('settings')}
            >
              Settings
            </button>
          </div>
        </nav>
        <main className="main">
          {view === 'research' && <ResearchView />}
          {view === 'dcf' && <DCFView />}
          {view === 'comps' && <CompsView />}
          {view === 'settings' && <SettingsView />}
        </main>
      </div>
    </ErrorBoundary>
  )
}
