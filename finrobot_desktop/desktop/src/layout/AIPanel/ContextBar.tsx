// ContextBar — AI 侧栏上下文条 (Phase 4, REFACTOR §2.5.2 / §3)
//
// 自动挂载：当前激活 Tab + workspace_path（不可移除）
// 手动挂载：来自 contextBundle.pinned（可点击 × 移除）
// "+ 添加" 按钮：展开固定列表 popover，选中后 addPinned

import { useState, useRef, useEffect } from 'react'
import { useLocation, useParams } from 'react-router-dom'
import { useUiStore } from '../../stores/uiStore'
import type { ContextItem } from '../../stores/uiStore'
import { useI18n } from '../../i18n'
import { IconDashboard, IconPipeline, IconFileText, IconStar } from '../../lib/icons'

// ── Route-derived active context ─────────────────────────────────
//
// The old "active Tab" chip read uiStore.activeTabId, but AppShell removed the
// tab system so it was frozen on the dashboard tab — a fake chip that lied
// about what the user was looking at (BUG-20260602-038). We now derive the
// auto-mounted chip from the URL so it matches EXACTLY what AiChatTab sends to
// /chat as context_bundle (route / ticker / artifact_id). When the route
// carries no analyst context (landing/settings), there is no fake chip at all.

interface ActiveContext {
  label: string
  icon: React.ReactNode
}

function deriveActiveContext(
  pathname: string,
  ticker: string | undefined,
  zh: boolean,
): ActiveContext | null {
  // /stocks/:ticker/runs/:artifactId — a report is open
  if (/^\/stocks\/[^/]+\/runs\//.test(pathname) && ticker) {
    return {
      label: zh ? `${ticker.toUpperCase()} 研报` : `${ticker.toUpperCase()} report`,
      icon: <IconFileText size={10} />,
    }
  }
  // /stocks/:ticker — a ticker workspace
  if (/^\/stocks\/[^/]+$/.test(pathname) && ticker) {
    return { label: ticker.toUpperCase(), icon: <IconStar size={10} /> }
  }
  // /coverage* — coverage desk
  if (pathname.startsWith('/coverage')) {
    return { label: zh ? '研究覆盖' : 'Coverage', icon: <IconDashboard size={10} /> }
  }
  // landing / settings / etc. — no analyst context to pin honestly
  return null
}

// ── 图标映射 ─────────────────────────────────────────────────────

function ChipIcon({ kind }: { kind: ContextItem['kind'] }): React.ReactElement {
  switch (kind) {
    case 'pipeline':
      return <IconPipeline size={10} />
    case 'report':
      return <IconFileText size={10} />
    case 'symbol':
      return <IconStar size={10} />
    case 'workspace':
      return <IconDashboard size={10} />
    default:
      return <IconDashboard size={10} />
  }
}

// ── 固定 chip（自动挂载，不可移除） ──────────────────────────────

interface FixedChipProps {
  label: string
  icon: React.ReactNode
}

function FixedChip({ label, icon }: FixedChipProps): React.ReactElement {
  return (
    <span className="ctx-chip">
      <span className="ic">{icon}</span>
      {label}
    </span>
  )
}

// ── 可移除 chip（pinned） ─────────────────────────────────────────

interface PinnedChipProps {
  item: ContextItem
  onRemove: (id: string) => void
}

function PinnedChip({ item, onRemove }: PinnedChipProps): React.ReactElement {
  const { t } = useI18n()
  return (
    <span className="ctx-chip">
      <span className="ic">
        <ChipIcon kind={item.kind} />
      </span>
      {item.label}
      <button
        className="x"
        title={t('chatpanel.context.remove')}
        onClick={() => onRemove(item.id)}
        type="button"
      >
        ×
      </button>
    </span>
  )
}

// ── Popover 候选列表 ──────────────────────────────────────────────

interface PopoverProps {
  openTabs: Array<{ id: string; kind: string; title: string }>
  onSelect: (item: ContextItem) => void
  onClose: () => void
}

function CtxPopover({ openTabs, onSelect, onClose }: PopoverProps): React.ReactElement {
  const ref = useRef<HTMLDivElement>(null)
  const { t } = useI18n()

  useEffect(() => {
    const handler = (e: MouseEvent): void => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose()
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  // 最近 5 个 Tab（排除 dashboard / workspace 类型，它们已经被 ContextBar
  // 自动挂载为 FixedChip，重复挂载会导致同一上下文出现两个 chip）。
  const recentTabs = openTabs
    .filter((t) => t.kind !== 'dashboard' && t.kind !== 'workspace')
    .slice(0, 5)

  // 候选项历史上还包含 { kind: 'workspace', label: 'Workspace' }，但 workspace
  // 已经是自动挂载的 FixedChip，再放到 popover 里只会让用户多挂一个重复 chip。
  // 当未来真有不重叠的静态候选项时再恢复这个 section。

  return (
    <div className="ctx-popover" ref={ref}>
      {recentTabs.length > 0 ? (
        <>
          <div className="ctx-popover-section">{t('chatpanel.context.openTabs')}</div>
          {recentTabs.map((tab) => (
            <button
              key={tab.id}
              className="ctx-popover-item"
              onClick={() => {
                onSelect({
                  kind: 'tab',
                  id: tab.id,
                  label: tab.title,
                })
                onClose()
              }}
              type="button"
            >
              <span className="ic">
                <IconFileText size={10} />
              </span>
              {tab.title}
            </button>
          ))}
        </>
      ) : (
        <div className="ctx-popover-section">{t('chatpanel.context.empty')}</div>
      )}
    </div>
  )
}

// ── ContextBar ────────────────────────────────────────────────────

export function ContextBar(): React.ReactElement {
  const { t, locale } = useI18n()
  const { ticker } = useParams<{ ticker?: string }>()
  const { pathname } = useLocation()
  const workspacePath = useUiStore((s) => s.workspacePath)
  const pinned = useUiStore((s) => s.contextBundle.pinned)
  const openTabs = useUiStore((s) => s.openTabs)
  const addPinned = useUiStore((s) => s.addPinned)
  const removePinned = useUiStore((s) => s.removePinned)

  const [popoverOpen, setPopoverOpen] = useState(false)

  // Route-derived active context — matches what AiChatTab sends to /chat.
  const activeContext = deriveActiveContext(pathname, ticker, locale === 'zh')

  // workspace_path 截短做 chip 标签：去掉 home 前缀只显示 16 字符，避免
  // 整条路径撑爆 ContextBar。
  const wsLabel = workspacePath.replace(/^~\//, '').slice(0, 16)

  return (
    <div className="ai-context">
      <span className="ctx-label">{t('chatpanel.context.label')}</span>

      {/* 自动挂载：当前路由派生的上下文（report / ticker / coverage） */}
      {activeContext && <FixedChip label={activeContext.label} icon={activeContext.icon} />}

      {/* 自动挂载：workspace_path */}
      <FixedChip label={wsLabel || 'workspace'} icon={<IconDashboard size={10} />} />

      {/* 用户挂载的 pinned 项 */}
      {pinned.map((item) => (
        <PinnedChip key={`${item.kind}:${item.id}`} item={item} onRemove={removePinned} />
      ))}

      {/* + 添加 按钮 */}
      <button className="ctx-add" onClick={() => setPopoverOpen((v) => !v)} type="button">
        {t('chatpanel.context.add')}
      </button>

      {popoverOpen && (
        <CtxPopover
          openTabs={openTabs}
          onSelect={addPinned}
          onClose={() => setPopoverOpen(false)}
        />
      )}
    </div>
  )
}
