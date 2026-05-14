// Dashboard — Phase 2 implementation.
// Visual source: finagent.html §752-912 / REFACTOR.md §2.4
// API source: GET /api/runs → RunListResponse (schema.d.ts)

import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import { useUiStore } from '../stores/uiStore'
import {
  IconSparkle,
  IconActivity,
  IconFileText,
} from '../lib/icons'
import { relativeTime } from '../utils/time'
import type { components } from '../api/schema'

type RunRecord = components['schemas']['RunRecord']

// ─── Static data (UI chrome, not financial data) ──────────────

const PIPELINES = [
  { id: 'PL-001', name: '个股深度分析', desc: '财报 · 估值 · 情绪',   source: 'FinRobot', time: '~ 42s', runs: 128 },
  { id: 'PL-002', name: '财报速读',     desc: '10-K / 季报解析',     source: 'EDGAR',    time: '~ 28s', runs: 94  },
  { id: 'PL-003', name: '行业轮动监测', desc: '板块情绪热力',         source: 'Realtime', time: '~ 35s', runs: 61  },
  { id: 'PL-004', name: '事件驱动扫描', desc: '公告 / 政策 / 突发',   source: '24/7',     time: '~ 18s', runs: 203 },
  { id: 'PL-005', name: '投资组合诊断', desc: '归因 / 风险敞口',      source: '本地',     time: '~ 56s', runs: 12  },
  { id: 'PL-006', name: '研报批处理',   desc: '批量导出 PDF',         source: '本地',     time: '~ 2m',  runs: 7   },
] as const

// Fallback cards shown when API returns empty — not real data.
// placeholder, not for production
const FALLBACK_REPORTS = [
  {
    type: '个股 · PL-001',
    time: '2h ago',
    name: '英伟达 Q3 FY26 财报解析',
    snip: '营收 $35.1B ↑94% YoY，数据中心占比 87.7%。AI 资本开支持续高位，Q4 指引 $37.5B…',
    foot: ['NVDA', '1,842 字', '已导出 PDF'],
    isSample: true,
  },
  {
    type: '行业 · PL-003',
    time: '昨天',
    name: '半导体板块周度轮动',
    snip: '资金流入设备 / 材料子板块，存储链情绪转暖。北方华创、长电科技领涨…',
    foot: ['申万一级', '2,310 字', '3 张图表'],
    isSample: true,
  },
  {
    type: '事件 · PL-004',
    time: '昨天',
    name: '美联储 5 月议息纪要扫描',
    snip: '通胀路径表述软化，点阵图暗示年内 1-2 次降息空间。利率敏感板块影响评级：高…',
    foot: ['宏观', '982 字', '14 标的关联'],
    isSample: true,
  },
  {
    type: '个股 · MODE A',
    time: '3 天前',
    name: '贵州茅台估值复盘对话',
    snip: '围绕"渠道库存 vs 终端动销"的多轮深挖，Agent 自主调用 PL-001 + 行业对比…',
    foot: ['600519', '7 轮对话', '已加入监控'],
    isSample: true,
  },
] as const

// ─── Helpers ──────────────────────────────────────────────────

function buildDateMeta(): string {
  const now = new Date()
  const days = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
  const months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
                  'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  const dd  = String(now.getDate()).padStart(2, '0')
  const mon = months[now.getMonth()]
  const yr  = now.getFullYear()
  const dow = days[now.getDay()]
  return `${dd} ${mon} ${yr} · ${dow} · 12 PIPELINES READY · FINROBOT CONNECTED`
}

function pipelineTypeLabel(pt: string): string {
  const map: Record<string, string> = {
    research: '个股 · PL-001',
    dcf:      'DCF · PL-002',
    comps:    '行业 · PL-003',
    lbo:      'LBO · PL-004',
    earnings: '财报 · PL-005',
    ic_memo:  'IC Memo',
  }
  return map[pt] ?? pt.toUpperCase()
}

// Derive a human-readable title from a RunRecord.
// Data source: /api/runs → RunRecord fields (ticker, pipeline_type, result_text).
function runTitle(run: RunRecord): string {
  const ticker = run.ticker.toUpperCase()
  const labels: Record<string, string> = {
    research: '深度研究报告',
    dcf:      'DCF 估值分析',
    comps:    '可比公司分析',
    lbo:      'LBO 模型',
    earnings: '财报分析',
    ic_memo:  'IC Memo',
  }
  return `${ticker} ${labels[run.pipeline_type] ?? run.pipeline_type}`
}

// Derive snippet from result_text (first 100 chars).
// Data source: RunRecord.result_text from /api/runs.
function runSnippet(run: RunRecord): string {
  const txt = run.result_text
  if (!txt) return '暂无摘要。'
  return txt.length > 100 ? txt.slice(0, 100) + '…' : txt
}

// Human-readable time delta from ISO string.
// Data source: RunRecord.created_at from /api/runs.
function runRelativeTime(isoStr: string): string {
  const ts = new Date(isoStr).getTime()
  return Number.isNaN(ts) ? '—' : relativeTime(ts)
}

// ─── Sub-components ───────────────────────────────────────────

interface RptCardProps {
  type: string
  time: string
  name: string
  snip: string
  foot: readonly string[]
  isSample?: boolean
}

function RptCard({ type, time, name, snip, foot, isSample }: RptCardProps) {
  return (
    <div className="rpt">
      <div className="rpt-head">
        <span className="rpt-type">
          {type}
          {isSample && (
            <span style={{ color: 'var(--text-3)', marginLeft: 6, fontWeight: 400 }}>
              SAMPLE
            </span>
          )}
        </span>
        <span className="rpt-time">{time}</span>
      </div>
      <div className="rpt-name">{name}</div>
      <div className="rpt-snip">{snip}</div>
      <div className="rpt-foot">
        {foot.map((f, i) => (
          <span key={i}>
            {i > 0 && <span className="dot" />}
            {f}
          </span>
        ))}
      </div>
    </div>
  )
}

function RptSkeleton() {
  return (
    <div
      className="rpt"
      style={{ minHeight: 120, background: 'var(--bg-2)', border: '1px solid var(--line)' }}
      aria-label="加载中"
    />
  )
}

// ─── Main component ───────────────────────────────────────────

export default function Dashboard() {
  const setMode               = useUiStore((s) => s.setMode)
  const setActivityBarSelection = useUiStore((s) => s.setActivityBarSelection)
  const toggleAiPanel           = useUiStore((s) => s.toggleAiPanel)
  const aiPanelOpen             = useUiStore((s) => s.aiPanelOpen)

  // GET /api/runs — data source for 03 最近报告.
  // endpoint: /api/runs (schema: RunListResponse → RunRecord[])
  const { data: runsData, isLoading: runsLoading } = useQuery({
    queryKey: ['recent-runs'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/runs')
      if (error) return []
      return (data?.runs ?? []).slice(0, 4)
    },
  })

  const dateMeta = buildDateMeta()

  function handleAskAgent() {
    setMode('A')
    if (!aiPanelOpen) toggleAiPanel()
  }

  function handleRunPipeline() {
    setMode('B')
    setActivityBarSelection('pipelines')
  }

  function handlePipelineRow(id: string) {
    console.log('[Dashboard] TODO Phase 4: open pipeline runner for', id)
    setMode('B')
    setActivityBarSelection('pipelines')
  }

  function handleNewReport() {
    console.log('[Dashboard] TODO Phase 5: open report template picker')
  }

  // Build report cards from API data, or fall back to samples.
  const hasRealRuns = !runsLoading && runsData && runsData.length > 0

  return (
    <div className="dashboard-scroll">

      {/* ── Hero ──────────────────────────────────────────────── */}
      <div className="dash-hero">
        <div>
          <div className="dash-title">
            早上好，<span className="em">李哥</span>
          </div>
          <div className="dash-sub">{dateMeta}</div>
        </div>
        <div className="dash-meta">
          <div>BUILD <span className="v">v0.4.1-P0</span></div>
          <div>MODE A/B PASSING</div>
          <div>UPTIME 14d 06h</div>
        </div>
      </div>

      {/* ── 01 快捷启动 ───────────────────────────────────────── */}
      <div className="section-h">
        <h3><span className="num">01</span>快捷启动</h3>
        <span className="more">配置 →</span>
      </div>
      <div className="quick-grid">
        {/* Card 1 — MODE A */}
        <div className="quick-card" onClick={handleAskAgent} role="button" tabIndex={0}
          onKeyDown={(e) => e.key === 'Enter' && handleAskAgent()}>
          <span className="kbd">⌘L</span>
          <div className="ic-box">
            <IconSparkle size={18} />
          </div>
          <div className="name">向 Agent 提问</div>
          <div className="desc">自然语言驱动，Agent 自主选择 Pipeline 与工具完成任务</div>
          <div className="meta">MODE A · DEEPSEEK-CHAT</div>
        </div>

        {/* Card 2 — MODE B */}
        <div className="quick-card blue" onClick={handleRunPipeline} role="button" tabIndex={0}
          onKeyDown={(e) => e.key === 'Enter' && handleRunPipeline()}>
          <span className="kbd">⌘R</span>
          <div className="ic-box">
            <IconActivity size={18} />
          </div>
          <div className="name">运行 Pipeline</div>
          <div className="desc">代码强制的流水线，可复用、可审计、可批量执行</div>
          <div className="meta">MODE B · 6 PIPELINES</div>
        </div>

        {/* Card 3 — New Report */}
        <div className="quick-card green" onClick={handleNewReport} role="button" tabIndex={0}
          onKeyDown={(e) => e.key === 'Enter' && handleNewReport()}>
          <span className="kbd">⌘N</span>
          <div className="ic-box">
            <IconFileText size={18} />
          </div>
          <div className="name">新建报告</div>
          <div className="desc">从模板创建结构化研究报告，可附加 AI 协作改写</div>
          <div className="meta">MARKDOWN · 6 模板</div>
        </div>
      </div>

      {/* ── 02 常用 PIPELINE ──────────────────────────────────── */}
      <div className="section-h">
        <h3><span className="num">02</span>常用 PIPELINE</h3>
        <span className="more">查看全部 6 →</span>
      </div>
      <div className="pipe-list">
        {/* Header row */}
        <div className="pipe-row head">
          <span>ID</span>
          <span>名称</span>
          <span>数据源</span>
          <span>耗时</span>
          <span>运行次数</span>
          <span />
        </div>
        {PIPELINES.map((pl) => (
          <div
            key={pl.id}
            className="pipe-row"
            onClick={() => handlePipelineRow(pl.id)}
          >
            <span className="pipe-id">{pl.id}</span>
            <span className="pipe-nm">
              {pl.name}
              <span className="desc">{pl.desc}</span>
            </span>
            <span className="pipe-src">{pl.source}</span>
            <span className="pipe-time">{pl.time}</span>
            <span className="pipe-runs">{pl.runs} 次</span>
            <span className="pipe-action">
              <button
                className="pipe-run-btn"
                onClick={(e) => {
                  e.stopPropagation()
                  handlePipelineRow(pl.id)
                }}
              >
                RUN
              </button>
            </span>
          </div>
        ))}
      </div>

      {/* ── 03 最近报告 ───────────────────────────────────────── */}
      <div className="section-h">
        <h3><span className="num">03</span>最近报告</h3>
        <span className="more">报告库 →</span>
      </div>
      <div className="reports">
        {runsLoading ? (
          // Loading skeleton — 4 placeholders
          <>
            <RptSkeleton />
            <RptSkeleton />
            <RptSkeleton />
            <RptSkeleton />
          </>
        ) : hasRealRuns ? (
          // Real data from /api/runs
          (runsData as RunRecord[]).map((run) => (
            <RptCard
              key={run.run_id}
              type={pipelineTypeLabel(run.pipeline_type)}
              time={runRelativeTime(run.created_at)}
              name={runTitle(run)}
              snip={runSnippet(run)}
              foot={[run.ticker.toUpperCase(), run.status]}
            />
          ))
        ) : (
          // Empty state — fallback sample cards (not production data)
          // placeholder, not for production
          FALLBACK_REPORTS.map((r, i) => (
            <RptCard
              key={i}
              type={r.type}
              time={r.time}
              name={r.name}
              snip={r.snip}
              foot={r.foot}
              isSample={r.isSample}
            />
          ))
        )}
      </div>

    </div>
  )
}
