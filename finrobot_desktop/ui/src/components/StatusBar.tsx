import { useEffect, useState } from 'react'

// TODO Phase 5: wire openExternal for Apache-2.0 badge click
// import { openExternal } from '../lib/tauri'

const MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC']

function pad(n: number): string {
  return String(n).padStart(2, '0')
}

function formatClock(d: Date): string {
  return `${pad(d.getDate())} ${MONTHS[d.getMonth()]} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

export default function StatusBar(): React.ReactElement {
  const [clock, setClock] = useState(() => formatClock(new Date()))

  useEffect(() => {
    const id = setInterval(() => setClock(formatClock(new Date())), 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="statusbar">
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

      {/* Apache-2.0 badge — TODO Phase 5: onClick={() => openExternal('https://www.apache.org/licenses/LICENSE-2.0')} */}
      <div className="sb-item clickable" title="Apache-2.0 License">
        Apache-2.0
      </div>

      <div className="spacer" />

      {/* Market indices — hardcoded Phase 1 */}
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

      {/* Clock */}
      <div className="sb-item clickable">{clock}</div>
    </div>
  )
}
