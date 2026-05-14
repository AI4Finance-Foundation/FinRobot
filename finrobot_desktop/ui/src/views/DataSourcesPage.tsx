// DataSourcesPage — Phase 3 placeholder.
// TODO Phase 5: real datasource connection management

export function DataSourcesPage(): React.ReactElement {
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
          数据源管理
        </div>
        <div style={{ fontSize: '0.78rem', color: 'var(--text-3)', lineHeight: 1.6 }}>
          TODO Phase 5: 数据源连接配置、状态监控、API 额度管理
        </div>
      </div>
    </div>
  )
}
