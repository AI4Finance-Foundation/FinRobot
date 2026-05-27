# Raw Research: Claude Code Tool System (Pillar 2)

**来源**: Explore 子 agent 深度通读 `/Users/zhunihaoyun/Desktop/code/claude-code/src/Tool.ts`、`src/tools/`、`src/services/tools/`
**日期**: 2026-05-12
**用途**: Pillar 2 综合决策文档的事实依据

> 子 agent 原始研究笔记，未经编辑。

---

## A. Tool 抽象定义

**Tool 接口**（`src/Tool.ts:362-695`）核心结构：

1. **必需方法/属性**：
   - `name: string` — tool 唯一标识
   - `call(args, context, canUseTool, parentMessage, onProgress?)` → `Promise<ToolResult<Output>>`
   - `description(input, options)` — 生成 tool 描述文本
   - `inputSchema: Zod<Input>` — Zod schema 定义输入形状
   - `isConcurrencySafe(input: Input): boolean`
   - `checkPermissions(input, context): Promise<PermissionResult>`
   - `prompt(options)` — 生成 tool prompt

2. **输入验证**：使用 **Zod v4 schema**（`Tool.ts:10`，`z.infer<Input>` 推导运行时类型）。MCP tool 也支持原生 JSON Schema via `inputJSONSchema` 属性（`Tool.ts:397`）

3. **输出类型**：
   ```typescript
   ToolResult<T> {
     data: T
     newMessages?: Message[]
     contextModifier?: (context: ToolUseContext) => ToolUseContext
     mcpMeta?: { _meta?, structuredContent? }
   }
   ```
   (`Tool.ts:321-336`)

4. **Stateful vs Pure**：Tool 是 class instance 或 plain object（建议用 `buildTool()` wrapper）。实例可维持状态，但通常是无状态单例。

---

## B. Tool 注册与发现

1. **全局注册表**：
   - `getAllBaseTools()` (`tools.ts:193-251`) — 返回所有 built-in tools（50+ 个）
   - 条件加载：feature flag + `process.env` 控制可用性
   - 工具动态组装：`assembleToolPool(permissionContext, mcpTools)` (`tools.ts:345-367`) 合并 built-in + MCP tools，按名称去重，built-in 优先

2. **运行时发现**：
   - `getTools(permissionContext)` — 返回当前权限下可用的 built-in tools
   - `findToolByName(tools, name)` (`Tool.ts:358-360`) — 按名称或别名查找
   - `toolMatchesName(tool, name)` (`Tool.ts:348-353`) — 支持 aliases

3. **MCP 工具集成**：
   - MCP 工具在 `services/mcp/client.ts:1766-1830` 动态转换为 `Tool` 对象
   - 名称规范化：`mcp__<serverName>__<toolName>`（或 SDK 模式下无前缀）
   - 存储 `mcpInfo: { serverName, toolName }` 用于权限检查

4. **权限过滤**：
   - `filterToolsByDenyRules(tools, permissionContext)` (`tools.ts:262-269`) 移除被 deny rule 覆盖的工具

---

## C. 输入验证

两层验证（`toolExecution.ts:615-733`）：

1. **Schema 验证（Zod）**：
   ```typescript
   const parsedInput = tool.inputSchema.safeParse(input)
   if (!parsedInput.success) {
     // formatZodValidationError → tool_use_error message
   }
   ```

2. **工具特定验证**：
   ```typescript
   const isValidCall = await tool.validateInput?.(parsedInput.data, context)
   if (isValidCall?.result === false) {
     // 返回 { result: false, message, errorCode }
   }
   ```

验证失败 → 写入 `tool_result` block，`is_error: true`。

---

## D. 并发执行

**判断逻辑**（`toolOrchestration.ts:91-116`）：

```typescript
function partitionToolCalls(toolUseMessages, context): Batch[] {
  return toolUseMessages.reduce((acc, toolUse) => {
    const isConcurrencySafe = parsedInput?.success
      ? Boolean(tool?.isConcurrencySafe(parsedInput.data))  // 按 input 判断！
      : false
    if (isConcurrencySafe && acc[acc.length-1]?.isConcurrencySafe) {
      acc[acc.length-1].blocks.push(toolUse)
    } else {
      acc.push({ isConcurrencySafe, blocks: [toolUse] })
    }
    return acc
  }, [])
}
```

**关键点**：
- `isConcurrencySafe(input)` 按**具体 input 值**判断（如 Bash 不同 command 不同安全性）
- Greedy partitioning：连续并发安全工具合并为批

**并发执行**（`toolOrchestration.ts:152-177`）：
```typescript
async function* runToolsConcurrently(blocks, ...) {
  yield* all(
    blocks.map(async function* (toolUse) { ... }),
    getMaxToolUseConcurrency()  // 默认 10（env: CLAUDE_CODE_MAX_TOOL_USE_CONCURRENCY）
  )
}
```

**StreamingToolExecutor**（`services/tools/StreamingToolExecutor.ts`）—— CC 独有：
- `addTool(block)` — 流式接收 tool_use block 时立即加入队列（line 76）
- `processQueue()` — 根据并发条件动态启动（line 140-151）
- 结果缓冲，按到达顺序产出
- "Sibling abort"：一个工具失败时 abort 其并行兄弟

---

## E. Permission Check

**函数签名**（`hooks/useCanUseTool.tsx:27`）：

```typescript
type CanUseToolFn = (
  tool: ToolType,
  input: Input,
  toolUseContext: ToolUseContext,
  assistantMessage: AssistantMessage,
  toolUseID: string,
  forceDecision?: PermissionDecision
) => Promise<PermissionDecision<Input>>
```

**执行流程**（`toolExecution.ts:455-468`）：
```typescript
for await (const update of streamedCheckPermissionsAndCallTool(
  tool, toolUseID, input, context, canUseTool, assistantMessage, ...
)) {
  yield update
}
```

**关键步骤**：
1. `validateInput()` — tool 自定义验证
2. `hasPermissionsToUseTool()` — 全局权限检查：allow/deny rules、permission mode、Bash classifier、hooks
3. Decision 分支：
   - `'allow'` → 直接执行
   - `'ask'` → 显示权限 dialog 或委托给 coordinator
   - `'deny'` → 返回 tool_result, is_error: true, "denied by auto mode"

**Denial tracking**（`utils/permissions/denialTracking.ts`）：累计 denials 达到阈值触发自动 fallback。

**传回模型的拒绝**（`toolExecution.ts:717-732`）：
```typescript
{
  type: 'tool_result',
  content: `<tool_use_error>${msg}</tool_use_error>`,
  is_error: true,
  tool_use_id: toolUseID
}
```

---

## F. Tool Result 包装

**映射协议**（`Tool.ts:557-560`）：
```typescript
mapToolResultToToolResultBlockParam(
  content: Output,
  toolUseID: string
): ToolResultBlockParam
```

**体积管理**（`utils/toolResultStorage.ts`）：
- 每个 tool 声明 `maxResultSizeChars`（如 Read 工具为 `Infinity`）
- 超过阈值 persist 到磁盘，返回预览 + 文件路径
- `MAX_TOOL_RESULT_BYTES` 全局上限
- `MAX_TOOL_RESULTS_PER_MESSAGE_CHARS` 聚合上限
- 预览大小：2000 字节

**多模态结果**：
- 数组形式 `[{ type: 'text', text }, { type: 'image', source: { type: 'base64', ... } }]`
- `mcpMeta` 字段传递 `_meta` 和 `structuredContent`

**进度事件**：`ToolCallProgress<P extends ToolProgressData>` callback（`Tool.ts:338-340`），支持流式进度（如 Bash stdout chunks）

---

## G. Tool Use Context

**完整定义**（`Tool.ts:158-300`）：

```typescript
ToolUseContext {
  options: {
    commands: Command[]
    tools: Tools
    mainLoopModel: string
    mcpClients: MCPServerConnection[]
    agentDefinitions: AgentDefinitionsResult
  }
  abortController: AbortController
  readFileState: FileStateCache
  getAppState(): AppState
  setAppState(f: AppState => AppState): void
  messages: Message[]
  toolDecisions?: Map<toolUseID, { source, decision, timestamp }>
  requestPrompt?: (source, summary?) => (request) => Promise<PromptResponse>
  // 60+ 个字段
}
```

工具访问 messages history via `context.messages`，abort signal via `context.abortController`，state via getter/setter。

**子 agent**：`agentId` + `agentType` 字段区分子 agent 调用。

---

## H. MCP 集成

**统一抽象**（`services/mcp/client.ts:1766-1830`）：

MCP 工具在获取时（`fetchToolsForClient()`）转换为标准 `Tool` 对象：

```typescript
return toolsToProcess.map((tool): Tool => ({
  ...MCPTool,
  name: fullyQualifiedName,  // mcp__server__toolName
  mcpInfo: { serverName, toolName },
  isMcp: true,
  isConcurrencySafe: () => tool.annotations?.readOnlyHint ?? false,
  isReadOnly: () => tool.annotations?.readOnlyHint ?? false,
  call: async (args, context, _, parentMessage, onProgress) => {
    // → callMCPToolWithUrlElicitationRetry → callMCPTool → client.request()
  },
}))
```

**transport**：`client.type === 'connected'` 包含 stdio、SSE、HTTP、WebSocket。

---

## I. 关键代码片段

### 1. Tool interface（`Tool.ts:362-425`）

```typescript
export type Tool<Input extends AnyObject = AnyObject, Output = unknown> = {
  name: string
  aliases?: string[]
  call(args: z.infer<Input>, context: ToolUseContext, ...): Promise<ToolResult<Output>>
  description(...): Promise<string>
  inputSchema: Input
  isConcurrencySafe(input: z.infer<Input>): boolean
  isReadOnly(input: z.infer<Input>): boolean
  checkPermissions(input, context): Promise<PermissionResult>
}
```

### 2. Greedy partitioning（`toolOrchestration.ts:109-115`）

```typescript
if (isConcurrencySafe && acc[acc.length - 1]?.isConcurrencySafe) {
  acc[acc.length - 1]!.blocks.push(toolUse)
} else {
  acc.push({ isConcurrencySafe, blocks: [toolUse] })
}
```

### 3. StreamingToolExecutor 核心（`StreamingToolExecutor.ts:140-151`）

```typescript
private async processQueue(): Promise<void> {
  for (const tool of this.tools) {
    if (tool.status !== 'queued') continue
    if (this.canExecuteTool(tool.isConcurrencySafe)) {
      await this.executeTool(tool)
    } else if (!tool.isConcurrencySafe) break
  }
}
```

### 4. canUseTool 权限检查（`hooks/useCanUseTool.tsx:32-92`）

```typescript
const decisionPromise = forceDecision !== undefined
  ? Promise.resolve(forceDecision)
  : hasPermissionsToUseTool(tool, input, ...)
return decisionPromise.then(result => {
  if (result.behavior === 'allow') { ... }
  else if (result.behavior === 'deny') {
    resolve(result)
  }
  else { /* 'ask' */ ... }
})
```

### 5. Input 验证失败处理（`toolExecution.ts:615-679`）

```typescript
const parsedInput = tool.inputSchema.safeParse(input)
if (!parsedInput.success) {
  const errorContent = formatZodValidationError(tool.name, parsedInput.error)
  return [{ message: createUserMessage({
    content: [{
      type: 'tool_result',
      content: `<tool_use_error>InputValidationError: ${errorContent}</tool_use_error>`,
      is_error: true,
      tool_use_id: toolUseID
    }]
  }) }]
}
```

---

## J. 未完全理解的部分

1. **`all()` generator combinator** 的具体实现（`utils/generators.ts`）— used in `runToolsConcurrently()`
2. **StreamingToolExecutor 错误传播** — "sibling abort" 的确切触发条件
3. **Prompt cache 与 tool schema 的交互** — `assembleToolPool()` 的排序对推理的实际影响
4. **Speculative Bash classifier** — `startSpeculativeClassifierCheck()` 与 async classifiers 的协调
5. **MCP `_meta` 通道完整语义** — `structuredContent` 在 tool result 中的使用案例

---

## 总结

CC Tool 系统特征：
- **Zod 类型化 schema** + 两层验证（schema + tool.validateInput）
- **per-input 并发安全判断**（不是 per-tool）
- **StreamingToolExecutor** 在模型流式响应中并发执行
- **分级权限**（allow / deny / ask）+ rule prefix matching + denial tracking
- **统一 MCP 抽象**：MCP 工具包装为同一 Tool interface
- **结果体积管理**：超阈值 persist 到磁盘 + 预览
- 50+ built-in tools + 任意 MCP tools
