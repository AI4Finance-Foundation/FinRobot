// ReportPage — Phase 3 placeholder.
// Phase 4 will wire Markdown rendering of local workspace .md files.

interface ReportPageProps {
  reportId: string
}

export function ReportPage({ reportId }: ReportPageProps): React.ReactElement {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100%',
      }}
    >
      <div
        style={{
          border: '1px dashed var(--border)',
          borderRadius: 8,
          padding: 32,
          textAlign: 'center',
          color: 'var(--text-2)',
          maxWidth: 480,
        }}
      >
        <div style={{ fontSize: '0.9rem', marginBottom: 8, color: 'var(--text-1)' }}>
          报告预览
        </div>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.78rem', color: 'var(--amber)' }}>
          {reportId}
        </div>
        <div style={{ marginTop: 16, fontSize: '0.75rem', color: 'var(--text-3)', lineHeight: 1.5 }}>
          TODO Phase 4: Markdown 渲染 + 选中文本右键「问 AI」
        </div>
      </div>
    </div>
  )
}
