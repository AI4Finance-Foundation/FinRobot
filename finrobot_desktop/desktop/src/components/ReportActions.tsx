const SERVER_URL = 'http://127.0.0.1:8000'

interface ReportActionsProps {
  ticker: string
  disabled?: boolean
}

export default function ReportActions({ ticker, disabled }: ReportActionsProps) {
  const handleViewReport = () => {
    window.open(`${SERVER_URL}/api/report/html?ticker=${ticker}`, '_blank')
  }

  const handleDownloadPdf = async () => {
    try {
      const response = await fetch(`${SERVER_URL}/api/report/pdf?ticker=${ticker}`)
      if (!response.ok) {
        alert(`PDF generation failed: ${response.statusText}`)
        return
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${ticker}_report.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      alert(`Failed to download PDF: ${err}`)
    }
  }

  return (
    <div className="flex gap-2 mt-4">
      <button
        className="px-4 py-2 bg-[#1a365d] text-white rounded hover:bg-[#1a365d]/80 disabled:opacity-50"
        onClick={handleViewReport}
        disabled={disabled || !ticker}
      >
        View Full Report
      </button>
      <button
        className="px-4 py-2 bg-[#d4a843] text-gray-900 rounded hover:bg-[#d4a843]/80 disabled:opacity-50"
        onClick={handleDownloadPdf}
        disabled={disabled || !ticker}
      >
        Download PDF
      </button>
    </div>
  )
}
