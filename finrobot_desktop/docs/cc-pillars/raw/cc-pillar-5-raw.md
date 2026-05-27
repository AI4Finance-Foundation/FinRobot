# Raw Research: CC Auto-compact + Memory (Pillar 5)

**来源**: Explore 子 agent 通读 CC `src/services/compact/`、`src/memdir/`、`src/services/snip/`、`src/tasks.ts`
**日期**: 2026-05-12

---

## A. 5 种压缩策略

### A.1 Auto-compact（proactive）

**触发** (`autoCompact.ts:72-91, 160-238`):
- `threshold = effectiveContextWindow - AUTOCOMPACT_BUFFER_TOKENS (13K)`
- `effectiveContextWindow = getContextWindowForModel() - MAX_OUTPUT_TOKENS_FOR_SUMMARY (20K)`
- env `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE` 可覆盖

**执行**: `autoCompactIfNeeded()` (autoCompact.ts:241-351) → 先 sessionMemoryCompaction → 失败回退 `compactConversation()`（LLM 摘要）

**Circuit breaker**: `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3`

### A.2 Microcompact

**两条路径** (`microCompact.ts:252-293`)：
- **Cached MC**：用 API `cache_edits` 删除旧工具结果，**不修改本地 message**。阈值 GrowthBook `triggerThreshold`（default 180K）+ `keepRecent` 工具数
- **Time-based MC**：上次助手回复 > `gapThresholdMinutes` (60min)，直接修改 message 内容设为 `[Old tool result content cleared]`，保留最近 5 工具

**vs autocompact**: incremental, single-turn, **不改变对话逻辑**

### A.3 Reactive Compact

**触发**: API 返回 `prompt_too_long` (413)，feature `REACTIVE_COMPACT` + growthbook `tengu_cobalt_raccoon`

**流程**: 截断旧消息组（API round groups），最多 3 次 `MAX_PTL_RETRIES`

**互斥**: reactive-only 开启时 `shouldAutoCompact()` 返回 false

### A.4 Context Collapse

**模式** (`autoCompact.ts:215-223`): feature `CONTEXT_COLLAPSE` + gate
- 在 90% commit / 95% block 间主动折叠
- 折叠：message 树从尾部逐步摘要到中间检查点
- 触发时禁用 proactive autocompact

### A.5 Snip

**作用** (`microCompact.ts:166-167`): 删除特定消息（hook results、progress messages）不 summarize

与 microcompact 正交、可共存。

---

## B. Compact 算法

### B.1 LLM vs 规则

- Autocompact / Partial-compact: 用 LLM（claude-opus 或主线程模型）
- Microcompact（cached & time-based）: 纯规则 + GrowthBook config
- Reactive Compact: API 错误驱动 + 规则式头截断

### B.2 保留 vs 丢弃

| 策略 | 保留 | 丢弃 |
|---|---|---|
| Autocompact | 最后 N 消息 + 摘要 + 附件 | 早期所有原文 |
| Cached MC | message 本体 | 旧工具结果（cache_edits） |
| Time-based MC | 最近 5 工具 | 早期工具结果（置空） |
| Reactive | 最近消息组 | 最旧 N 组 |
| Collapse | 尾部 5% | 中间 90% → 摘要 |

### B.3 压缩比

- Autocompact: 80K → 50K（含附件）
- Cached MC: 删除 5-20 工具 = 10-50K token 省
- Time-based MC: 单轮 5-15K 清理

### B.4 失败计数

- `MAX_CONSECUTIVE_AUTOCOMPACT_FAILURES = 3`
- `MAX_PTL_RETRIES = 3`（每次截 20%）

---

## C. Memory 系统

### C.1 文件组织 (`memdir/paths.ts`)

```
~/.claude/projects/{sanitized-git-root}/
  memory/
    ├── MEMORY.md           # 索引（200 行上限）
    ├── topic_files/
    │   ├── user_*.md
    │   ├── feedback_*.md
    │   ├── project_*.md
    │   └── reference_*.md
    ├── team/               # feature TEAMMEM
    └── logs/               # feature KAIROS, YYYY/MM/YYYY-MM-DD.md
```

扫描上限：200 文件；MEMORY.md 上限：200 行 OR 25KB

### C.2 三种 Memory 模式

| 模式 | 触发 | 用途 |
|---|---|---|
| Auto Memory（KAIROS disabled）| 默认 | 跨会话记忆索引 + 主题文件 |
| KAIROS（Assistant mode）| feature KAIROS + getKairosActive() | 长会话日志 + 夜间 /dream 摘要 |
| Team Memory | feature TEAMMEM + isTeamMemoryEnabled() | 协作记忆 |

### C.3 Memory 类型

```typescript
type MemoryType = 'user' | 'feedback' | 'project' | 'reference'
```

frontmatter:
```yaml
---
name: {{slug}}
description: {{relevance hint}}
type: user|feedback|project|reference
---
```

### C.4 写入触发

| 类型 | 何时 |
|---|---|
| User | 学到用户角色 / 偏好 / 知识 |
| Feedback | 用户修正或确认非显而易见方法 |
| Project | who/what/why/when（快速变化）|
| Reference | 外部系统的用途 + 位置 |

**主动触发**: 用户 `/remember` 或 `saveMemory()` 调用

### C.5 过期

无自动过期。陈旧检测：调用侧 query 时检查 memory 与代码当前状态冲突。

---

## D. Task 概念

`src/tasks.ts` + `tasks/` 目录

- **存在但**: Task ID 用于后台 agent 追踪（LocalAgentTask、RemoteAgentTask、DreamTask）
- **不用于**: 单轮 user turn 的内部 checkpoint

```typescript
type TaskState = {
  type: string
  id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress?: ProgressInfo
  error?: string
  output?: string
}
```

存储：AppState.tasks（内存）+ `~/.claude/tasks/{team-name}/`

---

## E. 关键代码定位

| 功能 | 文件:行 |
|---|---|
| getAutoCompactThreshold | `autoCompact.ts:72-91` |
| shouldAutoCompact | `autoCompact.ts:160-238` |
| autoCompactIfNeeded | `autoCompact.ts:241-351` |
| compactConversation | `compact.ts:387-763` |
| streamCompactSummary | `compact.ts:1136-1396` |
| BASE_COMPACT_PROMPT | `prompt.ts:61-77` |
| buildMemoryPrompt | `memdir.ts:272-316` |
| loadMemoryPrompt | `memdir.ts:419-507` |
| getAutoMemPath | `paths.ts:223-235` |
| scanMemoryFiles | `memoryScan.ts:35-77` |
| isWithheldPromptTooLong | `query.ts:811` |
| parsePromptTooLongTokenCounts | `errors.ts:62-96` |

---

## F. 压缩与 Prompt Cache 的协同

- Autocompact → `notifyCompaction()` → reset cache baseline
- Cached MC → `notifyCacheDeletion()`（合法的 cache_deleted）
- Time-based MC → `notifyCacheDeletion()` 抑制假阳性
- token 改变 > 5% 且无通知 → 标记为 break

---

## G. 未理解的部分

1. Context Collapse 具体实现
2. Session Memory Compact 准确性判定
3. KAIROS /dream 摘要算法
4. Team Memory 冲突解决
5. Task 与 compact 的交互
