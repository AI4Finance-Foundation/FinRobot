# Raw Research: Claude Code Query Loop (Pillar 1)

**来源**: Explore 子 agent 深度通读 `/Users/zhunihaoyun/Desktop/code/claude-code/src/`
**日期**: 2026-05-12
**用途**: 作为 Pillar 1 综合决策文档的事实依据

> 这份文档是子 agent 的原始研究笔记，未经编辑。事实陈述，不含决策。

---

## A. 整体架构

### 1. 唯一入口函数

**主入口：** `query()` 函数（位置：`src/query.ts:219-238`）

```typescript
export async function* query(
  params: QueryParams,
): AsyncGenerator<
  | StreamEvent
  | RequestStartEvent
  | Message
  | TombstoneMessage
  | ToolUseSummaryMessage,
  Terminal
> {
  const consumedCommandUuids: string[] = []
  const terminal = yield* queryLoop(params, consumedCommandUuids)
  for (const uuid of consumedCommandUuids) {
    notifyCommandLifecycle(uuid, 'completed')
  }
  return terminal
}
```

**实际循环实现：** `queryLoop()` 函数（位置：`src/query.ts:241-1729`）

### 2. 输入对象

**类型：** `QueryParams`（位置：`src/query.ts:181-199`）

字段：messages、systemPrompt、userContext、systemContext、canUseTool、toolUseContext、fallbackModel、querySource、maxOutputTokensOverride、maxTurns、skipCacheWrite、taskBudget、deps。

### 3. 输出类型

**AsyncGenerator 产出：** StreamEvent / RequestStartEvent / Message / TombstoneMessage / ToolUseSummaryMessage

**返回值（Terminal）：**

```typescript
type Terminal =
  | { reason: 'completed' }
  | { reason: 'max_turns'; turnCount: number }
  | { reason: 'aborted_streaming' | 'aborted_tools' }
  | { reason: 'prompt_too_long' | 'image_error' | 'blocking_limit' | 'model_error'; error?: unknown }
  | { reason: 'hook_stopped' }
```

### 4. 调用关系（3 层链）

```
QueryEngine.submitMessage()         [入口装饰器]
  ↓
query()                              [消费命令 UUID，处理 stop hooks 通知]
  ↓
queryLoop()                          [核心循环状态机]
  ├→ deps.callModel()                [queryModelWithStreaming → queryModel]
  ├→ runTools() / StreamingToolExecutor  [工具执行编排]
  ├→ handleStopHooks()
  ├→ deps.autocompact()
  └→ [递归：继续下一个 turn]
```

---

## B. 状态机

### 1. 显式状态（`State` 类型，`src/query.ts:204-217`）

```typescript
type State = {
  messages: Message[]
  toolUseContext: ToolUseContext
  autoCompactTracking: AutoCompactTrackingState | undefined
  maxOutputTokensRecoveryCount: number
  hasAttemptedReactiveCompact: boolean
  maxOutputTokensOverride: number | undefined
  pendingToolUseSummary: Promise<ToolUseSummaryMessage | null> | undefined
  stopHookActive: boolean | undefined
  turnCount: number
  transition: Continue | undefined
}
```

### 2. 隐式阶段序列（单次迭代）

1. **Pre-API setup** (line 301-649)：内存预取、Snip + microcompact、上下文折叠检查、自动压缩、阻塞限制检查
2. **API call + streaming** (line 652-863)：deps.callModel() 流式处理、缓存编辑、流事件消费、工具调用块积累
3. **Post-streaming processing** (line 864-1357)：流式工具完成、Abort 检查、max_output_tokens 错误恢复、stop hooks、token 预算
4. **Tool execution** (line 1360-1482)：工具编排（顺序或流式）、附件消息（memory、skill、command）、tool use 摘要异步生成
5. **Recursion or termination** (line 1504-1728)：Abort、maxTurns、状态更新 + continue / return

### 3. 状态转移条件

| Continue Reason | 条件 | 动作 | 位置 |
|---|---|---|---|
| `collapse_drain_retry` | 413 且未尝试过 collapse drain | 执行 contextCollapse.recoverFromOverflow() | line 1110 |
| `reactive_compact_retry` | 413 或媒体大小错误，reactive compact 成功 | 应用压缩结果 | line 1162 |
| `max_output_tokens_escalate` | max_output_tokens 且无覆盖，gate 开启 | 设置 override = 64k | line 1217 |
| `max_output_tokens_recovery` | max_output_tokens 且恢复次数 < 3 | 注入 "resume" 消息 | line 1245 |
| `stop_hook_blocking` | stop hooks 返回 blockingErrors | 添加错误消息 | line 1302 |
| `token_budget_continuation` | token 预算未耗尽 | 注入续传提示 | line 1338 |
| `next_turn` | tool_use blocks 存在且未超 maxTurns | turnCount + 1 | line 1725 |

### 4. 退出条件

- `'completed'` — 正常完成（无 tool_use）
- `'max_turns'` — 超过轮数限制
- `'aborted_streaming'` / `'aborted_tools'` — 中止
- `'prompt_too_long'` — 413 恢复失败
- `'image_error'` — 媒体大小错误恢复失败
- `'blocking_limit'` — 硬阻塞限制
- `'model_error'` — 模型调用异常
- `'hook_stopped'` — hook 停止

### 5. Turn 计数

- 初始 `turnCount = 1`（line 276）
- 递增：`nextTurnCount = turnCount + 1`（line 1679）
- 检查：`if (maxTurns && nextTurnCount > maxTurns)` → return（line 1705）

---

## C. 模型调用

### 1. 入口

`queryModelWithStreaming()`（`src/services/api/claude.ts:752-779`）。
内部调用 `queryModel()` → `queryModelWithRetry()` → `withRetry()` → `getAnthropicClient().beta.messages.stream()`。

### 2. 请求构建（query.ts:659-707）

```typescript
deps.callModel({
  messages: prependUserContext(messagesForQuery, userContext),
  systemPrompt: fullSystemPrompt,
  thinkingConfig: toolUseContext.options.thinkingConfig,
  tools: toolUseContext.options.tools,
  signal: toolUseContext.abortController.signal,
  options: {
    model: currentModel,
    fastMode: appState.fastMode,
    toolChoice: undefined,
    isNonInteractiveSession: true,
    fallbackModel,
    maxOutputTokensOverride,
    mcpTools: appState.mcp.tools,
    taskBudget: { total, remaining? },
    // ... 15+ 其他选项
  }
})
```

### 3. 流式 vs 非流式

主路径：流式（withStreamingVCR 包装）。
失败时降级到非流式（FallbackTriggeredError 触发）。
非流式 timeout：120s 远程 / 300s 本地。

流事件类型：`message_start` / `content_block_start` / `content_block_delta` / `content_block_stop` / `message_delta` / `message_stop`。

### 4. 重试策略

`withRetry()` 包装：
- 触发：5xx 非 500、429、特定 API 错误
- 次数：3-5 次（基于 RetryContext）
- 退避：指数 + jitter
- 529 + fallbackModel → FallbackTriggeredError（切换模型）

### 5. Prompt Caching

启用条件：Opus 3.5+、Statsig gate `tengu_prompt_cache_v1`、非 Ant 内部模式。
标记位置：system prompt 末尾 + 用户消息最后一个内容块，添加 `cache_control: { type: 'ephemeral' }`。
跨界：compact 会清空缓存。Prompt cache 1h 过期。

---

## D. Tool 执行

### 1. 顺序 vs 并行（query.ts:1366-1382）

```typescript
const toolUpdates = streamingToolExecutor
  ? streamingToolExecutor.getRemainingResults()
  : runTools(toolUseBlocks, assistantMessages, canUseTool, toolUseContext)
```

并行条件：gate `tengu_streaming_tool_execution2` 开启。
启用时：模型流式响应时就开始执行工具（拓扑排序）。
禁用时：等所有工具块收集完毕再顺序执行。

### 2. Tool Result 转换（query.ts:1384-1408）

工具结果转为 `tool_result` block（在 user message 中）：
```
{ type: 'tool_result', tool_use_id: string, content: string, is_error: boolean }
```

### 3. 失败处理

- 超时 → `is_error: true`
- 权限拒绝 → synthetic "Permission denied"
- 运行时异常 → error message + is_error=true
- 中止 → "Interrupted by user"

### 4. 权限审批（query.ts:673-679）

```typescript
const wrappedCanUseTool: CanUseToolFn = async (...) => {
  const result = await canUseTool(...)
  if (result.behavior !== 'allow') {
    this.permissionDenials.push({
      tool_name: sdkCompatToolName(tool.name),
      tool_use_id: toolUseID,
      tool_input: input,
    })
  }
  return result
}
```

---

## E. Stop Reason 处理

| stop_reason | 行为 | 代码位置 |
|---|---|---|
| `end_turn` | 正常完成，无 tool_use → return 'completed' | 1062-1357 |
| `tool_use` | 收集工具块，进入 tool execution phase | 832-845, 1360+ |
| `max_tokens` | 立即 withhold，尝试恢复（escalate→recovery） | 1188-1256 |
| `refusal` | 作为 content block 返回，无特殊处理 | (作为文本) |
| `stop_sequence` | 不直接处理 | (作为文本) |

捕获自 `message_delta`（query.ts:806-808）：

```typescript
if (message.event.delta.stop_reason != null) {
  lastStopReason = message.event.delta.stop_reason
}
```

---

## F. 边界 case

### 1. max_tokens 续传（query.ts:1185-1256）

**Phase 1: Escalate（一次）**
- 条件：初次 hit + override 未设置 + gate 开启
- 动作：设置 `maxOutputTokensOverride = 64000`，continue
- 目的：从默认 8k → 64k

**Phase 2: Recovery（最多 3 次）**
- 条件：`maxOutputTokensRecoveryCount < 3`
- 消息：`"Output token limit hit. Resume directly — no apology..."`
- 动作：递增计数，continue

**Phase 3: 放弃**
- 超过 3 次 → yield error message → return

### 2. JSON 格式错误

工具输入 JSON 错乱：backfill 机制（query.ts:742-787）—— 模型流式发送的 tool_use.input 可能不完整，yield 前克隆并修复（仅添加 missing 字段，不覆盖）。

### 3. 网络/API 错误（query.ts:893-953）

```typescript
catch (innerError) {
  if (innerError instanceof FallbackTriggeredError && fallbackModel) {
    // 清理已收集的 assistant/tool 块、重置 executor
    // 剥离签名块（thinking）防止模型混合
    // 注入系统消息通知用户
    currentModel = fallbackModel
    attemptWithFallback = true
    continue  // 重新进入 while
  }
  throw innerError
}
```

真实错误路径：
- ImageSizeError → return 'image_error'
- 其他异常 → yield synthetic error + return 'model_error'

### 4. 工具死循环防护

无显式死循环防护，依赖于：
- `maxTurns` 限制总轮数
- `token_budget` 限制 token 消耗
- `max_tokens` escalation + recovery 上限
- Stop hooks 可 `preventContinuation` → return 'hook_stopped'

### 5. Token 预算

**Proactive autocompact**（query.ts:453-543）：
- 计算当前 token（tokenCountWithEstimation）
- 超过阈值 → 触发 autocompact
- 成功 → post-compact messages 替换
- 失败 → 电路断路器（consecutiveFailures counter）

**USD 预算超出**（QueryEngine.ts:971-1002）：
- loop 外检查 `getTotalCost() >= maxBudgetUsd`
- yield `error_max_budget_usd` → return

**Task budget (Beta)**（query.ts:508-515）：
- 传入 `taskBudget.total`
- Compact 前记录 `taskBudgetRemaining`
- 递传给 API

---

## G. 关键数据结构

### Message 类型族

```typescript
type Message =
  | AssistantMessage
  | UserMessage
  | SystemMessage
  | ProgressMessage
  | AttachmentMessage
  | TombstoneMessage
  | SystemLocalCommandMessage
```

`AssistantMessage`：

```typescript
type AssistantMessage = {
  type: 'assistant'
  uuid: UUID
  message: {
    role: 'assistant'
    content: ContentBlock[]
    stop_reason?: BetaStopReason
    usage?: BetaUsage
  }
  requestId?: string
  apiError?: string
  isApiErrorMessage?: boolean
}
```

### ToolUseContext（Tool.ts:158-300）

```typescript
type ToolUseContext = {
  options: {
    commands: Command[]
    mainLoopModel: string
    tools: Tools
    thinkingConfig: ThinkingConfig
  }
  abortController: AbortController
  readFileState: FileStateCache
  getAppState(): AppState
  setAppState(f): void
  messages: Message[]
  agentId?: AgentId
  queryTracking?: { chainId, depth }
}
```

### AutoCompactTrackingState（services/compact/autoCompact.ts:51-60）

```typescript
type AutoCompactTrackingState = {
  compacted: boolean
  turnCounter: number
  turnId: string
  consecutiveFailures?: number
}
```

---

## H. 关键代码片段

### 1. 主循环（query.ts:307-1728）骨架

```typescript
while (true) {
  // 1. 解构状态
  let { toolUseContext } = state
  const { messages, autoCompactTracking, maxOutputTokensRecoveryCount, ... } = state

  // 2. 技能预取
  const pendingSkillPrefetch = skillPrefetch?.startSkillDiscoveryPrefetch(...)

  // 3. Pre-API：snip + microcompact + autocompact
  const microcompactResult = await deps.microcompact(messagesForQuery, ...)
  const { compactionResult } = await deps.autocompact(...)

  // 4. API 调用
  for await (const message of deps.callModel({...})) {
    if (message.type === 'assistant') {
      msgToolUseBlocks = message.message.content.filter(c => c.type === 'tool_use')
      if (msgToolUseBlocks.length > 0) {
        toolUseBlocks.push(...msgToolUseBlocks)
        needsFollowUp = true
      }
    }
    if (!withheld) yield message
  }

  // 5. 后处理
  if (!needsFollowUp) {
    const stopHookResult = yield* handleStopHooks(...)
    if (stopHookResult.preventContinuation) return { reason: 'stop_hook_prevented' }
    return { reason: 'completed' }
  }

  // 6. 工具执行
  const toolUpdates = streamingToolExecutor
    ? streamingToolExecutor.getRemainingResults()
    : runTools(toolUseBlocks, ...)

  for await (const update of toolUpdates) {
    yield update.message
    toolResults.push(...normalizeMessagesForAPI([update.message]))
  }

  // 7. 附件
  for await (const attachment of getAttachmentMessages(...)) {
    yield attachment
    toolResults.push(attachment)
  }

  // 8. Continue check
  if (maxTurns && nextTurnCount > maxTurns) {
    yield createAttachmentMessage({ type: 'max_turns_reached' })
    return { reason: 'max_turns', turnCount: nextTurnCount }
  }

  // 9. 递归 continue
  state = {
    messages: [...messagesForQuery, ...assistantMessages, ...toolResults],
    turnCount: nextTurnCount,
  }
}
```

### 2. Stop reason 分支（query.ts:1062-1084）

```typescript
if (!needsFollowUp) {
  const lastMessage = assistantMessages.at(-1)
  const isWithheld413 = lastMessage?.type === 'assistant' &&
                        lastMessage.isApiErrorMessage &&
                        isPromptTooLongMessage(lastMessage)
  const isWithheldMedia = mediaRecoveryEnabled &&
                          reactiveCompact?.isWithheldMediaSizeError(lastMessage)

  if (isWithheld413) {
    if (feature('CONTEXT_COLLAPSE') && contextCollapse &&
        state.transition?.reason !== 'collapse_drain_retry') {
      const drained = contextCollapse.recoverFromOverflow(messagesForQuery, ...)
      if (drained.committed > 0) {
        state = { ..., transition: { reason: 'collapse_drain_retry' } }
        continue
      }
    }
  }
  if ((isWithheld413 || isWithheldMedia) && reactiveCompact) {
    const compacted = await reactiveCompact.tryReactiveCompact({...})
    if (compacted) {
      state = { ..., transition: { reason: 'reactive_compact_retry' } }
      continue
    }
  }

  if (isWithheldMaxOutputTokens(lastMessage)) {
    if (capEnabled && maxOutputTokensOverride === undefined) {
      state = { ..., maxOutputTokensOverride: 64000 }
      continue
    }
    if (maxOutputTokensRecoveryCount < 3) {
      state = { ..., messages: [..., recoveryMessage] }
      continue
    }
    yield lastMessage
  }

  return { reason: 'completed' }
}
```

### 3. Fallback model 切换（query.ts:893-953）

```typescript
let attemptWithFallback = true
try {
  while (attemptWithFallback) {
    attemptWithFallback = false
    try {
      for await (const message of deps.callModel({...})) {
        // ...
      }
    } catch (innerError) {
      if (innerError instanceof FallbackTriggeredError && fallbackModel) {
        currentModel = fallbackModel
        attemptWithFallback = true

        yield* yieldMissingToolResultBlocks(assistantMessages, 'Model fallback triggered')
        assistantMessages.length = 0
        toolResults.length = 0
        toolUseBlocks.length = 0
        needsFollowUp = false

        if (streamingToolExecutor) {
          streamingToolExecutor.discard()
          streamingToolExecutor = new StreamingToolExecutor(...)
        }

        toolUseContext.options.mainLoopModel = fallbackModel
        if (process.env.USER_TYPE === 'ant') {
          messagesForQuery = stripSignatureBlocks(messagesForQuery)
        }

        yield createSystemMessage(`Switched to ${fallbackModel}...`)
        continue
      }
      throw innerError
    }
  }
} catch (error) {
  logError(error)
  if (error instanceof ImageSizeError) {
    yield createAssistantAPIErrorMessage({ content: error.message })
    return { reason: 'image_error' }
  }
  yield* yieldMissingToolResultBlocks(assistantMessages, error.message)
  yield createAssistantAPIErrorMessage({ content: error.message })
  return { reason: 'model_error', error }
}
```

---

## I. 未完全理解的机制

1. **Snip Compaction** (`HISTORY_SNIP` feature) — snip / microcompact / autocompact 三者的触发优先级和交互
2. **Context Collapse** (`CONTEXT_COLLAPSE` feature) — `applyCollapsesIfNeeded()` 和 `recoverFromOverflow()` 算法
3. **Reactive Compact** — 何时进入、是否单次或多次、成功条件
4. **Stop Hooks blockingErrors** — 能否混合类型、与 loop 继续的关系（hook 死循环风险）
5. **Tool Summary Generation** — Haiku 异步生成，与流式工具执行的并发控制
6. **Task Budget 跨 compact 累积** — `taskBudgetRemaining` 语义
7. **Message Normalization & API Boundary** — `normalizeMessagesForAPI()` 对 subagent context 的处理
8. **Microcompact Cache Edits** — `pendingCacheEdits` 与延迟边界消息机制
9. **Query Chain Tracking** — depth 何时递增、与 subagent fork 的关系
10. **Memory Prefetch Consumption** — `settledAt` 和 `consumedOnIteration` 状态机

---

## 总结

Claude Code 的 Query Loop 是一个精心设计的多阶段状态机：

1. **优雅降级：** 流式→非流式、主模型→fallback、完整→压缩
2. **多层恢复：** collapse drain → reactive compact → max_tokens escalate/recovery
3. **并发优化：** 流式工具执行、memory/skill 预取、tool use 摘要后台生成
4. **细粒度控制：** maxTurns、token 预算、USD 预算、stop hooks、权限检查
5. **精密 token 管理：** 预压缩计数、微压缩、缓存编辑、snip 释放跟踪
