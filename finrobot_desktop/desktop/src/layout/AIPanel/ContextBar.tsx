// ContextBar — AI 侧栏上下文条
//
// 自动挂载（不可移除）：当前路由派生的上下文 chip + workspace_path chip。
// 与 AiChatTab 发给 /chat 的 context_bundle（route / ticker / artifact_id）
// 一一对应——用户看到什么 chip，模型就拿到什么上下文。
//
// History: 手动 pinned chip + "+ Add" popover 已于 2026-06-10 连根移除——
// popover 唯一候选源是 Phase-4 Tab 系统(openTab 零调用)，永远是空列表，
// 属于死管道(同批移除 uiStore 的 Tab/mention/selected_text)。

import { useLocation, useParams } from 'react-router-dom'
import { useUiStore } from '../../stores/uiStore'
import { useI18n } from '../../i18n'
import { IconDashboard, IconFileText, IconStar } from '../../lib/icons'

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

// ── ContextBar ────────────────────────────────────────────────────

export function ContextBar(): React.ReactElement {
  const { t, locale } = useI18n()
  const { ticker } = useParams<{ ticker?: string }>()
  const { pathname } = useLocation()
  const workspacePath = useUiStore((s) => s.workspacePath)

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
    </div>
  )
}
