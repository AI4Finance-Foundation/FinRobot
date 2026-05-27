# Raw Research: CC Sub-agent / Task Spawn (Pillar 7)

**来源**: Explore 子 agent 通读 CC `src/tools/AgentTool/`、`src/utils/forkedAgent.ts`、`src/services/AgentSummary/`
**日期**: 2026-05-12

---

## A. Spawn API

**工具名**: `Agent`（别名 `agent`）—— `src/tools/AgentTool/AgentTool.tsx:226`

**入参**: description, prompt, subagent_type, model, run_in_background, name, team_name, mode, isolation, cwd

**协议**: 4 条执行路径
- Sync：`status='completed'`，阻塞父 agent
- Async：`status='async_launched'`，立即返回，后台执行
- Teammate：`status='teammate_spawned'`，tmux / in-process 独立
- Remote：`status='remote_launched'`，CCR 远程执行

---

## B. AgentDefinition

字段（`src/tools/AgentTool/loadAgentsDir.ts`）：
- `agentType` / `getSystemPrompt(context)` / `model`（'opus'/'sonnet'/'haiku'/'inherit'）
- `tools` / `maxTurns` / `permissionMode`
- `background` / `isolation` / `effort` / `omitClaudeMd`
- `mcpServers` / `hooks` / `skills` / `memory` / `requiredMcpServers` / `color`

**继承**:
- Model: `'inherit'` → 继承父
- Tools: fork 路径继承完整工具数组；普通路径用 worker permissionMode 重新组装
- Permission: agent 定义或参数覆盖
- Thinking: fork 继承父，普通禁用

---

## C. Context 隔离 vs 继承

**父 messages 传递**:
- Fork: `buildForkedMessages(prompt, assistantMessage)` —— 克隆父完整 assistant message + placeholder tool_results + per-child 指令；目的字节匹配实现 prompt cache 命中
- 普通: `[createUserMessage({ content: prompt })]`

**ToolUseContext fork** (`createSubagentContext` `forkedAgent.ts:345-462`):

| 字段 | 隔离 | 共享选项 |
|---|---|---|
| readFileState | 克隆 | 无 |
| abortController | 新建 link 父 | `shareAbortController` |
| getAppState | 包装 | `getAppState` 覆盖 |
| setAppState | no-op | `shareSetAppState` |
| messages | 覆盖 | `messages` 覆盖 |
| agentId | 新生成 | `agentId` 覆盖 |

**abort 链接**:
- Async: 新建独立 controller
- Sync: 共享父 controller
- Fork: `createChildAbortController(parentController)` 链接

---

## D. 执行流程

`runAgent` 调用栈 (`runAgent.ts:248-860`):
```
runAgent({agentDefinition, promptMessages, toolUseContext, ...})
  ├─ resolveAgentModel()
  ├─ createAgentId()
  ├─ setupAgentMcpServers()
  ├─ buildAgentSystemPrompt()
  ├─ createSubagentContext()
  ├─ registerFrontmatterHooks()
  ├─ preloadSkills()
  ├─ recordSidechainTranscript() (初始消息)
  └─ for await (query({...})) {
       ├─ recordSidechainTranscript([msg], parent_uuid)
       ├─ yield message
       └─ on_error: cleanup hooks/MCP/cache/todolists
     }
```

**同一 query()**: 所有 agent 用同一 `query()` 入口；差异在 systemPrompt / tools / messages / toolUseContext

**queryTracking** (`forkedAgent.ts:453-455`):
- 父: `{ chainId: uuid(), depth: 0 }`
- 子: `{ chainId: parentChainId, depth: parent.depth + 1 }`（主路径继承）
- BUT fork 路径 `chainId: randomUUID()`（不继承，文件 forkedAgent.ts:452-455）—— **mini-ADR-2 已记录此矛盾**

**并发 vs 串行**:
- Async: `void runWithAgentContext(...runAsyncAgentLifecycle(...))` 立即返回，事件循环并发
- Sync: `await for (const msg of runAgent(...))` 阻塞 while
- Teammate: 独立 tmux/in-process + mailbox 通信

---

## E. 结果回收

**AgentSummary** (`agentSummary.ts:46-179`):
- 定期 30s fork 子 query
- 生成 3-5 字现在时进度（"Reading file X"）
- 共享 prompt cache（`CacheSafeParams`）
- 无工具：`canUseTool` 返 deny
- 存储：`updateAgentSummary(taskId, summaryText, setAppState)`

**写回父 messages**:
- Sync: 通过 `runAgent()` AsyncGenerator 流回
- Async: 异步记录到 transcript + AgentProgress 更新
- Transcript 链式：`recordSidechainTranscript([msg], agentId, lastRecordedUuid)`

**失败处理**:
- Sync: try-finally 捕获，清理 MCP/hooks/cache
- Async: `failAsyncAgent()` → failed 状态 + UI 通知
- Abort: AbortError → `killAsyncAgent(taskId)`

---

## F. 关键代码

| 功能 | 文件:行 |
|---|---|
| AgentTool 入口 | `AgentTool.tsx:239-250` |
| runAgent 主体 | `runAgent.ts:248-860` |
| createSubagentContext | `forkedAgent.ts:345-462` |
| buildForkedMessages | `forkSubagent.ts:107-169` |
| spawnTeammate | `spawnMultiAgent.ts:1088-1093` |
| runForkedAgent | `forkedAgent.ts:489-626` |
| startAgentSummarization | `agentSummary.ts:46-179` |

---

## G. 未理解

1. `renderedSystemPrompt` 缓存机制
2. `querySource` 路由逻辑
3. worktree 隔离的 git 安全性
4. `reconstructForSubagentResume` 的 cache 稳定性
5. `runWithWorkload` ALS 上下文传播

---

## 总结

CC 4 执行路径（fork / async / sync / teammate），chain_id 继承（主路径）+ 矛盾的 fork 新建（fork 路径），State 通过 createSubagentContext 灵活隔离。Prompt cache 通过 CacheSafeParams 字节匹配实现共享。
