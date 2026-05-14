// MonitorPage — Phase 3: pulls /api/runs and groups by status.
// Data source: GET /api/runs → RunRecord[]

import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import type { components } from '../api/schema'
import { relativeTime } from '../utils/time'

type RunRecord = components['schemas']['RunRecord']

function statusColor(status: string): string {
  if (status === 'completed') return 'var(--green)'
  if (status === 'running')   return 'var(--amber)'
  if (status === 'failed')    return 'var(--red)'
  return 'var(--text-3)'
}

function RunRow({ run }: { run: RunRecord }) {
  const color = statusColor(run.status)
  const ts = new Date(run.created_at).getTime()
  const ago = Number.isNaN(ts) ? '—' : relativeTime(ts)

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '10px 16px',
        borderBottom: '1px solid var(--line)',
        fontSize: '0.82rem',
      }}
    >
      <span style={{ color, fontFamily: 'var(--font-mono)', fontSize: 9 }}>●</span>
      <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: 'var(--amber)', width: 64 }}>
        {run.ticker.toUpperCase()}
      </span>
      <span style={{ color: 'var(--text-1)', flex: 1 }}>{run.pipeline_type}</span>
      <span style={{ color, fontSize: '0.72rem', fontFamily: 'var(--font-mono)' }}>
        {run.status.toUpperCase()}
      </span>
      <span style={{ color: 'var(--text-3)', fontSize: '0.72rem', fontFamily: 'var(--font-mono)', width: 80, textAlign: 'right' }}>
        {ago}
      </span>
    </div>
  )
}

export function MonitorPage(): React.ReactElement {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['monitor-runs'],
    queryFn: async () => {
      const { data: resp, error } = await api.GET('/api/runs')
      if (error) return []
      return resp?.runs ?? []
    },
    refetchInterval: 10_000,
  })

  const runs: RunRecord[] = data ?? []
  const running   = runs.filter((r) => r.status === 'running')
  const completed = runs.filter((r) => r.status === 'completed')
  const failed    = runs.filter((r) => r.status === 'failed')

  if (isLoading) {
    return (
      <div style={{ padding: 32, color: 'var(--text-3)', fontFamily: 'var(--font-mono)', fontSize: '0.78rem' }}>
        加载任务列表…
      </div>
    )
  }

  if (isError) {
    return (
      <div style={{ padding: 32, color: 'var(--red)', fontSize: '0.82rem' }}>
        加载失败，请检查后端连接
      </div>
    )
  }

  function Section({ title, items, color }: { title: string; items: RunRecord[]; color: string }) {
    return (
      <div style={{ marginBottom: 24 }}>
        <div
          style={{
            padding: '8px 16px',
            background: 'var(--bg-1)',
            borderBottom: '1px solid var(--line)',
            fontSize: '0.7rem',
            fontFamily: 'var(--font-mono)',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color,
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
        >
          {title}
          <span style={{ color: 'var(--text-3)', fontWeight: 400 }}>{items.length}</span>
        </div>
        {items.length === 0 ? (
          <div style={{ padding: '12px 16px', color: 'var(--text-3)', fontSize: '0.78rem' }}>无</div>
        ) : (
          items.map((r) => <RunRow key={r.run_id} run={r} />)
        )}
      </div>
    )
  }

  return (
    <div style={{ height: '100%', overflowY: 'auto' }}>
      <Section title="运行中"  items={running}   color="var(--amber)" />
      <Section title="已完成"  items={completed} color="var(--green)" />
      <Section title="失败"    items={failed}    color="var(--red)"   />
    </div>
  )
}
