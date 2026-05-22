// v5 §6.12 散户情绪. Reads PR4b's /api/sentiment/{ticker} which already
// fans out to Reddit / X.com / Polymarket via the adanos provider.

import { useSentimentSnapshot } from '../../hooks/useV5Artifacts'


interface SentimentCardProps {
  ticker: string
}

export function SentimentCard({ ticker }: SentimentCardProps): React.ReactElement {
  const { data, isLoading } = useSentimentSnapshot(ticker, 7)

  if (isLoading) {
    return (
      <section id="sec-sentiment" className="cosmic-card" style={{ margin: "12px 0" }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>👥 散户情绪</h2>
        <p style={{ fontSize: 12, color: 'var(--text-faint)' }}>加载中…</p>
      </section>
    )
  }

  if (!data || data.available === false) {
    return (
      <section id="sec-sentiment" className="cosmic-card" style={{ margin: "12px 0" }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>👥 散户情绪</h2>
        <p style={{ marginTop: 8, fontSize: 12, color: 'var(--text-soft)' }}>
          未配置 Adanos 凭据 · <a href="/settings">跳设置 →</a>
        </p>
        {data?.warnings?.map((w, i) => (
          <p key={i} style={{ marginTop: 4, fontSize: 11, color: 'var(--text-faint)' }}>
            {w}
          </p>
        ))}
      </section>
    )
  }

  const bull = data.bullish_pct ?? 0
  const bear = data.bearish_pct ?? 0

  return (
    <section id="sec-sentiment" className="cosmic-card" style={{ margin: "12px 0" }}>
      <h2 style={{ margin: 0, fontSize: 14, fontWeight: 600 }}>
        👥 散户情绪
        <span style={{ marginLeft: 6, fontSize: 11, color: 'var(--text-faint)', fontWeight: 400 }}>
          · 近 {data.days} 天 · {data.coverage ?? ''} 平台覆盖
        </span>
      </h2>

      <div style={{ marginTop: 12 }}>
        <div
          aria-label="bull-bear-bar"
          style={{
            display: 'flex',
            height: 18,
            borderRadius: 9,
            overflow: 'hidden',
            background: 'var(--bg-soft, #f5f6f8)',
          }}
        >
          <span
            style={{
              width: `${bull}%`,
              background: 'rgba(16,185,129,0.85)',
              color: '#fff',
              fontSize: 10.5,
              textAlign: 'center',
              lineHeight: '18px',
            }}
          >
            🐂 看涨 {bull.toFixed(0)}%
          </span>
          <span
            style={{
              width: `${bear}%`,
              background: 'rgba(239,68,68,0.85)',
              color: '#fff',
              fontSize: 10.5,
              textAlign: 'center',
              lineHeight: '18px',
            }}
          >
            🐻 看跌 {bear.toFixed(0)}%
          </span>
        </div>
      </div>

      <p style={{ marginTop: 10, fontSize: 11.5, color: 'var(--text-soft)' }}>
        讨论平均活跃度 {data.average_buzz ?? 'N/A'} · 情绪一致性 {data.source_alignment ?? '-'}
      </p>

      <table
        style={{
          marginTop: 12,
          width: '100%',
          borderCollapse: 'collapse',
          fontSize: 11,
        }}
      >
        <thead>
          <tr style={{ color: 'var(--text-faint)' }}>
            <th style={{ textAlign: 'left', padding: '4px 0' }}>平台</th>
            <th style={{ textAlign: 'right' }}>看涨 %</th>
            <th style={{ textAlign: 'right' }}>活跃度</th>
            <th style={{ textAlign: 'right' }}>覆盖</th>
          </tr>
        </thead>
        <tbody>
          {data.sources.map((s) => (
            <tr key={s.platform}>
              <td style={{ padding: '4px 0' }}>{s.platform}</td>
              <td style={{ textAlign: 'right' }}>
                {s.bullish_pct !== null ? `${s.bullish_pct.toFixed(0)}%` : '—'}
              </td>
              <td style={{ textAlign: 'right' }}>
                {s.activity_value !== null
                  ? `${s.activity_value.toLocaleString()} ${s.activity_label}`
                  : '—'}
              </td>
              <td style={{ textAlign: 'right' }}>{s.has_data ? '✓' : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
