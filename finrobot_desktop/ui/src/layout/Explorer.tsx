import { IconPlus, IconRefresh } from '../lib/icons'

// Phase 1: static tree mirroring finagent.html prototype <aside class="sidebar-left">.
// Phase 3 will wire activityBarSelection → dynamic content per group.

export function Explorer(): React.ReactElement {
  return (
    <aside className="sidebar-left">
      <div className="sb-header">
        <span className="sb-title">WORKSPACE</span>
        <div className="sb-icons">
          <button className="sb-mini-btn" title="新建">
            <IconPlus size={13} />
          </button>
          <button className="sb-mini-btn" title="刷新">
            <IconRefresh size={13} />
          </button>
        </div>
      </div>

      <div className="sb-content">

        {/* 固定 */}
        <div className="tree-group">
          <div className="tree-head">
            <span className="caret">▾</span>
            <span>固定</span>
          </div>
          <div className="tree-item active">
            <svg className="ic ic-svg" viewBox="0 0 24 24">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="9" y1="9" x2="15" y2="9" />
              <line x1="9" y1="13" x2="15" y2="13" />
              <line x1="9" y1="17" x2="13" y2="17" />
            </svg>
            <span className="name">工作台首页</span>
          </div>
        </div>

        {/* Pipeline */}
        <div className="tree-group">
          <div className="tree-head">
            <span className="caret">▾</span>
            <span>Pipeline</span>
            <span className="count">12</span>
          </div>
          <div className="tree-item">
            <svg className="ic ic-svg" viewBox="0 0 24 24">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
            </svg>
            <span className="name">个股深度分析</span>
            <span className="tag">PL-001</span>
          </div>
          <div className="tree-item">
            <svg className="ic ic-svg" viewBox="0 0 24 24">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
            <span className="name">财报速读</span>
            <span className="tag run">RUN</span>
          </div>
          <div className="tree-item">
            <svg className="ic ic-svg" viewBox="0 0 24 24">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
            <span className="name">行业轮动</span>
            <span className="tag">PL-003</span>
          </div>
          <div className="tree-item">
            <svg className="ic ic-svg" viewBox="0 0 24 24">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
            </svg>
            <span className="name">事件驱动扫描</span>
            <span className="tag live">●</span>
          </div>
          <div className="tree-item">
            <svg className="ic ic-svg" viewBox="0 0 24 24">
              <path d="M3 3v18h18" />
              <polyline points="7 14 11 10 15 14 21 8" />
            </svg>
            <span className="name">投资组合诊断</span>
            <span className="tag">PL-005</span>
          </div>
          <div className="tree-item">
            <svg className="ic ic-svg" viewBox="0 0 24 24">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            <span className="name">研报批处理</span>
            <span className="tag">PL-006</span>
          </div>
        </div>

        {/* 报告 */}
        <div className="tree-group">
          <div className="tree-head">
            <span className="caret">▾</span>
            <span>报告</span>
            <span className="count">47</span>
          </div>
          {['NVDA-Q3-FY26.md', '半导体板块周报.md', '茅台-估值复盘.md', '美联储议息纪要.md'].map(
            (name) => (
              <div className="tree-item" key={name}>
                <svg className="ic ic-svg" viewBox="0 0 24 24">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                </svg>
                <span className="name">{name}</span>
              </div>
            ),
          )}
        </div>

        {/* 自选股 */}
        <div className="tree-group">
          <div className="tree-head">
            <span className="caret">▾</span>
            <span>自选股</span>
            <span className="count">18</span>
          </div>
          <div className="tree-item">
            <span className="ic" style={{ width: 14, textAlign: 'center', fontFamily: "'JetBrains Mono',monospace", fontSize: 9, color: 'var(--green)' }}>●</span>
            <span className="name">NVDA</span>
            <span className="tag" style={{ color: 'var(--green)' }}>+3.87%</span>
          </div>
          <div className="tree-item">
            <span className="ic" style={{ width: 14, textAlign: 'center', fontFamily: "'JetBrains Mono',monospace", fontSize: 9, color: 'var(--green)' }}>●</span>
            <span className="name">AAPL</span>
            <span className="tag" style={{ color: 'var(--green)' }}>+1.24%</span>
          </div>
          <div className="tree-item">
            <span className="ic" style={{ width: 14, textAlign: 'center', fontFamily: "'JetBrains Mono',monospace", fontSize: 9, color: 'var(--red)' }}>●</span>
            <span className="name">TSLA</span>
            <span className="tag" style={{ color: 'var(--red)' }}>-0.92%</span>
          </div>
          <div className="tree-item">
            <span className="ic" style={{ width: 14, textAlign: 'center', fontFamily: "'JetBrains Mono',monospace", fontSize: 9, color: 'var(--green)' }}>●</span>
            <span className="name">600519 茅台</span>
            <span className="tag" style={{ color: 'var(--green)' }}>+0.41%</span>
          </div>
        </div>

        {/* 数据源 */}
        <div className="tree-group">
          <div className="tree-head">
            <span className="caret">▾</span>
            <span>数据源</span>
          </div>
          <div className="tree-item">
            <svg className="ic ic-svg" viewBox="0 0 24 24">
              <ellipse cx="12" cy="5" rx="9" ry="3" />
              <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
              <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
            </svg>
            <span className="name">FinRobot</span>
            <span className="tag live">ON</span>
          </div>
          <div className="tree-item">
            <svg className="ic ic-svg" viewBox="0 0 24 24">
              <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
            </svg>
            <span className="name">实时行情</span>
            <span className="tag live">ON</span>
          </div>
        </div>

      </div>
    </aside>
  )
}
