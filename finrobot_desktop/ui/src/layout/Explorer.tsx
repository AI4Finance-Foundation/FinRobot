// Explorer — Phase 3: content driven by activityBarSelection.
// Each ActivityKey maps to a distinct tree-group set.
// Resize handle on right edge wires to uiStore.setExplorerWidth.

import { useRef, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useUiStore } from '../stores/uiStore'
import type { ActivityKey } from '../stores/uiStore'
import { useStocksStore } from '../stores/stocksStore'
import {
  IconPlus,
  IconRefresh,
  IconPipeline,
  IconFileText,
  IconActivity,
  IconDatabase,
  IconSettings,
  IconDashboard,
  IconStar,
  IconClock,
} from '../lib/icons'
import { PIPELINES } from '../lib/pipelines'
import { api } from '../api/client'
import type { Tab } from '../stores/uiStore'

// ─── Config per ActivityKey ───────────────────────────────────

const SECTION_TITLE: Record<ActivityKey, string> = {
  dashboard:   'WORKSPACE',
  pipelines:   'PIPELINES',
  reports:     'REPORTS',
  monitor:     'MONITOR',
  datasources: 'DATA SOURCES',
  watchlist:   'WATCHLIST',
  settings:    'SETTINGS',
}

// ─── Tree group + item types ──────────────────────────────────

interface TreeItem {
  id: string
  label: string
  tag?: string
  tagClass?: string  // 'live' | 'run' | ''
  icon: React.ReactNode
  onClick: () => void
  active?: boolean
}

interface TreeGroup {
  heading: string
  count?: number | string
  items: TreeItem[]
}

// ─── Section components ───────────────────────────────────────

function Group({ group }: { group: TreeGroup }) {
  return (
    <div className="tree-group">
      <div className="tree-head">
        <span className="caret">▾</span>
        <span>{group.heading}</span>
        {group.count !== undefined && (
          <span className="count">{group.count}</span>
        )}
      </div>
      {group.items.map((item) => (
        <div
          key={item.id}
          className={`tree-item${item.active ? ' active' : ''}`}
          onClick={item.onClick}
        >
          <span className="ic">{item.icon}</span>
          <span className="name">{item.label}</span>
          {item.tag !== undefined && (
            <span className={`tag${item.tagClass ? ' ' + item.tagClass : ''}`}>
              {item.tag}
            </span>
          )}
        </div>
      ))}
    </div>
  )
}

// ─── Per-activity content builders ───────────────────────────

function useDashboardGroups(openTabs: readonly Tab[], openTab: (t: Tab) => void): TreeGroup[] {
  const recentTabs = openTabs.filter((t) => t.id !== 'dashboard').slice(0, 5)
  return [
    {
      heading: '固定',
      items: [
        {
          id: 'dashboard',
          label: '工作台首页',
          icon: <IconDashboard size={13} />,
          onClick: () => openTab({ id: 'dashboard', kind: 'dashboard', title: '工作台' }),
          active: true,
        },
      ],
    },
    ...(recentTabs.length > 0
      ? [
          {
            heading: '最近打开',
            count: recentTabs.length,
            items: recentTabs.map((t) => ({
              id: t.id,
              label: t.title,
              icon: <IconFileText size={13} />,
              onClick: () => openTab(t),
            })),
          },
        ]
      : []),
  ]
}

function usePipelineGroups(openTab: (t: Tab) => void): TreeGroup[] {
  const stockPipelines = PIPELINES.filter((p) => p.category === 'stock')
  const sectorPipelines = PIPELINES.filter((p) => p.category === 'sector' || p.category === 'event')
  const otherPipelines = PIPELINES.filter((p) => p.category === 'portfolio' || p.category === 'batch')

  function makePipelineItem(pl: (typeof PIPELINES)[number]): TreeItem {
    const isLive = pl.id === 'PL-004'
    const isRunning = pl.id === 'PL-002'
    return {
      id: `pipeline:${pl.id}`,
      label: pl.name,
      tag: isLive ? '●' : isRunning ? 'RUN' : pl.id,
      tagClass: isLive ? 'live' : isRunning ? 'run' : '',
      icon: <IconPipeline size={13} />,
      onClick: () =>
        openTab({
          id: `pipeline:${pl.id}`,
          kind: 'pipeline',
          title: `${pl.id} ${pl.name}`,
          payload: { pipelineId: pl.id },
        }),
    }
  }

  return [
    {
      heading: '个股',
      count: stockPipelines.length,
      items: stockPipelines.map(makePipelineItem),
    },
    {
      heading: '行业 / 事件',
      count: sectorPipelines.length,
      items: sectorPipelines.map(makePipelineItem),
    },
    {
      heading: '组合 / 批处理',
      count: otherPipelines.length,
      items: otherPipelines.map(makePipelineItem),
    },
  ]
}

const REPORT_FILES = [
  'NVDA-Q3-FY26.md',
  '半导体板块周报.md',
  '茅台-估值复盘.md',
  '美联储议息纪要.md',
  // TODO Phase 5: load from local workspace dir
] as const

function useReportGroups(openTab: (t: Tab) => void): TreeGroup[] {
  return [
    {
      heading: '按日期',
      count: REPORT_FILES.length,
      items: REPORT_FILES.map((name) => ({
        id: `report:${name}`,
        label: name,
        icon: <IconFileText size={13} />,
        onClick: () =>
          openTab({
            id: `report:${name}`,
            kind: 'report',
            title: name,
            payload: { reportId: name },
          }),
      })),
    },
  ]
}

function MonitorGroups({ openTab }: { openTab: (t: Tab) => void }) {
  // GET /api/runs?limit=3 — real data for "已完成" group
  const { data } = useQuery({
    queryKey: ['explorer-runs'],
    queryFn: async () => {
      const { data: resp, error } = await api.GET('/api/runs')
      if (error) return []
      return (resp?.runs ?? []).slice(0, 3)
    },
    staleTime: 30_000,
  })

  const completedItems: TreeItem[] =
    data?.map((run) => ({
      id: `monitor:run:${run.run_id}`,
      label: `${run.ticker.toUpperCase()} ${run.pipeline_type}`,
      tag: run.status,
      tagClass: run.status === 'completed' ? 'live' : '',
      icon: <IconClock size={13} />,
      onClick: () =>
        openTab({
          id: 'monitor',
          kind: 'monitor',
          title: '任务监控',
        }),
    })) ?? []

  // Hardcoded running tasks — placeholder, not for production
  const runningItems: TreeItem[] = [
    {
      id: 'monitor:run:live-1',
      label: 'AAPL 个股深度分析',
      tag: '●',
      tagClass: 'live',
      icon: <IconActivity size={13} />,
      onClick: () => openTab({ id: 'monitor', kind: 'monitor', title: '任务监控' }),
    },
    {
      id: 'monitor:run:live-2',
      label: 'NVDA 财报速读',
      tag: 'RUN',
      tagClass: 'run',
      icon: <IconActivity size={13} />,
      onClick: () => openTab({ id: 'monitor', kind: 'monitor', title: '任务监控' }),
    },
  ]

  const groups: TreeGroup[] = [
    { heading: '运行中', count: runningItems.length, items: runningItems },
    { heading: '已完成', count: completedItems.length, items: completedItems },
    { heading: '失败', count: 0, items: [] },
  ]

  return (
    <>
      {groups.map((g) => (
        <Group key={g.heading} group={g} />
      ))}
    </>
  )
}

const DATASOURCE_ITEMS: TreeItem[] = [
  { id: 'ds:finrobot', label: 'FinRobot', tag: 'ON', tagClass: 'live', icon: <IconDatabase size={13} />, onClick: () => {} },
  { id: 'ds:realtime', label: '实时行情', tag: 'ON', tagClass: 'live', icon: <IconActivity size={13} />, onClick: () => {} },
  { id: 'ds:edgar',    label: 'SEC EDGAR', tag: 'ON', tagClass: 'live', icon: <IconFileText size={13} />, onClick: () => {} },
  { id: 'ds:fmp',      label: 'FMP',       tag: '',   icon: <IconDatabase size={13} />, onClick: () => {} },
  { id: 'ds:finnhub',  label: 'Finnhub',   tag: '',   icon: <IconDatabase size={13} />, onClick: () => {} },
]

function useDataSourceGroups(): TreeGroup[] {
  return [
    { heading: '数据源', items: DATASOURCE_ITEMS },
  ]
}

// Watchlist change percentages are hardcoded placeholders.
// placeholder, not for production — TODO Phase 5: real-time quotes
const WATCHLIST_STATIC: Record<string, { pct: string; color: string }> = {
  NVDA: { pct: '+3.87%', color: 'var(--green)' },
  AAPL: { pct: '+1.24%', color: 'var(--green)' },
  TSLA: { pct: '-0.92%', color: 'var(--red)'   },
  MSFT: { pct: '+0.61%', color: 'var(--green)' },
  '600519': { pct: '+0.41%', color: 'var(--green)' },
}

function useWatchlistGroups(openTab: (t: Tab) => void): TreeGroup[] {
  const recentTickers = useStocksStore((s) => s.recentTickers)
  const watchlist = useStocksStore((s) => s.watchlist)

  // Merge watchlist + recentTickers, deduplicated
  const allTickers = Array.from(
    new Set([...Array.from(watchlist), ...recentTickers]),
  ).slice(0, 12)

  const items: TreeItem[] = allTickers.map((ticker) => {
    const meta = WATCHLIST_STATIC[ticker]
    return {
      id: `watchlist:${ticker}`,
      label: ticker,
      tag: meta?.pct ?? '',
      // inline style applied below via JSX directly on the tag span
      icon: (
        <span
          style={{
            width: 14,
            display: 'inline-block',
            textAlign: 'center',
            fontFamily: "'JetBrains Mono',monospace",
            fontSize: 9,
            color: meta?.color ?? 'var(--text-2)',
          }}
        >
          ●
        </span>
      ),
      onClick: () =>
        openTab({
          id: `watchlist:${ticker}`,
          kind: 'watchlist',
          title: ticker,
          payload: { ticker },
        }),
    }
  })

  // If no tickers yet, provide defaults
  const fallback: TreeItem[] = items.length > 0 ? items : (
    ['NVDA', 'AAPL', 'TSLA'].map((ticker) => {
      const meta = WATCHLIST_STATIC[ticker]!
      return {
        id: `watchlist:${ticker}`,
        label: ticker,
        tag: meta.pct,
        icon: (
          <span
            style={{
              width: 14,
              display: 'inline-block',
              textAlign: 'center',
              fontFamily: "'JetBrains Mono',monospace",
              fontSize: 9,
              color: meta.color,
            }}
          >
            ●
          </span>
        ),
        onClick: () =>
          openTab({
            id: `watchlist:${ticker}`,
            kind: 'watchlist',
            title: ticker,
            payload: { ticker },
          }),
      }
    })
  )

  return [
    { heading: '自选股', count: fallback.length, items: fallback },
  ]
}

const SETTINGS_GROUPS: Array<{ heading: string; items: Array<{ id: string; label: string }> }> = [
  { heading: '账户', items: [{ id: 'settings:account', label: '账户信息' }] },
  { heading: 'API 密钥', items: [{ id: 'settings:apikeys', label: 'API 密钥管理' }] },
  { heading: '模型', items: [{ id: 'settings:model', label: '模型选择' }] },
  { heading: '外观', items: [{ id: 'settings:appearance', label: '语言 / 主题' }] },
]

function useSettingsGroups(openTab: (t: Tab) => void): TreeGroup[] {
  return SETTINGS_GROUPS.map((sg) => ({
    heading: sg.heading,
    items: sg.items.map((item) => ({
      id: item.id,
      label: item.label,
      icon: <IconSettings size={13} />,
      onClick: () =>
        openTab({
          id: 'settings',
          kind: 'settings',
          title: '设置',
        }),
    })),
  }))
}

// ─── Drag-resize handle ───────────────────────────────────────

function ResizeHandle() {
  const setExplorerWidth = useUiStore((s) => s.setExplorerWidth)
  const explorerWidth = useUiStore((s) => s.explorerWidth)

  const dragging = useRef(false)
  const startX = useRef(0)
  const startW = useRef(0)

  const onMouseDown = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault()
      dragging.current = true
      startX.current = e.clientX
      startW.current = explorerWidth

      function onMove(ev: MouseEvent) {
        if (!dragging.current) return
        const delta = ev.clientX - startX.current
        setExplorerWidth(startW.current + delta)
      }
      function onUp() {
        dragging.current = false
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseup', onUp)
      }
      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
    },
    [explorerWidth, setExplorerWidth],
  )

  return (
    <div
      onMouseDown={onMouseDown}
      style={{
        position: 'absolute',
        right: 0,
        top: 0,
        bottom: 0,
        width: 4,
        cursor: 'col-resize',
        zIndex: 10,
      }}
    />
  )
}

// ─── Main component ───────────────────────────────────────────

export function Explorer(): React.ReactElement {
  const activityBarSelection = useUiStore((s) => s.activityBarSelection)
  const explorerWidth = useUiStore((s) => s.explorerWidth)
  const openTab = useUiStore((s) => s.openTab)
  const openTabs = useUiStore((s) => s.openTabs)

  const title = SECTION_TITLE[activityBarSelection]

  // Build groups per activity selection
  const dashboardGroups = useDashboardGroups(openTabs, openTab)
  const pipelineGroups = usePipelineGroups(openTab)
  const reportGroups = useReportGroups(openTab)
  const datasourceGroups = useDataSourceGroups()
  const watchlistGroups = useWatchlistGroups(openTab)
  const settingsGroups = useSettingsGroups(openTab)

  function renderContent() {
    switch (activityBarSelection) {
      case 'dashboard':
        return dashboardGroups.map((g) => <Group key={g.heading} group={g} />)
      case 'pipelines':
        return pipelineGroups.map((g) => <Group key={g.heading} group={g} />)
      case 'reports':
        return reportGroups.map((g) => <Group key={g.heading} group={g} />)
      case 'monitor':
        return null  // rendered inline with MonitorGroups (needs hook)
      case 'datasources':
        return datasourceGroups.map((g) => <Group key={g.heading} group={g} />)
      case 'watchlist':
        return watchlistGroups.map((g) => <Group key={g.heading} group={g} />)
      case 'settings':
        return settingsGroups.map((g) => <Group key={g.heading} group={g} />)
    }
  }

  return (
    <aside
      className="sidebar-left"
      data-testid="explorer"
      style={{ width: explorerWidth, position: 'relative' }}
    >
      <div className="sb-header">
        <span className="sb-title">{title}</span>
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
        {activityBarSelection === 'monitor' ? (
          <MonitorGroups openTab={openTab} />
        ) : (
          renderContent()
        )}
      </div>

      <ResizeHandle />
    </aside>
  )
}

