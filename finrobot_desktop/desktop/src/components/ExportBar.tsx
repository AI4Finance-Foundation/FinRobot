import { useCallback, useState } from 'react'
import { useAppStore } from '../stores/appStore'
import { BASE_URL } from '../api/client'

export default function ExportBar() {
  const { ticker, dcfInputs, dcfResult, phase } = useAppStore()
  const [exporting, setExporting] = useState(false)

  const showBar = phase === 'pipeline_done' || phase === 'interactive'
  if (!showBar || !ticker) return null

  const handleExcelExport = useCallback(async () => {
    if (!dcfInputs || !dcfResult) return
    setExporting(true)
    try {
      const resp = await fetch(`${BASE_URL}/api/export/excel/dcf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ticker,
          inputs: dcfInputs,
          result: dcfResult,
        }),
      })
      if (!resp.ok) throw new Error('Export failed')
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${ticker}_dcf.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } finally {
      setExporting(false)
    }
  }, [ticker, dcfInputs, dcfResult])

  const handleHtmlReport = useCallback(() => {
    window.open(`${BASE_URL}/api/report/html?ticker=${ticker}`, '_blank')
  }, [ticker])

  const handlePdfDownload = useCallback(async () => {
    const resp = await fetch(`${BASE_URL}/api/report/pdf?ticker=${ticker}`)
    if (!resp.ok) return
    const blob = await resp.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${ticker}_report.pdf`
    a.click()
    URL.revokeObjectURL(url)
  }, [ticker])

  return (
    <div className="export-bar animate-in">
      <button className="btn" onClick={handleExcelExport} disabled={exporting || !dcfInputs}>
        <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M2 10v2h10v-2M7 2v7m-3-3l3 3 3-3" />
        </svg>
        {exporting ? 'Exporting...' : 'Export Excel'}
      </button>
      <button className="btn" onClick={handleHtmlReport}>
        <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="2" y="1" width="10" height="12" rx="1" />
          <path d="M5 4h4M5 7h4M5 10h2" />
        </svg>
        HTML Report
      </button>
      <button className="btn" onClick={handlePdfDownload}>
        <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
          <rect x="2" y="1" width="10" height="12" rx="1" />
          <path d="M5 5h4v3H5z" />
          <path d="M5 10h4" />
        </svg>
        PDF
      </button>
      <div style={{ flex: 1 }} />
      <button
        className="btn btn-primary"
        onClick={() => {
          useAppStore.getState().reset()
        }}
      >
        <svg viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5">
          <path d="M7 1v12M1 7h12" />
        </svg>
        New Analysis
      </button>
    </div>
  )
}
