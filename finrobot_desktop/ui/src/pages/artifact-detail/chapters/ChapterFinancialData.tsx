// Chapter 10 — Financial Data. Audit-trail surface: shows the raw_data
// dump that the pipeline saw at run time (data_source + fetched_at +
// raw fields). This is what makes every artifact reproducible — the
// numbers anyone reads here are exactly the numbers DCF / catalyst /
// peer steps ingested.

import { Chapter, SubChapter, tableStyle } from './ChapterBase'

interface ChapterFinancialDataProps {
  rawData: Record<string, unknown> | null
  dataSource: string | null
  fetchedAt: string | null
}

export function ChapterFinancialData({
  rawData,
  dataSource,
  fetchedAt,
}: ChapterFinancialDataProps): React.ReactElement {
  const entries = Object.entries(rawData ?? {})

  return (
    <Chapter
      id="data"
      num="10"
      title="Financial Data"
      sub="Raw Inputs · Source · Audit Trail"
    >
      <div
        style={{
          display: 'flex',
          gap: 18,
          fontFamily: 'var(--font-mono)',
          fontSize: 11,
          color: 'var(--text-muted)',
          marginBottom: 14,
          flexWrap: 'wrap',
        }}
      >
        <span>
          DATA SOURCE: <span style={{ color: 'var(--accent-cyan)' }}>{dataSource ?? 'unknown'}</span>
        </span>
        {fetchedAt && (
          <span>
            FETCHED AT:{' '}
            <span style={{ color: 'var(--text-secondary)' }}>
              {new Date(fetchedAt).toLocaleString('zh-CN')}
            </span>
          </span>
        )}
      </div>

      {entries.length > 0 ? (
        <SubChapter heading="Raw Data Dump (audit)">
          <table style={tableStyle}>
            <tbody>
              {entries.map(([k, v]) => (
                <tr key={k}>
                  <td
                    style={{
                      padding: '8px 14px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 11.5,
                      color: 'var(--text-muted)',
                      borderBottom: '1px solid var(--border-faint)',
                      width: '38%',
                    }}
                  >
                    {k}
                  </td>
                  <td
                    style={{
                      padding: '8px 14px',
                      fontFamily: 'var(--font-mono)',
                      fontSize: 11.5,
                      color: 'var(--text-secondary)',
                      borderBottom: '1px solid var(--border-faint)',
                      fontVariantNumeric: 'tabular-nums',
                      wordBreak: 'break-word',
                    }}
                  >
                    {formatVal(v)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </SubChapter>
      ) : (
        <p
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 11.5,
            color: 'var(--text-muted)',
            padding: '14px 18px',
            background: 'rgba(15, 15, 34, 0.5)',
            border: '1px dashed var(--border-soft)',
            borderRadius: 'var(--radius-sm)',
          }}
        >
          该 artifact 未保存 raw_data — 早期版本未做完整 audit dump，重跑后可获完整溯源
        </p>
      )}
    </Chapter>
  )
}

function formatVal(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'number') {
    if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(3)}B`
    if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(2)}M`
    if (Math.abs(v) < 1 && v !== 0) return v.toFixed(4)
    return v.toLocaleString('en-US', { maximumFractionDigits: 4 })
  }
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  if (typeof v === 'string') return v.length > 200 ? v.slice(0, 200) + '…' : v
  return JSON.stringify(v)
}
