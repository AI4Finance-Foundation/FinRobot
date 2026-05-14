// StatusBar — Phase 5: Apache-2.0 click wired + About tab entry.

import { useEffect, useState } from 'react'
import { openExternal } from '../lib/tauri'
import { useUiStore } from '../stores/uiStore'

const MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC']

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function formatClock(d: Date): string {
  return `${pad(d.getDate())} ${MONTHS[d.getMonth()]} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export default function StatusBar(): React.ReactElement {
  const [clock, setClock] = useState(() => formatClock(new Date()))
  const openTab = useUiStore((s) => s.openTab)

  useEffect(() => {
    const id = setInterval(() => setClock(formatClock(new Date())), 1000)
    return () => clearInterval(id)
  }, [])

  function handleLicense() {
    void openExternal('https://www.apache.org/licenses/LICENSE-2.0')
  }

  function handleAbout() {
    openTab({ id: 'about', kind: 'about', title: '关于' })
  }

  return (
    <div className="statusbar" data-testid="statusbar">
      {/* CORE version */}
      <div className="sb-item">
        <span className="dot" />
        <span className="lbl">CORE</span>
        {' '}v0.4.1
      </div>

      {/* Model (clickable placeholder) */}
      <div className="sb-item clickable">
        <span className="lbl">MODEL</span>
        {' '}deepseek-chat
      </div>

      {/* Running tasks */}
      <div className="sb-item warn">
        <span className="dot" />
        <span className="lbl">RUNNING</span>
        {' '}1 task
      </div>

      {/* FinRobot */}
      <div className="sb-item clickable">
        <span className="lbl">FINROBOT</span>
        {' '}connected
      </div>

      {/* Apache-2.0 badge */}
      <div
        className="sb-item clickable"
        title="Apache-2.0 License — 点击查看"
        onClick={handleLicense}
      >
        Apache-2.0
      </div>

      <div className="spacer" />

      {/* Market indices — Phase 1 static values */}
      <div className="sb-item">
        <span className="lbl">SH</span>
        {' '}3287.41{' '}
        <span style={{ color: 'var(--green)' }}>+0.84%</span>
      </div>
      <div className="sb-item">
        <span className="lbl">HSI</span>
        {' '}19842.6{' '}
        <span style={{ color: 'var(--red)' }}>-0.32%</span>
      </div>

      {/* About entry */}
      <div
        className="sb-item clickable"
        title="关于 FinAgent"
        onClick={handleAbout}
      >
        关于
      </div>

      {/* Clock */}
      <div className="sb-item clickable">{clock}</div>
    </div>
  )
}
